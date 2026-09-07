"""Candidate-native startup actions committed by the existing SQLite kernel.

Native files are reconstructible compatibility views, never a second control
authority. This route verifies registration and read-only Driver probes only.
It neither starts a Driver loop nor executes a project Workpack.
"""

from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess

from .control_kernel import (ControlKernelError, DURABLE_DELIVERY_MODE, START_PACKAGE_BINDING_KIND,
                             evaluator_implementation_sha256, rebuild_control_projections)
from .models import content_sha256
from .store import ControlEventStore


STARTUP_MODE = "START_PACKAGE_SQLITE_REGISTRATION"
STARTUP_CLASS = "CANDIDATE_NATIVE_REGISTRATION"
STARTUP_NODES = ("SHARED_CONTROL_BASELINE_LOCK", "CONTROL_PLANE_REGISTRATION", "PROGRAM_DRIVER_RUNTIME_VERIFIED")
CONTROL_DB_REF = ".harness-foundry/control.sqlite3"
STATE_REF = ".harness-foundry/control/PROGRAM_CONTROL_STATE.json"
EVENTS_REF = ".harness-foundry/control/PROGRAM_CONTROL_EVENTS.jsonl"
CONTROL_ROOT = "harness-resource://execution/.harness-foundry/control"
EVIDENCE_ROOT = "harness-resource://execution/evidence/engineering_dag/"
MODULES = dict(zip(STARTUP_NODES, ("shared_control_baseline", "control_plane_registration",
                                  "program_driver_runtime_verification")))
RESULT_SCHEMA = {"type": "object", "additionalProperties": False,
                 "required": ["status", "artifact_id", "native_transaction"], "properties": {
                     "status": {"type": "string", "enum": ["PASS", "VALIDATION_FAILED", "UNKNOWN_SIDE_EFFECT"]},
                     "reason_code": {"type": "string"}, "artifact_id": {"type": "string"},
                     "native_transaction": {"type": "object"}}}


def _require(condition, message, code="STARTUP_RUNTIME_INVALID"):
    if not condition:
        raise ControlKernelError(code, message)


