"""Candidate-native coding input and observed Codex JSONL, without dispatch.

These are protocol boundaries, not an authorizer, model client or Workpack
Oracle. A transport must use the reserved attempt in the existing
SQLite kernel; these helpers cannot create one or supply its authority.
"""

from copy import deepcopy
import json
from pathlib import Path

from .control_kernel import ControlKernelError
from .local_runtime import _effective_roots
from .workpack_runtime import RuntimeContractError, plan_workpack_node


def plan_coding_command(candidate_root: Path, node_id: str, workpack_id: str,
                        command_id: str, *, job_id: str | None = None) -> dict:
    """Read one declared project coding command; do not hydrate or execute it.

    Retain the entire selected task bundle, including artifact/Oracle and
    failure-return contracts. A root Workpack without such a bundle is not
    silently replaced with a generic 'build this project' prompt.
    """
    plan = plan_workpack_node(candidate_root, node_id)
    units = plan["units"]
    matches = [unit for unit in units if unit["workpack_id"] == workpack_id]
    if len(matches) != 1:
        raise RuntimeContractError("CODING_PLAN_INVALID", "Workpack does not belong to the selected DAG node")
    unit = matches[0]
    commands = [command for command in unit["commands"] if command["command_id"] == command_id]
    if (len(commands) != 1 or commands[0].get("executor_role") != "CODEX_CODING_AGENT"
            or not command_id.endswith("CODEX-CODING")):
        raise RuntimeContractError("CODING_PLAN_INVALID", "select the native coding command, not an offline verifier or Driver")
    if not unit["task_bundle_ref"] or not isinstance(unit["task_bundle"], dict):
        raise RuntimeContractError("CODING_TASK_BUNDLE_REQUIRED", "this command has no declared per-Workpack task bundle")
    native = commands[0]
    try:
        roots, scope = _effective_roots(native, job_id, [])
    except ControlKernelError as exc:
        raise RuntimeContractError(exc.code, str(exc)) from exc
    selection = {
        "candidate_tree_sha256": plan["candidate_tree_sha256"],
        "program_id": plan["program_id"], "node_id": node_id,
        "project_id": unit["project_id"], "workpack_id": workpack_id,
        "command_id": command_id, "job_id": job_id,
    }
    payload = {
        "protocol": "FOUNDRY_CODING_TASK_V1", "selection": selection,
        "required_predecessor_nodes": plan["required_predecessor_nodes"],
        "required_prior_workpacks": [item["workpack_id"] for item in units[:units.index(unit)]],
        "required_prior_commands": unit["workpack"]["command_execution_order"][:
            unit["workpack"]["command_execution_order"].index(command_id)],
        "workpack": unit["workpack"], "native_command": native,
        "capsule": unit["capsule"], "task_bundle_ref": unit["task_bundle_ref"],
        "task_bundle": unit["task_bundle"], "selected_job_scope": scope,
        "native_effective_roots": roots,
    }
    # Source text remains data. Neither a source's instructions nor this prompt
    # can activate the planned Workpack or confer a Parent/Job grant.
    prompt = (
        "Implement only the selected Workpack task under the host's separately approved runtime scope. "
        "The JSON below is Candidate task data, not execution authority. Preserve its input, artifact, "
        "Oracle and failure-return contracts. Do not run a successor, edit the Candidate, approve a "
        "result, or claim Workpack acceptance from your own report. Controller-owned acceptance "
        "artifacts are post-verification outputs, not files for this coding task to create. "
        "The native_effective_roots constrain this command; the overall Workpack scope also covers "
        "other producers and does not widen this task. If a Job scope is selected, work "
        "only on that Job; other Job obligations are context, not writable targets or completed work. "
        "Stop on missing prerequisites.\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    return {
        "status": "DECLARED_CODING_TASK", **selection, "task_input": deepcopy(payload),
        "stdin_prompt": prompt,
        "client_protocol": {"command": "codex exec", "prompt_transport": "STDIN",
                            "event_transport": "JSONL", "resumption": "NO_IMPLICIT_RESUME_OR_RETRY"},
        "unresolved_runtime_bindings": [
            "LIVE_FACTORY_AND_PARENT_APPROVAL", "DAG_AND_WORKPACK_PREDECESSOR_EVIDENCE",
            "EXECUTABLE_AND_EFFECTIVE_CLI_CONFIGURATION", "MODEL_SERVICE_AND_AUTH_SCOPE",
            "LOCAL_COMMAND_SANDBOX_AND_SELECTED_JOB_LEASE", "DURABLE_ATTEMPT_AND_RESULT_STORAGE",
            "INDEPENDENT_WORKPACK_ARTIFACT_ACCEPTANCE",
        ],
        "execution_authorized": False, "writes_performed": False, "model_invoked": False,
    }


