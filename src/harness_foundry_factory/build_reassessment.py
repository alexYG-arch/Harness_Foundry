"""Append-only correction of a completely captured reconnect misclassification.

The original command, attachments and attempt budget remain historical facts.
Only the existing controller may subsequently finish the original checks.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .build_state import project_budget_attempts
from .build_types import (IdempotencyConflictError, RequestValidationError,
                          RevisionConflictError, canonical_json)
from .coding_events import CodingEventObserver
from .coding_process import classify_coding_capture
from .process_observation import CommandObservation


EVENT = "BUILD_COMMAND_REASSESSED"
POLICY = "COMPLETED_RECONNECT_V1"


def require(condition, message):
    if not condition:
        raise RequestValidationError(message)


def runtime_identity():
    """Bind this observation policy, not unrelated product or legacy modules."""
    root = Path(__file__).parent
    names = ("build_reassessment.py", "coding_events.py", "coding_process.py", "process_observation.py")
    files = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
    return hashlib.sha256(canonical_json(files).encode()).hexdigest()


def capture_identity(command):
    """Read the original capture; never rewrite or synthesize a missing receipt."""
    root = Path(command["observation_root"])
    names = ["binding.json", "capture.json", "result.json", "stdout.bin"]
    names += [name for name in ("stderr.bin", "started.json", "model-configuration.json")
              if (root / name).exists()]
    identities = {}
    for name in names:
        path = root / name
        require(path.is_file() and not path.is_symlink(), "complete ordinary capture files required")
        digest, size = hashlib.sha256(), 0
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
                size += len(chunk)
                require(size <= 128 * 1024 * 1024, "command observation exceeds stream limit")
        identities[name] = {"sha256": digest.hexdigest(), "size_bytes": size}
    return identities


def replay_completed(command, expected):
    """Reinterpret durable bytes, using the current receipt validator as recovery does."""
    require(command["executor"] == "CODEX" and command["phase"] == "IMPLEMENTATION",
            "only a CODEX implementation observation can be reassessed")
    require(capture_identity(command) == expected, "capture bytes changed since recovery review")
    root = Path(command["observation_root"])
    binding = json.loads((root / "binding.json").read_text())
    require(binding == {"command_id": command["command_id"], "executor": "CODEX"},
            "capture dispatch identity differs")
    old = command["result"]
    require(json.loads((root / "result.json").read_text()) == old,
            "durable result differs from the recorded observation")
    capture = json.loads((root / "capture.json").read_text())
    require(old.get("capture") == capture, "capture differs from the original completion receipt")
    # Do not consult today's defaults or replace an old command's bound service.
    # Absence is legitimate only for legacy results that never claimed a config.
    try:
        CommandObservation._checked_configuration(root, binding, old)
        CommandObservation._checked_configuration(root, binding, capture)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RequestValidationError("cannot reconcile bound model configuration") from exc
    require(old.get("status") == "MODEL_PROCESS_FAILED"
            and old.get("reason_code") == "CODEX_PROCESS_OR_TURN_FAILED",
            "only the original process-or-turn misclassification is eligible")
    require(type(capture.get("exit_code")) is int and capture["exit_code"] == 0
            and capture.get("timed_out") is False and not capture.get("capture_error")
            and not capture.get("cancellation_reason") and capture.get("process_started") is not False,
            "successful, complete process capture required")
    for name in ("stdout", "stderr"):
        size = expected.get(name + ".bin", {}).get("size_bytes", 0)
        require(type(capture.get("stream_bytes", {}).get(name)) is int
                and capture["stream_bytes"][name] == size, "raw stream attachment is incomplete")
    observer = CodingEventObserver()
    with (root / "stdout.bin").open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            observer.feed(chunk)
    result = classify_coding_capture(capture, observer)
    require(result.get("status") == "MODEL_TURN_COMPLETED" and result.get("reconnect_notifications"),
            "original stream is not a completed recoverable reconnect")
    for field in ("thread_id", "event_count", "usage", "final_message", "reported_command_failures"):
        require(result.get(field) == old.get(field), "reinterpreted stream differs in " + field)
    CommandObservation._checked_configuration(root, binding, result)
    require(capture_identity(command) == expected, "capture changed during reassessment")
    return result


def _command(events, attempt):
    rows = [row for row in events if row["payload"].get("attempt_id") == attempt["attempt_id"]]
    planned = [row["payload"] for row in rows if row["event_type"] == "BUILD_COMMAND_PLANNED"]
    observed = [row["payload"] for row in rows if row["event_type"] == "BUILD_COMMAND_OBSERVED"]
    require(len(planned) == len(observed)
            and len({row["command_id"] for row in planned}) == len(planned)
            and len({row["command_id"] for row in observed}) == len(observed),
            "missing or duplicate observations require ordinary reconciliation")
    fields = ("prepared_event_id", "proposal_event_id", "attempt_id", "workpack_id", "job_id")
    for intent, fact in zip(planned, observed):
        require(all(fact.get(key) == value for key, value in intent.items())
                and all(intent.get(key) == attempt.get(key) for key in fields),
                "command observation differs from its original attempt")
    starts = [row["payload"] for row in rows if row["event_type"] == "BUILD_COMMAND_STARTED"]
    require(len({row["command_id"] for row in starts}) == len(starts), "duplicate command start records")
    for start in starts:
        intent = next((row for row in planned if row["command_id"] == start["command_id"]), None)
        require(intent is not None and all(start.get(key) == value for key, value in intent.items()),
                "unbound command start requires ordinary reconciliation")
    require([row["phase"] for row in observed] in (["IMPLEMENTATION"], ["PREFLIGHT", "IMPLEMENTATION"]),
            "only a completed producer before verification is eligible")
    if len(observed) == 2:
        require(observed[0]["result"].get("status") == "PASS", "preflight did not pass")
    return observed[-1]


def reassess_build_attempt(controller, prepared_id, attempt_id, *, evidence, human_message_ref,
                           expected_revision, idempotency_key, created_at):
    require(isinstance(human_message_ref, str) and human_message_ref.strip(),
            "the trusted host must bind the actual recovery decision")
    request = {"prepared_event_id": prepared_id, "attempt_id": attempt_id, "evidence": evidence,
               "human_message_ref": human_message_ref, "expected_revision": expected_revision}
    prior = controller.store.idempotent_events(controller.program_id, idempotency_key)
    if prior is not None:
        if (len(prior) != 3 or prior[0]["event_type"] != EVENT
                or canonical_json(prior[0]["payload"].get("request")) != canonical_json(request)):
            raise IdempotencyConflictError("reassessment key reused with different content")
        return prior[0]  # Pure receipt retrieval does not confer fresh execution authority.
    events, prepared, plan = controller._current(prepared_id)
    if len(events) != expected_revision:
        raise RevisionConflictError("re-read progress before reassessment")
    require(isinstance(evidence, dict) and set(evidence) == {"runtime_identity", "capture_files", "artifacts"},
            "bind the reviewed observer, original capture and current outputs")
    require(evidence["runtime_identity"] == runtime_identity(), "reviewed observation policy changed")
    attempts, accepted = controller._state(events, prepared_id)
    attempt = attempts.get(attempt_id)
    require(attempt is not None and attempt["status"] in {"BLOCKED", "REJECTED"},
            "only a current blocked process result can be reassessed")
    require(attempt == [row for row in attempts.values() if row["workpack_id"] == attempt["workpack_id"]][-1],
            "a later attempt supersedes this result")
    # _current already applies the approved replan boundary to every started
    # task; unrelated Plan revisions and goal wording do not change its checks.
    budget_attempts = project_budget_attempts(events, prepared_id)
    require(not any(row["status"] in {"IN_FLIGHT", "UNKNOWN_SIDE_EFFECT"} for row in budget_attempts.values()),
            "unresolved attempts must be reconciled first")
    require(not any(row["event_type"] in {EVENT, "BUILD_VERIFICATION_INPUTS"}
                    and row["payload"].get("attempt_id") == attempt_id for row in events),
            "attempt was already reassessed or verification started")
    task = next(row for row in plan["workpacks"] if row["workpack_id"] == attempt["workpack_id"])
    require(task["executor"] == "CODEX" and task["verification"] and set(task["depends_on"]) <= accepted.keys(),
            "producer or prerequisites are not eligible")
    command = _command(events, attempt)
    result = replay_completed(command, evidence["capture_files"])
    workspace = Path(prepared["scope"]["workspace_root"])
    artifacts = controller._artifacts(workspace, task["artifacts"])
    require(artifacts == evidence["artifacts"], "reviewed output bytes changed")
    controller._check_accepted_files(workspace, plan, accepted, budget_attempts)
    require(attempt.get("effects", {}).get("status") in {"NOT_DECLARED", "PASS"},
            "unresolved implementation effects cannot be corrected by reinterpreting events")
    binding = {key: attempt[key] for key in
               ("prepared_event_id", "proposal_event_id", "attempt_id", "workpack_id", "job_id")}
    payload = {**binding, "command_id": command["command_id"], "policy": POLICY,
               "request": deepcopy(request), "result": result, "original_result": command["result"],
               "execution_started": False, "budget_reset": False, "old_output_accepted": False}
    entries = [{"event_type": EVENT, "payload": payload},
               {"event_type": "BUILD_VERIFICATION_INPUTS", "payload": {**binding, "artifacts": artifacts}},
               {"event_type": "BUILD_ATTEMPT_RECOVERED", "payload": {
                   **binding, "status": "IN_FLIGHT", "artifacts": artifacts, "verification": [],
                   "reassessment_pending": True, "budget_reset": False, "old_output_accepted": False,
                   "human_message_ref": human_message_ref}}]
    current, _, _ = controller._current(prepared_id)
    require(len(current) == len(events), "control state changed before reassessment")
    require(controller._artifacts(workspace, task["artifacts"]) == artifacts, "outputs changed during reassessment")
    require(capture_identity(command) == evidence["capture_files"], "capture changed before reassessment commit")
    return controller.store.append_batch(controller.program_id, entries, expected_revision=expected_revision,
        idempotency_key=idempotency_key, created_at=created_at, require_new=True)[0]


def apply_reassessment(controller, prepared, events, attempt, commands):
    """Overlay only a validated correction in memory; original rows stay intact."""
    rows = [row["payload"] for row in events if row["event_type"] == EVENT
            and row["payload"].get("attempt_id") == attempt["attempt_id"]]
    if not rows:
        return commands
    require(len(rows) == 1, "duplicate reassessment records")
    record = rows[0]
    evidence = record["request"]["evidence"]
    require(record["policy"] == POLICY and evidence["runtime_identity"] == runtime_identity(),
            "recovery observation policy changed")
    require(record["prepared_event_id"] == prepared["prepared_event_id"]
            and record["proposal_event_id"] == attempt["proposal_event_id"], "reassessment scope or original attempt changed")
    result = []
    for command in commands:
        if command["command_id"] == record["command_id"]:
            replay = replay_completed(command, evidence["capture_files"])
            require(replay == record["result"], "reassessment conclusion changed")
            result.append({**command, "result": replay})
        else:
            result.append(command)
    require(any(row["command_id"] == record["command_id"] for row in commands), "reassessed command missing")
    return result
