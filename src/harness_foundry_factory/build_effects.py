"""Host observations of explicitly scoped local files, not another authority.

No external-state or whole-machine guarantee. No rollback. The caller records
the baseline and verdict in its existing revision event stream before acceptance.
"""

import hashlib
import os
from pathlib import Path, PurePosixPath
import stat

from .build_types import RequestValidationError


def effect_path(workspace, value):
    """Name an observed directory entry without granting its link target."""
    if not isinstance(value, str) or not value:
        raise RequestValidationError("relative path must be text")
    relative = PurePosixPath(value)
    if (relative.is_absolute() or ".." in relative.parts or "\\" in value
            or relative.as_posix() != value):
        raise RequestValidationError("path must be canonical and relative")
    workspace = Path(workspace)
    path = workspace / value
    for parent in reversed(path.parents):
        if parent == workspace or not parent.is_relative_to(workspace):
            continue
        try:
            mode = parent.lstat().st_mode
        except FileNotFoundError:
            # A normal first build may create missing parent directories.
            break
        if stat.S_ISLNK(mode):
            raise RequestValidationError("effect observation cannot follow symlink ancestors: " + value)
        if not stat.S_ISDIR(mode):
            raise RequestValidationError("effect ancestor must be a directory: " + value)
    return path


def snapshot_effects(workspace, write_roots, contract):
    workspace = Path(workspace).resolve()
    rows = {}

    def visit(path, *, preserved=False):
        relative = str(path.relative_to(workspace))
        path = effect_path(workspace, relative)
        try:
            info = path.lstat()
        except FileNotFoundError:
            rows[relative] = {"kind": "absent"}
            return
        if stat.S_ISLNK(info.st_mode):
            rows[relative] = {"kind": "symlink", "target": os.readlink(path)}
        elif stat.S_ISDIR(info.st_mode):
            if preserved:
                raise RequestValidationError("must_preserve requires named files, not directories")
            rows[relative] = {"kind": "directory"}
            for child in sorted(path.iterdir()):
                visit(child)
        elif stat.S_ISREG(info.st_mode):
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            rows[relative] = {"kind": "file", "size": info.st_size,
                              "sha256": digest, "mode": info.st_mode & 0o777}
        else:
            raise RequestValidationError("unsupported effect object: " + relative)

    for relative in write_roots:
        visit(workspace / relative)
    for relative in contract["must_preserve"]:
        visit(workspace / relative, preserved=True)
    return rows


def compare_effects(before, after, contract):
    changed = sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))
    allowed = set(contract["allowed"])
    parent_dirs = {str(parent) for path in allowed for parent in Path(path).parents}
    violations = []
    for path in changed:
        if path in contract["must_preserve"]:
            violations.append({"path": path, "reason": "PRESERVED_FILE_CHANGED"})
        elif path not in allowed and not (path in parent_dirs and after.get(path, {}).get("kind") == "directory"
                                         and before.get(path, {}).get("kind", "absent") == "absent"):
            violations.append({"path": path, "reason": "UNDECLARED_FILE_EFFECT"})
    missing = [path for path in contract["required"] if after.get(path, {}).get("kind") != "file"]
    return {"status": "VIOLATION" if violations else "MISSING_REQUIRED" if missing else "PASS",
            "coverage": "DECLARED_WRITE_ROOTS_AND_NAMED_PRESERVED_FILES_ONLY",
            "changed_paths": changed, "violations": violations, "missing_required": missing,
            "external_effects_verified": False, "rollback_performed": False}


def environment_probe_argv(environment):
    """Run under the declared interpreter, cwd and existing read-only receiver."""
    import json
    script = """import importlib.util,json,os,sys
from pathlib import Path
request=json.loads(sys.argv[1])
missing_modules=[name for name in request['modules'] if importlib.util.find_spec(name) is None]
missing_paths=[name for name in request['paths'] if not Path(name).exists() or not os.access(name,os.R_OK)]
print(json.dumps({'status':'PASS' if not (missing_modules or missing_paths) else 'ENVIRONMENT_BLOCKED',
 'missing_modules':missing_modules,'missing_paths':missing_paths,'python':sys.executable,'cwd':str(Path.cwd())}))
raise SystemExit(bool(missing_modules or missing_paths))
"""
    return [environment["python"], "-I", "-B", "-c", script, json.dumps(environment)]
