"""Narrow accepted-artifact repair requests; defect judgment stays with Codex."""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from .build_types import RequestValidationError, RevisionConflictError, IdempotencyConflictError, canonical_json
from .build_state import affected_workpacks, repair_budget_exhaustion, project_execution_state, project_budget_attempts
from .build_artifacts import relative_path, file_identity, superseded_artifacts, check_accepted_files


@dataclass(frozen=True)
class RepairContext:
    """Current checked facts supplied immediately by the controller.

    No cached authority or dispatcher is exposed. The existing store's expected
    revision still protects the single invalidation transaction.
    """
    events: list
    prepared: dict
    plan: dict


def _require(condition, message):
    if not condition:
        raise RequestValidationError(message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _validate_request(request, program_id):
    required = {"program_id", "prepared_event_id", "expected_revision", "idempotency_key", "targets", "finding"}
    _require(isinstance(request, dict) and required <= request.keys()
             and request.keys() <= required | {"continuation_of"}, "invalid repair request fields")
    _require(request["program_id"] == program_id and _text(request["prepared_event_id"])
             and _text(request["idempotency_key"]), "repair request must bind this Program and preparation")
    _require(type(request["expected_revision"]) is int and request["expected_revision"] >= 0,
             "repair expected_revision must be a nonnegative integer")
    targets = request["targets"]
    _require(isinstance(targets, list) and bool(targets), "repair targets must be nonempty")
    for target in targets:
        _require(isinstance(target, dict) and set(target) == {"artifact_id", "accepted_attempt_id"}
                 and all(_text(value) for value in target.values()), "invalid repair target")
    _require(len({row["artifact_id"] for row in targets}) == len(targets), "duplicate repair artifact")
    finding = request["finding"]
    _require(isinstance(finding, dict) and set(finding) == {
        "requirement_refs", "reason", "evidence_refs", "repair_goal"}, "invalid confirmed finding fields")
    for key in ("requirement_refs", "evidence_refs"):
        _require(isinstance(finding[key], list) and bool(finding[key]) and all(_text(v) for v in finding[key]),
                 "finding requires nonempty requirement and evidence references")
    _require(_text(finding["reason"]) and _text(finding["repair_goal"]), "finding reason and repair goal are required")
    _require("continuation_of" not in request or _text(request["continuation_of"]), "invalid continuation reference")


def request_build_repair(controller, request):
    """Invalidate current accepted versions atomically; never dispatch a command."""
    _validate_request(request, controller.program_id)
    request = deepcopy(request)
    store, program = controller.store, controller.program_id
    replay = store.idempotent_events(program, request["idempotency_key"])
    if replay is not None:
        if (len(replay) != 1 or replay[0]["event_type"] != "BUILD_ACCEPTANCE_INVALIDATED"
                or canonical_json(replay[0]["payload"].get("repair_request")) != canonical_json(request)):
            raise IdempotencyConflictError("repair idempotency key was reused with different content")
        return replay[0]

    prepared_id = request["prepared_event_id"]
    context = controller.repair_context(prepared_id)
    events, prepared, plan = context.events, context.prepared, context.plan
    if len(events) != request["expected_revision"]:
        raise RevisionConflictError("re-read current build progress before repair")
    workspace = Path(prepared["scope"]["workspace_root"])
    for event in events:
        if event["event_type"] != "BUILD_AUTHORIZATION_PREPARED":
            continue
        prior_root = Path(event["payload"]["scope"]["workspace_root"])
        if workspace.is_relative_to(prior_root) or prior_root.is_relative_to(workspace):
            prior, _ = project_execution_state(events, event["event_id"])
            _require(not any(row["status"] in {"IN_FLIGHT", "UNKNOWN_SIDE_EFFECT"} for row in prior.values()),
                     "repair requires reconciliation of unresolved attempts in overlapping scopes")
    attempts, accepted = project_execution_state(events, prepared_id)
    tasks = {task["workpack_id"]: task for task in plan["workpacks"]}
    producers = {item["artifact_id"]: task["workpack_id"]
                 for task in plan["workpacks"] for item in task["artifacts"]}
    latest = {row["workpack_id"]: row for row in attempts.values()}
    pending = tasks.keys() - accepted.keys()
    origin = None
    if "continuation_of" in request:
        origin = next((row for row in events if row["event_id"] == request["continuation_of"]), None)
        _require(origin is not None and origin["event_type"] == "BUILD_ACCEPTANCE_INVALIDATED"
                 and origin["payload"].get("reason") == "CODEX_CONFIRMED_REPAIR_REQUEST"
                 and origin["payload"].get("prepared_event_id") == prepared_id
                 and "continuation_of" not in origin["payload"].get("repair_request", {}),
                 "continuation must reference the original repair request in this preparation")
        original_scope = set(origin["payload"]["workpack_ids"])
        _require(pending <= original_scope, "unaccepted work is outside the original repair chain")
        invalidations = [row for row in events if row["event_type"] == "BUILD_ACCEPTANCE_INVALIDATED"
                         and row["payload"].get("prepared_event_id") == prepared_id
                         and row["stream_revision"] >= origin["stream_revision"]]
        handled = {row["payload"].get("failed_attempt_id") for row in invalidations
                   if row["payload"].get("reason") == "INDEPENDENT_ARTIFACT_REPAIR_REQUIRED"}
        for key in pending:
            row = latest.get(key, {})
            invalidated = row.get("status") == "INVALIDATED" and any(
                key in item["payload"]["workpack_ids"] and row.get("invalidation") == item["payload"]
                for item in invalidations)
            routed_failure = row.get("status") == "REJECTED" and row.get("attempt_id") in handled
            # Native recovery settled this attempt without implementation. It
            # remains pending in the original chain; its spent budget stays spent.
            not_dispatched = row.get("status") == "NOT_DISPATCHED"
            _require(invalidated or routed_failure or not_dispatched,
                     "latest unaccepted attempt has not been invalidated, handled by native repair or settled as NOT_DISPATCHED")
    else:
        _require(not pending, "initial extra-defect repair requires all plan tasks accepted")

    target_ids = {row["artifact_id"] for row in request["targets"]}
    owners = set()
    for target in request["targets"]:
        owner = producers.get(target["artifact_id"])
        record = accepted.get(owner)
        _require(record is not None and record["attempt_id"] == target["accepted_attempt_id"]
                 and target["artifact_id"] in record["artifacts"], "repair target is not its current accepted version")
        _require(tasks[owner]["executor"] == "CODEX", "LOCAL producer has no prompt-driven repair method")
        _require(origin is None or owner in original_scope, "repair target is outside the original repair chain")
        identity = record["artifacts"][target["artifact_id"]]
        path = relative_path(workspace, identity["path"])
        _require(path.is_file() and file_identity(path) == {key: identity[key] for key in ("size", "sha256")},
                 "repair target bytes differ from the current accepted version")
        owners.add(owner)
    check_accepted_files(workspace, plan, accepted, project_budget_attempts(events, prepared_id))
    affected = affected_workpacks(plan, owners)
    required = affected | pending
    superseded = superseded_artifacts(plan, project_budget_attempts(events, prepared_id))
    _require(not target_ids.intersection(superseded) and not any(
        item["kind"] == "ARTIFACT" and item["id"] in superseded
        for key in required for item in tasks[key]["inputs"]), "repair needs a consumed artifact version")
    exhausted = repair_budget_exhaustion(prepared, project_budget_attempts(events, prepared_id), required)
    _require(exhausted is None, exhausted["status"] if exhausted else "")
    payload = {"prepared_event_id": prepared_id, "reason": "CODEX_CONFIRMED_REPAIR_REQUEST",
               "targets": request["targets"], "finding": request["finding"], "repair_request": request,
               "workpack_ids": [key for key in tasks if key in affected],
               "budget_reset": False, "files_deleted": False}
    if origin is not None:
        payload["continuation_of"] = origin["event_id"]
    return store.append_batch(program, [{"event_type": "BUILD_ACCEPTANCE_INVALIDATED", "payload": payload}],
                              expected_revision=request["expected_revision"], idempotency_key=request["idempotency_key"],
                              created_at=controller.clock().isoformat())[0]
