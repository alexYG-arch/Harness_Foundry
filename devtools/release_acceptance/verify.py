"""Read-only independent checks for the displayed public acceptance contracts."""
import argparse
import ast
import json
from pathlib import Path
import subprocess


class CheckFailure(Exception):
    def __init__(self, kind, reason, *, evidence=None, repair=()):
        self.verdict = {"status": "CHECKS_FAILED", "failure_kind": kind,
                        "reason": reason, "evidence": evidence}
        if repair:
            self.verdict["repair_artifact_ids"] = list(repair)


def nested_result(result, label):
    """Unexpected errors are not assertions, even through a generated checker."""
    if result.get("status") == "CHECKS_PASS":
        return
    kind = result.get("failure_kind")
    raise CheckFailure(kind if kind in {"ASSERTION", "CONTRACT_GAP"} else "INFRASTRUCTURE",
                       label, evidence=result)


def environment_report(report, kind):
    require(report["protected_source_unchanged"], "checker modified protected project source")
    tests = report["tests"]
    # Preserve the typed setup/discovery error first, before any wrapping H failure.
    try:
        nested_result(tests, "project tests failed")
    except CheckFailure as exc:
        if exc.verdict["failure_kind"] == "ASSERTION":
            exc.verdict["repair_artifact_ids"] = ["U-0", "U-1" if kind == "task" else "U-3"]
        raise
    require(tests.get("tests_run", 0) > 0, "no actual project tests")
    process = report["harness_check"]
    try:
        verdict = json.loads(process["stdout"])
    except ValueError as exc:
        # A traceback/non-JSON failure is not evidence identifying a repair owner.
        raise CheckFailure("INFRASTRUCTURE", "generated checker did not return a typed verdict",
                           evidence=process) from exc
    if not isinstance(verdict, dict) or verdict.get("status") not in {"CHECKS_PASS", "CHECKS_FAILED"}:
        raise CheckFailure("ASSERTION", "generated checker violates the reviewed JSON interface",
                           evidence=process, repair=["H-2"])
    if process["exit_code"] != (0 if verdict["status"] == "CHECKS_PASS" else 1):
        raise CheckFailure("ASSERTION", "checker exit contradicts its verdict", evidence=process, repair=["H-2"])
    nested_result(verdict, "generated Harness check failed")


def negative_harness_report(report):
    require(report["negative_source_unchanged"], "checker changed negative fixture source")
    process = report["negative_harness_check"]
    try:
        verdict = json.loads(process["stdout"])
    except ValueError as exc:
        raise CheckFailure("INFRASTRUCTURE", "negative checker observation is not a typed result", evidence=process) from exc
    if not isinstance(verdict, dict):
        raise CheckFailure("INFRASTRUCTURE", "invalid negative checker result", evidence=process)
    if process["exit_code"] == 0 and verdict.get("status") == "CHECKS_PASS":
        raise CheckFailure("ASSERTION", "Harness accepted disclosed wrong business behavior",
                           evidence=process, repair=["H-2"])
    if (process["exit_code"] != 1 or verdict.get("status") != "CHECKS_FAILED"
            or verdict.get("failure_kind") != "ASSERTION"):
        raise CheckFailure("INFRASTRUCTURE", "checker crash/error does not prove negative rejection", evidence=process)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def output(row, expected, exit_code=0):
    require(row["exit_code"] == exit_code, f"wrong exit code for {row['argv']}")
    require(not row["stderr"].strip(), f"unexpected stderr for {row['argv']}")
    try:
        actual = json.loads(row["stdout"])
    except ValueError as exc:
        raise AssertionError(f"expected one stdout JSON for {row['argv']}") from exc
    require(actual == expected, f"{row['argv']}: expected {expected!r}, observed {actual!r}")


def error(row, code=None):
    require(row["exit_code"] == 2 and not row["stdout"].strip(), "error exit/stdout contract")
    try:
        value = json.loads(row["stderr"])["error"]
    except (ValueError, KeyError, TypeError) as exc:
        raise AssertionError("expected stderr error JSON") from exc
    if code is None:
        require(isinstance(value, str) and bool(value.strip()), "CSV error must be nonempty text")
    else:
        require(isinstance(value, dict) and value.get("code") == code and
                isinstance(value.get("message"), str) and bool(value["message"].strip()), "task error object")


def task_report(report):
    rows = report["observations"]
    t1 = {"id": 1, "title": "写 报告", "status": "todo"}
    t2 = {"id": 2, "title": "Review", "status": "todo"}
    done = dict(t1, status="done")
    t3 = {"id": 3, "title": "第三项", "status": "todo"}
    expected = {"empty": {"tasks": []}, "add1": {"task": t1}, "add2": {"task": t2},
                "list": {"tasks": [t1, t2]}, "complete": {"task": done}, "idempotent": {"task": done},
                "todo": {"tasks": [t2]}, "done": {"tasks": [done]}, "delete": {"deleted_id": 1},
                "add3": {"task": t3}, "final": {"tasks": [t2, t3]}}
    for name, value in expected.items():
        output(rows[name], value)
    require(rows["empty"]["before"] is None and rows["empty"]["after"] is None, "empty read created storage")
    require(json.loads(rows["idempotent"]["before"]) == json.loads(rows["idempotent"]["after"]),
            "repeat complete changed persisted state")
    final = json.loads(rows["final"]["after"])
    require(final == {"version": 1, "next_id": 4, "tasks": [t2, t3]}, "stored shape/sequence incorrect")
    errors = {name: "INVALID_INPUT" for name in
              ("blank", "bad-id", "zero-id", "bad-state", "bad-command")}
    errors.update({"unknown": "NOT_FOUND", "unknown-delete": "NOT_FOUND"})
    errors.update({name: "DATA_INVALID" for name in
                  ("broken-json", "wrong-type", "duplicate-id", "bad-version", "bad-stored-status",
                   "blank-stored-title", "bad-next-id")})
    for name, code in errors.items():
        error(rows[name], code)
        require(rows[name]["before"] == rows[name]["after"], f"{name} overwrote source storage")


