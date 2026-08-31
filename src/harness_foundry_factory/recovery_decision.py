"""Generic, authority-neutral recovery decision protocol for v2.9."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


DECISION_MODES = (
    "RESULT_VALIDATION_ONLY",
    "FINALIZATION_ONLY",
    "RETRY_EXECUTOR",
    "HUMAN_RISK_REVIEW",
)


class RecoveryDecisionError(ValueError):
    pass


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def decide_recovery(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Select one deterministic recovery mode without creating authority."""

    required = {
        "command_receipt_status",
        "effect_certainty",
        "result_receipt_status",
        "event_commit_state",
        "grant_state",
        "checkpoint_status",
        "retry_budget_remaining",
    }
    missing = sorted(required - set(inputs))
    if missing:
        raise RecoveryDecisionError(f"missing recovery inputs: {missing}")
    retry_budget = inputs["retry_budget_remaining"]
    if isinstance(retry_budget, bool) or not isinstance(retry_budget, int) or retry_budget < 0:
        raise RecoveryDecisionError("retry_budget_remaining must be a non-negative integer")

    effect = inputs["effect_certainty"]
    event = inputs["event_commit_state"]
    result = inputs["result_receipt_status"]
    grant = inputs["grant_state"]
    checkpoint = inputs["checkpoint_status"]
    command = inputs["command_receipt_status"]

    if effect == "UNKNOWN" or event == "UNKNOWN":
        decision = "HUMAN_RISK_REVIEW"
        reason = "UNKNOWN_SIDE_EFFECT_OR_COMMIT_STATE"
    elif result == "VALID" and event == "COMMITTED":
        decision = "RESULT_VALIDATION_ONLY"
        reason = "RESULT_AND_EVENT_ALREADY_COMMITTED"
    elif effect == "COMMITTED" and event == "NOT_COMMITTED" and result in {
        "VALID",
        "PRESENT_UNVALIDATED",
    }:
        decision = "FINALIZATION_ONLY"
        reason = "EFFECT_COMMITTED_EVENT_FINALIZATION_REQUIRED"
    elif (
        effect == "NO_EFFECT"
        and event == "NOT_COMMITTED"
        and result in {"MISSING", "INVALID"}
        and grant == "ACTIVE"
        and checkpoint == "VALID"
        and command == "VALID"
        and retry_budget > 0
    ):
        decision = "RETRY_EXECUTOR"
        reason = "KNOWN_NO_EFFECT_AND_RETRY_BUDGET_AVAILABLE"
    else:
        decision = "HUMAN_RISK_REVIEW"
        reason = "NO_SAFE_MACHINE_RECOVERY_RULE"

    body = {
        "schema_version": "2.9",
        "protocol_id": "V29_GENERIC_RECOVERY_DECISION_PROTOCOL_V1",
        "input_sha256": _hash(dict(inputs)),
        "decision": decision,
        "reason_code": reason,
        "creates_authority": False,
        "executor_invoked": False,
        "allowed_decision_modes": list(DECISION_MODES),
    }
    return {**body, "decision_sha256": _hash(body)}


__all__ = ["DECISION_MODES", "RecoveryDecisionError", "decide_recovery"]

