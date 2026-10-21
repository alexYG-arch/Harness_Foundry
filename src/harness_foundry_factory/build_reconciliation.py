"""Ingest completed host observations without granting or executing work.

Missing captures remain missing. A separate authenticated host decision may
reconcile termination and effects for a retry; it never invents a process result.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .build_state import project_execution_state
from .build_types import RequestValidationError, RevisionConflictError, IdempotencyConflictError, canonical_json
from .process_observation import CommandObservation


_SUMMARY_EVENT = "BUILD_OBSERVATIONS_RECONCILED"


def _require(condition, message):
    if not condition:
        raise RequestValidationError(message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _missing_commands(events, attempt):
    rows = [row for row in events if row["payload"].get("attempt_id") == attempt["attempt_id"]]
    observed = {row["payload"]["command_id"] for row in rows if row["event_type"] == "BUILD_COMMAND_OBSERVED"}
    planned = [row["payload"] for row in rows if row["event_type"] == "BUILD_COMMAND_PLANNED"]
    _require(len({row["command_id"] for row in planned}) == len(planned), "duplicate command intent needs host inspection")
    fields = ("prepared_event_id", "proposal_event_id", "attempt_id", "workpack_id", "job_id")
    _require(all(all(row.get(key) == attempt.get(key) for key in fields) for row in planned),
             "command intent differs from the attempt binding")
    return [row for row in planned if row["command_id"] not in observed]


def _completed_resource_result(command):
    """Read only an already settled resource receipt, never stage or clean it."""
    root = Path(command["observation_root"])
    saved, cleaned = root / "resource-result.json", root / "resource-cleanup.json"
    if not saved.is_file() or not cleaned.is_file():
        return None
    binding = command["resource_binding"]
    stored = json.loads(saved.read_text())
    _require(isinstance(stored, dict) and stored.get("binding") == binding,
             "resource observation belongs to another command binding")
    result = deepcopy(stored["result"])
    _require(isinstance(result, dict), "resource result must be an object")
    cleanup = json.loads(cleaned.read_text())
    _require(isinstance(cleanup, dict) and _text(cleanup.get("status")), "resource cleanup receipt is incomplete")
    # Only archived report bytes are used. Neither live staging nor credentials
    # are read again, including when the original scratch has already gone.
    if binding.get("profile", {}).get("credentials") and result.get("workload_started") is not False:
        from .resource_observation import _credential_reports
        _credential_reports(result, binding, root)
    else:
        from .verification_resources import _read_regular
        reports = result.get("resource_reports", [])
        names = [report["name"] for report in reports]
        _require(len(names) == len(set(names)) and not set(names) - set(binding["report_files"]),
                 "resource report archive differs from its declared files")
        for report in reports:
            content = _read_regular(root / "reports", report["name"])
            _require(len(content) == report["size_bytes"]
                     and hashlib.sha256(content).hexdigest() == report["sha256"],
                     "resource report archive differs from its completion receipt")
    result["resource_cleanup"] = cleanup
    return result


def reconcile_build_observations(store, program_id, prepared_event_id, *, expected_revision,
                                 idempotency_key, created_at):
    """Persist completed facts after interruption, even after expiry/revocation.

    This route changes only the controller stream. It does not classify an
    attempt as accepted, recheck products, resolve effects, allocate resources,
    run a verifier, or continue a business command. Resource records requiring
    report settlement or cleanup are explicitly left pending.
    """
    request = {"prepared_event_id": prepared_event_id, "expected_revision": expected_revision,
               "idempotency_key": idempotency_key}
    replay = store.idempotent_events(program_id, idempotency_key)
    if replay is not None:
        if (not replay or replay[-1]["event_type"] != _SUMMARY_EVENT
                or canonical_json(replay[-1]["payload"].get("request")) != canonical_json(request)):
            raise IdempotencyConflictError("observation reconciliation key was reused with different content")
        return replay[-1]
    events = store.list_events(program_id)
    if len(events) != expected_revision:
        raise RevisionConflictError("re-read current build progress before reconciling observations")
    _require(any(row["event_id"] == prepared_event_id and row["event_type"] == "BUILD_AUTHORIZATION_PREPARED"
                 for row in events), "prepared reference is not in this Program's event stream")
    attempts, _ = project_execution_state(events, prepared_event_id)
    entries, recovered, pending = [], [], []
    for attempt in attempts.values():
        if attempt["status"] not in {"IN_FLIGHT", "UNKNOWN_SIDE_EFFECT"}:
            continue
        for command in _missing_commands(events, attempt):
            try:
                raw = CommandObservation.recover(command["observation_root"], command["command_id"], command["executor"])
                if raw is None:
                    pending.append({"command_id": command["command_id"], "reason": "COMPLETE_CAPTURE_UNAVAILABLE"})
                    continue
                _require(isinstance(raw, dict), "completed command observation must be an object")
                result = raw
                if "resource_binding" in command:
                    result = _completed_resource_result(command)
                    if result is None:
                        pending.append({"command_id": command["command_id"],
                                        "reason": "RESOURCE_SETTLEMENT_PENDING"})
                        continue
                elif command["phase"] == "VERIFICATION":
                    # Local import keeps this observation-only helper separate
                    # from the controller's dispatch lifecycle.
                    from .build_runtime import classify_verification_result
                    result = classify_verification_result(result)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise RequestValidationError("cannot reconcile complete command observation") from exc
            entries.append({"event_type": "BUILD_COMMAND_OBSERVED", "payload": {**command, "result": result}})
            recovered.append(command["command_id"])
    entries.append({"event_type": _SUMMARY_EVENT, "payload": {
        "prepared_event_id": prepared_event_id, "request": request,
        "recovered_command_ids": recovered, "pending_commands": pending,
        "execution_started": False, "target_write": False, "cleanup_performed": False,
        "automatic_acceptance": False, "budget_reset": False,
    }})
    return store.append_batch(program_id, entries, expected_revision=expected_revision,
                              idempotency_key=idempotency_key, created_at=created_at)[-1]


def validate_host_reconciliation(events, attempt, receipt):
    """Validate the binding/shape of trusted host assertions, not their truth.

    The public resolve route still authenticates the actual human decision.
    Neither a PID probe nor this JSON document proves termination or effects.
    The host must have reconciled the whole command process tree and effects
    from its referenced evidence before submitting this receipt.
    """
    _require(isinstance(receipt, dict) and set(receipt) == {"prepared_event_id", "attempt_id", "commands"},
             "host reconciliation requires prepared, attempt and command bindings")
    _require(receipt["prepared_event_id"] == attempt["prepared_event_id"]
             and receipt["attempt_id"] == attempt["attempt_id"], "host reconciliation belongs to another attempt")
    missing = _missing_commands(events, attempt)
    _require(bool(missing), "host reconciliation is only for missing command observations")
    records = receipt["commands"]
    _require(isinstance(records, list) and len(records) == len(missing),
             "host reconciliation must cover exactly the missing commands")
    _require(all(isinstance(row, dict) and set(row) == {
        "command_id", "executor", "observation_root", "termination", "effects"} for row in records),
        "invalid host command reconciliation fields")
    expected = {row["command_id"]: row for row in missing}
    identifiers = [row["command_id"] for row in records]
    _require(all(_text(value) for value in identifiers) and len(set(identifiers)) == len(identifiers)
             and set(identifiers) == set(expected), "host reconciliation command set differs from missing observations")
    for row in records:
        command = expected[row["command_id"]]
        _require(all(row[key] == command[key] for key in ("executor", "observation_root")),
                 "host command identity differs from the original dispatch")
        for field in ("termination", "effects"):
            facts = row[field]
            _require(isinstance(facts, dict) and set(facts) == {"status", "detail", "evidence_refs"}
                     and _text(facts["detail"]) and isinstance(facts["evidence_refs"], list)
                     and bool(facts["evidence_refs"]) and all(_text(ref) for ref in facts["evidence_refs"]),
                     "host reconciliation requires specific termination and effects evidence")
        status = row["termination"]["status"]
        _require(_text(status) and status in {"PROCESS_TREE_TERMINATED", "NOT_STARTED"},
                 "active or unknown process outcome cannot permit retry")
        if status == "NOT_STARTED":
            _require(not any(event["event_type"] == "BUILD_COMMAND_STARTED"
                             and event["payload"].get("command_id") == row["command_id"] for event in events)
                     and not (Path(command["observation_root"]) / "started.json").exists(),
                     "an observed process start cannot be reconciled as not started")
        _require(row["effects"]["status"] == "RECONCILED_FOR_RETRY", "unknown effects cannot permit retry")
        try:
            raw = CommandObservation.recover(command["observation_root"], command["command_id"], command["executor"])
            completed = (_completed_resource_result(command) if raw is not None and "resource_binding" in command
                         else raw)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise RequestValidationError("inspect the original command observation before host reconciliation") from exc
        _require(completed is None, "complete command observation is available; reconcile it before resolving effects")
    return deepcopy(receipt)
