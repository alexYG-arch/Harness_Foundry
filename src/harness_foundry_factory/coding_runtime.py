"""Audited coding command stages on the existing SQLite stream.

This adapter does not accept Workpacks. The first post-startup coding task can
run; later tasks need the independent Workpack acceptance provider before their
predecessor capabilities can be satisfied. No synthetic PASS is substituted.
"""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from collections.abc import Mapping

from .coding_process import CodingCommand, CodexCodingRunner, client_state_root
from .coding_protocol import plan_coding_command
from .control_kernel import ControlKernelError, DURABLE_DELIVERY_MODE, START_PACKAGE_BINDING_KIND, rebuild_control_projections
from .local_process import LocalCommand, LocalProcessError
from .local_runtime import _covered, _effective_roots, _file_digest, _publish_lease, _resolve, _strings, _uri
from .models import content_sha256
from .startup_runtime import CONTROL_DB_REF, project_startup_views, verify_startup_views
from .store import ControlEventStore
from .workpack_runtime import RuntimeContractError


CODING_MODE = "CODEX_CODING_SERVICE"
CODING_CLASS = "CODEX_CODING_MODEL_TURN"
CODING_RESULT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["status", "reason_code", "artifact_id", "model_result", "job_lease", "workpack_accepted"],
    "properties": {"status": {"type": "string"}, "reason_code": {"type": "string"},
                   "artifact_id": {"type": "string"}, "model_result": {"type": "object"},
                   "job_lease": {"type": "object"}, "workpack_accepted": {"type": "boolean", "enum": [False]}},
}


def _require(condition, message, code="CODING_RUNTIME_BINDING_INVALID"):
    if not condition:
        raise ControlKernelError(code, message)


def bind_coding_transition(transition, coding_plan, *, runtime_read_refs=(), timeout_seconds=1800):
    task = deepcopy(coding_plan["task_input"])
    roots, _ = _effective_roots(task["native_command"], task["selection"]["job_id"], list(runtime_read_refs))
    result = deepcopy(transition)
    result.update(roots)
    result.update(command_contract={"command_class": CODING_CLASS, "delivery_mode": DURABLE_DELIVERY_MODE,
        "coding_invocation": {"task_input": task, "runtime_read_refs": list(runtime_read_refs),
                              "timeout_seconds": timeout_seconds}}, result_schema=deepcopy(CODING_RESULT_SCHEMA))
    result["risk"].update(network_mode="DECLARED_WRITE", secret_access=True, external_effect_class="EXTERNAL_REVERSIBLE")
    result["risk"]["permissions"] = sorted(set(result["risk"]["permissions"]) | {"USE_CODEX_CLIENT_SERVICE_AND_SAVED_AUTH"})
    # Completion of this stage is not a capability receipt for the next
    # Workpack. The unimplemented acceptance provider must not be skipped.
    result.update(next_transition_id=None, stop_gate=None, retry_policy={"max_retries": 0})
    return result


