"""Slice 06 durable Checkpoint, Resume and Explain Stop tests."""

from __future__ import annotations

from contextlib import closing
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from harness_foundry_factory.control_kernel import (
    GenericTransitionEngine,
    prepare_parent_authorization_challenge,
    rebuild_control_projections,
)
from harness_foundry_factory.store import ControlEventStore
from tests.test_runtime_advance_cli import NOW, bindings, parent, transition


ROOT = Path(__file__).resolve().parents[1]


class CheckpointResumeCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "control.sqlite3"
        self.program_id = "PROGRAM-SLICE-06"
        self.store = ControlEventStore(self.database)
        self.engine = GenericTransitionEngine(self.store, {})
        self.authorization = parent(self.program_id, max_transitions=2)
        challenge = prepare_parent_authorization_challenge(
            self.authorization, expected_bindings=bindings()
        )
        self.engine.register_approved_parent_authorization(
            self.authorization,
            challenge,
            {
                "decision": "APPROVE",
                "challenge_sha256": challenge["challenge_sha256"],
                "approved_by": {
                    "type": "HUMAN_VIA_CODEX_CHAT",
                    "chat_thread_id": "THREAD-SLICE-06",
                    "turn_id": "TURN-SLICE-06-APPROVAL",
                },
                "approved_at": NOW,
            },
            created_at=NOW,
        )
        self.environment = {"runtime": "python-test", "platform": "local"}
        self.artifacts = {"artifacts": [], "scope": "test-only"}
        self.resume_transition = transition("T-TWO", "STATE")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _run_cli(
        self, command: str, request: dict | None = None
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["HFFACTORY_ALLOW_TEST_ADAPTERS"] = "1"
        arguments = [
            sys.executable,
            "-B",
            "-m",
            "tests.legacy_cli",
            command,
        ]
        if request is not None:
            request_path = self.root / f"{command}-request.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            arguments.extend(["--request", str(request_path)])
        else:
            arguments.extend(["--program-id", self.program_id])
        arguments.extend(["--control-db", str(self.database), "--json"])
        return subprocess.run(
            arguments,
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

    def _checkpoint_request(self, *, resume_node: str = "T-TWO") -> dict:
        return {
            "schema_version": "2.9",
            "program_id": self.program_id,
            "parent_authorization_id": self.authorization["authorization_id"],
            "expected_bindings": bindings(),
            "expected_control_state_sha256": self.engine.control_state_sha256(
                self.program_id
            ),
            "environment_manifest": deepcopy(self.environment),
            "artifact_manifest": deepcopy(self.artifacts),
            "resume_node": resume_node,
            "created_at": NOW,
        }

    def _resume_request(self, capsule: dict) -> dict:
        return {
            "schema_version": "2.9",
            "adapter_mode": "TEST_ONLY_IDEMPOTENT_ADAPTERS",
            "resume_capsule": deepcopy(capsule),
            "transition": deepcopy(self.resume_transition),
            "inputs": {"approved": True},
            "expected_bindings": bindings(),
            "expected_control_state_sha256": self.engine.control_state_sha256(
                self.program_id
            ),
            "expected_fencing_token": capsule["fencing_token"],
            "environment_manifest": deepcopy(self.environment),
            "artifact_manifest": deepcopy(self.artifacts),
            "created_at": NOW,
            "test_adapter_results": [
                {"status": "PASS", "artifact_id": "RESUMED-TWO"}
            ],
        }

    def _commit_first_transition(self) -> None:
        adapter = lambda context: {  # noqa: E731 - test adapter
            "status": "PASS",
            "artifact_id": "COMPLETED-ONE",
        }
        engine = GenericTransitionEngine(self.store, {"READ": adapter})
        outcome = engine.execute_transition(
            self.program_id,
            self.authorization["authorization_id"],
            transition("T-ONE", "READ"),
            {"approved": True},
            created_at=NOW,
        )
        self.assertEqual(outcome["status"], "COMMITTED")

    def test_checkpoint_is_event_bound_and_idempotent(self) -> None:
        self._commit_first_transition()
        request = self._checkpoint_request()

        first = self._run_cli("checkpoint", request)

        self.assertEqual(first.returncode, 0, first.stdout)
        result = json.loads(first.stdout)
        checkpoint = result["checkpoint"]
        capsule = result["resume_capsule"]
        self.assertEqual(checkpoint["completed_event_hash"], self.store.list_events(self.program_id)[-3]["event_hash"])
        self.assertEqual(checkpoint["completed_artifacts"][0]["artifact_id"], "COMPLETED-ONE")
        self.assertEqual(checkpoint["authorization_hash"], capsule["authorization_hash"])
        self.assertEqual(checkpoint["environment_hash"], hashlib.sha256(json.dumps(self.environment, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
        self.assertEqual(
            checkpoint["artifact_manifest_hash"],
            hashlib.sha256(
                json.dumps(
                    self.artifacts, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest(),
        )
        self.assertEqual(
            checkpoint["side_effect_inventory"][0]["effect_state"],
            "COMMITTED",
        )
        self.assertEqual(
            capsule["checkpoint_sha256"], checkpoint["checkpoint_sha256"]
        )
        self.assertEqual(capsule["resume_node"], "T-TWO")
        self.assertEqual(capsule["fencing_token"], 2)
        self.assertEqual(capsule["unknown_side_effects"], [])
        self.assertEqual(
            capsule["revalidation_requirements"],
            [
                "CURRENT_PARENT_AUTHORIZATION",
                "RUNTIME_BINDINGS",
                "ENVIRONMENT_HASH",
                "ARTIFACT_MANIFEST_HASH",
                "EVENT_TIP",
                "FENCING_TOKEN",
                "UNKNOWN_SIDE_EFFECTS_EMPTY",
            ],
        )
        self.assertEqual([event["event_type"] for event in self.store.list_events(self.program_id)[-2:]], ["CHECKPOINT_RECORDED", "RESUME_CAPSULE_EMITTED"])
        projection = rebuild_control_projections(
            self.store.list_events(self.program_id)
        )
        self.assertEqual(
            projection["recovery_state"]["latest_checkpoint"], checkpoint
        )
        self.assertEqual(
            projection["recovery_state"]["latest_resume_capsule"], capsule
        )
        with closing(sqlite3.connect(self.database)) as connection:
            durable_pair = connection.execute(
                "SELECT events_json FROM control_idempotency "
                "WHERE idempotency_key LIKE 'CHECKPOINT-CAPSULE:%'"
            ).fetchone()
        self.assertIsNotNone(durable_pair)
        self.assertEqual(len(json.loads(durable_pair[0])), 2)
        before = self.store.list_events(self.program_id)

        second = self._run_cli("checkpoint", request)

        self.assertEqual(second.returncode, 0, second.stdout)
        self.assertFalse(json.loads(second.stdout)["writes_performed"])
        self.assertEqual(self.store.list_events(self.program_id), before)

    def test_resume_revalidates_and_never_replays_completed_transition(self) -> None:
        self._commit_first_transition()
        checkpoint = json.loads(
            self._run_cli("checkpoint", self._checkpoint_request()).stdout
        )
        capsule = checkpoint["resume_capsule"]
        request = self._resume_request(capsule)

        resumed = self._run_cli("resume", request)

        self.assertEqual(resumed.returncode, 0, resumed.stdout)
        result = json.loads(resumed.stdout)
        self.assertEqual(result["status"], "RESUMED")
        events = self.store.list_events(self.program_id)
        committed = [
            event["payload"]["transition_id"]
            for event in events
            if event["event_type"] == "TRANSITION_COMMITTED"
        ]
        self.assertEqual(committed, ["T-ONE", "T-TWO"])
        self.assertEqual(sum(event["event_type"] == "RESUME_RECONCILED" for event in events), 1)

        request["expected_control_state_sha256"] = self.engine.control_state_sha256(self.program_id)
        again = self._run_cli("resume", request)
        self.assertEqual(again.returncode, 0, again.stdout)
        self.assertEqual(json.loads(again.stdout)["status"], "ALREADY_RESUMED")
        committed_again = [
            event for event in self.store.list_events(self.program_id)
            if event["event_type"] == "TRANSITION_COMMITTED"
        ]
        self.assertEqual(len(committed_again), 2)

    def test_resume_drift_checks_fail_closed_before_adapter(self) -> None:
        variants = (
            ("state", lambda request: request.update(expected_control_state_sha256="0" * 64), "STATE_CAS_MISMATCH"),
            ("environment", lambda request: request.update(environment_manifest={"runtime": "changed"}), "ENVIRONMENT_DRIFT"),
            ("artifact", lambda request: request.update(artifact_manifest={"artifacts": ["changed"]}), "ARTIFACT_DRIFT"),
            ("fence", lambda request: request.update(expected_fencing_token=999), "FENCING_TOKEN_MISMATCH"),
            ("binding", lambda request: request["expected_bindings"].update(architecture_lock_sha256="d" * 64), "RUNTIME_STALE_BINDING"),
            ("mixed-epoch", lambda request: request["expected_bindings"].update(control_plane_epoch=5), "RUNTIME_MIXED_EPOCH"),
            ("capsule", lambda request: request["resume_capsule"].update(resume_node="T-TAMPERED"), "RESUME_CAPSULE_INVALID"),
        )
        for name, mutate, reason in variants:
            with self.subTest(name=name):
                local = self._new_isolated_checkpoint(name)
                request = local["request"]
                mutate(request)
                before = local["store"].list_events(local["program_id"])
                completed = self._run_cli_for_local("resume", request, local)
                self.assertEqual(completed.returncode, 6, completed.stdout)
                self.assertEqual(json.loads(completed.stdout)["error"]["reason_code"], reason)
                self.assertEqual(local["store"].list_events(local["program_id"]), before)

    def test_resume_expired_or_revoked_parent_fails_without_adapter_event(self) -> None:
        expired = self._new_isolated_checkpoint("resume-expired")
        expired_request = expired["request"]
        expired_request["created_at"] = "2028-08-12T08:00:00Z"
        expired_before = expired["store"].list_events(expired["program_id"])

        expired_result = self._run_cli_for_local(
            "resume", expired_request, expired
        )

        self.assertEqual(expired_result.returncode, 6, expired_result.stdout)
        self.assertEqual(
            json.loads(expired_result.stdout)["error"]["reason_code"],
            "PARENT_AUTHORIZATION_EXPIRED",
        )
        self.assertEqual(
            expired["store"].list_events(expired["program_id"]),
            expired_before,
        )

        revoked = self._new_isolated_checkpoint("resume-revoked")
        revoked["engine"].revoke_parent_authorization(
            revoked["program_id"],
            revoked["authorization"]["authorization_id"],
            created_at=NOW,
        )
        revoked["request"]["expected_control_state_sha256"] = revoked[
            "engine"
        ].control_state_sha256(revoked["program_id"])
        revoked_before = revoked["store"].list_events(revoked["program_id"])

        revoked_result = self._run_cli_for_local(
            "resume", revoked["request"], revoked
        )

        self.assertEqual(revoked_result.returncode, 6, revoked_result.stdout)
        self.assertEqual(
            json.loads(revoked_result.stdout)["error"]["reason_code"],
            "PARENT_AUTHORIZATION_NOT_ACTIVE",
        )
        self.assertEqual(
            revoked["store"].list_events(revoked["program_id"]),
            revoked_before,
        )

    def test_event_tip_drift_and_unknown_side_effect_require_hard_stop(self) -> None:
        self._commit_first_transition()
        checkpoint = json.loads(
            self._run_cli("checkpoint", self._checkpoint_request()).stdout
        )
        request = self._resume_request(checkpoint["resume_capsule"])
        previous = self.store.list_events(self.program_id)[-1]["event_hash"]
        self.store.append_batch(
            self.program_id,
            [{"event_type": "EXTERNAL_STATE_CHANGED", "payload": {"value": 1}}],
            idempotency_key="EXTERNAL-STATE-CHANGED",
            created_at=NOW,
            expected_previous_event_hash=previous,
        )
        request["expected_control_state_sha256"] = self.engine.control_state_sha256(self.program_id)

        drift = self._run_cli("resume", request)

        self.assertEqual(json.loads(drift.stdout)["error"]["reason_code"], "EVENT_TIP_DRIFT")

        local = self._new_unknown_side_effect_program()
        checkpoint_request = local["checkpoint_request"]
        hard = self._run_cli_for_local("checkpoint", checkpoint_request, local)
        capsule = json.loads(hard.stdout)["resume_capsule"]
        self.assertEqual(capsule["status"], "HUMAN_DECISION_REQUIRED")
        resume_request = local["resume_request"](capsule)
        stopped = self._run_cli_for_local("resume", resume_request, local)
        self.assertEqual(json.loads(stopped.stdout)["error"]["reason_code"], "UNKNOWN_SIDE_EFFECT_HARD_STOP")
        explanation = self._run_cli_for_local("explain-stop", None, local)
        blocker = json.loads(explanation.stdout)["blocker"]
        self.assertEqual(blocker["blocker_type"], "UNKNOWN_SIDE_EFFECT")
        self.assertEqual(blocker["owner"], "HUMAN_RISK_OWNER")
        self.assertTrue(blocker["evidence"])
        self.assertEqual(blocker["minimum_return_path"]["intents"], ["RECONCILE_SIDE_EFFECT", "HUMAN_DECISION"])
        self.assertTrue(blocker["human_gate"])

    def test_explain_stop_is_read_only(self) -> None:
        previous = self.store.list_events(self.program_id)[-1]["event_hash"]
        self.store.append_batch(
            self.program_id,
            [{"event_type": "TRANSITION_STOPPED", "payload": {"transition_id": "T-TWO", "stop_reason": "BUDGET_EXHAUSTION", "reason_code": "ADVANCE_BUDGET_EXHAUSTED", "human_authority_required": False}}],
            idempotency_key="STOP-BUDGET",
            created_at=NOW,
            expected_previous_event_hash=previous,
        )
        before_events = self.store.list_events(self.program_id)
        before_hash = hashlib.sha256(self.database.read_bytes()).hexdigest()

        explained = self._run_cli("explain-stop")

        self.assertEqual(explained.returncode, 0, explained.stdout)
        result = json.loads(explained.stdout)
        self.assertEqual(result["blocker"]["owner"], "AUTHORIZATION_OWNER")
        self.assertFalse(result["writes_performed"])
        self.assertEqual(self.store.list_events(self.program_id), before_events)
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(), before_hash)

    def _new_isolated_checkpoint(self, suffix: str) -> dict:
        database = self.root / f"{suffix}.sqlite3"
        program_id = f"PROGRAM-SLICE-06-{suffix.upper()}"
        store = ControlEventStore(database)
        engine = GenericTransitionEngine(store, {})
        authorization = parent(program_id, max_transitions=2)
        challenge = prepare_parent_authorization_challenge(authorization, expected_bindings=bindings())
        engine.register_approved_parent_authorization(authorization, challenge, {"decision": "APPROVE", "challenge_sha256": challenge["challenge_sha256"], "approved_by": {"type": "HUMAN_VIA_CODEX_CHAT", "chat_thread_id": "T", "turn_id": "A"}, "approved_at": NOW}, created_at=NOW)
        local = {"database": database, "program_id": program_id, "store": store, "engine": engine, "authorization": authorization}
        checkpoint_request = {"schema_version": "2.9", "program_id": program_id, "parent_authorization_id": authorization["authorization_id"], "expected_bindings": bindings(), "expected_control_state_sha256": engine.control_state_sha256(program_id), "environment_manifest": deepcopy(self.environment), "artifact_manifest": deepcopy(self.artifacts), "resume_node": "T-TWO", "created_at": NOW}
        checkpoint = json.loads(self._run_cli_for_local("checkpoint", checkpoint_request, local).stdout)
        local["request"] = {"schema_version": "2.9", "adapter_mode": "TEST_ONLY_IDEMPOTENT_ADAPTERS", "resume_capsule": checkpoint["resume_capsule"], "transition": deepcopy(self.resume_transition), "inputs": {"approved": True}, "expected_bindings": bindings(), "expected_control_state_sha256": engine.control_state_sha256(program_id), "expected_fencing_token": checkpoint["resume_capsule"]["fencing_token"], "environment_manifest": deepcopy(self.environment), "artifact_manifest": deepcopy(self.artifacts), "created_at": NOW, "test_adapter_results": [{"status": "PASS", "artifact_id": "RESUMED"}]}
        return local

    def _new_unknown_side_effect_program(self) -> dict:
        database = self.root / "unknown-effect.sqlite3"
        program_id = "PROGRAM-SLICE-06-UNKNOWN-EFFECT"
        store = ControlEventStore(database)
        engine = GenericTransitionEngine(store, {})
        authorization = parent(program_id, max_transitions=2)
        challenge = prepare_parent_authorization_challenge(authorization, expected_bindings=bindings())
        engine.register_approved_parent_authorization(authorization, challenge, {"decision": "APPROVE", "challenge_sha256": challenge["challenge_sha256"], "approved_by": {"type": "HUMAN_VIA_CODEX_CHAT", "chat_thread_id": "T", "turn_id": "A"}, "approved_at": NOW}, created_at=NOW)
        unknown_engine = GenericTransitionEngine(store, {"READ": lambda context: {"status": "UNKNOWN_SIDE_EFFECT", "artifact_id": "UNKNOWN"}})
        unknown_engine.execute_transition(program_id, authorization["authorization_id"], transition("T-UNKNOWN", "READ"), {"approved": True}, created_at=NOW)
        local = {"database": database, "program_id": program_id, "store": store, "engine": unknown_engine, "authorization": authorization}
        local["checkpoint_request"] = {"schema_version": "2.9", "program_id": program_id, "parent_authorization_id": authorization["authorization_id"], "expected_bindings": bindings(), "expected_control_state_sha256": unknown_engine.control_state_sha256(program_id), "environment_manifest": deepcopy(self.environment), "artifact_manifest": deepcopy(self.artifacts), "resume_node": "T-UNKNOWN", "created_at": NOW}
        local["resume_request"] = lambda capsule: {"schema_version": "2.9", "adapter_mode": "TEST_ONLY_IDEMPOTENT_ADAPTERS", "resume_capsule": capsule, "transition": transition("T-UNKNOWN", "READ"), "inputs": {"approved": True}, "expected_bindings": bindings(), "expected_control_state_sha256": GenericTransitionEngine(store, {}).control_state_sha256(program_id), "expected_fencing_token": capsule["fencing_token"], "environment_manifest": deepcopy(self.environment), "artifact_manifest": deepcopy(self.artifacts), "created_at": NOW, "test_adapter_results": [{"status": "PASS", "artifact_id": "MUST-NOT-RUN"}]}
        return local

    def _run_cli_for_local(self, command: str, request: dict | None, local: dict) -> subprocess.CompletedProcess[str]:
        original_database, original_program = self.database, self.program_id
        self.database, self.program_id = local["database"], local["program_id"]
        try:
            return self._run_cli(command, request)
        finally:
            self.database, self.program_id = original_database, original_program


if __name__ == "__main__":
    unittest.main()
