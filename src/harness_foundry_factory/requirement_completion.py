"""Minimum v2.9 Requirement completion and honest independence decisions."""

from __future__ import annotations

from typing import Any, Mapping

from .models import content_sha256


REQUIREMENT_STATES = {
    "NOT_APPLICABLE",
    "PLANNED",
    "PARTIAL",
    "SATISFIED",
    "BLOCKED",
    "INVALIDATED",
}
VERIFICATION_LEVELS = ("STATIC", "TEST", "FIXTURE", "LIVE", "INSTALLED")


class RequirementCompletionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def evaluate_requirement_completion(
    contract: Mapping[str, Any], observations: Mapping[str, Any]
) -> dict[str, Any]:
    """Apply the explicit v2.9 ALL_OF rule without semantic inference."""

    required_fields = {
        "requirement_id",
        "instance_id",
        "applicability_decision",
        "mandatory_subrequirements",
        "required_workpacks",
        "required_cases",
        "required_evidence",
        "required_oracles",
        "invalidation_dependencies",
    }
    if required_fields.difference(contract):
        raise RequirementCompletionError(
            "REQUIREMENT_COMPLETION_CONTRACT_INVALID", "contract is incomplete"
        )
    applicability = contract["applicability_decision"]
    if applicability not in {"APPLICABLE", "NOT_APPLICABLE"}:
        raise RequirementCompletionError(
            "APPLICABILITY_DECISION_INVALID", str(applicability)
        )
    if applicability == "NOT_APPLICABLE":
        if not contract.get("applicability_decision_receipt_sha256"):
            raise RequirementCompletionError(
                "APPLICABILITY_DECISION_UNBOUND", "N/A requires a decision receipt"
            )
        return _completion_record(contract, "NOT_APPLICABLE", [], "STATIC")

    blockers: list[dict[str, Any]] = []
    invalidated = set(observations.get("invalidated_dependencies", []))
    declared_dependencies = set(contract["invalidation_dependencies"])
    if invalidated.intersection(declared_dependencies):
        blockers.append(
            {
                "code": "DECLARED_DEPENDENCY_INVALIDATED",
                "ids": sorted(invalidated.intersection(declared_dependencies)),
            }
        )
        return _completion_record(contract, "INVALIDATED", blockers, "STATIC")

    blocking_findings = [
        item
        for item in observations.get("findings", [])
        if isinstance(item, Mapping) and item.get("blocking") is True
    ]
    if blocking_findings:
        blockers.append(
            {
                "code": "BLOCKING_FINDING_OPEN",
                "ids": sorted(str(item.get("finding_id")) for item in blocking_findings),
            }
        )

    checks = (
        (
            "SUBREQUIREMENT_NOT_SATISFIED",
            contract["mandatory_subrequirements"],
            observations.get("subrequirements", {}),
            {"SATISFIED"},
        ),
        (
            "WORKPACK_NOT_VALID",
            contract["required_workpacks"],
            observations.get("workpacks", {}),
            {"PASS_VALID"},
        ),
        (
            "CASE_NOT_PASS",
            contract["required_cases"],
            observations.get("cases", {}),
            {"PASS"},
        ),
        (
            "EVIDENCE_NOT_PASS",
            contract["required_evidence"],
            observations.get("evidence", {}),
            {"PASS"},
        ),
        (
            "ORACLE_NOT_PASS",
            contract["required_oracles"],
            observations.get("oracles", {}),
            {"PASS"},
        ),
    )
    for code, required_ids, actual, passing in checks:
        if not isinstance(required_ids, list) or not isinstance(actual, Mapping):
            raise RequirementCompletionError(
                "REQUIREMENT_COMPLETION_CONTRACT_INVALID", code
            )
        for item_id in required_ids:
            item = actual.get(item_id)
            if not isinstance(item, Mapping) or item.get("status") not in passing:
                blockers.append({"code": code, "ids": [str(item_id)]})
                continue
            if code in {"CASE_NOT_PASS", "EVIDENCE_NOT_PASS", "ORACLE_NOT_PASS"}:
                if (
                    item.get("requirement_id") != contract["requirement_id"]
                    or item.get("instance_id") != contract["instance_id"]
                    or item.get("invalidated") is True
                    or item.get("stale") is True
                ):
                    blockers.append(
                        {"code": "WRONG_OR_STALE_EVIDENCE_INSTANCE", "ids": [str(item_id)]}
                    )

    if blocking_findings:
        state = "BLOCKED"
    elif blockers:
        state = "PARTIAL" if _has_any_progress(observations) else "PLANNED"
    else:
        state = "SATISFIED"
    level = str(observations.get("verification_level", "STATIC"))
    if level not in VERIFICATION_LEVELS:
        raise RequirementCompletionError(
            "VERIFICATION_LEVEL_INVALID", level
        )
    return _completion_record(contract, state, blockers, level)


def dependency_invalidation_events(
    contract: Mapping[str, Any], changed_dependency_ids: list[str]
) -> list[dict[str, Any]]:
    """Create direct invalidation events only for declared dependencies."""

    declared = set(contract.get("invalidation_dependencies", []))
    return [
        {
            "event_type": "DECLARED_DEPENDENCY_INVALIDATED",
            "payload": {
                "requirement_id": contract["requirement_id"],
                "instance_id": contract["instance_id"],
                "dependency_id": dependency_id,
            },
        }
        for dependency_id in changed_dependency_ids
        if dependency_id in declared
    ]


