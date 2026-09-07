"""Minimal v2.9 generic control kernel.

The kernel is deliberately project-agnostic.  Profiles and transition data
select work; the engine only evaluates frozen rules, narrows a Parent Risk
Envelope, invokes a registered command adapter and appends authoritative
events.  All query state is rebuilt from that event stream.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from .models import content_sha256
from .store import ControlEventStore


AUTHORITY_PRECEDENCE = (
    "PLATFORM_SAFETY",
    "FROZEN_CHARTER",
    "FROZEN_REQUIREMENT",
    "ARCHITECTURE_POLICY",
    "TRANSITION_LOCAL",
)
CONTINUE_DECISIONS = {"MACHINE_CONTINUE", "MACHINE_REVIEW_THEN_CONTINUE"}
DECISIONS = CONTINUE_DECISIONS | {
    "HUMAN_AUTHORITY_REQUIRED",
    "HARD_STOP_UNKNOWN_SIDE_EFFECT",
    "POLICY_CONFLICT",
    "POLICY_UNKNOWN",
}
NETWORK_RANK = {"DENY": 0, "DECLARED_READ": 1, "DECLARED_WRITE": 2}
EFFECT_RANK = {
    "NONE": 0,
    "LOCAL_REVERSIBLE": 1,
    "EXTERNAL_REVERSIBLE": 2,
    "IRREVERSIBLE": 3,
}
PROGRAM_GRAPH_BINDING_FIELDS = (
    "requirement_epoch",
    "architecture_epoch",
    "control_plane_epoch",
    "requirement_lock_sha256",
    "architecture_lock_sha256",
    "compiled_contract_sha256",
)


class ControlKernelError(RuntimeError):
    """Fail-closed v2.9 control error with a stable reason code."""

    def __init__(
        self, code: str, message: str, *, details: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


class InjectedKernelCrash(RuntimeError):
    """Test-only crash after an idempotent adapter call, before event commit."""


CommandAdapter = Callable[[Mapping[str, Any]], Mapping[str, Any]]
TransitionResolver = Callable[[str], Mapping[str, Any] | None]
TransitionExecutor = Callable[[Mapping[str, Any]], Mapping[str, Any]]
DURABLE_DELIVERY_MODE = "DURABLE_SINGLE_ATTEMPT"


def evaluator_implementation_sha256() -> str:
    """Bind Decision Receipts to the exact evaluator implementation bytes."""

    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def evaluate_decision_policy(
    policy: Mapping[str, Any],
    declared_input_schema: Mapping[str, Any],
    inputs: Mapping[str, Any],
    *,
    transition_contract_sha256: str,
) -> dict[str, Any]:
    """Evaluate the frozen equality-rule subset of HF29 deterministic JSON rules."""

    evaluator_sha256 = evaluator_implementation_sha256()
    policy_sha256 = content_sha256(policy)
    common = {
        "schema_version": "2.9",
        "policy_id": policy.get("policy_id"),
        "policy_sha256": policy_sha256,
        "evaluator_sha256": evaluator_sha256,
        "transition_contract_sha256": transition_contract_sha256,
        "input_sha256": content_sha256(inputs),
    }
    if (
        policy.get("status") != "FROZEN"
        or policy.get("rule_language_id") != "HF29_DETERMINISTIC_JSON_RULES"
        or policy.get("rule_language_version") != "1.0"
        or policy.get("evaluator_sha256") != evaluator_sha256
        or tuple(policy.get("precedence", [])) != AUTHORITY_PRECEDENCE
        or policy.get("conflict_policy") != "FAIL_CLOSED_POLICY_CONFLICT"
        or policy.get("unknown_policy") != "FAIL_CLOSED_POLICY_UNKNOWN"
    ):
        return _decision_receipt(
            common,
            decision="POLICY_UNKNOWN",
            matched_rule_ids=[],
            reason_codes=["POLICY_BINDING_INVALID"],
            next_transition_selector=None,
        )

    properties = declared_input_schema.get("properties")
    required = declared_input_schema.get("required")
    if not isinstance(properties, Mapping) or not isinstance(required, list):
        return _decision_receipt(
            common,
            decision="POLICY_UNKNOWN",
            matched_rule_ids=[],
            reason_codes=["DECLARED_INPUT_SCHEMA_INVALID"],
            next_transition_selector=None,
        )
    if any(field not in inputs for field in required) or any(
        field not in properties for field in inputs
    ):
        return _decision_receipt(
            common,
            decision="POLICY_UNKNOWN",
            matched_rule_ids=[],
            reason_codes=["DECLARED_INPUT_MISSING_OR_UNDECLARED"],
            next_transition_selector=None,
        )
    for field, value in inputs.items():
        rule = properties.get(field)
        if not isinstance(rule, Mapping) or not _matches_json_type(
            value, rule.get("type")
        ):
            return _decision_receipt(
                common,
                decision="POLICY_UNKNOWN",
                matched_rule_ids=[],
                reason_codes=["DECLARED_INPUT_TYPE_MISMATCH"],
                next_transition_selector=None,
            )

    matches: list[Mapping[str, Any]] = []
    for rule in policy.get("rules", []):
        if not isinstance(rule, Mapping):
            return _decision_receipt(
                common,
                decision="POLICY_UNKNOWN",
                matched_rule_ids=[],
                reason_codes=["RULE_DOCUMENT_INVALID"],
                next_transition_selector=None,
            )
        when = rule.get("when")
        if (
            not isinstance(when, Mapping)
            or any(field not in properties or field not in inputs for field in when)
            or rule.get("authority_layer") not in AUTHORITY_PRECEDENCE
            or rule.get("decision") not in DECISIONS
        ):
            return _decision_receipt(
                common,
                decision="POLICY_UNKNOWN",
                matched_rule_ids=[],
                reason_codes=["RULE_NOT_EVALUABLE"],
                next_transition_selector=None,
            )
        if all(inputs[field] == expected for field, expected in when.items()):
            matches.append(rule)

    if not matches:
        return _decision_receipt(
            common,
            decision="POLICY_UNKNOWN",
            matched_rule_ids=[],
            reason_codes=["NO_RULE_MATCH"],
            next_transition_selector=None,
        )
    strongest = min(
        AUTHORITY_PRECEDENCE.index(str(rule["authority_layer"]))
        for rule in matches
    )
    effective = [
        rule
        for rule in matches
        if AUTHORITY_PRECEDENCE.index(str(rule["authority_layer"])) == strongest
    ]
    outcomes = {
        (rule.get("decision"), rule.get("next_transition_selector"))
        for rule in effective
    }
    if len(outcomes) != 1:
        return _decision_receipt(
            common,
            decision="POLICY_CONFLICT",
            matched_rule_ids=sorted(str(rule.get("rule_id")) for rule in effective),
            reason_codes=sorted(str(rule.get("reason_code")) for rule in effective),
            next_transition_selector=None,
        )
    decision, selector = next(iter(outcomes))
    return _decision_receipt(
        common,
        decision=str(decision),
        matched_rule_ids=sorted(str(rule.get("rule_id")) for rule in effective),
        reason_codes=sorted(str(rule.get("reason_code")) for rule in effective),
        next_transition_selector=str(selector) if selector is not None else None,
    )


def validate_parent_authorization(parent: Mapping[str, Any]) -> dict[str, Any]:
    """Return a normalized Parent Risk Envelope or fail closed."""

    required = {
        "authorization_id",
        "authorization_class",
        "status",
        "program_id",
        "allowed_write_roots",
        "command_classes",
        "permissions",
        "network_mode",
        "secret_access",
        "external_effect_class",
        "budgets",
        "expires_at",
        "revocation_epoch",
        "stop_gates",
    }
    if required.difference(parent):
        raise ControlKernelError(
            "PARENT_AUTHORIZATION_INVALID", "Parent Risk Envelope is incomplete"
        )
    normalized = dict(parent)
    if (
        parent.get("authorization_class") != "PARENT_RISK_ENVELOPE"
        or parent.get("status") not in {"GRANTED", "ACTIVE"}
        or parent.get("network_mode") not in NETWORK_RANK
        or parent.get("external_effect_class") not in EFFECT_RANK
        or not isinstance(parent.get("secret_access"), bool)
        or not all(
            isinstance(parent.get(field), list)
            for field in (
                "allowed_write_roots",
                "command_classes",
                "permissions",
                "stop_gates",
            )
        )
        or not isinstance(parent.get("budgets"), Mapping)
    ):
        raise ControlKernelError(
            "PARENT_AUTHORIZATION_INVALID", "Parent Risk Envelope is invalid"
        )
    budgets = parent["budgets"]
    for name in ("max_transitions", "max_attempts", "max_retries"):
        value = budgets.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ControlKernelError(
                "PARENT_AUTHORIZATION_INVALID", f"invalid budget: {name}"
            )
    _parse_time(parent["expires_at"], "PARENT_AUTHORIZATION_INVALID")
    if "local_execution" in parent:
        from .local_runtime import validate_local_execution
        validate_local_execution(parent)
    normalized["parent_authorization_sha256"] = content_sha256(parent)
    return normalized


def prepare_parent_authorization_challenge(
    parent: Mapping[str, Any],
    *,
    expected_bindings: Mapping[str, Any],
) -> dict[str, Any]:
    """Render the complete Parent scope and risk for human approval."""

    normalized = validate_parent_authorization(parent)
    bindings = _validate_runtime_bindings(
        expected_bindings,
        parent,
        (),
    )
    external_effect = str(parent["external_effect_class"])
    challenge = {
        "schema_version": "2.9",
        "challenge_kind": "PARENT_AUTHORIZATION_READABLE_RISK_CHALLENGE",
        "authorization_id": parent["authorization_id"],
        "program_id": parent["program_id"],
        "bindings": bindings,
        "scope": {
            "command_classes": list(parent["command_classes"]),
            "permissions": list(parent["permissions"]),
            "network_mode": parent["network_mode"],
            "secret_access": parent["secret_access"],
            "stop_gates": list(parent["stop_gates"]),
        },
        "risks": {
            "external_effect_class": external_effect,
            "network_mode": parent["network_mode"],
            "secret_access": parent["secret_access"],
        },
        "irreversible_effects": (
            [external_effect] if external_effect == "IRREVERSIBLE" else []
        ),
        "write_roots": list(parent["allowed_write_roots"]),
        "budgets": dict(parent["budgets"]),
        "expires_at": parent["expires_at"],
        "revocation_epoch": parent["revocation_epoch"],
        "parent_authorization_sha256": normalized[
            "parent_authorization_sha256"
        ],
        "manual_child_hash_input_required": False,
    }
    if "allowed_read_roots" in parent:
        challenge["read_roots"] = list(parent["allowed_read_roots"])
    if "local_execution" in parent:
        # This contains the actual paths, executable bindings and complete
        # command/Job selection, not merely an opaque plan digest.
        from copy import deepcopy
        challenge["local_execution"] = deepcopy(parent["local_execution"])
    challenge["challenge_sha256"] = content_sha256(challenge)
    return challenge


def derive_attempt_grant(
    parent: Mapping[str, Any],
    transition: Mapping[str, Any],
    *,
    attempt_id: str,
    input_state_sha256: str,
    fencing_token: int,
    usage: Mapping[str, int],
    now: str,
) -> dict[str, Any]:
    """Machine-derive one child Grant without asking a human for a Hash."""

    normalized_parent = validate_parent_authorization(parent)
    if _parse_time(parent["expires_at"], "PARENT_AUTHORIZATION_INVALID") <= _parse_time(
        now, "TRANSITION_TIME_INVALID"
    ):
        raise ControlKernelError(
            "PARENT_AUTHORIZATION_EXPIRED", "Parent Risk Envelope has expired"
        )
    scope = _transition_scope(transition)
    _require_scope_subset(normalized_parent, scope)
    budgets = normalized_parent["budgets"]
    if (
        usage.get("transitions", 0) >= budgets["max_transitions"]
        or usage.get("attempts", 0) >= budgets["max_attempts"]
        or usage.get("retries", 0) > budgets["max_retries"]
    ):
        raise ControlKernelError(
            "PARENT_AUTHORIZATION_BUDGET_EXHAUSTED",
            "Derived Grant would exceed the Parent budget",
        )
    transition_sha256 = content_sha256(transition)
    grant_material = {
        "schema_version": "2.9",
        "parent_authorization_id": parent["authorization_id"],
        "parent_authorization_sha256": normalized_parent[
            "parent_authorization_sha256"
        ],
        "attempt_id": attempt_id,
        "transition_contract_sha256": transition_sha256,
        "input_state_sha256": input_state_sha256,
        "scope": scope,
        "expires_at": parent["expires_at"],
        "revocation_epoch": parent["revocation_epoch"],
        "fencing_token": fencing_token,
        "status": "ISSUED",
    }
    grant_id = f"GRANT-{content_sha256(grant_material)[:32].upper()}"
    grant = {"grant_id": grant_id, **grant_material}
    grant["grant_sha256"] = content_sha256(grant)
    return grant


def rebuild_control_projections(events: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Rebuild all v2.9 control views from events; create no authority."""

    parents: dict[str, dict[str, Any]] = {}
    grants: dict[str, dict[str, Any]] = {}
    transitions: dict[str, dict[str, Any]] = {}
    decisions: list[dict[str, Any]] = []
    recovery_state: dict[str, Any] = {
        "latest_checkpoint": None,
        "latest_resume_capsule": None,
        "resumed_capsule_sha256s": [],
    }
    human_cost = {
        "architecture_freeze_count": 0,
        "parent_risk_authorization_count": 0,
        "human_decision_count": 0,
        "manual_hash_input_count": 0,
        "human_interruptions_to_completion": 0,
        "human_wait_duration_ms": 0,
        "auto_transition_count": 0,
        "derived_grant_count": 0,
        "bounded_retry_count": 0,
        "resume_count": 0,
        "stop_reason_counts": {},
    }
    distinct_node_kinds: set[str] = set()
    for event in events:
        event_type = str(event.get("event_type"))
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            raise ControlKernelError(
                "CONTROL_EVENT_INVALID", "event payload is not an object"
            )
        if event_type == "ARCHITECTURE_FREEZE_RECORDED":
            human_cost["architecture_freeze_count"] += 1
            human_cost["human_decision_count"] += 1
            human_cost["human_interruptions_to_completion"] += 1
            human_cost["manual_hash_input_count"] += int(
                bool(payload.get("manual_hash_input"))
            )
        elif event_type == "PARENT_AUTHORIZATION_GRANTED":
            parent = dict(payload["authorization"])
            approval_receipt = payload.get("approval_receipt")
            if (
                isinstance(approval_receipt, Mapping)
                and approval_receipt.get("status") == "APPROVED"
                and approval_receipt.get("authorization_id")
                == parent.get("authorization_id")
                and approval_receipt.get("parent_authorization_sha256")
                == payload.get("parent_authorization_sha256")
            ):
                parent["approved_challenge_sha256"] = approval_receipt.get(
                    "challenge_sha256"
                )
                parent["approval_receipt_sha256"] = approval_receipt.get(
                    "receipt_sha256"
                )
            parents[str(parent["authorization_id"])] = parent
            human_cost["parent_risk_authorization_count"] += 1
            human_cost["human_decision_count"] += 1
            human_cost["human_interruptions_to_completion"] += 1
            human_cost["manual_hash_input_count"] += int(
                bool(payload.get("manual_hash_input"))
            )
        elif event_type in {"PARENT_AUTHORIZATION_REVOKED", "PARENT_AUTHORIZATION_EXPIRED"}:
            parent_id = str(payload["authorization_id"])
            if parent_id in parents:
                parents[parent_id]["status"] = event_type.rsplit("_", 1)[-1]
            for grant in grants.values():
                if grant.get("parent_authorization_id") == parent_id and grant.get(
                    "status"
                ) == "ISSUED":
                    grant["status"] = "INVALIDATED"
        elif event_type == "DERIVED_GRANT_ISSUED":
            grant = dict(payload["grant"])
            grants[str(grant["grant_id"])] = grant
            human_cost["derived_grant_count"] += 1
        elif event_type == "DERIVED_GRANT_CONSUMED":
            grant_id = str(payload["grant_id"])
            if grant_id in grants:
                grants[grant_id]["status"] = "CONSUMED"
                grants[grant_id]["outcome"] = payload.get("outcome")
        elif event_type == "DECISION_RECORDED":
            decisions.append(dict(payload["decision_receipt"]))
        elif event_type == "TRANSITION_TEMPORARY_FAILURE":
            human_cost["bounded_retry_count"] += 1
        elif event_type == "TRANSITION_COMMITTED":
            transitions[str(payload["transition_id"])] = dict(payload)
            human_cost["auto_transition_count"] += 1
            distinct_node_kinds.add(str(payload["node_kind"]))
        elif event_type == "RESUME_RECONCILED":
            human_cost["resume_count"] += 1
            capsule_sha256 = payload.get("capsule_sha256")
            if isinstance(capsule_sha256, str):
                recovery_state["resumed_capsule_sha256s"].append(
                    capsule_sha256
                )
        elif event_type == "CHECKPOINT_RECORDED":
            recovery_state["latest_checkpoint"] = dict(payload["checkpoint"])
        elif event_type == "RESUME_CAPSULE_EMITTED":
            recovery_state["latest_checkpoint"] = dict(payload["checkpoint"])
            recovery_state["latest_resume_capsule"] = dict(
                payload["resume_capsule"]
            )
        elif event_type == "TRANSITION_STOPPED":
            reason = str(payload["stop_reason"])
            counts = human_cost["stop_reason_counts"]
            counts[reason] = counts.get(reason, 0) + 1
            if payload.get("human_authority_required"):
                human_cost["human_interruptions_to_completion"] += 1
    human_cost["distinct_node_kinds_auto_advanced"] = sorted(
        distinct_node_kinds
    )
    human_cost["distinct_node_kind_count"] = len(distinct_node_kinds)
    return {
        "schema_version": "2.9",
        "grant_ledger": {"parents": parents, "derived_grants": grants},
        "program_control_state": {"completed_transitions": transitions},
        "decision_receipts": decisions,
        "recovery_state": recovery_state,
        "human_cost_result": human_cost,
    }


