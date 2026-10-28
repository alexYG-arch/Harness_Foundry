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
    "test_rsi_adoption",
    "test_rsi_cases",
    "test_rsi_review",
    "test_rsi_tdd",
    "test_rsi_wiki",
    "test_rsi_reports",
    "test_rsi_delivery",
    "test_revision_control_store",
    "test_build_readpath",
    "test_revision_bodies",
    "test_revision_migration",
    "test_acceptance_contract",
    "test_build_entrypoint",
    "test_build_runtime",
    "test_build_runtime_context",
    "test_build_reconciliation",
    "test_build_reassessment",
    "test_build_correction",
    "test_build_correction_budget",
    "test_build_correction_runtime",
    "test_build_preview",
    "test_coding_reconnect",
    "test_build_observation_race",
    "test_build_model_defaults",
    "test_build_daily_model_defaults",
    "test_coding_defaults",
    "test_model_service_configuration",
    "test_model_configuration_observation",
    "test_build_model_service",
    "test_python_startup",
    "test_build_rebind",
    "test_build_budget_extension",
    "test_build_check_protocol",
    "test_portable_local_cli",
    "test_skill_contract",
    "test_release_source_gate",
    "test_generic_distribution",
    "test_r3_distribution",
    "test_capability_distribution",
    "test_capability_connections",
    "test_capability_native",
    "test_capability_rsi_handoff",
    "test_capability_external_delivery",
    "test_capability_author",
    "test_capability_feature_inventory",
    "test_capability_feature_delivery",
    "test_capability_feature_reports",
    "test_capability_delivery_intents",
    "test_capability_feature_package_selection",
    "test_capability_feature_versions",
    "test_r3_behavior_baseline",
    "test_build_resource_lifecycle",
    "test_build_replan",
    "test_verification_resources",
    "test_build_resources",
    "test_resource_network",
    "test_resource_credentials",
    "test_resource_credential_observation",
    "test_process_cancellation",
    "test_process_observation",
    "test_committed_distribution",
    "test_route_retirement",
    "test_test_execution",
    "test_release_acceptance_adapters",
)

# This assertion invokes the real macOS otool. It remains required on macOS;
# the Linux job reports it as not applicable, never as a pass or ignored skip.
MACOS_ONLY_TESTS = frozenset({
    "test_capability_feature_versions.PythonV2Tests.test_native_observation_uses_selected_module_dependencies_and_then_actual_probe",
})


def platform_suite(suite, platform):
    selected = unittest.TestSuite()
    not_applicable = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            nested, excluded = platform_suite(item, platform)
            selected.addTest(nested)
            not_applicable.extend(excluded)
        elif platform != "darwin" and item.id() in MACOS_ONLY_TESTS:
            not_applicable.append({"test": item.id(), "reason": "Requires actual macOS otool; covered by the macOS CI job"})
        else:
            selected.addTest(item)
    return selected, not_applicable


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
    selected, not_applicable = platform_suite(unittest.TestSuite(suites), sys.platform)
    tests = check_suite(selected)
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
        "platform": sys.platform,
        "platform_not_applicable": not_applicable,
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
