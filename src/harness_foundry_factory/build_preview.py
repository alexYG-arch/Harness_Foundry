"""Optional complete preview and one real human confirmation for a new build.

Previews are host preparation files, not Programs or authority. Materialization
uses the existing event store, proposal, source and preparation functions. Its
last event explicitly grants the displayed preview; it never claims the human
saw an event ID that did not exist at presentation time.
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from .build_authoring import record_build_plan_proposal
from .build_plan import compile_build_plan, validate_compiled_build_plan
from .build_review import validate_build_document_material, validate_build_review, validate_review_sources
from .build_runtime import (prepare_build_scope, prepare_build_authorization,
                            record_source_snapshot, _utc)
from .build_types import (RequestValidationError, RevisionConflictError,
                          IdempotencyConflictError, canonical_json)
from .revision_store import RevisionControlEventStore
from .source_intake import load_local_sources


def _require(condition, message):
    if not condition:
        raise RequestValidationError(message)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _path(value):
    _require(isinstance(value, str) and Path(value).is_absolute() and ".." not in Path(value).parts,
             "preview paths must be explicit and absolute")
    return Path(value).resolve()


def _document(document):
    """Validate the displayed material without inventing a human decision."""
    _require(isinstance(document, dict) and set(document) == {"document_id", "version", "documents"},
             "preview requires document identity, version and complete documents")
    validate_build_document_material(document)


def _source(request):
    root = _path(request["source_root"])
    return {"source_root": str(root), "manifest": deepcopy(request["manifest"]),
            "snapshot": load_local_sources(root, request["manifest"])}


def _same_preparation(preview, *, now):
    request = preview["request"]
    _document(request["document"])
    source = _source(request)
    _require(source == preview["source"], "preview source changed; show updated scope before confirmation")
    validate_review_sources(request["document"], request["requirement_ir"],
                            source_root=source["source_root"], snapshot=source["snapshot"])
    prepared = prepare_build_scope(SimpleNamespace(database_path=Path(preview["control_db"])),
        request["requirement_ir"], request["plan"], source, preview["materialization_scope"],
        created_at=now, prepared_preview=preview["prepared"])
    return prepared


def preview_build(request, control_db, *, clock=None):
    """Save complete nonexecuting host preparation; no controller is created."""
    now = (clock or _now)()
    required = {"preview_path", "document", "requirement_ir", "plan", "source_root", "manifest", "scope"}
    _require(isinstance(request, dict) and required <= set(request) <= required | {"follow_codex_defaults"},
             "invalid preview-build fields")
    request = deepcopy(request)
    path, database = _path(request["preview_path"]), _path(str(control_db))
    _require(path != database, "preview file cannot be the control database")
    if path.exists():
        preview = json.loads(path.read_text(encoding="utf-8"))
        _require(preview.get("request") == request and preview.get("control_db") == str(database),
                 "preview path already binds different content; preserve it and use a new version")
        _verify_envelope(preview)
        _same_preparation(preview, now=now)
        return _preview_result(preview, path)
    if database.exists():
        store = RevisionControlEventStore(database, read_only=True)
        _require(not store.list_program_ids(), "complete initial preview cannot replace an existing Program")
    _document(request["document"])
    compiled = compile_build_plan(request["requirement_ir"], request["plan"])
    validate_compiled_build_plan(request["requirement_ir"], request["plan"], compiled)
    source = _source(request)
    validate_review_sources(request["document"], request["requirement_ir"],
                            source_root=source["source_root"], snapshot=source["snapshot"])
    workspace = _path(request["scope"]["workspace_root"])
    _require(not path.is_relative_to(workspace), "preview must be host-owned outside the target workspace")
    resources = request["scope"].get("verification_resources")
    _require(not resources or not path.is_relative_to(_path(resources["root"])),
             "preview must be outside writable verification resources")
    prepared = prepare_build_scope(SimpleNamespace(database_path=database),
        request["requirement_ir"], request["plan"], source, request["scope"], created_at=now,
        follow_codex_defaults=request.get("follow_codex_defaults", False))
    # Frozen defaults stay frozen. Daily defaults retain their existing policy
    # and bound service. The original request remains available for audit.
    materialization_scope = deepcopy(prepared["scope"])
    if "verifier_source" in prepared:
        materialization_scope["verification_root"] = prepared["verifier_source"]["source_root"]
    preview = {"schema_version": "BUILD_PREVIEW_V1", "preview_id": "PREVIEW-" + uuid4().hex,
               "created_at": now, "control_db": str(database), "request": request,
               "source": source, "prepared": prepared, "materialization_scope": materialization_scope,
               "execution_started": False, "runtime_authorized": False,
               "snapshot_write_root": str(database.with_suffix(".verifiers")),
               "confirmation_action": "CONFIRM_BUILD_AND_RUNTIME"}
    preview["sha256"] = _digest(preview)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(preview, ensure_ascii=False, indent=2) + "\n")
    return _preview_result(preview, path)


def _verify_envelope(preview):
    _require(isinstance(preview, dict) and preview.get("schema_version") == "BUILD_PREVIEW_V1"
             and preview.get("sha256") == _digest({k: v for k, v in preview.items() if k != "sha256"}),
             "preview identity/content mismatch")


def _preview_result(preview, path):
    return {"status": "BUILD_PREVIEW_NOT_AUTHORIZED", "preview_id": preview["preview_id"],
            "preview_path": str(path), "preview_sha256": preview["sha256"], "readback": deepcopy(preview),
            "control_state_write": False, "target_write": False, "execution_started": False,
            "harness_e2e_verified": False}


def _result(events, confirmed, approved):
    prepared_id = approved["payload"]["prepared_event_id"]
    return {"status": "BUILD_PREVIEW_MATERIALIZED", "program_id": approved["program_id"],
            "preview_id": confirmed["payload"]["preview"]["preview_id"],
            "prepared_event_id": prepared_id, "event_id": approved["event_id"],
            "stream_revision": len(events), "approval_basis": approved["payload"]["approval_basis"],
            "authority_revalidated": False, "control_state_write": True, "target_write": False,
            "execution_started": False, "harness_e2e_verified": False}


def materialize_build_preview(request, control_db, *, clock=None):
    """Resume one confirmed preparation without inventing human/event chronology."""
    now = clock or _now
    required = {"preview_path", "preview_sha256", "presentation", "decision", "expected_revision", "idempotency_key"}
    _require(isinstance(request, dict) and set(request) == required, "invalid materialize-build-preview fields")
    _require(type(request["expected_revision"]) is int and request["expected_revision"] >= 0,
             "expected_revision must be nonnegative")
    key = request["idempotency_key"]
    _require(isinstance(key, str) and key.strip(), "idempotency_key is required")
    path, database = _path(request["preview_path"]), _path(str(control_db))
    store = RevisionControlEventStore(database, read_only=True) if database.exists() else None
    programs = store.list_program_ids() if store else []
    _require(len(programs) <= 1, "controller belongs to multiple Programs")
    confirmed = None
    events = store.list_events(programs[0]) if programs else []
    if store and programs:
        found = store.idempotent_events(programs[0], key + ":confirmation")
        if found:
            _require(len(found) == 1 and found[0]["event_type"] == "BUILD_PREVIEW_CONFIRMED",
                     "materialization key conflicts with existing records")
            confirmed = found[0]
            if confirmed["payload"]["request"] != request:
                raise IdempotencyConflictError("materialization key was reused with different confirmation")
    preview = (confirmed["payload"]["preview"] if confirmed else json.loads(path.read_text(encoding="utf-8")))
    _verify_envelope(preview)
    _require(preview["sha256"] == request["preview_sha256"] and preview["control_db"] == str(database)
             and preview["request"]["preview_path"] == request["preview_path"], "confirmation binds a different preview")
    program = preview["request"]["requirement_ir"]["program_id"]
    _require(not programs or programs == [program], "controller belongs to another Program")
    if confirmed:
        complete = store.idempotent_events(program, key + ":approval")
        if complete:
            # Complete capture is retrieval, even after expiry/revocation or
            # removal of preparation files. Dispatch revalidates current grant.
            return _result(events, confirmed, complete[0])
    decision = request["decision"]
    _require(isinstance(decision, dict) and decision.get("action") == "CONFIRM_BUILD_AND_RUNTIME",
             "one real human message must explicitly confirm both document and runtime scope")
    review = {**preview["request"]["document"], "presentation": request["presentation"], "decision": decision}
    validate_build_review(review)
    _same_preparation(preview, now=now())
    if not confirmed:
        _require(request["expected_revision"] == 0 and not events,
                 "initial preview materialization cannot overwrite or reset an existing Program")
    else:
        expected_types = ["BUILD_PREVIEW_CONFIRMED", "BUILD_PLAN_PROPOSED", "BUILD_SOURCES_CAPTURED", "BUILD_AUTHORIZATION_PREPARED"]
        _require([event["event_type"] for event in events] == expected_types[:len(events)],
                 "materialization stream changed; inspect current records before continuing")
    store = RevisionControlEventStore(database)
    if confirmed is None:
        confirmed = store.append_batch(program, [{"event_type": "BUILD_PREVIEW_CONFIRMED", "payload": {
            "request": deepcopy(request), "preview": deepcopy(preview), "document_review": review,
            "runtime_authorized": False}}], expected_revision=0, idempotency_key=key + ":confirmation",
            created_at=now(), exclusive_program=True)[0]
    def step(suffix, kind, operation):
        prior = store.idempotent_events(program, key + ":" + suffix)
        if prior:
            _require(len(prior) == 1 and prior[0]["event_type"] == kind, "unexpected materialization record")
            return prior[0]
        return operation({"expected_revision": len(store.list_events(program)),
                          "idempotency_key": key + ":" + suffix, "created_at": now()})
    proposal = step("proposal", "BUILD_PLAN_PROPOSED", lambda kw: record_build_plan_proposal(store,
        preview["request"]["requirement_ir"], preview["request"]["plan"], document_review=review, **kw))
    source = step("sources", "BUILD_SOURCES_CAPTURED", lambda kw: record_source_snapshot(store, program,
        proposal["event_id"], preview["source"]["source_root"], preview["source"]["manifest"], **kw))
    prepared = step("prepared", "BUILD_AUTHORIZATION_PREPARED", lambda kw: prepare_build_authorization(store,
        program, proposal["event_id"], source["event_id"], preview["materialization_scope"],
        prepared_preview=preview["prepared"], **kw))
    # Validate once more immediately before the final grant. No previous step
    # authorizes dispatch, including when a crash leaves a complete prepared.
    _same_preparation(preview, now=now())
    current = store.list_events(program)
    _require([e["event_type"] for e in current] == ["BUILD_PREVIEW_CONFIRMED", "BUILD_PLAN_PROPOSED",
        "BUILD_SOURCES_CAPTURED", "BUILD_AUTHORIZATION_PREPARED"],
        "materialization changed or was revoked before approval")
    _require(prepared["payload"]["proposal_event_id"] == proposal["event_id"]
             and prepared["payload"]["source_event_id"] == source["event_id"], "materialization binding mismatch")
    basis = {"kind": "CONFIRMED_COMPLETE_PREVIEW_V1", "confirmation_event_id": confirmed["event_id"],
             "preview_id": preview["preview_id"], "preview_sha256": preview["sha256"],
             "presentation": request["presentation"], "prepared_event_id": prepared["event_id"]}
    approved = store.append_batch(program, [{"event_type": "BUILD_AUTHORIZATION_APPROVED", "payload": {
        "prepared_event_id": prepared["event_id"], "human_message_ref": canonical_json(decision),
        "approval_basis": basis}}], expected_revision=len(current), idempotency_key=key + ":approval", created_at=now())[0]
    return _result(store.list_events(program), confirmed, approved)
