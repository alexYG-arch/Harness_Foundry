"""Bind approved local Workpack invocations to the durable control kernel.

The Parent owns the complete local plan. CLI requests select that plan; they
cannot supply a replacement executable, resource mapping, command or lease.
Native lease files are projections of reserved Grants, never bearer authority.
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping
from urllib.parse import urlsplit

from .control_kernel import ControlKernelError, DURABLE_DELIVERY_MODE, START_PACKAGE_BINDING_KIND, rebuild_control_projections
from .local_process import CodexSandboxRunner, LocalCommand, LocalProcessError
from .models import content_sha256
from .store import ControlEventStore


LOCAL_MODE = "LOCAL_OFFLINE_PROCESSES"
LOCAL_CLASS = "LOCAL_OFFLINE_PROCESS"
LOCAL_RESULT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["status", "reason_code", "artifact_id", "process_result", "job_lease"],
    "properties": {"status": {"type": "string"}, "reason_code": {"type": "string"},
                   "artifact_id": {"type": "string"}, "process_result": {"type": "object"},
                   "job_lease": {"type": "object"}},
}


def _require(condition, message, code="LOCAL_RUNTIME_BINDING_INVALID"):
    if not condition:
        raise ControlKernelError(code, message)


def _uri(ref):
    _require(isinstance(ref, str), "resource reference must be a string")
    value = urlsplit(ref)
    parts = value.path[1:].split("/") if value.path else []
    _require(value.scheme == "harness-resource" and value.netloc in {"candidate", "execution", "runtime-tools"}
             and not value.query and not value.fragment and "%" not in ref and "\\" not in ref
             and (not value.path or value.path.startswith("/"))
             and all(part not in {"", ".", ".."} for part in parts), "resource reference is not canonical")
    return value.netloc, tuple(parts)


def _covered(ref, roots):
    domain, parts = _uri(ref)
    return any(domain == other_domain and parts[:len(other_parts)] == other_parts
               for other_domain, other_parts in map(_uri, roots))


def _strings(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value) and len(value) == len(set(value))


def _offline_native(native):
    _require(isinstance(native, Mapping) and isinstance(native.get("command_id"), str)
             and not native["command_id"].endswith("CODEX-CODING")
             and native.get("executor_role") != "BUILD_PROGRAM_DRIVER",
             "code generation and Driver commands require their own transport")


def _selected_scope(native, job_id):
    contract = native.get("job_artifact_lease_contract")
    required = native.get("job_artifact_lease_required", False)
    _require(isinstance(required, bool), "native lease requirement must be boolean")
    if not required:
        _require(contract is None and job_id is None, "a Job selection requires its native lease contract")
        return None
    _require(isinstance(contract, Mapping) and isinstance(job_id, str), "native Job lease selection is missing")
    _require(contract.get("selection_cardinality") in {
        "EXACTLY_ONE_ACTIVE_JOB_LEASE_PER_INVOCATION",
        "EXACTLY_ONE_ACTIVE_JOB_LEASE_PER_CASE_PARTITION",
        "EXACTLY_ONE_ACTIVE_JOB_LEASE_PER_REGISTRY_READ_PARTITION",
    }, "unsupported native Job lease cardinality")
    matches = [item for item in contract.get("job_scope_bindings", [])
               if isinstance(item, Mapping) and item.get("job_id") == job_id]
    _require(len(matches) == 1, "exactly one native Job scope must be selected")
    selected = matches[0]
    _require(set(selected) == {"job_id", "allowed_read_roots", "allowed_write_roots",
                              "allowed_read_roots_sha256", "allowed_write_roots_sha256",
                              "scope_sha256", "lease_receipt_ref"}, "native Job scope fields differ")
    document = {key: selected.get(key) for key in ("job_id", "allowed_read_roots", "allowed_write_roots")}
    for field in ("allowed_read_roots", "allowed_write_roots"):
        _require(_strings(document[field]) and selected.get(field + "_sha256") == content_sha256(document[field]),
                 "native Job root binding is stale")
        _require(all(_uri(ref)[0] == "execution" and _uri(ref)[1][:2] == ("jobs", job_id)
                     for ref in document[field]), "native selected roots cross Job ownership")
    _require(selected.get("scope_sha256") == content_sha256(document), "native Job scope binding is stale")
    _uri(selected.get("lease_receipt_ref"))
    return selected


def _effective_roots(native, job_id, runtime_reads):
    selected = _selected_scope(native, job_id)
    _require(_strings(runtime_reads) and all(_uri(ref)[0] == "runtime-tools" for ref in runtime_reads),
             "runtime dependency reads must be explicitly declared tool resources")
    roots = {}
    for field in ("allowed_read_roots", "allowed_write_roots"):
        values = native.get(field, [])
        _require(_strings(values), "native shared roots must be a unique array")
        _require(not any(_uri(ref)[0] == "execution" and _uri(ref)[1][:1] == ("jobs",) for ref in values),
                 "Job roots must come from the selected lease, not the shared scope")
        values = [*values, *(selected[field] if selected else [])]
        if field == "allowed_read_roots":
            values += [*runtime_reads, *([selected["lease_receipt_ref"]] if selected else [])]
        for ref in values:
            domain, parts = _uri(ref)
            if domain == "execution" and parts[:1] == ("jobs",):
                _require(len(parts) > 1 and parts[1] == job_id,
                         "invocation crosses Job ownership", "LOCAL_JOB_SCOPE_EXPANSION")
            if field == "allowed_write_roots":
                _require(domain == "execution" and parts and parts[0] != ".harness-foundry",
                         "workload cannot write Candidate, tool or controller roots")
        roots[field] = sorted(set(values))
    return roots, selected


def bind_local_workpack_transition(transition, *, native_command, project_id, workpack_id,
                                   argv, cwd_ref, executable_sha256, runtime_read_refs=(),
                                   job_id=None, timeout_seconds=60):
    """Hydrate one native command without changing the Candidate or granting it.

    `transition` supplies the frozen decision/input/next-node contracts. The
    complete native command (including its lease schema) is retained, not
    reduced to an execution label. Code-generation/model commands use a separate
    transport; this receiver must never relabel them as offline Python jobs.
    """
    _offline_native(native_command)
    roots, _ = _effective_roots(native_command, job_id, list(runtime_read_refs))
    result = deepcopy(transition)
    result.update(roots)
    result["command_contract"] = {
        "command_class": LOCAL_CLASS, "delivery_mode": DURABLE_DELIVERY_MODE,
        "local_invocation": {"project_id": project_id, "workpack_id": workpack_id,
            "native_command": deepcopy(native_command), "job_id": job_id,
            "argv": deepcopy(argv), "cwd_ref": cwd_ref, "executable_sha256": executable_sha256,
            "runtime_read_refs": list(runtime_read_refs), "timeout_seconds": timeout_seconds},
    }
    result["result_schema"] = deepcopy(LOCAL_RESULT_SCHEMA)
    result["risk"].update(network_mode="DENY", secret_access=False)
    return result


def validate_local_execution(parent):
    """Validate the local plan structurally, without reading tools or paths."""
    plan = parent.get("local_execution")
    binding = parent.get("bindings", {})
    factory_bound = isinstance(binding, Mapping) and binding.get("binding_kind") == START_PACKAGE_BINDING_KIND
    fields = {
        "mode", "candidate_root", "execution_root", "control_db", "receiver", "runtime_resources", "transitions"
    } | ({"factory_source"} if factory_bound else set())
    _require(isinstance(plan, Mapping) and set(plan) == fields and plan.get("mode") == LOCAL_MODE,
             "Parent local execution plan is incomplete")
    if factory_bound:
        source = plan["factory_source"]
        _require(isinstance(source, Mapping) and set(source) == {"database_path", "runs_root"}
                 and all(isinstance(value, str) and Path(value).is_absolute() and ".." not in Path(value).parts
                         for value in source.values()), "Factory read locator must be part of the approved local plan")
    _require(_strings(parent.get("allowed_read_roots")) and parent.get("network_mode") == "DENY"
             and parent.get("secret_access") is False, "offline Parent needs explicit reads and no network/secrets")
    _require(isinstance(plan["receiver"], Mapping) and set(plan["receiver"]) == {"executable_abs", "executable_sha256"},
             "receiver must have an explicit executable binding")
    for value in (plan["candidate_root"], plan["execution_root"], plan["control_db"], plan["receiver"]["executable_abs"]):
        _require(isinstance(value, str) and Path(value).is_absolute() and ".." not in Path(value).parts,
                 "local plan paths must be absolute")
    _require(isinstance(plan["runtime_resources"], Mapping) and all(
        _uri(ref)[0] == "runtime-tools" and isinstance(path, str) and Path(path).is_absolute()
        and ".." not in Path(path).parts
        for ref, path in plan["runtime_resources"].items()), "runtime tool resources must be explicitly mapped")
    contracts = plan["transitions"]
    _require(isinstance(contracts, Mapping) and bool(contracts), "local transitions are missing")
    for transition_id, transition in contracts.items():
        _require(isinstance(transition, Mapping) and transition.get("transition_id") == transition_id,
                 "local transition identity differs")
        command = transition.get("command_contract", {})
        _require(command.get("command_class") == LOCAL_CLASS and command.get("delivery_mode") == DURABLE_DELIVERY_MODE
                 and transition.get("result_schema") == LOCAL_RESULT_SCHEMA, "local command delivery/result contract differs")
        invocation = command.get("local_invocation")
        _require(isinstance(invocation, Mapping) and set(invocation) == {
            "project_id", "workpack_id", "native_command", "job_id", "argv", "cwd_ref", "executable_sha256",
            "runtime_read_refs", "timeout_seconds"}, "local invocation is incomplete")
        native = invocation["native_command"]
        _offline_native(native)
        _require(all(isinstance(invocation[key], str) and invocation[key] for key in ("project_id", "workpack_id")),
                 "invocation project and Workpack identity are required")
        roots, selected = _effective_roots(native, invocation["job_id"], invocation["runtime_read_refs"])
        for field, values in roots.items():
            _require(transition.get(field) == values and all(_covered(ref, parent[field]) for ref in values),
                     "transition roots must equal its native selected scope within the Parent")
        if selected:
            properties = native["job_artifact_lease_contract"].get("receipt_schema", {}).get("properties", {})
            _require(properties.get("workpack_id", {}).get("const") == invocation["workpack_id"]
                     and properties.get("command_id", {}).get("const") == native["command_id"],
                     "native lease belongs to another Workpack/command")
            domain, lease_parts = _uri(selected["lease_receipt_ref"])
            _require(domain == "execution" and lease_parts[:2] == ("evidence", "job_artifact_leases"),
                     "native lease publication must use the controller evidence domain")
            _require(_covered(selected["lease_receipt_ref"], parent["allowed_write_roots"]),
                     "Parent must cover controller publication of the native lease receipt")
        _require(transition.get("risk", {}).get("network_mode") == "DENY"
                 and transition.get("risk", {}).get("secret_access") is False, "local risk must remain offline")
        _require(_covered(invocation["cwd_ref"], roots["allowed_read_roots"] + roots["allowed_write_roots"]),
                 "cwd exceeds the selected Job scope")
        _require(isinstance(invocation["argv"], list) and bool(invocation["argv"])
                 and all(isinstance(arg, str) or isinstance(arg, Mapping) and set(arg) == {"resource_ref"}
                         for arg in invocation["argv"]), "argv must contain literals or typed resource arguments")
        for arg in invocation["argv"]:
            if isinstance(arg, Mapping):
                _require(_covered(arg["resource_ref"], roots["allowed_read_roots"] + roots["allowed_write_roots"]),
                         "argument resource exceeds the selected Job scope")
        _require(isinstance(invocation["argv"][0], Mapping), "executable must use a bound resource reference")
        _require(isinstance(invocation["timeout_seconds"], (int, float)) and not isinstance(invocation["timeout_seconds"], bool)
                 and 0 < invocation["timeout_seconds"] <= 86400, "invalid local timeout")
        for digest in (invocation["executable_sha256"], plan["receiver"]["executable_sha256"]):
            _require(isinstance(digest, str) and len(digest) == 64
                     and all(char in "0123456789abcdef" for char in digest), "executable byte binding is missing")
    return plan


def _resolve(plan, ref):
    domain, parts = _uri(ref)
    if domain in {"candidate", "execution"}:
        root = Path(plan[domain + "_root"])
        _require(root.is_dir() and root.resolve() == root, "runtime root is absent or linked")
        path = root.joinpath(*parts)
        _require(path.resolve().is_relative_to(root) and path.resolve() == path,
                 "resource crosses a linked path outside its bound location")
        return path
    matches = [(key, value) for key, value in plan["runtime_resources"].items() if _covered(ref, [key])]
    _require(bool(matches), "tool resource has no approved binding")
    key, value = max(matches, key=lambda item: len(_uri(item[0])[1]))
    path = Path(value).joinpath(*parts[len(_uri(key)[1]):])
    resolved = path.resolve()
    for root in (Path(plan["candidate_root"]), Path(plan["execution_root"])):
        _require(not resolved.is_relative_to(root) and not root.is_relative_to(resolved),
                 "tool alias cannot reopen a Candidate or execution resource domain")
    return path


def _file_digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _publish_lease(path, lease):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".lease-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(lease, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class LocalRuntimeAdapter:
    """Dispatch only the current approved plan's durably reserved invocation."""

    def __init__(self, store, program_id, parent_id):
        self.store, self.program_id, self.parent_id = store, program_id, parent_id

    def __call__(self, context):
        events = self.store.list_events(self.program_id)
        projections = rebuild_control_projections(events)
        parent = projections["grant_ledger"]["parents"].get(self.parent_id, {})
        _require(parent.get("status") in {"GRANTED", "ACTIVE"} and parent.get("approval_receipt_sha256"),
                 "local Parent is not currently approved", "PARENT_AUTHORIZATION_NOT_ACTIVE")
        plan = validate_local_execution(parent)
        transition = plan["transitions"].get(context["transition_id"])
        grant = projections["grant_ledger"]["derived_grants"].get(context["idempotency_key"], {})
        _require(grant.get("status") == "ISSUED" and grant.get("parent_authorization_id") == self.parent_id
                 and grant.get("transition_contract_sha256") == content_sha256(transition)
                 and grant == context["grant"], "local invocation has no current reserved Grant")
        issued = [event for event in events if event["event_type"] == "TRANSITION_ATTEMPT_STARTED"
                  and event["payload"].get("grant_id") == grant["grant_id"]]
        _require(len(issued) == 1, "local dispatch needs exactly one persisted attempt")
        now = datetime.now(timezone.utc)
        expires = datetime.fromisoformat(parent["expires_at"].replace("Z", "+00:00"))
        _require(now < expires, "local Parent expired before process dispatch", "PARENT_AUTHORIZATION_EXPIRED")
        invocation = transition["command_contract"]["local_invocation"]
        roots, selected = _effective_roots(invocation["native_command"], invocation["job_id"], invocation["runtime_read_refs"])
        lease = {}
        result = {"status": "VALIDATION_FAILED", "reason_code": "LOCAL_PROCESS_PREFLIGHT_FAILED",
                  "artifact_id": f"process-result://{self.program_id}/{context['attempt_id']}",
                  "process_result": {}, "job_lease": lease}
        try:
            reads = [_resolve(plan, ref) for ref in roots["allowed_read_roots"]]
            writes = [_resolve(plan, ref) for ref in roots["allowed_write_roots"]]
            argv = [str(_resolve(plan, arg["resource_ref"])) if isinstance(arg, Mapping) else arg
                    for arg in invocation["argv"]]
            cwd = _resolve(plan, invocation["cwd_ref"])
            receiver = plan["receiver"]
            _require(_file_digest(receiver["executable_abs"]) == receiver["executable_sha256"]
                     and _file_digest(argv[0]) == invocation["executable_sha256"], "executable bytes changed")
            for path in writes:
                if not path.is_file():
                    path.mkdir(parents=True, exist_ok=True)
            if selected:
                lease.update({**selected, "lease_id": grant["grant_id"], "program_id": self.program_id,
                    "project_id": invocation["project_id"], "workpack_id": invocation["workpack_id"],
                    "command_id": invocation["native_command"]["command_id"], "holder_id": context["attempt_id"],
                    "fencing_token": grant["fencing_token"], "issued_at": issued[0]["created_at"],
                    "expires_at": parent["expires_at"], "lease_state_sha256": grant["input_state_sha256"],
                    "consumed": False, "status": "ACTIVE"})
                _publish_lease(_resolve(plan, lease["lease_receipt_ref"]), lease)
            command = LocalCommand.prepare(argv=argv, cwd=cwd, read_roots=reads, write_roots=writes,
                                           timeout_seconds=invocation["timeout_seconds"])
        except (OSError, LocalProcessError, ControlKernelError) as exc:
            result["process_result"] = {"workload_started": False, "diagnostic": str(exc)}
            return result
        try:
            observed = CodexSandboxRunner(receiver["executable_abs"]).run(command)
            result.update(status=observed["status"], reason_code=observed["reason_code"], process_result=observed)
        except (OSError, LocalProcessError) as exc:
            # Receiver errors after dispatch can follow partial command effects.
            # Do not report them as a proven pre-effect failure or retry them.
            result.update(status="UNKNOWN_SIDE_EFFECT", reason_code="LOCAL_RECEIVER_OUTCOME_UNRESOLVED",
                          process_result={"workload_started": None, "diagnostic": str(exc)})
        return result


