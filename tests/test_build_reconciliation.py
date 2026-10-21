"""Engineering fixtures for host recovery; no real model or business execution."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness_foundry_factory.build_reconciliation import reconcile_build_observations, validate_host_reconciliation
from harness_foundry_factory.build_state import project_execution_state, project_budget_attempts, attempt_budget
from harness_foundry_factory.build_types import RequestValidationError, RevisionConflictError, IdempotencyConflictError
from harness_foundry_factory.process_observation import CommandObservation
from harness_foundry_factory.revision_store import RevisionControlEventStore


class BuildReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.store = RevisionControlEventStore(self.root / "control.sqlite3")
        self.program = "TEST-RECOVERY"
        self.scope = {"max_attempts": 3, "max_task_attempts": 3, "expires_at": "2001-01-01T00:00:00Z"}
        prepared = self.append("BUILD_AUTHORIZATION_PREPARED", {"scope": self.scope})
        self.prepared = prepared["event_id"]
        self.binding = {"prepared_event_id": self.prepared, "proposal_event_id": "PROPOSAL-1",
                        "attempt_id": "ATTEMPT-1", "workpack_id": "TASK-1", "job_id": "JOB-1"}
        self.append("BUILD_ATTEMPT_STARTED", self.binding)
        self.command = self.make_command("COMMAND-1")

    def events(self):
        return self.store.list_events(self.program)

    def append(self, kind, payload):
        count = len(self.events())
        return self.store.append_batch(self.program, [{"event_type": kind, "payload": payload}],
            expected_revision=count, idempotency_key="fixture-" + str(count), created_at="2000-01-01T00:00:00Z")[0]

    def make_command(self, identifier, **extra):
        command = {**self.binding, "command_id": identifier, "executor": "LOCAL", "phase": "IMPLEMENTATION",
                   "case_id": None, "observation_root": str(self.root / identifier), **extra}
        self.append("BUILD_COMMAND_PLANNED", command)
        return command

    def finish(self, command=None, result=None):
        command = command or self.command
        observation = CommandObservation(command["observation_root"], command["command_id"], command["executor"])
        observation.finished(result or {"status": "PASS", "exit_code": 0})
        observation.close()

    def reconcile(self, **overrides):
        arguments = dict(expected_revision=len(self.events()), idempotency_key="reconcile", created_at="2026-10-21T00:00:00Z")
        arguments.update(overrides)
        return reconcile_build_observations(self.store, self.program, self.prepared, **arguments)

    def receipt(self, command=None):
        command = command or self.command
        return {"prepared_event_id": self.prepared, "attempt_id": self.binding["attempt_id"], "commands": [{
            **{key: command[key] for key in ("command_id", "executor", "observation_root")},
            "termination": {"status": "PROCESS_TREE_TERMINATED", "detail": "TEST supervisor observed all owned processes exit",
                            "evidence_refs": ["TEST-SUPERVISOR-EXIT-1"]},
            "effects": {"status": "RECONCILED_FOR_RETRY", "detail": "TEST host inspected finite effects and permits retry",
                        "evidence_refs": ["TEST-EFFECTS-1"]}}]}

    def test_expired_revoked_capture_is_ingested_without_dispatch_acceptance_or_budget_change(self):
        self.append("BUILD_AUTHORIZATION_REVOKED", {"prepared_event_id": self.prepared})
        self.finish()
        before = self.events()
        budget = attempt_budget(self.scope, list(project_budget_attempts(before, self.prepared).values()))
        with patch("subprocess.Popen", side_effect=AssertionError("must not execute")), \
             patch("harness_foundry_factory.resource_observation._cleanup", side_effect=AssertionError("must not clean")):
            summary = self.reconcile()
        self.assertEqual(summary["payload"]["recovered_command_ids"], ["COMMAND-1"])
        self.assertEqual(summary["payload"]["pending_commands"], [])
        attempts, accepted = project_execution_state(self.events(), self.prepared)
        self.assertEqual(attempts["ATTEMPT-1"]["status"], "IN_FLIGHT")
        self.assertEqual(accepted, {})
        self.assertEqual(budget, attempt_budget(self.scope, list(project_budget_attempts(self.events(), self.prepared).values())))
        self.assertEqual(self.events()[:len(before)], before)
        self.assertFalse(summary["payload"]["execution_started"])

    def test_missing_capture_stays_pending_even_if_pid_is_absent(self):
        observer = CommandObservation(self.command["observation_root"], "COMMAND-1", "LOCAL")
        observer.started(987654321)
        observer.write("stdout", b"partial")
        observer.close()
        summary = self.reconcile()["payload"]
        self.assertEqual(summary["pending_commands"], [{"command_id": "COMMAND-1", "reason": "COMPLETE_CAPTURE_UNAVAILABLE"}])
        self.assertFalse(summary["recovered_command_ids"])
        self.assertFalse(any(row["event_type"] == "BUILD_COMMAND_OBSERVED" for row in self.events()))

    def test_exact_retry_returns_old_summary_without_rereading_or_appending(self):
        self.finish()
        revision = len(self.events())
        first = self.reconcile(expected_revision=revision)
        before = self.events()
        with patch.object(CommandObservation, "recover", side_effect=AssertionError("do not reread completed request")):
            second = self.reconcile(expected_revision=revision)
        self.assertEqual(first, second)
        self.assertEqual(before, self.events())
        with self.assertRaises(IdempotencyConflictError):
            self.reconcile(expected_revision=revision + 1)

    def test_new_reconciliation_does_not_duplicate_an_observed_command(self):
        self.finish()
        self.reconcile()
        summary = self.reconcile(idempotency_key="reconcile-later")
        self.assertEqual(summary["payload"]["recovered_command_ids"], [])
        self.assertEqual(sum(row["event_type"] == "BUILD_COMMAND_OBSERVED" for row in self.events()), 1)

    def test_stale_revision_does_not_read_capture_or_write(self):
        with patch.object(CommandObservation, "recover", side_effect=AssertionError("stale")), self.assertRaises(RevisionConflictError):
            self.reconcile(expected_revision=len(self.events()) - 1)

    def test_capture_binding_mismatch_is_not_ingested(self):
        observation = CommandObservation(self.command["observation_root"], "OTHER", "LOCAL")
        observation.finished({"status": "PASS", "exit_code": 0})
        observation.close()
        before = self.events()
        with self.assertRaises(RequestValidationError):
            self.reconcile()
        self.assertEqual(before, self.events())

    def test_resource_settlement_is_not_started_by_observation_only_route(self):
        command = self.make_command("COMMAND-2", phase="VERIFICATION", resource_binding={"profile": {}, "report_files": ["summary.json"]})
        self.finish(command)
        with patch("harness_foundry_factory.resource_observation.finish_resource_observation", side_effect=AssertionError("must not settle")):
            summary = self.reconcile()["payload"]
        self.assertIn({"command_id": "COMMAND-2", "reason": "RESOURCE_SETTLEMENT_PENDING"}, summary["pending_commands"])
        self.assertFalse((Path(command["observation_root"]) / "resource-result.json").exists())

    def settled_resource(self):
        binding = {"profile": {}, "report_files": ["summary.json"]}
        command = self.make_command("COMMAND-2", phase="VERIFICATION", resource_binding=binding)
        self.finish(command)
        root = Path(command["observation_root"])
        (root / "reports").mkdir()
        content = b'{"status":"PASS"}'
        (root / "reports/summary.json").write_bytes(content)
        report = {"name": "summary.json", "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        (root / "resource-result.json").write_text(json.dumps({"binding": binding, "result": {"status": "PASS", "resource_reports": [report]}}))
        (root / "resource-cleanup.json").write_text(json.dumps({"status": "CLEANED"}))
        return command

    def test_already_settled_resource_receipts_are_read_without_cleanup_or_staging(self):
        self.settled_resource()
        with patch("harness_foundry_factory.resource_observation._cleanup", side_effect=AssertionError("must not clean")), \
             patch("harness_foundry_factory.resource_credentials.resolve_credentials", side_effect=AssertionError("must not load credentials")):
            result = self.reconcile()["payload"]
        self.assertEqual(result["recovered_command_ids"], ["COMMAND-2"])
        observed = next(row for row in self.events() if row["event_type"] == "BUILD_COMMAND_OBSERVED")
        self.assertEqual(observed["payload"]["result"]["resource_cleanup"], {"status": "CLEANED"})

    def test_changed_archived_resource_bytes_are_not_ingested(self):
        command = self.settled_resource()
        (Path(command["observation_root"]) / "reports/summary.json").write_text("changed")
        before = self.events()
        with self.assertRaises(RequestValidationError):
            self.reconcile()
        self.assertEqual(before, self.events())

    def test_host_receipt_retains_missing_capture_without_fabricated_result(self):
        receipt = self.receipt()
        before = self.events()
        result = validate_host_reconciliation(before, self.binding, receipt)
        self.assertEqual(result, receipt)
        result["commands"][0]["effects"]["detail"] = "changed copy"
        self.assertNotEqual(result, receipt)
        self.assertEqual(before, self.events())
        self.assertNotIn("exit_code", json.dumps(receipt))

    def test_host_receipt_rejects_wrong_prepared_attempt_executor_root_or_command(self):
        for field, value in (("prepared_event_id", "OTHER"), ("attempt_id", "OTHER"), ("executor", "CODEX"),
                             ("observation_root", "/other"), ("command_id", "OTHER")):
            with self.subTest(field=field):
                receipt = self.receipt()
                if field in ("prepared_event_id", "attempt_id"):
                    receipt[field] = value
                else:
                    receipt["commands"][0][field] = value
                with self.assertRaises(RequestValidationError):
                    validate_host_reconciliation(self.events(), self.binding, receipt)

    def test_host_receipt_requires_all_missing_commands_exactly_once(self):
        second = self.make_command("COMMAND-2")
        receipt = self.receipt()
        with self.assertRaises(RequestValidationError):
            validate_host_reconciliation(self.events(), self.binding, receipt)
        receipt["commands"].append(deepcopy(receipt["commands"][0]))
        with self.assertRaises(RequestValidationError):
            validate_host_reconciliation(self.events(), self.binding, receipt)
        receipt["commands"][1] = self.receipt(second)["commands"][0]
        self.assertEqual(validate_host_reconciliation(self.events(), self.binding, receipt), receipt)

    def test_host_receipt_rejects_unknown_live_or_unsubstantiated_effects(self):
        for section, field, value in (("termination", "status", "RUNNING"), ("termination", "status", []),
                                     ("termination", "status", "PID_ABSENT_EFFECTS_UNKNOWN"),
                                     ("effects", "status", "UNKNOWN"), ("termination", "evidence_refs", []),
                                     ("effects", "evidence_refs", []), ("termination", "detail", "")):
            with self.subTest(section=section, field=field):
                receipt = self.receipt()
                receipt["commands"][0][section][field] = value
                with self.assertRaises(RequestValidationError):
                    validate_host_reconciliation(self.events(), self.binding, receipt)

    def test_observed_start_cannot_be_declared_not_started(self):
        self.append("BUILD_COMMAND_STARTED", {**self.command, "pid": 12345})
        receipt = self.receipt()
        receipt["commands"][0]["termination"]["status"] = "NOT_STARTED"
        with self.assertRaises(RequestValidationError):
            validate_host_reconciliation(self.events(), self.binding, receipt)

    def test_host_receipt_cannot_override_a_complete_existing_observation(self):
        self.append("BUILD_COMMAND_OBSERVED", {**self.command, "result": {"status": "PASS", "exit_code": 0}})
        with self.assertRaises(RequestValidationError):
            validate_host_reconciliation(self.events(), self.binding, self.receipt())


    def public_request(self, **extra):
        return {"program_id": self.program, "prepared_event_id": self.prepared,
                "expected_revision": len(self.events()), "idempotency_key": "public", **extra}

    def human_decision(self):
        return {"action": "RESOLVE_BUILD_ATTEMPT", "actor": {
            "type": "HUMAN_VIA_CODEX_CHAT", "chat_thread_id": "TEST-ONLY", "turn_id": "TEST-ONLY"},
            "user_message": "TEST ONLY: termination and effects inspected; permit remaining-budget retry"}

    def test_public_reconciliation_returns_expired_completed_capture_without_execution(self):
        from harness_foundry_factory.build_entrypoint import apply_build_request
        self.finish()
        request = self.public_request()
        with patch("subprocess.Popen", side_effect=AssertionError("no execution")):
            result = apply_build_request("reconcile-build-observations", request, self.store.database_path)
            repeated = apply_build_request("reconcile-build-observations", request, self.store.database_path)
        self.assertEqual(result, repeated)
        self.assertEqual(result["status"], "BUILD_COMMAND_OBSERVATIONS_RECONCILED")
        self.assertEqual(result["recovered_command_ids"], ["COMMAND-1"])
        self.assertFalse(result["execution_started"])
        self.assertFalse(result["target_write"])
        self.assertFalse(result["automatic_acceptance"])

    def test_public_host_resolution_preserves_missing_capture_and_spent_budget(self):
        from harness_foundry_factory.build_entrypoint import apply_build_request
        self.append("BUILD_COMMAND_STARTED", {**self.command, "pid": 12345})
        before = self.events()
        request = self.public_request(attempt_id="ATTEMPT-1", reason="TEST effects inspected", decision=self.human_decision(),
                                      host_reconciliation=self.receipt())
        with patch("subprocess.Popen", side_effect=AssertionError("no execution")):
            result = apply_build_request("resolve-build-attempt", request, self.store.database_path)
            repeated = apply_build_request("resolve-build-attempt", request, self.store.database_path)
        self.assertEqual(result, repeated)
        attempts, accepted = project_execution_state(self.events(), self.prepared)
        self.assertEqual(attempts["ATTEMPT-1"]["status"], "RETRY_ALLOWED")
        self.assertEqual(attempts["ATTEMPT-1"]["original_status"], "IN_FLIGHT")
        self.assertFalse(attempts["ATTEMPT-1"]["old_output_accepted"])
        self.assertEqual(accepted, {})
        self.assertFalse(any(row["event_type"] == "BUILD_COMMAND_OBSERVED" for row in self.events()))
        self.assertEqual(self.events()[:len(before)], before)
        budget = attempt_budget(self.scope, list(project_budget_attempts(self.events(), self.prepared).values()))
        self.assertEqual(budget["attempts_consumed"], 1)
        self.assertEqual(budget["attempts_remaining"], 2)
        self.assertFalse(budget["reset"])

    def test_public_host_resolution_requires_actual_human_decision(self):
        from harness_foundry_factory.build_entrypoint import apply_build_request
        decision = self.human_decision()
        decision["actor"]["type"] = "ASSISTANT"
        request = self.public_request(attempt_id="ATTEMPT-1", reason="TEST effects inspected", decision=decision,
                                      host_reconciliation=self.receipt())
        before = self.events()
        with self.assertRaises(RequestValidationError):
            apply_build_request("resolve-build-attempt", request, self.store.database_path)
        self.assertEqual(before, self.events())

    def test_public_completed_inflight_observation_can_be_resolved_without_receipt(self):
        from harness_foundry_factory.build_entrypoint import apply_build_request
        self.finish(result={"status": "UNKNOWN_SIDE_EFFECT", "exit_code": -2})
        self.reconcile()
        request = self.public_request(attempt_id="ATTEMPT-1", reason="TEST effects inspected", decision=self.human_decision())
        with patch("subprocess.Popen", side_effect=AssertionError("no execution")):
            result = apply_build_request("resolve-build-attempt", request, self.store.database_path)
        self.assertEqual(result["status"], "BUILD_ATTEMPT_RESOLVED_NOT_EXECUTED")
        self.assertFalse(result["execution_started"])

    def test_public_resolution_checks_each_observed_process_not_only_last(self):
        from harness_foundry_factory.build_entrypoint import apply_build_request
        self.append("BUILD_COMMAND_OBSERVED", {**self.command, "result": {"status": "UNKNOWN_SIDE_EFFECT"}})
        second = self.make_command("COMMAND-2")
        self.append("BUILD_COMMAND_OBSERVED", {**second, "result": {"status": "PASS", "exit_code": 0}})
        request = self.public_request(attempt_id="ATTEMPT-1", reason="TEST effects inspected", decision=self.human_decision())
        before = self.events()
        with self.assertRaises(RequestValidationError):
            apply_build_request("resolve-build-attempt", request, self.store.database_path)
        self.assertEqual(before, self.events())

    def test_late_observation_does_not_replace_host_resolution_or_count_another_attempt(self):
        from harness_foundry_factory.build_entrypoint import apply_build_request
        request = self.public_request(attempt_id="ATTEMPT-1", reason="TEST effects inspected", decision=self.human_decision(),
                                      host_reconciliation=self.receipt())
        apply_build_request("resolve-build-attempt", request, self.store.database_path)
        self.append("BUILD_COMMAND_OBSERVED", {**self.command, "result": {"status": "PASS", "exit_code": 0}})
        attempts, accepted = project_execution_state(self.events(), self.prepared)
        self.assertEqual(attempts["ATTEMPT-1"]["status"], "RETRY_ALLOWED")
        self.assertFalse(accepted)
        self.assertEqual(len(project_budget_attempts(self.events(), self.prepared)), 1)
        # A later explicit rebind still sees the old attempt exactly once.
        new_prepared = self.append("BUILD_AUTHORIZATION_PREPARED", {"scope": self.scope, "rebind_from": self.prepared})
        self.assertEqual(len(project_budget_attempts(self.events(), new_prepared["event_id"])), 1)


    def test_start_attachment_before_event_still_rejects_not_started_receipt(self):
        observation = CommandObservation(self.command["observation_root"], "COMMAND-1", "LOCAL")
        observation.started(12345)
        observation.close()
        receipt = self.receipt()
        receipt["commands"][0]["termination"]["status"] = "NOT_STARTED"
        with self.assertRaisesRegex(RequestValidationError, "observed process start"):
            validate_host_reconciliation(self.events(), self.binding, receipt)

    def test_complete_uningested_capture_requires_retrieval_before_host_resolution(self):
        self.finish()
        with self.assertRaisesRegex(RequestValidationError, "reconcile it before"):
            validate_host_reconciliation(self.events(), self.binding, self.receipt())

    def test_complete_resource_receipt_requires_retrieval_before_host_resolution(self):
        command = self.settled_resource()
        receipt = self.receipt()
        receipt["commands"].append(self.receipt(command)["commands"][0])
        with self.assertRaisesRegex(RequestValidationError, "reconcile it before"):
            validate_host_reconciliation(self.events(), self.binding, receipt)

    def test_not_started_host_receipt_without_contradictory_start_keeps_assertion_scope(self):
        receipt = self.receipt()
        receipt["commands"][0]["termination"]["status"] = "NOT_STARTED"
        receipt["commands"][0]["termination"]["detail"] = "TEST supervisor confirmed launch was never performed"
        self.assertEqual(validate_host_reconciliation(self.events(), self.binding, receipt), receipt)


if __name__ == "__main__":
    unittest.main()
