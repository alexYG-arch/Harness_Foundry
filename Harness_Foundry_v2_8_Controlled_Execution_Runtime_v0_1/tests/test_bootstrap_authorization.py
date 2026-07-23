"""Bootstrap approval compression and separate A3 authorization tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from harness_foundry_runtime.engine import (
    RuntimeViolation,
    authorization_plan,
    bootstrap_apply,
    bootstrap_plan,
    plan_next,
    status,
    verify_run,
)
from harness_foundry_runtime.util import file_sha256, json_sha256, write_json

from support import SyntheticRuntime


class BootstrapAuthorizationTests(unittest.TestCase):
    @staticmethod
    def _rewrite_handoff(
        fixture: SyntheticRuntime, **changes: object
    ) -> None:
        handoff = json.loads(
            fixture.handoff_path.read_text(encoding="utf-8")
        )
        handoff.update(changes)
        excluded = {
            "handoff_sha256",
            "status",
            "writes_performed",
            "commands_executed",
        }
        body = {
            key: value
            for key, value in handoff.items()
            if key not in excluded
        }
        handoff["handoff_sha256"] = json_sha256(body)
        write_json(fixture.handoff_path, handoff)

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

    def test_bootstrap_materializes_a_self_contained_driver(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            launcher = (
                fixture.execution / "control_plane/bin/hfdriver"
            )
            completed = subprocess.run(
                [str(launcher), "--help"],
                cwd=fixture.root,
                env={
                    **os.environ,
                    "PYTHONPATH": "/definitely/not/the/runtime",
                },
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("usage: hfdriver", completed.stdout)

    def test_failed_driver_probe_does_not_close_runtime_verification(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            bundle = bootstrap_plan(
                fixture.handoff_path, fixture.execution
            )
            write_json(fixture.bundle_path, bundle)
            with mock.patch(
                "harness_foundry_runtime.engine._launch_driver_probe",
                side_effect=RuntimeViolation(
                    "DRIVER_LAUNCH_FAILED", "synthetic failure"
                ),
            ):
                with self.assertRaisesRegex(
                    RuntimeViolation, "synthetic failure"
                ):
                    bootstrap_apply(
                        fixture.bundle_path,
                        bundle["confirmation_text"],
                    )

            state = json.loads(
                (
                    fixture.execution
                    / "control_plane/state/PROGRAM_DRIVER_STATE.json"
                ).read_text(encoding="utf-8")
            )
            self.assertTrue(state["driver"]["materialized"])
            self.assertFalse(state["driver"]["runtime_verified"])
            self.assertNotIn(
                "PROGRAM_DRIVER_RUNTIME_VERIFIED",
                state["locally_closed_nodes"],
            )

    def test_vendored_driver_tamper_fails_verify_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            vendored_engine = (
                fixture.execution
                / "control_plane/driver/runtime"
                / "harness_foundry_runtime/engine.py"
            )
            vendored_engine.write_text(
                vendored_engine.read_text(encoding="utf-8")
                + "\n# tampered\n",
                encoding="utf-8",
            )

            report = verify_run(fixture.execution)
            codes = {
                item["code"] for item in report["blocking_findings"]
            }

            self.assertEqual(report["status"], "FAIL")
            self.assertIn("EVIDENCE_HASH_MISMATCH", codes)

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

    def test_bootstrap_rejects_missing_handoff_program_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            self._rewrite_handoff(fixture, program_id=None)

            result = bootstrap_plan(
                fixture.handoff_path, fixture.execution
            )
            codes = {
                item["code"] for item in result["blocking_findings"]
            }

            self.assertEqual(result["status"], "FAIL")
            self.assertIn("HANDOFF_PROGRAM_ID_MISSING", codes)
            self.assertFalse(fixture.execution.exists())

    def test_bootstrap_rejects_program_id_binding_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            self._rewrite_handoff(
                fixture, program_id="PROGRAM-OTHER"
            )

            result = bootstrap_plan(
                fixture.handoff_path, fixture.execution
            )
            codes = {
                item["code"] for item in result["blocking_findings"]
            }

            self.assertEqual(result["status"], "FAIL")
            self.assertIn("HANDOFF_PROGRAM_ID_MISMATCH", codes)
            self.assertFalse(fixture.execution.exists())

    def test_a1_plans_but_does_not_advance_without_separate_authorization(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            decision = plan_next(fixture.execution)
            report = status(fixture.execution)

            self.assertEqual(
                decision["decision"], "PREPARATION_REQUIRED"
            )
            self.assertEqual(
                decision["reason"]["code"], "COMMAND_OVERLAY_REQUIRED"
            )
            self.assertEqual(report["effective_mode"], "A1_PLAN_ONLY")
            self.assertEqual(
                report["authorization"]["status"], "NOT_GRANTED"
            )
            self.assertEqual(
                report["next_required_action"],
                "REGISTER_COMMAND_OVERLAYS",
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
