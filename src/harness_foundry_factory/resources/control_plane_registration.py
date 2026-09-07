#!/usr/bin/env python3
"""Register the portable v2.9 control-plane executable closure.

The action is deliberately registration-only.  It validates the completed
Shared Control Baseline receipt, the exact packaged control-kernel modules, a
one-shot authorization, fencing, idempotency, the append-only event tip, and a
state CAS.  It never starts the Program Driver or a Workpack.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping


sys.dont_write_bytecode = True
TOOLS_ROOT = Path(__file__).resolve().parent
_BASE_PATH = TOOLS_ROOT / "shared_control_baseline.py"
_BASE_SPEC = importlib.util.spec_from_file_location(
    "harness_foundry_shared_control_baseline", _BASE_PATH
)
if _BASE_SPEC is None or _BASE_SPEC.loader is None:
    raise RuntimeError("portable Shared Control Baseline runtime is missing")
base = importlib.util.module_from_spec(_BASE_SPEC)
_BASE_SPEC.loader.exec_module(base)


ACTION_ID = "REGISTER-CONTROL-PLANE-EXECUTABLE-CLOSURE"
NODE_ID = "CONTROL_PLANE_REGISTRATION"
NEXT_NODE_ID = "PROGRAM_DRIVER_RUNTIME_VERIFIED"
IMPLEMENTATION_REF = "tools/control_plane_registration.py"
ACTION_CONTRACT_REF = "validation/CONTROL_PLANE_REGISTRATION_ACTION_CONTRACT.json"
RESULT_SCHEMA_REF = "contracts/CONTROL_PLANE_REGISTRATION_RESULT.schema.json"
GENERATION_PROFILE_REF = "EPOCH38_GENERATION_PROFILE.json"
AUTHORIZATION_POLICY_REF = "AUTHORIZATION_POLICY.json"
PREDECESSOR_REF = "evidence/engineering_dag/SHARED_CONTROL_BASELINE_LOCK/result.json"
CONTROL_STATE_REF = base.CONTROL_STATE_REF
CONTROL_EVENTS_REF = base.CONTROL_EVENTS_REF
TRANSACTION_REF = ".harness-foundry/control/transactions/CONTROL_PLANE_REGISTRATION.transaction.json"
LEASE_REF = ".harness-foundry/control/leases/CONTROL_PLANE_REGISTRATION.lease.json"
RESULT_REF = "evidence/engineering_dag/CONTROL_PLANE_REGISTRATION/result.json"
RECOVERY_REF = "evidence/engineering_dag/CONTROL_PLANE_REGISTRATION/recovery_receipt.json"
CRASH_POINTS = set(base.CRASH_POINTS)
PRODUCED_CAPABILITIES = ["CONTROL_PLANE_REGISTRATION_PASS"]
ASSURANCE_PROFILE = "SELF_USE_LOCAL_TRUSTED_OPERATOR"
LOCAL_ISSUER_ROLE = "LOCAL_TRUSTED_OPERATOR"
SIGNATURE_POLICY = "NOT_APPLICABLE_SELF_USE_LOCAL_TRUSTED_OPERATOR"
RUNTIME_INTERNAL_WRITE_REFS = [
    "harness-resource://execution/.harness-foundry/control/PROGRAM_CONTROL_STATE.json",
    "harness-resource://execution/.harness-foundry/control/PROGRAM_CONTROL_EVENTS.jsonl",
    (
        "harness-resource://execution/.harness-foundry/control/transactions/"
        "CONTROL_PLANE_REGISTRATION.transaction.json"
    ),
    (
        "harness-resource://execution/.harness-foundry/control/leases/"
        "CONTROL_PLANE_REGISTRATION.lease.json"
    ),
    "harness-resource://execution/evidence/engineering_dag/CONTROL_PLANE_REGISTRATION/result.json",
    (
        "harness-resource://execution/evidence/engineering_dag/"
        "CONTROL_PLANE_REGISTRATION/recovery_receipt.json"
    ),
]


ContractError = base.ContractError
InjectedCrash = base.InjectedCrash
canonical_bytes = base.canonical_bytes
json_hash = base.json_hash
file_hash = base.file_hash
hash_without = base.hash_without
read_json = base.read_json
atomic_json = base.atomic_json
exclusive_json = base.exclusive_json
append_event = base.append_event
read_events = base.read_events
require_equal = base.require_equal
candidate_identity = base.candidate_identity
utc_now = base.utc_now
file_hash_from_value = base.file_hash_from_value


def validate_static_contract(candidate_root: Path) -> dict[str, Any]:
    action_path = candidate_root / IMPLEMENTATION_REF
    contract_path = candidate_root / ACTION_CONTRACT_REF
    schema_path = candidate_root / RESULT_SCHEMA_REF
    contract = read_json(contract_path, "CONTROL_PLANE_REGISTRATION_CONTRACT_INVALID")
    profile_ref = contract.get("generation_profile_ref", GENERATION_PROFILE_REF)
    if profile_ref not in (GENERATION_PROFILE_REF, "validation/CONTROL_STARTUP_PROFILE.json"):
        raise ContractError("CONTROL_PLANE_REGISTRATION_CONTRACT_INVALID", "undeclared profile ref")
    profile_path = candidate_root / profile_ref
    policy_path = candidate_root / AUTHORIZATION_POLICY_REF
    for path in (
        action_path,
        contract_path,
        schema_path,
        profile_path,
        policy_path,
        _candidate_base(candidate_root),
    ):
        if not path.is_file():
            raise ContractError("CONTROL_PLANE_REGISTRATION_CONTRACT_INVALID", path.name)
    contract = read_json(
        contract_path, "CONTROL_PLANE_REGISTRATION_CONTRACT_INVALID"
    )
    schema = read_json(
        schema_path, "CONTROL_PLANE_REGISTRATION_RESULT_SCHEMA_INVALID"
    )
    profile = read_json(
        profile_path, "CONTROL_PLANE_REGISTRATION_CONTRACT_INVALID"
    )
    policy = read_json(
        policy_path, "CONTROL_PLANE_REGISTRATION_CONTRACT_INVALID"
    )
    module_hashes = _runtime_module_hashes(candidate_root, contract)
    authorization_profile = contract.get("authorization_profile")
    runtime_inputs = contract.get("runtime_input_contract")
    persistence = contract.get("persistence_contract")
    scope_contract = (
        authorization_profile.get("scope_contract")
        if isinstance(authorization_profile, Mapping)
        else None
    )
    profile_schemas = policy.get("profile_authorization_schemas")
    profile_authorizations = (
        profile_schemas.get(ASSURANCE_PROFILE)
        if isinstance(profile_schemas, Mapping)
        else None
    )
    profile_policy = (
        profile_authorizations.get("REGISTRATION_AUTHORIZATION")
        if isinstance(profile_authorizations, Mapping)
        else None
    )
    persistence_refs = (
        {
            value
            for key, value in persistence.items()
            if str(key).endswith("_ref") and isinstance(value, str)
        }
        if isinstance(persistence, Mapping)
        else set()
    )
    manifest = read_json(
        candidate_root / "THREE_PROJECT_PROGRAM_MANIFEST.json",
        "CONTROL_PLANE_REGISTRATION_CONTRACT_INVALID",
    )
    epoch_domains = manifest.get("epoch_domains")
    if (
        contract.get("action_id") != ACTION_ID
        or contract.get("node_id") != NODE_ID
        or contract.get("implementation_ref") != IMPLEMENTATION_REF
        or contract.get("executor_implementation_sha256") != file_hash(action_path)
        or contract.get("result_schema_ref") != RESULT_SCHEMA_REF
        or contract.get("result_schema_sha256") != file_hash(schema_path)
        or not isinstance(epoch_domains, Mapping)
        or contract.get("epoch_domain_contract") != epoch_domains
        or contract.get("runtime_module_sha256s") != module_hashes
        or contract.get("runtime_bundle_sha256") != json_hash(module_hashes)
        or contract.get("contract_sha256") != hash_without(contract, "contract_sha256")
        or profile.get("assurance_profile") != ASSURANCE_PROFILE
        or not isinstance(authorization_profile, Mapping)
        or authorization_profile.get("assurance_profile") != ASSURANCE_PROFILE
        or authorization_profile.get("issuer_role") != LOCAL_ISSUER_ROLE
        or authorization_profile.get("max_transitions") != 1
        or authorization_profile.get("delegation_allowed") is not False
        or authorization_profile.get("signature_policy") != SIGNATURE_POLICY
        or authorization_profile.get("signature_value") is not None
        or authorization_profile.get("external_cryptographic_signature_required")
        is not False
        or not isinstance(runtime_inputs, Mapping)
        or authorization_profile.get("required_fields")
        != runtime_inputs.get("authorization_required_fields")
        or profile_policy != authorization_profile
        or contract.get("runtime_internal_write_refs")
        != RUNTIME_INTERNAL_WRITE_REFS
        or not isinstance(scope_contract, Mapping)
        or scope_contract.get("runtime_internal_write_refs")
        != RUNTIME_INTERNAL_WRITE_REFS
        or persistence_refs != set(RUNTIME_INTERNAL_WRITE_REFS)
        or any(
            not ref.startswith("harness-resource://execution/")
            for ref in RUNTIME_INTERNAL_WRITE_REFS
        )
    ):
        raise ContractError(
            "CONTROL_PLANE_REGISTRATION_CONTRACT_INVALID",
            "static executable or runtime-module hash binding failed",
        )
    required = contract.get("execution_contract", {}).get("required_result_fields")
    if (
        not isinstance(required, list)
        or schema.get("required") != required
        or set(schema.get("properties", {})) != set(required)
        or schema.get("additionalProperties") is not False
    ):
        raise ContractError(
            "CONTROL_PLANE_REGISTRATION_RESULT_SCHEMA_INVALID",
            "schema does not exactly close over the declared result fields",
        )
    return contract


def _candidate_base(candidate_root: Path) -> Path:
    return candidate_root / "tools/shared_control_baseline.py"


def _runtime_module_hashes(
    candidate_root: Path, contract: Mapping[str, Any]
) -> dict[str, str]:
    refs = contract.get("runtime_module_refs")
    if not isinstance(refs, list) or not refs:
        raise ContractError(
            "CONTROL_PLANE_REGISTRATION_CONTRACT_INVALID",
            "runtime_module_refs must be a non-empty list",
        )
    hashes: dict[str, str] = {}
    for value in refs:
        ref = str(value)
        relative = Path(ref)
        path = candidate_root / relative
        if relative.is_absolute() or ".." in relative.parts or not path.is_file():
            raise ContractError("CONTROL_PLANE_RUNTIME_MODULE_INVALID", ref)
        hashes[ref] = file_hash(path)
    return hashes


def validate_result_document(
    result: Mapping[str, Any], schema: Mapping[str, Any], contract: Mapping[str, Any]
) -> None:
    required = schema.get("required")
    properties = schema.get("properties")
    if not isinstance(required, list) or not isinstance(properties, Mapping):
        raise ContractError(
            "CONTROL_PLANE_REGISTRATION_RESULT_SCHEMA_INVALID", "invalid schema"
        )
    if set(result) != set(required):
        raise ContractError(
            "CONTROL_PLANE_REGISTRATION_RESULT_INVALID", "result fields are not exact"
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
                "CONTROL_PLANE_REGISTRATION_RESULT_SCHEMA_INVALID", field
            )
        expected_type = type_map.get(str(rule.get("type")))
        value = result.get(field)
        if expected_type is None or not isinstance(value, expected_type) or (
            expected_type is int and isinstance(value, bool)
        ):
            raise ContractError("CONTROL_PLANE_REGISTRATION_RESULT_INVALID", field)
        if "const" in rule and value != rule["const"]:
            raise ContractError("CONTROL_PLANE_REGISTRATION_RESULT_INVALID", field)
        pattern = rule.get("pattern")
        if pattern and (
            not isinstance(value, str)
            or re.fullmatch(str(pattern), value) is None
        ):
            raise ContractError("CONTROL_PLANE_REGISTRATION_RESULT_INVALID", field)
    require_equal(
        result.get("control_runtime_module_sha256s"),
        contract["runtime_module_sha256s"],
        "CONTROL_PLANE_REGISTRATION_RESULT_INVALID",
        "control_runtime_module_sha256s",
    )
    require_equal(
        result.get("control_runtime_bundle_sha256"),
        contract["runtime_bundle_sha256"],
        "CONTROL_PLANE_REGISTRATION_RESULT_INVALID",
        "control_runtime_bundle_sha256",
    )
    require_equal(
        result.get("produced_capabilities"),
        PRODUCED_CAPABILITIES,
        "CONTROL_PLANE_REGISTRATION_RESULT_INVALID",
        "produced_capabilities",
    )
    require_equal(
        result.get("result_sha256"),
        hash_without(result, "result_sha256"),
        "CONTROL_PLANE_REGISTRATION_RESULT_INVALID",
        "result_sha256",
    )


def _validate_runtime_inputs(
    candidate_root: Path,
    execution_root: Path,
    command_path: Path,
    authorization_path: Path,
    *,
    recovery_event: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    contract = validate_static_contract(candidate_root)
    implementation_sha = file_hash(candidate_root / IMPLEMENTATION_REF)
    action_contract_sha = file_hash(candidate_root / ACTION_CONTRACT_REF)
    schema_sha = file_hash(candidate_root / RESULT_SCHEMA_REF)
    module_hashes = _runtime_module_hashes(candidate_root, contract)
    runtime_bundle_sha = json_hash(module_hashes)
    candidate_sha = candidate_identity(candidate_root)
    inputs = base._resolve_candidate_inputs(candidate_root)
    predecessor_path = execution_root / PREDECESSOR_REF
    state_path = execution_root / CONTROL_STATE_REF
    predecessor = read_json(
        predecessor_path, "SHARED_CONTROL_BASELINE_RESULT_INVALID"
    )
    predecessor_sha = file_hash(predecessor_path)
    state = read_json(state_path, "PROGRAM_CONTROL_STATE_INVALID")
    command = read_json(command_path, "COMMAND_MANIFEST_INVALID")
    authorization = read_json(
        authorization_path, "REGISTRATION_AUTHORIZATION_INVALID"
    )
    command_sha = file_hash(command_path)
    authorization_sha = file_hash(authorization_path)
    state_sha = file_hash(state_path)

    shared_contract = base.validate_static_contract(candidate_root)
    shared_schema = read_json(candidate_root / base.RESULT_SCHEMA_REF)
    base.validate_result_document(predecessor, shared_schema, shared_contract)
    require_equal(predecessor.get("node_id"), "SHARED_CONTROL_BASELINE_LOCK", "SHARED_CONTROL_BASELINE_RESULT_INVALID", "node_id")
    require_equal(predecessor.get("status"), "PASS", "SHARED_CONTROL_BASELINE_RESULT_INVALID", "status")
    require_equal(predecessor.get("candidate_tree_sha256"), candidate_sha, "SHARED_CONTROL_BASELINE_RESULT_INVALID", "candidate_tree_sha256")
    require_equal(predecessor.get("requirement_ir_sha256"), inputs["requirement_ir_sha256"], "SHARED_CONTROL_BASELINE_RESULT_INVALID", "requirement_ir_sha256")
    require_equal(predecessor.get("control_plane_epoch"), inputs["execution_control_plane_epoch"], "SHARED_CONTROL_BASELINE_RESULT_INVALID", "control_plane_epoch")

    checks = {
        "action_id": ACTION_ID,
        "node_id": NODE_ID,
        "executor_implementation_ref": IMPLEMENTATION_REF,
        "executor_implementation_sha256": implementation_sha,
        "action_contract_sha256": action_contract_sha,
        "result_schema_sha256": schema_sha,
        "candidate_tree_sha256": candidate_sha,
        "requirement_ir_sha256": inputs["requirement_ir_sha256"],
        "shared_control_baseline_result_sha256": predecessor_sha,
        "control_runtime_bundle_sha256": runtime_bundle_sha,
        "expected_control_state_sha256": state_sha,
    }
    for field, expected in checks.items():
        code = (
            "UNBOUND_OR_DRIFTED_CONTROL_ACTION_IMPLEMENTATION"
            if field.startswith("executor_")
            else "COMMAND_MANIFEST_INVALID"
        )
        require_equal(command.get(field), expected, code, field)

    required_authorization_fields = contract["runtime_input_contract"][
        "authorization_required_fields"
    ]
    if set(authorization) != set(required_authorization_fields):
        raise ContractError(
            "REGISTRATION_AUTHORIZATION_INVALID",
            "authorization fields do not exactly match the local profile schema",
        )
    if authorization.get("status") == "REVOKED":
        raise ContractError(
            "REGISTRATION_AUTHORIZATION_REVOKED", "authorization is revoked"
        )
    expected_scope = {
        "program_id": inputs["program_id"],
        "node_id": NODE_ID,
        "allowed_action_id": ACTION_ID,
        "execution_mode": "REGISTRATION_ONLY",
        "runtime_internal_write_refs": RUNTIME_INTERNAL_WRITE_REFS,
    }
    authorization_checks = {
        "schema_version": "1.0",
        "status": "GRANTED",
        "authorization_class": "REGISTRATION_AUTHORIZATION",
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
        "human_approval_receipt_sha256": predecessor.get(
            "human_approval_receipt_sha256"
        ),
        "shared_control_baseline_result_sha256": predecessor_sha,
        "control_runtime_bundle_sha256": runtime_bundle_sha,
        "expected_control_state_sha256": state_sha,
        "max_transitions": 1,
        "delegation_allowed": False,
        "signature_policy": SIGNATURE_POLICY,
        "signature": None,
    }
    for field, expected in authorization_checks.items():
        code = (
            "UNBOUND_OR_DRIFTED_CONTROL_ACTION_IMPLEMENTATION"
            if field == "executor_implementation_sha256"
            else "REGISTRATION_AUTHORIZATION_INVALID"
        )
        require_equal(authorization.get(field), expected, code, field)
    authorization_id = authorization.get("authorization_id")
    if not isinstance(authorization_id, str) or not authorization_id:
        raise ContractError(
            "REGISTRATION_AUTHORIZATION_INVALID", "authorization_id is required"
        )
    issued_at = base.parse_time(authorization.get("issued_at"), "issued_at")
    not_before = base.parse_time(authorization.get("not_before"), "not_before")
    expires_at = base.parse_time(authorization.get("expires_at"), "expires_at")
    now = datetime.now(timezone.utc)
    if issued_at > not_before or not_before > now or expires_at <= now:
        raise ContractError(
            "REGISTRATION_AUTHORIZATION_INVALID",
            "authorization is outside its validity window",
        )

    require_equal(state.get("state_sha256"), hash_without(state, "state_sha256"), "PROGRAM_CONTROL_STATE_INVALID", "state_sha256")
    require_equal(state.get("program_id"), inputs["program_id"], "PROGRAM_CONTROL_STATE_INVALID", "program_id")
    require_equal(state.get("epoch_domains"), inputs["epoch_domains"], "PROGRAM_CONTROL_STATE_INVALID", "epoch_domains")
    require_equal(state.get("control_plane_epoch"), inputs["execution_control_plane_epoch"], "PROGRAM_CONTROL_STATE_INVALID", "control_plane_epoch")
    require_equal(state.get("last_completed_node"), "SHARED_CONTROL_BASELINE_LOCK", "PROGRAM_CONTROL_STATE_INVALID", "last_completed_node")
    require_equal(state.get("next_node"), NODE_ID, "PROGRAM_CONTROL_STATE_INVALID", "next_node")
    require_equal(state.get("authorization_status"), "GRANTED", "PROGRAM_CONTROL_STATE_INVALID", "authorization_status")
    require_equal(state.get("active_authorization_id"), authorization.get("authorization_id"), "PROGRAM_CONTROL_STATE_INVALID", "active_authorization_id")
    require_equal(state.get("remaining_transition_budget"), 1, "PROGRAM_CONTROL_STATE_INVALID", "remaining_transition_budget")
    require_equal(state.get("driver_started"), False, "PROGRAM_CONTROL_STATE_INVALID", "driver_started")
    require_equal(state.get("active_workpack"), None, "PROGRAM_CONTROL_STATE_INVALID", "active_workpack")
    events = read_events(execution_root / CONTROL_EVENTS_REF)
    actual_tip = events[-1]["event_hash"] if events else None
    state_tip = state.get("last_event_hash")
    if actual_tip != state_tip:
        if not (
            isinstance(recovery_event, Mapping)
            and actual_tip == recovery_event.get("event_hash")
            and recovery_event.get("previous_event_hash") == state_tip
            and events[-1] == recovery_event
        ):
            raise ContractError(
                "CONTROL_EVENT_LEDGER_INVALID",
                "last_event_hash does not match the control state or prepared transaction",
            )

    fencing = authorization.get("fencing_token")
    if not isinstance(fencing, int) or isinstance(fencing, bool) or fencing < 1:
        raise ContractError(
            "FENCING_TOKEN_INVALID", "fencing_token must be a positive integer"
        )
    require_equal(fencing, state.get("next_fencing_token"), "FENCING_TOKEN_REGRESSION", "fencing_token")
    require_equal(command.get("fencing_token"), fencing, "COMMAND_MANIFEST_INVALID", "fencing_token")
    lease_id = authorization.get("lease_id")
    if not isinstance(lease_id, str) or not lease_id:
        raise ContractError("LEASE_ID_INVALID", "lease_id is required")
    require_equal(command.get("lease_id"), lease_id, "COMMAND_MANIFEST_INVALID", "lease_id")
    expected_idempotency = json_hash(
        {
            "action_id": ACTION_ID,
            "authorization_id": authorization.get("authorization_id"),
            "candidate_tree_sha256": candidate_sha,
            "fencing_token": fencing,
            "lease_id": lease_id,
            "requirement_ir_sha256": inputs["requirement_ir_sha256"],
            "shared_control_baseline_result_sha256": predecessor_sha,
            "control_runtime_bundle_sha256": runtime_bundle_sha,
        }
    )
    require_equal(command.get("idempotency_key"), expected_idempotency, "IDEMPOTENCY_KEY_INVALID", "command idempotency_key")
    require_equal(authorization.get("idempotency_key"), expected_idempotency, "IDEMPOTENCY_KEY_INVALID", "authorization idempotency_key")
    require_equal(command.get("authorization_id"), authorization.get("authorization_id"), "COMMAND_MANIFEST_INVALID", "authorization_id")

    return {
        "contract": contract,
        "inputs": inputs,
        "command_sha": command_sha,
        "authorization": authorization,
        "authorization_sha": authorization_sha,
        "state": state,
        "state_sha": state_sha,
        "candidate_sha": candidate_sha,
        "implementation_sha": implementation_sha,
        "action_contract_sha": action_contract_sha,
        "schema_sha": schema_sha,
        "predecessor_sha": predecessor_sha,
        "module_hashes": module_hashes,
        "runtime_bundle_sha": runtime_bundle_sha,
        "idempotency_key": expected_idempotency,
        "lease_id": lease_id,
        "fencing_token": fencing,
    }


def _crash(point: str, crash_after: str | None) -> None:
    if crash_after == point:
        raise InjectedCrash(point)


def _validate_transaction(
    transaction: Mapping[str, Any],
    contract: Mapping[str, Any],
    schema: Mapping[str, Any],
) -> None:
    if transaction.get("transaction_sha256") != hash_without(
        transaction, "transaction_sha256"
    ):
        raise ContractError("TRANSACTION_JOURNAL_INVALID", "transaction hash is invalid")
    result = transaction.get("result_payload")
    event = transaction.get("event_payload")
    if not isinstance(result, Mapping) or not isinstance(event, Mapping):
        raise ContractError(
            "TRANSACTION_JOURNAL_INVALID", "result or event payload is missing"
        )
    next_state = transaction.get("next_state_payload")
    prior_state = transaction.get("prior_state_payload")
    if not all(
        isinstance(value, Mapping)
        for value in (result, event, next_state, prior_state)
    ):
        raise ContractError("TRANSACTION_JOURNAL_INVALID", "transaction payload is incomplete")
    validate_result_document(result, schema, contract)
    require_equal(transaction.get("result_file_sha256"), file_hash_from_value(result), "TRANSACTION_JOURNAL_INVALID", "result_file_sha256")
    require_equal(event.get("event_hash"), hash_without(event, "event_hash"), "TRANSACTION_JOURNAL_INVALID", "event_hash")
    require_equal(next_state.get("state_sha256"), hash_without(next_state, "state_sha256"), "TRANSACTION_JOURNAL_INVALID", "next state hash")
    require_equal(prior_state.get("state_sha256"), hash_without(prior_state, "state_sha256"), "TRANSACTION_JOURNAL_INVALID", "prior state hash")


def _commit_transaction(
    execution_root: Path,
    prepared: Mapping[str, Any],
    crash_after: str | None,
    *,
    was_recovery: bool,
) -> str:
    transaction_path = execution_root / TRANSACTION_REF
    result_path = execution_root / RESULT_REF
    event_path = execution_root / CONTROL_EVENTS_REF
    state_path = execution_root / CONTROL_STATE_REF
    recovery_path = execution_root / RECOVERY_REF
    transaction = dict(prepared)
    recovered_from = str(transaction.get("transaction_state"))

    if transaction.get("transaction_state") == "PREPARED":
        _crash("AFTER_PREPARE_BEFORE_RESULT_RENAME", crash_after)
        if result_path.exists():
            require_equal(file_hash(result_path), transaction["result_file_sha256"], "UNKNOWN_COMMIT_STATE", "result")
        else:
            atomic_json(result_path, transaction["result_payload"])
        transaction["transaction_state"] = "RESULT_COMMITTED"
        transaction["transaction_sha256"] = hash_without(transaction, "transaction_sha256")
        atomic_json(transaction_path, transaction)

    if transaction.get("transaction_state") == "RESULT_COMMITTED":
        _crash("AFTER_RESULT_RENAME_BEFORE_EVENT_APPEND", crash_after)
        events = read_events(event_path)
        matches = [event for event in events if event.get("idempotency_key") == transaction["idempotency_key"]]
        if len(matches) > 1:
            raise ContractError("DUPLICATE_CONTROL_EVENT", "duplicate idempotency event")
        if matches:
            require_equal(matches[0], transaction["event_payload"], "UNKNOWN_COMMIT_STATE", "event")
        else:
            append_event(event_path, transaction["event_payload"])
        transaction["transaction_state"] = "CONTROL_EVENT_COMMITTED"
        transaction["transaction_sha256"] = hash_without(transaction, "transaction_sha256")
        atomic_json(transaction_path, transaction)

    if transaction.get("transaction_state") == "CONTROL_EVENT_COMMITTED":
        _crash("AFTER_EVENT_APPEND_BEFORE_STATE_REPLACE", crash_after)
        current = read_json(state_path, "PROGRAM_CONTROL_STATE_INVALID")
        if current.get("state_sha256") == transaction["next_state_payload"]["state_sha256"]:
            pass
        elif file_hash(state_path) == transaction["previous_state_file_sha256"]:
            atomic_json(state_path, transaction["next_state_payload"])
        else:
            raise ContractError("UNKNOWN_COMMIT_STATE", "control state CAS failed")
        transaction["transaction_state"] = "STATE_COMMITTED"
        transaction["transaction_sha256"] = hash_without(transaction, "transaction_sha256")
        atomic_json(transaction_path, transaction)

    if transaction.get("transaction_state") != "STATE_COMMITTED":
        raise ContractError("UNKNOWN_COMMIT_STATE", "transaction state is not recognized")
    _crash("AFTER_STATE_REPLACE_BEFORE_RESPONSE", crash_after)
    atomic_json(
        recovery_path,
        {
            "schema_version": "1.0",
            "action_id": ACTION_ID,
            "node_id": NODE_ID,
            "idempotency_key": transaction["idempotency_key"],
            "transaction_sha256": file_hash(transaction_path),
            "recovered": was_recovery,
            "recovered_from_state": recovered_from,
            "duplicate_side_effect_count": 0,
            "status": "PASS",
        },
    )
    if was_recovery and recovered_from == "STATE_COMMITTED":
        return "ALREADY_COMMITTED"
    return "RECOVERED_AND_COMMITTED" if was_recovery else "COMMITTED"


def _validate_recovery_inputs(
    candidate_root: Path,
    execution_root: Path,
    command_path: Path,
    authorization_path: Path,
    transaction: Mapping[str, Any],
) -> dict[str, Any]:
    current = read_json(execution_root / CONTROL_STATE_REF, "PROGRAM_CONTROL_STATE_INVALID")
    final_state = transaction.get("next_state_payload")
    prior_state = transaction.get("prior_state_payload")
    if not isinstance(final_state, Mapping) or not isinstance(prior_state, Mapping):
        raise ContractError("TRANSACTION_JOURNAL_INVALID", "state payload is missing")
    if current.get("state_sha256") == prior_state.get("state_sha256"):
        runtime = _validate_runtime_inputs(
            candidate_root,
            execution_root,
            command_path,
            authorization_path,
            recovery_event=(
                transaction.get("event_payload")
                if isinstance(transaction.get("event_payload"), Mapping)
                else None
            ),
        )
        require_equal(runtime["candidate_sha"], transaction.get("candidate_tree_sha256"), "UNKNOWN_COMMIT_STATE", "candidate")
        require_equal(runtime["command_sha"], transaction.get("command_manifest_sha256"), "UNKNOWN_COMMIT_STATE", "command")
        require_equal(runtime["authorization_sha"], transaction.get("authorization_sha256"), "UNKNOWN_COMMIT_STATE", "authorization")
        require_equal(runtime["implementation_sha"], transaction.get("executor_implementation_sha256"), "UNKNOWN_COMMIT_STATE", "executor")
        return runtime
    if current.get("state_sha256") != final_state.get("state_sha256"):
        raise ContractError("UNKNOWN_COMMIT_STATE", "control state is unrelated to the transaction")

    contract = validate_static_contract(candidate_root)
    candidate_sha = candidate_identity(candidate_root)
    inputs = base._resolve_candidate_inputs(candidate_root)
    command = read_json(command_path, "COMMAND_MANIFEST_INVALID")
    authorization = read_json(authorization_path, "REGISTRATION_AUTHORIZATION_INVALID")
    predecessor_path = execution_root / PREDECESSOR_REF
    predecessor_sha = file_hash(predecessor_path)
    implementation_sha = file_hash(candidate_root / IMPLEMENTATION_REF)
    command_sha = file_hash(command_path)
    authorization_sha = file_hash(authorization_path)
    require_equal(candidate_sha, transaction.get("candidate_tree_sha256"), "UNKNOWN_COMMIT_STATE", "candidate")
    require_equal(command_sha, transaction.get("command_manifest_sha256"), "UNKNOWN_COMMIT_STATE", "command")
    require_equal(authorization_sha, transaction.get("authorization_sha256"), "UNKNOWN_COMMIT_STATE", "authorization")
    require_equal(implementation_sha, transaction.get("executor_implementation_sha256"), "UNBOUND_OR_DRIFTED_CONTROL_ACTION_IMPLEMENTATION", "executor")
    require_equal(command.get("action_id"), ACTION_ID, "COMMAND_MANIFEST_INVALID", "action_id")
    require_equal(command.get("node_id"), NODE_ID, "COMMAND_MANIFEST_INVALID", "node_id")
    require_equal(command.get("idempotency_key"), transaction.get("idempotency_key"), "IDEMPOTENCY_KEY_CONFLICT", "command idempotency_key")
    require_equal(command.get("shared_control_baseline_result_sha256"), predecessor_sha, "SHARED_CONTROL_BASELINE_RESULT_INVALID", "command predecessor hash")
    require_equal(command.get("control_runtime_bundle_sha256"), contract["runtime_bundle_sha256"], "CONTROL_PLANE_RUNTIME_MODULE_INVALID", "command runtime bundle")
    require_equal(authorization.get("idempotency_key"), transaction.get("idempotency_key"), "IDEMPOTENCY_KEY_CONFLICT", "authorization idempotency_key")
    require_equal(authorization.get("status"), "GRANTED", "REGISTRATION_AUTHORIZATION_INVALID", "status")
    require_equal(authorization.get("one_shot"), True, "REGISTRATION_AUTHORIZATION_INVALID", "one_shot")
    require_equal(authorization.get("program_id"), inputs["program_id"], "REGISTRATION_AUTHORIZATION_INVALID", "program_id")
    require_equal(authorization.get("shared_control_baseline_result_sha256"), predecessor_sha, "REGISTRATION_AUTHORIZATION_INVALID", "authorization predecessor hash")
    require_equal(authorization.get("control_runtime_bundle_sha256"), contract["runtime_bundle_sha256"], "REGISTRATION_AUTHORIZATION_INVALID", "authorization runtime bundle")
    if (
        base.parse_time(authorization.get("not_before"), "not_before")
        > datetime.now(timezone.utc)
        or base.parse_time(authorization.get("expires_at"), "expires_at")
        <= datetime.now(timezone.utc)
    ):
        raise ContractError(
            "REGISTRATION_AUTHORIZATION_INVALID",
            "authorization is outside its validity window",
        )
    result = transaction.get("result_payload")
    event = transaction.get("event_payload")
    require_equal(result.get("shared_control_baseline_result_sha256"), predecessor_sha, "UNKNOWN_COMMIT_STATE", "result predecessor hash")
    require_equal(result.get("control_runtime_bundle_sha256"), contract["runtime_bundle_sha256"], "UNKNOWN_COMMIT_STATE", "result runtime bundle")
    events = read_events(execution_root / CONTROL_EVENTS_REF)
    matches = [
        item
        for item in events
        if item.get("idempotency_key") == transaction.get("idempotency_key")
    ]
    if len(matches) != 1 or matches[0] != event:
        raise ContractError(
            "UNKNOWN_COMMIT_STATE", "committed control event is missing or duplicated"
        )
    require_equal(current.get("last_event_hash"), event.get("event_hash"), "UNKNOWN_COMMIT_STATE", "committed event tip")
    return {
        "contract": contract,
        "idempotency_key": transaction.get("idempotency_key"),
    }


def _prepare_transaction(candidate_root: Path, execution_root: Path, runtime: Mapping[str, Any]) -> dict[str, Any]:
    """Build validated payloads; never commit a lease, journal, result or state."""
    schema = read_json(candidate_root / RESULT_SCHEMA_REF)
    started_at = utc_now()
    result = {
        "schema_version": "1.0",
        "result_id": f"{NODE_ID}-{runtime['idempotency_key'][:16]}",
        "program_id": runtime["inputs"]["program_id"],
        "node_id": NODE_ID,
        "status": "PASS",
        "execution_mode": "REGISTRATION_ONLY",
        "control_plane_epoch": runtime["inputs"]["control_plane_epoch"],
        "candidate_tree_sha256": runtime["candidate_sha"],
        "requirement_ir_sha256": runtime["inputs"]["requirement_ir_sha256"],
        "shared_control_baseline_result_sha256": runtime["predecessor_sha"],
        "control_runtime_module_sha256s": runtime["module_hashes"],
        "control_runtime_bundle_sha256": runtime["runtime_bundle_sha"],
        "command_manifest_sha256": runtime["command_sha"],
        "executor_implementation_sha256": runtime["implementation_sha"],
        "action_contract_sha256": runtime["action_contract_sha"],
        "result_schema_sha256": runtime["schema_sha"],
        "authorization_id": runtime["authorization"]["authorization_id"],
        "authorization_sha256": runtime["authorization_sha"],
        "idempotency_key": runtime["idempotency_key"],
        "lease_id": runtime["lease_id"],
        "fencing_token": runtime["fencing_token"],
        "produced_capabilities": list(PRODUCED_CAPABILITIES),
        "driver_started": False,
        "workpack_started": False,
        "started_at": started_at,
        "completed_at": utc_now(),
        "result_sha256": "",
    }
    result["result_sha256"] = hash_without(result, "result_sha256")
    validate_result_document(result, schema, runtime["contract"])

    previous_event_hash = runtime["state"].get("last_event_hash")
    event = {
        "schema_version": "1.0",
        "event_type": "CONTROL_PLANE_REGISTRATION_COMMITTED",
        "program_id": runtime["inputs"]["program_id"],
        "node_id": NODE_ID,
        "idempotency_key": runtime["idempotency_key"],
        "authorization_id": runtime["authorization"]["authorization_id"],
        "authorization_sha256": runtime["authorization_sha"],
        "executor_implementation_sha256": runtime["implementation_sha"],
        "control_runtime_bundle_sha256": runtime["runtime_bundle_sha"],
        "result_sha256": file_hash_from_value(result),
        "previous_event_hash": previous_event_hash,
        "fencing_token": runtime["fencing_token"],
    }
    event["event_hash"] = hash_without(event, "event_hash")
    next_state = dict(runtime["state"])
    next_state.update(
        {
            "revision": int(runtime["state"].get("revision", 0)) + 1,
            "last_completed_node": NODE_ID,
            "next_node": NEXT_NODE_ID,
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
    prepared = {
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
        "previous_state_file_sha256": runtime["state_sha"],
        "prior_state_payload": runtime["state"],
        "result_payload": result,
        "result_file_sha256": file_hash_from_value(result),
        "event_payload": event,
        "next_state_payload": next_state,
        "transaction_sha256": "",
    }
    prepared["transaction_sha256"] = hash_without(prepared, "transaction_sha256")
    return prepared


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
    *,
    crash_after: str | None = None,
) -> dict[str, Any]:
    if (execution_root / ".harness-foundry/control.sqlite3").exists():
        raise ContractError("SQLITE_CONTROLLER_OWNS_STATE", "use read-only preparation through the authoritative controller")
    if candidate_root.is_symlink() or execution_root.is_symlink():
        raise ContractError("CANDIDATE_EXECUTION_ROOT_OVERLAP", "root symlinks are forbidden")
    candidate_root = candidate_root.resolve()
    execution_root = execution_root.resolve()
    if candidate_root == execution_root or candidate_root in execution_root.parents or execution_root in candidate_root.parents:
        raise ContractError("CANDIDATE_EXECUTION_ROOT_OVERLAP", "Candidate and execution roots must be disjoint")
    if crash_after is not None and crash_after not in CRASH_POINTS:
        raise ContractError("CRASH_POINT_INVALID", crash_after)
    for supplied, label in ((command_manifest_path, "command manifest"), (authorization_path, "authorization")):
        resolved = supplied.resolve()
        if supplied.is_symlink() or not resolved.is_relative_to(execution_root):
            raise ContractError("CONTROL_ACTION_INPUT_INVALID", f"{label} must be under the execution root")

    transaction_path = execution_root / TRANSACTION_REF
    schema = read_json(candidate_root / RESULT_SCHEMA_REF)
    if transaction_path.exists():
        transaction = read_json(transaction_path, "TRANSACTION_JOURNAL_INVALID")
        runtime = _validate_recovery_inputs(candidate_root, execution_root, command_manifest_path, authorization_path, transaction)
        _validate_transaction(transaction, runtime["contract"], schema)
        disposition = _commit_transaction(execution_root, transaction, crash_after, was_recovery=True)
        result = read_json(execution_root / RESULT_REF, "CONTROL_PLANE_REGISTRATION_RESULT_INVALID")
        validate_result_document(result, schema, runtime["contract"])
        return {"status": "PASS", "disposition": disposition, "result": result}

    runtime = _validate_runtime_inputs(candidate_root, execution_root, command_manifest_path, authorization_path)
    lease_path = execution_root / LEASE_REF
    lease_payload = {
        "schema_version": "1.0",
        "action_id": ACTION_ID,
        "lease_id": runtime["lease_id"],
        "idempotency_key": runtime["idempotency_key"],
        "fencing_token": runtime["fencing_token"],
        "status": "ACQUIRED",
    }
    if lease_path.exists():
        require_equal(read_json(lease_path), lease_payload, "LEASE_CONFLICT", "lease")
    else:
        try:
            exclusive_json(lease_path, lease_payload)
        except FileExistsError:
            require_equal(read_json(lease_path), lease_payload, "LEASE_CONFLICT", "lease")

    prepared = _prepare_transaction(candidate_root, execution_root, runtime)
    result = prepared["result_payload"]
    try:
        exclusive_json(transaction_path, prepared)
    except FileExistsError:
        raise ContractError("TRANSACTION_CONFLICT", "another executor created the transaction") from None
    disposition = _commit_transaction(execution_root, prepared, crash_after, was_recovery=False)
    return {"status": "PASS", "disposition": disposition, "result": result}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-contract")
    validate.add_argument("--candidate-root", type=Path, default=Path(__file__).resolve().parents[1])
    run = subparsers.add_parser("execute")
    run.add_argument("--candidate-root", type=Path, default=Path(__file__).resolve().parents[1])
    run.add_argument("--execution-root", type=Path, required=True)
    run.add_argument("--command-manifest", type=Path, required=True)
    run.add_argument("--authorization", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-contract":
            contract = validate_static_contract(args.candidate_root.resolve())
            output = {
                "status": "PASS",
                "action_id": contract["action_id"],
                "executor_implementation_sha256": contract["executor_implementation_sha256"],
                "runtime_bundle_sha256": contract["runtime_bundle_sha256"],
            }
        else:
            output = execute_action(
                args.candidate_root,
                args.execution_root,
                args.command_manifest.resolve(),
                args.authorization.resolve(),
            )
    except ContractError as exc:
        print(json.dumps({"status": "FAIL", "code": exc.code, "message": exc.message}, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