def prepare_local_runtime(control_db, program_id, parent_id, contracts):
    """Read-only binding check before opening the existing controller for writes."""
    store = ControlEventStore(control_db, read_only=True)
    parent = rebuild_control_projections(store.list_events(program_id))["grant_ledger"]["parents"].get(parent_id, {})
    _require(parent.get("status") in {"ACTIVE", "GRANTED"} and parent.get("approval_receipt_sha256"),
             "production local mode requires an already approved Parent", "PARENT_AUTHORIZATION_NOT_ACTIVE")
    plan = validate_local_execution(parent)
    _require(Path(plan["control_db"]) == Path(control_db).resolve(), "local control store differs from approved plan")
    candidate, execution = Path(plan["candidate_root"]), Path(plan["execution_root"])
    _require(candidate.is_dir() and execution.is_dir() and candidate.resolve() == candidate and execution.resolve() == execution
             and not candidate.is_relative_to(execution) and not execution.is_relative_to(candidate),
             "local Candidate and execution roots must already exist and be disjoint")
    _require(Path(control_db).resolve().is_relative_to(execution / ".harness-foundry"),
             "control database must remain in the execution controller domain")
    _require(not any((execution / ".harness-foundry/control" / name).exists()
                     for name in ("PROGRAM_CONTROL_EVENTS.jsonl", "PROGRAM_CONTROL_STATE.json")),
             "legacy controller must be migrated, not dual-written", "LOCAL_LEGACY_CONTROLLER_PRESENT")
    _require(isinstance(contracts, Mapping) and bool(contracts)
             and all(plan["transitions"].get(key) == value for key, value in contracts.items()),
             "requested transitions differ from the approved local plan")
    return LocalRuntimeAdapter(ControlEventStore(control_db), program_id, parent_id)
