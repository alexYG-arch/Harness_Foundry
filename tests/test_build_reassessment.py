"""Historical observation correction against disposable control state.

Synthetic Codex streams never invoke a model. Independent verifiers are real
local Python processes, not native sandbox or real-model qualification.
"""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_build_runtime as fixture
from harness_foundry_factory.build_runtime import (
    BuildController, approve_build_authorization, prepare_build_authorization,
    record_source_snapshot, resolve_build_attempt, revoke_build_authorization,
)
from harness_foundry_factory.build_state import attempt_budget, project_budget_attempts, project_readback_attempts
from harness_foundry_factory.build_authoring import record_build_plan_proposal
from harness_foundry_factory.build_reassessment import (
    capture_identity, reassess_build_attempt, replay_completed, runtime_identity,
)
from harness_foundry_factory.build_types import (
    IdempotencyConflictError, RequestValidationError, RevisionConflictError,
)
from harness_foundry_factory.coding_events import observe_coding_process
from harness_foundry_factory.process_observation import CommandObservation


ROWS = [
    {"type": "thread.started", "thread_id": "TEST-ONLY-RECOVERY"},
    {"type": "turn.started"},
    {"type": "error", "message": "Reconnecting... 2/5 (stream disconnected before completion: TEST reset)"},
    {"type": "turn.completed", "usage": {"input_tokens": 7, "output_tokens": 3}},
]


class BuildReassessmentTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.BuildRuntimeTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.plan["workpacks"][0]["executor"] = "CODEX"
        del self.f.plan["workpacks"][0]["local_argv"]
        self.f.scope.update(model="TEST-NOT-A-MODEL", allow_model_service=True)
        self.f.prepare()
        self.model_calls = 0
        self.configuration = None
        self.local = fixture.FixtureProcessRunner()
        self.controller = BuildController(self.f.store, self.f.program,
            runner=self.synthetic_producer, clock=fixture.CLOCK)

    def synthetic_producer(self, invocation, before_dispatch):
        before_dispatch()
        self.assertEqual(invocation["executor"], "CODEX")
        self.model_calls += 1
        (self.f.workspace / "src/reader.py").write_text(fixture.GOOD_READER)
        raw = b"".join((json.dumps(row) + "\n").encode() for row in ROWS)
        capture = {"exit_code": 0, "timed_out": False, "capture_error": None,
            "stream_bytes": {"stdout": len(raw), "stderr": 0}, "stdout": "", "stderr": "",
            "output_truncated": True, "stdout_truncated": True, "stderr_truncated": False}
        # Represent the old receiver's persisted false failure. Inline previews
        # were clipped, while the complete protocol capture is still available.
        result = observe_coding_process(raw, exit_code=0)
        for key in tuple(result):
            if key.startswith("reconnect"):
                result.pop(key)
        result.update(status="MODEL_PROCESS_FAILED", reason_code="CODEX_PROCESS_OR_TURN_FAILED", capture=capture)
        journal = CommandObservation(invocation["observation_root"], invocation["command_id"], "CODEX")
        try:
            if self.configuration is not None:
                journal.model_configuration(self.configuration)
                capture["model_configuration"] = deepcopy(self.configuration)
                result["model_configuration"] = deepcopy(self.configuration)
            journal.write("stdout", raw)
            journal.captured(capture)
            journal.finished(result)
        finally:
            journal.close()
        return result

    def blocked(self, *, configuration=False, expected_status="BLOCKED"):
        if configuration:
            self.configuration = {"model_policy": "FIXED", "model": "TEST-NOT-A-MODEL",
                "reasoning_effort": "high", "model_service": {"provider": "openai"}}
        for index in range(3):
            self.controller.advance(self.f.prepared_id, advance_mode="ONE_ATTEMPT")
            attempts, _ = self.controller._state(self.f.events(), self.f.prepared_id)
            self.attempt = list(attempts.values())[-1]
            self.assertEqual(self.attempt["status"], expected_status)
            if index < 2:
                resolve_build_attempt(self.f.store, self.f.program, self.f.prepared_id,
                    self.attempt["attempt_id"], reason="TEST synthetic legacy observation",
                    human_message_ref="TEST-ONLY", **self.f.kwargs("resolve-" + str(index)))
        self.command = next(row["payload"] for row in reversed(self.f.events())
                            if row["event_type"] == "BUILD_COMMAND_OBSERVED")
        self.evidence = {"runtime_identity": runtime_identity(),
            "capture_files": capture_identity(self.command),
            "artifacts": self.controller._artifacts(self.f.workspace, self.f.plan["workpacks"][0]["artifacts"])}
        self.original_events = self.f.events()
        self.original_calls = self.model_calls
        self.controller.runner = self.only_checks

    def only_checks(self, invocation, before_dispatch):
        self.assertEqual((invocation["executor"], invocation["phase"]), ("LOCAL", "VERIFICATION"))
        return self.local(invocation, before_dispatch)

    def reassess(self, **overrides):
        arguments = {"evidence": self.evidence, "human_message_ref": "TEST-ONLY-RECOVERY-GRANT",
                     **self.f.kwargs("reassess")}
        arguments.update(overrides)
        return reassess_build_attempt(self.controller, self.f.prepared_id,
            self.attempt["attempt_id"], **arguments)

    def budget(self, prepared_id=None):
        return attempt_budget(self.f.scope, list(project_budget_attempts(
            self.f.events(), prepared_id or self.f.prepared_id).values()))

    def advance(self):
        return self.controller.advance(self.f.prepared_id, advance_mode="ONE_ATTEMPT")

    def assert_preserved(self, budget):
        self.assertEqual(self.model_calls, self.original_calls)
        self.assertEqual(self.budget(), budget)
        self.assertEqual(self.f.events()[:len(self.original_events)], self.original_events)

    def test_exhausted_legacy_attempt_runs_only_missing_checks_and_preserves_history(self):
        self.blocked()
        budget = self.budget()
        self.assertEqual(budget["task_attempts_remaining"][self.attempt["workpack_id"]], 0)
        self.assertNotIn("model-configuration.json", self.evidence["capture_files"])
        event = self.reassess()
        self.assertFalse(event["payload"]["old_output_accepted"])
        self.assertEqual(self.local.invocations, [])
        self.advance()
        attempts, accepted = self.controller._state(self.f.events(), self.f.prepared_id)
        self.assertEqual(attempts[self.attempt["attempt_id"]]["status"], "ACCEPTED")
        self.assertIn(self.attempt["workpack_id"], accepted)
        self.assertEqual(len(self.local.invocations), 2)
        self.assert_preserved(budget)

    def test_legacy_rejected_process_classification_is_corrected_without_retry(self):
        original = BuildController._failure_status
        def legacy_classification(result):
            if result.get("status") == "MODEL_PROCESS_FAILED":
                return "REJECTED"
            return original(result)
        with patch.object(BuildController, "_failure_status", side_effect=legacy_classification):
            self.blocked(expected_status="REJECTED")
        budget = self.budget()
        self.reassess(); self.advance()
        self.assertIn(self.attempt["workpack_id"], self.controller._state(self.f.events(), self.f.prepared_id)[1])
        self.assert_preserved(budget)

    def test_configuration_receipt_is_bound_and_compatible_with_reassessment(self):
        self.blocked(configuration=True)
        self.assertIn("model-configuration.json", self.evidence["capture_files"])
        recovered = replay_completed(self.command, self.evidence["capture_files"])
        self.assertEqual(recovered["model_configuration"], self.configuration)
        budget = self.budget()
        self.reassess(); self.advance()
        self.assertIn(self.attempt["workpack_id"], self.controller._state(self.f.events(), self.f.prepared_id)[1])
        self.assert_preserved(budget)

    def test_missing_declared_configuration_receipt_cannot_be_reapproved_as_legacy(self):
        self.blocked(configuration=True)
        (Path(self.command["observation_root"]) / "model-configuration.json").unlink()
        self.evidence["capture_files"] = capture_identity(self.command)
        with self.assertRaises(RequestValidationError):
            self.reassess()
        self.assertEqual(self.f.events(), self.original_events)

    def test_receipt_wrong_command_or_configuration_refuses_even_with_fresh_hashes(self):
        self.blocked(configuration=True)
        path = Path(self.command["observation_root"]) / "model-configuration.json"
        original = path.read_bytes()
        for field in ("binding", "configuration"):
            with self.subTest(field=field):
                document = json.loads(original)
                if field == "binding":
                    document[field]["command_id"] = "OTHER-COMMAND"
                else:
                    document[field]["model"] = "DIFFERENT-MODEL"
                path.write_text(json.dumps(document))
                self.evidence["capture_files"] = capture_identity(self.command)
                with self.assertRaises(RequestValidationError):
                    self.reassess()
                self.assertEqual(self.f.events(), self.original_events)
        path.write_bytes(original)

    def test_receipt_added_after_legacy_review_is_not_silently_ignored(self):
        self.blocked()
        path = Path(self.command["observation_root"]) / "model-configuration.json"
        path.write_text(json.dumps({"binding": {"command_id": self.command["command_id"], "executor": "CODEX"},
                                    "configuration": {"model": "new"}}))
        with self.assertRaises(RequestValidationError):
            self.reassess()
        self.evidence["capture_files"] = capture_identity(self.command)
        with self.assertRaises(RequestValidationError):
            self.reassess()
        self.assertEqual(self.f.events(), self.original_events)

    def test_configuration_drift_after_recording_blocks_without_check_or_model(self):
        self.blocked(configuration=True)
        budget = self.budget()
        self.reassess()
        path = Path(self.command["observation_root"]) / "model-configuration.json"
        document = json.loads(path.read_text()); document["configuration"]["reasoning_effort"] = "low"
        path.write_text(json.dumps(document))
        self.assertEqual(self.advance()["status"], "BUILD_STOPPED")
        self.assertEqual(self.local.invocations, [])
        self.assert_preserved(budget)

    def test_duplicate_receipt_after_acceptance_or_revocation_does_not_execute(self):
        self.blocked()
        revision = len(self.f.events())
        event = self.reassess(expected_revision=revision)
        self.advance()
        revoke_build_authorization(self.f.store, self.f.program, self.f.prepared_id, **self.f.kwargs("revoke"))
        before = self.f.events(); calls = len(self.local.invocations)
        self.assertEqual(self.reassess(expected_revision=revision), event)
        self.assertEqual(self.f.events(), before)
        self.assertEqual(len(self.local.invocations), calls)
        with self.assertRaises(IdempotencyConflictError):
            self.reassess(expected_revision=revision + 1)
        self.assertEqual(self.model_calls, self.original_calls)

    def test_new_key_cannot_reassess_twice_or_accept_old_result(self):
        self.blocked(); self.reassess()
        before = self.f.events()
        with self.assertRaises(RequestValidationError):
            self.reassess(idempotency_key="different-key")
        self.assertEqual(self.f.events(), before)
        self.assertEqual(self.local.invocations, [])

    def test_same_key_with_different_evidence_cannot_reuse_old_receipt(self):
        self.blocked()
        revision = len(self.f.events())
        self.reassess(expected_revision=revision)
        before = self.f.events()
        changed = {**self.evidence, "artifacts": {}}
        with self.assertRaises(IdempotencyConflictError):
            self.reassess(expected_revision=revision, evidence=changed)
        self.assertEqual(self.f.events(), before)
        self.assertEqual(self.local.invocations, [])

    def test_failure_before_correction_commit_does_not_start_check_or_lose_budget(self):
        self.blocked(); budget = self.budget()
        with patch.object(self.f.store, "append_batch", side_effect=OSError("TEST storage unavailable")):
            with self.assertRaises(OSError):
                self.reassess()
        self.assertEqual(self.f.events(), self.original_events)
        self.assertEqual(self.local.invocations, [])
        self.reassess(); self.advance()
        self.assertIn(self.attempt["workpack_id"], self.controller._state(self.f.events(), self.f.prepared_id)[1])
        self.assert_preserved(budget)

    def test_stale_revision_runtime_capture_or_artifact_identity_does_not_write(self):
        self.blocked()
        with self.assertRaises(RevisionConflictError):
            self.reassess(expected_revision=len(self.original_events) - 1)
        for field, value in (("runtime_identity", "wrong"), ("capture_files", {}), ("artifacts", {})):
            with self.subTest(field=field), self.assertRaises(RequestValidationError):
                self.reassess(evidence={**self.evidence, field: value})
        self.assertEqual(self.f.events(), self.original_events)

    def test_revoked_expired_and_foreign_prepared_cannot_start_reassessment(self):
        self.blocked()
        self.controller.clock = lambda: datetime.fromisoformat("2099-01-01T00:00:00+00:00")
        with self.assertRaisesRegex(RequestValidationError, "expired"):
            self.reassess()
        self.controller.clock = fixture.CLOCK
        with self.assertRaises(RequestValidationError):
            reassess_build_attempt(self.controller, "FOREIGN-PREPARED", self.attempt["attempt_id"],
                evidence=self.evidence, human_message_ref="TEST", **self.f.kwargs("foreign"))
        revoke_build_authorization(self.f.store, self.f.program, self.f.prepared_id, **self.f.kwargs("revoke"))
        with self.assertRaisesRegex(RequestValidationError, "revoked"):
            self.reassess()
        self.assertEqual(self.local.invocations, [])

    def test_source_and_checker_drift_refuses_without_check(self):
        self.blocked()
        for path in (self.f.source / "brief.md", self.f.verifier / "check.py"):
            original = path.read_bytes()
            path.write_bytes(original + b"\n# changed\n")
            with self.subTest(path=path), self.assertRaises(RequestValidationError):
                self.reassess()
            path.write_bytes(original)
        self.assertEqual(self.f.events(), self.original_events)

    def test_current_artifact_drift_after_recording_prevents_check(self):
        self.blocked(); self.reassess()
        (self.f.workspace / "src/reader.py").write_text("changed")
        self.assertEqual(self.advance()["status"], "BUILD_STOPPED")
        self.assertEqual(self.local.invocations, [])

    def test_raw_capture_drift_after_recording_prevents_check(self):
        self.blocked(); self.reassess()
        path = Path(self.command["observation_root"]) / "stdout.bin"
        path.write_bytes(path.read_bytes() + b"\n")
        self.assertEqual(self.advance()["status"], "BUILD_STOPPED")
        self.assertEqual(self.local.invocations, [])
        self.assertEqual(self.f.events()[:len(self.original_events)], self.original_events)

    def test_product_failure_remains_unaccepted_without_unlocking_successor(self):
        self.blocked()
        (self.f.workspace / "src/reader.py").write_text(fixture.BAD_READER)
        self.evidence["artifacts"] = self.controller._artifacts(
            self.f.workspace, self.f.plan["workpacks"][0]["artifacts"])
        budget = self.budget()
        self.reassess(); self.advance()
        attempts, accepted = self.controller._state(self.f.events(), self.f.prepared_id)
        self.assertNotEqual(attempts[self.attempt["attempt_id"]]["status"], "ACCEPTED")
        self.assertNotIn(self.attempt["workpack_id"], accepted)
        self.assertFalse((self.f.workspace / "outputs/summary.json").exists())
        self.assert_preserved(budget)

    def test_completed_check_capture_recovers_without_repeating_that_check(self):
        self.blocked(); self.reassess(); budget = self.budget()
        def crash_after_capture(invocation, before_dispatch):
            result = self.only_checks(invocation, before_dispatch)
            journal = CommandObservation(invocation["observation_root"], invocation["command_id"], "LOCAL")
            try:
                journal.finished(result)
            finally:
                journal.close()
            raise fixture.InjectedControllerCrash()
        self.controller.runner = crash_after_capture
        with self.assertRaises(fixture.InjectedControllerCrash):
            self.advance()
        self.controller.runner = self.only_checks
        self.advance()
        self.assertEqual(len(self.local.invocations), 2)
        self.assertEqual(len({call["command_id"] for call in self.local.invocations}), 2)
        self.assertIn(self.attempt["workpack_id"], self.controller._state(self.f.events(), self.f.prepared_id)[1])
        self.assert_preserved(budget)

    def test_started_check_without_capture_holds_instead_of_redispatch(self):
        self.blocked(); self.reassess(); budget = self.budget()
        dispatched = []
        def crash_without_capture(invocation, before_dispatch):
            before_dispatch()
            dispatched.append(invocation["command_id"])
            raise fixture.InjectedControllerCrash()
        self.controller.runner = crash_without_capture
        with self.assertRaises(fixture.InjectedControllerCrash):
            self.advance()
        self.controller.runner = self.only_checks
        for _ in range(2):
            self.assertEqual(self.advance()["status"], "HELD_UNRESOLVED_ATTEMPT")
        self.assertEqual(len(dispatched), 1)
        self.assertEqual(self.local.invocations, [])
        self.assert_preserved(budget)

    def test_prior_recovery_record_does_not_hide_new_reassessment_completion(self):
        self.blocked()
        self.controller._append("BUILD_ATTEMPT_RECOVERED", deepcopy(self.attempt), len(self.f.events()),
                                self.attempt["attempt_id"] + ":recovered")
        self.reassess(); self.advance()
        self.assertIn(self.attempt["workpack_id"], self.controller._state(self.f.events(), self.f.prepared_id)[1])

    def test_unbound_start_and_missing_human_reference_do_not_write_correction(self):
        self.blocked()
        with self.assertRaises(RequestValidationError):
            self.reassess(human_message_ref="")
        self.controller._append("BUILD_COMMAND_STARTED", {**self.command, "command_id": "UNBOUND"},
                                len(self.f.events()), "unbound-start")
        with self.assertRaisesRegex(RequestValidationError, "unbound command start"):
            self.reassess()
        self.assertEqual(self.local.invocations, [])

    def test_readback_retains_original_failure_and_corrected_observation(self):
        self.blocked(); self.reassess(); self.advance()
        row = project_readback_attempts(self.f.events())[self.attempt["attempt_id"]]
        self.assertEqual(row["status"], "ACCEPTED")
        self.assertFalse(row["reassessment_pending"])
        correction = row["command_reassessments"][0]
        self.assertEqual(correction["original_result"]["status"], "MODEL_PROCESS_FAILED")
        self.assertEqual(correction["result"]["status"], "MODEL_TURN_COMPLETED")
        self.assertFalse(correction["automatic_acceptance"])

    def test_accepted_result_rebind_preserves_all_three_attempts_without_producer(self):
        self.blocked(); self.reassess(); self.advance()
        old = self.f.prepared_id
        new = prepare_build_authorization(self.f.store, self.f.program, self.f.proposal_id, self.f.source_id,
            self.f.scope, rebind_from=old, **self.f.kwargs("rebind"))["event_id"]
        approve_build_authorization(self.f.store, self.f.program, new,
            human_message_ref="TEST-ONLY-NEW-BINDING", **self.f.kwargs("approve-rebind"))
        self.assertEqual(self.budget(new)["attempts_consumed"], 3)
        self.assertIn(self.attempt["workpack_id"], self.controller._state(self.f.events(), new)[1])
        self.assertEqual(self.controller.advance(old)["status"], "BUILD_STOPPED")
        self.assertEqual(self.model_calls, self.original_calls)
        self.assertEqual(len(self.local.invocations), 2)

    def record_plan(self, mutate):
        revised = deepcopy(self.f.plan)
        revised["revision"] += 1
        mutate(revised)
        return record_build_plan_proposal(self.f.store, self.f.ir, revised,
            document_review=self.f.review, **self.f.kwargs("plan-revision-" + str(revised["revision"])))

    def test_unrelated_plan_revision_before_reassessment_only_runs_original_checks(self):
        self.blocked()
        old_proposal = self.attempt["proposal_event_id"]
        budget = self.budget()
        revised = self.record_plan(lambda plan: plan["workpacks"][1].update(
            goal=plan["workpacks"][1]["goal"] + " (TEST implementation clarification)"))
        self.reassess(); self.advance()
        row = project_readback_attempts(self.f.events())[self.attempt["attempt_id"]]
        self.assertEqual(row["status"], "ACCEPTED")
        self.assertEqual(row["proposal_event_id"], revised["event_id"])
        self.assertEqual(row["implementation_proposal_event_id"], old_proposal)
        self.assertEqual(self.command["proposal_event_id"], old_proposal)
        self.assertEqual(row["implementation_commands"][0]["command_id"], self.command["command_id"])
        self.assertEqual(len(self.local.invocations), 2)
        self.assert_preserved(budget)

    def test_goal_revision_after_reassessment_accepts_and_reuses_without_new_calls(self):
        self.blocked(); self.reassess()
        old_proposal = self.attempt["proposal_event_id"]
        revised = self.record_plan(lambda plan: plan["workpacks"][0].update(
            goal=plan["workpacks"][0]["goal"] + " (TEST clearer wording, same requirements)"))
        budget = self.budget()
        self.advance()
        row = project_readback_attempts(self.f.events())[self.attempt["attempt_id"]]
        self.assertEqual(row["status"], "ACCEPTED")
        self.assertEqual(row["proposal_event_id"], revised["event_id"])
        self.assertEqual(row["implementation_proposal_event_id"], old_proposal)
        self.assertEqual(self.command["proposal_event_id"], old_proposal)
        self.assertEqual(row["implementation_commands"][0]["command_id"], self.command["command_id"])
        self.assertEqual(len(self.local.invocations), 2)
        self.assert_preserved(budget)
        # Finish the fixture's still-pending LOCAL successor once. It is new
        # work, not a repeat of the accepted producer or its independent checks.
        self.controller.runner = self.local
        self.assertEqual(self.controller.advance(self.f.prepared_id)["status"], "PLAN_CHECKS_ACCEPTED")
        calls = len(self.local.invocations)
        self.assertEqual(calls, 4)
        final_budget = self.budget()
        self.assertEqual(final_budget["attempts_consumed"], 4)
        for _ in range(2):
            self.assertEqual(self.controller.advance(self.f.prepared_id)["status"], "PLAN_CHECKS_ACCEPTED")
        source = record_source_snapshot(self.f.store, self.f.program, revised["event_id"], self.f.source,
            [{"source_id": "PROJECT-BRIEF", "path": "brief.md"}], **self.f.kwargs("same-source-new-plan"))
        new = prepare_build_authorization(self.f.store, self.f.program, revised["event_id"], source["event_id"],
            self.f.scope, rebind_from=self.f.prepared_id, **self.f.kwargs("adapted-rebind"))["event_id"]
        approve_build_authorization(self.f.store, self.f.program, new,
            human_message_ref="TEST-ONLY-ADAPTED-BINDING", **self.f.kwargs("adapted-approve"))
        self.assertEqual(self.controller.advance(new)["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(self.budget(new)["attempts_consumed"], final_budget["attempts_consumed"])
        self.assertEqual(len(self.local.invocations), calls)
        self.assertEqual(self.model_calls, self.original_calls)

    def test_changed_verification_command_is_not_legal_plan_adaptation(self):
        self.blocked(); budget = self.budget()
        self.record_plan(lambda plan: plan["workpacks"][0]["verification"][0]["argv"].append("--changed-check"))
        before = self.f.events()
        with self.assertRaisesRegex(RequestValidationError, "acceptance"):
            self.reassess()
        self.assertEqual(self.advance()["status"], "BUILD_STOPPED")
        self.assertEqual(self.local.invocations, [])
        self.assertEqual(self.f.events(), before)
        self.assert_preserved(budget)

    def test_ordinary_unreassessed_recovery_keeps_plan_change_hold(self):
        def crash_after_model_capture(invocation, before_dispatch):
            self.synthetic_producer(invocation, before_dispatch)
            raise fixture.InjectedControllerCrash()
        self.controller.runner = crash_after_model_capture
        with self.assertRaises(fixture.InjectedControllerCrash):
            self.advance()
        self.assertEqual(self.model_calls, 1)
        budget = self.budget()
        self.record_plan(lambda plan: plan["workpacks"][0].update(
            goal=plan["workpacks"][0]["goal"] + " (TEST changed wording)"))
        self.controller.runner = self.only_checks
        self.assertEqual(self.advance()["status"], "HELD_UNRESOLVED_ATTEMPT")
        self.assertEqual(self.model_calls, 1)
        self.assertEqual(self.local.invocations, [])
        self.assertEqual(self.budget(), budget)
        self.assertFalse(self.f.events("BUILD_COMMAND_REASSESSED"))

    def test_public_route_binds_host_decision_and_does_not_execute(self):
        from harness_foundry_factory.build_entrypoint import apply_build_request
        self.blocked()
        request = {"program_id": self.f.program, "prepared_event_id": self.f.prepared_id,
            "attempt_id": self.attempt["attempt_id"], "evidence": self.evidence,
            "expected_revision": len(self.f.events()), "idempotency_key": "public-reassessment",
            "decision": {"action": "REASSESS_BUILD_ATTEMPT", "actor": {
                "type": "HUMAN_VIA_CODEX_CHAT", "chat_thread_id": "TEST-NOT-REAL", "turn_id": "TEST-NOT-REAL"},
                "user_message": "TEST ONLY: bound observation correction, not real authority"}}
        invalid = deepcopy(request); invalid["decision"]["actor"]["type"] = "MODEL"
        with self.assertRaises(RequestValidationError):
            apply_build_request("reassess-build-attempt", invalid, self.f.store.database_path)
        with patch("harness_foundry_factory.build_entrypoint.BuildController", return_value=self.controller):
            response = apply_build_request("reassess-build-attempt", request, self.f.store.database_path)
        self.assertEqual(response["status"], "BUILD_REASSESSMENT_RECORDED_NOT_ACCEPTED")
        self.assertFalse(response["execution_started"])
        self.assertEqual(self.local.invocations, [])
