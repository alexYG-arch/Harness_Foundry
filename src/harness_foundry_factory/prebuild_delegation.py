"""Opt-in authoring delegation, recorded in the existing Factory event store.

This is not a runtime authorization or a human-token adapter. The local Chat
boundary supplies human decision provenance, as on the existing human route.
No signatures, extra audit database, process execution, or Candidate writes.
"""

from copy import deepcopy
from pathlib import Path
import re

from .models import InvalidTransitionError, RequestValidationError, SAFE_ID_RE, content_sha256


DELEGATE = "CODEX_DELEGATED_AGENT"
HUMAN = "HUMAN_VIA_CODEX_CHAT"
SCOPE = "PREBUILD_AUTHORING_AND_CANDIDATE_DECISION"
APPROVED_STOP = "PREBUILD_APPROVED_EXECUTION_NOT_AUTHORIZED"
DELEGATED_INTENTS = frozenset({
    "REOPEN", "BIND_DELEGATED_OUTPUT", "PREPARE_READBACK", "ADVANCE_AUTHORING_UNTIL_GATE",
    "DELEGATED_FREEZE", "PREPARE_ARCHITECTURE_READBACK", "DELEGATED_ARCHITECTURE_LOCK",
    "GENERATE", "REVIEW_CANDIDATE",
})
DELEGATE_ONLY = {"BIND_DELEGATED_OUTPUT", "DELEGATED_FREEZE", "DELEGATED_ARCHITECTURE_LOCK", "REVIEW_CANDIDATE"}


def scope_basis(requirement_ir):
    """Keep all authored semantics; omit only Factory-derived views/decisions.

    Delegates cannot call ANSWER/UPDATE_REQUIREMENTS/ADD_SOURCES. Production
    contracts remain deterministically derived and independently validated.
    """
    basis = deepcopy(requirement_ir)
    for field in ("sources", "decisions", "coverage_edges", "portable_projection", "production_contract_compilation"):
        basis.pop(field, None)
    basis["open_questions"] = [q for q in basis.get("open_questions", []) if q.get("origin") != "FACTORY_GAP"]
    for field in ("output_root", "previous_output_root"):
        basis.get("target", {}).pop(field, None)
    for atom in basis.get("atoms", []):
        atom.pop("production_contract", None)
    return basis


def require_payload(payload, fields):
    if set(payload) != set(fields):
        raise RequestValidationError("prebuild payload fields do not match declared contract",
                                     details={"required": sorted(fields), "actual": sorted(payload)})


def make_grant(snapshot, request, now):
    require_payload(request.payload, {"delegation_id", "decision", "scope", "requirement_ir_sha256", "approval_text"})
    data = request.payload
    if request.actor.type != HUMAN or data["decision"] != "APPROVE" or data["scope"] != SCOPE:
        raise InvalidTransitionError("prebuild grant requires explicit human approval of the exact scope")
    if not isinstance(data["approval_text"], str) or not data["approval_text"].strip():
        raise RequestValidationError("prebuild grant requires the actual human approval text")
    grant_id = data["delegation_id"]
    if not isinstance(grant_id, str) or not SAFE_ID_RE.fullmatch(grant_id):
        raise RequestValidationError("delegation_id must be path-safe")
    if grant_id in snapshot.get("prebuild_delegations", {}):
        raise InvalidTransitionError("delegation ID cannot be reused")
    if any(g.get("status") == "ACTIVE" for g in snapshot.get("prebuild_delegations", {}).values()):
        raise InvalidTransitionError("revoke the existing active delegation before replacing it")
    ir = snapshot["requirement_ir"]
    if data["requirement_ir_sha256"] != content_sha256(ir):
        raise InvalidTransitionError("delegation approval must bind the current Requirement IR")
    root = ir.get("target", {}).get("output_root")
    if not isinstance(root, str) or not Path(root).is_absolute():
        raise InvalidTransitionError("delegation requires an existing absolute output binding")
    output = Path(root).resolve()
    return {
        "protocol": "PREBUILD_DELEGATION_V1", "delegation_id": grant_id,
        "status": "ACTIVE", "scope": SCOPE, "program_id": snapshot["program_id"],
        "issued_at": now, "issued_by": request.actor.as_dict(), "approval_text": data["approval_text"],
        "approval_event_ref": f"factory-event://{snapshot['program_id']}/{request.request_id}",
        "requirement_ir_sha256_at_grant": data["requirement_ir_sha256"],
        "scope_sha256": content_sha256(scope_basis(ir)),
        "source_registry_sha256": content_sha256(snapshot.get("source_registry", [])),
        "spec_content_sha256": snapshot["spec_lock"]["content_sha256"],
        "first_requirement_epoch": snapshot["requirement_epoch"],
        "allowed_intents": sorted(DELEGATED_INTENTS),
        "initial_output_root": str(output),
        "output_parent": str(output.parent), "output_stem": re.sub(r"-epoch\d+$", "", output.name),
        "lifetime": "UNTIL_CANDIDATE_APPROVAL_OR_HUMAN_REVOCATION",
        "execution_authorized": False,
    }


