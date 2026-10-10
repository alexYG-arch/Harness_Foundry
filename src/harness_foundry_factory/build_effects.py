"""Host observations of explicitly scoped local files, not another authority.

No external-state or whole-machine guarantee. No rollback. The caller records
the baseline and verdict in its existing revision event stream before acceptance.
"""

import hashlib
from pathlib import Path

from .build_types import RequestValidationError


def snapshot_effects(workspace, write_roots, contract):
    workspace = Path(workspace).resolve()
    rows = {}

    def visit(path):
        # Do not follow symlinked ancestors or recursively inspect other roots.
        relative = path.relative_to(workspace)
        if any(parent.is_symlink() for parent in [path, *path.parents] if parent != workspace and parent.is_relative_to(workspace)):
            raise RequestValidationError("effect observation cannot follow symlinks: " + str(relative))
        if not path.exists():
            rows[str(relative)] = {"kind": "absent"}
        elif path.is_dir():
            rows[str(relative)] = {"kind": "directory"}
            for child in sorted(path.iterdir()):
                visit(child)
        elif path.is_file():
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            rows[str(relative)] = {"kind": "file", "size": path.stat().st_size,
                                   "sha256": digest, "mode": path.stat().st_mode & 0o777}
        else:
            raise RequestValidationError("unsupported effect object: " + str(relative))

    for relative in write_roots:
        visit(workspace / relative)
    for relative in contract["must_preserve"]:
        path = workspace / relative
        if path.is_dir():
            raise RequestValidationError("must_preserve requires named files, not directories")
        visit(path)
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