def validate_coding_execution(parent):
    plan = parent.get("coding_execution")
    _require(isinstance(plan, Mapping) and set(plan) == {
        "mode", "candidate_root", "execution_root", "control_db", "factory_source", "receiver",
        "runtime_resources", "transitions", "client_state_root", "model", "output_limit_bytes"}
        and plan["mode"] == CODING_MODE, "complete coding plan is required")
    _require(parent.get("bindings", {}).get("binding_kind") == START_PACKAGE_BINDING_KIND,
             "coding requires the audited live Factory binding")
    _require("local_execution" not in parent and "startup_execution" not in parent,
             "service access uses its own Parent; offline Parents are not widened")
    _require(parent.get("network_mode") == "DECLARED_WRITE" and parent.get("secret_access") is True
             and parent.get("external_effect_class") == "EXTERNAL_REVERSIBLE"
             and "USE_CODEX_CLIENT_SERVICE_AND_SAVED_AUTH" in parent.get("permissions", [])
             and _strings(parent.get("allowed_read_roots")), "model/client effects must be explicit in the Parent")
    receiver = plan["receiver"]
    _require(isinstance(receiver, Mapping) and set(receiver) == {"executable_abs", "executable_sha256"},
             "bind the actual client executable")
    source = plan["factory_source"]
    _require(isinstance(source, Mapping) and set(source) == {"database_path", "runs_root"}, "Factory locator is missing")
    for value in [plan[key] for key in ("candidate_root", "execution_root", "control_db", "client_state_root")
                  ] + [receiver["executable_abs"], *source.values()]:
        _require(isinstance(value, str) and Path(value).is_absolute() and ".." not in Path(value).parts,
                 "coding paths must be explicit absolute bindings")
    _require(Path(plan["client_state_root"]) == client_state_root(), "only the existing OS-user client state is supported")
    _require(plan["model"] is None or isinstance(plan["model"], str) and bool(plan["model"]), "invalid model binding")
    _require(type(plan["output_limit_bytes"]) is int and 1 <= plan["output_limit_bytes"] <= 16 * 1024 * 1024,
             "capture limit must be explicit and at most 16 MiB per stream")
    digest = receiver["executable_sha256"]
    _require(isinstance(digest, str) and len(digest) == 64 and all(char in "0123456789abcdef" for char in digest),
             "client executable byte binding is missing")
    _require(isinstance(plan["runtime_resources"], Mapping) and all(
        _uri(ref)[0] == "runtime-tools" and isinstance(path, str) and Path(path).is_absolute()
        and ".." not in Path(path).parts for ref, path in plan["runtime_resources"].items()), "invalid runtime tool resources")
    _require(isinstance(plan["transitions"], Mapping) and bool(plan["transitions"]), "coding transitions are missing")
    for key, transition in plan["transitions"].items():
        _require(isinstance(transition, Mapping) and transition.get("transition_id") == key,
                 "coding transition identity differs")
        command = transition.get("command_contract", {})
        _require(command.get("command_class") == CODING_CLASS and command.get("delivery_mode") == DURABLE_DELIVERY_MODE
                 and transition.get("result_schema") == CODING_RESULT_SCHEMA
                 and transition.get("next_transition_id") is None and transition.get("stop_gate") is None
                 and transition.get("retry_policy") == {"max_retries": 0}, "coding stage cannot skip acceptance or retry")
        invocation = command.get("coding_invocation", {})
        _require(isinstance(invocation, Mapping) and set(invocation) == {"task_input", "runtime_read_refs", "timeout_seconds"},
                 "coding invocation is incomplete")
        task = invocation["task_input"]
        _require(isinstance(task, Mapping) and isinstance(task.get("selection"), Mapping), "coding task is missing")
        selection, native = task["selection"], task.get("native_command", {})
        _require(selection.get("program_id") == parent["program_id"]
                 and selection.get("candidate_tree_sha256") == parent["bindings"]["candidate_tree_sha256"]
                 and native.get("executor_role") == "CODEX_CODING_AGENT"
                 and native.get("command_id") == selection.get("command_id"), "native coding task identity differs")
        roots, selected = _effective_roots(native, selection.get("job_id"), invocation["runtime_read_refs"])
        for field, values in roots.items():
            _require(transition.get(field) == values and all(_covered(ref, parent[field]) for ref in values),
                     "coding roots differ from the native selected scope or exceed Parent")
        if selected:
            schema = native["job_artifact_lease_contract"].get("receipt_schema", {}).get("properties", {})
            _require(schema.get("workpack_id", {}).get("const") == selection["workpack_id"]
                     and schema.get("command_id", {}).get("const") == selection["command_id"]
                     and _uri(selected["lease_receipt_ref"])[:1] == ("execution",)
                     and _uri(selected["lease_receipt_ref"])[1][:2] == ("evidence", "job_artifact_leases")
                     and _covered(selected["lease_receipt_ref"], parent["allowed_write_roots"]), "invalid coding Job lease owner/publication")
        _require(type(invocation["timeout_seconds"]) in {int, float} and 0 < invocation["timeout_seconds"] <= 86400,
                 "invalid coding timeout")
        risk = transition.get("risk", {})
        _require(risk.get("network_mode") == "DECLARED_WRITE" and risk.get("secret_access") is True
                 and risk.get("external_effect_class") == "EXTERNAL_REVERSIBLE"
                 and "USE_CODEX_CLIENT_SERVICE_AND_SAVED_AUTH" in risk.get("permissions", []), "coding risk was relabeled as offline")
    return plan


