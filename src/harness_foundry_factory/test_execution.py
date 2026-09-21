"""Optional standard-library test adapter. Execution still needs host authority.

Keep test errors distinct from assertions and pass caller-selected paths through
the subprocess boundary. This is not a sandbox or an acceptance authority.
"""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback
import unittest


def execution_paths(project, workdir, python):
    project, workdir = Path(project).resolve(strict=True), Path(workdir).resolve(strict=True)
    python = Path(python).absolute()  # Keep the declared venv/executable alias.
    if not project.is_dir() or not workdir.is_dir() or not python.is_file():
        raise ValueError("project/workdir must exist; python must be an explicit executable file")
    if project == workdir or workdir in project.parents:
        raise ValueError("workdir cannot equal or contain project")
    return project, workdir, python


def source_snapshot(project, workdir):
    """Exclude exactly the caller's mutable subtree, never the whole project."""
    return {str(path.relative_to(project)): path.read_bytes()
            for path in project.rglob("*") if path.is_file() and not path.resolve().is_relative_to(workdir)}


class StructuredResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.error_details = []

    def _record_error(self, test, err):
        frames = traceback.extract_tb(err[2])
        names = {frame.name for frame in frames}
        phase = next((name for name in ("setUpModule", "setUpClass", "setUp", "tearDown", "tearDownClass", "tearDownModule")
                      if name in names), "TEST_OR_DISCOVERY")
        self.error_details.append({"test": test.id(), "phase": phase,
                                   "exception_type": err[0].__name__,
                                   "traceback": "".join(traceback.format_exception(*err))})
    def addError(self, test, err):
        self._record_error(test, err)
        super().addError(test, err)

    def addSubTest(self, test, subtest, err):
        if err is not None and not issubclass(err[0], test.failureException):
            self._record_error(subtest, err)
        super().addSubTest(test, subtest, err)


def collect_tests(project, pattern):
    stream, output, errors = io.StringIO(), io.StringIO(), io.StringIO()
    loader = unittest.TestLoader()
    # Redirect test prints; the adapter's stdout remains one parseable verdict.
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
        suite = loader.discover(str(project), pattern=pattern)
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=StructuredResult).run(suite)
    incomplete = bool(result.skipped or result.expectedFailures or not result.testsRun)
    kind = "INFRASTRUCTURE" if result.errors or loader.errors or incomplete else "ASSERTION"
    passed = result.wasSuccessful() and not incomplete and not loader.errors
    return {"status": "CHECKS_PASS" if passed else "CHECKS_FAILED",
            "failure_kind": None if passed else kind, "phase": "UNITTEST",
            "tests_run": result.testsRun,
            "failures": [{"test": test.id(), "traceback": detail} for test, detail in result.failures],
            "errors": result.error_details, "discovery_errors": loader.errors,
            "skipped": [{"test": test.id(), "reason": reason} for test, reason in result.skipped],
            "expected_failures": [test.id() for test, _ in result.expectedFailures],
            "unexpected_successes": [test.id() for test in result.unexpectedSuccesses],
            "stdout": output.getvalue(), "stderr": errors.getvalue(), "test_log": stream.getvalue()}


def run_tests(project, workdir, python, *, pattern="test_*.py", timeout=60):
    project, workdir, python = execution_paths(project, workdir, python)
    before = source_snapshot(project, workdir)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(project),
               TMPDIR=str(workdir), TMP=str(workdir), TEMP=str(workdir),
               FOUNDRY_TEST_WORKDIR=str(workdir), BOUND_PYTHON=str(python))
    argv = [str(python), "-B", str(Path(__file__).resolve()), "--collect", "--project", str(project),
            "--workdir", str(workdir), "--python", str(python), "--pattern", pattern]
    # Child processes may inherit stdout at fd level; do not parse their logs as
    # the collector verdict or rely on the last stdout line being JSON.
    serialized = None
    with tempfile.TemporaryDirectory(prefix="foundry-tests-", dir=workdir) as capture:
        result_file = Path(capture) / "result.json"
        argv.extend(["--result-file", str(result_file)])
        try:
            child = subprocess.run(argv, cwd=workdir, env=env, capture_output=True, text=True, timeout=timeout)
            if result_file.is_file():
                serialized = result_file.read_text()
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"status": "CHECKS_FAILED", "failure_kind": "INFRASTRUCTURE", "phase": "DISPATCH",
                    "exception_type": type(exc).__name__, "reason": str(exc), "argv": argv}
    raw = {"argv": argv, "exit_code": child.returncode, "stdout": child.stdout, "stderr": child.stderr}
    try:
        verdict = json.loads(serialized)
        if not isinstance(verdict, dict) or verdict.get("status") not in {"CHECKS_PASS", "CHECKS_FAILED"}:
            raise ValueError("missing test verdict")
        if child.returncode != (0 if verdict["status"] == "CHECKS_PASS" else 1):
            raise ValueError("child exit and verdict disagree")
    except (TypeError, ValueError) as exc:
        return {"status": "CHECKS_FAILED", "failure_kind": "INFRASTRUCTURE", "phase": "COLLECTION",
                "reason": str(exc), "process": raw}
    after = source_snapshot(project, workdir)
    if before != after:
        return {"status": "CHECKS_FAILED", "failure_kind": "ASSERTION", "phase": "SOURCE_PROTECTION",
                "reason": "tests modified protected project files", "tests": verdict, "process": raw}
    return {**verdict, "process": raw, "protected_source_unchanged": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--pattern", default="test_*.py")
    parser.add_argument("--collect", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--result-file", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        project, workdir, python = execution_paths(args.project, args.workdir, args.python)
        result = collect_tests(project, args.pattern) if args.collect else run_tests(project, workdir, python, pattern=args.pattern)
    except (OSError, ValueError) as exc:
        result = {"status": "CHECKS_FAILED", "failure_kind": "INFRASTRUCTURE", "phase": "PREPARATION",
                  "exception_type": type(exc).__name__, "reason": str(exc)}
    if args.collect and args.result_file:
        args.result_file.write_text(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "CHECKS_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
