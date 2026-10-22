"""Public generic Build host boundary; one controller, no legacy Candidate route.

The cooperating local chat host authenticates the real human decision. JSON
shape validation cannot authenticate a person; model-produced decision objects
are not permission. Target workers cannot write the host's controller database.
"""

from datetime import datetime, timezone
from pathlib import Path

from .build_authoring import read_build_plan_proposal, record_build_plan_proposal
from .build_plan import compile_build_plan, validate_compiled_build_plan
from .build_repair import request_build_repair
from .build_state import attempt_budget, project_readback_attempts, project_budget_attempts, project_execution_state
from .build_rebind import superseding_prepared, reverification_candidates
from .build_review import validate_build_review, validate_review_sources, review_summary
from .build_runtime import (
    BuildController, _utc, approve_build_authorization, prepare_build_authorization,
    record_source_snapshot, revoke_build_authorization,
    resolve_build_attempt,
)
from .build_types import RequestValidationError, RevisionConflictError, SAFE_ID_RE, canonical_json
from .revision_store import RevisionControlEventStore as ControlEventStore
from .process_observation import CommandObservation


MUTATIONS = {
    "record-build-plan": {"requirement_ir", "plan", "document_review"},
    "capture-build-sources": {"program_id", "proposal_event_id", "source_root", "manifest"},
    "prepare-build-authorization": {"program_id", "proposal_event_id", "source_event_id", "scope"},
    "approve-build-authorization": {"program_id", "prepared_event_id", "decision"},
    "revoke-build-authorization": {"program_id", "prepared_event_id", "decision", "reason"},
    "reassess-build-attempt": {"program_id", "prepared_event_id", "attempt_id", "decision", "evidence"},
    "reconcile-build-observations": {"program_id", "prepared_event_id"},
    "resolve-build-attempt": {"program_id", "prepared_event_id", "attempt_id", "decision", "reason"},
    "request-build-repair": {"program_id", "prepared_event_id", "targets", "finding"},
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
    successor = superseding_prepared(events, prepared_id)
    state = ("SUPERSEDED" if successor else "REVOKED" if revoked else "EXPIRED" if _utc(payload["scope"]["expires_at"]) <= datetime.now(timezone.utc)
             else "APPROVED" if approved else "APPROVAL_REQUIRED")
    source = next(row for row in events if row["event_id"] == payload["source_event_id"])
    proposal = next(row for row in events if row["event_id"] == payload["proposal_event_id"])
    attempts = [row["payload"] for row in events if row["event_type"] == "BUILD_ATTEMPT_STARTED"
                and row["payload"]["prepared_event_id"] == prepared_id]
    budget = attempt_budget(payload["scope"], list(project_budget_attempts(events, prepared_id).values()))
    continuation = {}
    if payload.get("rebind_from"):
        # Include untouched original owners; their allowance was not reduced.
        for owner in payload["scope"]["task_write_roots"]:
            budget["task_attempts_remaining"].setdefault(owner, payload["scope"]["max_task_attempts"])
        _, accepted = project_execution_state(events, prepared_id)
        continuation = {"rebind_from": payload["rebind_from"],
                        "reverification_pending": sorted(reverification_candidates(events, prepared_id)),
                        "reused_acceptance": {key: {field: record[field] for field in
                            ("attempt_id", "prepared_event_id", "proposal_event_id")}
                            for key, record in accepted.items() if record["prepared_event_id"] != prepared_id}}
    return {"prepared_event_id": prepared_id, "proposal_event_id": payload["proposal_event_id"],
            "requirement_ir": proposal["payload"]["requirement_ir"], "plan": proposal["payload"]["plan"],
            "scope": payload["scope"], "source_binding": _source_summary(source),
            **({"model_defaults_source": payload["model_defaults_source"]} if "model_defaults_source" in payload else {}),
            "verification_files": sorted(payload["verifier_files"]), "state": state,
            **({"verifier_source": payload["verifier_source"]} if "verifier_source" in payload else {}),
            "coding_instruction_preflight": payload.get("coding_instruction_preflight"),
            "acceptance_contracts": payload.get("acceptance_contracts"),
            "budget": {**budget, "this_preparation_attempts": len(attempts)}, **continuation,
            **({"superseded_by": successor} if successor else {}),
            "directory_creation": ("CHECKER_SNAPSHOT_DURING_PREPARE_RESOURCES_DURING_APPROVED_ADVANCE"
                                   if "verifier_source" in payload else "ONLY_DURING_APPROVED_ADVANCE"),
            "freshness_rechecked_at_dispatch": True, "execution_started_by_readback": False}


def read_build(control_db, program_id):
    """Read persisted declarations and progress without creating a database."""
    program_id = _program(program_id)
    store = ControlEventStore(_database(control_db), read_only=True, storage_format="REVISION_V1")
    proposal = read_build_plan_proposal(store, program_id)
    events = store.list_events(program_id)
    latest_proposal = next(row for row in events if row["event_id"] == proposal["proposal_binding"]["proposal_event_id"])
    attempts = project_readback_attempts(events)
    # Host observation inspection is the read-only I/O boundary. It is not part
    # of event projection and does not require executable current authority.
    for row in attempts.values():
        command = row.get("last_command", {})
        if row["status"] in {"UNKNOWN_SIDE_EFFECT", "IN_FLIGHT"} and command.get("observation_root"):
            row["recovery"]["host_observation"] = CommandObservation.inspect(command["observation_root"])
    return {"status": "BUILD_READBACK", "program_id": program_id, "stream_revision": len(events),
            "proposal": proposal, "requirement_ir": latest_proposal["payload"]["requirement_ir"],
            "document_review": review_summary(latest_proposal["payload"].get("document_review")),
            "sources": [_source_summary(row) for row in events if row["event_type"] == "BUILD_SOURCES_CAPTURED"],
            "authorizations": [_scope_readback(row, events) for row in events if row["event_type"] == "BUILD_AUTHORIZATION_PREPARED"],
            "attempts": list(attempts.values()),
            "repair_requests": [{"event_id": row["event_id"], **row["payload"]} for row in events
                                if row["event_type"] == "BUILD_ACCEPTANCE_INVALIDATED"
                                and row["payload"].get("reason") == "CODEX_CONFIRMED_REPAIR_REQUEST"],
            "writes_performed": False,
            "harness_e2e_verified": False}


def apply_build_request(command, request, control_db):
    """Mutate the explicit generic controller or advance its approved workload.

    No caller-selectable test receiver, shell, model fallback or legacy route.
    An invalid initial proposal is rejected before mkdir/DDL. The same stream
    provides transaction/CAS and exact idempotency for all subsequent mutations.
    """
    _require(isinstance(request, dict), "build request must be an object")
    if command == "advance-build":
        required = {"program_id", "prepared_event_id", "expected_revision"}
        _require(required <= set(request) <= required | {"advance_mode", "codex_handoff"},
                 "invalid advance-build fields")
        mode = request.get("advance_mode", "CONTINUOUS")
        _require(mode in ("CONTINUOUS", "ONE_ATTEMPT"), "invalid advance_mode")
        if "codex_handoff" in request:
            handoff = request["codex_handoff"]
            _require(mode == "ONE_ATTEMPT", "codex_handoff requires ONE_ATTEMPT")
            _require(isinstance(handoff, dict) and set(handoff) == {"workpack_id", "basis_attempt_ids", "summary"},
                     "invalid codex_handoff fields")
            _require(all(isinstance(handoff[key], str) and handoff[key].strip()
                         for key in ("workpack_id", "summary")), "codex_handoff needs workpack_id and summary")
            basis = handoff["basis_attempt_ids"]
            _require(isinstance(basis, list) and all(isinstance(item, str) and item.strip() for item in basis)
                     and len(set(basis)) == len(basis), "invalid codex_handoff basis_attempt_ids")
    else:
        required = MUTATIONS.get(command, set()) | {"expected_revision", "idempotency_key"}
        optional = ({"continuation_of"} if command == "request-build-repair" else
                    {"rebind_from", "follow_codex_defaults"} if command == "prepare-build-authorization" else
                    {"host_reconciliation"} if command == "resolve-build-attempt" else set())
        _require(command in MUTATIONS and required <= set(request) <= required | optional,
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
    if command == "reassess-build-attempt":
        human_ref = _human_ref(request["decision"], "REASSESS_BUILD_ATTEMPT")
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
        return {**BuildController(store, program).advance(
                    request["prepared_event_id"], advance_mode=request.get("advance_mode", "CONTINUOUS"),
                    codex_handoff=request.get("codex_handoff")),
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
        event = prepare_build_authorization(store, program, request["proposal_event_id"], request["source_event_id"], request["scope"],
                                             rebind_from=request.get("rebind_from"),
                                             follow_codex_defaults=request.get("follow_codex_defaults", False), **kwargs)
        status = "BUILD_SCOPE_APPROVAL_REQUIRED"
    elif command == "approve-build-authorization":
        event = approve_build_authorization(store, program, request["prepared_event_id"], human_message_ref=human_ref, **kwargs)
        status = "BUILD_APPROVED_EXECUTION_NOT_STARTED"
    elif command == "request-build-repair":
        event = request_build_repair(BuildController(store, program), request)
        return {"status": "BUILD_REPAIR_REQUESTED", "program_id": program, "event_id": event["event_id"],
                "stream_revision": event["stream_revision"], "prepared_event_id": event["payload"]["prepared_event_id"],
                "workpack_ids": event["payload"]["workpack_ids"], "targets": event["payload"]["targets"],
                "finding": event["payload"]["finding"], "budget_reset": False, "files_deleted": False,
                "control_state_write": True, "target_write": False, "execution_started": False,
                "harness_e2e_verified": False}
    elif command == "reconcile-build-observations":
        from .build_reconciliation import reconcile_build_observations
        event = reconcile_build_observations(store, program, request["prepared_event_id"], **kwargs)
        return {"status": "BUILD_COMMAND_OBSERVATIONS_RECONCILED", "program_id": program,
                "event_id": event["event_id"], "stream_revision": event["stream_revision"],
                **event["payload"], "control_state_write": True, "target_write": False,
                "execution_started": False, "harness_e2e_verified": False}
    elif command == "reassess-build-attempt":
        from .build_reassessment import reassess_build_attempt
        event = reassess_build_attempt(BuildController(store, program), request["prepared_event_id"],
            request["attempt_id"], evidence=request["evidence"], human_message_ref=human_ref, **kwargs)
        return {"status": "BUILD_REASSESSMENT_RECORDED_NOT_ACCEPTED", "program_id": program,
                "event_id": event["event_id"], "stream_revision": len(store.list_events(program)),
                "prepared_event_id": request["prepared_event_id"], "attempt_id": request["attempt_id"],
                "control_state_write": True, "target_write": False, "execution_started": False,
                "budget_reset": False, "old_output_accepted": False, "harness_e2e_verified": False}
    elif command == "resolve-build-attempt":
        event = resolve_build_attempt(store, program, request["prepared_event_id"], request["attempt_id"],
                                      reason=request["reason"], human_message_ref=human_ref,
                                      host_reconciliation=request.get("host_reconciliation"), **kwargs)
        status = "BUILD_ATTEMPT_RESOLVED_NOT_EXECUTED"
    else:
        event = revoke_build_authorization(store, program, request["prepared_event_id"], human_message_ref=human_ref,
                                           reason=request["reason"], **kwargs)
        status = "BUILD_AUTHORIZATION_REVOKED"
    return {"status": status, "program_id": program, "event_id": event["event_id"], "stream_revision": event["stream_revision"],
            "readback": _scope_readback(event, store.list_events(program)) if command == "prepare-build-authorization" else None,
            "control_state_write": True, "target_write": False, "execution_started": False, "harness_e2e_verified": False}
