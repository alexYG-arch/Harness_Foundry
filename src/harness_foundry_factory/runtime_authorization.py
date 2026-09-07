"""Public local-runtime authorization, not a model or Workpack executor.

The trusted chat host supplies the actual human decision. Readback is pure;
approval reuses the kernel receipt and its single SQLite authority. These
commands do not authenticate a chat transcript or manufacture an approval.
"""

from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Mapping

from .control_kernel import (
    ControlKernelError, GenericTransitionEngine, START_PACKAGE_BINDING_KIND,
    _parse_time, _require_scope_subset, _transition_scope, _validate_transition_contract,
    prepare_parent_authorization_challenge, prepare_parent_approval_receipt,
    rebuild_control_projections,
)
from .execution_handoff import verify_runtime_factory_binding
from .local_runtime import LOCAL_CLASS
from .models import SAFE_ID_RE
from .startup_runtime import (
    STARTUP_CLASS, CONTROL_DB_REF, STATE_REF, EVENTS_REF, startup_transitions,
    project_startup_views, verify_startup_views,
)
from .store import ControlEventStore


def _require(condition, message, code="RUNTIME_AUTHORIZATION_INVALID"):
    if not condition:
        raise ControlKernelError(code, message)


def _human(actor):
    _require(isinstance(actor, Mapping) and actor.get("type") == "HUMAN_VIA_CODEX_CHAT"
             and all(isinstance(actor.get(field), str) and actor[field].strip()
                     for field in ("chat_thread_id", "turn_id")),
             "an actual human chat decision with thread and turn identity is required", "PARENT_APPROVAL_INVALID")


def _path(value):
    _require(isinstance(value, str) and Path(value).is_absolute() and ".." not in Path(value).parts,
             "paths must be explicit absolute bindings")
    path = Path(value)
    _require(path.resolve() == path, "linked controller paths are not supported")
    return path


def _store(database, program):
    if not database.exists():
        return None
    _require(database.is_file(), "controller must be a native database file")
    store = ControlEventStore(database, read_only=True)
    _require(set(store.list_program_ids()).issubset({program}), "controller belongs to a different Program")
    _require(store.verify_stream(program)["status"] == "PASS", "control event stream is invalid")
    return store


def _preflight(parent, control_db):
    _require(isinstance(parent, Mapping) and isinstance(parent.get("program_id"), str)
             and SAFE_ID_RE.fullmatch(parent["program_id"]), "Program identity is required")
    challenge = prepare_parent_authorization_challenge(parent, expected_bindings=parent.get("bindings", {}))
    _require(parent.get("bindings", {}).get("binding_kind") == START_PACKAGE_BINDING_KIND,
             "public local authorization requires the live Factory approval binding")
    plans = {key: parent[key] for key in ("startup_execution", "local_execution") if key in parent}
    _require(bool(plans), "an explicit startup or offline process plan is required")
    plan = plans.get("startup_execution", plans.get("local_execution"))
    database, execution, candidate = (_path(str(control_db)), _path(plan["execution_root"]), _path(plan["candidate_root"]))
    _require(database == _path(plan["control_db"]) == execution / CONTROL_DB_REF,
             "use the one controller named in the Parent plan")
    _require(not execution.exists() or execution.is_dir(), "execution root is not a directory")
    # Read-only Factory locators retain their approved spelling (including OS
    # aliases such as /var); compare their resolved identity to writable roots.
    protected = [candidate, Path(plan["factory_source"]["runs_root"]).resolve(),
                 Path(plan["factory_source"]["database_path"]).resolve().parent, Path(__file__).resolve().parents[2]]
    _require(all(not execution.is_relative_to(root) and not root.is_relative_to(execution) for root in protected),
             "execution root overlaps Candidate, Factory or authoring storage")
    _require(_parse_time(parent["expires_at"], "PARENT_AUTHORIZATION_INVALID") > datetime.now(timezone.utc),
             "Parent has expired", "PARENT_AUTHORIZATION_EXPIRED")
    expected_classes = {STARTUP_CLASS if key == "startup_execution" else LOCAL_CLASS for key in plans}
    _require(set(parent["command_classes"]) == expected_classes,
             "Parent command classes must match its implemented local plans")
    for key, value in plans.items():
        if key == "startup_execution":
            _require(value["transitions"] == startup_transitions(candidate, parent["bindings"]),
                     "startup transitions differ from the Candidate DAG")
        for transition in value["transitions"].values():
            _validate_transition_contract(transition)
            _require(transition.get("bindings") == parent["bindings"], "transition binding differs from its Parent")
            _require_scope_subset(parent, _transition_scope(transition))
    verify_runtime_factory_binding(parent)
    store = _store(database, parent["program_id"])
    if any((execution / ref).exists() for ref in (STATE_REF, EVENTS_REF)):
        _require(store is not None, "legacy controller must be migrated explicitly", "LOCAL_LEGACY_CONTROLLER_PRESENT")
        if "startup_execution" in plans:
            rows = project_startup_views(store, parent["program_id"], execution)
            _require(bool(rows) and all(row["result"]["native_transaction"]["candidate_tree_sha256"]
                                       == parent["bindings"]["candidate_tree_sha256"] for row in rows),
                     "legacy control files are not owned by this SQLite stream", "LOCAL_LEGACY_CONTROLLER_PRESENT")
        else:
            verify_startup_views(store, parent["program_id"], execution, parent["bindings"])
    return challenge, database, store