def authorize(snapshot, request):
    if request.actor.type == HUMAN:
        if request.intent in DELEGATE_ONLY:
            raise InvalidTransitionError("delegated decision requires a delegated actor, not a relabeled human")
        return None
    if request.actor.type != DELEGATE or snapshot is None or request.intent not in DELEGATED_INTENTS:
        raise InvalidTransitionError("intent is outside prebuild delegation")
    grant = snapshot.get("prebuild_delegations", {}).get(request.actor.delegation_id)
    if (not isinstance(grant, dict) or grant.get("status") != "ACTIVE"
            or grant.get("program_id") != snapshot["program_id"]
            or grant.get("issued_by", {}).get("chat_thread_id") != request.actor.chat_thread_id
            or request.intent not in grant.get("allowed_intents", [])
            or grant.get("execution_authorized") is not False
            or snapshot["requirement_epoch"] < grant["first_requirement_epoch"]):
        raise InvalidTransitionError("prebuild delegation is absent, inactive, or out of scope")
    if (grant["scope_sha256"] != content_sha256(scope_basis(snapshot["requirement_ir"]))
            or grant["source_registry_sha256"] != content_sha256(snapshot.get("source_registry", []))
            or grant["spec_content_sha256"] != snapshot["spec_lock"]["content_sha256"]):
        raise InvalidTransitionError("prebuild delegation scope changed; new human decision required")
    if request.intent in {"GENERATE", "BIND_DELEGATED_OUTPUT", "PREPARE_READBACK", "PREPARE_ARCHITECTURE_READBACK", "ADVANCE_AUTHORING_UNTIL_GATE"}:
        require_payload(request.payload, set())
    if request.intent == "REOPEN":
        require_payload(request.payload, {"reason"})
    if request.intent == "GENERATE":
        expected = (Path(grant["initial_output_root"]) if snapshot["requirement_epoch"] == grant["first_requirement_epoch"]
                    else delegated_output_root(grant, snapshot["requirement_epoch"]))
        actual = snapshot["requirement_ir"].get("target", {}).get("output_root")
        if actual != str(expected) or Path(actual).resolve() != expected:
            raise InvalidTransitionError("generation output no longer matches the delegated root binding")
    return grant


def delegated_output_root(grant, epoch):
    return Path(grant["output_parent"]) / f"{grant['output_stem']}-epoch{epoch}"


