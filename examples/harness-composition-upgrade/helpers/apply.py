"""Apply explicit ordinary-file intents in a cooperating single-writer target.

Every affected file must match expected or desired state before any writes.
The caller-declared --result path can be replaced on resume; the report is
diagnostic, not a Harness receipt. Partial application is not rolled back.
"""

import argparse
import importlib.util
from pathlib import Path
import sys

_spec = importlib.util.spec_from_file_location("r3_file_states", Path(__file__).with_name("file_states.py"))
fs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fs)


def prepare(manifest_path, target, result):
    manifest, data = fs.read_manifest(manifest_path)
    paths = fs.validate_paths(data["files"])
    target = Path(target).absolute()
    if target.is_symlink() or not target.is_dir():
        raise fs.PlanError("target must be an existing directory")
    target = target.resolve()
    result_relative = fs.relative_path(result)
    if any(result_relative == p or result_relative in p.parents or p in result_relative.parents for p in paths):
        raise fs.PlanError("result overlaps a declared file path")
    fs.validate_target_paths(target, [*paths, result_relative])
    result_path = fs.beneath(target, result)
    prepared = []
    for item in data["files"]:
        action = item.get("action")
        if action not in ("create", "update", "remove", "leave-unmanaged"):
            raise fs.PlanError("unknown file action")
        if "expected" not in item or "desired" not in item:
            raise fs.PlanError("each apply entry needs expected and desired")
        expected, source_old = fs.load_state(item["expected"], manifest.parent)
        desired, source_new = fs.load_state(item["desired"], manifest.parent)
        for source in (source_old, source_new):
            if source is not None and fs.within_existing_root(target, source):
                raise fs.PlanError("payload source must remain outside the writable target")
        if action == "create" and (expected is not None or desired is None):
            raise fs.PlanError("create requires missing expected and present desired")
        if action == "update" and (expected is None or desired is None):
            raise fs.PlanError("update requires present expected and desired")
        if action == "remove" and (expected is None or desired is not None):
            raise fs.PlanError("remove requires present expected and missing desired")
        path = fs.beneath(target, item["path"])
        current = fs.read_current(path)
        if action != "leave-unmanaged" and current != expected and current != desired:
            raise fs.PlanError("target differs from expected and desired: " + item["path"])
        prepared.append((item, expected, desired))
    if fs.within_existing_root(target, manifest.resolve()):
        raise fs.PlanError("apply manifest must remain outside the writable target")
    return manifest, target, result_path, prepared


def apply(manifest_path, target, result):
    manifest, target, result_path, prepared = prepare(manifest_path, target, result)
    report = {"format_version": 1, "kind": "r3-apply-diagnostic", "manifest": str(manifest),
              "target": str(target), "status": "INCOMPLETE", "files": []}
    try:
        for item, expected, desired in prepared:
            path = fs.beneath(target, item["path"])
            current = fs.read_current(path)
            if item["action"] == "leave-unmanaged":
                status = "LEFT_UNMANAGED"
            elif current == desired:
                status = "ALREADY_DESIRED"
            else:
                if current != expected:
                    raise fs.PlanError("target changed after preflight: " + item["path"])
                if desired is None:
                    path.unlink()
                else:
                    mode = path.stat().st_mode if current is not None else None
                    fs.atomic_write(path, desired[0], desired[1], mode)
                status = "APPLIED"
            row = {"path": item["path"], "action": item["action"], "status": status}
            report["files"].append(row)
            print(fs.json_bytes(row).decode(), end="", flush=True)
        report["status"] = "APPLIED"
    except (OSError, fs.PlanError) as exc:
        report["error"] = str(exc)
        # Failure can happen after earlier files changed; this is not rollback.
        raise
    finally:
        # Even an incomplete report is diagnostic only. A new invocation may
        # compare target state and resume only after the caller permits it.
        fs.beneath(target, str(result_path.relative_to(target)))
        fs.atomic_write(result_path, fs.json_bytes(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--target", default=".")
    parser.add_argument("--result", required=True)
    args = parser.parse_args()
    try:
        report = apply(args.manifest, args.target, args.result)
    except (OSError, fs.PlanError) as exc:
        print("apply failed: " + str(exc), file=sys.stderr)
        return 1
    print(fs.json_bytes(report).decode(), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
