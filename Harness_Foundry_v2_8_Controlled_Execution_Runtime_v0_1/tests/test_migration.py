"""Read-only migration and new-epoch safety tests."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import tempfile
import unittest

from harness_foundry_runtime.engine import (
    bootstrap_apply,
    bootstrap_plan,
    plan_next,
    status,
    verify_run,
)
from harness_foundry_runtime.migration import migration_apply, migration_plan
from harness_foundry_runtime.store import RuntimeStore
from harness_foundry_runtime.util import tree_sha256, write_json

from support import SyntheticRuntime


class MigrationTests(unittest.TestCase):
    def test_migration_rebinds_execution_paths_to_the_new_epoch(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = SyntheticRuntime(root)
            fixture.bootstrap()
            new_root = root / "new-execution"
            plan = migration_plan(
                fixture.candidate,
                fixture.execution,
                new_root,
            )
            plan_path = root / "MIGRATION_PLAN.json"
            write_json(plan_path, plan)

            migration_apply(plan_path, plan["confirmation_text"])

            state = RuntimeStore(new_root).load_state()
            node = next(
                row
                for row in state["control_plan"]["nodes"]
                if row["node_id"] == "NODE_A"
            )
            self.assertEqual(
                node["allowed_write_paths"],
                [str(new_root / "workspace")],
            )
            self.assertNotIn(
                str(fixture.execution),
                "\n".join(node["allowed_write_paths"]),
            )

    def test_current_runtime_epoch_uses_authoritative_sqlite_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = SyntheticRuntime(root)
            fixture.bootstrap()
            legacy_before = tree_sha256(fixture.execution)

            plan = migration_plan(
                fixture.candidate,
                fixture.execution,
                root / "new-execution",
            )

            self.assertEqual(plan["program_id"], fixture.program_id)
            self.assertEqual(
                plan["source"]["legacy_state_source"],
                "SQLITE_EVENT_STORE",
            )
            self.assertEqual(
                plan["source"]["legacy_runtime_verification"]["status"],
                "PASS",
            )
            classifications = Counter(
                row["classification"]
                for row in plan["node_classifications"]
            )
            self.assertEqual(
                classifications["REVERIFY_REQUIRED"],
                5,
            )
            self.assertEqual(
                classifications["NOT_STARTED"],
                len(fixture.node_ids) + 1,
            )
            self.assertEqual(
                tree_sha256(fixture.execution),
                legacy_before,
            )
            self.assertFalse((root / "new-execution").exists())

    def test_migration_preserves_sources_and_restores_no_pass_or_authority(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = SyntheticRuntime(root)
            legacy = root / "legacy-execution"
            write_json(
                legacy / "control_plane/state/CONTROL_STATE.json",
                {
                    "schema_version": "legacy",
                    "program_id": fixture.program_id,
                    "completed_nodes": [
                        "START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW",
                        "START_PACKAGE_HUMAN_APPROVAL",
                    ],
                    "execution_authorization_status": "GRANTED",
                },
            )
            write_json(
                legacy
                / "control_plane/authorizations/LEGACY_AUTHORIZATION.json",
                {"status": "GRANTED"},
            )
            write_json(
                legacy
                / "evidence/engineering_dag/START_PACKAGE_HUMAN_APPROVAL.result.json",
                {"status": "PASS"},
            )
            new_root = root / "new-execution"
            candidate_before = tree_sha256(fixture.candidate)
            legacy_before = tree_sha256(legacy)
            plan = migration_plan(
                fixture.candidate, legacy, new_root
            )
            self.assertFalse(new_root.exists())
            plan_path = root / "MIGRATION_PLAN.json"
            write_json(plan_path, plan)
            result = migration_apply(
                plan_path, plan["confirmation_text"]
            )

            self.assertEqual(result["status"], "PASS")
            self.assertFalse(result["legacy_authorizations_imported"])
            self.assertFalse(result["historical_pass_restored"])
            self.assertFalse(result["target_code_executed"])
            self.assertEqual(tree_sha256(fixture.candidate), candidate_before)
            self.assertEqual(tree_sha256(legacy), legacy_before)
            state = RuntimeStore(new_root).load_state()
            self.assertIsNone(state["authorization"])
            self.assertEqual(state["completed_nodes"], [])
            self.assertFalse(state["driver"]["runtime_verified"])
            self.assertFalse(
                (
                    new_root
                    / "control_plane/authorizations/LEGACY_AUTHORIZATION.json"
                ).exists()
            )
            self.assertEqual(verify_run(new_root)["status"], "PASS")

    def test_migration_status_and_plan_stop_at_fresh_bootstrap_gate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = SyntheticRuntime(root)
            legacy = root / "legacy-execution"
            write_json(
                legacy / "control_plane/state/CONTROL_STATE.json",
                {
                    "schema_version": "legacy",
                    "program_id": fixture.program_id,
                    "completed_nodes": [],
                },
            )
            new_root = root / "new-execution"
            plan = migration_plan(
                fixture.candidate, legacy, new_root
            )
            plan_path = root / "MIGRATION_PLAN.json"
            write_json(plan_path, plan)
            migration_apply(plan_path, plan["confirmation_text"])

            decision = plan_next(new_root)
            report = status(new_root)
            self.assertEqual(decision["decision"], "HUMAN_GATE")
            self.assertEqual(
                decision["human_gate_id"],
                "MIGRATION_BOOTSTRAP_REVERIFICATION_REQUIRED",
            )
            self.assertEqual(report["highest_touched"], None)
            self.assertEqual(report["highest_locally_closed"], None)
            self.assertEqual(
                report["authorization"]["status"], "NOT_GRANTED"
            )

            bundle = bootstrap_plan(None, new_root)
            self.assertEqual(
                bundle["bootstrap_target_kind"], "MIGRATED_EPOCH"
            )
            bundle_path = root / "MIGRATED_BOOTSTRAP_BUNDLE.json"
            write_json(bundle_path, bundle)
            applied = bootstrap_apply(
                bundle_path, bundle["confirmation_text"]
            )
            self.assertTrue(applied["driver_runtime_verified"])
            self.assertFalse(applied["workpacks_executed"])
            after_bootstrap = plan_next(new_root)
            self.assertEqual(
                after_bootstrap["reason"]["code"],
                "COMMAND_OVERLAY_REQUIRED",
            )
