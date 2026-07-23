"""Bootstrap approval compression and separate A3 authorization tests."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from harness_foundry_runtime.engine import (
    RuntimeViolation,
    authorization_plan,
    bootstrap_apply,
    bootstrap_plan,
    plan_next,
    status,
    verify_run,
)
from harness_foundry_runtime.util import file_sha256, write_json

from support import SyntheticRuntime


class BootstrapAuthorizationTests(unittest.TestCase):
    def test_bootstrap_bundle_has_five_independent_child_authorizations(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            before = bootstrap_plan(
                fixture.handoff_path, fixture.execution
            )
            self.assertFalse(fixture.execution.exists())
            self.assertEqual(len(before["child_authorizations"]), 5)
            self.assertFalse(before["execution_authorization_included"])
            write_json(fixture.bundle_path, before)
            result = bootstrap_apply(
                fixture.bundle_path, before["confirmation_text"]
            )

            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["effective_mode"], "A1_PLAN_ONLY")
            self.assertEqual(
                result["execution_authorization"], "NOT_GRANTED"
            )
            self.assertFalse(result["workpacks_executed"])
            self.assertEqual(verify_run(fixture.execution)["status"], "PASS")

    def test_wrong_bootstrap_confirmation_does_not_create_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            bundle = bootstrap_plan(
                fixture.handoff_path, fixture.execution
            )
            write_json(fixture.bundle_path, bundle)
            with self.assertRaisesRegex(
                RuntimeViolation, "bootstrap bundle"
            ):
                bootstrap_apply(fixture.bundle_path, "wrong")
            self.assertFalse(fixture.execution.exists())

    def test_a1_plans_but_does_not_advance_without_separate_authorization(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            decision = plan_next(fixture.execution)
            report = status(fixture.execution)

            self.assertEqual(decision["decision"], "HUMAN_GATE")
            self.assertEqual(
                decision["reason"]["code"], "AUTHORIZATION_MISSING"
            )
            self.assertEqual(report["effective_mode"], "A1_PLAN_ONLY")
            self.assertEqual(
                report["authorization"]["status"], "NOT_GRANTED"
            )

    def test_authorization_rejects_path_and_manifest_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            manifest = fixture.make_manifest("NODE_A")
            request = {
                "level": "A3_PROGRAM_BOUNDED",
                "dag_node_ids": ["NODE_A"],
                "workpack_ids": ["WP-NODE_A"],
                "command_manifests": {
                    "NODE_A": {
                        "path": str(manifest),
                        "sha256": "0" * 64,
                    }
                },
                "allowed_write_roots": ["/tmp/outside-authority"],
                "environment_ids": ["TEST-ENV"],
                "expires_at": "2099-01-01T00:00:00Z",
                "max_transitions": 1,
                "max_loop_rounds": 1,
                "max_wall_time_seconds": 60,
            }
            request_path = fixture.root / "bad-request.json"
            write_json(request_path, request)
            result = authorization_plan(
                fixture.execution, request_path
            )
            codes = {
                item["code"] for item in result["blocking_findings"]
            }
            self.assertIn("COMMAND_MANIFEST_HASH_MISMATCH", codes)
            self.assertIn("AUTHORIZATION_WRITE_SCOPE_INVALID", codes)

    def test_execution_authorization_is_exact_and_effective_budget_is_minimum(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            fixture.authorize(max_transitions=2, max_loop_rounds=2)
            report = status(fixture.execution)
            self.assertEqual(
                report["effective_mode"], "A3_PROGRAM_BOUNDED"
            )
            self.assertEqual(report["budget"]["transitions_max"], 2)
            self.assertEqual(report["budget"]["loop_rounds_max"], 2)
            self.assertFalse(report["real_target_install_allowed"])