def next_delegated_intents(snapshot):
    if not any(g.get("status") == "ACTIVE" for g in snapshot.get("prebuild_delegations", {}).values()):
        return []
    return {
        "INTAKE_OPEN": ["BIND_DELEGATED_OUTPUT", "ADVANCE_AUTHORING_UNTIL_GATE"],
        "CLARIFYING": ["BIND_DELEGATED_OUTPUT", "ADVANCE_AUTHORING_UNTIL_GATE"],
        "REQUIREMENTS_READBACK_READY": ["DELEGATED_FREEZE"],
        "WAITING_REQUIREMENTS_FREEZE": ["REOPEN"],
        "REQUIREMENTS_FROZEN": ["PREPARE_ARCHITECTURE_READBACK", "DELEGATED_ARCHITECTURE_LOCK", "GENERATE", "REOPEN"],
        "CANDIDATE_READY_FOR_HUMAN_REVIEW": ["REVIEW_CANDIDATE", "REOPEN"],
        "OUTPUT_COLLISION": ["REOPEN"], "REOPEN_REQUIRED": ["REOPEN"],
    }.get(snapshot["factory_state"], [])


def audit_events(events):
    """Check authority relationships in an already hash-verified event history.

    Independent of grant creation and request authorization. Old human-only
    histories remain valid; a delegated actor must have a prior human grant.
    """
    findings, previous, checked = [], {}, 0
    for event in events:
        current = event["resulting_snapshot"]
        actor = event["actor"]
        kind = event["event_type"]
        if kind == "PREBUILD_DELEGATION_GRANTED_BY_HUMAN":
            data = event["payload"]
            grant = current.get("prebuild_delegations", {}).get(data.get("delegation_id"), {})
            if (actor.get("type") != HUMAN or data.get("decision") != "APPROVE"
                    or grant.get("issued_by") != actor or grant.get("scope") != SCOPE
                    or grant.get("execution_authorized") is not False
                    or grant.get("status") != "ACTIVE"
                    or grant.get("program_id") != event["program_id"]
                    or grant.get("allowed_intents") != sorted(DELEGATED_INTENTS)
                    or grant.get("approval_text") != data.get("approval_text")
                    or grant.get("approval_event_ref") != f"factory-event://{event['program_id']}/{event['request_id']}"):
                findings.append({"code": "PREBUILD_GRANT_AUDIT_INVALID", "revision": event["revision"]})
        if actor.get("type") == DELEGATE:
            checked += 1
            grant = previous.get("prebuild_delegations", {}).get(actor.get("delegation_id"), {})
            if (grant.get("status") != "ACTIVE" or grant.get("program_id") != event["program_id"]
                    or grant.get("issued_by", {}).get("chat_thread_id") != actor.get("chat_thread_id")
                    or grant.get("scope_sha256") != content_sha256(scope_basis(current["requirement_ir"]))
                    or grant.get("execution_authorized") is not False or "BY_HUMAN" in kind):
                findings.append({"code": "PREBUILD_DELEGATE_AUTHORITY_AUDIT_INVALID", "revision": event["revision"]})
            boundary = current.get("authoring_boundary", {})
            if boundary.get("execution_mode") != "AUTHORING_ONLY" or any(
                boundary.get(field) is not False for field in ("execution_started", "install_started", "certification_started", "auto_start_generated_workpacks")
            ):
                findings.append({"code": "PREBUILD_EXECUTION_BOUNDARY_AUDIT_INVALID", "revision": event["revision"]})
            if kind == "REQUIREMENTS_FROZEN_BY_DELEGATE":
                freeze = current.get("freeze", {})
                if (freeze.get("approved_by") != actor or "confirmation_token" in freeze
                        or freeze.get("decision_evidence", {}).get("delegation_id") != actor.get("delegation_id")):
                    findings.append({"code": "PREBUILD_FREEZE_PROVENANCE_AUDIT_INVALID", "revision": event["revision"]})
            if kind == "CANDIDATE_DECIDED_BY_DELEGATE":
                decision = current.get("candidate_decision", {})
                if (decision.get("actor") != actor or decision.get("approval_mode") != "DELEGATED"
                        or decision.get("execution_authorized") is not False):
                    findings.append({"code": "PREBUILD_CANDIDATE_DECISION_AUDIT_INVALID", "revision": event["revision"]})
        previous = current
    return {"status": "FAIL" if findings else "PASS", "findings": findings, "delegated_events_checked": checked}