def _durable_attempt(
    events: list[Mapping[str, Any]],
    transition: Mapping[str, Any],
    parent_id: str,
    inputs: Mapping[str, Any],
    *,
    completed: bool = False,
) -> dict[str, Any] | None:
    """Recover an intent/observation from the existing authoritative stream.

    An incomplete attempt excludes another dispatch in this Program. A known
    terminal failure remains terminal within its Parent; a new Parent is not
    permitted to bypass an unresolved earlier side effect.
    """
    grants: dict[str, Mapping[str, Any]] = {}
    attempts: dict[str, dict[str, Any]] = {}
    last_decision: Mapping[str, Any] = {}
    for event in events:
        payload = event["payload"]
        kind = event["event_type"]
        grant_id = payload.get("grant_id")
        if kind == "DECISION_RECORDED":
            last_decision = payload["decision_receipt"]
        elif kind == "DERIVED_GRANT_ISSUED":
            grant = payload["grant"]
            grants[grant["grant_id"]] = grant
        elif kind == "TRANSITION_ATTEMPT_STARTED" and payload.get("delivery_mode") == DURABLE_DELIVERY_MODE:
            attempts[grant_id] = {"intent": payload, "grant": grants[grant_id],
                                  "input_sha256": last_decision["input_sha256"],
                                  "result": None, "outcome": None}
        elif kind == "COMMAND_RESULT_OBSERVED" and grant_id in attempts:
            attempts[grant_id]["result"] = payload["result"]
        elif kind == "DERIVED_GRANT_CONSUMED" and grant_id in attempts:
            attempts[grant_id]["outcome"] = payload["outcome"]
    pending = [item for item in attempts.values() if item["outcome"] is None]
    if pending and not completed:
        if len(pending) != 1 or pending[0]["intent"]["transition_id"] != transition["transition_id"]:
            raise ControlKernelError("COMMAND_ATTEMPT_PENDING", "another command attempt is unresolved in this Program")
        selected = pending[0]
    else:
        selected = next((item for item in reversed(list(attempts.values()))
                         if item["intent"]["transition_id"] == transition["transition_id"]
                         and (completed or item["grant"]["parent_authorization_id"] == parent_id)), None)
    if selected is not None and (
        (not completed and selected["grant"]["parent_authorization_id"] != parent_id)
        or selected["grant"]["transition_contract_sha256"] != content_sha256(transition)
        or selected["input_sha256"] != content_sha256(inputs)
    ):
        raise ControlKernelError("DURABLE_COMMAND_BINDING_CHANGED", "pending command input or contract changed")
    return selected


