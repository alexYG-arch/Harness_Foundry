"""Run the delivered DOC CLI once and compare its export with a private full oracle."""

import argparse
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile


# The protected wrapper observes exceptions from the actual CLI. It does not
# import the producer's renderer or accept a producer-written PASS report.
RUNNER = r'''
import json, runpy, sys
sys.argv = sys.argv[1:]
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
except OSError as error:
    print(json.dumps({"doc_cli_error": "OS", "errno": error.errno,
          "filename": error.filename, "message": str(error)}), file=sys.stderr)
    raise SystemExit(1)
except (ValueError, KeyError, TypeError, IndexError, AttributeError, SyntaxError) as error:
    print(json.dumps({"doc_cli_error": "PRODUCT", "message": str(error)}), file=sys.stderr)
    raise SystemExit(1)
'''


def nonempty_lines(value):
    return [line for line in value.splitlines() if line.strip()]


def check(args):
    report = {"schema_version": "1.0", "case_id": os.environ.get("FOUNDRY_CASE_ID", "standalone"),
              "command_id": os.environ.get("FOUNDRY_COMMAND_ID", "standalone"),
              "status": "CHECKS_FAILED", "checks": [], "errors": []}
    try:
        root = os.environ.get("FOUNDRY_VERIFIER_ROOT")
        if root:
            protected = Path(root).resolve(strict=True)
            if (not Path(__file__).resolve().is_relative_to(protected)
                    or not args.expected.resolve(strict=True).is_relative_to(protected)):
                raise ValueError("checker and expectation must use the protected verifier copy")
            if not os.environ.get("FOUNDRY_SCRATCH_DIR"):
                raise ValueError("resource checker requires its declared FOUNDRY_SCRATCH_DIR")
        expected_bytes = args.expected.read_bytes()
        expected = nonempty_lines(expected_bytes.decode("utf-8"))
        if not expected:
            raise ValueError("project expectation must be a complete nonempty Markdown document")
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise ValueError("timeout must be positive")
    except (OSError, ValueError, UnicodeError) as error:
        report["checks"].append({"id": "document-export", "status": "ERROR"})
        report["errors"].append(str(error))
        return report
    try:
        paths = {name: getattr(args, name).absolute() for name in ("tool", "config", "notes", "sources")}
        bindings = {}
        for name, path in paths.items():
            try:
                bindings[name + "_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as error:
                if error.errno in (errno.ENOENT, errno.ENOTDIR, errno.EISDIR):
                    raise AssertionError("declared product input path error: " + str(error)) from error
                raise
        report["input_bindings"] = bindings
        report["expected_sha256"] = hashlib.sha256(expected_bytes).hexdigest()
        with tempfile.TemporaryDirectory(prefix="doc-export-", dir=os.environ.get("FOUNDRY_SCRATCH_DIR")) as temporary:
            output = Path(temporary).resolve() / "export.md"
            tool_argv = [str(paths["tool"])]
            for name in ("config", "notes", "sources"):
                tool_argv.extend(["--" + name, str(paths[name])])
            tool_argv.extend(["--output", str(output)])
            argv = [sys.executable, "-I", "-B", "-c", RUNNER, *tool_argv]
            report["execution"] = {"argv": argv, "python": sys.executable, "tool_argv": tool_argv, "invocation_attempts": 1}
            # Private verifier locations are not passed as task arguments or
            # environment hints to the delivered producer.
            env = {key: value for key, value in os.environ.items() if not key.startswith("FOUNDRY_")}
            completed = subprocess.run(argv, cwd=temporary, env=env, capture_output=True, timeout=args.timeout)
            report["execution"]["returncode"] = completed.returncode
            if completed.returncode < 0:
                raise RuntimeError("document CLI terminated by a signal")
            if completed.returncode:
                try:
                    error = json.loads(completed.stderr.splitlines()[-1])
                except (ValueError, UnicodeError, IndexError):
                    error = {}
                if isinstance(error, dict) and error.get("doc_cli_error") == "OS":
                    filename = error.get("filename")
                    product_path = isinstance(filename, str) and Path(filename).is_absolute() and Path(filename).resolve() in {path.resolve() for path in paths.values()}
                    if error.get("errno") in (errno.ENOENT, errno.ENOTDIR, errno.EISDIR) and product_path:
                        raise AssertionError("document CLI product path error: " + error["message"])
                    raise OSError(error.get("errno"), error.get("message", "document CLI OS error"))
                raise AssertionError("document CLI failed: " + completed.stderr.decode("utf-8", errors="replace"))
            if not output.is_file():
                raise AssertionError("document CLI did not create its declared output")
            actual = output.read_bytes()
            report["actual_sha256"] = hashlib.sha256(actual).hexdigest()
            report["actual_export"] = actual.decode("utf-8")
            if nonempty_lines(report["actual_export"]) != expected:
                raise AssertionError("actual exported content differs from the complete project expectation")
    except (AssertionError, UnicodeError) as error:
        report["checks"].append({"id": "document-export", "status": "FAIL"})
        report["failure_kind"] = "ASSERTION"
        report["diagnostic"] = str(error)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        report["checks"].append({"id": "document-export", "status": "ERROR"})
        report["errors"].append(str(error))
    else:
        report["status"] = "CHECKS_PASS"
        report["checks"].append({"id": "document-export", "status": "PASS"})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("tool", "config", "notes", "sources", "expected"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    destination = args.report
    if destination is None:
        if "FOUNDRY_REPORT_DIR" not in os.environ:
            parser.error("--report or FOUNDRY_REPORT_DIR is required")
        destination = Path(os.environ["FOUNDRY_REPORT_DIR"]) / "summary.json"
    try:
        if destination.resolve().is_relative_to(Path(__file__).resolve().parent):
            raise ValueError("report must be outside the capability/checker directory")
        # Reserve the new report before running the CLI: an already archived
        # report is never a reason to repeat the producer command.
        with destination.open("x", encoding="utf-8") as stream:
            report = check(args)
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except (OSError, ValueError) as error:
        print("document checker: " + str(error), file=sys.stderr)
        return 2
    return 0 if report["status"] == "CHECKS_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