def csv_report(report):
    rows = report["observations"]
    output(rows["summary"], {"columns": ["id", "name"], "rows": 2})
    output(rows["normal"], {"rows": 2, "invalid_rows": []})
    output(rows["empty"], {"rows": 0, "invalid_rows": []})
    invalid = [{"row": 2, "missing_fields": ["name"]}, {"row": 3, "missing_fields": ["city"]},
               {"row": 4, "missing_fields": ["name", "city"]}]
    output(rows["missing"], {"rows": 4, "invalid_rows": invalid})
    output(rows["strict"], {"rows": 4, "invalid_rows": invalid}, 3)
    ordered = [*invalid[:2], {"row": 4, "missing_fields": ["city", "name"]}]
    output(rows["ordered"], {"rows": 4, "invalid_rows": ordered})
    for name in ("unknown-column", "no-required", "empty-column", "duplicate", "blank-header", "bad-encoding", "no-file"):
        error(rows[name])
    require(all(row["input_unchanged"] for row in rows.values()), "CSV input was changed")


def check(kind, phase, root, inputs, python=None):
    if phase == "harness":
        for name in ("AGENTS.md", "BUILD.md", "check.py"):
            require((root / "harness" / name).is_file(), f"missing Harness {name}")
        for name in ("AGENTS.md", "BUILD.md"):
            text = (root / "harness" / name).read_text()
            require(bool(text.strip()), f"empty {name}")
            require("/Users/" not in text, f"private path in {name}")
        # The following is a resource precondition, not semantic A1/B1 acceptance.
        ast.parse((root / "harness/check.py").read_text())
        # Exercise the public parser under the verifier's existing read-only scope.
        if not python:
            raise ValueError("an explicit bound Python is required for the interface check")
        result = subprocess.run([str(python), "-B", str(root / "harness/check.py"), "--help"],
                                capture_output=True, text=True, timeout=15)
        if result.returncode or any(flag not in result.stdout for flag in ("--project", "--workdir", "--python")):
            raise CheckFailure("ASSERTION", "Harness public interface is not callable", evidence={
                "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
    elif phase == "source":
        name = "tasks.py" if kind == "task" else "csv_tool.py"
        ast.parse((root / "app" / name).read_text())
        require(bool((root / "app/README.md").read_text().strip()), "missing usage instructions")
        require(bool((root / "app/HARNESS_USE.md").read_text().strip()), "missing Harness use observations")
        for path in (root / "app").glob("test_*.py"):
            ast.parse(path.read_text())
        if kind == "csv":
            for destination, source in (("USER_NOTES.md", "USER_NOTES.md"), ("test_summary.py", "test_summary.py.txt")):
                require((root / "app" / destination).read_bytes() == (inputs / source).read_bytes(),
                        f"existing {destination} changed")
    elif phase == "scenario":
        report = json.loads((root / "scenario/report.json").read_text())
        require(report["kind"] == kind, "wrong scenario")
        try:
            (task_report if kind == "task" else csv_report)(report)
        except AssertionError as exc:
            # Disclosed disposable fault retries E; actual business defects return U.
            raise CheckFailure("ASSERTION", str(exc), repair=[] if report["fault_injected"] else ["U-0"]) from exc
        environment_report(report["development_environment"], kind)
        environment_report(report, kind)
        negative_harness_report(report)
        if kind == "csv":
            check(kind, "source", root, inputs, python)
    elif phase == "final":
        check(kind, "scenario", root, inputs, python)
        report = json.loads((root / "scenario/report.json").read_text())
        first = json.loads((root / "scenario/attempt-1/report.json").read_text())
        require(first["fault_injected"] and not report["fault_injected"], "missing disclosed fault/recovery")
        require(json.loads((root / "completion/result.json").read_text()) == {"scenario_present": True}, "missing successor")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["task", "csv"])
    parser.add_argument("phase", choices=["harness", "source", "scenario", "final"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--python", required=True)
    args = parser.parse_args()
    try:
        check(args.kind, args.phase, args.root, args.inputs, args.python)
    except CheckFailure as exc:
        print(json.dumps(exc.verdict, ensure_ascii=False))
        return 1
    except AssertionError as exc:
        print(json.dumps({"status": "CHECKS_FAILED", "failure_kind": "ASSERTION", "reason": str(exc)}, ensure_ascii=False))
        return 1
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "CHECKS_FAILED", "failure_kind": "INFRASTRUCTURE",
                          "phase": args.phase, "exception_type": type(exc).__name__, "reason": str(exc)}))
        return 1
    # Missing files not declared as artifacts or checker errors are infrastructure failures.
    print(json.dumps({"status": "CHECKS_PASS", "phase": args.phase,
                      "harness_semantics_accepted": False, "release_accepted": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
