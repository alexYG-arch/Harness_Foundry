"""Frozen Epoch 9 Generic Control Kernel acceptance tests."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

import harness_foundry_factory
from harness_foundry_factory.control_kernel import (
    ControlKernelError,
    GenericTransitionEngine,
    InjectedKernelCrash,
    derive_attempt_grant,
    evaluate_decision_policy,
    evaluator_implementation_sha256,
    instantiate_program_graph,
    rebuild_control_projections,
)
from harness_foundry_factory.requirement_completion import (
    evaluate_human_cost_acceptance,
)
from harness_foundry_factory.models import (
    RequestValidationError,
    StateConflictError,
    content_sha256,
)
from harness_foundry_factory.store import ControlEventStore


NOW = "2026-08-04T08:40:00Z"


def graph_bindings() -> dict:
    return {
        "requirement_epoch": 38,
        "architecture_epoch": 4,
        "control_plane_epoch": 4,
        "requirement_lock_sha256": "a" * 64,
        "architecture_lock_sha256": "b" * 64,
        "compiled_contract_sha256": "c" * 64,
    }


def policy(*, conflict: bool = False) -> dict:
    rules = [
        {
            "rule_id": "RULE-CONTINUE",
            "authority_layer": "FROZEN_REQUIREMENT",
            "when": {"approved": True, "risk_delta": "NONE"},
            "decision": "MACHINE_CONTINUE",
            "reason_code": "FROZEN_SCOPE_UNCHANGED",
            "next_transition_selector": None,
        }
    ]
    if conflict:
        rules.append(
            {
                "rule_id": "RULE-CONFLICT",
                "authority_layer": "FROZEN_REQUIREMENT",
                "when": {"approved": True, "risk_delta": "NONE"},
                "decision": "HUMAN_AUTHORITY_REQUIRED",
                "reason_code": "CONFLICTING_REQUIREMENT_RULE",
                "next_transition_selector": None,
            }
        )
    return {
        "schema_version": "1.0",
        "policy_id": "POLICY-V29-TEST",
        "status": "FROZEN",
        "rule_language_id": "HF29_DETERMINISTIC_JSON_RULES",
        "rule_language_version": "1.0",
        "evaluator_ref": "harness-resource://candidate/tools/control_kernel.py",
        "evaluator_sha256": evaluator_implementation_sha256(),
        "declared_input_schema_ref": "harness-resource://candidate/contracts/decision-input.schema.json",
        "rules": rules,
        "precedence": [
            "PLATFORM_SAFETY",
            "FROZEN_CHARTER",
            "FROZEN_REQUIREMENT",
            "ARCHITECTURE_POLICY",
            "TRANSITION_LOCAL",
        ],
        "conflict_policy": "FAIL_CLOSED_POLICY_CONFLICT",
        "unknown_policy": "FAIL_CLOSED_POLICY_UNKNOWN",
        "decision_receipt_schema_ref": "harness-resource://candidate/contracts/decision-receipt.schema.json",
    }


def transition(
    transition_id: str,
    node_kind: str,
    command_class: str,
    *,
    next_transition_id: str | None = None,
    stop_gate: str | None = None,
    max_retries: int = 0,
) -> dict:
    return {
        "schema_version": "2.9",
        "transition_id": transition_id,
        "node_kind": node_kind,
        "precondition_claims": [],
        "input_refs": [],
        "allowed_read_roots": ["harness-resource://candidate"],
        "allowed_write_roots": [
            f"harness-resource://execution/work/{transition_id.lower()}"
        ],
        "required_authorization_class": "PARENT_RISK_ENVELOPE",
        "command_contract": {"command_class": command_class},
        "result_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["status", "artifact_id"],
            "properties": {
                "status": {
                    "type": "string",
                    "enum": [
                        "PASS",
                        "VALIDATION_FAILED",
                        "TEMPORARY_FAILURE",
                        "UNKNOWN_SIDE_EFFECT",
                    ],
                },
                "artifact_id": {"type": "string"},
                "reason_code": {"type": "string"},
                "applied_count": {"type": "integer"},
            },
        },
        "evidence_obligations": [f"EVIDENCE-{transition_id}"],
        "decision_policy": policy(),
        "declared_input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["approved", "risk_delta"],
            "properties": {
                "approved": {"type": "boolean"},
                "risk_delta": {"type": "string"},
            },
        },
        "retry_policy": {"max_retries": max_retries},
        "checkpoint_policy": {"resume_requires_revalidation": True},
        "risk": {
            "permissions": ["WRITE_DECLARED_EVIDENCE"],
            "network_mode": "DENY",
            "secret_access": False,
            "external_effect_class": "LOCAL_REVERSIBLE",
        },
        "next_transition_id": next_transition_id,
        "stop_gate": stop_gate,
    }


def parent(program_id: str, *, write_root: str = "harness-resource://execution/work") -> dict:
    return {
        "schema_version": "2.9",
        "authorization_id": f"PARENT-{program_id}",
        "authorization_class": "PARENT_RISK_ENVELOPE",
        "status": "GRANTED",
        "program_id": program_id,
        "allowed_write_roots": [write_root],
        "command_classes": ["READ", "STATE", "FIXTURE"],
        "permissions": ["WRITE_DECLARED_EVIDENCE"],
        "network_mode": "DENY",
        "secret_access": False,
        "external_effect_class": "LOCAL_REVERSIBLE",
        "budgets": {"max_transitions": 3, "max_attempts": 4, "max_retries": 1},
        "expires_at": "2027-08-04T00:00:00Z",
        "revocation_epoch": 0,
        "stop_gates": ["RISK_GATE"],
        "fixture_authority": "SYNTHETIC_FIXTURE_NOT_AUTHORITY",
    }


class ControlKernelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = ControlEventStore(self.root / "control.sqlite3")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_historical_kernel_is_not_a_public_new_build_api(self) -> None:
        for name in ("instantiate_program_graph", "GenericTransitionEngine",
                     "evaluate_decision_policy", "prepare_parent_authorization_challenge"):
            with self.subTest(name=name):
                self.assertNotIn(name, harness_foundry_factory.__all__)
                with self.assertRaises(AttributeError):
                    getattr(harness_foundry_factory, name)

    def test_rule_conflict_and_unknown_fail_closed(self) -> None:
        contract = transition("T1", "READ_ONLY_VALIDATION", "READ")
        conflict_policy = policy(conflict=True)
        receipt = evaluate_decision_policy(
            conflict_policy,
            contract["declared_input_schema"],
            {"approved": True, "risk_delta": "NONE"},
            transition_contract_sha256="a" * 64,
        )
        self.assertEqual(receipt["decision"], "POLICY_CONFLICT")
        receipt_material = deepcopy(receipt)
        receipt_sha256 = receipt_material.pop("receipt_sha256")
        self.assertEqual(receipt_sha256, content_sha256(receipt_material))
        unknown = evaluate_decision_policy(
            policy(),
            contract["declared_input_schema"],
            {"approved": True},
            transition_contract_sha256="a" * 64,
        )
        self.assertEqual(unknown["decision"], "POLICY_UNKNOWN")

    def test_stronger_authority_rule_wins_without_prompt_arbitration(self) -> None:
        frozen = policy()
        frozen["rules"].append(
            {
                "rule_id": "RULE-SAFETY-STOP",
                "authority_layer": "PLATFORM_SAFETY",
                "when": {"approved": True, "risk_delta": "NONE"},
                "decision": "HARD_STOP_UNKNOWN_SIDE_EFFECT",
                "reason_code": "PLATFORM_SAFETY_OVERRIDE",
                "next_transition_selector": None,
            }
        )
        contract = transition("T1", "READ_ONLY_VALIDATION", "READ")
        receipt = evaluate_decision_policy(
            frozen,
            contract["declared_input_schema"],
            {"approved": True, "risk_delta": "NONE"},
            transition_contract_sha256="a" * 64,
        )
        self.assertEqual(receipt["decision"], "HARD_STOP_UNKNOWN_SIDE_EFFECT")
        self.assertEqual(receipt["matched_rule_ids"], ["RULE-SAFETY-STOP"])

    def test_child_grant_cannot_expand_parent_scope(self) -> None:
        narrow_parent = parent(
            "PROGRAM-SCOPE", write_root="harness-resource://execution/work/allowed"
        )
        with self.assertRaises(ControlKernelError) as raised:
            derive_attempt_grant(
                narrow_parent,
                transition("ESCAPE", "READ_ONLY_VALIDATION", "READ"),
                attempt_id="ATTEMPT-1",
                input_state_sha256="b" * 64,
                fencing_token=1,
                usage={"transitions": 0, "attempts": 0, "retries": 0},
                now=NOW,
            )
        self.assertEqual(raised.exception.code, "DERIVED_GRANT_SCOPE_EXPANSION")

    def test_deterministic_validation_failure_consumes_grant_and_never_retries(
        self,
    ) -> None:
        program_id = "PROGRAM-DETERMINISTIC-FAILURE"
        calls = 0

        def validation_adapter(context: dict) -> dict:
            nonlocal calls
            calls += 1
            return {
                "status": "VALIDATION_FAILED",
                "artifact_id": "PROFILE-READ-RESULT",
                "reason_code": "PROFILE_SCHEMA_MISMATCH",
            }

        engine = GenericTransitionEngine(self.store, {"READ": validation_adapter})
        authorization = parent(program_id)
        engine.register_parent_authorization(authorization, created_at=NOW)
        outcome = engine.execute_transition(
            program_id,
            authorization["authorization_id"],
            transition(
                "READ-FAIL",
                "READ_ONLY_VALIDATION",
                "READ",
                max_retries=1,
            ),
            {"approved": True, "risk_delta": "NONE"},
            created_at=NOW,
        )

        self.assertEqual(outcome["status"], "STOPPED")
        self.assertEqual(
            outcome["stop_reason"], "DETERMINISTIC_VALIDATION_FAILURE"
        )
        self.assertEqual(outcome["reason_code"], "PROFILE_SCHEMA_MISMATCH")
        self.assertEqual(calls, 1)
        events = self.store.list_events(program_id)
        self.assertEqual(
            [event["event_type"] for event in events[-5:]],
            [
                "DECISION_RECORDED",
                "DERIVED_GRANT_ISSUED",
                "TRANSITION_ATTEMPT_STARTED",
                "DERIVED_GRANT_CONSUMED",
                "TRANSITION_STOPPED",
            ],
        )
        self.assertEqual(events[-2]["payload"]["outcome"], "VALIDATION_FAILED")
        self.assertFalse(events[-1]["payload"]["human_authority_required"])
        projection = rebuild_control_projections(events)
        grant = next(iter(projection["grant_ledger"]["derived_grants"].values()))
        self.assertEqual(grant["status"], "CONSUMED")
        self.assertEqual(
            projection["human_cost_result"]["stop_reason_counts"],
            {"DETERMINISTIC_VALIDATION_FAILURE": 1},
        )

    def test_native_store_rejects_incompatible_database_without_mutation(self) -> None:
        database = self.root / "incompatible.sqlite3"
        connection = sqlite3.connect(database)
        connection.execute(
            "CREATE TABLE control_events (event_seq INTEGER PRIMARY KEY, event_type TEXT)"
        )
        connection.commit()
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        connection.close()
        before = hashlib.sha256(database.read_bytes()).hexdigest()

        with self.assertRaises(RequestValidationError):
            ControlEventStore(database)

        self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), before)
        self.assertFalse(Path(f"{database}-wal").exists())
        check = sqlite3.connect(database)
        self.assertEqual(check.execute("PRAGMA journal_mode").fetchone()[0], journal_mode)
        self.assertEqual(
            [row[1] for row in check.execute("PRAGMA table_info(control_events)")],
            ["event_seq", "event_type"],
        )
        check.close()

    def test_native_store_database_triggers_reject_update_and_delete(self) -> None:
        program_id = "PROGRAM-APPEND-ONLY"
        self.store.append_batch(
            program_id,
            [{"event_type": "TEST_EVENT", "payload": {"value": 1}}],
            idempotency_key="TEST-EVENT-1",
            created_at=NOW,
            expected_previous_event_hash=None,
        )
        connection = sqlite3.connect(self.store.database_path)
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE control_events SET event_type = 'MUTATED' WHERE program_id = ?",
                (program_id,),
            )
        connection.rollback()
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                "DELETE FROM control_events WHERE program_id = ?",
                (program_id,),
            )
        connection.rollback()
        connection.close()

    def test_attempt_commit_cas_rejects_concurrent_event_after_adapter(self) -> None:
        program_id = "PROGRAM-ATTEMPT-CAS"
        authorization = parent(program_id)

        def racing_adapter(context: dict) -> dict:
            previous = self.store.list_events(program_id)[-1]["event_hash"]
            self.store.append_batch(
                program_id,
                [{"event_type": "CONCURRENT_TEST_EVENT", "payload": {"value": 1}}],
                idempotency_key="CONCURRENT-TEST-EVENT",
                created_at=NOW,
                expected_previous_event_hash=previous,
            )
            return {"status": "PASS", "artifact_id": "RACING-RESULT"}

        engine = GenericTransitionEngine(self.store, {"READ": racing_adapter})
        engine.register_parent_authorization(authorization, created_at=NOW)

        with self.assertRaises(StateConflictError):
            engine.execute_transition(
                program_id,
                authorization["authorization_id"],
                transition("T-CAS", "READ_ONLY_VALIDATION", "READ"),
                {"approved": True, "risk_delta": "NONE"},
                created_at=NOW,
            )

        events = self.store.list_events(program_id)
        self.assertEqual(events[-1]["event_type"], "CONCURRENT_TEST_EVENT")
        self.assertFalse(
            any(event["event_type"] == "TRANSITION_COMMITTED" for event in events)
        )

    def test_parent_revocation_invalidates_unconsumed_child_projection(self) -> None:
        program_id = "PROGRAM-REVOKE"
        engine = GenericTransitionEngine(self.store, {})
        authorization = parent(program_id)
        engine.register_parent_authorization(authorization, created_at=NOW)
        grant = derive_attempt_grant(
            authorization,
            transition("T-REVOKE", "READ_ONLY_VALIDATION", "READ"),
            attempt_id="ATTEMPT-1",
            input_state_sha256="c" * 64,
            fencing_token=1,
            usage={"transitions": 0, "attempts": 0, "retries": 0},
            now=NOW,
        )
        previous = self.store.list_events(program_id)[-1]["event_hash"]
        self.store.append_batch(
            program_id,
            [
                {
                    "event_type": "DERIVED_GRANT_ISSUED",
                    "payload": {"grant": grant},
                }
            ],
            idempotency_key="ISSUE-UNCONSUMED",
            created_at=NOW,
            expected_previous_event_hash=previous,
        )
        engine.revoke_parent_authorization(
            program_id, authorization["authorization_id"], created_at=NOW
        )
        projection = rebuild_control_projections(self.store.list_events(program_id))
        self.assertEqual(
            projection["grant_ledger"]["derived_grants"][grant["grant_id"]]["status"],
            "INVALIDATED",
        )

    def test_three_node_kinds_retry_and_resume_use_one_engine_and_parent(self) -> None:
        program_id = "PROGRAM-VERTICAL"
        internal_calls = 0
        fixture_effects: set[str] = set()

        def read_adapter(context: dict) -> dict:
            return {"status": "PASS", "artifact_id": "READ-EVIDENCE"}

        def state_adapter(context: dict) -> dict:
            nonlocal internal_calls
            internal_calls += 1
            if internal_calls == 1:
                return {
                    "status": "TEMPORARY_FAILURE",
                    "artifact_id": "STATE-EVIDENCE",
                    "reason_code": "DECLARED_TRANSIENT",
                }
            return {"status": "PASS", "artifact_id": "STATE-EVIDENCE"}

        def fixture_adapter(context: dict) -> dict:
            fixture_effects.add(str(context["idempotency_key"]))
            return {
                "status": "PASS",
                "artifact_id": "FIXTURE-EVIDENCE",
                "applied_count": 1,
            }

        engine = GenericTransitionEngine(
            self.store,
            {"READ": read_adapter, "STATE": state_adapter, "FIXTURE": fixture_adapter},
        )
        engine.record_architecture_freeze(program_id, "FREEZE-E9", created_at=NOW)
        authorization = parent(program_id)
        engine.register_parent_authorization(authorization, created_at=NOW)
        inputs = {"approved": True, "risk_delta": "NONE"}
        read = transition(
            "READ-CHECK", "READ_ONLY_VALIDATION", "READ", next_transition_id="STATE-COMMIT"
        )
        state = transition(
            "STATE-COMMIT",
            "INTERNAL_STATE_TRANSACTION",
            "STATE",
            next_transition_id="FIXTURE-ACTION",
            max_retries=1,
        )
        fixture = transition(
            "FIXTURE-ACTION",
            "BOUNDED_REVERSIBLE_FIXTURE_ACTION",
            "FIXTURE",
            stop_gate="RISK_GATE",
        )
        self.assertEqual(
            engine.execute_transition(
                program_id,
                authorization["authorization_id"],
                read,
                inputs,
                created_at=NOW,
            )["status"],
            "COMMITTED",
        )
        self.assertEqual(
            engine.execute_transition(
                program_id,
                authorization["authorization_id"],
                state,
                inputs,
                created_at=NOW,
            )["status"],
            "COMMITTED",
        )
        with self.assertRaises(InjectedKernelCrash):
            engine.execute_transition(
                program_id,
                authorization["authorization_id"],
                fixture,
                inputs,
                created_at=NOW,
                inject_crash_after_command=True,
            )
        recovered = engine.execute_transition(
            program_id,
            authorization["authorization_id"],
            fixture,
            inputs,
            created_at=NOW,
            resume=True,
        )
        self.assertEqual(recovered["status"], "COMMITTED")
        self.assertEqual(len(fixture_effects), 1)
        self.assertEqual(self.store.verify_stream(program_id)["status"], "PASS")

        projection = rebuild_control_projections(self.store.list_events(program_id))
        cost = projection["human_cost_result"]
        self.assertEqual(cost["human_decision_count"], 2)
        self.assertEqual(cost["architecture_freeze_count"], 1)
        self.assertEqual(cost["parent_risk_authorization_count"], 1)
        self.assertEqual(cost["manual_hash_input_count"], 0)
        self.assertEqual(cost["distinct_node_kind_count"], 3)
        self.assertEqual(cost["bounded_retry_count"], 1)
        self.assertEqual(cost["resume_count"], 1)
        self.assertEqual(cost["derived_grant_count"], 4)
        acceptance = evaluate_human_cost_acceptance(
            cost,
            {
                "architecture_freeze_count": 1,
                "parent_risk_authorization_count": 1,
                "human_decision_count": 2,
                "manual_hash_input_count": 0,
                "minimum_distinct_node_kinds_auto_advanced": 3,
                "minimum_derived_grant_count": 3,
                "minimum_safe_retry_or_resume_count": 1,
            },
        )
        self.assertEqual(acceptance["status"], "PASS")

    def test_sequential_parents_each_receive_an_isolated_one_transition_budget(
        self,
    ) -> None:
        program_id = "PROGRAM-SEQUENTIAL-PARENTS"
        read_calls = 0
        state_calls = 0
        fixture_calls = 0

        def read_adapter(context: dict) -> dict:
            nonlocal read_calls
            read_calls += 1
            if read_calls == 1:
                return {
                    "status": "TEMPORARY_FAILURE",
                    "artifact_id": "PROFILE-READ-EVIDENCE",
                    "reason_code": "DECLARED_TRANSIENT",
                }
            return {"status": "PASS", "artifact_id": "PROFILE-READ-EVIDENCE"}

        def state_adapter(context: dict) -> dict:
            nonlocal state_calls
            state_calls += 1
            return {"status": "PASS", "artifact_id": "PROFILE-STATE-EVIDENCE"}

        def fixture_adapter(context: dict) -> dict:
            nonlocal fixture_calls
            fixture_calls += 1
            return {"status": "PASS", "artifact_id": "FIXTURE-EVIDENCE"}

        engine = GenericTransitionEngine(
            self.store,
            {"READ": read_adapter, "STATE": state_adapter, "FIXTURE": fixture_adapter},
        )
        first_parent = parent(program_id)
        first_parent["authorization_id"] = "PARENT-PROFILE-READ"
        first_parent["budgets"] = {
            "max_transitions": 1,
            "max_attempts": 2,
            "max_retries": 1,
        }
        engine.register_parent_authorization(first_parent, created_at=NOW)
        first = engine.execute_transition(
            program_id,
            first_parent["authorization_id"],
            transition(
                "PROFILE_READ_VALIDATION",
                "READ_ONLY_VALIDATION",
                "READ",
                max_retries=1,
            ),
            {"approved": True, "risk_delta": "NONE"},
            created_at=NOW,
        )
        engine.revoke_parent_authorization(
            program_id, first_parent["authorization_id"], created_at=NOW
        )

        second_parent = parent(program_id)
        second_parent["authorization_id"] = "PARENT-PROFILE-INTERNAL-STATE"
        second_parent["budgets"] = {
            "max_transitions": 1,
            "max_attempts": 1,
            "max_retries": 0,
        }
        engine.register_parent_authorization(second_parent, created_at=NOW)
        second = engine.execute_transition(
            program_id,
            second_parent["authorization_id"],
            transition(
                "PROFILE_INTERNAL_STATE",
                "INTERNAL_STATE_TRANSACTION",
                "STATE",
            ),
            {"approved": True, "risk_delta": "NONE"},
            created_at=NOW,
        )
        engine.revoke_parent_authorization(
            program_id, second_parent["authorization_id"], created_at=NOW
        )

        self.assertEqual(first["status"], "COMMITTED")
        self.assertEqual(second["status"], "COMMITTED")
        self.assertEqual(read_calls, 2)
        self.assertEqual(state_calls, 1)
        self.assertEqual(fixture_calls, 0)
        self.assertEqual(first["attempt_id"], "PROFILE_READ_VALIDATION-ATTEMPT-2")
        self.assertEqual(second["attempt_id"], "PROFILE_INTERNAL_STATE-ATTEMPT-1")
        projection = rebuild_control_projections(self.store.list_events(program_id))
        grants = projection["grant_ledger"]["derived_grants"].values()
        self.assertEqual(
            sum(
                grant["parent_authorization_id"] == first_parent["authorization_id"]
                for grant in grants
            ),
            2,
        )
        self.assertEqual(
            sum(
                grant["parent_authorization_id"] == second_parent["authorization_id"]
                for grant in grants
            ),
            1,
        )

    def test_profile_graph_and_advance_until_real_gate_are_data_driven(self) -> None:
        program_id = "PROGRAM-AUTO"
        contracts = {
            "T-READ": transition(
                "T-READ", "READ_ONLY_VALIDATION", "READ", next_transition_id="T-STATE"
            ),
            "T-STATE": transition(
                "T-STATE", "INTERNAL_STATE_TRANSACTION", "STATE", next_transition_id="T-FIXTURE"
            ),
            "T-FIXTURE": transition(
                "T-FIXTURE",
                "BOUNDED_REVERSIBLE_FIXTURE_ACTION",
                "FIXTURE",
                stop_gate="RISK_GATE",
            ),
        }
        profile = {
            "schema_version": "2.9",
            "profile_id": "PROFILE-STATIC",
            "program_graph_template_id": "GRAPH-GENERIC",
            "activated_capabilities": ["CONTROL_VERTICAL"],
            "bindings": graph_bindings(),
            "status": "FROZEN",
        }
        for contract in contracts.values():
            contract["bindings"] = graph_bindings()
        graph = instantiate_program_graph(
            profile,
            {
                "schema_version": "2.9",
                "program_graph_template_id": "GRAPH-GENERIC",
                "bindings": graph_bindings(),
                "minimum_node_kind_count": 3,
                "capability_transitions": {
                    "CONTROL_VERTICAL": ["T-READ", "T-STATE", "T-FIXTURE"]
                },
                "transition_order": ["T-READ", "T-STATE", "T-FIXTURE"],
            },
            contracts,
            expected_bindings=graph_bindings(),
        )
        self.assertEqual(len(graph["nodes"]), 3)
        self.assertEqual(graph["bindings"], graph_bindings())
        self.assertEqual(len(graph["transition_contract_sha256_by_id"]), 3)
        adapter = lambda context: {  # noqa: E731 - tiny test adapter
            "status": "PASS",
            "artifact_id": str(context["transition_id"]),
        }
        engine = GenericTransitionEngine(
            self.store, {"READ": adapter, "STATE": adapter, "FIXTURE": adapter}
        )
        authorization = parent(program_id)
        engine.register_parent_authorization(authorization, created_at=NOW)
        outcome = engine.advance_until_gate(
            program_id,
            authorization["authorization_id"],
            contracts,
            {key: {"approved": True, "risk_delta": "NONE"} for key in contracts},
            start_transition_id="T-READ",
            created_at=NOW,
            max_transitions=3,
        )
        self.assertEqual(len(outcome["trace"]), 3)
        self.assertEqual(outcome["trace"][-1]["stop_gate"], "RISK_GATE")

    def test_profile_graph_rejects_mixed_epoch_and_stale_lock_binding(self) -> None:
        contracts = {
            "T-READ": transition("T-READ", "READ_ONLY_VALIDATION", "READ"),
            "T-STATE": transition("T-STATE", "INTERNAL_STATE_TRANSACTION", "STATE"),
            "T-FIXTURE": transition(
                "T-FIXTURE", "BOUNDED_REVERSIBLE_FIXTURE_ACTION", "FIXTURE"
            ),
        }
        bindings = graph_bindings()
        for contract in contracts.values():
            contract["bindings"] = deepcopy(bindings)
        profile = {
            "schema_version": "2.9",
            "profile_id": "PROFILE-STATIC",
            "program_graph_template_id": "GRAPH-GENERIC",
            "activated_capabilities": ["CONTROL_VERTICAL"],
            "bindings": deepcopy(bindings),
            "status": "FROZEN",
        }
        template = {
            "schema_version": "2.9",
            "program_graph_template_id": "GRAPH-GENERIC",
            "bindings": deepcopy(bindings),
            "minimum_node_kind_count": 3,
            "capability_transitions": {
                "CONTROL_VERTICAL": ["T-READ", "T-STATE", "T-FIXTURE"]
            },
            "transition_order": ["T-READ", "T-STATE", "T-FIXTURE"],
        }

        mixed = deepcopy(profile)
        mixed["bindings"]["architecture_epoch"] = 5
        with self.assertRaises(ControlKernelError) as raised:
            instantiate_program_graph(
                mixed,
                template,
                contracts,
                expected_bindings=bindings,
            )
        self.assertEqual(raised.exception.code, "PROGRAM_GRAPH_MIXED_EPOCH")

        stale = deepcopy(template)
        stale["bindings"]["architecture_lock_sha256"] = "d" * 64
        with self.assertRaises(ControlKernelError) as raised:
            instantiate_program_graph(
                profile,
                stale,
                contracts,
                expected_bindings=bindings,
            )
        self.assertEqual(raised.exception.code, "PROGRAM_GRAPH_STALE_BINDING")

    def test_profile_graph_requires_three_distinct_node_kinds(self) -> None:
        bindings = graph_bindings()
        contracts = {
            transition_id: {
                **transition(transition_id, "READ_ONLY_VALIDATION", "READ"),
                "bindings": deepcopy(bindings),
            }
            for transition_id in ("T-ONE", "T-TWO", "T-THREE")
        }
        with self.assertRaises(ControlKernelError) as raised:
            instantiate_program_graph(
                {
                    "schema_version": "2.9",
                    "profile_id": "PROFILE-STATIC",
                    "program_graph_template_id": "GRAPH-GENERIC",
                    "activated_capabilities": ["CONTROL_VERTICAL"],
                    "bindings": deepcopy(bindings),
                    "status": "FROZEN",
                },
                {
                    "schema_version": "2.9",
                    "program_graph_template_id": "GRAPH-GENERIC",
                    "bindings": deepcopy(bindings),
                    "minimum_node_kind_count": 3,
                    "capability_transitions": {
                        "CONTROL_VERTICAL": ["T-ONE", "T-TWO", "T-THREE"]
                    },
                    "transition_order": ["T-ONE", "T-TWO", "T-THREE"],
                },
                contracts,
                expected_bindings=bindings,
            )
        self.assertEqual(
            raised.exception.code,
            "PROGRAM_GRAPH_NODE_KIND_COVERAGE_INCOMPLETE",
        )


if __name__ == "__main__":
    unittest.main()
