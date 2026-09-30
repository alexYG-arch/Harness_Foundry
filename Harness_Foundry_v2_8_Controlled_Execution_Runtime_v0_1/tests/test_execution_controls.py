"""A3 advancement, retry/fix, recovery, fencing, and hard-stop tests."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from harness_foundry_runtime.engine import (
    _execute_attempt,
    _load_authorized_manifest,
    _write_scope_fingerprint,
    advance_one,
    advance_until_gate,
    authorization_revoke,
    plan_next,
    resume,
    status,
    verify_run,
)
from harness_foundry_runtime.store import RuntimeStore
from harness_foundry_runtime.util import write_json

from support import SyntheticRuntime


class ExecutionControlTests(unittest.TestCase):
    def test_a3_advances_multiple_nodes_without_per_node_confirmation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            fixture.authorize()
            result = advance_until_gate(fixture.execution)

            self.assertEqual(result["status"], "STOPPED_AT_GATE")
            self.assertEqual(result["transitions_committed"], 2)
            self.assertEqual(
                result["stop"]["human_gate_id"],
                "WAIT_REAL_TARGET_INSTALL_AUTHORIZATION",
            )
            report = status(fixture.execution)
            self.assertEqual(
                report["locally_closed_nodes"][-2:],
                ["NODE_A", "NODE_B"],
            )
            self.assertFalse(report["real_target_install_allowed"])
            self.assertEqual(verify_run(fixture.execution)["status"], "PASS")

    def test_transition_budget_stops_before_next_node(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            fixture.authorize(max_transitions=1)
            result = advance_until_gate(fixture.execution)
            self.assertEqual(result["transitions_committed"], 1)
            self.assertEqual(
                result["stop"]["reason"]["code"],
                "TRANSITION_BUDGET_EXHAUSTED",
            )

    def test_retry_only_for_allowlisted_cleaned_transient_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            fixture.authorize(
                node_ids=["NODE_A"],
                modes={"NODE_A": "retry"},
            )
            result = advance_one(fixture.execution)
            self.assertEqual(result["status"], "PASS")
            report = status(fixture.execution)
            self.assertEqual(report["budget"]["loop_rounds_used"], 1)

    def test_acceptance_failure_enters_finding_and_bounded_fix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            fixture.authorize(
                node_ids=["NODE_A"],
                modes={"NODE_A": "repair"},
            )
            result = advance_one(fixture.execution)
            self.assertEqual(result["status"], "PASS")
            state = RuntimeStore(fixture.execution).load_state()
            finding_events = [
                event
                for event in RuntimeStore(fixture.execution).events()
                if event["event_type"] == "ACCEPTANCE_FINDING_RECORDED"
            ]
            self.assertEqual(len(finding_events), 1)
            self.assertEqual(state["loop_rounds_used"], 1)

    def test_fix_budget_is_renewed_after_each_workpack_promotion(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            fixture.authorize(
                modes={
                    "NODE_A": "repair",
                    "NODE_B": "repair",
                },
                max_loop_rounds=1,
            )

            result = advance_until_gate(fixture.execution)

            self.assertEqual(result["status"], "STOPPED_AT_GATE")
            self.assertEqual(result["transitions_committed"], 2)
            report = status(fixture.execution)
            self.assertEqual(
                report["locally_closed_nodes"][-2:],
                ["NODE_A", "NODE_B"],
            )
            self.assertEqual(report["budget"]["loop_rounds_used"], 2)
            self.assertEqual(
                report["budget"]["active_workpack_loop_rounds_used"],
                0,
            )

    def test_review_identity_is_read_only_at_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            fixture.authorize(
                node_ids=["NODE_A"],
                modes={"NODE_A": "review_mutates"},
            )

            result = advance_one(fixture.execution)

            self.assertEqual(result["status"], "HARD_STOP")
            self.assertEqual(
                result["hard_stop"]["code"], "REVIEW_MUTATED_TARGET"
            )
            self.assertEqual(
                result["unique_return_path"], "HUMAN_REVIEW_REQUIRED"
            )

    def test_resume_preserves_pre_review_mutation_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            fixture.authorize(node_ids=["NODE_A"])
            store = RuntimeStore(fixture.execution)
            state = store.load_state()
            node = next(
                item
                for item in state["control_plan"]["nodes"]
                if item["node_id"] == "NODE_A"
            )
            store.reserve(
                "NODE_A",
                "ATTEMPT-REVIEW-CRASH",
                expected_revision=state["revision"],
            )
            before = _write_scope_fingerprint(
                store.load_state(), node
            )

            def seed_crashed_review(current):
                attempt = current["active_attempt"]
                attempt["loop_round"] = 0
                attempt["review_scope_snapshots"] = {
                    "WP-NODE_A": {
                        "loop_round": 0,
                        "fingerprint": before,
                    }
                }
                attempt["receipts"] = [
                    {
                        "command_id": f"NODE_A-{stage}",
                        "workpack_id": "WP-NODE_A",
                        "stage": stage.lower(),
                        "status": "PASS",
                    }
                    for stage in ("EXECUTE", "POSTFLIGHT", "REVIEW")
                ]

            store.append(
                "TEST_CRASH_AFTER_REVIEW_RECEIPT",
                {},
                mutate=seed_crashed_review,
            )
            (fixture.workspace / "review-mutated").write_text(
                "forbidden", encoding="utf-8"
            )

            result = resume(fixture.execution)

            self.assertEqual(result["status"], "HARD_STOP")
            self.assertEqual(
                result["hard_stop"]["code"], "REVIEW_MUTATED_TARGET"
            )

    def test_no_progress_fix_hard_stops_with_one_return_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            fixture.authorize(
                node_ids=["NODE_A"],
                modes={"NODE_A": "no_progress"},
            )
            result = advance_one(fixture.execution)
            self.assertEqual(result["status"], "HARD_STOP")
            self.assertEqual(
                result["hard_stop"]["code"], "NO_PROGRESS_DETECTED"
            )
            self.assertEqual(
                result["unique_return_path"],
                "RETURN_TO_FINDING_REPAIR_GATE",
            )

    def test_manifest_hash_drift_is_a_hard_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            fixture.authorize(node_ids=["NODE_A"])
            binding = RuntimeStore(fixture.execution).load_state()[
                "authorization"
            ]["command_manifests"]["NODE_A"]
            Path(binding["path"]).write_text("{}\n", encoding="utf-8")
            result = advance_one(fixture.execution)
            self.assertEqual(result["status"], "HARD_STOP")
            self.assertEqual(
                result["hard_stop"]["code"], "COMMAND_MANIFEST_HASH_DRIFT"
            )

    def test_missing_expired_revoked_and_out_of_node_authority_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            fixture.register_overlays(node_ids=["NODE_A"])
            self.assertEqual(
                plan_next(fixture.execution)["reason"]["code"],
                "AUTHORIZATION_MISSING",
            )
            fixture.authorize(node_ids=["NODE_A"])
            store = RuntimeStore(fixture.execution)

            def expire(state):
                state["authorization"]["expires_at"] = (
                    "2000-01-01T00:00:00Z"
                )

            store.append("TEST_EXPIRE_AUTHORIZATION", {}, mutate=expire)
            self.assertEqual(
                plan_next(fixture.execution)["reason"]["code"],
                "AUTHORIZATION_EXPIRED",
            )

        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            fixture.authorize(node_ids=["NODE_A"])
            authorization_id = RuntimeStore(
                fixture.execution
            ).load_state()["authorization"]["authorization_id"]
            authorization_revoke(
                fixture.execution, authorization_id, "test"
            )
            self.assertEqual(
                plan_next(fixture.execution)["reason"]["code"],
                "AUTHORIZATION_REVOKED",
            )

        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            fixture.authorize(node_ids=["NODE_A"])
            store = RuntimeStore(fixture.execution)

            def remove_scope(state):
                state["authorization"]["dag_node_ids"] = []

            store.append("TEST_REMOVE_NODE_SCOPE", {}, mutate=remove_scope)
            self.assertEqual(
                plan_next(fixture.execution)["reason"]["code"],
                "AUTHORIZATION_NODE_SCOPE_MISMATCH",
            )

    def test_single_active_attempt_and_stale_fencing_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            fixture.authorize(node_ids=["NODE_A"])
            store = RuntimeStore(fixture.execution)
            state = store.load_state()
            token, _ = store.reserve(
                "NODE_A", "ATTEMPT-ONE", expected_revision=state["revision"]
            )
            with self.assertRaisesRegex(
                RuntimeError, "ACTIVE_ATTEMPT_ALREADY_EXISTS"
            ):
                store.reserve(
                    "NODE_A",
                    "ATTEMPT-TWO",
                    expected_revision=store.load_state()["revision"],
                )
            node = next(
                item
                for item in state["control_plan"]["nodes"]
                if item["node_id"] == "NODE_A"
            )
            manifest = _load_authorized_manifest(
                store.load_state(), node
            )

            def replace_fence(current):
                current["active_attempt"]["fencing_token"] = token + 1

            store.append("TEST_NEW_FENCE", {}, mutate=replace_fence)
            result = _execute_attempt(
                store,
                node,
                manifest,
                attempt_id="ATTEMPT-ONE",
                fencing_token=token,
                resumed=True,
            )
            self.assertEqual(
                result["hard_stop"]["code"], "STALE_FENCING_TOKEN"
            )

    def test_resume_replays_idempotent_but_stops_unknown_non_idempotent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            fixture.authorize(node_ids=["NODE_A"])
            store = RuntimeStore(fixture.execution)
            state = store.load_state()
            token, _ = store.reserve(
                "NODE_A", "ATTEMPT-CRASH", expected_revision=state["revision"]
            )

            def mark_started(current):
                current["active_attempt"]["current_command"] = {
                    "command_id": "NODE_A-EXECUTE",
                    "idempotent": True,
                }

            store.append("TEST_SIMULATED_CRASH", {}, mutate=mark_started)
            result = resume(fixture.execution)
            self.assertEqual(result["status"], "PASS")

        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            fixture.authorize(node_ids=["NODE_A"])
            store = RuntimeStore(fixture.execution)
            state = store.load_state()
            store.reserve(
                "NODE_A", "ATTEMPT-UNKNOWN", expected_revision=state["revision"]
            )

            def mark_non_idempotent(current):
                current["active_attempt"]["current_command"] = {
                    "command_id": "SIDE-EFFECT",
                    "idempotent": False,
                }

            store.append(
                "TEST_SIMULATED_UNKNOWN_OUTCOME",
                {},
                mutate=mark_non_idempotent,
            )
            result = resume(fixture.execution)
            self.assertEqual(
                result["hard_stop"]["code"],
                "UNKNOWN_NON_IDEMPOTENT_OUTCOME",
            )

    def test_ledger_tamper_and_oscillation_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            database = (
                fixture.execution / "control_plane/factory.sqlite3"
            )
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    "UPDATE events SET payload_json='{}' WHERE seq=1"
                )
                connection.commit()
            report = verify_run(fixture.execution)
            codes = {
                item["code"] for item in report["blocking_findings"]
            }
            self.assertTrue(
                {"EVENT_HASH_MISMATCH", "EVENT_STATE_HASH_MISMATCH"}
                & codes
            )

        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            fixture.authorize(node_ids=["NODE_A"])
            store = RuntimeStore(fixture.execution)

            def oscillate(state):
                state["state_path_history"] = ["A", "B", "A"]

            store.append("TEST_OSCILLATION", {}, mutate=oscillate)
            result = advance_one(fixture.execution)
            self.assertEqual(
                result["hard_stop"]["code"],
                "STATE_OSCILLATION_DETECTED",
            )

    def test_p3_na_and_real_install_remain_human_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary), include_p3=True)
            fixture.bootstrap()
            decision = plan_next(fixture.execution)
            self.assertEqual(decision["decision"], "HUMAN_GATE")
            self.assertEqual(
                decision["human_gate_id"],
                "P3_IMPLEMENT_OR_APPROVED_NA_SELECTION",
            )

        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            fixture.authorize()
            advance_until_gate(fixture.execution)
            decision = plan_next(fixture.execution)
            self.assertEqual(
                decision["human_gate_id"],
                "WAIT_REAL_TARGET_INSTALL_AUTHORIZATION",
            )