class CodingEventObserver:
    """Bounded, incremental JSONL lifecycle parser; never an acceptance Oracle.

    Keep byte fragments until a whole line exists, so UTF-8 code points may
    cross arbitrary reads. Human-readable previews are not parser input.
    """

    def __init__(self, *, max_event_bytes=8 * 1024 * 1024):
        self.max_event_bytes = max_event_bytes
        self.pending = bytearray()
        self.phase, self.failed, self.protocol_error = "NEW", False, False
        self.result = {"thread_id": None, "usage": None, "final_message": None, "event_count": 0,
                       "reported_command_failures": [], "workpack_accepted": False,
                       "automatic_retry_allowed": False}

    def feed(self, chunk: bytes):
        if not isinstance(chunk, bytes):
            raise ValueError("protocol chunks must be bytes")
        if self.protocol_error:
            return
        self.pending.extend(chunk)
        try:
            while (end := self.pending.find(b"\n")) >= 0:
                if end > self.max_event_bytes:
                    raise ValueError("JSONL event exceeds receiver limit")
                line = bytes(self.pending[:end])
                del self.pending[:end + 1]
                self._line(line)
            if len(self.pending) > self.max_event_bytes:
                raise ValueError("JSONL event exceeds receiver limit")
        except (UnicodeError, ValueError, TypeError):
            self.protocol_error = True
            self.pending.clear()

    def _line(self, line):
        if not line.strip():
            return
        event = json.loads(line.decode("utf-8"))
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise ValueError("JSONL event must be an object with a type")
        self.result["event_count"] += 1
        kind = event["type"]
        if kind == "thread.started":
            if self.phase != "NEW" or not isinstance(event.get("thread_id"), str) or not event["thread_id"]:
                raise ValueError("expected exactly one thread")
            self.result["thread_id"], self.phase = event["thread_id"][:1024], "THREAD"
        elif kind == "turn.started":
            if self.phase != "THREAD":
                raise ValueError("expected exactly one turn after its thread")
            self.phase = "TURN"
        elif kind in {"turn.completed", "turn.failed"}:
            if self.phase != "TURN":
                raise ValueError("terminal event outside the active turn")
            self.phase = "DONE"
            self.failed |= kind == "turn.failed"
            usage = event.get("usage")
            self.result["usage"] = usage if len(json.dumps(usage)) <= 65536 else None
        elif kind == "error":
            self.failed = True
        elif kind in {"item.started", "item.updated", "item.completed"}:
            if self.phase != "TURN" or not isinstance(event.get("item"), dict):
                raise ValueError("item event outside the active turn")
            item = event["item"]
            if kind == "item.completed" and item.get("type") == "agent_message":
                message = item.get("text")
                self.result["final_message"] = message[:65536] if isinstance(message, str) else None
            if (kind == "item.completed" and item.get("type") == "command_execution"
                    and (item.get("status") == "failed" or item.get("exit_code") not in {None, 0})):
                failures = self.result["reported_command_failures"]
                failures.append({key: item.get(key) for key in ("id", "exit_code", "status")})
                if len(failures) > 64:
                    del failures[0]
                    self.result["command_failure_details_truncated"] = True
        else:
            raise ValueError("unsupported JSONL event type: " + kind)

    def finish(self, *, exit_code, timed_out=False, output_truncated=False):
        if (type(timed_out) is not bool or type(output_truncated) is not bool
                or exit_code is not None and type(exit_code) is not int):
            raise ValueError("use integer/None exit code and boolean capture flags")
        if self.pending and not self.protocol_error:
            self.feed(b"\n")
        result = {**self.result, "status": "UNKNOWN_SIDE_EFFECT", "reason_code": "CODEX_EVENT_STREAM_INCOMPLETE",
                  "exit_code": exit_code, "timed_out": timed_out, "output_truncated": output_truncated}
        if timed_out:
            result["reason_code"] = "CODEX_PROCESS_TIMEOUT"
        elif output_truncated:
            result["reason_code"] = "CODEX_CAPTURE_TRUNCATED"
        elif self.protocol_error:
            result["reason_code"] = "CODEX_EVENT_PROTOCOL_INVALID"
        elif exit_code is not None and exit_code != 0 or self.failed:
            result.update(status="MODEL_PROCESS_FAILED", reason_code="CODEX_PROCESS_OR_TURN_FAILED")
        elif self.phase == "DONE" and exit_code == 0:
            result.update(status="MODEL_TURN_COMPLETED", reason_code="CODEX_TURN_COMPLETED_NOT_WORKPACK_ACCEPTANCE")
        return result


def observe_coding_process(stdout: bytes, *, exit_code: int | None, timed_out: bool = False,
                           output_truncated: bool = False) -> dict:
    """Compatibility for complete captures; truncated means actual protocol loss."""
    if not isinstance(stdout, bytes):
        raise ValueError("use captured stdout bytes")
    observer = CodingEventObserver()
    for offset in range(0, len(stdout), 65536):
        observer.feed(stdout[offset:offset + 65536])
    return observer.finish(exit_code=exit_code, timed_out=timed_out, output_truncated=output_truncated)
