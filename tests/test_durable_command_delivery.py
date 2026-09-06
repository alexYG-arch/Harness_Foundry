"""Durable command intent/outcome tests, including actual process restarts."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Barrier
import unittest

from harness_foundry_factory.control_kernel import (
    ControlKernelError, GenericTransitionEngine, InjectedKernelCrash, prepare_parent_authorization_challenge,
    rebuild_control_projections,
)
from harness_foundry_factory.store import ControlEventStore
from harness_foundry_factory.models import StateConflictError
from tests import test_runtime_advance_cli as support


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/durable_transition_process_fixture.py"


class DurableCommandDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database = self.root / "control.sqlite3"
        self.marker = self.root / "effects.txt"
        self.program_id = "PROGRAM-DURABLE-TEST"
        self.store = ControlEventStore(self.database)
        self.engine = GenericTransitionEngine(self.store, {})
        self.parent = support.parent(self.program_id)
        challenge = prepare_parent_authorization_challenge(self.parent, expected_bindings=support.bindings())
        self.engine.register_approved_parent_authorization(
            self.parent, challenge, {
                "decision": "APPROVE", "challenge_sha256": challenge["challenge_sha256"],
                "approved_by": {"type": "HUMAN_VIA_CODEX_CHAT",
                                "chat_thread_id": "TEST-ONLY-THREAD", "turn_id": "TEST-ONLY-TURN"},
                "approved_at": support.NOW,
            }, created_at=support.NOW,
        )
        self.transition = support.transition("T-PROCESS", "STATE")
        self.transition["command_contract"]["delivery_mode"] = "DURABLE_SINGLE_ATTEMPT"
        self.transition["result_schema"]["properties"]["exit_code"] = {"type": "integer"}

    def _run(self, **overrides):
        request = {
            "database": str(self.database), "marker": str(self.marker),
            "program_id": self.program_id,
            "parent_authorization_id": self.parent["authorization_id"],
            "transition": self.transition, "inputs": {"approved": True},
            "created_at": support.NOW, **overrides,
        }
        path = self.root / "request.json"
        path.write_text(json.dumps(request))
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run([sys.executable, "-B", str(FIXTURE), "execute", str(path)],
                              env=environment, capture_output=True, text=True, timeout=60)

    def _result(self, completed):
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)

    def test_intent_is_committed_before_a_real_process_runs(self):
        result = self._result(self._run(require_persisted_intent=True))
        self.assertEqual(result["status"], "COMMITTED")
        self.assertEqual(result["result"]["exit_code"], 0)
        events = self.store.list_events(self.program_id)
        types = [event["event_type"] for event in events]
        self.assertLess(types.index("TRANSITION_ATTEMPT_STARTED"), types.index("COMMAND_RESULT_OBSERVED"))
        self.assertLess(types.index("COMMAND_RESULT_OBSERVED"), types.index("TRANSITION_COMMITTED"))
        self.assertEqual(self.store.verify_stream(self.program_id)["status"], "PASS")

    def test_process_restart_finalizes_observed_result_without_replaying_effect(self):
        crashed = self._run(fault="after-observation")
        self.assertNotEqual(crashed.returncode, 0)
        self.assertEqual(self.marker.read_text(), "APPLIED\n")
        result = self._result(self._run(resume=True, forbid_command=True))
        self.assertEqual(result["status"], "COMMITTED")
        self.assertEqual(self.marker.read_text(), "APPLIED\n")
        projection = rebuild_control_projections(self.store.list_events(self.program_id))
        self.assertEqual(projection["human_cost_result"]["derived_grant_count"], 1)
        self.assertEqual(projection["human_cost_result"]["resume_count"], 1)

    def test_unobserved_side_effect_is_not_replayed_after_process_death(self):
        crashed = self._run(fault="after-side-effect")
        self.assertEqual(crashed.returncode, 18)
        stopped = self._result(self._run(forbid_command=True))
        self.assertEqual(stopped["stop_reason"], "COMMAND_OUTCOME_PENDING")
        self.assertEqual(stopped["reason_code"], "COMMAND_OUTCOME_UNRESOLVED")
        self.assertEqual(self.marker.read_text(), "APPLIED\n")
        self.assertFalse(any(event["event_type"] == "TRANSITION_COMMITTED"
                             for event in self.store.list_events(self.program_id)))

    def test_nonzero_exit_remains_terminal_on_reentry(self):
        first = self._result(self._run(exit_code=7))
        self.assertEqual(first["stop_reason"], "DETERMINISTIC_VALIDATION_FAILURE")
        second = self._result(self._run(forbid_command=True))
        self.assertEqual(second["reason_code"], "LOCAL_PROCESS_NONZERO_EXIT")
        self.assertEqual(self.marker.read_text(), "APPLIED\n")

    def test_pending_attempt_cannot_be_rebound_to_changed_inputs(self):
        self.assertNotEqual(self._run(fault="after-observation").returncode, 0)
        changed = self._run(inputs={"approved": False}, forbid_command=True)
        self.assertNotEqual(changed.returncode, 0)
        self.assertIn("pending command input or contract changed", changed.stderr)
        self.assertEqual(self.marker.read_text(), "APPLIED\n")

    def test_observed_result_cannot_be_rebound_by_dropping_delivery_mode(self):
        self.assertNotEqual(self._run(fault="after-observation").returncode, 0)
        changed = deepcopy(self.transition)
        changed["command_contract"].pop("delivery_mode")
        completed = self._run(transition=changed, forbid_command=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("pending command input or contract changed", completed.stderr)

    def _effect(self, context):
        completed = subprocess.run([sys.executable, "-B", str(FIXTURE), "effect", str(self.marker), "0"],
                                   capture_output=True, text=True, check=False, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return {"status": "PASS", "artifact_id": "TEST-EFFECT", "exit_code": 0}

    def test_concurrent_reservations_only_dispatch_one_process(self):
        barrier = Barrier(2)

        class BarrierStore(ControlEventStore):
            def append_batch(self, *args, **kwargs):
                if kwargs.get("require_new"):
                    barrier.wait(timeout=10)
                return super().append_batch(*args, **kwargs)

        # Synchronize only the competing intent inserts, not either command or
        # its result. Both clients read the same pre-attempt state.
        stores = [BarrierStore(self.database), BarrierStore(self.database)]

        def run(store):
            engine = GenericTransitionEngine(store, {"STATE": self._effect})
            try:
                return engine.execute_transition(self.program_id, self.parent["authorization_id"],
                                                 self.transition, {"approved": True}, created_at=support.NOW)["status"]
            except StateConflictError:
                return "LOST_RESERVATION"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(run, stores))
        self.assertCountEqual(outcomes, ["COMMITTED", "LOST_RESERVATION"])
        self.assertEqual(self.marker.read_text(), "APPLIED\n")
        self.assertEqual(self.store.verify_stream(self.program_id)["status"], "PASS")

    def test_observed_transient_failure_retains_declared_retry_budget(self):
        self.transition["retry_policy"]["max_retries"] = 1
        engine = GenericTransitionEngine(self.store, {"STATE": lambda context: {
            "status": "TEMPORARY_FAILURE", "artifact_id": "TEST-NOT-LAUNCHED",
            "reason_code": "DECLARED_TRANSIENT_BEFORE_PROCESS",
        }})
        with self.assertRaises(InjectedKernelCrash):
            engine.execute_transition(self.program_id, self.parent["authorization_id"], self.transition,
                                      {"approved": True}, created_at=support.NOW, inject_crash_after_command=True)
        self.assertFalse(self.marker.exists())
        restarted = GenericTransitionEngine(ControlEventStore(self.database), {"STATE": self._effect})
        result = restarted.execute_transition(self.program_id, self.parent["authorization_id"], self.transition,
                                              {"approved": True}, created_at=support.NOW, resume=True)
        self.assertEqual(result["status"], "COMMITTED")
        self.assertEqual(self.marker.read_text(), "APPLIED\n")
        cost = rebuild_control_projections(self.store.list_events(self.program_id))["human_cost_result"]
        self.assertEqual(cost["derived_grant_count"], 2)
        self.assertEqual(cost["bounded_retry_count"], 1)

    def test_other_node_cannot_run_while_a_command_outcome_is_unresolved(self):
        self.assertEqual(self._run(fault="after-side-effect").returncode, 18)
        other = deepcopy(self.transition)
        other["transition_id"] = "T-OTHER"
        engine = GenericTransitionEngine(self.store, {"STATE": self._effect})
        with self.assertRaises(ControlKernelError) as caught:
            engine.execute_transition(self.program_id, self.parent["authorization_id"], other,
                                      {"approved": True}, created_at=support.NOW)
        self.assertEqual(caught.exception.code, "COMMAND_ATTEMPT_PENDING")
        self.assertEqual(self.marker.read_text(), "APPLIED\n")

    def test_revoked_parent_does_not_resume_or_dispatch_a_pending_command(self):
        self.assertNotEqual(self._run(fault="after-observation").returncode, 0)
        self.engine.revoke_parent_authorization(self.program_id, self.parent["authorization_id"],
                                                created_at=support.NOW)
        completed = self._run(forbid_command=True, resume=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("no active Parent Risk Envelope", completed.stderr)
        self.assertEqual(self.marker.read_text(), "APPLIED\n")

    def test_runtime_advance_can_finalize_observation_without_an_adapter(self):
        self.assertNotEqual(self._run(fault="after-observation").returncode, 0)
        engine = GenericTransitionEngine(ControlEventStore(self.database), {})
        result = engine.runtime_advance_until_gate(
            self.program_id, self.parent["authorization_id"],
            {self.transition["transition_id"]: self.transition},
            {self.transition["transition_id"]: {"approved": True}},
            start_transition_id=self.transition["transition_id"], created_at=support.NOW,
            max_transitions=1, expected_bindings=support.bindings(),
            expected_control_state_sha256=engine.control_state_sha256(self.program_id),
        )
        self.assertEqual(result["transition_receipts"][0]["status"], "COMMITTED")
        self.assertEqual(self.marker.read_text(), "APPLIED\n")

    def test_completed_node_reentry_does_not_replay_or_block_on_another_pending_node(self):
        first = deepcopy(self.transition)
        first["transition_id"] = "T-FIRST"
        engine = GenericTransitionEngine(self.store, {"STATE": self._effect})
        engine.execute_transition(self.program_id, self.parent["authorization_id"], first,
                                  {"approved": True}, created_at=support.NOW)
        self.assertEqual(self._run(fault="after-side-effect").returncode, 18)
        reentry = engine.execute_transition(self.program_id, self.parent["authorization_id"], first,
                                            {"approved": True}, created_at=support.NOW)
        self.assertEqual(reentry["status"], "ALREADY_COMMITTED")
        self.assertEqual(self.marker.read_text(), "APPLIED\nAPPLIED\n")

    def test_unknown_delivery_mode_is_rejected_before_dispatch(self):
        before = self.store.list_events(self.program_id)
        for mode in ("DURABLE_SINGEL_ATTEMPT", ["DURABLE_SINGLE_ATTEMPT"]):
            with self.subTest(mode=mode):
                changed = deepcopy(self.transition)
                changed["command_contract"]["delivery_mode"] = mode
                engine = GenericTransitionEngine(self.store, {"STATE": self._effect})
                with self.assertRaises(ControlKernelError) as caught:
                    engine.execute_transition(self.program_id, self.parent["authorization_id"], changed,
                                              {"approved": True}, created_at=support.NOW)
                self.assertEqual(caught.exception.code, "TRANSITION_CONTRACT_INVALID")
        self.assertFalse(self.marker.exists())
        self.assertEqual(before, self.store.list_events(self.program_id))

    def test_pending_reentry_does_not_write_over_a_live_callers_event_tip(self):
        observed = []

        def command(context):
            before = self.store.list_events(self.program_id)
            reader = GenericTransitionEngine(ControlEventStore(self.database), {})
            pending = reader.execute_transition(self.program_id, self.parent["authorization_id"], self.transition,
                                                {"approved": True}, created_at=support.NOW)
            observed.append((pending, before == self.store.list_events(self.program_id)))
            return self._effect(context)

        engine = GenericTransitionEngine(self.store, {"STATE": command})
        result = engine.execute_transition(self.program_id, self.parent["authorization_id"], self.transition,
                                           {"approved": True}, created_at=support.NOW)
        self.assertEqual(result["status"], "COMMITTED")
        self.assertEqual(observed[0][0]["stop_reason"], "COMMAND_OUTCOME_PENDING")
        self.assertTrue(observed[0][0]["may_still_be_running"])
        self.assertFalse(observed[0][0]["human_authority_required"])
        self.assertTrue(observed[0][1])
        self.assertEqual(self.marker.read_text(), "APPLIED\n")


if __name__ == "__main__":
    unittest.main()
