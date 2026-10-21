"""Compare actual C/G/N states and write inspectable candidate inputs.

Exit 0: all entries resolved; exit 2: conflict or missing baseline; exit 1: bad
input or preparation failure. candidate.json is diagnostic, not acceptance.
"""

import argparse
import importlib.util
from pathlib import Path
import sys

# Explicit adjacent dependency works under `python -I -B` without PYTHONPATH.
_spec = importlib.util.spec_from_file_location("r3_file_states", Path(__file__).with_name("file_states.py"))
fs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fs)


def merge(inputs, output):
    manifest, data = fs.read_manifest(inputs)
    fs.validate_paths(data["files"])
    prepared = []
    for item in data["files"]:
        if not all(key in item for key in ("C", "G", "N")):
            raise fs.PlanError("each merge entry needs C, G and N")
        owners = item.get("owners", [])
        if not isinstance(owners, list) or not all(isinstance(x, str) for x in owners):
            raise fs.PlanError("owners must be a list of strings")
        states = {}
        sources = {}
        for key in ("C", "G", "N"):
            if key == "G" and item[key] is None:
                states[key], sources[key] = None, None
            else:
                states[key], sources[key] = fs.load_state(item[key], manifest.parent)
        unknown = item["G"] is None
        if unknown:
            status, selected = "PROJECT_INCREMENTAL_REQUIRED", None
        elif states["C"] == states["G"]:
            status, selected = "RESOLVED", "N"
        elif states["N"] == states["G"]:
            status, selected = "RESOLVED", "C"
        elif states["C"] == states["N"]:
            status, selected = "RESOLVED", "C"
        else:
            status, selected = "CONFLICT", None
        prepared.append((item, states, sources, status, selected))

    output = Path(output).absolute()
    if output.is_symlink() or output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise fs.PlanError("candidate output must be a new or empty directory")
    if output == manifest.parent or output in manifest.parents:
        raise fs.PlanError("candidate output cannot contain its input manifest")
    output.mkdir(parents=True, exist_ok=True)
    report = {"format_version": 1, "kind": "r3-candidate-diagnostic", "inputs_manifest": str(manifest), "files": []}
    for index, (item, states, sources, status, selected) in enumerate(prepared):
        copies = {}
        source_refs = {}
        for key in ("C", "G", "N"):
            state = states[key]
            source_refs[key] = str(sources[key]) if sources[key] else None
            if key == "G" and item[key] is None:
                copies[key] = None
            elif state is None:
                copies[key] = {"missing": True}
            else:
                name = "payloads/{:04d}-{}.bin".format(index, key)
                fs.atomic_write(output / name, state[0], state[1])
                copies[key] = {"file": name, "executable": state[1]}
        report["files"].append({"path": item["path"], "owners": item.get("owners", []),
                                "status": status, "source_refs": source_refs, "inputs": copies,
                                "selected": selected, "resolved": copies[selected] if selected else None})
    statuses = {item["status"] for item in report["files"]}
    report["status"] = ("CONFLICT" if "CONFLICT" in statuses else
                        "PROJECT_INCREMENTAL_REQUIRED" if "PROJECT_INCREMENTAL_REQUIRED" in statuses else "READY")
    fs.atomic_write(output / "candidate.json", fs.json_bytes(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        report = merge(args.inputs, args.output)
    except (OSError, fs.PlanError) as exc:
        print("merge failed: " + str(exc), file=sys.stderr)
        return 1
    print(fs.json_bytes(report).decode(), end="")
    return 0 if report["status"] == "READY" else 2


if __name__ == "__main__":
    sys.exit(main())