def evaluate_control_domain(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Prove independence from lineage facts or return an honest downgrade."""

    required = {
        "claim_id",
        "assurance_level",
        "producer_domain_id",
        "oracle_domain_id",
        "producer_implementation_sha256",
        "oracle_implementation_sha256",
        "credential_scope_ids",
        "workspace_binding_ids",
        "state_store_ids",
        "parent_task_ids",
        "blind_input_policy",
        "common_mode_failure_classes",
    }
    if required.difference(contract):
        raise RequirementCompletionError(
            "CONTROL_DOMAIN_CONTRACT_INVALID", "contract is incomplete"
        )
    reasons: list[str] = []
    if contract["producer_domain_id"] == contract["oracle_domain_id"]:
        reasons.append("SHARED_CONTROL_DOMAIN")
    if (
        contract["producer_implementation_sha256"]
        == contract["oracle_implementation_sha256"]
    ):
        reasons.append("SHARED_VALIDATOR_IMPLEMENTATION")
    for field, reason in (
        ("credential_scope_ids", "CREDENTIAL_LINEAGE_NOT_SEPARATED"),
        ("workspace_binding_ids", "WORKSPACE_LINEAGE_NOT_SEPARATED"),
        ("state_store_ids", "STATE_STORE_LINEAGE_NOT_SEPARATED"),
        ("parent_task_ids", "PARENT_TASK_LINEAGE_NOT_SEPARATED"),
    ):
        values = contract[field]
        if not isinstance(values, list) or len(set(values)) < 2:
            reasons.append(reason)
    reasons.extend(str(value) for value in contract["common_mode_failure_classes"])
    if contract["assurance_level"] == "INDEPENDENT_INTERNAL_CERTIFICATION":
        if "SHARED_VALIDATOR_IMPLEMENTATION" in reasons:
            decision = "FAIL_CLOSED"
        elif reasons:
            decision = "DOWNGRADE_TO_COORDINATED"
        else:
            decision = "PASS"
    elif contract["assurance_level"] == "COORDINATED_SEPARATION":
        decision = "PASS" if "SHARED_VALIDATOR_IMPLEMENTATION" not in reasons else "FAIL_CLOSED"
    else:
        raise RequirementCompletionError(
            "CONTROL_DOMAIN_CONTRACT_INVALID", "assurance_level"
        )
    receipt = {
        "schema_version": "2.9",
        "claim_id": contract["claim_id"],
        "requested_assurance_level": contract["assurance_level"],
        "independence_decision": decision,
        "decision_reason_codes": sorted(set(reasons)),
        "contract_sha256": content_sha256(contract),
    }
    receipt["receipt_sha256"] = content_sha256(receipt)
    return receipt


def evaluate_human_cost_acceptance(
    result: Mapping[str, Any], thresholds: Mapping[str, Any]
) -> dict[str, Any]:
    """Machine-count the fixed v2.9 attention budget."""

    failures: list[str] = []
    exact = {
        "architecture_freeze_count": thresholds.get("architecture_freeze_count", 1),
        "parent_risk_authorization_count": thresholds.get(
            "parent_risk_authorization_count", 1
        ),
        "manual_hash_input_count": thresholds.get("manual_hash_input_count", 0),
        "human_decision_count": thresholds.get("human_decision_count", 2),
    }
    for field, expected in exact.items():
        if result.get(field) != expected:
            failures.append(field)
    minimums = {
        "distinct_node_kind_count": thresholds.get(
            "minimum_distinct_node_kinds_auto_advanced", 3
        ),
        "derived_grant_count": thresholds.get("minimum_derived_grant_count", 3),
    }
    for field, minimum in minimums.items():
        if int(result.get(field, 0)) < int(minimum):
            failures.append(field)
    if int(result.get("bounded_retry_count", 0)) + int(
        result.get("resume_count", 0)
    ) < int(thresholds.get("minimum_safe_retry_or_resume_count", 1)):
        failures.append("safe_retry_or_resume_count")
    receipt = {
        "schema_version": "2.9",
        "status": "PASS" if not failures else "FAIL",
        "failed_metrics": sorted(failures),
        "result_sha256": content_sha256(result),
        "thresholds_sha256": content_sha256(thresholds),
    }
    receipt["receipt_sha256"] = content_sha256(receipt)
    return receipt


def _completion_record(
    contract: Mapping[str, Any],
    state: str,
    blockers: list[dict[str, Any]],
    verification_level: str,
) -> dict[str, Any]:
    if state not in REQUIREMENT_STATES:
        raise RequirementCompletionError("REQUIREMENT_STATE_INVALID", state)
    record = {
        "schema_version": "2.9",
        "requirement_id": contract["requirement_id"],
        "instance_id": contract["instance_id"],
        "state": state,
        "verification_level": verification_level,
        "completion_rule": "EXPLICIT_ALL_OF_AND_NO_BLOCKING_FINDING",
        "blockers": blockers,
        "contract_sha256": content_sha256(contract),
    }
    record["record_sha256"] = content_sha256(record)
    return record


def _has_any_progress(observations: Mapping[str, Any]) -> bool:
    for field in ("subrequirements", "workpacks", "cases", "evidence", "oracles"):
        values = observations.get(field)
        if isinstance(values, Mapping) and values:
            return True
    return False
