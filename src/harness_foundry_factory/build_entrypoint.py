"""Public generic Build host boundary; one controller, no legacy Candidate route.

The cooperating local chat host authenticates the real human decision. JSON
shape validation cannot authenticate a person; model-produced decision objects
are not permission. Target workers cannot write the host's controller database.
"""

from datetime import datetime, timezone
from pathlib import Path

from .build_authoring import read_build_plan_proposal, record_build_plan_proposal
from .build_plan import compile_build_plan, validate_compiled_build_plan
from .build_review import validate_build_review, validate_review_sources, review_summary
from .build_runtime import (
    BuildController, _utc, approve_build_authorization, prepare_build_authorization,
    record_source_snapshot, revoke_build_authorization,
    resolve_build_attempt,
)
from .models import RequestValidationError, RevisionConflictError, SAFE_ID_RE, canonical_json
from .store import ControlEventStore
from .process_observation import CommandObservation


MUTATIONS = {
    "record-build-plan": {"requirement_ir", "plan", "document_review"},
    "capture-build-sources": {"program_id", "proposal_event_id", "source_root", "manifest"},
    "prepare-build-authorization": {"program_id", "proposal_event_id", "source_event_id", "scope"},
    "approve-build-authorization": {"program_id", "prepared_event_id", "decision"},
    "revoke-build-authorization": {"program_id", "prepared_event_id", "decision", "reason"},
    "resolve-build-attempt": {"program_id", "prepared_event_id", "attempt_id", "decision", "reason"},
}


def _require(condition, message):
    if not condition:
        raise RequestValidationError(message)


def _database(value):
    path = Path(value)
    _require(path.is_absolute() and ".." not in path.parts, "control-db must be an explicit absolute path")
    _require(not path.exists() or path.is_file(), "control-db must be a file")
    return path.resolve()


def _program(value):
    _require(isinstance(value, str) and SAFE_ID_RE.fullmatch(value), "invalid Program ID")
    return value


def _human_ref(decision, action):
    _require(isinstance(decision, dict) and set(decision) == {"action", "actor", "user_message"},
             "decision requires action, actor and original user_message")
    actor = decision["actor"]
    _require(decision["action"] == action and isinstance(actor, dict)
             and set(actor) == {"type", "chat_thread_id", "turn_id"}
             and actor["type"] == "HUMAN_VIA_CODEX_CHAT"
             and all(isinstance(actor[key], str) and actor[key].strip() for key in ("chat_thread_id", "turn_id"))
             and isinstance(decision["user_message"], str) and decision["user_message"].strip(),
             "trusted host must bind an actual human decision; agent self-approval is not accepted")
    return canonical_json(decision)


def _source_summary(event):
    payload = event["payload"]
    return {"source_event_id": event["event_id"], "proposal_event_id": payload["proposal_event_id"],
            "source_root": payload["source_root"], "manifest": payload["manifest"],
            "sources": [{key: value for key, value in source.items() if key != "text"}
                        for source in payload["snapshot"]["sources"]],
            "semantic_completeness_verified": False}


def _scope_readback(event, events):
    payload = event["payload"]
    prepared_id = event["event_id"]
    approved = any(row["event_type"] == "BUILD_AUTHORIZATION_APPROVED"
                   and row["payload"]["prepared_event_id"] == prepared_id for row in events)
    revoked = any(row["event_type"] == "BUILD_AUTHORIZATION_REVOKED"
                  and row["payload"]["prepared_event_id"] == prepared_id for row in events)
    state = ("REVOKED" if revoked else "EXPIRED" if _utc(payload["scope"]["expires_at"]) <= datetime.now(timezone.utc)
             else "APPROVED" if approved else "APPROVAL_REQUIRED")
    source = next(row for row in events if row["event_id"] == payload["source_event_id"])
    proposal = next(row for row in events if row["event_id"] == payload["proposal_event_id"])
    return {"prepared_event_id": prepared_id, "proposal_event_id": payload["proposal_event_id"],
            "requirement_ir": proposal["payload"]["requirement_ir"], "plan": proposal["payload"]["plan"],
            "scope": payload["scope"], "source_binding": _source_summary(source),
            "verification_files": sorted(payload["verifier_files"]), "state": state,
            "coding_instruction_preflight": payload.get("coding_instruction_preflight"),
            "directory_creation": "ONLY_DURING_APPROVED_ADVANCE",
            "freshness_rechecked_at_dispatch": True, "execution_started_by_readback": False}


