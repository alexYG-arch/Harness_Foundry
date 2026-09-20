"""Slice 08 official core validation and evidence projection contracts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from harness_foundry_factory.core_validation import (
    project_core_evidence,
    validate_core,
)


ROOT = Path(__file__).resolve().parents[1]


def _source_snapshot(root: Path) -> dict[str, str]:
    paths = [root / "FACTORY_MANIFEST.json"]
    paths.extend(sorted((root / "src").rglob("*.py")))
    paths.extend(sorted((root / "tests").rglob("*.py")))
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }


class CoreValidationCliTests(unittest.TestCase):
    def _run_cli(self, command: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "harness_foundry_factory.cli",
                command,
                "--json",
            ],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_validate_core_executes_bound_behavior_and_failure_selectors_read_only(self) -> None:
        before = _source_snapshot(ROOT)

        completed = self._run_cli("validate-core")

        self.assertEqual(completed.returncode, 0, completed.stdout)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["validation_kind"], "OFFICIAL_CORE_VALIDATION")
        self.assertEqual(result["validation_scope"], "HISTORICAL_BASELINE_REGRESSION")
        self.assertFalse(result["current_public_route_verified"])
        self.assertFalse(result["generic_release_accepted"])
        self.assertEqual(result["core_regression"]["status"], "PASS")
        self.assertTrue(result["core_regression"]["tests_executed"])
        self.assertEqual(len(result["capability_behavior_matrix"]), 41)
        self.assertGreater(len(result["major_failure_path_matrix"]), 10)
        self.assertTrue(
            all(
                binding["implementation_module_sha256"]
                and binding["product_manifest_sha256"]
                and binding["exact_test_selectors"]
                and binding["public_entrypoint"]
                for binding in result["capability_behavior_matrix"]
            )
        )
        self.assertTrue(
            all(item["status"] == "PASS" for item in result["selector_results"])
        )
        self.assertFalse(result["writes_performed"])
        self.assertFalse(result["external_certification_claimed"])
        self.assertEqual(result["optional_security_hardening"], "NOT_RUN")
        self.assertEqual(result["optional_compatibility"]["validation_status"], "NOT_RUN")
        self.assertEqual(result["optional_compatibility"]["capability_count"], 8)
        self.assertFalse(result["optional_compatibility"]["default_route"])
        self.assertFalse(result["optional_compatibility"]["core_release_blocking"])
        optional_capabilities = set(result["optional_compatibility"]["capabilities"])
        self.assertTrue(optional_capabilities)
        self.assertTrue(
            optional_capabilities.isdisjoint(
                binding["capability"]
                for binding in result["capability_behavior_matrix"]
            )
        )
        self.assertEqual(_source_snapshot(ROOT), before)

    def test_core_evidence_projection_is_deterministic_and_not_a_receipt(self) -> None:
        first = project_core_evidence()
        second = project_core_evidence()

        self.assertEqual(first, second)
        self.assertEqual(first["status"], "PASS")
        self.assertEqual(
            first["projection_kind"],
            "IMPLEMENTATION_EVIDENCE_PROJECTION_NOT_RECEIPT",
        )
        self.assertFalse(first["creates_authority"])
        self.assertEqual(first["validation_scope"], "HISTORICAL_BASELINE_REGRESSION")
        self.assertFalse(first["current_public_route_verified"])
        self.assertFalse(first["generic_release_accepted"])
        self.assertFalse(first["release_receipt_created"])
        self.assertFalse(first["external_certification_claimed"])
        self.assertEqual(first["optional_security_hardening"], "NOT_RUN")
        self.assertEqual(first["optional_compatibility"]["validation_status"], "NOT_RUN")
        self.assertFalse(first["optional_compatibility"]["core_release_blocking"])
        material = dict(first)
        projection_sha256 = material.pop("projection_sha256")
        encoded = json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(projection_sha256, hashlib.sha256(encoded).hexdigest())

    def test_manifest_gap_fails_before_any_test_program_executes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / "src", root / "src")
            shutil.copytree(ROOT / "tests", root / "tests")
            manifest = json.loads(
                (ROOT / "FACTORY_MANIFEST.json").read_text(encoding="utf-8")
            )
            manifest["implemented_core_capabilities"].remove("version")
            (root / "FACTORY_MANIFEST.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            result = validate_core(root, execute_tests=False)

        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["core_regression"]["tests_executed"])
        self.assertIn(
            "IMPLEMENTATION_MANIFEST_CAPABILITY_MISMATCH",
            {finding["code"] for finding in result["findings"]},
        )

    def test_optional_compatibility_scope_mismatch_fails_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / "src", root / "src")
            shutil.copytree(ROOT / "tests", root / "tests")
            manifest = json.loads(
                (ROOT / "FACTORY_MANIFEST.json").read_text(encoding="utf-8")
            )
            manifest["implemented_optional_compatibility_capabilities"].pop()
            (root / "FACTORY_MANIFEST.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            result = validate_core(root, execute_tests=False)

        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["core_regression"]["tests_executed"])
        self.assertIn(
            "OPTIONAL_COMPATIBILITY_MANIFEST_CAPABILITY_MISMATCH",
            {finding["code"] for finding in result["findings"]},
        )

    def test_projection_rejects_candidate_style_pass_self_report(self) -> None:
        with self.assertRaises(TypeError):
            project_core_evidence(
                {
                    "schema_version": "2.9",
                    "status": "PASS",
                    "external_certification_claimed": False,
                }
            )

    def test_project_core_evidence_cli_runs_validation_without_input_receipt(self) -> None:
        completed = self._run_cli("project-core-evidence")

        self.assertEqual(completed.returncode, 0, completed.stdout)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["creates_authority"])
        self.assertFalse(result["release_receipt_created"])
        self.assertNotIn("validation-result", completed.args)


if __name__ == "__main__":
    unittest.main()
