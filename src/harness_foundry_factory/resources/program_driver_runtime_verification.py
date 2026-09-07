#!/usr/bin/env python3
"""Verify the portable Program Driver with read-only pre-start probes.

The action is a one-shot project-validation transition.  It invokes only the
packaged Driver's read-only ``status``, ``plan-next``, and
``validate-transition`` commands, proves that the probes caused no filesystem
mutation, then commits one result, one event, and one control-state CAS.  It
never starts the Driver loop or a Workpack.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping


sys.dont_write_bytecode = True
TOOLS_ROOT = Path(__file__).resolve().parent


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"portable runtime module is missing: {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load_module(
    "harness_foundry_driver_verification_base",
    TOOLS_ROOT / "shared_control_baseline.py",
)
registration = _load_module(
    "harness_foundry_driver_verification_predecessor",
    TOOLS_ROOT / "control_plane_registration.py",
)


ACTION_ID = "VERIFY-PORTABLE-PROGRAM-DRIVER-RUNTIME"
NODE_ID = "PROGRAM_DRIVER_RUNTIME_VERIFIED"
PREDECESSOR_NODE_ID = "CONTROL_PLANE_REGISTRATION"
IMPLEMENTATION_REF = "tools/program_driver_runtime_verification.py"
DRIVER_ENTRYPOINT_REF = "tools/program_driver.py"
ACTION_CONTRACT_REF = (
    "validation/PROGRAM_DRIVER_RUNTIME_VERIFICATION_ACTION_CONTRACT.json"
)
RESULT_SCHEMA_REF = (
    "contracts/PROGRAM_DRIVER_RUNTIME_VERIFICATION_RESULT.schema.json"
)
GENERATION_PROFILE_REF = "EPOCH38_GENERATION_PROFILE.json"
AUTHORIZATION_POLICY_REF = "AUTHORIZATION_POLICY.json"
PREDECESSOR_REF = (
    "evidence/engineering_dag/CONTROL_PLANE_REGISTRATION/result.json"
)
HUMAN_BINDING_PREDECESSOR_REF = (
    "evidence/engineering_dag/SHARED_CONTROL_BASELINE_LOCK/result.json"
)
CONTROL_STATE_REF = base.CONTROL_STATE_REF
CONTROL_EVENTS_REF = base.CONTROL_EVENTS_REF
TRANSACTION_REF = (
    ".harness-foundry/control/transactions/"
    "PROGRAM_DRIVER_RUNTIME_VERIFIED.transaction.json"
)
LEASE_REF = (
    ".harness-foundry/control/leases/"
    "PROGRAM_DRIVER_RUNTIME_VERIFIED.lease.json"
)
RESULT_REF = (
    "evidence/engineering_dag/PROGRAM_DRIVER_RUNTIME_VERIFIED/result.json"
)
PROBE_COMMANDS = ("status", "plan-next", "validate-transition")
PRODUCED_CAPABILITIES = ["PROGRAM_DRIVER_RUNTIME_VERIFIED_PASS"]
ASSURANCE_PROFILE = "SELF_USE_LOCAL_TRUSTED_OPERATOR"
LOCAL_ISSUER_ROLE = "LOCAL_TRUSTED_OPERATOR"
SIGNATURE_POLICY = "NOT_APPLICABLE_SELF_USE_LOCAL_TRUSTED_OPERATOR"
FORBIDDEN_ACTIONS = [
    "PROGRAM_DRIVER_START",
    "WORKPACK_EXECUTION",
    "TARGET_INSTALL",
    "AUTO_SUCCESSOR_ADVANCE",
]
RUNTIME_INTERNAL_WRITE_REFS = [
    "harness-resource://execution/.harness-foundry/control/PROGRAM_CONTROL_STATE.json",
    "harness-resource://execution/.harness-foundry/control/PROGRAM_CONTROL_EVENTS.jsonl",
    (
        "harness-resource://execution/.harness-foundry/control/transactions/"
        "PROGRAM_DRIVER_RUNTIME_VERIFIED.transaction.json"
    ),
    (
        "harness-resource://execution/.harness-foundry/control/leases/"
        "PROGRAM_DRIVER_RUNTIME_VERIFIED.lease.json"
    ),
    (
        "harness-resource://execution/evidence/engineering_dag/"
        "PROGRAM_DRIVER_RUNTIME_VERIFIED/result.json"
    ),
]


ContractError = base.ContractError
candidate_identity = base.candidate_identity
file_hash = base.file_hash
file_hash_from_value = base.file_hash_from_value
hash_without = base.hash_without
json_hash = base.json_hash
read_events = base.read_events
read_json = base.read_json
require_equal = base.require_equal
atomic_json = base.atomic_json
exclusive_json = base.exclusive_json
append_event = base.append_event
utc_now = base.utc_now


def _required_result_fields(contract: Mapping[str, Any]) -> list[str]:
    execution = contract.get("execution_contract")
    required = (
        execution.get("required_result_fields")
        if isinstance(execution, Mapping)
        else None
    )
    if not isinstance(required, list):
        raise ContractError(
            "PROGRAM_DRIVER_RUNTIME_VERIFICATION_CONTRACT_INVALID",
            "required_result_fields is missing",
        )
    return [str(field) for field in required]


def validate_static_contract(candidate_root: Path) -> dict[str, Any]:
    contract = read_json(candidate_root / ACTION_CONTRACT_REF,
                         "PROGRAM_DRIVER_RUNTIME_VERIFICATION_CONTRACT_INVALID")
    profile_ref = contract.get("generation_profile_ref", GENERATION_PROFILE_REF)
    if profile_ref not in (GENERATION_PROFILE_REF, "validation/CONTROL_STARTUP_PROFILE.json"):
        raise ContractError("PROGRAM_DRIVER_RUNTIME_VERIFICATION_CONTRACT_INVALID", "undeclared profile ref")
    refs = (
        IMPLEMENTATION_REF,
        DRIVER_ENTRYPOINT_REF,
        ACTION_CONTRACT_REF,
        RESULT_SCHEMA_REF,
        profile_ref,
        AUTHORIZATION_POLICY_REF,
        "tools/shared_control_baseline.py",
        "tools/control_plane_registration.py",
    )
    paths = {ref: candidate_root / ref for ref in refs}
    for ref, path in paths.items():
        if not path.is_file():
            raise ContractError(
                "PROGRAM_DRIVER_RUNTIME_VERIFICATION_CONTRACT_INVALID", ref
            )
    contract = read_json(
        paths[ACTION_CONTRACT_REF],
        "PROGRAM_DRIVER_RUNTIME_VERIFICATION_CONTRACT_INVALID",
    )
    schema = read_json(
        paths[RESULT_SCHEMA_REF],
        "PROGRAM_DRIVER_RUNTIME_VERIFICATION_RESULT_SCHEMA_INVALID",
    )
    profile = read_json(
        paths[profile_ref],
        "PROGRAM_DRIVER_RUNTIME_VERIFICATION_CONTRACT_INVALID",
    )
    policy = read_json(
        paths[AUTHORIZATION_POLICY_REF],
        "PROGRAM_DRIVER_RUNTIME_VERIFICATION_CONTRACT_INVALID",
    )
    manifest = read_json(
        candidate_root / "THREE_PROJECT_PROGRAM_MANIFEST.json",
        "PROGRAM_DRIVER_RUNTIME_VERIFICATION_CONTRACT_INVALID",
    )
    epoch_domains = manifest.get("epoch_domains")
    authorization_profile = contract.get("authorization_profile")
    profile_schemas = policy.get("profile_authorization_schemas")
    local_schemas = (
        profile_schemas.get(ASSURANCE_PROFILE)
        if isinstance(profile_schemas, Mapping)
        else None
    )
    policy_profile = (
        local_schemas.get("PROJECT_VALIDATION_AUTHORIZATION")
        if isinstance(local_schemas, Mapping)
        else None
    )
    scope_contract = (
        authorization_profile.get("scope_contract")
        if isinstance(authorization_profile, Mapping)
        else None
    )
    persistence = contract.get("persistence_contract")
    persistence_refs = (
        {
            value
            for key, value in persistence.items()
            if str(key).endswith("_ref") and isinstance(value, str)
        }
        if isinstance(persistence, Mapping)
        else set()
    )
    required = _required_result_fields(contract)
    dag = read_json(candidate_root / "ENGINEERING_PROJECT_DAG.json", "ENGINEERING_PROJECT_DAG_INVALID")
    nodes = [node for node in dag.get("nodes", []) if node.get("node_id") == NODE_ID]
    successors = nodes[0].get("allowed_next_nodes") if len(nodes) == 1 else None
    successor = contract.get("execution_contract", {}).get("successor_node_id")
    if not isinstance(successor, str) or successors != [successor]:
        raise ContractError("PROGRAM_DRIVER_RUNTIME_VERIFICATION_CONTRACT_INVALID", "DAG successor binding differs")
    if schema.get("properties", {}).get("next_node", {}).get("const") != successor:
        raise ContractError("PROGRAM_DRIVER_RUNTIME_VERIFICATION_CONTRACT_INVALID", "result successor binding differs")
    if (
        contract.get("action_id") != ACTION_ID
        or contract.get("node_id") != NODE_ID
        or contract.get("implementation_ref") != IMPLEMENTATION_REF
        or contract.get("executor_implementation_sha256")
        != file_hash(paths[IMPLEMENTATION_REF])
        or contract.get("driver_entrypoint_ref") != DRIVER_ENTRYPOINT_REF
        or contract.get("driver_entrypoint_sha256")
        != file_hash(paths[DRIVER_ENTRYPOINT_REF])
        or contract.get("result_schema_ref") != RESULT_SCHEMA_REF
        or contract.get("result_schema_sha256")
        != file_hash(paths[RESULT_SCHEMA_REF])
        or contract.get("read_only_probe_commands") != list(PROBE_COMMANDS)
        or not isinstance(epoch_domains, Mapping)
        or contract.get("epoch_domain_contract") != epoch_domains
        or contract.get("runtime_internal_write_refs")
        != RUNTIME_INTERNAL_WRITE_REFS
        or contract.get("contract_sha256")
        != hash_without(contract, "contract_sha256")
        or profile.get("assurance_profile") != ASSURANCE_PROFILE
        or not isinstance(authorization_profile, Mapping)
        or authorization_profile.get("authorization_class")
        != "PROJECT_VALIDATION_AUTHORIZATION"
        or authorization_profile.get("issuer_role") != LOCAL_ISSUER_ROLE
        or authorization_profile.get("max_transitions") != 1
        or authorization_profile.get("delegation_allowed") is not False
        or authorization_profile.get("signature_policy") != SIGNATURE_POLICY
        or authorization_profile.get("signature_value") is not None
        or authorization_profile.get(
            "external_cryptographic_signature_required"
        )
        is not False
        or policy_profile != authorization_profile
        or not isinstance(scope_contract, Mapping)
        or scope_contract.get("runtime_internal_write_refs")
        != RUNTIME_INTERNAL_WRITE_REFS
        or scope_contract.get("read_only_probe_commands")
        != list(PROBE_COMMANDS)
        or persistence_refs != set(RUNTIME_INTERNAL_WRITE_REFS)
        or schema.get("required") != required
        or set(schema.get("properties", {})) != set(required)
        or schema.get("additionalProperties") is not False
    ):
        raise ContractError(
            "PROGRAM_DRIVER_RUNTIME_VERIFICATION_CONTRACT_INVALID",
            "static entrypoint, policy, schema, or persistence binding failed",
        )
    return contract


def validate_result_document(
    result: Mapping[str, Any],
    schema: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> None:
    required = schema.get("required")
    properties = schema.get("properties")
    if not isinstance(required, list) or not isinstance(properties, Mapping):
        raise ContractError(
            "PROGRAM_DRIVER_RUNTIME_VERIFICATION_RESULT_SCHEMA_INVALID",
            "schema is invalid",
        )
    if set(result) != set(required):
        raise ContractError(
            "PROGRAM_DRIVER_RUNTIME_VERIFICATION_RESULT_INVALID",
            "result fields are not exact",
        )
    type_map = {
        "string": str,
        "integer": int,
        "array": list,
        "object": dict,
        "boolean": bool,
    }
    for field in required:
        rule = properties.get(field)
        if not isinstance(rule, Mapping):
            raise ContractError(
                "PROGRAM_DRIVER_RUNTIME_VERIFICATION_RESULT_SCHEMA_INVALID",
                field,
            )
        expected = type_map.get(str(rule.get("type")))
        value = result.get(field)
        if expected is None or not isinstance(value, expected) or (
            expected is int and isinstance(value, bool)
        ):
            raise ContractError(
                "PROGRAM_DRIVER_RUNTIME_VERIFICATION_RESULT_INVALID", field
            )
        if "const" in rule and value != rule["const"]:
            raise ContractError(
                "PROGRAM_DRIVER_RUNTIME_VERIFICATION_RESULT_INVALID", field
            )
        pattern = rule.get("pattern")
        if pattern and (
            not isinstance(value, str)
            or re.fullmatch(str(pattern), value) is None
        ):
            raise ContractError(
                "PROGRAM_DRIVER_RUNTIME_VERIFICATION_RESULT_INVALID", field
            )
    require_equal(
        result.get("next_node"),
        contract.get("execution_contract", {}).get("successor_node_id"),
        "PROGRAM_DRIVER_RUNTIME_VERIFICATION_RESULT_INVALID",
        "next_node",
    )
    require_equal(
        result.get("produced_capabilities"),
        PRODUCED_CAPABILITIES,
        "PROGRAM_DRIVER_RUNTIME_VERIFICATION_RESULT_INVALID",
        "produced_capabilities",
    )
    require_equal(
        result.get("probe_commands"),
        list(PROBE_COMMANDS),
        "PROGRAM_DRIVER_RUNTIME_VERIFICATION_RESULT_INVALID",
        "probe_commands",
    )
    require_equal(
        result.get("result_sha256"),
        hash_without(result, "result_sha256"),
        "PROGRAM_DRIVER_RUNTIME_VERIFICATION_RESULT_INVALID",
        "result_sha256",
    )


def _tree_snapshot(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ContractError(
                "PROGRAM_DRIVER_READ_ONLY_PROBE_MUTATION",
                f"symlink encountered: {path.relative_to(root)}",
            )
        if path.is_file():
            snapshot[path.relative_to(root).as_posix()] = file_hash(path)
    return snapshot


def _run_read_only_probes(
    candidate_root: Path,
    execution_root: Path,
    *,
    candidate_sha: str,
    state_file_sha: str,
    state_payload_sha: str,
) -> dict[str, Any]:
    entrypoint = candidate_root / DRIVER_ENTRYPOINT_REF
    candidate_before = _tree_snapshot(candidate_root)
    execution_before = _tree_snapshot(execution_root)
    results: dict[str, Any] = {}
    # The declared probe does not need caller credentials or Python startup
    # hooks. Keep the original interpreter (including its venv) explicit.
    environment = {"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
    for command in PROBE_COMMANDS:
        completed = subprocess.run(
            [
                sys.executable,
                str(entrypoint),
                command,
                "--candidate-root",
                str(candidate_root),
                "--execution-root",
                str(execution_root),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            env=environment,
        )
        try:
            output = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ContractError(
                "PROGRAM_DRIVER_READ_ONLY_PROBE_FAILED",
                f"{command}: invalid JSON: {exc}",
            ) from None
        if (
            completed.returncode != 0
            or output.get("status") != "PASS"
            or output.get("command") != command
            or output.get("read_only") is not True
            or output.get("candidate_tree_sha256") != candidate_sha
            or output.get("control_state_file_sha256") != state_file_sha
            or output.get("control_state_payload_sha256")
            != state_payload_sha
            or output.get("driver_started") is not False
            or output.get("workpack_started") is not False
            or output.get("probe_sha256")
            != hash_without(output, "probe_sha256")
        ):
            raise ContractError(
                "PROGRAM_DRIVER_READ_ONLY_PROBE_FAILED",
                f"{command}: read-only probe contract failed",
            )
        results[command] = output
    if (
        candidate_before != _tree_snapshot(candidate_root)
        or execution_before != _tree_snapshot(execution_root)
    ):
        raise ContractError(
            "PROGRAM_DRIVER_READ_ONLY_PROBE_MUTATION",
            "read-only probes changed Candidate or Execution Root bytes",
        )
    return results


def _validate_runtime_inputs(
    candidate_root: Path,
    execution_root: Path,
    command_path: Path,
    authorization_path: Path,
) -> dict[str, Any]:
    contract = validate_static_contract(candidate_root)
    schema = read_json(
        candidate_root / RESULT_SCHEMA_REF,
        "PROGRAM_DRIVER_RUNTIME_VERIFICATION_RESULT_SCHEMA_INVALID",
    )
    candidate_sha = candidate_identity(candidate_root)
    inputs = base._resolve_candidate_inputs(candidate_root)
    predecessor_path = execution_root / PREDECESSOR_REF
    predecessor = read_json(
        predecessor_path, "CONTROL_PLANE_REGISTRATION_RESULT_INVALID"
    )
    predecessor_contract = registration.validate_static_contract(candidate_root)
    predecessor_schema = read_json(candidate_root / registration.RESULT_SCHEMA_REF)
    registration.validate_result_document(
        predecessor, predecessor_schema, predecessor_contract
    )
    predecessor_sha = file_hash(predecessor_path)
    human_binding_path = execution_root / HUMAN_BINDING_PREDECESSOR_REF
    human_binding = read_json(
        human_binding_path, "SHARED_CONTROL_BASELINE_RESULT_INVALID"
    )
    require_equal(
        file_hash(human_binding_path),
        predecessor.get("shared_control_baseline_result_sha256"),
        "CONTROL_PLANE_REGISTRATION_RESULT_INVALID",
        "shared_control_baseline_result_sha256",
    )
    state_path = execution_root / CONTROL_STATE_REF
    state = read_json(state_path, "PROGRAM_CONTROL_STATE_INVALID")
    state_file_sha = file_hash(state_path)
    command = read_json(command_path, "COMMAND_MANIFEST_INVALID")
    command_sha = file_hash(command_path)
    authorization = read_json(
        authorization_path, "PROJECT_VALIDATION_AUTHORIZATION_INVALID"
    )
    authorization_sha = file_hash(authorization_path)
    implementation_sha = file_hash(candidate_root / IMPLEMENTATION_REF)
    entrypoint_sha = file_hash(candidate_root / DRIVER_ENTRYPOINT_REF)
    action_contract_sha = file_hash(candidate_root / ACTION_CONTRACT_REF)
    result_schema_sha = file_hash(candidate_root / RESULT_SCHEMA_REF)

    require_equal(
        predecessor.get("node_id"),
        PREDECESSOR_NODE_ID,
        "CONTROL_PLANE_REGISTRATION_RESULT_INVALID",
        "node_id",
    )
    require_equal(
        predecessor.get("status"),
        "PASS",
        "CONTROL_PLANE_REGISTRATION_RESULT_INVALID",
        "status",
    )
    require_equal(
        predecessor.get("candidate_tree_sha256"),
        candidate_sha,
        "CONTROL_PLANE_REGISTRATION_RESULT_INVALID",
        "candidate_tree_sha256",
    )
    require_equal(
        predecessor.get("requirement_ir_sha256"),
        inputs["requirement_ir_sha256"],
        "CONTROL_PLANE_REGISTRATION_RESULT_INVALID",
        "requirement_ir_sha256",
    )

    command_checks = {
        "action_id": ACTION_ID,
        "node_id": NODE_ID,
        "authorization_id": authorization.get("authorization_id"),
        "candidate_tree_sha256": candidate_sha,
        "requirement_ir_sha256": inputs["requirement_ir_sha256"],
        "executor_implementation_ref": IMPLEMENTATION_REF,
        "executor_implementation_sha256": implementation_sha,
        "driver_entrypoint_ref": DRIVER_ENTRYPOINT_REF,
        "driver_entrypoint_sha256": entrypoint_sha,
        "action_contract_sha256": action_contract_sha,
        "result_schema_sha256": result_schema_sha,
        "control_plane_registration_result_sha256": predecessor_sha,
        "expected_control_state_sha256": state_file_sha,
        "expected_event_tip": state.get("last_event_hash"),
        "read_only_probe_commands": list(PROBE_COMMANDS),
    }
    required_command_fields = contract["runtime_input_contract"][
        "command_manifest_required_fields"
    ]
    if set(command) != set(required_command_fields):
        raise ContractError(
            "COMMAND_MANIFEST_INVALID",
            "command fields do not exactly match the action contract",
        )
    for field, expected in command_checks.items():
        code = (
            "UNBOUND_OR_DRIFTED_PROGRAM_DRIVER_ENTRYPOINT"
            if field in {"driver_entrypoint_ref", "driver_entrypoint_sha256"}
            else "UNBOUND_OR_DRIFTED_CONTROL_ACTION_IMPLEMENTATION"
            if field.startswith("executor_")
            else "COMMAND_MANIFEST_INVALID"
        )
        require_equal(
            command.get(field), expected, code, field
        )

    required_authorization_fields = contract["runtime_input_contract"][
        "authorization_required_fields"
    ]
    if set(authorization) != set(required_authorization_fields):
        raise ContractError(
            "PROJECT_VALIDATION_AUTHORIZATION_INVALID",
            "authorization fields do not exactly match the local profile schema",
        )
    if authorization.get("status") == "REVOKED":
        raise ContractError(
            "PROJECT_VALIDATION_AUTHORIZATION_REVOKED",
            "authorization is revoked",
        )
    expected_scope = {
        "program_id": inputs["program_id"],
        "node_id": NODE_ID,
        "allowed_action_id": ACTION_ID,
        "execution_mode": "PROJECT_VALIDATION",
        "read_only_probe_commands": list(PROBE_COMMANDS),
        "runtime_internal_write_refs": RUNTIME_INTERNAL_WRITE_REFS,
    }
    authorization_checks = {
        "schema_version": "1.0",
        "authorization_class": "PROJECT_VALIDATION_AUTHORIZATION",
        "status": "GRANTED",
        "one_shot": True,
        "program_id": inputs["program_id"],
        "issuer_role": LOCAL_ISSUER_ROLE,
        "node_id": NODE_ID,
        "allowed_action_id": ACTION_ID,
        "scope": expected_scope,
        "command_manifest_hashes": [command_sha],
        "command_manifest_sha256": command_sha,
        "candidate_tree_sha256": candidate_sha,
        "requirement_ir_sha256": inputs["requirement_ir_sha256"],
        "executor_implementation_sha256": implementation_sha,
        "driver_entrypoint_sha256": entrypoint_sha,
        "human_approval_receipt_sha256": human_binding.get(
            "human_approval_receipt_sha256"
        ),
        "control_plane_registration_result_sha256": predecessor_sha,
        "expected_control_state_sha256": state_file_sha,
        "expected_event_tip": state.get("last_event_hash"),
        "read_only_probe_commands": list(PROBE_COMMANDS),
        "forbidden_actions": FORBIDDEN_ACTIONS,
        "max_transitions": 1,
        "delegation_allowed": False,
        "signature_policy": SIGNATURE_POLICY,
        "signature": None,
    }
    for field, expected in authorization_checks.items():
        require_equal(
            authorization.get(field),
            expected,
            "PROJECT_VALIDATION_AUTHORIZATION_INVALID",
            field,
        )
    issued_at = base.parse_time(authorization.get("issued_at"), "issued_at")
    not_before = base.parse_time(
        authorization.get("not_before"), "not_before"
    )
    expires_at = base.parse_time(authorization.get("expires_at"), "expires_at")
    now = datetime.now(timezone.utc)
    if issued_at > not_before or not_before > now or expires_at <= now:
        raise ContractError(
            "PROJECT_VALIDATION_AUTHORIZATION_INVALID",
            "authorization is outside its validity window",
        )

    require_equal(
        state.get("state_sha256"),
        hash_without(state, "state_sha256"),
        "PROGRAM_CONTROL_STATE_INVALID",
        "state_sha256",
    )
    require_equal(
        state.get("program_id"),
        inputs["program_id"],
        "PROGRAM_CONTROL_STATE_INVALID",
        "program_id",
    )
    require_equal(
        state.get("epoch_domains"),
        inputs["epoch_domains"],
        "PROGRAM_CONTROL_STATE_INVALID",
        "epoch_domains",
    )
    require_equal(
        state.get("control_plane_epoch"),
        inputs["execution_control_plane_epoch"],
        "PROGRAM_CONTROL_STATE_INVALID",
        "control_plane_epoch",
    )
    require_equal(
        state.get("last_completed_node"),
        PREDECESSOR_NODE_ID,
        "PROGRAM_CONTROL_STATE_INVALID",
        "last_completed_node",
    )
    require_equal(
        state.get("next_node"),
        NODE_ID,
        "PROGRAM_CONTROL_STATE_INVALID",
        "next_node",
    )
    require_equal(
        state.get("authorization_status"),
        "GRANTED",
        "PROGRAM_CONTROL_STATE_INVALID",
        "authorization_status",
    )
    require_equal(
        state.get("active_authorization_id"),
        authorization.get("authorization_id"),
        "PROGRAM_CONTROL_STATE_INVALID",
        "active_authorization_id",
    )
    require_equal(
        state.get("remaining_transition_budget"),
        1,
        "PROGRAM_CONTROL_STATE_INVALID",
        "remaining_transition_budget",
    )
    require_equal(
        state.get("driver_started"),
        False,
        "PROGRAM_CONTROL_STATE_INVALID",
        "driver_started",
    )
    require_equal(
        state.get("active_workpack"),
        None,
        "PROGRAM_CONTROL_STATE_INVALID",
        "active_workpack",
    )
    events = read_events(execution_root / CONTROL_EVENTS_REF)
    actual_tip = events[-1].get("event_hash") if events else None
    require_equal(
        state.get("last_event_hash"),
        actual_tip,
        "CONTROL_EVENT_LEDGER_INVALID",
        "last_event_hash",
    )

    fencing = authorization.get("fencing_token")
    if not isinstance(fencing, int) or isinstance(fencing, bool) or fencing < 1:
        raise ContractError(
            "FENCING_TOKEN_INVALID", "fencing_token must be positive"
        )
    require_equal(
        fencing,
        state.get("next_fencing_token"),
        "FENCING_TOKEN_REGRESSION",
        "fencing_token",
    )
    require_equal(
        command.get("fencing_token"),
        fencing,
        "COMMAND_MANIFEST_INVALID",
        "fencing_token",
    )
    lease_id = authorization.get("lease_id")
    if not isinstance(lease_id, str) or not lease_id:
        raise ContractError("LEASE_ID_INVALID", "lease_id is required")
    require_equal(
        command.get("lease_id"),
        lease_id,
        "COMMAND_MANIFEST_INVALID",
        "lease_id",
    )
    expected_idempotency = json_hash(
        {
            "action_id": ACTION_ID,
            "authorization_id": authorization.get("authorization_id"),
            "candidate_tree_sha256": candidate_sha,
            "control_plane_registration_result_sha256": predecessor_sha,
            "driver_entrypoint_sha256": entrypoint_sha,
            "fencing_token": fencing,
            "lease_id": lease_id,
            "requirement_ir_sha256": inputs["requirement_ir_sha256"],
        }
    )
    require_equal(
        command.get("idempotency_key"),
        expected_idempotency,
        "IDEMPOTENCY_KEY_INVALID",
        "command idempotency_key",
    )
    require_equal(
        authorization.get("idempotency_key"),
        expected_idempotency,
        "IDEMPOTENCY_KEY_INVALID",
        "authorization idempotency_key",
    )
    probes = _run_read_only_probes(
        candidate_root,
        execution_root,
        candidate_sha=candidate_sha,
        state_file_sha=state_file_sha,
        state_payload_sha=str(state.get("state_sha256")),
    )
    return {
        "contract": contract,
        "schema": schema,
        "inputs": inputs,
        "candidate_sha": candidate_sha,
        "state": state,
        "state_file_sha": state_file_sha,
        "command_sha": command_sha,
        "authorization": authorization,
        "authorization_sha": authorization_sha,
        "implementation_sha": implementation_sha,
        "entrypoint_sha": entrypoint_sha,
        "action_contract_sha": action_contract_sha,
        "result_schema_sha": result_schema_sha,
        "predecessor_sha": predecessor_sha,
        "idempotency_key": expected_idempotency,
        "lease_id": lease_id,
        "fencing_token": fencing,
        "probes": probes,
    }


def _validate_committed_transaction(
    execution_root: Path, transaction: Mapping[str, Any]
) -> dict[str, Any]:
    if (
        transaction.get("transaction_sha256")
        != hash_without(transaction, "transaction_sha256")
        or transaction.get("transaction_state") != "COMMITTED"
    ):
        raise ContractError(
            "UNKNOWN_COMMIT_STATE",
            "existing verification transaction is not safely committed",
        )
    result = read_json(
        execution_root / RESULT_REF,
        "PROGRAM_DRIVER_RUNTIME_VERIFICATION_RESULT_INVALID",
    )
    state = read_json(
        execution_root / CONTROL_STATE_REF, "PROGRAM_CONTROL_STATE_INVALID"
    )
    event = transaction.get("event_payload")
    if not isinstance(event, Mapping):
        raise ContractError("UNKNOWN_COMMIT_STATE", "event payload is missing")
    events = read_events(execution_root / CONTROL_EVENTS_REF)
    matches = [
        item
        for item in events
        if item.get("idempotency_key") == transaction.get("idempotency_key")
    ]
    if (
        len(matches) != 1
        or matches[0] != event
        or file_hash_from_value(result) != transaction.get("result_file_sha256")
        or state.get("state_sha256")
        != transaction.get("next_state_payload", {}).get("state_sha256")
    ):
        raise ContractError(
            "UNKNOWN_COMMIT_STATE",
            "committed transaction outputs do not reconcile",
        )
    return result


def _prepare_transaction(candidate: Path, execution: Path, runtime: Mapping[str, Any]) -> dict[str, Any]:
    """Build validated payloads; never commit a lease, journal, result or state."""
    result = {
        "schema_version": "1.0",
        "result_id": f"{NODE_ID}-{runtime['idempotency_key'][:16]}",
        "program_id": runtime["inputs"]["program_id"],
        "node_id": NODE_ID,
        "next_node": runtime["contract"]["execution_contract"]["successor_node_id"],
        "status": "PASS",
        "execution_mode": "PROJECT_VALIDATION",
        "control_plane_epoch": runtime["inputs"]["execution_control_plane_epoch"],
        "candidate_tree_sha256": runtime["candidate_sha"],
        "requirement_ir_sha256": runtime["inputs"]["requirement_ir_sha256"],
        "control_plane_registration_result_sha256": runtime["predecessor_sha"],
        "driver_entrypoint_ref": DRIVER_ENTRYPOINT_REF,
        "driver_entrypoint_sha256": runtime["entrypoint_sha"],
        "command_manifest_sha256": runtime["command_sha"],
        "executor_implementation_sha256": runtime["implementation_sha"],
        "action_contract_sha256": runtime["action_contract_sha"],
        "result_schema_sha256": runtime["result_schema_sha"],
        "authorization_id": runtime["authorization"]["authorization_id"],
        "authorization_sha256": runtime["authorization_sha"],
        "idempotency_key": runtime["idempotency_key"],
        "lease_id": runtime["lease_id"],
        "fencing_token": runtime["fencing_token"],
        "probe_commands": list(PROBE_COMMANDS),
        "probe_results": runtime["probes"],
        "probe_bundle_sha256": json_hash(runtime["probes"]),
        "produced_capabilities": PRODUCED_CAPABILITIES,
        "driver_started": False,
        "workpack_started": False,
        "side_effects_allowed": False,
        "started_at": utc_now(),
        "completed_at": utc_now(),
        "result_sha256": "",
    }
    result["result_sha256"] = hash_without(result, "result_sha256")
    validate_result_document(result, runtime["schema"], runtime["contract"])
    event = {
        "schema_version": "1.0",
        "event_type": "PROGRAM_DRIVER_RUNTIME_VERIFICATION_COMMITTED",
        "program_id": runtime["inputs"]["program_id"],
        "node_id": NODE_ID,
        "idempotency_key": runtime["idempotency_key"],
        "authorization_id": runtime["authorization"]["authorization_id"],
        "authorization_sha256": runtime["authorization_sha"],
        "executor_implementation_sha256": runtime["implementation_sha"],
        "driver_entrypoint_sha256": runtime["entrypoint_sha"],
        "result_sha256": file_hash_from_value(result),
        "previous_event_hash": runtime["state"].get("last_event_hash"),
        "fencing_token": runtime["fencing_token"],
    }
    event["event_hash"] = hash_without(event, "event_hash")
    next_state = dict(runtime["state"])
    next_state.update(
        {
            "revision": int(runtime["state"].get("revision", 0)) + 1,
            "last_completed_node": NODE_ID,
            "next_node": result["next_node"],
            "authorization_status": "CONSUMED",
            "active_authorization_id": None,
            "remaining_transition_budget": 0,
            "next_fencing_token": runtime["fencing_token"] + 1,
            "last_event_hash": event["event_hash"],
            "driver_started": False,
            "active_workpack": None,
        }
    )
    next_state["state_sha256"] = hash_without(next_state, "state_sha256")
    transaction = {
        "schema_version": "1.0",
        "transaction_id": f"{NODE_ID}-{runtime['idempotency_key'][:16]}",
        "action_id": ACTION_ID,
        "node_id": NODE_ID,
        "transaction_state": "PREPARED",
        "idempotency_key": runtime["idempotency_key"],
        "lease_id": runtime["lease_id"],
        "fencing_token": runtime["fencing_token"],
        "candidate_tree_sha256": runtime["candidate_sha"],
        "command_manifest_sha256": runtime["command_sha"],
        "authorization_sha256": runtime["authorization_sha"],
        "executor_implementation_sha256": runtime["implementation_sha"],
        "driver_entrypoint_sha256": runtime["entrypoint_sha"],
        "previous_state_file_sha256": runtime["state_file_sha"],
        "prior_state_payload": runtime["state"],
        "result_payload": result,
        "result_file_sha256": file_hash_from_value(result),
        "event_payload": event,
        "next_state_payload": next_state,
        "transaction_sha256": "",
    }
    transaction["transaction_sha256"] = hash_without(
        transaction, "transaction_sha256"
    )
    return transaction


def prepare_action(candidate_root: Path, execution_root: Path, command_manifest_path: Path,
                   authorization_path: Path) -> dict[str, Any]:
    """Read-only preparation for a controller that owns the authoritative commit.

    The returned proposal is not a committed action or execution permission.
    Its controller must revalidate its own authority and compare-and-swap the
    input state before committing. Driver probes remain read-only verification.
    """
    if candidate_root.is_symlink() or execution_root.is_symlink():
        raise ContractError("CANDIDATE_EXECUTION_ROOT_OVERLAP", "root symlinks are forbidden")
    candidate, execution = candidate_root.resolve(), execution_root.resolve()
    if candidate == execution or candidate in execution.parents or execution in candidate.parents:
        raise ContractError("CANDIDATE_EXECUTION_ROOT_OVERLAP", "Candidate and execution roots must be disjoint")
    for path in (command_manifest_path, authorization_path):
        if path.is_symlink() or not path.resolve().is_relative_to(execution):
            raise ContractError("CONTROL_ACTION_INPUT_INVALID", "action inputs must be under the execution root")
    runtime = _validate_runtime_inputs(candidate, execution, command_manifest_path.resolve(), authorization_path.resolve())
    return _prepare_transaction(candidate, execution, runtime)


def execute_action(
    candidate_root: Path,
    execution_root: Path,
    command_manifest_path: Path,
    authorization_path: Path,
) -> dict[str, Any]:
    if (execution_root / ".harness-foundry/control.sqlite3").exists():
        raise ContractError("SQLITE_CONTROLLER_OWNS_STATE", "use read-only preparation through the authoritative controller")
    if candidate_root.is_symlink() or execution_root.is_symlink():
        raise ContractError(
            "CANDIDATE_EXECUTION_ROOT_OVERLAP", "root symlinks are forbidden"
        )
    candidate = candidate_root.resolve()
    execution = execution_root.resolve()
    if (
        candidate == execution
        or candidate in execution.parents
        or execution in candidate.parents
    ):
        raise ContractError(
            "CANDIDATE_EXECUTION_ROOT_OVERLAP",
            "Candidate and Execution Root must be disjoint",
        )
    for supplied, label in (
        (command_manifest_path, "command manifest"),
        (authorization_path, "authorization"),
    ):
        if supplied.is_symlink() or not supplied.resolve().is_relative_to(
            execution
        ):
            raise ContractError(
                "CONTROL_ACTION_INPUT_INVALID",
                f"{label} must be under the Execution Root",
            )

    transaction_path = execution / TRANSACTION_REF
    if transaction_path.exists():
        transaction = read_json(transaction_path, "TRANSACTION_JOURNAL_INVALID")
        result = _validate_committed_transaction(execution, transaction)
        return {
            "status": "PASS",
            "disposition": "ALREADY_COMMITTED",
            "result": result,
        }

    runtime = _validate_runtime_inputs(
        candidate,
        execution,
        command_manifest_path.resolve(),
        authorization_path.resolve(),
    )
    lease_path = execution / LEASE_REF
    lease = {
        "schema_version": "1.0",
        "action_id": ACTION_ID,
        "lease_id": runtime["lease_id"],
        "idempotency_key": runtime["idempotency_key"],
        "fencing_token": runtime["fencing_token"],
        "status": "ACQUIRED",
    }
    try:
        exclusive_json(lease_path, lease)
    except FileExistsError:
        require_equal(
            read_json(lease_path), lease, "LEASE_CONFLICT", "lease"
        )

    transaction = _prepare_transaction(candidate, execution, runtime)
    result, event, next_state = (transaction[key] for key in ("result_payload", "event_payload", "next_state_payload"))
    try:
        exclusive_json(transaction_path, transaction)
    except FileExistsError:
        raise ContractError(
            "TRANSACTION_CONFLICT",
            "another executor created the transaction",
        ) from None
    atomic_json(execution / RESULT_REF, result)
    append_event(execution / CONTROL_EVENTS_REF, event)
    if file_hash(execution / CONTROL_STATE_REF) != runtime["state_file_sha"]:
        raise ContractError(
            "UNKNOWN_COMMIT_STATE", "control state CAS failed"
        )
    atomic_json(execution / CONTROL_STATE_REF, next_state)
    transaction["transaction_state"] = "COMMITTED"
    transaction["transaction_sha256"] = hash_without(
        transaction, "transaction_sha256"
    )
    atomic_json(transaction_path, transaction)
    return {"status": "PASS", "disposition": "COMMITTED", "result": result}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-contract")
    validate.add_argument(
        "--candidate-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    execute = subparsers.add_parser("execute")
    execute.add_argument("--candidate-root", type=Path, required=True)
    execute.add_argument("--execution-root", type=Path, required=True)
    execute.add_argument("--command-manifest", type=Path, required=True)
    execute.add_argument("--authorization", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-contract":
            contract = validate_static_contract(args.candidate_root.resolve())
            output = {
                "status": "PASS",
                "action_id": contract["action_id"],
                "executor_implementation_sha256": contract[
                    "executor_implementation_sha256"
                ],
                "driver_entrypoint_sha256": contract[
                    "driver_entrypoint_sha256"
                ],
            }
        else:
            output = execute_action(
                args.candidate_root,
                args.execution_root,
                args.command_manifest.resolve(),
                args.authorization.resolve(),
            )
    except ContractError as exc:
        print(
            json.dumps(
                {"status": "FAIL", "code": exc.code, "message": exc.message},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