def read_build(control_db, program_id):
    """Read persisted declarations and progress without creating a database."""
    program_id = _program(program_id)
    store = ControlEventStore(_database(control_db), read_only=True, storage_format="REVISION_V1")
    proposal = read_build_plan_proposal(store, program_id)
    events = store.list_events(program_id)
    latest_proposal = next(row for row in events if row["event_id"] == proposal["proposal_binding"]["proposal_event_id"])
    attempts = {}
    for event in events:
        payload = event["payload"]
        if event["event_type"] == "BUILD_ATTEMPT_STARTED":
            attempts[payload["attempt_id"]] = {**payload, "status": "IN_FLIGHT"}
        elif event["event_type"] in {"BUILD_ATTEMPT_FINISHED", "BUILD_ATTEMPT_RECOVERED", "BUILD_ATTEMPT_RESOLVED"}:
            attempts[payload["attempt_id"]].update(payload)
        elif event["event_type"] in {"BUILD_COMMAND_PLANNED", "BUILD_COMMAND_STARTED", "BUILD_COMMAND_OBSERVED"}:
            attempts[payload["attempt_id"]]["last_command"] = {
                "event_id": event["event_id"], "event_type": event["event_type"], **payload}
        elif event["event_type"] == "BUILD_ACCEPTANCE_INVALIDATED":
            for attempt in attempts.values():
                if (attempt["prepared_event_id"] == payload["prepared_event_id"]
                        and attempt["workpack_id"] in payload["workpack_ids"] and attempt["status"] == "ACCEPTED"):
                    attempt.update(status="INVALIDATED", invalidation=payload)
    for row in attempts.values():
        action = {"UNKNOWN_SIDE_EFFECT": "RECONCILE_EFFECTS", "IN_FLIGHT": "RECONCILE_COMMAND_OBSERVATIONS",
                  "BLOCKED": "REPAIR_RUNTIME_ENVIRONMENT", "REJECTED": "REPAIR_WITHIN_BUDGET",
                  "ACCEPTED": "NO_REPLAY", "RETRY_ALLOWED": "ADVANCE_WITH_CURRENT_SCOPE_AND_BUDGET",
                  "INVALIDATED": "REBUILD_AFFECTED_BRANCH_WITHIN_BUDGET"}.get(row["status"], "INSPECT")
        row["recovery"] = {"next_action": action, "automatic_acceptance": False}
        command = row.get("last_command", {})
        if row["status"] == "REJECTED" and BuildController._failure_status(command.get("result", {})) == "BLOCKED":
            row["recovery"].update(next_action="REPAIR_RUNTIME_ENVIRONMENT", historical_classification="REJECTED")
        if row["status"] in {"UNKNOWN_SIDE_EFFECT", "IN_FLIGHT"} and command.get("observation_root"):
            row["recovery"]["host_observation"] = CommandObservation.inspect(command["observation_root"])
    return {"status": "BUILD_READBACK", "program_id": program_id, "stream_revision": len(events),
            "proposal": proposal, "requirement_ir": latest_proposal["payload"]["requirement_ir"],
            "document_review": review_summary(latest_proposal["payload"].get("document_review")),
            "sources": [_source_summary(row) for row in events if row["event_type"] == "BUILD_SOURCES_CAPTURED"],
            "authorizations": [_scope_readback(row, events) for row in events if row["event_type"] == "BUILD_AUTHORIZATION_PREPARED"],
            "attempts": list(attempts.values()), "writes_performed": False,
            "harness_e2e_verified": False}


