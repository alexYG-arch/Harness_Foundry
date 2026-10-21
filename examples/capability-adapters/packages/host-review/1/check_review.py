"""Check protected byte bindings and project-owned independent observations.

This single-file checker does not import the producer, operate a host tool,
authenticate a reviewer's identity, or decide the truth of screenshots/prose.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys


class IncompleteReview(ValueError):
    def __init__(self, errors, findings):
        super().__init__("; ".join(errors))
        self.findings = findings


def text(value):
    return isinstance(value, str) and bool(value.strip())


def parse_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(data.decode("utf-8"), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def read_json(path):
    return parse_json(Path(path).read_bytes())


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
            raise ValueError("checking inputs must be ordinary files: " + name)
    if not current.is_file():
        raise ValueError("missing checking input: " + name)
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


def inspect(args, files=None):
    # Bind only bytes this inspection actually consumes. Reused evidence and
    # task bytes are read once, so the observation hash describes the check.
    payloads = {}
    def read(path, key):
        if key not in payloads:
            if files is not None:
                files[key] = None
            payloads[key] = path.read_bytes()
            if files is not None:
                files[key] = hashlib.sha256(payloads[key]).hexdigest()
        return payloads[key]

    # Resolve the task file itself before choosing its relative dependencies;
    # a legitimate parent alias must not redirect reads to a public sibling.
    task_root = args.task.resolve(strict=True).parent
    snapshot_file = args.snapshot.resolve(strict=True)
    snapshot = snapshot_file.parent
    root = os.environ.get("FOUNDRY_VERIFIER_ROOT")
    if root:
        protected = Path(root).resolve(strict=True)
        for path in (Path(__file__), args.task, args.expectation, snapshot_file):
            if not path.resolve(strict=True).is_relative_to(protected):
                raise ValueError("checker, task, expectation and snapshot must use the protected verifier copy")
        actual = args.outputs.resolve()
        if actual.is_relative_to(protected) or protected.is_relative_to(actual):
            raise ValueError("current outputs must be separate from protected checking inputs")
    task = parse_json(read(args.task, "task"))
    expected = parse_json(read(args.expectation, "expectation"))
    validate_task(task)
    if not isinstance(expected, dict) or expected.get("task_id") != task["task_id"]:
        raise ValueError("independent expectation belongs to another task")
    required = expected.get("required_observations")
    if (not isinstance(required, list) or not required or any(not text(key) for key in required)
            or len(required) != len(set(required))):
        raise ValueError("independent expectation must name unique required observations")
    if snapshot_file.name != "snapshot.json":
        raise ValueError("--snapshot must name the captured snapshot.json file")
    captured = parse_json(read(snapshot_file, "snapshot"))
    if not isinstance(captured, dict) or captured.get("task_id") != task["task_id"] or not text(captured.get("reviewer")):
        raise ValueError("snapshot task or independent reviewer is incomplete")
    if read(ordinary(snapshot, "task/task.json"), "snapshot:task/task.json") != read(args.task, "task"):
        raise ValueError("snapshot is stale for the declared project task")
    if read(ordinary(snapshot, "task/workflow"), "snapshot:task/workflow") != read(ordinary(task_root, task["workflow"]), "workflow"):
        raise ValueError("snapshot is stale for the selected workflow")
    input_files = {key: "inputs/" + str(index) for index, key in enumerate(task["inputs"])}
    if captured.get("input_files") != input_files:
        raise ValueError("snapshot input mapping differs from the declared inputs")
    for key, name in task["inputs"].items():
        if read(ordinary(snapshot, input_files[key]), "snapshot:" + input_files[key]) != read(ordinary(task_root, name), "input:" + key):
            raise ValueError("snapshot is stale for project input: " + key)
    for name in task["outputs"]:
        if read(ordinary(snapshot, "outputs/" + name), "snapshot:outputs/" + name) != read(ordinary(args.outputs, name), "output:" + name):
            raise ValueError("snapshot is stale for current output: " + name)
    rows = captured.get("observations")
    if not isinstance(rows, list):
        raise ValueError("snapshot observations are incomplete")
    ids, failures, errors = set(), [], []
    for row in rows:
        try:
            if not isinstance(row, dict) or not text(row.get("id")) or row["id"] in ids:
                raise ValueError("observations need unique nonempty ids")
            ids.add(row["id"])
            if row.get("result") not in ("PASS", "FAIL") or not text(row.get("reason")):
                raise ValueError("host observation is unfinished: " + row["id"])
            refs = row.get("evidence_refs")
            if not isinstance(refs, list) or not refs:
                raise ValueError("host observation has no actual evidence: " + row["id"])
            for ref in refs:
                relative(ref)
                if not ref.startswith("evidence/") or not read(ordinary(snapshot, ref), "snapshot:" + ref):
                    raise ValueError("host observation has no actual evidence: " + row["id"])
        except (OSError, ValueError, KeyError, TypeError, UnicodeError) as error:
            errors.append(str(error))
            continue
        if row["result"] == "FAIL":
            failures.append(row["id"] + ": " + row["reason"])
    if not set(required).issubset(ids):
        errors.append("host observations do not cover the independent project requirements")
    # Additional supplied FAIL observations remain findings; the required list
    # is never derived from the review itself. Incomplete supplied rows are ERROR,
    # but cannot erase valid findings in other rows or prevent their inspection.
    if errors:
        raise IncompleteReview(errors, failures)
    return failures


def check(args):
    files = dict.fromkeys(("task", "workflow", "snapshot", "expectation"))
    report = {"schema_version": "1.0", "case_id": os.environ.get("FOUNDRY_CASE_ID", "standalone"),
              "command_id": os.environ.get("FOUNDRY_COMMAND_ID", "standalone"),
              "status": "CHECKS_FAILED", "checks": [], "errors": [],
              "observation_binding": {"format": "host-review", "files": files},
              "scope": "Byte-bound supplied independent host observations only; semantic truth and controller acceptance remain external."}
    try:
        failures = inspect(args, files)
    except IncompleteReview as error:
        report["checks"].append({"id": "host-review", "status": "ERROR"})
        report["errors"].append(str(error))
        report["findings"] = error.findings
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as error:
        report["checks"].append({"id": "host-review", "status": "ERROR"})
        report["errors"].append(str(error))
    else:
        if failures:
            report["checks"].append({"id": "host-review", "status": "FAIL"})
            report["failure_kind"] = "ASSERTION"
            report["findings"] = failures
            report["diagnostic"] = "; ".join(failures)
        else:
            report["status"] = "CHECKS_PASS"
            report["checks"].append({"id": "host-review", "status": "PASS"})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("task", "expectation", "snapshot", "outputs"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report_path = args.report
    if report_path is None:
        if "FOUNDRY_REPORT_DIR" not in os.environ:
            parser.error("--report or FOUNDRY_REPORT_DIR is required")
        report_path = Path(os.environ["FOUNDRY_REPORT_DIR"]) / "summary.json"
    report = check(args)
    try:
        for root in (Path(__file__).parent, args.task.resolve().parent, args.snapshot.resolve().parent, args.outputs):
            if report_path.resolve().is_relative_to(root.resolve()):
                raise ValueError("report must be separate from checked inputs and outputs")
        with report_path.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    except (OSError, ValueError) as error:
        print("host-review checker: " + str(error), file=sys.stderr)
        return 2
    return 0 if report["status"] == "CHECKS_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