class GenericTransitionEngine:
    """Run every declared node kind through one data-bound implementation."""

    def __init__(
        self,
        event_store: ControlEventStore,
        command_adapters: Mapping[str, CommandAdapter],
    ) -> None:
        self.event_store = event_store
        self.command_adapters = dict(command_adapters)

    def record_architecture_freeze(
        self, program_id: str, freeze_id: str, *, created_at: str
    ) -> None:
        previous = self._last_event_hash(program_id)
        self.event_store.append_batch(
            program_id,
            [
                {
                    "event_type": "ARCHITECTURE_FREEZE_RECORDED",
                    "payload": {
                        "freeze_id": freeze_id,
                        "manual_hash_input": False,
                    },
                }
            ],
            idempotency_key=f"ARCHITECTURE-FREEZE:{freeze_id}",
            created_at=created_at,
            expected_previous_event_hash=previous,
        )

    def register_parent_authorization(
        self, parent: Mapping[str, Any], *, created_at: str
    ) -> dict[str, Any]:
        normalized = validate_parent_authorization(parent)
        previous = self._last_event_hash(str(parent["program_id"]))
        self.event_store.append_batch(
            str(parent["program_id"]),
            [
                {
                    "event_type": "PARENT_AUTHORIZATION_GRANTED",
                    "payload": {
                        "authorization": dict(parent),
                        "parent_authorization_sha256": normalized[
                            "parent_authorization_sha256"
                        ],
                        "manual_hash_input": False,
                    },
                }
            ],
            idempotency_key=f"PARENT-AUTH:{parent['authorization_id']}",
            created_at=created_at,
            expected_previous_event_hash=previous,
        )
        return normalized

    def register_approved_parent_authorization(
        self,
        parent: Mapping[str, Any],
        challenge: Mapping[str, Any],
        approval: Mapping[str, Any],
        *,
        created_at: str,
    ) -> dict[str, Any]:
        """Register one Parent only after an exact readable challenge approval."""

        expected_bindings = parent.get("bindings")
        if not isinstance(expected_bindings, Mapping):
            raise ControlKernelError(
                "RUNTIME_STALE_BINDING", "Parent binding is missing"
            )
        expected_challenge = prepare_parent_authorization_challenge(
            parent,
            expected_bindings=expected_bindings,
        )
        if dict(challenge) != expected_challenge:
            raise ControlKernelError(
                "PARENT_CHALLENGE_STALE", "Readable Parent challenge is stale"
            )
        actor = approval.get("approved_by")
        if (
            approval.get("decision") != "APPROVE"
            or approval.get("challenge_sha256")
            != expected_challenge["challenge_sha256"]
            or not isinstance(actor, Mapping)
            or actor.get("type") != "HUMAN_VIA_CODEX_CHAT"
            or not isinstance(approval.get("approved_at"), str)
        ):
            raise ControlKernelError(
                "PARENT_APPROVAL_INVALID",
                "Parent approval must bind the exact readable challenge",
            )
        normalized = validate_parent_authorization(parent)
        receipt = {
            "schema_version": "2.9",
            "receipt_kind": "PARENT_AUTHORIZATION_DERIVATION_RECEIPT",
            "status": "APPROVED",
            "authorization_id": parent["authorization_id"],
            "parent_authorization_sha256": normalized[
                "parent_authorization_sha256"
            ],
            "challenge_sha256": expected_challenge["challenge_sha256"],
            "approved_by": dict(actor),
            "approved_at": approval["approved_at"],
            "manual_child_hash_input": False,
        }
        receipt["receipt_sha256"] = content_sha256(receipt)
        previous = self._last_event_hash(str(parent["program_id"]))
        self.event_store.append_batch(
            str(parent["program_id"]),
            [
                {
                    "event_type": "PARENT_AUTHORIZATION_GRANTED",
                    "payload": {
                        "authorization": dict(parent),
                        "parent_authorization_sha256": normalized[
                            "parent_authorization_sha256"
                        ],
                        "challenge": expected_challenge,
                        "approval_receipt": receipt,
                        "manual_hash_input": False,
                    },
                }
            ],
            idempotency_key=f"PARENT-AUTH:{parent['authorization_id']}",
            created_at=created_at,
            expected_previous_event_hash=previous,
        )
        return receipt

    def revoke_parent_authorization(
        self, program_id: str, authorization_id: str, *, created_at: str
    ) -> None:
        previous = self._last_event_hash(program_id)
        self.event_store.append_batch(
            program_id,
            [
                {
                    "event_type": "PARENT_AUTHORIZATION_REVOKED",
                    "payload": {"authorization_id": authorization_id},
                }
            ],
            idempotency_key=f"PARENT-REVOKE:{authorization_id}",
            created_at=created_at,
            expected_previous_event_hash=previous,
        )

    def execute_transition(
        self,
        program_id: str,
        parent_authorization_id: str,
        transition: Mapping[str, Any],
        inputs: Mapping[str, Any],
        *,
        created_at: str,
        resume: bool = False,
        resume_capsule_sha256: str | None = None,
        inject_crash_after_command: bool = False,
    ) -> dict[str, Any]:
        _validate_transition_contract(transition)
        transition_id = str(transition["transition_id"])
        durable = transition["command_contract"].get("delivery_mode") == DURABLE_DELIVERY_MODE
        events = self.event_store.list_events(program_id)
        projections = rebuild_control_projections(events)
        committed = projections["program_control_state"]["completed_transitions"].get(
            transition_id
        )
        retained = _durable_attempt(events, transition, parent_authorization_id, inputs,
                                    completed=committed is not None)
        if committed is not None:
            if durable and retained is None:
                raise ControlKernelError("DURABLE_COMMAND_HISTORY_MISSING", "completed transition has no durable command observation")
            return {"status": "ALREADY_COMMITTED", **committed}
        parent = projections["grant_ledger"]["parents"].get(
            parent_authorization_id
        )
        if not isinstance(parent, Mapping) or parent.get("status") not in {
            "GRANTED",
            "ACTIVE",
        }:
            raise ControlKernelError(
                "PARENT_AUTHORIZATION_NOT_ACTIVE",
                "transition has no active Parent Risk Envelope",
            )

        transition_sha256 = content_sha256(transition)
        decision = evaluate_decision_policy(
            transition["decision_policy"],
            transition["declared_input_schema"],
            inputs,
            transition_contract_sha256=transition_sha256,
        )
        if decision["decision"] not in CONTINUE_DECISIONS:
            stop_reason = _decision_stop_reason(str(decision["decision"]))
            previous = self._last_event_hash(program_id)
            self.event_store.append_batch(
                program_id,
                [
                    {
                        "event_type": "DECISION_RECORDED",
                        "payload": {"decision_receipt": decision},
                    },
                    {
                        "event_type": "TRANSITION_STOPPED",
                        "payload": {
                            "transition_id": transition_id,
                            "stop_reason": stop_reason,
                            "human_authority_required": decision["decision"]
                            in {
                                "HUMAN_AUTHORITY_REQUIRED",
                                "HARD_STOP_UNKNOWN_SIDE_EFFECT",
                            },
                        },
                    },
                ],
                idempotency_key=f"STOP:{transition_id}:{decision['receipt_sha256']}",
                created_at=created_at,
                expected_previous_event_hash=previous,
            )
            return {
                "status": "STOPPED",
                "transition_id": transition_id,
                "stop_reason": stop_reason,
                "decision_receipt": decision,
                "decision_receipt_sha256": decision["receipt_sha256"],
            }

        retry_policy = transition["retry_policy"]
        max_retries = int(retry_policy.get("max_retries", 0))
        while True:
            events = self.event_store.list_events(program_id)
            projections = rebuild_control_projections(events)
            retained = _durable_attempt(events, transition, parent_authorization_id, inputs)
            # Refresh the Parent at every attempt, including after a retry.
            parent = projections["grant_ledger"]["parents"].get(parent_authorization_id)
            if not isinstance(parent, Mapping) or parent.get("status") not in {"GRANTED", "ACTIVE"}:
                raise ControlKernelError("PARENT_AUTHORIZATION_NOT_ACTIVE", "command has no active Parent Risk Envelope")
            attempt_previous_event_hash = (
                str(events[-1]["event_hash"]) if events else None
            )
            usage = _parent_usage(projections, parent_authorization_id)
            if retained is not None and retained["outcome"] in {"VALIDATION_FAILED", "UNKNOWN_SIDE_EFFECT"}:
                return {
                    "status": "STOPPED", "transition_id": transition_id,
                    "attempt_id": retained["grant"]["attempt_id"],
                    "grant_id": retained["grant"]["grant_id"],
                    "stop_reason": "DETERMINISTIC_VALIDATION_FAILURE" if retained["outcome"] == "VALIDATION_FAILED" else "UNKNOWN_SIDE_EFFECT",
                    "reason_code": retained["result"].get("reason_code"),
                    "artifact_id": retained["result"].get("artifact_id"),
                }
            if retained is not None and retained["outcome"] == "TEMPORARY_FAILURE" and usage["retries"] > max_retries:
                return {"status": "STOPPED", "transition_id": transition_id,
                        "stop_reason": "DECLARED_STOP_GATE", "reason_code": "RETRY_BUDGET_EXHAUSTED"}
            recovering = retained is not None and retained["outcome"] is None
            if recovering:
                if retained["result"] is None:
                    # Another caller may still be running. Do not write a stop
                    # event that would invalidate its result-commit CAS, infer
                    # process death, or turn an observation gap into authority.
                    return {
                        "status": "STOPPED", "transition_id": transition_id,
                        "attempt_id": retained["grant"]["attempt_id"],
                        "grant_id": retained["grant"]["grant_id"],
                        "stop_reason": "COMMAND_OUTCOME_PENDING",
                        "reason_code": "COMMAND_OUTCOME_UNRESOLVED",
                        "may_still_be_running": True, "automatic_replay_allowed": False,
                        "human_authority_required": False, "writes_performed": False,
                    }
                grant = dict(retained["grant"])
                attempt_id = grant["attempt_id"]
            else:
                attempt_number = usage["attempts"] + 1
                attempt_id = f"{transition_id}-ATTEMPT-{attempt_number}"
                grant = derive_attempt_grant(
                    parent, transition, attempt_id=attempt_id,
                    input_state_sha256=content_sha256(projections["program_control_state"]),
                    fencing_token=attempt_number, usage=usage, now=created_at,
                )
            command_class = str(transition["command_contract"]["command_class"])
            command = self.command_adapters.get(command_class)
            if command is None and not recovering:
                raise ControlKernelError(
                    "COMMAND_ADAPTER_UNAVAILABLE", command_class
                )
            command_context = {
                "schema_version": "2.9",
                "program_id": program_id,
                "transition_id": transition_id,
                "node_kind": transition["node_kind"],
                "attempt_id": attempt_id,
                "idempotency_key": grant["grant_id"],
                "grant": grant,
                "inputs": dict(inputs),
                "resume": resume,
            }
            common_events = [
                {
                    "event_type": "DECISION_RECORDED",
                    "payload": {"decision_receipt": decision},
                },
                {
                    "event_type": "DERIVED_GRANT_ISSUED",
                    "payload": {"grant": grant},
                },
                {
                    "event_type": "TRANSITION_ATTEMPT_STARTED",
                    "payload": {
                        "transition_id": transition_id,
                        "attempt_id": attempt_id,
                        "grant_id": grant["grant_id"],
                    },
                },
            ]
            if durable:
                command_context["command_contract"] = dict(transition["command_contract"])
                if recovering:
                    result = dict(retained["result"])
                else:
                    # The preceding Decision Receipt already binds the input;
                    # retain that evidence rather than writing another digest.
                    common_events[-1]["payload"]["delivery_mode"] = DURABLE_DELIVERY_MODE
                    reserved = self.event_store.append_batch(
                        program_id, common_events, idempotency_key=f"COMMAND-INTENT:{grant['grant_id']}",
                        created_at=created_at, expected_previous_event_hash=attempt_previous_event_hash,
                        require_new=True,
                    )
                    attempt_previous_event_hash = reserved[-1]["event_hash"]
                    result = dict(command(command_context))
                common_events = []
            else:
                result = dict(command(command_context))
                if inject_crash_after_command:
                    raise InjectedKernelCrash("AFTER_COMMAND_BEFORE_EVENT_COMMIT")
            status = result.get("status")
            if status not in {"PASS", "VALIDATION_FAILED", "TEMPORARY_FAILURE", "UNKNOWN_SIDE_EFFECT"}:
                raise ControlKernelError("COMMAND_RESULT_INVALID", "command returned an unsupported status")
            _validate_result_schema(result, transition["result_schema"])
            if durable and not recovering:
                observed = self.event_store.append_batch(
                    program_id, [{"event_type": "COMMAND_RESULT_OBSERVED", "payload": {
                        "transition_id": transition_id, "attempt_id": attempt_id,
                        "grant_id": grant["grant_id"], "result": result,
                    }}], idempotency_key=f"COMMAND-RESULT:{grant['grant_id']}",
                    created_at=created_at, expected_previous_event_hash=attempt_previous_event_hash,
                )
                attempt_previous_event_hash = observed[-1]["event_hash"]
            if durable and inject_crash_after_command:
                raise InjectedKernelCrash("AFTER_OBSERVATION_BEFORE_TRANSITION_COMMIT")
            if status == "VALIDATION_FAILED":
                batch = common_events + [
                    {
                        "event_type": "DERIVED_GRANT_CONSUMED",
                        "payload": {
                            "grant_id": grant["grant_id"],
                            "outcome": "VALIDATION_FAILED",
                        },
                    },
                    {
                        "event_type": "TRANSITION_STOPPED",
                        "payload": {
                            "transition_id": transition_id,
                            "attempt_id": attempt_id,
                            "stop_reason": "DETERMINISTIC_VALIDATION_FAILURE",
                            "reason_code": result["reason_code"],
                            "artifact_id": result["artifact_id"],
                            "human_authority_required": False,
                        },
                    },
                ]
                self._append_attempt(
                    program_id,
                    grant,
                    batch,
                    created_at,
                    expected_previous_event_hash=attempt_previous_event_hash,
                )
                return {
                    "status": "STOPPED",
                    "transition_id": transition_id,
                    "attempt_id": attempt_id,
                    "grant_id": grant["grant_id"],
                    "grant_sha256": grant["grant_sha256"],
                    "parent_authorization_sha256": grant[
                        "parent_authorization_sha256"
                    ],
                    "stop_reason": "DETERMINISTIC_VALIDATION_FAILURE",
                    "reason_code": result["reason_code"],
                    "artifact_id": result["artifact_id"],
                    "decision_receipt": decision,
                }
            if status == "TEMPORARY_FAILURE":
                batch = common_events + [
                    {
                        "event_type": "DERIVED_GRANT_CONSUMED",
                        "payload": {
                            "grant_id": grant["grant_id"],
                            "outcome": "TEMPORARY_FAILURE",
                        },
                    },
                    {
                        "event_type": "TRANSITION_TEMPORARY_FAILURE",
                        "payload": {
                            "transition_id": transition_id,
                            "attempt_id": attempt_id,
                            "grant_id": grant["grant_id"],
                            "reason_code": result.get("reason_code"),
                        },
                    },
                ]
                self._append_attempt(
                    program_id,
                    grant,
                    batch,
                    created_at,
                    expected_previous_event_hash=attempt_previous_event_hash,
                )
                if usage["retries"] >= max_retries:
                    return {
                        "status": "STOPPED",
                        "transition_id": transition_id,
                        "attempt_id": attempt_id,
                        "grant_id": grant["grant_id"],
                        "grant_sha256": grant["grant_sha256"],
                        "parent_authorization_sha256": grant[
                            "parent_authorization_sha256"
                        ],
                        "stop_reason": "DECLARED_STOP_GATE",
                        "reason_code": "RETRY_BUDGET_EXHAUSTED",
                    }
                continue
            if status == "UNKNOWN_SIDE_EFFECT":
                batch = common_events + [
                    {
                        "event_type": "DERIVED_GRANT_CONSUMED",
                        "payload": {
                            "grant_id": grant["grant_id"],
                            "outcome": "UNKNOWN_SIDE_EFFECT",
                        },
                    },
                    {
                        "event_type": "TRANSITION_STOPPED",
                        "payload": {
                            "transition_id": transition_id,
                            "stop_reason": "UNKNOWN_SIDE_EFFECT",
                            "human_authority_required": True,
                        },
                    },
                ]
                self._append_attempt(
                    program_id,
                    grant,
                    batch,
                    created_at,
                    expected_previous_event_hash=attempt_previous_event_hash,
                )
                return {
                    "status": "STOPPED",
                    "transition_id": transition_id,
                    "attempt_id": attempt_id,
                    "grant_id": grant["grant_id"],
                    "grant_sha256": grant["grant_sha256"],
                    "parent_authorization_sha256": grant[
                        "parent_authorization_sha256"
                    ],
                    "stop_reason": "UNKNOWN_SIDE_EFFECT",
                }

            next_transition_id = decision.get("next_transition_selector") or transition.get(
                "next_transition_id"
            )
            committed_payload = {
                "transition_id": transition_id,
                "node_kind": transition["node_kind"],
                "attempt_id": attempt_id,
                "grant_id": grant["grant_id"],
                "grant_sha256": grant["grant_sha256"],
                "parent_authorization_sha256": grant[
                    "parent_authorization_sha256"
                ],
                "decision_receipt_sha256": decision["receipt_sha256"],
                "result": result,
                "result_sha256": content_sha256(result),
                "next_transition_id": next_transition_id,
                "stop_gate": transition.get("stop_gate"),
            }
            batch = common_events + [
                {
                    "event_type": "DERIVED_GRANT_CONSUMED",
                    "payload": {"grant_id": grant["grant_id"], "outcome": "PASS"},
                },
                {"event_type": "TRANSITION_COMMITTED", "payload": committed_payload},
            ]
            if resume:
                batch.append(
                    {
                        "event_type": "RESUME_RECONCILED",
                        "payload": {
                            "transition_id": transition_id,
                            "attempt_id": attempt_id,
                            "capsule_sha256": resume_capsule_sha256,
                        },
                    }
                )
            self._append_attempt(
                program_id,
                grant,
                batch,
                created_at,
                expected_previous_event_hash=attempt_previous_event_hash,
            )
            return {"status": "COMMITTED", **committed_payload}

    def advance_until_gate(
        self,
        program_id: str,
        parent_authorization_id: str,
        contracts: Mapping[str, Mapping[str, Any]],
        inputs_by_transition: Mapping[str, Mapping[str, Any]],
        *,
        start_transition_id: str,
        created_at: str,
        max_transitions: int,
    ) -> dict[str, Any]:
        return self.advance_path_until_gate(
            start_transition_id=start_transition_id,
            resolve_transition=contracts.get,
            execute_transition=lambda contract: self.execute_transition(
                program_id,
                parent_authorization_id,
                contract,
                inputs_by_transition.get(str(contract["transition_id"]), {}),
                created_at=created_at,
            ),
            max_transitions=max_transitions,
        )

    def runtime_advance_until_gate(
        self,
        program_id: str,
        parent_authorization_id: str,
        contracts: Mapping[str, Mapping[str, Any]],
        inputs_by_transition: Mapping[str, Mapping[str, Any]],
        *,
        start_transition_id: str,
        created_at: str,
        max_transitions: int,
        expected_bindings: Mapping[str, Any],
        expected_control_state_sha256: str,
        environment_manifest: Mapping[str, Any] | None = None,
        artifact_manifest: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Advance the Runtime inside one approved Parent Risk Envelope."""

        events = self.event_store.list_events(program_id)
        projections = rebuild_control_projections(events)
        parent = projections["grant_ledger"]["parents"].get(
            parent_authorization_id
        )
        if not isinstance(parent, Mapping) or parent.get("status") not in {
            "GRANTED",
            "ACTIVE",
        }:
            raise ControlKernelError(
                "PARENT_AUTHORIZATION_NOT_ACTIVE",
                "Runtime has no active Parent Risk Envelope",
            )
        if not isinstance(parent.get("approval_receipt_sha256"), str):
            raise ControlKernelError(
                "PARENT_READABLE_CHALLENGE_NOT_APPROVED",
                "Runtime Parent lacks an approved readable risk challenge",
            )
        if _parse_time(
            parent["expires_at"], "PARENT_AUTHORIZATION_INVALID"
        ) <= _parse_time(created_at, "TRANSITION_TIME_INVALID"):
            raise ControlKernelError(
                "PARENT_AUTHORIZATION_EXPIRED",
                "Parent Risk Envelope has expired",
            )
        _validate_runtime_bindings(expected_bindings, parent, contracts.values())
        if expected_control_state_sha256 != self.control_state_sha256(program_id):
            raise ControlKernelError(
                "STATE_CAS_MISMATCH",
                "Runtime control state changed before advance",
            )

        def execute(contract: Mapping[str, Any]) -> dict[str, Any]:
            risk = contract.get("risk")
            if (
                isinstance(risk, Mapping)
                and risk.get("external_effect_class") == "IRREVERSIBLE"
            ):
                return self._runtime_stop(
                    program_id,
                    str(contract["transition_id"]),
                    "IRREVERSIBLE_RISK",
                    "IRREVERSIBLE_RISK",
                    created_at=created_at,
                )
            try:
                outcome = self.execute_transition(
                    program_id,
                    parent_authorization_id,
                    contract,
                    inputs_by_transition.get(
                        str(contract["transition_id"]), {}
                    ),
                    created_at=created_at,
                )
                if outcome.get("reason_code") == "RETRY_BUDGET_EXHAUSTED":
                    stopped = self._runtime_stop(
                        program_id,
                        str(contract["transition_id"]),
                        "RECOVERABLE_INTERRUPTION",
                        "RETRY_BUDGET_EXHAUSTED",
                        created_at=created_at,
                    )
                    return {**outcome, **stopped}
                return outcome
            except ControlKernelError as exc:
                if exc.code == "DERIVED_GRANT_SCOPE_EXPANSION":
                    return self._runtime_stop(
                        program_id,
                        str(contract["transition_id"]),
                        "AUTHORITY_EXPANSION",
                        exc.code,
                        created_at=created_at,
                    )
                if exc.code == "PARENT_AUTHORIZATION_BUDGET_EXHAUSTED":
                    return self._runtime_stop(
                        program_id,
                        str(contract["transition_id"]),
                        "BUDGET_EXHAUSTION",
                        exc.code,
                        created_at=created_at,
                    )
                raise

        advanced = self.advance_path_until_gate(
            start_transition_id=start_transition_id,
            resolve_transition=contracts.get,
            execute_transition=execute,
            max_transitions=max_transitions,
        )
        trace = list(advanced["trace"])
        if advanced.get("reason_code") == "ADVANCE_BUDGET_EXHAUSTED":
            next_transition_id = (
                trace[-1].get("next_transition_id") if trace else start_transition_id
            )
            trace.append(
                self._runtime_stop(
                    program_id,
                    str(next_transition_id),
                    "BUDGET_EXHAUSTION",
                    "ADVANCE_BUDGET_EXHAUSTED",
                    created_at=created_at,
                )
            )
            advanced = {"status": "COMPLETE_OR_GATE", "trace": trace}
        last = trace[-1] if trace else {}
        stop_reason = _runtime_stop_reason(advanced, last)
        gate_id = _runtime_gate_id(advanced, last, stop_reason)
        usage = _parent_usage(
            rebuild_control_projections(self.event_store.list_events(program_id)),
            parent_authorization_id,
        )
        result = {
            "schema_version": "2.9",
            "status": "STOPPED_AT_REAL_GATE",
            "program_id": program_id,
            "parent_authorization_id": parent_authorization_id,
            "parent_authorization_binding": {
                "parent_authorization_sha256": content_sha256(
                    {
                        key: value
                        for key, value in parent.items()
                        if key
                        not in {
                            "approved_challenge_sha256",
                            "approval_receipt_sha256",
                        }
                    }
                ),
                "approved_challenge_sha256": parent[
                    "approved_challenge_sha256"
                ],
                "approval_receipt_sha256": parent[
                    "approval_receipt_sha256"
                ],
            },
            "transition_receipts": trace,
            "stop_reason": stop_reason,
            "gate_id": gate_id,
            "budget_consumed": usage,
            "state_hash": self.control_state_sha256(program_id),
            "event_stream": self.event_store.verify_stream(program_id),
            "execution_root_created": False,
        }
        if stop_reason in {"BUDGET_EXHAUSTION", "RECOVERABLE_INTERRUPTION"}:
            if not isinstance(environment_manifest, Mapping) or not isinstance(
                artifact_manifest, Mapping
            ):
                raise ControlKernelError(
                    "CHECKPOINT_CONTEXT_MISSING",
                    "Recoverable Runtime stops require environment and artifact manifests",
                )
            checkpoint_result = self.create_checkpoint(
                program_id,
                parent_authorization_id,
                expected_bindings=expected_bindings,
                expected_control_state_sha256=self.control_state_sha256(
                    program_id
                ),
                environment_manifest=environment_manifest,
                artifact_manifest=artifact_manifest,
                resume_node=str(last.get("transition_id")),
                created_at=created_at,
            )
            result.update(
                {
                    "checkpoint": checkpoint_result["checkpoint"],
                    "resume_capsule": checkpoint_result["resume_capsule"],
                    "state_hash": self.control_state_sha256(program_id),
                    "event_stream": self.event_store.verify_stream(program_id),
                }
            )
        return result

    def create_checkpoint(
        self,
        program_id: str,
        parent_authorization_id: str,
        *,
        expected_bindings: Mapping[str, Any],
        expected_control_state_sha256: str,
        environment_manifest: Mapping[str, Any],
        artifact_manifest: Mapping[str, Any],
        resume_node: str,
        created_at: str,
    ) -> dict[str, Any]:
        """Append a durable Checkpoint and Resume Capsule to the control stream."""

        request_material = {
            "program_id": program_id,
            "parent_authorization_id": parent_authorization_id,
            "expected_bindings": dict(expected_bindings),
            "expected_control_state_sha256": expected_control_state_sha256,
            "environment_manifest_sha256": content_sha256(environment_manifest),
            "artifact_manifest_sha256": content_sha256(artifact_manifest),
            "resume_node": resume_node,
        }
        request_sha256 = content_sha256(request_material)
        events = self.event_store.list_events(program_id)
        stream = self.event_store.verify_stream(program_id)
        if stream["status"] != "PASS":
            raise ControlKernelError(
                "CONTROL_EVENT_STREAM_INVALID",
                "Checkpoint requires a valid authoritative control event stream",
            )
        if events and events[-1]["event_type"] == "RESUME_CAPSULE_EMITTED":
            latest = events[-1]["payload"]
            if latest.get("checkpoint_request_sha256") == request_sha256:
                return {
                    "schema_version": "2.9",
                    "status": latest["resume_capsule"]["status"],
                    "program_id": program_id,
                    "checkpoint": dict(latest["checkpoint"]),
                    "resume_capsule": dict(latest["resume_capsule"]),
                    "writes_performed": False,
                    "execution_started": False,
                }
        if expected_control_state_sha256 != self.control_state_sha256(program_id):
            raise ControlKernelError(
                "STATE_CAS_MISMATCH",
                "Runtime control state changed before Checkpoint",
            )
        if not isinstance(resume_node, str) or not resume_node:
            raise ControlKernelError(
                "CHECKPOINT_INPUT_INVALID", "resume_node is required"
            )
        if not isinstance(environment_manifest, Mapping) or not isinstance(
            artifact_manifest, Mapping
        ):
            raise ControlKernelError(
                "CHECKPOINT_INPUT_INVALID",
                "environment and artifact manifests are required",
            )
        if not events:
            raise ControlKernelError(
                "CONTROL_EVENT_STREAM_INVALID",
                "Checkpoint requires a valid non-empty control event stream",
            )
        projection = rebuild_control_projections(events)
        parent = _active_approved_parent(
            projection, parent_authorization_id, created_at
        )
        bindings = _validate_runtime_bindings(
            expected_bindings, parent, ()
        )
        parent_sha256 = _projected_parent_authorization_sha256(parent)
        completed_artifacts = _completed_artifacts(projection)
        side_effect_inventory, unknown_side_effects = _side_effect_inventory(
            events, projection
        )
        usage = _parent_usage(projection, parent_authorization_id)
        stop_event = next(
            (
                event
                for event in reversed(events)
                if event["event_type"] == "TRANSITION_STOPPED"
            ),
            None,
        )
        checkpoint = {
            "schema_version": "2.9",
            "checkpoint_kind": "DURABLE_CONTROL_EVENT_CHECKPOINT",
            "program_id": program_id,
            "parent_authorization_id": parent_authorization_id,
            "authorization_hash": parent_sha256,
            "bindings": bindings,
            "completed_event_hash": events[-1]["event_hash"],
            "completed_artifacts": completed_artifacts,
            "environment_hash": content_sha256(environment_manifest),
            "artifact_manifest_hash": content_sha256(artifact_manifest),
            "side_effect_inventory": side_effect_inventory,
            "stop_reason": (
                stop_event["payload"].get("stop_reason")
                if stop_event is not None
                else "EXPLICIT_CHECKPOINT"
            ),
            "stop_event_hash": (
                stop_event["event_hash"] if stop_event is not None else None
            ),
            "resume_node": resume_node,
            "created_at": created_at,
        }
        checkpoint["checkpoint_sha256"] = content_sha256(checkpoint)
        checkpoint_event = self.event_store.preview_event(
            program_id,
            len(events) + 1,
            "CHECKPOINT_RECORDED",
            {"checkpoint": checkpoint},
            previous_event_hash=events[-1]["event_hash"],
            created_at=created_at,
        )
        capsule = {
            "schema_version": "2.9",
            "capsule_kind": "DURABLE_RESUME_CAPSULE",
            "status": (
                "HUMAN_DECISION_REQUIRED"
                if unknown_side_effects
                else "RESUME_READY"
            ),
            "program_id": program_id,
            "parent_authorization_id": parent_authorization_id,
            "authorization_hash": parent_sha256,
            "bindings": bindings,
            "checkpoint_sha256": checkpoint["checkpoint_sha256"],
            "checkpoint_event_hash": checkpoint_event["event_hash"],
            "revalidation_requirements": [
                "CURRENT_PARENT_AUTHORIZATION",
                "RUNTIME_BINDINGS",
                "ENVIRONMENT_HASH",
                "ARTIFACT_MANIFEST_HASH",
                "EVENT_TIP",
                "FENCING_TOKEN",
                "UNKNOWN_SIDE_EFFECTS_EMPTY",
            ],
            "resume_node": resume_node,
            "fencing_token": usage["attempts"] + 1,
            "unknown_side_effects": unknown_side_effects,
            "created_at": created_at,
        }
        capsule["capsule_sha256"] = content_sha256(capsule)
        appended = self.event_store.append_batch(
            program_id,
            [
                {
                    "event_type": "CHECKPOINT_RECORDED",
                    "payload": {"checkpoint": checkpoint},
                },
                {
                    "event_type": "RESUME_CAPSULE_EMITTED",
                    "payload": {
                        "checkpoint": checkpoint,
                        "resume_capsule": capsule,
                        "checkpoint_request_sha256": request_sha256,
                    },
                }
            ],
            idempotency_key=f"CHECKPOINT-CAPSULE:{request_sha256}",
            created_at=created_at,
            expected_previous_event_hash=events[-1]["event_hash"],
        )
        if appended[0]["event_hash"] != checkpoint_event["event_hash"]:
            raise ControlKernelError(
                "CHECKPOINT_EVENT_HASH_MISMATCH",
                "Control Event Store did not reproduce the previewed Checkpoint Hash",
            )
        return {
            "schema_version": "2.9",
            "status": capsule["status"],
            "program_id": program_id,
            "checkpoint": checkpoint,
            "resume_capsule": capsule,
            "writes_performed": True,
            "execution_started": False,
        }

    def resume_from_capsule(
        self,
        capsule: Mapping[str, Any],
        transition: Mapping[str, Any],
        inputs: Mapping[str, Any],
        *,
        expected_bindings: Mapping[str, Any],
        expected_control_state_sha256: str,
        expected_fencing_token: int,
        environment_manifest: Mapping[str, Any],
        artifact_manifest: Mapping[str, Any],
        created_at: str,
    ) -> dict[str, Any]:
        """Revalidate a durable Capsule and resume through the same engine."""

        capsule_material = dict(capsule)
        claimed_capsule_sha256 = capsule_material.pop("capsule_sha256", None)
        if claimed_capsule_sha256 != content_sha256(capsule_material):
            raise ControlKernelError(
                "RESUME_CAPSULE_INVALID", "Resume Capsule Hash does not verify"
            )
        program_id = capsule.get("program_id")
        parent_authorization_id = capsule.get("parent_authorization_id")
        if not isinstance(program_id, str) or not isinstance(
            parent_authorization_id, str
        ):
            raise ControlKernelError(
                "RESUME_CAPSULE_INVALID", "Resume Capsule identity is invalid"
            )
        if not isinstance(environment_manifest, Mapping) or not isinstance(
            artifact_manifest, Mapping
        ):
            raise ControlKernelError(
                "RESUME_INPUT_INVALID",
                "Resume requires environment and artifact manifests",
            )
        stream = self.event_store.verify_stream(program_id)
        if stream["status"] != "PASS":
            raise ControlKernelError(
                "CONTROL_EVENT_STREAM_INVALID",
                "Resume requires a valid authoritative control event stream",
            )
        events = self.event_store.list_events(program_id)
        projection = rebuild_control_projections(events)
        if claimed_capsule_sha256 in projection["recovery_state"][
            "resumed_capsule_sha256s"
        ]:
            completed = projection["program_control_state"][
                "completed_transitions"
            ].get(str(capsule.get("resume_node")))
            return {
                "schema_version": "2.9",
                "status": "ALREADY_RESUMED",
                "program_id": program_id,
                "resume_node": capsule.get("resume_node"),
                "transition_receipt": (
                    {"status": "ALREADY_COMMITTED", **dict(completed)}
                    if isinstance(completed, Mapping)
                    else None
                ),
                "checkpoint_sha256": capsule.get("checkpoint_sha256"),
                "capsule_sha256": claimed_capsule_sha256,
                "state_hash": self.control_state_sha256(program_id),
                "event_stream": self.event_store.verify_stream(program_id),
                "writes_performed": False,
                "execution_root_created": False,
            }
        parent = _active_approved_parent(
            projection, parent_authorization_id, created_at
        )
        if capsule.get("authorization_hash") != _projected_parent_authorization_sha256(
            parent
        ):
            raise ControlKernelError(
                "RESUME_AUTHORIZATION_DRIFT",
                "Current Parent Authorization differs from Checkpoint",
            )
        bindings = _validate_runtime_bindings(
            expected_bindings, parent, (transition,)
        )
        if capsule.get("bindings") != bindings:
            raise ControlKernelError(
                "RUNTIME_STALE_BINDING", "Resume Capsule binding is stale"
            )
        if capsule.get("unknown_side_effects"):
            raise ControlKernelError(
                "UNKNOWN_SIDE_EFFECT_HARD_STOP",
                "Unknown side effects require a human decision and cannot auto-resume",
            )
        if expected_control_state_sha256 != self.control_state_sha256(program_id):
            raise ControlKernelError(
                "STATE_CAS_MISMATCH", "Runtime state changed before Resume"
            )
        if (
            not events
            or events[-1]["event_type"] != "RESUME_CAPSULE_EMITTED"
            or events[-1]["payload"].get("resume_capsule") != dict(capsule)
        ):
            raise ControlKernelError(
                "EVENT_TIP_DRIFT", "Resume Capsule is not the current event tip"
            )
        checkpoint = events[-1]["payload"].get("checkpoint")
        if (
            not isinstance(checkpoint, Mapping)
            or checkpoint.get("checkpoint_sha256")
            != capsule.get("checkpoint_sha256")
            or len(events) < 2
            or events[-2]["event_type"] != "CHECKPOINT_RECORDED"
            or events[-2]["event_hash"] != capsule.get("checkpoint_event_hash")
            or events[-2]["payload"].get("checkpoint") != checkpoint
            or content_sha256(
                {
                    key: value
                    for key, value in checkpoint.items()
                    if key != "checkpoint_sha256"
                }
            )
            != checkpoint.get("checkpoint_sha256")
        ):
            raise ControlKernelError(
                "CHECKPOINT_BINDING_INVALID",
                "Resume Capsule does not bind the authoritative Checkpoint event",
            )
        if content_sha256(environment_manifest) != checkpoint.get(
            "environment_hash"
        ):
            raise ControlKernelError(
                "ENVIRONMENT_DRIFT", "Environment differs from Checkpoint"
            )
        if content_sha256(artifact_manifest) != checkpoint.get(
            "artifact_manifest_hash"
        ):
            raise ControlKernelError(
                "ARTIFACT_DRIFT", "Artifact manifest differs from Checkpoint"
            )
        expected_next_fence = _parent_usage(
            projection, parent_authorization_id
        )["attempts"] + 1
        if (
            not isinstance(expected_fencing_token, int)
            or isinstance(expected_fencing_token, bool)
            or expected_fencing_token != capsule.get("fencing_token")
            or expected_fencing_token != expected_next_fence
        ):
            raise ControlKernelError(
                "FENCING_TOKEN_MISMATCH",
                "Resume fencing token is stale or invalid",
            )
        if transition.get("transition_id") != capsule.get("resume_node"):
            raise ControlKernelError(
                "RESUME_NODE_MISMATCH",
                "Transition does not match the Capsule resume node",
            )
        outcome = self.execute_transition(
            program_id,
            parent_authorization_id,
            transition,
            inputs,
            created_at=created_at,
            resume=True,
            resume_capsule_sha256=str(claimed_capsule_sha256),
        )
        return {
            "schema_version": "2.9",
            "status": (
                "RESUMED"
                if outcome.get("status") in {"COMMITTED", "ALREADY_COMMITTED"}
                else "STOPPED_AT_REAL_GATE"
            ),
            "program_id": program_id,
            "resume_node": capsule["resume_node"],
            "transition_receipt": outcome,
            "checkpoint_sha256": capsule["checkpoint_sha256"],
            "capsule_sha256": capsule["capsule_sha256"],
            "state_hash": self.control_state_sha256(program_id),
            "event_stream": self.event_store.verify_stream(program_id),
            "execution_root_created": False,
        }

    def explain_stop(self, program_id: str) -> dict[str, Any]:
        """Return a read-only typed explanation of the latest Runtime stop."""

        stream = self.event_store.verify_stream(program_id)
        if stream["status"] != "PASS":
            raise ControlKernelError(
                "CONTROL_EVENT_STREAM_INVALID",
                "Stop evidence requires a valid authoritative event stream",
            )
        events = self.event_store.list_events(program_id)
        stop = next(
            (
                event
                for event in reversed(events)
                if event["event_type"] == "TRANSITION_STOPPED"
            ),
            None,
        )
        if stop is None:
            raise ControlKernelError("STOP_NOT_FOUND", "Runtime has no stop event")
        reason = str(stop["payload"].get("stop_reason"))
        owner, finding, path = _stop_explanation(reason)
        capsule_event = next(
            (
                event
                for event in reversed(events)
                if event["event_type"] == "RESUME_CAPSULE_EMITTED"
                and event["payload"]["checkpoint"].get("stop_event_hash")
                == stop["event_hash"]
            ),
            None,
        )
        evidence = {
            "stop_event_id": stop["event_id"],
            "stop_event_hash": stop["event_hash"],
            "stop_payload": dict(stop["payload"]),
            "checkpoint_sha256": (
                capsule_event["payload"]["checkpoint"]["checkpoint_sha256"]
                if capsule_event is not None
                else None
            ),
            "capsule_sha256": (
                capsule_event["payload"]["resume_capsule"]["capsule_sha256"]
                if capsule_event is not None
                else None
            ),
        }
        return {
            "schema_version": "2.9",
            "status": "STOP_EXPLAINED",
            "program_id": program_id,
            "blocker": {
                "blocker_type": reason,
                "owner": owner,
                "finding": finding,
                "evidence": evidence,
                "minimum_return_path": {"intents": path},
                "human_gate": reason
                in {
                    "UNKNOWN_SIDE_EFFECT",
                    "AUTHORITY_EXPANSION",
                    "IRREVERSIBLE_RISK",
                },
            },
            "writes_performed": False,
            "execution_started": False,
        }

    def control_state_sha256(self, program_id: str) -> str:
        events = self.event_store.list_events(program_id)
        projection = rebuild_control_projections(events)
        return content_sha256(
            {
                "program_id": program_id,
                "projection": projection,
                "event_stream_tip_sha256": (
                    events[-1]["event_hash"] if events else None
                ),
            }
        )

    def _runtime_stop(
        self,
        program_id: str,
        transition_id: str,
        stop_reason: str,
        reason_code: str,
        *,
        created_at: str,
    ) -> dict[str, Any]:
        previous = self._last_event_hash(program_id)
        events = self.event_store.append_batch(
            program_id,
            [
                {
                    "event_type": "TRANSITION_STOPPED",
                    "payload": {
                        "transition_id": transition_id,
                        "stop_reason": stop_reason,
                        "reason_code": reason_code,
                        "human_authority_required": stop_reason
                        in {"AUTHORITY_EXPANSION", "IRREVERSIBLE_RISK"},
                    },
                }
            ],
            idempotency_key=f"RUNTIME-STOP:{transition_id}:{stop_reason}",
            created_at=created_at,
            expected_previous_event_hash=previous,
        )
        return {
            "status": "STOPPED",
            "transition_id": transition_id,
            "stop_reason": stop_reason,
            "reason_code": reason_code,
            "stop_event_hash": events[-1]["event_hash"],
        }

    @staticmethod
    def advance_path_until_gate(
        *,
        start_transition_id: str,
        resolve_transition: TransitionResolver,
        execute_transition: TransitionExecutor,
        max_transitions: int,
    ) -> dict[str, Any]:
        """Run one deterministic path; Factory Authoring and Runtime share this loop."""

        if not isinstance(max_transitions, int) or max_transitions < 1:
            raise ControlKernelError(
                "ADVANCE_BUDGET_INVALID", "max_transitions must be positive"
            )
        current: str | None = start_transition_id
        trace: list[dict[str, Any]] = []
        while current is not None and len(trace) < max_transitions:
            contract = resolve_transition(current)
            if not isinstance(contract, Mapping):
                raise ControlKernelError("TRANSITION_CONTRACT_MISSING", current)
            outcome = dict(execute_transition(contract))
            if outcome.get("status") not in {
                "ALREADY_COMMITTED",
                "COMMITTED",
                "STOPPED",
            }:
                raise ControlKernelError(
                    "TRANSITION_OUTCOME_INVALID",
                    "advance path received an unsupported transition outcome",
                )
            trace.append(outcome)
            if outcome["status"] == "STOPPED" or outcome.get("stop_gate"):
                return {"status": "COMPLETE_OR_GATE", "trace": trace}
            current = outcome.get("next_transition_id")
            if current is not None and not isinstance(current, str):
                raise ControlKernelError(
                    "TRANSITION_OUTCOME_INVALID", "next transition is invalid"
                )
        if current is not None:
            return {
                "status": "STOPPED",
                "stop_reason": "DECLARED_STOP_GATE",
                "reason_code": "ADVANCE_BUDGET_EXHAUSTED",
                "trace": trace,
            }
        return {"status": "COMPLETE_OR_GATE", "trace": trace}

    def _append_attempt(
        self,
        program_id: str,
        grant: Mapping[str, Any],
        batch: list[Mapping[str, Any]],
        created_at: str,
        *,
        expected_previous_event_hash: str | None,
    ) -> None:
        self.event_store.append_batch(
            program_id,
            batch,
            idempotency_key=f"ATTEMPT:{grant['grant_id']}",
            created_at=created_at,
            expected_previous_event_hash=expected_previous_event_hash,
        )

    def _last_event_hash(self, program_id: str) -> str | None:
        events = self.event_store.list_events(program_id)
        return str(events[-1]["event_hash"]) if events else None


def instantiate_program_graph(
    profile: Mapping[str, Any],
    graph_template: Mapping[str, Any],
    contracts: Mapping[str, Mapping[str, Any]],
    *,
    expected_bindings: Mapping[str, Any],
) -> dict[str, Any]:
    """Instantiate only capabilities activated by a frozen static Profile."""

    if profile.get("schema_version") != "2.9" or profile.get("status") != "FROZEN":
        raise ControlKernelError("ASSURANCE_PROFILE_NOT_FROZEN", "profile")
    if graph_template.get("schema_version") != "2.9":
        raise ControlKernelError("PROGRAM_GRAPH_TEMPLATE_INVALID", "schema version")
    bindings = _validate_program_graph_bindings(
        profile,
        graph_template,
        contracts,
        expected_bindings,
    )
    template_id = graph_template.get("program_graph_template_id")
    if (
        not isinstance(template_id, str)
        or profile.get("program_graph_template_id") != template_id
    ):
        raise ControlKernelError(
            "PROGRAM_GRAPH_TEMPLATE_INVALID",
            "profile and template identity differ",
        )
    capability_transitions = graph_template.get("capability_transitions")
    order = graph_template.get("transition_order")
    if not isinstance(capability_transitions, Mapping) or not isinstance(order, list):
        raise ControlKernelError("PROGRAM_GRAPH_TEMPLATE_INVALID", "template")
    selected: set[str] = set()
    for capability in profile.get("activated_capabilities", []):
        routed = capability_transitions.get(capability)
        if not isinstance(routed, list):
            raise ControlKernelError(
                "PROFILE_CAPABILITY_UNROUTED", str(capability)
            )
        selected.update(str(value) for value in routed)
    ordered = [str(value) for value in order if str(value) in selected]
    if (
        selected.difference(ordered)
        or len(ordered) != len(selected)
        or any(item not in contracts for item in ordered)
    ):
        raise ControlKernelError("PROGRAM_GRAPH_TEMPLATE_INVALID", "transition set")
    for transition_id in ordered:
        if contracts[transition_id].get("schema_version") != "2.9":
            raise ControlKernelError(
                "PROGRAM_GRAPH_TEMPLATE_INVALID",
                "transition schema version",
            )
        _validate_transition_contract(contracts[transition_id])
    nodes = [
        {
            "transition_id": transition_id,
            "node_kind": contracts[transition_id]["node_kind"],
            "transition_contract_sha256": content_sha256(
                contracts[transition_id]
            ),
        }
        for transition_id in ordered
    ]
    node_kinds = {str(node["node_kind"]) for node in nodes}
    minimum_node_kind_count = graph_template.get("minimum_node_kind_count")
    if (
        not isinstance(minimum_node_kind_count, int)
        or isinstance(minimum_node_kind_count, bool)
        or minimum_node_kind_count < 3
        or len(node_kinds) < minimum_node_kind_count
    ):
        raise ControlKernelError(
            "PROGRAM_GRAPH_NODE_KIND_COVERAGE_INCOMPLETE",
            "profile route does not cover the required distinct node kinds",
        )
    edges = [
        {"from": left, "to": right}
        for left, right in zip(ordered, ordered[1:])
    ]
    graph = {
        "schema_version": "2.9",
        "profile_id": profile["profile_id"],
        "program_graph_template_id": template_id,
        "bindings": bindings,
        "nodes": nodes,
        "edges": edges,
        "transition_contract_sha256_by_id": {
            str(node["transition_id"]): node["transition_contract_sha256"]
            for node in nodes
        },
        "status": "INSTANTIATED_NOT_EXECUTED",
    }
    graph["program_graph_sha256"] = content_sha256(graph)
    return graph


def _validate_program_graph_bindings(
    profile: Mapping[str, Any],
    graph_template: Mapping[str, Any],
    contracts: Mapping[str, Mapping[str, Any]],
    expected_bindings: Mapping[str, Any],
) -> dict[str, Any]:
    if any(field not in expected_bindings for field in PROGRAM_GRAPH_BINDING_FIELDS):
        raise ControlKernelError(
            "PROGRAM_GRAPH_STALE_BINDING",
            "expected lock and epoch binding is incomplete",
        )
    normalized = {
        field: expected_bindings[field] for field in PROGRAM_GRAPH_BINDING_FIELDS
    }
    epoch_fields = PROGRAM_GRAPH_BINDING_FIELDS[:3]
    if any(
        not isinstance(normalized[field], int)
        or isinstance(normalized[field], bool)
        or normalized[field] < 1
        for field in epoch_fields
    ) or any(
        not isinstance(normalized[field], str)
        or len(normalized[field]) != 64
        or any(character not in "0123456789abcdef" for character in normalized[field])
        for field in PROGRAM_GRAPH_BINDING_FIELDS[3:]
    ):
        raise ControlKernelError(
            "PROGRAM_GRAPH_STALE_BINDING",
            "expected lock and epoch binding is invalid",
        )
    for source in (profile, graph_template, *contracts.values()):
        binding = source.get("bindings")
        if not isinstance(binding, Mapping):
            raise ControlKernelError(
                "PROGRAM_GRAPH_STALE_BINDING",
                "profile, template, or transition binding is missing",
            )
        if any(binding.get(field) != normalized[field] for field in epoch_fields):
            raise ControlKernelError(
                "PROGRAM_GRAPH_MIXED_EPOCH",
                "profile, template, and transitions must use one epoch tuple",
            )
        if any(
            binding.get(field) != normalized[field]
            for field in PROGRAM_GRAPH_BINDING_FIELDS[3:]
        ):
            raise ControlKernelError(
                "PROGRAM_GRAPH_STALE_BINDING",
                "profile, template, or transition lock binding is stale",
            )
    return normalized


def _validate_runtime_bindings(
    expected_bindings: Mapping[str, Any],
    parent: Mapping[str, Any],
    transitions: Any,
) -> dict[str, Any]:
    if any(field not in expected_bindings for field in PROGRAM_GRAPH_BINDING_FIELDS):
        raise ControlKernelError(
            "RUNTIME_STALE_BINDING", "Runtime binding is incomplete"
        )
    normalized = {
        field: expected_bindings[field] for field in PROGRAM_GRAPH_BINDING_FIELDS
    }
    if (
        any(
            not isinstance(normalized[field], int)
            or isinstance(normalized[field], bool)
            or normalized[field] < 1
            for field in PROGRAM_GRAPH_BINDING_FIELDS[:3]
        )
        or normalized["architecture_epoch"]
        != normalized["control_plane_epoch"]
    ):
        raise ControlKernelError(
            "RUNTIME_MIXED_EPOCH",
            "Runtime Architecture and Control Plane epochs must match",
        )
    if any(
        not isinstance(normalized[field], str)
        or len(normalized[field]) != 64
        or any(
            character not in "0123456789abcdef"
            for character in normalized[field]
        )
        for field in PROGRAM_GRAPH_BINDING_FIELDS[3:]
    ):
        raise ControlKernelError(
            "RUNTIME_STALE_BINDING", "Runtime lock binding is invalid"
        )
    sources = (parent, *tuple(transitions))
    for source in sources:
        source_bindings = source.get("bindings")
        if not isinstance(source_bindings, Mapping):
            raise ControlKernelError(
                "RUNTIME_STALE_BINDING", "Runtime source binding is missing"
            )
        if (
            source_bindings.get("architecture_epoch")
            != source_bindings.get("control_plane_epoch")
            or any(
                source_bindings.get(field) != normalized[field]
                for field in PROGRAM_GRAPH_BINDING_FIELDS[:3]
            )
        ):
            raise ControlKernelError(
                "RUNTIME_MIXED_EPOCH", "Runtime source epoch is mixed"
            )
        if any(
            source_bindings.get(field) != normalized[field]
            for field in PROGRAM_GRAPH_BINDING_FIELDS[3:]
        ):
            raise ControlKernelError(
                "RUNTIME_STALE_BINDING", "Runtime source lock binding is stale"
            )
    return normalized


def _decision_receipt(
    common: Mapping[str, Any],
    *,
    decision: str,
    matched_rule_ids: list[str],
    reason_codes: list[str],
    next_transition_selector: str | None,
) -> dict[str, Any]:
    receipt = {
        **dict(common),
        "decision": decision,
        "matched_rule_ids": matched_rule_ids,
        "reason_codes": reason_codes,
        "next_transition_selector": next_transition_selector,
    }
    receipt["receipt_sha256"] = content_sha256(receipt)
    return receipt


def _matches_json_type(value: Any, expected: Any) -> bool:
    types = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "object": Mapping,
        "array": list,
        "null": type(None),
    }
    expected_type = types.get(str(expected))
    if expected_type is None or not isinstance(value, expected_type):
        return False
    return not (expected in {"integer", "number"} and isinstance(value, bool))


def _parse_time(value: Any, code: str) -> datetime:
    if not isinstance(value, str):
        raise ControlKernelError(code, "timestamp is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ControlKernelError(code, "timestamp is invalid") from None
    if parsed.tzinfo is None:
        raise ControlKernelError(code, "timestamp must contain a timezone")
    return parsed.astimezone(timezone.utc)


def _transition_scope(transition: Mapping[str, Any]) -> dict[str, Any]:
    risk = transition.get("risk")
    command = transition.get("command_contract")
    if not isinstance(risk, Mapping) or not isinstance(command, Mapping):
        raise ControlKernelError("TRANSITION_CONTRACT_INVALID", "risk or command")
    scope = {
        "allowed_write_roots": list(transition.get("allowed_write_roots", [])),
        "command_classes": [command.get("command_class")],
        "permissions": list(risk.get("permissions", [])),
        "network_mode": risk.get("network_mode"),
        "secret_access": risk.get("secret_access"),
        "external_effect_class": risk.get("external_effect_class"),
        "stop_gates": [transition.get("stop_gate")]
        if transition.get("stop_gate")
        else [],
    }
    # Legacy fixture grants retain their wire shape. Real local dispatch also
    # carries its narrowed read lease through the existing authoritative Grant.
    if command.get("command_class") == "LOCAL_OFFLINE_PROCESS":
        scope["allowed_read_roots"] = list(transition.get("allowed_read_roots", []))
    return scope


def _require_scope_subset(
    parent: Mapping[str, Any], child: Mapping[str, Any]
) -> None:
    if "allowed_read_roots" in child and not all(
        any(_resource_within(root, parent_root) for parent_root in parent.get("allowed_read_roots", []))
        for root in child["allowed_read_roots"]
    ):
        raise ControlKernelError("DERIVED_GRANT_SCOPE_EXPANSION", "read root exceeds Parent scope")
    if not all(
        any(_resource_within(root, parent_root) for parent_root in parent["allowed_write_roots"])
        for root in child["allowed_write_roots"]
    ):
        raise ControlKernelError(
            "DERIVED_GRANT_SCOPE_EXPANSION", "write root exceeds Parent scope"
        )
    for field in ("command_classes", "permissions", "stop_gates"):
        if not set(child[field]).issubset(set(parent[field])):
            raise ControlKernelError(
                "DERIVED_GRANT_SCOPE_EXPANSION", f"{field} exceeds Parent scope"
            )
    if NETWORK_RANK.get(str(child["network_mode"]), 99) > NETWORK_RANK[
        str(parent["network_mode"])
    ]:
        raise ControlKernelError(
            "DERIVED_GRANT_SCOPE_EXPANSION", "network mode exceeds Parent scope"
        )
    if bool(child["secret_access"]) and not bool(parent["secret_access"]):
        raise ControlKernelError(
            "DERIVED_GRANT_SCOPE_EXPANSION", "Secret access exceeds Parent scope"
        )
    if EFFECT_RANK.get(str(child["external_effect_class"]), 99) > EFFECT_RANK[
        str(parent["external_effect_class"])
    ]:
        raise ControlKernelError(
            "DERIVED_GRANT_SCOPE_EXPANSION", "external effect exceeds Parent scope"
        )


def _resource_within(child: Any, parent: Any) -> bool:
    if not isinstance(child, str) or not isinstance(parent, str):
        return False
    child_uri = urlsplit(child)
    parent_uri = urlsplit(parent)
    if (
        child_uri.scheme != "harness-resource"
        or child_uri.scheme != parent_uri.scheme
        or child_uri.netloc != parent_uri.netloc
        or child_uri.query
        or child_uri.fragment
        or parent_uri.query
        or parent_uri.fragment
    ):
        return False
    child_parts = PurePosixPath(child_uri.path).parts
    parent_parts = PurePosixPath(parent_uri.path).parts
    return child_parts[: len(parent_parts)] == parent_parts


def _validate_transition_contract(transition: Mapping[str, Any]) -> None:
    required = {
        "transition_id",
        "node_kind",
        "allowed_read_roots",
        "allowed_write_roots",
        "required_authorization_class",
        "command_contract",
        "result_schema",
        "evidence_obligations",
        "decision_policy",
        "declared_input_schema",
        "retry_policy",
        "checkpoint_policy",
        "risk",
    }
    if required.difference(transition):
        raise ControlKernelError(
            "TRANSITION_CONTRACT_INVALID", "transition contract is incomplete"
        )
    if transition.get("required_authorization_class") != "PARENT_RISK_ENVELOPE":
        raise ControlKernelError(
            "TRANSITION_CONTRACT_INVALID", "authorization class"
        )
    if not isinstance(transition.get("command_contract"), Mapping) or not isinstance(
        transition["command_contract"].get("command_class"), str
    ):
        raise ControlKernelError("TRANSITION_CONTRACT_INVALID", "command class")
    if transition["command_contract"].get("delivery_mode") not in (None, DURABLE_DELIVERY_MODE):
        raise ControlKernelError("TRANSITION_CONTRACT_INVALID", "unsupported command delivery mode")
    if not isinstance(transition.get("retry_policy"), Mapping) or not isinstance(
        transition["retry_policy"].get("max_retries"), int
    ):
        raise ControlKernelError("TRANSITION_CONTRACT_INVALID", "retry policy")


def _validate_result_schema(
    result: Mapping[str, Any], schema: Mapping[str, Any]
) -> None:
    required = schema.get("required")
    properties = schema.get("properties")
    if not isinstance(required, list) or not isinstance(properties, Mapping):
        raise ControlKernelError("RESULT_SCHEMA_INVALID", "schema")
    if any(field not in result for field in required):
        raise ControlKernelError("TRANSITION_RESULT_INVALID", "required field")
    if schema.get("additionalProperties") is False and set(result).difference(
        properties
    ):
        raise ControlKernelError("TRANSITION_RESULT_INVALID", "extra field")
    for field, value in result.items():
        rule = properties.get(field)
        if not isinstance(rule, Mapping) or not _matches_json_type(
            value, rule.get("type")
        ):
            raise ControlKernelError("TRANSITION_RESULT_INVALID", str(field))
        if "enum" in rule and value not in rule["enum"]:
            raise ControlKernelError("TRANSITION_RESULT_INVALID", str(field))
    if result.get("status") == "VALIDATION_FAILED" and not result.get(
        "reason_code"
    ):
        raise ControlKernelError(
            "TRANSITION_RESULT_INVALID",
            "reason_code is required for VALIDATION_FAILED",
        )


def _parent_usage(
    projections: Mapping[str, Any], parent_authorization_id: str
) -> dict[str, int]:
    grants = projections["grant_ledger"]["derived_grants"]
    owned = {
        str(grant_id): grant
        for grant_id, grant in grants.items()
        if grant.get("parent_authorization_id") == parent_authorization_id
    }
    owned_grant_ids = set(owned)
    retries = sum(
        1 for grant in owned.values() if grant.get("outcome") == "TEMPORARY_FAILURE"
    )
    transitions = sum(
        1
        for transition in projections["program_control_state"][
            "completed_transitions"
        ].values()
        if transition.get("grant_id") in owned_grant_ids
    )
    return {"attempts": len(owned), "retries": retries, "transitions": transitions}


def _decision_stop_reason(decision: str) -> str:
    if decision == "HUMAN_AUTHORITY_REQUIRED":
        return "REAL_RISK_DELTA"
    if decision == "HARD_STOP_UNKNOWN_SIDE_EFFECT":
        return "UNKNOWN_SIDE_EFFECT"
    if decision in {"POLICY_CONFLICT", "POLICY_UNKNOWN"}:
        return decision
    return "DECLARED_STOP_GATE"


def _runtime_stop_reason(
    advanced: Mapping[str, Any], last: Mapping[str, Any]
) -> str:
    if last.get("status") == "STOPPED":
        reason = last.get("stop_reason")
        if isinstance(reason, str):
            return reason
    if last.get("stop_gate"):
        return "TRUE_GATE"
    if advanced.get("reason_code") == "ADVANCE_BUDGET_EXHAUSTED":
        return "BUDGET_EXHAUSTION"
    return "TRANSITION_PATH_COMPLETE"


def _runtime_gate_id(
    advanced: Mapping[str, Any],
    last: Mapping[str, Any],
    stop_reason: str,
) -> str:
    if isinstance(last.get("stop_gate"), str):
        return str(last["stop_gate"])
    if isinstance(last.get("transition_id"), str):
        return f"{last['transition_id']}:{stop_reason}"
    return str(advanced.get("reason_code") or stop_reason)


def _active_approved_parent(
    projection: Mapping[str, Any],
    parent_authorization_id: str,
    now: str,
) -> Mapping[str, Any]:
    parent = projection["grant_ledger"]["parents"].get(
        parent_authorization_id
    )
    if not isinstance(parent, Mapping) or parent.get("status") not in {
        "GRANTED",
        "ACTIVE",
    }:
        raise ControlKernelError(
            "PARENT_AUTHORIZATION_NOT_ACTIVE",
            "Checkpoint or Resume has no active Parent Risk Envelope",
        )
    if not isinstance(parent.get("approval_receipt_sha256"), str):
        raise ControlKernelError(
            "PARENT_READABLE_CHALLENGE_NOT_APPROVED",
            "Parent lacks an approved readable risk challenge",
        )
    if _parse_time(
        parent["expires_at"], "PARENT_AUTHORIZATION_INVALID"
    ) <= _parse_time(now, "TRANSITION_TIME_INVALID"):
        raise ControlKernelError(
            "PARENT_AUTHORIZATION_EXPIRED", "Parent Risk Envelope has expired"
        )
    return parent


def _projected_parent_authorization_sha256(parent: Mapping[str, Any]) -> str:
    return content_sha256(
        {
            key: value
            for key, value in parent.items()
            if key
            not in {
                "approved_challenge_sha256",
                "approval_receipt_sha256",
            }
        }
    )


def _completed_artifacts(projection: Mapping[str, Any]) -> list[dict[str, Any]]:
    completed = projection["program_control_state"]["completed_transitions"]
    return [
        {
            "transition_id": transition_id,
            "artifact_id": transition.get("result", {}).get("artifact_id"),
            "result_sha256": transition.get("result_sha256"),
            "grant_id": transition.get("grant_id"),
        }
        for transition_id, transition in sorted(completed.items())
    ]


def _side_effect_inventory(
    events: list[Mapping[str, Any]],
    projection: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grants = projection["grant_ledger"]["derived_grants"]
    completed = projection["program_control_state"]["completed_transitions"]
    inventory: list[dict[str, Any]] = []
    for transition_id, transition in sorted(completed.items()):
        grant = grants.get(transition.get("grant_id"), {})
        scope = grant.get("scope", {}) if isinstance(grant, Mapping) else {}
        inventory.append(
            {
                "transition_id": transition_id,
                "effect_state": "COMMITTED",
                "external_effect_class": scope.get("external_effect_class"),
                "idempotency_key": transition.get("grant_id"),
                "result_sha256": transition.get("result_sha256"),
            }
        )
    unknown: list[dict[str, Any]] = []
    for event in events:
        if event.get("event_type") != "TRANSITION_STOPPED":
            continue
        payload = event.get("payload")
        if isinstance(payload, Mapping) and payload.get("stop_reason") == "UNKNOWN_SIDE_EFFECT":
            finding = {
                "transition_id": payload.get("transition_id"),
                "stop_event_hash": event.get("event_hash"),
                "reason_code": payload.get("reason_code", "UNKNOWN_SIDE_EFFECT"),
            }
            inventory.append({**finding, "effect_state": "UNKNOWN"})
            unknown.append(finding)
    return inventory, unknown


def _stop_explanation(reason: str) -> tuple[str, str, list[str]]:
    explanations = {
        "BUDGET_EXHAUSTION": (
            "AUTHORIZATION_OWNER",
            "The bounded Runtime transition budget is exhausted.",
            ["REVIEW_CHECKPOINT", "ISSUE_NEW_PARENT_AUTHORIZATION", "RESUME"],
        ),
        "RECOVERABLE_INTERRUPTION": (
            "RUNTIME_OPERATOR",
            "A known recoverable interruption produced a durable Resume Capsule.",
            ["REVIEW_CHECKPOINT", "RESUME"],
        ),
        "UNKNOWN_SIDE_EFFECT": (
            "HUMAN_RISK_OWNER",
            "The external side-effect commit state is unknown; automatic retry or resume is prohibited.",
            ["RECONCILE_SIDE_EFFECT", "HUMAN_DECISION"],
        ),
        "AUTHORITY_EXPANSION": (
            "AUTHORIZATION_OWNER",
            "The next transition exceeds the approved Parent scope.",
            ["REVIEW_SCOPE", "ISSUE_NEW_PARENT_AUTHORIZATION"],
        ),
        "IRREVERSIBLE_RISK": (
            "HUMAN_RISK_OWNER",
            "The next transition declares an irreversible effect.",
            ["REVIEW_IRREVERSIBLE_EFFECT", "HUMAN_DECISION"],
        ),
        "POLICY_CONFLICT": (
            "POLICY_OWNER",
            "Current policy rules resolve to conflicting decisions.",
            ["REPAIR_POLICY", "RETRY_ADVANCE"],
        ),
        "POLICY_UNKNOWN": (
            "POLICY_OWNER",
            "Current policy inputs or binding cannot produce a known decision.",
            ["REPAIR_POLICY_INPUT", "RETRY_ADVANCE"],
        ),
    }
    return explanations.get(
        reason,
        (
            "RUNTIME_OPERATOR",
            f"Runtime stopped with typed reason {reason}.",
            ["REVIEW_STOP_EVIDENCE"],
        ),
    )