def apply_build_request(command, request, control_db):
    """Mutate the explicit generic controller or advance its approved workload.

    No caller-selectable test receiver, shell, model fallback or legacy route.
    An invalid initial proposal is rejected before mkdir/DDL. The same stream
    provides transaction/CAS and exact idempotency for all subsequent mutations.
    """
    _require(isinstance(request, dict), "build request must be an object")
    if command == "advance-build":
        _require(set(request) == {"program_id", "prepared_event_id", "expected_revision"}, "invalid advance-build fields")
    else:
        _require(command in MUTATIONS and set(request) == MUTATIONS[command] | {"expected_revision", "idempotency_key"},
                 "build request has missing or unsupported fields")
        _require(isinstance(request["idempotency_key"], str) and request["idempotency_key"].strip(), "idempotency_key is required")
    _require(type(request["expected_revision"]) is int and request["expected_revision"] >= 0,
             "expected_revision must be a nonnegative integer")
    database = _database(control_db)
    if command == "record-build-plan":
        validate_build_review(request["document_review"])
        compiled = compile_build_plan(request["requirement_ir"], request["plan"])
        validate_compiled_build_plan(request["requirement_ir"], request["plan"], compiled)
        validate_review_sources(request["document_review"], request["requirement_ir"])
        program = _program(request["requirement_ir"]["program_id"])
        _require(database.exists() or request["expected_revision"] == 0, "new controller starts at revision zero")
        _require(database.exists() or request["requirement_ir"]["revision"] == request["plan"]["revision"] == 1,
                 "a new proposal stream starts at requirement and plan revision 1")
    else:
        program = _program(request["program_id"])
        _require(database.is_file(), "generic controller does not exist; record a proposal first")
    human_ref = None
    if command == "resolve-build-attempt":
        human_ref = _human_ref(request["decision"], "RESOLVE_BUILD_ATTEMPT")
    if command in {"approve-build-authorization", "revoke-build-authorization"}:
        human_ref = _human_ref(request["decision"], "APPROVE_BUILD" if command.startswith("approve") else "REVOKE_BUILD")
        if command.startswith("revoke"):
            _require(isinstance(request["reason"], str) and request["reason"].strip(), "revocation reason is required")
    # Existing incompatible/historical stores are inspected read-only first.
    if database.exists():
        existing = ControlEventStore(database, read_only=True, storage_format="REVISION_V1")
        _require(set(existing.list_program_ids()) <= {program}, "controller belongs to another Program")
        if command == "advance-build" and len(existing.list_events(program)) != request["expected_revision"]:
            raise RevisionConflictError("re-read current build progress before dispatch")
    store = ControlEventStore(database, storage_format="REVISION_V1")
    if command == "advance-build":
        return {**BuildController(store, program).advance(request["prepared_event_id"]),
                "program_id": program, "stream_revision": len(store.list_events(program)), "harness_e2e_verified": False}
    kwargs = {"expected_revision": request["expected_revision"], "idempotency_key": request["idempotency_key"],
              "created_at": datetime.now(timezone.utc).isoformat()}
    if command == "record-build-plan":
        event = record_build_plan_proposal(store, request["requirement_ir"], request["plan"],
                                           document_review=request["document_review"], **kwargs)
        status = "BUILD_PLAN_RECORDED_NOT_AUTHORIZED"
    elif command == "capture-build-sources":
        event = record_source_snapshot(store, program, request["proposal_event_id"], request["source_root"], request["manifest"], **kwargs)
        status = "BUILD_SOURCES_CAPTURED_NOT_SEMANTICALLY_ACCEPTED"
    elif command == "prepare-build-authorization":
        event = prepare_build_authorization(store, program, request["proposal_event_id"], request["source_event_id"], request["scope"], **kwargs)
        status = "BUILD_SCOPE_APPROVAL_REQUIRED"
    elif command == "approve-build-authorization":
        event = approve_build_authorization(store, program, request["prepared_event_id"], human_message_ref=human_ref, **kwargs)
        status = "BUILD_APPROVED_EXECUTION_NOT_STARTED"
    elif command == "resolve-build-attempt":
        event = resolve_build_attempt(store, program, request["prepared_event_id"], request["attempt_id"],
                                      reason=request["reason"], human_message_ref=human_ref, **kwargs)
        status = "BUILD_ATTEMPT_RESOLVED_NOT_EXECUTED"
    else:
        event = revoke_build_authorization(store, program, request["prepared_event_id"], human_message_ref=human_ref,
                                           reason=request["reason"], **kwargs)
        status = "BUILD_AUTHORIZATION_REVOKED"
    return {"status": status, "program_id": program, "event_id": event["event_id"], "stream_revision": event["stream_revision"],
            "readback": _scope_readback(event, store.list_events(program)) if command == "prepare-build-authorization" else None,
            "control_state_write": True, "target_write": False, "execution_started": False, "harness_e2e_verified": False}