def _action(candidate, node):
    # Candidate identity and the live approval are verified by the host before
    # dispatch. This is the declared packaged implementation, not a model hook.
    sys.dont_write_bytecode = True
    path = candidate / "tools" / (MODULES[node] + ".py")
    spec = importlib.util.spec_from_file_location("startup_" + MODULES[node], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _require(callable(getattr(module, "prepare_action", None)), "Candidate lacks read-only action preparation")
    module.validate_static_contract(candidate)
    return module


def startup_transitions(candidate_root, bindings):
    """Derive the three declared startup nodes; creates no execution artifacts."""
    candidate = Path(candidate_root)
    dag = json.loads((candidate / "ENGINEERING_PROJECT_DAG.json").read_text())
    nodes = {node["node_id"]: node for node in dag["nodes"]}
    policy = {"schema_version": "2.9", "policy_id": "CANDIDATE-STARTUP-ONLY", "status": "FROZEN",
              "rule_language_id": "HF29_DETERMINISTIC_JSON_RULES", "rule_language_version": "1.0",
              "evaluator_sha256": evaluator_implementation_sha256(),
              "precedence": ["PLATFORM_SAFETY", "FROZEN_CHARTER", "FROZEN_REQUIREMENT", "ARCHITECTURE_POLICY", "TRANSITION_LOCAL"],
              "conflict_policy": "FAIL_CLOSED_POLICY_CONFLICT", "unknown_policy": "FAIL_CLOSED_POLICY_UNKNOWN",
              "rules": [{"rule_id": "STARTUP-REQUESTED", "authority_layer": "TRANSITION_LOCAL",
                         "when": {"requested": True}, "decision": "MACHINE_CONTINUE",
                         "reason_code": "REQUESTED_NATIVE_STARTUP", "next_transition_selector": None}]}
    result = {}
    for index, node in enumerate(STARTUP_NODES):
        _require(node in nodes and nodes[node].get("executor_implementation_ref") == "tools/" + MODULES[node] + ".py",
                 "startup provider differs from Candidate DAG")
        if index:
            _require(nodes[node].get("required_predecessor_nodes") == [STARTUP_NODES[index - 1]],
                     "startup predecessor differs from Candidate DAG")
        else:
            _require(nodes[node].get("required_predecessor_nodes") == ["START_PACKAGE_HUMAN_APPROVAL"],
                     "first startup node must follow the Candidate decision")
        result[node] = {"schema_version": "2.9", "transition_id": node, "node_kind": node,
                        "bindings": deepcopy(bindings), "precondition_claims": nodes[node].get("required_predecessor_nodes", []),
                        "input_refs": ["harness-resource://candidate/" + nodes[node]["action_contract_ref"]],
                        # The final native probe checks the entire execution
                        # tree for mutations; disclose that actual read scope.
                        "allowed_read_roots": (["harness-resource://candidate", "harness-resource://execution"] if index == 2
                                               else ["harness-resource://candidate", CONTROL_ROOT, EVIDENCE_ROOT.rstrip("/")]),
                        "allowed_write_roots": [CONTROL_ROOT, EVIDENCE_ROOT + node,
                                                EVIDENCE_ROOT + "START_PACKAGE_HUMAN_APPROVAL"],
                        "required_authorization_class": "PARENT_RISK_ENVELOPE",
                        "command_contract": {"command_class": STARTUP_CLASS, "delivery_mode": DURABLE_DELIVERY_MODE},
                        "result_schema": deepcopy(RESULT_SCHEMA), "evidence_obligations": [nodes[node]["result_schema_ref"]],
                        "decision_policy": deepcopy(policy),
                        "declared_input_schema": {"type": "object", "required": ["requested"],
                                                  "properties": {"requested": {"type": "boolean"}}},
                        "retry_policy": {"max_retries": 0}, "checkpoint_policy": {"resume_requires_revalidation": True},
                        "risk": {"permissions": ["WRITE_DECLARED_EVIDENCE"], "network_mode": "DENY",
                                 "secret_access": False, "external_effect_class": "LOCAL_REVERSIBLE"},
                        "next_transition_id": STARTUP_NODES[index + 1] if index + 1 < len(STARTUP_NODES) else None,
                        "stop_gate": None}
    return result


def validate_startup_execution(parent):
    plan = parent.get("startup_execution")
    _require(isinstance(plan, dict) and set(plan) == {"mode", "candidate_root", "execution_root", "control_db",
                                                    "factory_source", "approval_receipt", "transitions"}
             and plan["mode"] == STARTUP_MODE, "startup plan is incomplete")
    _require(parent.get("bindings", {}).get("binding_kind") == START_PACKAGE_BINDING_KIND,
             "startup requires the actual Factory approval binding")
    for field in ("candidate_root", "execution_root", "control_db"):
        _require(isinstance(plan[field], str) and Path(plan[field]).is_absolute() and ".." not in Path(plan[field]).parts,
                 "startup paths must be explicit absolute bindings")
    _require(plan["control_db"] == str(Path(plan["execution_root"]) / CONTROL_DB_REF),
             "startup uses one canonical SQLite controller")
    source = plan["factory_source"]
    _require(isinstance(source, dict) and set(source) == {"database_path", "runs_root"}
             and all(isinstance(value, str) and Path(value).is_absolute() and ".." not in Path(value).parts
                     for value in source.values()), "Factory locator must be in the readable Parent plan")
    _require(parent.get("network_mode") == "DENY" and parent.get("secret_access") is False,
             "startup is offline and cannot use secrets")
    _require(isinstance(plan["transitions"], dict) and set(plan["transitions"]) == set(STARTUP_NODES),
             "startup must retain all three native nodes")
    _require(isinstance(plan["approval_receipt"], dict), "audited approval projection is required")
    from .local_runtime import _covered
    for transition in plan["transitions"].values():
        for field in ("allowed_read_roots", "allowed_write_roots"):
            _require(isinstance(parent.get(field), list) and isinstance(transition.get(field), list)
                     and all(_covered(ref, parent[field]) for ref in transition[field]), "startup scope exceeds its Parent")
    return plan


def _committed(store, program):
    _require(store.verify_stream(program)["status"] == "PASS", "invalid authoritative control stream")
    rows = [event["payload"] for event in store.list_events(program) if event["event_type"] == "TRANSITION_COMMITTED"
            and event["payload"]["result"].get("native_transaction") is not None]
    _require([row["transition_id"] for row in rows] == list(STARTUP_NODES[:len(rows)]),
             "native startup results are not an ordered prefix")
    return rows


def _atomic_bytes(path, payload):
    _require(path.resolve() == path, "linked compatibility view")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".view-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_json(path, value):
    _atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())


