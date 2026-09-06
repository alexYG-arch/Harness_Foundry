"""Opt-in pre-build delegation; temporary Factory state, never a target run."""

from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator
from harness_foundry_factory.models import ChatRequest, FactoryError, content_sha256
from harness_foundry_factory.service import _tree_hash
import test_state_machine as state_tests
from harness_foundry_factory.constants import default_spec_root


class PrebuildDelegationTests(unittest.TestCase):
    setUp = state_tests.FactoryStateMachineTests.setUp
    tearDown = state_tests.FactoryStateMachineTests.tearDown
    _clock = state_tests.FactoryStateMachineTests._clock
    _actor = staticmethod(state_tests.FactoryStateMachineTests._actor)
    _request = state_tests.FactoryStateMachineTests._request
    _canonical_ir = state_tests.FactoryStateMachineTests._canonical_ir
    _create_and_complete_requirements = state_tests.FactoryStateMachineTests._create_and_complete_requirements
    _freeze = state_tests.FactoryStateMachineTests._freeze

    def send(self, intent, payload=None, *, delegated=True):
        self.sequence = getattr(self, "sequence", 100) + 1
        record = self.store.get_program("PROGRAM-1")
        request = self._request(intent, number=self.sequence, expected_state_hash=record.state_hash, payload=payload)
        if delegated:
            request["actor"].update(type="CODEX_DELEGATED_AGENT", delegation_id="DELEGATION-1")
        return self.service.handle_chat_turn(request)

    def grant(self):
        self._freeze()
        record = self.store.get_program("PROGRAM-1")
        return self.send("GRANT_PREBUILD_DELEGATION", {
            "delegation_id": "DELEGATION-1", "decision": "APPROVE",
            "scope": "PREBUILD_AUTHORING_AND_CANDIDATE_DECISION",
            "requirement_ir_sha256": content_sha256(record.snapshot["requirement_ir"]),
            "approval_text": "Approve audited pre-build delegation, including Candidate decision; stop before Harness execution.",
        }, delegated=False)

    def reopen_and_freeze(self):
        self.send("REOPEN", {"reason": "Generic Producer repair"})
        bound = self.send("BIND_DELEGATED_OUTPUT")
        self.assertFalse(Path(bound["output_root"]).exists())
        readback = self.send("PREPARE_READBACK")
        ir = self.store.get_program("PROGRAM-1").snapshot["requirement_ir"]
        return self.send("DELEGATED_FREEZE", {"decision": "APPROVE",
            "requirement_ir_sha256": content_sha256(ir), "readback_sha256": readback["readback_sha256"]})

    def test_grant_is_opt_in_and_does_not_relabel_existing_human_freeze(self):
        self._freeze()
        before = deepcopy(self.store.get_program("PROGRAM-1").snapshot)
        response = self.send("GRANT_PREBUILD_DELEGATION", {
            "delegation_id": "DELEGATION-1", "decision": "APPROVE",
            "scope": "PREBUILD_AUTHORING_AND_CANDIDATE_DECISION",
            "requirement_ir_sha256": content_sha256(before["requirement_ir"]),
            "approval_text": "Explicit protocol delegation approval.",
        }, delegated=False)
        after = self.store.get_program("PROGRAM-1").snapshot
        self.assertEqual(after["requirement_ir"], before["requirement_ir"])
        self.assertEqual(after["freeze"], before["freeze"])
        grant = response["delegation"]
        self.assertFalse(grant["execution_authorized"])
        self.assertEqual(grant["status"], "ACTIVE")
        self.assertEqual(self.service.verify_run("PROGRAM-1")["status"], "PASS")
        self.assertIn("prebuild_delegations", self.service.readback("PROGRAM-1"))

    def test_delegated_freeze_records_grant_instead_of_fabricating_human_token(self):
        self.grant()
        frozen = self.reopen_and_freeze()
        lock = frozen["freeze_lock"]
        self.assertEqual(lock["approved_by"]["type"], "CODEX_DELEGATED_AGENT")
        self.assertEqual(lock["decision_evidence"]["delegation_id"], "DELEGATION-1")
        self.assertNotIn("confirmation_token", lock)
        self.assertEqual(frozen["factory_state"], "REQUIREMENTS_FROZEN")
        self.assertFalse(self.store.get_program("PROGRAM-1").snapshot["authoring_boundary"]["execution_started"])

    def test_delegate_cannot_grant_itself_or_use_human_confirmation_or_update_scope(self):
        self.grant()
        for intent in ("GRANT_PREBUILD_DELEGATION", "CONFIRM_FREEZE", "UPDATE_REQUIREMENTS", "ANSWER", "ADD_SOURCES"):
            before = self.store.get_program("PROGRAM-1").state_hash
            with self.assertRaises(FactoryError): self.send(intent, {"mission": "different"})
            self.assertEqual(self.store.get_program("PROGRAM-1").state_hash, before)
        with self.assertRaises(FactoryError):
            self.send("GENERATE", {"target_root": str(self.root / "other")})

    def test_revocation_and_other_chat_reject_without_mutating_state(self):
        self.grant()
        record = self.store.get_program("PROGRAM-1")
        req = self._request("REOPEN", number=999, expected_state_hash=record.state_hash, payload={"reason": "repair"})
        req["actor"].update(type="CODEX_DELEGATED_AGENT", delegation_id="DELEGATION-1", chat_thread_id="OTHER")
        with self.assertRaises(FactoryError): self.service.handle_chat_turn(req)
        self.send("REVOKE_PREBUILD_DELEGATION", {"delegation_id": "DELEGATION-1", "reason": "Owner revoked"}, delegated=False)
        before = self.store.get_program("PROGRAM-1").state_hash
        with self.assertRaises(FactoryError): self.send("REOPEN", {"reason": "repair"})
        self.assertEqual(self.store.get_program("PROGRAM-1").state_hash, before)

    def test_changed_requirement_does_not_inherit_grant(self):
        self.grant(); self.send("REOPEN", {"reason": "repair"})
        self.send("UPDATE_REQUIREMENTS", {"mission": "Different product"}, delegated=False)
        with self.assertRaises(FactoryError): self.send("BIND_DELEGATED_OUTPUT")

    def test_delegated_output_is_deterministic_absent_and_non_creating(self):
        self.grant(); self.send("REOPEN", {"reason": "repair"})
        target = self.root / "target-output-epoch1"
        target.mkdir(); (target / "original.txt").write_text("preserve")
        with self.assertRaises(FactoryError): self.send("BIND_DELEGATED_OUTPUT")
        self.assertEqual((target / "original.txt").read_text(), "preserve")
        with self.assertRaises(FactoryError): self.send("BIND_DELEGATED_OUTPUT", {"output_root": str(self.root / "elsewhere")})

    def test_wire_schema_and_parser_distinguish_human_and_delegate(self):
        schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/chat_turn_request.schema.json").read_text())
        request = self._request("DELEGATED_FREEZE", number=1)
        request["actor"].update(type="CODEX_DELEGATED_AGENT", delegation_id="DELEGATION-1")
        Draft202012Validator(schema).validate(request)
        self.assertEqual(ChatRequest.from_dict(request).actor.as_dict(), request["actor"])
        del request["actor"]["delegation_id"]
        self.assertFalse(Draft202012Validator(schema).is_valid(request))
        with self.assertRaises(FactoryError): ChatRequest.from_dict(request)

    def test_public_auto_advance_records_delegate_and_keeps_revoked_grant_closed(self):
        self.grant(); self.send("REOPEN", {"reason": "repair"}); self.send("BIND_DELEGATED_OUTPUT")
        result = self.service.advance_authoring_until_gate("PROGRAM-1")
        self.assertEqual(result["factory_state"], "REQUIREMENTS_READBACK_READY")
        self.assertEqual(result["status"], "DELEGATED_ACTION_READY")
        events = self.store.list_events("PROGRAM-1")
        self.assertIn("CODEX_DELEGATED_AGENT", json.dumps(events[-1]))
        self.assertEqual(self.service.status("PROGRAM-1")["delegated_next_allowed_intents"], ["DELEGATED_FREEZE"])

    def test_revoked_auto_route_never_falls_back_to_a_synthetic_human_actor(self):
        self.grant(); self.send("REOPEN", {"reason":"repair"}); self.send("BIND_DELEGATED_OUTPUT")
        self.send("REVOKE_PREBUILD_DELEGATION", {"delegation_id":"DELEGATION-1", "reason":"stop"}, delegated=False)
        before = self.store.get_program("PROGRAM-1").state_hash
        result = self.service.advance_authoring_until_gate("PROGRAM-1")
        self.assertEqual(result["status"], "PREBUILD_DELEGATION_INACTIVE")
        self.assertEqual(self.store.get_program("PROGRAM-1").state_hash, before)

    def test_authority_audit_checks_prior_grant_and_non_human_provenance(self):
        from harness_foundry_factory.prebuild_delegation import audit_events
        self.grant(); self.reopen_and_freeze()
        events = self.store.list_events("PROGRAM-1")
        self.assertEqual(audit_events(events)["status"], "PASS")
        damaged = deepcopy(events)
        damaged[-1]["actor"]["delegation_id"] = "MISSING"
        self.assertEqual(audit_events(damaged)["status"], "FAIL")
        damaged = deepcopy(events)
        damaged[-1]["resulting_snapshot"]["freeze"]["confirmation_token"] = "NOT_A_HUMAN_CONFIRMATION"
        self.assertIn("PREBUILD_FREEZE_PROVENANCE_AUDIT_INVALID", [f["code"] for f in audit_events(damaged)["findings"]])
        self.assertEqual(self.service.verify_run("PROGRAM-1")["prebuild_delegation_audit"]["status"], "PASS")

    def test_delegated_architecture_lock_uses_the_same_lock_builder_without_a_token(self):
        original = self._canonical_ir
        def ir():
            value = original()
            value["target"].update(architecture_epoch=1, control_plane_epoch=1,
                architecture_input={"capabilities":["compile"], "stages":["P1"], "subharnesses":["main"],
                    "modules":["main.py"], "rules":["declared only"], "policies":["no execution"],
                    "tools":["python"], "interfaces":["status"], "failure_returns":["FAILED"], "unresolved_decisions":[]})
            return value
        self._canonical_ir = ir
        self.grant(); self.reopen_and_freeze()
        prepared = self.send("PREPARE_ARCHITECTURE_READBACK")
        readback_hash = prepared["architecture_readback_sha256"]
        with self.assertRaises(FactoryError):
            self.send("DELEGATED_ARCHITECTURE_LOCK", {"decision":"APPROVE", "architecture_readback_sha256":"0"*64})
        self.send("DELEGATED_ARCHITECTURE_LOCK", {"decision":"APPROVE", "architecture_readback_sha256":readback_hash})
        lifecycle = self.store.get_program("PROGRAM-1").snapshot["architecture_lifecycle"]
        self.assertEqual(lifecycle["locked_by"]["type"], "CODEX_DELEGATED_AGENT")
        self.assertNotIn("confirmation_token", lifecycle)
        self.assertEqual(self.service.compile_contract("PROGRAM-1")["status"], "PASS")

    def test_real_temporary_candidate_uses_delegated_freeze_and_review_without_runtime_authority(self):
        self.service.spec_root = default_spec_root().resolve()
        self.grant(); self.reopen_and_freeze()
        generated = self.send("GENERATE")
        self.assertEqual(generated["hard_stop"], "DELEGATED_CANDIDATE_REVIEW_REQUIRED")
        candidate = generated["candidate"]
        payload = {"decision":"APPROVE", "candidate_content_sha256":candidate["compiler_result"]["content_sha256"],
            "requirement_ir_sha256":candidate["requirement_ir_sha256"],
            "review":{"summary":"Generic temporary protocol integration fixture, not production approval",
                      "findings":[], "reviewed_refs":["harness-resource://candidate/START_CONTEXT.json"]}}
        decided = self.send("REVIEW_CANDIDATE", payload)
        self.assertEqual(decided["factory_state"], "PREBUILD_APPROVED_EXECUTION_NOT_AUTHORIZED")
        self.assertEqual(self.service.advance_authoring_until_gate("PROGRAM-1")["stop_reason"], "HARNESS_EXECUTION_AUTHORIZATION_REQUIRED")
        self.assertEqual(self.service.verify_run("PROGRAM-1")["status"], "PASS")
        self.assertEqual(self.service.validate_program_candidate("PROGRAM-1")["status"], "PASS")
        self.assertEqual(_tree_hash(Path(candidate["candidate_path"]))[0], payload["candidate_content_sha256"])
        self.assertEqual(self.service.readback("PROGRAM-1")["authoring_boundary"]["execution_started"], False)

    def generate_fixture(self):
        self.grant(); self.reopen_and_freeze()
        def compile_stub(ir, spec, staging, target, created, lock, **kwargs):
            target.mkdir()
            (target / "unit-input.json").write_text('{"unit_fixture":true}')
            digest, count = _tree_hash(target)
            return {"candidate_path": str(target), "content_sha256": digest, "file_count": count}
        with patch("harness_foundry_factory.compiler.compile_candidate", side_effect=compile_stub), \
             patch.object(self.service, "validate_candidate", return_value={"status": "PASS", "blocking_findings": []}):
            return self.send("GENERATE")

    def test_review_binds_bytes_and_stops_before_execution_without_claiming_human_approval(self):
        generated = self.generate_fixture()
        candidate = generated["candidate"]
        payload = {"decision": "APPROVE", "candidate_content_sha256": candidate["compiler_result"]["content_sha256"],
                   "requirement_ir_sha256": candidate["requirement_ir_sha256"],
                   "review": {"summary": "Unit test of decision transition, not target review", "findings": [],
                              "reviewed_refs": ["harness-resource://candidate/unit-input.json"]}}
        before = self.store.get_program("PROGRAM-1").state_hash
        with patch.object(self.service, "validate_candidate", return_value={"status": "FAIL", "blocking_findings": [{"code": "BROKEN"}]}):
            with self.assertRaises(FactoryError): self.send("REVIEW_CANDIDATE", payload)
        self.assertEqual(self.store.get_program("PROGRAM-1").state_hash, before)
        with patch.object(self.service, "validate_candidate", return_value={"status": "PASS", "blocking_findings": []}):
            changed = deepcopy(payload); changed["candidate_content_sha256"] = "0" * 64
            with self.assertRaises(FactoryError): self.send("REVIEW_CANDIDATE", changed)
            approved = self.send("REVIEW_CANDIDATE", payload)
        self.assertEqual(approved["hard_stop"], "HARNESS_EXECUTION_AUTHORIZATION_REQUIRED")
        snapshot = self.store.get_program("PROGRAM-1").snapshot
        self.assertEqual(snapshot["candidate"]["human_approval_status"], "PENDING")
        self.assertEqual(snapshot["candidate_decision"]["approval_mode"], "DELEGATED")
        self.assertEqual(snapshot["prebuild_delegations"]["DELEGATION-1"]["status"], "COMPLETED")
        self.assertFalse(snapshot["authoring_boundary"]["execution_started"])
        with self.assertRaises(FactoryError): self.send("REOPEN", {"reason": "grant already completed"})
        self.assertEqual(self.service.verify_run("PROGRAM-1")["status"], "PASS")