def _fresh_task(plan, invocation):
    selected = invocation["task_input"]["selection"]
    _require(all(isinstance(selected.get(key), str) and selected[key]
                 for key in ("node_id", "workpack_id", "command_id")) and "job_id" in selected,
             "coding task selection is incomplete")
    try:
        task = plan_coding_command(Path(plan["candidate_root"]), selected["node_id"], selected["workpack_id"],
                                   selected["command_id"], job_id=selected["job_id"])
    except RuntimeContractError as exc:
        raise ControlKernelError(exc.code, str(exc)) from exc
    _require(task["task_input"] == invocation["task_input"], "coding task changed since Parent approval")
    return task


def _predecessors(store, parent, task):
    plan = parent["coding_execution"]
    verify_startup_views(store, parent["program_id"], plan["execution_root"], parent["bindings"])
    rows = project_startup_views(store, parent["program_id"], plan["execution_root"])
    data = task["task_input"]
    _require(not data["required_prior_workpacks"] and not data["required_prior_commands"]
             and data["required_predecessor_nodes"] == [rows[-1]["transition_id"]]
             and rows[-1]["result"]["native_transaction"]["next_state_payload"]["next_node"] == data["selection"]["node_id"],
             "later coding tasks need independent Workpack acceptance, which is not implemented",
             "CODING_PREDECESSOR_ACCEPTANCE_REQUIRED")


