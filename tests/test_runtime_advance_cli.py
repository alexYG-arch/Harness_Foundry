"""Slice 05 Runtime advance-until-real-gate acceptance tests."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from harness_foundry_factory.control_kernel import (
    GenericTransitionEngine,
    evaluator_implementation_sha256,
    prepare_parent_authorization_challenge,
    rebuild_control_projections,
)
from harness_foundry_factory.store import ControlEventStore


ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-08-12T08:00:00Z"


def bindings() -> dict:
    return {
        "requirement_epoch": 38,
        "architecture_epoch": 4,
        "control_plane_epoch": 4,
        "requirement_lock_sha256": "a" * 64,
        "architecture_lock_sha256": "b" * 64,
        "compiled_contract_sha256": "c" * 64,
    }


def policy(*, decision: str = "MACHINE_CONTINUE") -> dict:
    return {
        "schema_version": "2.9",
        "policy_id": f"POLICY-{decision}",
        "status": "FROZEN",
        "rule_language_id": "HF29_DETERMINISTIC_JSON_RULES",
        "rule_language_version": "1.0",
        "evaluator_sha256": evaluator_implementation_sha256(),
        "precedence": [
            "PLATFORM_SAFETY",
            "FROZEN_CHARTER",
            "FROZEN_REQUIREMENT",
            "ARCHITECTURE_POLICY",
            "TRANSITION_LOCAL",
        ],
        "conflict_policy": "FAIL_CLOSED_POLICY_CONFLICT",
        "unknown_policy": "FAIL_CLOSED_POLICY_UNKNOWN",
        "rules": [
            {
                "rule_id": f"RULE-{decision}",
                "authority_layer": "FROZEN_REQUIREMENT",
                "when": {"approved": True},
                "decision": decision,
                "reason_code": decision,
                "next_transition_selector": None,
            }
        ],
    }


def transition(
    transition_id: str,
    command_class: str,
    *,
    next_transition_id: str | None = None,
    stop_gate: str | None = None,
    max_retries: int = 0,
    effect: str = "LOCAL_REVERSIBLE",
) -> dict:
    return {
        "schema_version": "2.9",
        "transition_id": transition_id,
        "node_kind": f"NODE-{transition_id}",
        "bindings": bindings(),
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
                "status": {"type": "string"},
                "artifact_id": {"type": "string"},
                "reason_code": {"type": "string"},
            },
        },
        "evidence_obligations": [f"EVIDENCE-{transition_id}"],
        "decision_policy": policy(),
        "declared_input_schema": {
            "type": "object",
            "required": ["approved"],
            "properties": {"approved": {"type": "boolean"}},
        },
        "retry_policy": {"max_retries": max_retries},
        "checkpoint_policy": {"resume_requires_revalidation": True},
        "risk": {
            "permissions": ["WRITE_DECLARED_EVIDENCE"],
            "network_mode": "DENY",
            "secret_access": False,
            "external_effect_class": effect,
        },
        "next_transition_id": next_transition_id,
        "stop_gate": stop_gate,
    }


def parent(program_id: str, *, max_transitions: int = 3) -> dict:
    return {
        "schema_version": "2.9",
        "authorization_id": f"PARENT-{program_id}",
        "authorization_class": "PARENT_RISK_ENVELOPE",
        "status": "GRANTED",
        "program_id": program_id,
        "bindings": bindings(),
        "allowed_write_roots": ["harness-resource://execution/work"],
        "command_classes": ["READ", "STATE", "FIXTURE", "UNKNOWN"],
        "permissions": ["WRITE_DECLARED_EVIDENCE"],
        "network_mode": "DENY",
        "secret_access": False,
        "external_effect_class": "IRREVERSIBLE",
        "budgets": {
            "max_transitions": max_transitions,
            "max_attempts": 5,
            "max_retries": 1,
        },
        "expires_at": "2027-08-12T00:00:00Z",
        "revocation_epoch": 0,
        "stop_gates": ["RISK_GATE"],
    }


class RuntimeAdvanceCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "control.sqlite3"
        self.program_id = "PROGRAM-SLICE-05"
        self.store = ControlEventStore(self.database)
        self.engine = GenericTransitionEngine(self.store, {})
        self.authorization = parent(self.program_id)
        self.challenge = prepare_parent_authorization_challenge(
            self.authorization,
            expected_bindings=bindings(),
        )
        self.approval = {
            "decision": "APPROVE",
            "challenge_sha256": self.challenge["challenge_sha256"],
            "approved_by": {
                "type": "HUMAN_VIA_CODEX_CHAT",
                "chat_thread_id": "THREAD-SLICE-05",
                "turn_id": "TURN-SLICE-05-APPROVAL",
            },
            "approved_at": NOW,
        }
        self.engine.register_approved_parent_authorization(
            self.authorization,
            self.challenge,
            self.approval,
            created_at=NOW,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _contracts(self) -> dict:
        return {
            "T-READ": transition(
                "T-READ", "READ", next_transition_id="T-STATE"
            ),
            "T-STATE": transition(
                "T-STATE",
                "STATE",
                next_transition_id="T-FIXTURE",
                max_retries=1,
            ),
            "T-FIXTURE": transition(
                "T-FIXTURE", "FIXTURE", stop_gate="RISK_GATE"
            ),
        }

    def _request(
        self,
        contracts: dict | None = None,
        *,
        expected_bindings: dict | None = None,
        expected_state_sha256: str | None = None,
        adapter_results: dict | None = None,
        max_transitions: int = 3,
    ) -> dict:
        selected = contracts or self._contracts()
        return {
            "schema_version": "2.9",
            "adapter_mode": "TEST_ONLY_IDEMPOTENT_ADAPTERS",
            "program_id": self.program_id,
            "parent_authorization_id": self.authorization["authorization_id"],
            "expected_bindings": expected_bindings or bindings(),
            "expected_control_state_sha256": (
                expected_state_sha256 or self.engine.control_state_sha256(self.program_id)
            ),
            "contracts": selected,
            "inputs_by_transition": {
                transition_id: {"approved": True} for transition_id in selected
            },
            "start_transition_id": next(iter(selected)),
            "created_at": NOW,
            "max_transitions": max_transitions,
            "environment_manifest": {
                "runtime": "python-test",
                "platform": "test-local",
            },
            "artifact_manifest": {
                "artifacts": [],
                "scope": "test-only",
            },
            "test_adapter_results": adapter_results
            or {
                "READ": [{"status": "PASS", "artifact_id": "READ-RESULT"}],
                "STATE": [
                    {
                        "status": "TEMPORARY_FAILURE",
                        "artifact_id": "STATE-RESULT",
                        "reason_code": "DECLARED_TRANSIENT",
                    },
                    {"status": "PASS", "artifact_id": "STATE-RESULT"},
                ],
                "FIXTURE": [
                    {"status": "PASS", "artifact_id": "FIXTURE-RESULT"}
                ],
            },
        }

    def _run_cli(
        self, request: dict, *, allow_test_adapters: bool = True
    ) -> subprocess.CompletedProcess[str]:
        request_path = self.root / "runtime-request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        if allow_test_adapters:
            environment["HFFACTORY_ALLOW_TEST_ADAPTERS"] = "1"
        else:
            environment.pop("HFFACTORY_ALLOW_TEST_ADAPTERS", None)
        return subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "tests.legacy_cli",
                "advance-until-gate",
                "--request",
                str(request_path),
                "--control-db",
                str(self.database),
                "--json",
            ],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_readable_parent_challenge_and_machine_derived_approval_receipt(self) -> None:
        self.assertEqual(self.challenge["scope"]["command_classes"], self.authorization["command_classes"])
        self.assertEqual(self.challenge["risks"]["external_effect_class"], "IRREVERSIBLE")
        self.assertEqual(self.challenge["irreversible_effects"], ["IRREVERSIBLE"])
        self.assertEqual(self.challenge["write_roots"], self.authorization["allowed_write_roots"])
        self.assertEqual(self.challenge["budgets"], self.authorization["budgets"])
        self.assertFalse(self.challenge["manual_child_hash_input_required"])
        event = self.store.list_events(self.program_id)[0]
        receipt = event["payload"]["approval_receipt"]
        self.assertEqual(receipt["status"], "APPROVED")
        self.assertFalse(receipt["manual_child_hash_input"])
        self.assertEqual(event["payload"]["manual_hash_input"], False)

    def test_cli_advances_three_nodes_retries_once_and_emits_complete_trace(self) -> None:
        completed = self._run_cli(self._request())

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "STOPPED_AT_REAL_GATE")
        self.assertEqual(result["stop_reason"], "TRUE_GATE")
        self.assertEqual(result["gate_id"], "RISK_GATE")
        self.assertEqual(len(result["transition_receipts"]), 3)
        self.assertTrue(
            all(receipt.get("grant_sha256") for receipt in result["transition_receipts"])
        )
        self.assertEqual(
            result["parent_authorization_binding"]["approval_receipt_sha256"],
            self.store.list_events(self.program_id)[0]["payload"]["approval_receipt"]["receipt_sha256"],
        )
        self.assertEqual(result["budget_consumed"], {"attempts": 4, "retries": 1, "transitions": 3})
        self.assertEqual(result["state_hash"], self.engine.control_state_sha256(self.program_id))
        self.assertEqual(self.store.verify_stream(self.program_id)["status"], "PASS")
        projection = rebuild_control_projections(self.store.list_events(self.program_id))
        self.assertEqual(projection["human_cost_result"]["derived_grant_count"], 4)
        self.assertEqual(projection["human_cost_result"]["manual_hash_input_count"], 0)

        before_events = self.store.list_events(self.program_id)
        second = self._run_cli(
            self._request(expected_state_sha256=self.engine.control_state_sha256(self.program_id))
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(len(self.store.list_events(self.program_id)), len(before_events))
        self.assertTrue(
            all(
                item["status"] == "ALREADY_COMMITTED"
                for item in json.loads(second.stdout)["transition_receipts"]
            )
        )

    def test_binding_state_and_unknown_adapter_fail_closed_without_event(self) -> None:
        cases: list[tuple[str, dict, str]] = []
        stale = bindings()
        stale["architecture_lock_sha256"] = "d" * 64
        cases.append(("stale", self._request(expected_bindings=stale), "RUNTIME_STALE_BINDING"))
        mixed = bindings()
        mixed["control_plane_epoch"] = 5
        cases.append(("mixed", self._request(expected_bindings=mixed), "RUNTIME_MIXED_EPOCH"))
        cases.append(("cas", self._request(expected_state_sha256="0" * 64), "STATE_CAS_MISMATCH"))
        unknown_contract = {"T-UNKNOWN": transition("T-UNKNOWN", "UNKNOWN")}
        cases.append(
            (
                "adapter",
                self._request(
                    unknown_contract,
                    adapter_results={"UNUSED": [{"status": "PASS", "artifact_id": "X"}]},
                    max_transitions=1,
                ),
                "COMMAND_ADAPTER_UNAVAILABLE",
            )
        )
        for name, request, reason_code in cases:
            with self.subTest(name=name):
                before = self.store.list_events(self.program_id)
                completed = self._run_cli(request)
                self.assertEqual(completed.returncode, 6, completed.stdout)
                self.assertEqual(json.loads(completed.stdout)["error"]["reason_code"], reason_code)
                self.assertEqual(self.store.list_events(self.program_id), before)

    def test_budget_authority_irreversible_and_policy_stops_are_typed(self) -> None:
        budget_contracts = {
            "T-ONE": transition("T-ONE", "READ", next_transition_id="T-TWO"),
            "T-TWO": transition("T-TWO", "STATE"),
        }
        self._new_program(
            "budget",
            parent_patch={
                "budgets": {
                    "max_transitions": 1,
                    "max_attempts": 5,
                    "max_retries": 1,
                }
            },
        )
        budget = self._run_cli(
            self._request(
                budget_contracts,
                adapter_results={
                    "READ": [{"status": "PASS", "artifact_id": "ONE"}],
                    "STATE": [{"status": "PASS", "artifact_id": "TWO"}],
                },
                max_transitions=2,
            )
        )
        budget_result = json.loads(budget.stdout)
        self.assertEqual(budget_result["stop_reason"], "BUDGET_EXHAUSTION")
        self.assertEqual(
            budget_result["checkpoint"]["stop_reason"], "BUDGET_EXHAUSTION"
        )
        self.assertEqual(
            budget_result["resume_capsule"]["status"], "RESUME_READY"
        )
        self.assertEqual(
            [event["event_type"] for event in self.store.list_events(self.program_id)[-2:]],
            ["CHECKPOINT_RECORDED", "RESUME_CAPSULE_EMITTED"],
        )

        isolated: list[tuple[str, dict, str]] = [
            (
                "irreversible",
                {"T-RISK": transition("T-RISK", "READ", effect="IRREVERSIBLE")},
                "IRREVERSIBLE_RISK",
            ),
            (
                "policy-conflict",
                {"T-POLICY": {**transition("T-POLICY", "READ"), "decision_policy": policy(decision="POLICY_CONFLICT")}},
                "POLICY_CONFLICT",
            ),
            (
                "policy-unknown",
                {"T-POLICY": {**transition("T-POLICY", "READ"), "decision_policy": policy(decision="POLICY_UNKNOWN")}},
                "POLICY_UNKNOWN",
            ),
        ]
        for name, contracts, stop_reason in isolated:
            with self.subTest(name=name):
                self._new_program(name)
                completed = self._run_cli(
                    self._request(
                        contracts,
                        adapter_results={"READ": [{"status": "PASS", "artifact_id": "X"}]},
                        max_transitions=1,
                    )
                )
                self.assertEqual(completed.returncode, 0, completed.stdout)
                self.assertEqual(json.loads(completed.stdout)["stop_reason"], stop_reason)

        self._new_program(
            "authority",
            parent_patch={
                "allowed_write_roots": [
                    "harness-resource://execution/work/allowed"
                ]
            },
        )
        authority = self._run_cli(
            self._request(
                {"T-ESCAPE": transition("T-ESCAPE", "READ")},
                adapter_results={"READ": [{"status": "PASS", "artifact_id": "X"}]},
                max_transitions=1,
            )
        )
        self.assertEqual(json.loads(authority.stdout)["stop_reason"], "AUTHORITY_EXPANSION")

    def test_retry_exhaustion_emits_durable_recovery_pair(self) -> None:
        contracts = {
            "T-RECOVER": transition(
                "T-RECOVER", "READ", max_retries=0
            )
        }

        completed = self._run_cli(
            self._request(
                contracts,
                adapter_results={
                    "READ": [
                        {
                            "status": "TEMPORARY_FAILURE",
                            "artifact_id": "RECOVER-LATER",
                            "reason_code": "DECLARED_TRANSIENT",
                        }
                    ]
                },
                max_transitions=1,
            )
        )

        self.assertEqual(completed.returncode, 0, completed.stdout)
        result = json.loads(completed.stdout)
        self.assertEqual(result["stop_reason"], "RECOVERABLE_INTERRUPTION")
        self.assertEqual(
            result["checkpoint"]["stop_reason"], "RECOVERABLE_INTERRUPTION"
        )
        self.assertEqual(
            result["resume_capsule"]["resume_node"], "T-RECOVER"
        )
        self.assertEqual(
            [event["event_type"] for event in self.store.list_events(self.program_id)[-2:]],
            ["CHECKPOINT_RECORDED", "RESUME_CAPSULE_EMITTED"],
        )

    def test_expired_revoked_and_disabled_test_adapter_modes_fail_closed(self) -> None:
        self._new_program(
            "expired",
            parent_patch={"expires_at": "2025-01-01T00:00:00Z"},
        )
        expired = self._run_cli(self._request())
        self.assertEqual(json.loads(expired.stdout)["error"]["reason_code"], "PARENT_AUTHORIZATION_EXPIRED")

        self._new_program("revoked")
        self.engine.revoke_parent_authorization(
            self.program_id,
            self.authorization["authorization_id"],
            created_at=NOW,
        )
        revoked = self._run_cli(self._request())
        self.assertEqual(json.loads(revoked.stdout)["error"]["reason_code"], "PARENT_AUTHORIZATION_NOT_ACTIVE")

        self._new_program("disabled")
        disabled = self._run_cli(self._request(), allow_test_adapters=False)
        self.assertEqual(disabled.returncode, 6)
        self.assertEqual(json.loads(disabled.stdout)["error"]["reason_code"], "TEST_ADAPTER_MODE_DISABLED")

        self._new_program("legacy")
        legacy_database = self.root / "legacy-control.sqlite3"
        legacy_store = ControlEventStore(legacy_database)
        legacy_engine = GenericTransitionEngine(legacy_store, {})
        legacy_parent = parent("PROGRAM-SLICE-05-LEGACY")
        legacy_engine.register_parent_authorization(legacy_parent, created_at=NOW)
        self.database = legacy_database
        self.program_id = legacy_parent["program_id"]
        self.authorization = legacy_parent
        self.store = legacy_store
        self.engine = legacy_engine
        legacy = self._run_cli(self._request())
        self.assertEqual(
            json.loads(legacy.stdout)["error"]["reason_code"],
            "PARENT_READABLE_CHALLENGE_NOT_APPROVED",
        )

    def test_unknown_side_effect_stops_without_retry(self) -> None:
        completed = self._run_cli(
            self._request(
                {"T-EFFECT": transition("T-EFFECT", "READ", max_retries=1)},
                adapter_results={
                    "READ": [
                        {
                            "status": "UNKNOWN_SIDE_EFFECT",
                            "artifact_id": "EFFECT-UNKNOWN",
                        },
                        {"status": "PASS", "artifact_id": "MUST-NOT-RUN"},
                    ]
                },
                max_transitions=1,
            )
        )

        self.assertEqual(completed.returncode, 0, completed.stdout)
        result = json.loads(completed.stdout)
        self.assertEqual(result["stop_reason"], "UNKNOWN_SIDE_EFFECT")
        self.assertEqual(result["budget_consumed"]["attempts"], 1)
        events = self.store.list_events(self.program_id)
        self.assertTrue(events[-1]["payload"]["human_authority_required"])
        self.assertEqual(
            sum(event["event_type"] == "TRANSITION_ATTEMPT_STARTED" for event in events),
            1,
        )

    def _new_program(
        self, suffix: str, *, parent_patch: dict | None = None
    ) -> None:
        self.database = self.root / f"control-{suffix}.sqlite3"
        self.program_id = f"PROGRAM-SLICE-05-{suffix.upper()}"
        self.store = ControlEventStore(self.database)
        self.engine = GenericTransitionEngine(self.store, {})
        self.authorization = parent(self.program_id)
        if parent_patch:
            self.authorization.update(deepcopy(parent_patch))
        self._replace_program_authorization()

    def _replace_program_authorization(self) -> None:
        self.store = ControlEventStore(self.database)
        self.engine = GenericTransitionEngine(self.store, {})
        self.challenge = prepare_parent_authorization_challenge(
            self.authorization,
            expected_bindings=bindings(),
        )
        approval = {
            **self.approval,
            "challenge_sha256": self.challenge["challenge_sha256"],
        }
        self.engine.register_approved_parent_authorization(
            self.authorization,
            self.challenge,
            approval,
            created_at=NOW,
        )


if __name__ == "__main__":
    unittest.main()