def prepare_runtime_authorization(parent, control_db):
    challenge, database, store = _preflight(parent, control_db)
    return {"status": "RUNTIME_PARENT_APPROVAL_REQUIRED", "challenge": challenge,
            "control_db_exists": store is not None, "writes_performed": False,
            "execution_started": False, "authorization_granted": False}


def approve_runtime_authorization(parent, challenge, approval, control_db):
    # All decision validation precedes mkdir, DDL or grant registration.
    receipt = prepare_parent_approval_receipt(parent, challenge, approval)
    _human(approval.get("approved_by"))
    _require(_parse_time(approval.get("approved_at"), "PARENT_APPROVAL_INVALID") <= datetime.now(timezone.utc),
             "approval time is in the future", "PARENT_APPROVAL_INVALID")
    _, database, store = _preflight(parent, control_db)
    if store is not None:
        events = store.list_events(parent["program_id"])
        current = rebuild_control_projections(events)["grant_ledger"]["parents"].get(parent["authorization_id"])
        if current is not None:
            _require(current["status"] in {"ACTIVE", "GRANTED"}, "a revoked Parent cannot be reactivated", "PARENT_AUTHORIZATION_REVOKED")
            previous = next(event["payload"].get("approval_receipt") for event in events
                            if event["event_type"] == "PARENT_AUTHORIZATION_GRANTED"
                            and event["payload"]["authorization"]["authorization_id"] == parent["authorization_id"])
            _require(previous == receipt, "authorization ID already binds a different decision", "PARENT_APPROVAL_CONFLICT")
            return {"status": "RUNTIME_PARENT_ALREADY_APPROVED", "approval_receipt": previous,
                    "writes_performed": False, "execution_started": False}
    try:
        # A native empty store left after interruption is resumable. An existing
        # non-native SQLite file is rejected by the store; never overwrite it.
        writable = ControlEventStore(database)
        verify_runtime_factory_binding(parent)
        result = GenericTransitionEngine(writable, {}).register_approved_parent_authorization(
            parent, challenge, approval, created_at=datetime.now(timezone.utc).isoformat(), exclusive_program=True)
    except OSError as exc:
        raise ControlKernelError("RUNTIME_INITIALIZATION_FAILED", str(exc)) from exc
    return {"status": "RUNTIME_PARENT_APPROVED_EXECUTION_NOT_STARTED", "approval_receipt": result,
            "control_db": str(database), "writes_performed": True, "execution_started": False}


def revoke_runtime_authorization(program, parent_id, actor, reason, control_db):
    _human(actor)
    _require(isinstance(program, str) and SAFE_ID_RE.fullmatch(program)
             and isinstance(parent_id, str) and parent_id
             and isinstance(reason, str) and reason.strip(), "Program, Parent and revocation reason are required")
    database = _path(str(control_db))
    store = _store(database, program)
    _require(store is not None, "controller does not exist")
    parent = rebuild_control_projections(store.list_events(program))["grant_ledger"]["parents"].get(parent_id)
    _require(parent is not None, "Parent does not exist")
    plan = parent.get("startup_execution", parent.get("local_execution"))
    _require(isinstance(plan, Mapping) and database == _path(plan["control_db"])
             == _path(plan["execution_root"]) / CONTROL_DB_REF, "controller differs from the recorded Parent")
    if parent["status"] == "REVOKED":
        return {"status": "RUNTIME_PARENT_ALREADY_REVOKED", "writes_performed": False, "execution_started": False}
    # Revocation must remain possible after Factory REOPEN or Parent expiry.
    GenericTransitionEngine(ControlEventStore(database), {}).revoke_parent_authorization(
        program, parent_id, revoked_by=actor, reason=reason, created_at=datetime.now(timezone.utc).isoformat())
    return {"status": "RUNTIME_PARENT_REVOKED", "writes_performed": True, "execution_started": False,
            "in_flight_process_terminated": False}
