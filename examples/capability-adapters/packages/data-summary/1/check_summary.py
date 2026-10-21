"""Compare with project-owned independent expectations; never import the producer."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


BODY_KEYS = {"schema_version", "summary", "groups", "rows", "excluded"}


def read_bytes(path, files=None, key=None):
    data = path.read_bytes()
    if files is not None:
        files[key] = hashlib.sha256(data).hexdigest()
    return data


def read_json(path, files=None, key=None):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key: " + key)
            value[key] = item
        return value
    return json.loads(read_bytes(path, files, key).decode("utf-8"), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def check(args):
    files = dict.fromkeys(("input", "config", "actual", "expected"))
    report = {"schema_version": "1.0", "case_id": os.environ.get("FOUNDRY_CASE_ID", "standalone"),
              "command_id": os.environ.get("FOUNDRY_COMMAND_ID", "standalone"),
              "status": "CHECKS_FAILED", "checks": [], "errors": [],
              "observation_binding": {"format": "data-summary", "files": files}}
    try:
        root = os.environ.get("FOUNDRY_VERIFIER_ROOT")
        if root:
            protected = Path(root).resolve(strict=True)
            if not Path(__file__).resolve().is_relative_to(protected) or not args.expected.resolve(strict=True).is_relative_to(protected):
                raise ValueError("checker and project expectation must use the protected verifier copy")
        expected = read_json(args.expected, files, "expected")
        if (not isinstance(expected, dict) or set(expected) != BODY_KEYS or expected["schema_version"] != "1.0"
                or not isinstance(expected["summary"], dict)
                or set(expected["summary"]) != {"input_rows", "included_rows", "excluded_rows"}
                or any(type(v) is not int or v < 0 for v in expected["summary"].values())
                or any(not isinstance(expected[key], list) for key in ("groups", "rows", "excluded"))):
            raise ValueError("independent expectation must contain the complete summary, groups, rows and exclusions")
        read_bytes(args.input, files, "input")
        read_bytes(args.config, files, "config")
        bindings = {"input_sha256": files["input"], "config_sha256": files["config"]}
    except (OSError, ValueError, TypeError, UnicodeError) as error:
        report["checks"].append({"id": "data-summary", "status": "ERROR"})
        report["errors"].append(str(error))
    else:
        try:
            actual = read_json(args.actual, files, "actual")
            if not isinstance(actual, dict) or set(actual) != BODY_KEYS | set(bindings):
                raise AssertionError("actual result fields differ from the complete output contract")
            if any(actual[key] != value for key, value in bindings.items()):
                raise AssertionError("actual result is not bound to the checked input and configuration")
            body = {key: actual[key] for key in BODY_KEYS}
            # Canonical JSON also distinguishes bool from int and int from float.
            if json.dumps(body, sort_keys=True, ensure_ascii=False) != json.dumps(expected, sort_keys=True, ensure_ascii=False):
                raise AssertionError("actual result differs from the independent project expectation")
        except (AssertionError, ValueError, UnicodeError, FileNotFoundError, IsADirectoryError) as error:
            report["checks"].append({"id": "data-summary", "status": "FAIL"})
            report["failure_kind"] = "ASSERTION"
            report["diagnostic"] = str(error)
        except OSError as error:
            report["checks"].append({"id": "data-summary", "status": "ERROR"})
            report["errors"].append(str(error))
        else:
            report["status"] = "CHECKS_PASS"
            report["checks"].append({"id": "data-summary", "status": "PASS"})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("input", "config", "actual", "expected"):
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
        if report_path.resolve().is_relative_to(Path(__file__).resolve().parent):
            raise ValueError("report must be outside the capability/checker directory")
        with report_path.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    except (OSError, ValueError) as error:
        print("data-summary checker: " + str(error), file=sys.stderr)
        return 2
    return 0 if report["status"] == "CHECKS_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
