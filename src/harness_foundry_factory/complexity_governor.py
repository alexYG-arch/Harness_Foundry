"""Executable v2.9 complexity budget with one exact aggregate output."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


class ComplexityGovernorError(ValueError):
    pass


def _hash(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ComplexityGovernorError("complexity input is not canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def evaluate_complexity(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate all five declared outputs without granting execution authority."""

    required = {
        "active_bespoke_paths_before",
        "active_bespoke_paths_after",
        "new_node_specific_authorized_paths",
        "new_fixed_attempt_or_receipt_ids_in_core",
        "generic_path_added",
        "retired_authoritative_paths",
        "human_gate_added",
        "human_gate_has_risk_delta_or_external_boundary",
        "control_fault_fingerprint_occurrences",
    }
    if not isinstance(inputs, Mapping) or set(inputs) != required:
        missing = sorted(required - set(inputs)) if isinstance(inputs, Mapping) else sorted(required)
        extra = sorted(set(inputs) - required) if isinstance(inputs, Mapping) else []
        raise ComplexityGovernorError(
            f"complexity input fields are not exact; missing={missing}, extra={extra}"
        )
    integer_fields = required - {
        "generic_path_added",
        "human_gate_added",
        "human_gate_has_risk_delta_or_external_boundary",
    }
    for field in integer_fields:
        value = inputs[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ComplexityGovernorError(f"{field} must be a non-negative integer")
    for field in required - integer_fields:
        if not isinstance(inputs[field], bool):
            raise ComplexityGovernorError(f"{field} must be boolean")

    violations: list[str] = []
    if inputs["new_node_specific_authorized_paths"] > 0:
        violations.append("NEW_NODE_SPECIFIC_AUTHORIZED_PATH")
    if inputs["new_fixed_attempt_or_receipt_ids_in_core"] > 0:
        violations.append("NEW_FIXED_ATTEMPT_OR_RECEIPT_ID_IN_CORE")
    retirement_required = bool(inputs["generic_path_added"])
    retirement_satisfied = (
        not retirement_required or inputs["retired_authoritative_paths"] >= 1
    )
    if not retirement_satisfied:
        violations.append("GENERIC_PATH_WITHOUT_AUTHORITATIVE_RETIREMENT")
    path_delta = (
        inputs["active_bespoke_paths_after"]
        - inputs["active_bespoke_paths_before"]
    )
    if path_delta >= 0:
        violations.append("ACTIVE_BESPOKE_PATH_DELTA_NOT_NEGATIVE")
    human_gate_justified = (
        not inputs["human_gate_added"]
        or inputs["human_gate_has_risk_delta_or_external_boundary"]
    )
    if not human_gate_justified:
        violations.append("HUMAN_GATE_WITHOUT_REAL_RISK_OR_EXTERNAL_BOUNDARY")

    repeated_fault = inputs["control_fault_fingerprint_occurrences"] >= 2
    if repeated_fault:
        decision = "ARCHITECTURE_REVIEW_REQUIRED"
        reason = "REPEATED_CONTROL_FAULT_CIRCUIT_BREAKER"
    elif violations:
        decision = "FAIL"
        reason = "COMPLEXITY_BUDGET_VIOLATION"
    else:
        decision = "PASS"
        reason = "COMPLEXITY_BUDGET_SATISFIED"

    body = {
        "schema_version": "2.9",
        "governor_id": "V29_EXECUTABLE_COMPLEXITY_GOVERNOR_V2",
        "input_sha256": _hash(dict(inputs)),
        "decision": decision,
        "reason_code": reason,
        "violations": violations,
        "outputs": {
            "complexity_baseline": {
                "active_bespoke_paths_before": inputs["active_bespoke_paths_before"],
                "new_node_specific_authorized_paths": inputs[
                    "new_node_specific_authorized_paths"
                ],
                "new_fixed_attempt_or_receipt_ids_in_core": inputs[
                    "new_fixed_attempt_or_receipt_ids_in_core"
                ],
            },
            "complexity_delta": {
                "active_bespoke_paths_after": inputs["active_bespoke_paths_after"],
                "active_bespoke_path_delta": path_delta,
                "delta_is_negative": path_delta < 0,
            },
            "retirement_manifest": {
                "generic_path_added": inputs["generic_path_added"],
                "retired_authoritative_paths": inputs[
                    "retired_authoritative_paths"
                ],
                "retirement_required": retirement_required,
                "retirement_satisfied": retirement_satisfied,
            },
            "human_cost_result": {
                "human_gate_added": inputs["human_gate_added"],
                "risk_delta_or_external_boundary": inputs[
                    "human_gate_has_risk_delta_or_external_boundary"
                ],
                "human_gate_justified": human_gate_justified,
            },
            "circuit_breaker_decision_receipt": {
                "control_fault_fingerprint_occurrences": inputs[
                    "control_fault_fingerprint_occurrences"
                ],
                "threshold": 2,
                "circuit_breaker_open": repeated_fault,
                "decision": (
                    "ARCHITECTURE_REVIEW_REQUIRED" if repeated_fault else "CONTINUE"
                ),
                "reason_code": (
                    "REPEATED_CONTROL_FAULT_CIRCUIT_BREAKER"
                    if repeated_fault
                    else "FAULT_THRESHOLD_NOT_REACHED"
                ),
            },
        },
        "creates_authority": False,
    }
    return {**body, "assessment_sha256": _hash(body)}


__all__ = ["ComplexityGovernorError", "evaluate_complexity"]
