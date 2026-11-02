"""Copy only declared checker inputs into host-owned observation storage."""

from pathlib import Path, PurePosixPath
import shutil
from uuid import uuid4

from .build_types import RequestValidationError
from .build_artifacts import file_identity, relative_path
from .verification_resources import checker_files_for_case


def _case_selections(plan, config):
    cases = {}
    for task in plan["workpacks"]:
        for check in task["verification"]:
            choices = cases.setdefault(check["case_id"], [])
            selected = checker_files_for_case(config, check)
            if selected not in choices:
                choices.append(selected)
    return {case: sorted(choices) for case, choices in cases.items()}


def snapshot_verifier(store, plan, scope):
    """Resource-mode preparation snapshots files, never product/control state.

    Explicit helper files keep the scope reviewable without recursively hashing
    a checkout. The snapshot is used even if checker source lives in the product.
    """
    source = Path(scope["verification_root"]).resolve(strict=True)
    config = scope["verification_resources"]
    checks = [check for task in plan["workpacks"] for check in task["verification"]]
    # Legacy snapshot callers need no Case identity until they opt into views.
    names = set(config.get("checker_files", []))
    names.update(name for check in checks for name in checker_files_for_case(config, check))
    cases = _case_selections(plan, config) if "case_checker_files" in config else {}
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
    views_root = target.with_name("CASES-" + target.name)
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
        views = {}
        if "case_checker_files" in config:
            index = 0
            for case_id, choices in sorted(cases.items()):
                variants = []
                for selected in choices:
                    view = views_root / str(index)
                    index += 1
                    view.mkdir(parents=True)
                    for name in selected:
                        destination = view / name
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        # Copy the captured bytes, never reread a changing source.
                        shutil.copyfile(target / name, destination)
                        destination.chmod((target / name).stat().st_mode & 0o777)
                    variants.append({"runtime_root": str(view), "files": selected})
                # A Case may legally appear in multiple tasks with different entrypoints.
                views[case_id] = variants[0] if len(variants) == 1 else variants
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        shutil.rmtree(views_root, ignore_errors=True)
        raise
    return {"source_root": str(source), "runtime_root": str(target), "files": sorted(files),
            **({"case_views": views} if "case_checker_files" in config else {}),
            "guarantee": "FUNCTIONAL_CHECKER_SNAPSHOT_NOT_ADVERSARIAL_PROCESS_SEPARATION"}


def case_verifier_binding(prepared, check):
    """Select a frozen view without allocating resources or changing old reports."""
    scope = prepared["scope"]
    config = scope.get("verification_resources", {})
    if "case_checker_files" not in config:
        return scope["verification_root"], prepared["verifier_files"]
    names = checker_files_for_case(config, check)
    views = prepared.get("verifier_source", {}).get("case_views", {})
    choices = views.get(check["case_id"])
    choices = choices if isinstance(choices, list) else [choices]
    matches = [view for view in choices if isinstance(view, dict) and view.get("files") == names]
    if len(matches) != 1:
        raise RequestValidationError("Case checker view is missing or differs from declared files")
    view = matches[0]
    root = Path(view["runtime_root"])
    expected = Path(scope["verification_root"]).with_name("CASES-" + Path(scope["verification_root"]).name)
    if root.parent != expected or root.resolve(strict=True) != root or not root.is_dir():
        raise RequestValidationError("Case checker view binding changed")
    return str(root), {name: prepared["verifier_files"][name] for name in names}


def validate_case_views(prepared, plan):
    if "case_checker_files" not in prepared["scope"].get("verification_resources", {}):
        return
    cases = [check for task in plan["workpacks"] for check in task["verification"]]
    if set(prepared.get("verifier_source", {}).get("case_views", {})) != {c["case_id"] for c in cases}:
        raise RequestValidationError("Case checker views do not match the Plan")
    expected = _case_selections(plan, prepared["scope"]["verification_resources"])
    for case_id, selections in expected.items():
        variants = prepared["verifier_source"]["case_views"][case_id]
        variants = variants if isinstance(variants, list) else [variants]
        if (not all(isinstance(view, dict) and isinstance(view.get("files"), list) for view in variants)
                or len(variants) != len(selections)
                or any(view["files"] not in selections for view in variants)):
            raise RequestValidationError("Case checker variants do not match the Plan")
    for check in cases:
        root, files = case_verifier_binding(prepared, check)
        for name, identity in files.items():
            if file_identity(relative_path(Path(root), name)) != identity:
                raise RequestValidationError("independent Case checker bytes changed")
