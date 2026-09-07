"""Actual public bootstrap/approval on temporary Candidates; TEST ONLY actors."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
import unittest

from harness_foundry_factory.control_kernel import GenericTransitionEngine, rebuild_control_projections
from harness_foundry_factory.service import _tree_hash
from harness_foundry_factory.startup_runtime import STATE_REF
from harness_foundry_factory.store import ControlEventStore
from tests import test_startup_sqlite_runtime as support


class RuntimeAuthorizationCliTests(unittest.TestCase):
    def setUp(self):
        self.fixture = support.StartupSQLiteRuntimeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.local, self.parent = self.fixture.local, self.fixture.parent
        self.execution = self.local.root / "new-runtime"
        self.database = self.execution / ".harness-foundry/control.sqlite3"
        self.parent["startup_execution"].update(execution_root=str(self.execution), control_db=str(self.database))
        self.local.execution, self.local.database = self.execution, self.database
        self.actor = {"type": "HUMAN_VIA_CODEX_CHAT", "chat_thread_id": "TEST-ONLY", "turn_id": "TEST-ONLY-APPROVAL"}

    def prepare(self):
        completed, result = self.local.cli({"parent": self.parent}, command="prepare-runtime-authorization")
        self.assertEqual(completed.returncode, 0, result)
        return result["challenge"]

    def approval_request(self, challenge=None):
        challenge = challenge or self.prepare()
        return {"parent": self.parent, "challenge": challenge, "approval": {
            "decision": "APPROVE", "challenge_sha256": challenge["challenge_sha256"],
            "approved_by": self.actor, "approved_at": datetime.now(timezone.utc).isoformat()}}

    def approve(self, request=None):
        request = request or self.approval_request()
        completed, result = self.local.cli(request, command="approve-runtime-authorization")
        self.assertEqual(completed.returncode, 0, result)
        self.local.store = ControlEventStore(self.database, read_only=True)
        self.local.engine = GenericTransitionEngine(self.local.store, {})
        return request, result

    def test_public_readback_approval_and_startup_need_no_internal_registration_call(self):
        before = _tree_hash(self.fixture.fixture.factory.root)
        challenge = self.prepare()
        self.assertFalse(self.execution.exists())
        self.assertEqual(challenge["startup_execution"], self.parent["startup_execution"])
        self.assertEqual(challenge["controller_effects"]["control_db"], str(self.database))
        self.assertFalse(challenge["controller_effects"]["executes_commands"])
        request, result = self.approve(self.approval_request(challenge))
        events = self.local.store.list_events(self.local.program)
        self.assertEqual([event["event_type"] for event in events], ["PARENT_AUTHORIZATION_GRANTED"])
        self.assertFalse(result["execution_started"])
        self.assertFalse((self.execution / STATE_REF).exists())
        self.assertEqual(events[0]["payload"]["approval_receipt"]["approved_by"], self.actor)
        root_before_readback = _tree_hash(self.execution)
        self.prepare()
        self.assertEqual(root_before_readback, _tree_hash(self.execution))
        repeated, result = self.local.cli(request, command="approve-runtime-authorization")
        self.assertEqual(repeated.returncode, 0, result)
        self.assertFalse(result["writes_performed"])
        self.assertEqual(events, self.local.store.list_events(self.local.program))
        completed, result = self.local.cli(self.fixture.request())
        self.assertEqual(completed.returncode, 0, result)
        state = json.loads((self.execution / STATE_REF).read_text())
        self.assertEqual(state["next_node"], "LAB_BOOTSTRAP")
        self.assertFalse(state["driver_started"])
        self.assertEqual(before, _tree_hash(self.fixture.fixture.factory.root))

    def test_missing_changed_or_delegated_decision_does_not_create_root(self):
        valid = self.approval_request()
        mutations = [
            lambda value: value.pop("approval"),
            lambda value: value["parent"]["budgets"].update(max_attempts=20),
            lambda value: value["approval"]["approved_by"].update(type="CODEX_DELEGATED_AGENT"),
            lambda value: value["approval"]["approved_by"].pop("turn_id"),
            lambda value: value["approval"].update(approved_at="not-a-date"),
            lambda value: value["approval"].update(approved_at="2099-01-01T00:00:00Z"),
            lambda value: value.update(created_at="2026-01-01T00:00:00Z"),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                changed = deepcopy(valid)
                mutation(changed)
                completed, result = self.local.cli(changed, command="approve-runtime-authorization")
                self.assertNotEqual(completed.returncode, 0, result)
                self.assertFalse(self.execution.exists())

    def test_factory_reopen_between_readback_and_approval_creates_nothing(self):
        request = self.approval_request()
        self.fixture.fixture.factory.send("REOPEN", {"reason": "TEST changed after challenge"}, delegated=False)
        completed, result = self.local.cli(request, command="approve-runtime-authorization")
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertEqual(result["error"]["code"], "EXECUTION_HANDOFF_BLOCKED")
        self.assertFalse(self.execution.exists())

    def test_revocation_remains_available_after_reopen_and_is_audited_and_idempotent(self):
        request, _ = self.approve()
        self.fixture.fixture.factory.send("REOPEN", {"reason": "TEST invalidated Factory"}, delegated=False)
        revoke = {"program_id": self.local.program, "parent_authorization_id": self.parent["authorization_id"],
                  "revoked_by": self.actor, "reason": "TEST cancel future dispatch"}
        completed, result = self.local.cli(revoke, command="revoke-runtime-authorization")
        self.assertEqual(completed.returncode, 0, result)
        self.assertFalse(result["in_flight_process_terminated"])
        events = self.local.store.list_events(self.local.program)
        self.assertEqual(events[-1]["payload"]["revoked_by"], self.actor)
        self.assertEqual(events[-1]["payload"]["reason"], revoke["reason"])
        completed, result = self.local.cli(revoke, command="revoke-runtime-authorization")
        self.assertEqual(completed.returncode, 0, result)
        self.assertFalse(result["writes_performed"])
        self.assertEqual(events, self.local.store.list_events(self.local.program))
        completed, result = self.local.cli(self.fixture.request())
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertEqual(events, self.local.store.list_events(self.local.program))

    def test_native_empty_store_can_resume_but_another_program_cannot_share_it(self):
        request = self.approval_request()
        store = ControlEventStore(self.database)  # TEST interruption after schema initialization.
        self.assertEqual(store.list_program_ids(), [])
        self.approve(request)
        self.assertEqual(store.list_program_ids(), [self.local.program])
        store.append_batch("OTHER-PROGRAM", [{"event_type": "TEST_ONLY", "payload": {}}],
                           idempotency_key="TEST-OTHER", created_at=datetime.now(timezone.utc).isoformat())
        before = store.list_events(self.local.program)
        completed, result = self.local.cli(request, command="approve-runtime-authorization")
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertEqual(before, store.list_events(self.local.program))

    def test_path_override_link_and_unowned_control_files_are_not_adopted(self):
        request = self.approval_request()
        other = self.local.root / "other.sqlite3"
        completed, result = self.local.cli(request, command="approve-runtime-authorization", database=other)
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertFalse(other.exists())
        self.assertFalse(self.execution.exists())
        outside = self.local.root / "outside"
        outside.mkdir()
        self.execution.symlink_to(outside, target_is_directory=True)
        completed, result = self.local.cli(request, command="approve-runtime-authorization")
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertEqual(list(outside.iterdir()), [])
        self.execution.unlink()
        state = self.execution / STATE_REF
        state.parent.mkdir(parents=True)
        state.write_text('{"TEST_ONLY":"legacy"}')
        before = _tree_hash(self.execution)
        completed, result = self.local.cli(request, command="approve-runtime-authorization")
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertEqual(before, _tree_hash(self.execution))
        self.assertFalse(self.database.exists())

    def test_existing_non_native_database_is_preserved(self):
        request = self.approval_request()
        import sqlite3
        from contextlib import closing
        self.database.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("CREATE TABLE test_unrelated (value TEXT)")
            connection.commit()
        before = _tree_hash(self.execution)
        completed, result = self.local.cli(request, command="approve-runtime-authorization")
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertEqual(before, _tree_hash(self.execution))

    def test_revoked_or_expired_parent_and_reused_identity_cannot_regain_authority(self):
        request, _ = self.approve()
        changed = deepcopy(request)
        changed["approval"]["approved_by"]["turn_id"] = "TEST-OTHER-DECISION"
        completed, result = self.local.cli(changed, command="approve-runtime-authorization")
        self.assertNotEqual(completed.returncode, 0, result)
        revoke = {"program_id": self.local.program, "parent_authorization_id": self.parent["authorization_id"],
                  "revoked_by": self.actor, "reason": "TEST revoke"}
        completed, result = self.local.cli(revoke, command="revoke-runtime-authorization")
        self.assertEqual(completed.returncode, 0, result)
        before = self.local.store.list_events(self.local.program)
        completed, result = self.local.cli(request, command="approve-runtime-authorization")
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertEqual(result["error"]["reason_code"], "PARENT_AUTHORIZATION_REVOKED")
        self.parent["expires_at"] = "2020-01-01T00:00:00Z"
        completed, result = self.local.cli({"parent": self.parent}, command="prepare-runtime-authorization")
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertEqual(before, self.local.store.list_events(self.local.program))

    def test_another_program_appearing_after_preflight_cannot_receive_second_grant(self):
        request = self.approval_request()
        from unittest.mock import patch
        from harness_foundry_factory import runtime_authorization as api
        from harness_foundry_factory.models import StateConflictError
        real_verify = api.verify_runtime_factory_binding
        calls = 0

        def verify_and_publish_other_program(parent):
            nonlocal calls
            result = real_verify(parent)
            calls += 1
            if calls == 2:
                ControlEventStore(self.database).append_batch("OTHER-PROGRAM", [{"event_type": "TEST_ONLY", "payload": {}}],
                    idempotency_key="TEST-CONCURRENT", created_at=datetime.now(timezone.utc).isoformat())
            return result

        with patch.object(api, "verify_runtime_factory_binding", side_effect=verify_and_publish_other_program):
            with self.assertRaises(StateConflictError):
                api.approve_runtime_authorization(self.parent, request["challenge"], request["approval"], self.database)
        store = ControlEventStore(self.database, read_only=True)
        self.assertEqual(store.list_program_ids(), ["OTHER-PROGRAM"])
        self.assertEqual(store.list_events(self.local.program), [])

    @unittest.skipUnless(os.environ.get("HFFACTORY_TEST_CODEX_SANDBOX"), "real local sandbox opt-in not configured")
    def test_public_bootstrap_then_startup_then_new_parent_executes_actual_job(self):
        self.approve()
        completed, result = self.local.cli(self.fixture.request())
        self.assertEqual(completed.returncode, 0, result)
        parent = self.parent
        plan = deepcopy(self.fixture.local_plan)
        plan.update(execution_root=str(self.execution), control_db=str(self.database))
        from harness_foundry_factory.local_runtime import LOCAL_CLASS
        parent.pop("startup_execution")
        parent.update(authorization_id="PARENT-TEST-PUBLIC-JOB", local_execution=plan, command_classes=[LOCAL_CLASS],
                      allowed_read_roots=["harness-resource://candidate", "harness-resource://execution/jobs",
                                         "harness-resource://execution/evidence/job_artifact_leases", "harness-resource://runtime-tools"],
                      allowed_write_roots=["harness-resource://execution/jobs", "harness-resource://execution/evidence/job_artifact_leases"])
        self.approve()
        folder = self.execution / "jobs/JOB-A/input"
        folder.mkdir(parents=True)
        (folder / "value").write_text("JOB-A")
        self.fixture.fixture.parent = parent
        completed, result = self.local.cli(self.fixture.fixture.request())
        self.assertEqual(completed.returncode, 0, result)
        self.assertEqual((self.execution / "jobs/JOB-A/output/output").read_text(), "JOB-A")
        events = self.local.store.list_events(self.local.program)
        projection = rebuild_control_projections(events)
        self.assertEqual(len(projection["program_control_state"]["completed_transitions"]), 4)
        self.assertEqual(self.local.store.list_program_ids(), [self.local.program])
