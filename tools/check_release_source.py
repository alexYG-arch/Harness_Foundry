#!/usr/bin/env python3
"""Run required public source checks; never grant whole-release acceptance.

No model, target build, private Case, normative sibling or release upload is
needed. Native opt-in and full compatibility tests remain separate obligations.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_MODULES = (
    "test_product_identity",
    "test_build_review",
    "test_build_plan",
    "test_build_authoring",
    "test_source_intake",
    "test_revision_control_store",
    "test_acceptance_contract",
    "test_build_entrypoint",
    "test_build_runtime",
    "test_portable_local_cli",
    "test_skill_contract",
    "test_release_source_gate",
    "test_generic_distribution",
    "test_build_replan",
    "test_process_cancellation",
    "test_committed_distribution",
    "test_route_retirement",
)


class RequiredResult(unittest.TextTestResult):
    """unittest's ordinary success permits skips/xfail; this gate must not."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.passed = 0

    def addSuccess(self, test):
        super().addSuccess(test)
        self.passed += 1


def check_suite(suite: unittest.TestSuite, *, stream=None) -> dict:
    discovered = suite.countTestCases()
    result = unittest.TextTestRunner(
        stream=stream or sys.stderr, verbosity=2, resultclass=RequiredResult,
    ).run(suite)
    passed = (
        discovered > 0 and result.testsRun == discovered
        and result.passed == discovered and result.wasSuccessful()
        and not result.skipped and not result.expectedFailures
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "discovered": discovered,
        "executed": result.testsRun,
        "passed": result.passed,
        "skipped": [{"test": test.id(), "reason": reason} for test, reason in result.skipped],
        "failures": [test.id() for test, _ in result.failures],
        "errors": [test.id() for test, _ in result.errors],
        "expected_failures": [test.id() for test, _ in result.expectedFailures],
        "unexpected_successes": [test.id() for test in result.unexpectedSuccesses],
    }


def source_checks() -> dict:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tests"))
    sys.path.insert(0, str(ROOT / "src"))
    loader = unittest.TestLoader()
    suites = []
    missing = []
    empty = []
    for module in REQUIRED_MODULES:
        if not (ROOT / "tests" / f"{module}.py").is_file():
            missing.append(module)
            continue
        loaded = loader.loadTestsFromName(module)
        if not loaded.countTestCases():
            empty.append(module)
        suites.append(loaded)
    tests = check_suite(unittest.TestSuite(suites))
    skill = subprocess.run(
        [sys.executable, "-B", str(ROOT / "tools/validate_skill.py")],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=60,
    )
    try:
        skill_result = json.loads(skill.stdout)
    except ValueError:
        skill_result = {"status": "FAIL", "error": "Skill checker did not emit JSON"}
    skill_ok = isinstance(skill_result, dict) and skill_result.get("status") == "PASS" and skill.returncode == 0
    passed = tests["status"] == "PASS" and not missing and not empty and not loader.errors and skill_ok
    return {
        "schema_version": "1.0",
        "status": "SOURCE_CHECKS_PASS" if passed else "SOURCE_CHECKS_FAIL",
        "scope": "PUBLIC_GENERIC_SOURCE_WITH_HISTORICAL_REGRESSION_AND_PORTABLE_SMOKE",
        "historical_regression_is_current_product_acceptance": False,
        "required_modules": list(REQUIRED_MODULES),
        "missing_modules": missing,
        "empty_modules": empty,
        "load_errors": loader.errors,
        "tests": tests,
        "skill": skill_result,
        "release_accepted": False,
        "harness_e2e_verified": False,
        "not_run": [
            "FULL_COMPATIBILITY_REGRESSION", "PHYSICAL_SIBLING_SPEC_CHECK",
            "NATIVE_CODEX_ACCEPTANCE", "SAME_PACKAGE_TWO_CASES",
            "CLEAN_COMMITTED_RELEASE_BUILD", "PUBLICATION",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Write JSON to a new diagnostic file; never overwrite.")
    args = parser.parse_args()
    if args.report and args.report.exists():
        parser.error("--report must name a new file")
    try:
        report = source_checks()
    except Exception as exc:
        report = {"status": "SOURCE_CHECKS_FAIL", "error": f"{type(exc).__name__}: {exc}",
                  "release_accepted": False, "harness_e2e_verified": False}
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as output:
            output.write(serialized + "\n")
    print(serialized)
    return 0 if report["status"] == "SOURCE_CHECKS_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