def project_startup_views(store, program, execution_root, *, write=False):
    """Rebuild only committed native artifacts from SQLite; never import files."""
    execution = Path(execution_root)
    rows = _committed(store, program)
    files, events = {}, []
    for row in rows:
        transaction = row["result"]["native_transaction"]
        node = row["transition_id"]
        files["evidence/engineering_dag/" + node + "/result.json"] = transaction["result_payload"]
        events.append(transaction["event_payload"])
    if rows:
        files[STATE_REF] = rows[-1]["result"]["native_transaction"]["next_state_payload"]
    if write:
        for relative, value in files.items():
            _atomic_json(execution / relative, value)
        if rows:
            payload = b"".join((json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
                               for event in events)
            _atomic_bytes(execution / EVENTS_REF, payload)
    return rows


def verify_startup_views(store, program, execution_root, bindings):
    """Accept a compatibility view only when this SQLite stream owns its bytes."""
    rows = _committed(store, program)
    _require(len(rows) == len(STARTUP_NODES), "startup is not fully committed in this controller", "LOCAL_LEGACY_CONTROLLER_PRESENT")
    execution = Path(execution_root)
    for row in rows:
        transaction = row["result"]["native_transaction"]
        _require(transaction["candidate_tree_sha256"] == bindings["candidate_tree_sha256"], "startup belongs to a different Candidate")
        path = execution / "evidence/engineering_dag" / row["transition_id"] / "result.json"
        payload = (json.dumps(transaction["result_payload"], ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        _require(path.is_file() and path.resolve() == path and path.read_bytes() == payload, "startup result projection differs")
    expected_state = rows[-1]["result"]["native_transaction"]["next_state_payload"]
    path = execution / STATE_REF
    _require(path.is_file() and path.resolve() == path
             and path.read_bytes() == (json.dumps(expected_state, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(),
             "startup state projection differs")
    events = b"".join((json.dumps(row["result"]["native_transaction"]["event_payload"], ensure_ascii=False,
                                 sort_keys=True, separators=(",", ":")) + "\n").encode() for row in rows)
    path = execution / EVENTS_REF
    _require(path.is_file() and path.resolve() == path and path.read_bytes() == events, "startup event projection differs")


def _native_inputs(action, candidate, execution, parent, grant, issued_at, rows):
    base = action if action.NODE_ID == STARTUP_NODES[0] else action.base
    inputs = base._resolve_candidate_inputs(candidate)
    node = action.NODE_ID
    approval = parent["startup_execution"]["approval_receipt"]
    _atomic_json(execution / base.HUMAN_APPROVAL_REF, approval)
    state = deepcopy(rows[-1]["result"]["native_transaction"]["next_state_payload"]) if rows else {
        "schema_version": "1.0", "program_id": parent["program_id"], "revision": 1,
        "control_plane_epoch": inputs["execution_control_plane_epoch"], "epoch_domains": inputs["epoch_domains"],
        "next_node": STARTUP_NODES[0], "last_event_hash": None, "driver_started": False, "active_workpack": None}
    _require(state["next_node"] == node, "cannot skip the Candidate startup predecessor")
    state.update(active_authorization_id=grant["grant_id"], authorization_status="GRANTED", remaining_transition_budget=1,
                 next_fencing_token=grant["fencing_token"])
    state["state_sha256"] = base.hash_without(state, "state_sha256")
    _atomic_json(execution / STATE_REF, state)
    if not rows:
        # Empty JSONL is a view of the empty native-action prefix.
        path = execution / EVENTS_REF
        _require(path.resolve() == path, "linked event projection")
        _atomic_bytes(path, b"")
    command = {"schema_version": "1.0", "command_id": node, "action_id": action.ACTION_ID, "node_id": node,
               "authorization_id": grant["grant_id"], "candidate_tree_sha256": parent["bindings"]["candidate_tree_sha256"],
               "requirement_ir_sha256": parent["bindings"]["requirement_ir_sha256"],
               "executor_implementation_ref": action.IMPLEMENTATION_REF,
               "executor_implementation_sha256": base.file_hash(candidate / action.IMPLEMENTATION_REF),
               "action_contract_sha256": base.file_hash(candidate / action.ACTION_CONTRACT_REF),
               "result_schema_sha256": base.file_hash(candidate / action.RESULT_SCHEMA_REF),
               "expected_control_state_sha256": base.file_hash(execution / STATE_REF),
               "lease_id": grant["grant_id"], "fencing_token": grant["fencing_token"]}
    identity = {key: command[key] for key in ("action_id", "authorization_id", "candidate_tree_sha256",
                                             "requirement_ir_sha256", "lease_id", "fencing_token")}
    extra = {}
    if node == STARTUP_NODES[0]:
        command["human_approval_receipt_sha256"] = base.file_hash(execution / base.HUMAN_APPROVAL_REF)
    elif node == STARTUP_NODES[1]:
        extra = {"shared_control_baseline_result_sha256": base.file_hash(execution / action.PREDECESSOR_REF),
                 "control_runtime_bundle_sha256": base.json_hash(action._runtime_module_hashes(candidate, action.validate_static_contract(candidate)))}
    else:
        extra = {"control_plane_registration_result_sha256": base.file_hash(execution / action.PREDECESSOR_REF),
                 "driver_entrypoint_sha256": base.file_hash(candidate / action.DRIVER_ENTRYPOINT_REF)}
        command.update(driver_entrypoint_ref=action.DRIVER_ENTRYPOINT_REF, expected_event_tip=state["last_event_hash"],
                       read_only_probe_commands=list(action.PROBE_COMMANDS))
    command.update(extra)
    identity.update(extra)
    command["idempotency_key"] = base.json_hash(identity)
    command_path = execution / ".harness-foundry/control/action_inputs" / (node + ".json")
    _atomic_json(command_path, command)
    authorization = {key: command[key] for key in ("schema_version", "authorization_id", "node_id", "candidate_tree_sha256",
        "requirement_ir_sha256", "executor_implementation_sha256", "expected_control_state_sha256", "idempotency_key",
        "lease_id", "fencing_token")}
    authorization.update(program_id=parent["program_id"], authorization_class="REGISTRATION_AUTHORIZATION", status="GRANTED",
                         one_shot=True, allowed_action_id=action.ACTION_ID, command_manifest_sha256=base.file_hash(command_path),
                         not_before=issued_at, expires_at=parent["expires_at"],
                         human_approval_receipt_sha256=base.file_hash(execution / base.HUMAN_APPROVAL_REF))
    if node != STARTUP_NODES[0]:
        mode = "REGISTRATION_ONLY" if node == STARTUP_NODES[1] else "PROJECT_VALIDATION"
        authorization.update(issuer_role=action.LOCAL_ISSUER_ROLE, issued_at=issued_at,
                             scope={"program_id": parent["program_id"], "node_id": node, "allowed_action_id": action.ACTION_ID,
                                    "execution_mode": mode, "runtime_internal_write_refs": action.RUNTIME_INTERNAL_WRITE_REFS},
                             command_manifest_hashes=[base.file_hash(command_path)], max_transitions=1,
                             delegation_allowed=False, signature_policy=action.SIGNATURE_POLICY, signature=None, **extra)
        if node == STARTUP_NODES[2]:
            authorization.update(authorization_class="PROJECT_VALIDATION_AUTHORIZATION", expected_event_tip=state["last_event_hash"],
                                 read_only_probe_commands=list(action.PROBE_COMMANDS), forbidden_actions=action.FORBIDDEN_ACTIONS)
            authorization["scope"]["read_only_probe_commands"] = list(action.PROBE_COMMANDS)
    authorization_path = execution / ".harness-foundry/control/authorizations" / (node + ".json")
    _atomic_json(authorization_path, authorization)
    return command_path, authorization_path


class StartupRuntimeAdapter:
    def __init__(self, store, program, parent_id):
        self.store, self.program, self.parent_id = store, program, parent_id

    def __call__(self, context):
        events = self.store.list_events(self.program)
        projection = rebuild_control_projections(events)
        parent = projection["grant_ledger"]["parents"].get(self.parent_id, {})
        _require(parent.get("status") in {"ACTIVE", "GRANTED"} and parent.get("approval_receipt_sha256"), "active approved Parent required")
        plan = validate_startup_execution(parent)
        grant = projection["grant_ledger"]["derived_grants"].get(context["idempotency_key"], {})
        _require(grant == context["grant"] and grant.get("status") == "ISSUED"
                 and grant.get("parent_authorization_id") == self.parent_id, "live reserved grant required")
        _require(datetime.now(timezone.utc) < datetime.fromisoformat(parent["expires_at"].replace("Z", "+00:00")), "Parent expired")
        transition = plan["transitions"].get(context["transition_id"])
        _require(grant.get("transition_contract_sha256") == content_sha256(transition), "grant is not bound to this native action")
        rows = project_startup_views(self.store, self.program, plan["execution_root"], write=True)
        _require(len(rows) < len(STARTUP_NODES) and STARTUP_NODES[len(rows)] == context["transition_id"], "cannot skip startup predecessor")
        issued = next(event["created_at"] for event in events if event["event_type"] == "TRANSITION_ATTEMPT_STARTED"
                      and event["payload"].get("grant_id") == grant["grant_id"])
        candidate, execution = Path(plan["candidate_root"]), Path(plan["execution_root"])
        action = _action(candidate, context["transition_id"])
        try:
            command, authorization = _native_inputs(action, candidate, execution, parent, grant, issued, rows)
        except (OSError, ControlKernelError) as exc:
            return {"status": "VALIDATION_FAILED", "reason_code": getattr(exc, "code", "NATIVE_INPUT_PUBLICATION_FAILED"),
                    "artifact_id": f"control-attempt://{self.program}/{context['attempt_id']}", "native_transaction": {}}
        try:
            transaction = action.prepare_action(candidate, execution, command, authorization)
        except (action.ContractError, OSError, subprocess.SubprocessError) as exc:
            code = getattr(exc, "code", "NATIVE_PREPARATION_INTERRUPTED")
            # A probe failure/timeout may follow effects; never infer safe retry
            # from a missing success result or treat it as a validation PASS.
            unknown = "PROBE" in code or not isinstance(exc, action.ContractError)
            return {"status": "UNKNOWN_SIDE_EFFECT" if unknown else "VALIDATION_FAILED", "reason_code": code,
                    "artifact_id": f"control-attempt://{self.program}/{context['attempt_id']}", "native_transaction": {}}
        return {"status": "PASS", "artifact_id": EVIDENCE_ROOT + action.NODE_ID + "/result.json", "native_transaction": transaction}


def prepare_startup_runtime(control_db, program, parent_id, contracts, *, entry_node=None):
    store = ControlEventStore(control_db, read_only=True)
    parent = rebuild_control_projections(store.list_events(program))["grant_ledger"]["parents"].get(parent_id, {})
    _require(parent.get("status") in {"ACTIVE", "GRANTED"} and parent.get("approval_receipt_sha256"),
             "startup requires an approved Parent", "PARENT_AUTHORIZATION_NOT_ACTIVE")
    plan = validate_startup_execution(parent)
    _require(datetime.now(timezone.utc) < datetime.fromisoformat(parent["expires_at"].replace("Z", "+00:00")),
             "Parent expired", "PARENT_AUTHORIZATION_EXPIRED")
    candidate, execution = Path(plan["candidate_root"]), Path(plan["execution_root"])
    _require(candidate.is_dir() and execution.is_dir() and candidate.resolve() == candidate and execution.resolve() == execution
             and not candidate.is_relative_to(execution) and not execution.is_relative_to(candidate), "roots must exist and be disjoint")
    _require(Path(control_db).resolve() == Path(plan["control_db"]), "control store differs from the approved plan")
    _require(plan["transitions"] == startup_transitions(candidate, parent["bindings"]), "startup plan differs from Candidate")
    _require(isinstance(contracts, dict) and bool(contracts)
             and all(plan["transitions"].get(key) == value for key, value in contracts.items()), "request changes the approved startup plan")
    rows = _committed(store, program)
    _require(all(row["result"]["native_transaction"]["candidate_tree_sha256"] == parent["bindings"]["candidate_tree_sha256"]
                 for row in rows), "existing startup belongs to a different Candidate")
    if entry_node is not None:
        _require(entry_node in STARTUP_NODES and STARTUP_NODES.index(entry_node) <= len(rows),
                 "requested node skips an uncommitted startup predecessor")
    if not rows:
        native_attempt = any(event["event_type"] == "COMMAND_RESULT_OBSERVED" and event["payload"].get("transition_id") in STARTUP_NODES
                             for event in store.list_events(program))
        _require(native_attempt or not any((execution / ref).exists() for ref in (STATE_REF, EVENTS_REF)),
                 "unowned legacy controller requires explicit migration", "LOCAL_LEGACY_CONTROLLER_PRESENT")
    return StartupRuntimeAdapter(ControlEventStore(control_db), program, parent_id)
