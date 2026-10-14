"""Copy only declared checker inputs into host-owned observation storage."""

from pathlib import Path, PurePosixPath
import shutil
from uuid import uuid4

from .build_types import RequestValidationError


def snapshot_verifier(store, plan, scope):
    """Resource-mode preparation snapshots files, never product/control state.

    Explicit helper files keep the scope reviewable without recursively hashing
    a checkout. The snapshot is used even if checker source lives in the product.
    """
    source = Path(scope["verification_root"]).resolve(strict=True)
    names = {arg.removeprefix("verifier://") for task in plan["workpacks"]
             for check in task["verification"] for arg in check["argv"][1:]
             if arg.startswith("verifier://")}
    names.update(scope["verification_resources"].get("checker_files", []))
    files = {}
    for name in names:
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or ".." in path.parts or "\\" in name
                or str(path) != name):
            raise RequestValidationError("checker file must be canonical and relative")
        resolved = (source / name).resolve(strict=True)
        if not resolved.is_relative_to(source) or not resolved.is_file():
            raise RequestValidationError("checker files must be regular files inside verifier source")
        files[name] = resolved
    target = store.database_path.with_suffix(".verifiers") / ("VERIFIER-" + uuid4().hex)
    workspace = Path(scope["workspace_root"]).resolve()
    resource_root = Path(scope["verification_resources"]["root"]).resolve()
    if target.is_relative_to(workspace) or target.is_relative_to(resource_root):
        raise RequestValidationError("checker snapshot must be host-owned, outside writable resources")
    try:
        target.mkdir(parents=True)
        for name, path in files.items():
            destination = target / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            destination.chmod(0o444 | (path.stat().st_mode & 0o111))
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return {"source_root": str(source), "runtime_root": str(target), "files": sorted(files),
            "guarantee": "FUNCTIONAL_CHECKER_SNAPSHOT_NOT_ADVERSARIAL_PROCESS_SEPARATION"}
