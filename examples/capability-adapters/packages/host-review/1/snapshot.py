"""Copy explicitly named host evidence without running or accepting the task."""

import argparse
import json
from pathlib import Path, PurePosixPath
import sys


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def text(value):
    return isinstance(value, str) and bool(value.strip())


def relative(value):
    if (not text(value) or PurePosixPath(value).is_absolute() or "\\" in value
            or any(part in ("", ".", "..") for part in value.split("/"))):
        raise ValueError("expected a named relative file")
    return value


def ordinary(root, name):
    current = Path(root)
    for part in relative(name).split("/"):
        current /= part
        if current.is_symlink():
            raise ValueError("snapshot inputs must be ordinary files: " + name)
    if not current.is_file():
        raise ValueError("missing snapshot input: " + name)
    return current


def validate_task(task):
    if not isinstance(task, dict) or not text(task.get("task_id")):
        raise ValueError("task_id must name this project task")
    relative(task.get("workflow"))
    inputs = task.get("inputs")
    if not isinstance(inputs, dict) or any(not text(key) for key in inputs):
        raise ValueError("inputs must map named project inputs to files")
    for name in inputs.values():
        relative(name)
    outputs = task.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise ValueError("outputs must declare the project result files")
    for name in outputs:
        relative(name)
    if len(outputs) != len(set(outputs)):
        raise ValueError("duplicate declared output")
    host_tools = task.get("host_tools")
    if not isinstance(host_tools, list) or not host_tools or any(not text(item) for item in host_tools):
        raise ValueError("host_tools must describe the actual cooperating host interfaces")


def validate_observations(review):
    if not isinstance(review, dict) or not text(review.get("reviewer")):
        raise ValueError("name the actual independent host reviewer")
    rows = review.get("observations")
    if not isinstance(rows, list):
        raise ValueError("observations must be the supplied independent host findings")
    ids = set()
    references = []
    for row in rows:
        if not isinstance(row, dict) or not text(row.get("id")) or row["id"] in ids:
            raise ValueError("observations need unique nonempty ids")
        ids.add(row["id"])
        if row.get("result") not in ("PASS", "FAIL", "UNKNOWN", "NOT_RUN") or not text(row.get("reason")):
            raise ValueError("observation result or reason is incomplete")
        refs = row.get("evidence_refs")
        if not isinstance(refs, list):
            raise ValueError("observation evidence_refs must be a list")
        for ref in refs:
            relative(ref)
            if ref not in references:
                references.append(ref)
    return rows, references


def prepare(task_path, outputs, evidence_root, review, destination):
    task_path = Path(task_path).resolve(strict=True)
    task = read_json(task_path)
    validate_task(task)
    rows, references = validate_observations(review)
    task_root, outputs, evidence_root = task_path.parent, Path(outputs), Path(evidence_root)
    destination = Path(destination)
    resolved_destination = destination.resolve()
    # This helper only creates a new evidence directory, outside the things it copies.
    for source_root in (task_root, outputs, evidence_root):
        root = source_root.resolve()
        if resolved_destination.is_relative_to(root) or root.is_relative_to(resolved_destination):
            raise ValueError("snapshot destination must be separate from task, outputs and evidence roots")
    payloads = {"task/task.json": task_path.read_bytes(),
                "task/workflow": ordinary(task_root, task["workflow"]).read_bytes()}
    input_files = {}
    for index, (key, name) in enumerate(task["inputs"].items()):
        target = "inputs/" + str(index)
        payloads[target] = ordinary(task_root, name).read_bytes()
        input_files[key] = target
    for name in task["outputs"]:
        payloads["outputs/" + name] = ordinary(outputs, name).read_bytes()
    for ref in references:
        payloads["evidence/" + ref] = ordinary(evidence_root, ref).read_bytes()
    document = {"task_id": task["task_id"], "input_files": input_files,
                "reviewer": review["reviewer"],
                "observations": [dict(row, evidence_refs=["evidence/" + ref for ref in row["evidence_refs"]])
                                 for row in rows]}
    payloads["snapshot.json"] = (json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    # Complete the reads before writing. I/O failure is retained, never retried here.
    destination.mkdir(parents=True, exist_ok=False)
    for name, data in payloads.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return {"status": "HOST_SNAPSHOT_COPIED", "task_id": task["task_id"], "accepted": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("task", "outputs", "evidence-root", "review", "destination"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.task, args.outputs, args.evidence_root, read_json(args.review), args.destination)
    except (OSError, ValueError, TypeError, UnicodeError) as error:
        print("host-review snapshot: " + str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