class CodingRuntimeAdapter:
    def __init__(self, store, program_id, parent_id, binding_verifier):
        self.store, self.program_id, self.parent_id = store, program_id, parent_id
        self.binding_verifier = binding_verifier

    def _current(self, context):
        events = self.store.list_events(self.program_id)
        projections = rebuild_control_projections(events)
        parent = projections["grant_ledger"]["parents"].get(self.parent_id, {})
        _require(parent.get("status") in {"ACTIVE", "GRANTED"} and parent.get("approval_receipt_sha256"), "coding Parent is not active")
        plan = validate_coding_execution(parent)
        transition = plan["transitions"].get(context["transition_id"])
        grant = projections["grant_ledger"]["derived_grants"].get(context["idempotency_key"], {})
        _require(grant.get("status") == "ISSUED" and grant.get("parent_authorization_id") == self.parent_id
                 and grant.get("transition_contract_sha256") == content_sha256(transition) and grant == context["grant"],
                 "coding needs the current reserved Grant")
        _require(datetime.now(timezone.utc) < datetime.fromisoformat(parent["expires_at"].replace("Z", "+00:00")),
                 "coding Parent expired", "PARENT_AUTHORIZATION_EXPIRED")
        issued = [event for event in events if event["event_type"] == "TRANSITION_ATTEMPT_STARTED"
                  and event["payload"].get("grant_id") == grant["grant_id"]]
        _require(len(issued) == 1, "coding requires one persisted attempt")
        invocation = transition["command_contract"]["coding_invocation"]
        task = _fresh_task(plan, invocation)
        _predecessors(self.store, parent, task)
        return parent, plan, invocation, task, grant, issued[0]["created_at"]

    def __call__(self, context):
        parent, plan, invocation, task, grant, issued = self._current(context)
        selected = task["task_input"]["selection"]
        native = task["task_input"]["native_command"]
        roots, job = _effective_roots(native, selected["job_id"], invocation["runtime_read_refs"])
        result = {"status": "VALIDATION_FAILED", "reason_code": "CODING_PREFLIGHT_FAILED",
                  "artifact_id": f"coding-result://{self.program_id}/{context['attempt_id']}",
                  "model_result": {}, "job_lease": {}, "workpack_accepted": False}
        try:
            receiver = plan["receiver"]
            _require(_file_digest(receiver["executable_abs"]) == receiver["executable_sha256"], "coding executable changed")
            reads = [_resolve(plan, ref) for ref in roots["allowed_read_roots"]]
            writes = [_resolve(plan, ref) for ref in roots["allowed_write_roots"]]
            cwd_ref = native.get("cwd_absolute", native.get("cwd_abs"))
            _require(_covered(cwd_ref, roots["allowed_read_roots"] + roots["allowed_write_roots"]), "coding cwd exceeds native scope")
            for path in writes:
                if not path.is_file():
                    path.mkdir(parents=True, exist_ok=True)
            if job:
                lease = {**job, "lease_id": grant["grant_id"], "program_id": self.program_id,
                    "project_id": selected["project_id"], "workpack_id": selected["workpack_id"],
                    "command_id": selected["command_id"], "holder_id": context["attempt_id"],
                    "fencing_token": grant["fencing_token"], "issued_at": issued, "expires_at": parent["expires_at"],
                    "lease_state_sha256": grant["input_state_sha256"], "consumed": False, "status": "ACTIVE"}
                _publish_lease(_resolve(plan, job["lease_receipt_ref"]), lease)
                result["job_lease"] = lease
            scope = LocalCommand.prepare(argv=[receiver["executable_abs"]], cwd=_resolve(plan, cwd_ref),
                read_roots=reads, write_roots=writes, timeout_seconds=invocation["timeout_seconds"])
            # Keep portable Candidate task bytes intact. Supply only the
            # hydrated scope the host just resolved, not Factory/auth paths or
            # an implicit grant to the entire execution tree.
            runtime_context = {
                "cwd": str(scope.cwd), "job_id": selected["job_id"],
                "allowed_read_bindings": dict(zip(roots["allowed_read_roots"], map(str, reads))),
                "allowed_write_bindings": dict(zip(roots["allowed_write_roots"], map(str, writes))),
            }
            prompt = task["stdin_prompt"] + (
                "\nHOST_RUNTIME_BINDINGS\nResolve a logical resource by its longest matching bound prefix below, "
                "appending only its relative suffix. These are the resolved paths within the approved scope, "
                "not additional authority. Preserve logical references inside portable artifacts.\n"
                + json.dumps(runtime_context, ensure_ascii=False, sort_keys=True))
            command = CodingCommand(scope, prompt, plan["model"])
            command.validate()
        except (OSError, LocalProcessError, ControlKernelError) as exc:
            result["model_result"] = {"model_process_started": False, "diagnostic": str(exc)}
            return result

        def before_dispatch():
            current, current_plan, *_ = self._current(context)
            self.binding_verifier(current)
            _require(_file_digest(current_plan["receiver"]["executable_abs"]) == receiver["executable_sha256"], "client bytes changed")

        try:
            observed = CodexCodingRunner(receiver["executable_abs"], output_limit_bytes=plan["output_limit_bytes"]).run(
                command, before_dispatch=before_dispatch)
            status = {"MODEL_TURN_COMPLETED": "PASS", "MODEL_PROCESS_FAILED": "VALIDATION_FAILED"}.get(observed["status"], observed["status"])
            result.update(status=status, reason_code=observed["reason_code"], model_result=observed)
        except (OSError, LocalProcessError, ControlKernelError) as exc:
            result.update(status="UNKNOWN_SIDE_EFFECT", reason_code="CODING_OUTCOME_UNRESOLVED",
                          model_result={"model_process_started": None, "diagnostic": str(exc)})
        return result


def prepare_coding_runtime(control_db, program_id, parent_id, contracts, *, binding_verifier):
    _require(callable(binding_verifier), "coding requires a live host binding verifier")
    store = ControlEventStore(control_db, read_only=True)
    parent = rebuild_control_projections(store.list_events(program_id))["grant_ledger"]["parents"].get(parent_id, {})
    _require(parent.get("status") in {"ACTIVE", "GRANTED"} and parent.get("approval_receipt_sha256"),
             "coding requires an already approved Parent", "PARENT_AUTHORIZATION_NOT_ACTIVE")
    plan = validate_coding_execution(parent)
    _require(Path(plan["control_db"]) == Path(control_db).resolve() == Path(plan["execution_root"]) / CONTROL_DB_REF,
             "coding must use the approved canonical controller")
    _require(isinstance(contracts, Mapping) and bool(contracts)
             and all(plan["transitions"].get(key) == value for key, value in contracts.items()), "requested coding plan differs")
    for transition in contracts.values():
        task = _fresh_task(plan, transition["command_contract"]["coding_invocation"])
        _predecessors(store, parent, task)
    return CodingRuntimeAdapter(ControlEventStore(control_db), program_id, parent_id, binding_verifier)
