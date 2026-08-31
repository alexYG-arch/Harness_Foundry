"""One-shot structural validation for a materialized Main Execution Package.

This provider is packaged into a generated Candidate for use by a separately
authorized sibling Runtime.  It reads the predecessor repository without
executing it, validates the exact structural package contract, then commits one
result, one event, and one control-state CAS.  It never starts the successor.
"""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
from typing import Any, Mapping


TOOLS_ROOT = Path(__file__).resolve().parent


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"portable runtime module is missing: {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load_module(
    "harness_foundry_package_validation_base",
    TOOLS_ROOT.parent / "shared_control_baseline.py",
)


ACTION_ID = "VALIDATE-MAIN-EXECUTION-PACKAGE-STRUCTURE"
NODE_ID = "MAIN_EXECUTION_PACKAGE_VALIDATED"
NEXT_NODE_ID = "MAIN_PROGRAM_REGISTRATION"
PREDECESSOR_NODE_ID = "MAIN_EXECUTION_PACKAGE_MATERIALIZED"
WORKPACK_ID = "WP-HARNESS-FOUNDRY-V2-9-CHAT-FACTORY-G0-001"
IMPLEMENTATION_REF = (
    "tools/harness_foundry_runtime/main_execution_package_validation.py"
)
ENTRYPOINT_REF = "tools/main_execution_package_validation.py"
ACTION_CONTRACT_REF = (
    "validation/MAIN_EXECUTION_PACKAGE_VALIDATION_ACTION_CONTRACT.json"
)
RESULT_SCHEMA_REF = (
    "contracts/MAIN_EXECUTION_PACKAGE_VALIDATION_RESULT.schema.json"
)
GENERATION_PROFILE_REF = "EPOCH38_GENERATION_PROFILE.json"
AUTHORIZATION_POLICY_REF = "AUTHORIZATION_POLICY.json"
PREDECESSOR_RESULT_REF = (
    "evidence/engineering_dag/MAIN_EXECUTION_PACKAGE_MATERIALIZED/result.json"
)
REPOSITORY_REF = "project_start_packages/main_build/repository"
CONTROL_STATE_REF = base.CONTROL_STATE_REF
CONTROL_EVENTS_REF = base.CONTROL_EVENTS_REF
TRANSACTION_REF = (
    ".harness-foundry/control/transactions/"
    "MAIN_EXECUTION_PACKAGE_VALIDATED.transaction.json"
)
LEASE_REF = (
    ".harness-foundry/control/leases/"
    "MAIN_EXECUTION_PACKAGE_VALIDATED.lease.json"
)
RESULT_REF = (
    "evidence/engineering_dag/MAIN_EXECUTION_PACKAGE_VALIDATED/result.json"
)
NODE_EVIDENCE_WRITE_REF = (
    "harness-resource://execution/evidence/engineering_dag/"
    "MAIN_EXECUTION_PACKAGE_VALIDATED"
)
VALIDATION_SCOPE = "STRUCTURAL_PACKAGE_CONTRACT_ONLY"
PRODUCED_CAPABILITIES = ["MAIN_EXECUTION_PACKAGE_VALIDATED_PASS"]
ASSURANCE_PROFILE = "SELF_USE_LOCAL_TRUSTED_OPERATOR"
LOCAL_ISSUER_ROLE = "LOCAL_TRUSTED_OPERATOR"
SIGNATURE_POLICY = "NOT_APPLICABLE_SELF_USE_LOCAL_TRUSTED_OPERATOR"
RUNTIME_INTERNAL_WRITE_REFS = [
    "harness-resource://execution/.harness-foundry/control/PROGRAM_CONTROL_STATE.json",
    "harness-resource://execution/.harness-foundry/control/PROGRAM_CONTROL_EVENTS.jsonl",
    (
        "harness-resource://execution/.harness-foundry/control/transactions/"
        "MAIN_EXECUTION_PACKAGE_VALIDATED.transaction.json"
    ),
    (
        "harness-resource://execution/.harness-foundry/control/leases/"
        "MAIN_EXECUTION_PACKAGE_VALIDATED.lease.json"
    ),
    (
        "harness-resource://execution/evidence/engineering_dag/"
        "MAIN_EXECUTION_PACKAGE_VALIDATED/result.json"
    ),
]
REQUIRED_TOP_LEVEL_ENTRIES = ["pyproject.toml", "src", "tests"]


ContractError = base.ContractError
atomic_json = base.atomic_json
append_event = base.append_event
candidate_identity = base.candidate_identity
exclusive_json = base.exclusive_json
file_hash = base.file_hash
file_hash_from_value = base.file_hash_from_value
hash_without = base.hash_without
json_hash = base.json_hash
read_events = base.read_events
read_json = base.read_json
require_equal = base.require_equal
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
            "MAIN_EXECUTION_PACKAGE_VALIDATION_CONTRACT_INVALID",
            "required_result_fields is missing",
        )
    return [str(field) for field in required]


def validate_static_contract(candidate_root: Path) -> dict[str, Any]:
    refs = (
        IMPLEMENTATION_REF,
        ENTRYPOINT_REF,
        ACTION_CONTRACT_REF,
        RESULT_SCHEMA_REF,
        GENERATION_PROFILE_REF,
        AUTHORIZATION_POLICY_REF,
        "tools/shared_control_baseline.py",
    )
    paths = {ref: candidate_root / ref for ref in refs}
    for ref, path in paths.items():
        if not path.is_file():
            raise ContractError(
                "MAIN_EXECUTION_PACKAGE_VALIDATION_CONTRACT_INVALID", ref
            )
    contract = read_json(
        paths[ACTION_CONTRACT_REF],
        "MAIN_EXECUTION_PACKAGE_VALIDATION_CONTRACT_INVALID",
    )
    schema = read_json(
        paths[RESULT_SCHEMA_REF],
        "MAIN_EXECUTION_PACKAGE_VALIDATION_RESULT_SCHEMA_INVALID",
    )
    profile = read_json(
        paths[GENERATION_PROFILE_REF],
        "MAIN_EXECUTION_PACKAGE_VALIDATION_CONTRACT_INVALID",
    )
    policy = read_json(
        paths[AUTHORIZATION_POLICY_REF],
        "MAIN_EXECUTION_PACKAGE_VALIDATION_CONTRACT_INVALID",
    )
    manifest = read_json(
        candidate_root / "THREE_PROJECT_PROGRAM_MANIFEST.json",
        "MAIN_EXECUTION_PACKAGE_VALIDATION_CONTRACT_INVALID",
    )
    epoch_domains = manifest.get("epoch_domains")
    authorization_profile = contract.get("authorization_profile")
    local_profile = policy.get("profile_authorization_schemas", {}).get(
        ASSURANCE_PROFILE, {}
    )
    policy_profile = (
        local_profile.get("MAIN_EXECUTION_PACKAGE_VALIDATION_AUTHORIZATION")
        if isinstance(local_profile, Mapping)
        else None
    )
    scope = (
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
    if (
        contract.get("action_id") != ACTION_ID
        or contract.get("node_id") != NODE_ID
        or contract.get("implementation_ref") != IMPLEMENTATION_REF
        or contract.get("executor_implementation_sha256")
        != file_hash(paths[IMPLEMENTATION_REF])
        or contract.get("runtime_entrypoint_ref") != ENTRYPOINT_REF
        or contract.get("runtime_entrypoint_sha256")
        != file_hash(paths[ENTRYPOINT_REF])
        or contract.get("result_schema_ref") != RESULT_SCHEMA_REF
        or contract.get("result_schema_sha256")
        != file_hash(paths[RESULT_SCHEMA_REF])
        or contract.get("contract_sha256")
        != hash_without(contract, "contract_sha256")
        or contract.get("assurance_profile") != ASSURANCE_PROFILE
        or contract.get("validation_scope") != VALIDATION_SCOPE
        or contract.get("predecessor_repository_write_allowed") is not False
        or contract.get("automatic_successor_advance_allowed") is not False
        or not isinstance(epoch_domains, Mapping)
        or contract.get("epoch_domain_contract") != epoch_domains
        or profile.get("assurance_profile") != ASSURANCE_PROFILE
        or policy_profile != authorization_profile
        or not isinstance(scope, Mapping)
        or scope.get("node_evidence_write_ref") != NODE_EVIDENCE_WRITE_REF
        or scope.get("predecessor_repository_write_allowed") is not False
        or scope.get("automatic_successor_advance_allowed") is not False
        or persistence_refs != set(RUNTIME_INTERNAL_WRITE_REFS)
        or schema.get("required") != required
        or set(schema.get("properties", {})) != set(required)
        or schema.get("additionalProperties") is not False
    ):
        raise ContractError(
            "MAIN_EXECUTION_PACKAGE_VALIDATION_CONTRACT_INVALID",
            "static provider, policy, schema, or write-boundary binding failed",
        )
    return contract


def validate_result_document(
    result: Mapping[str, Any],
    schema: Mapping[str, Any],
) -> None:
    required = schema.get("required")
    properties = schema.get("properties")
    if not isinstance(required, list) or not isinstance(properties, Mapping):
        raise ContractError(
            "MAIN_EXECUTION_PACKAGE_VALIDATION_RESULT_SCHEMA_INVALID",
            "schema is invalid",
        )
    if set(result) != set(required):
        raise ContractError(
            "MAIN_EXECUTION_PACKAGE_VALIDATION_RESULT_INVALID",
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
        expected = type_map.get(str(rule.get("type"))) if isinstance(rule, Mapping) else None
        value = result.get(field)
        if expected is None or not isinstance(value, expected) or (
            expected is int and isinstance(value, bool)
        ):
            raise ContractError(
                "MAIN_EXECUTION_PACKAGE_VALIDATION_RESULT_INVALID", field
            )
        if "const" in rule and value != rule["const"]:
            raise ContractError(
                "MAIN_EXECUTION_PACKAGE_VALIDATION_RESULT_INVALID", field
            )
        pattern = rule.get("pattern")
        if pattern and (
            not isinstance(value, str)
            or re.fullmatch(str(pattern), value) is None
        ):
            raise ContractError(
                "MAIN_EXECUTION_PACKAGE_VALIDATION_RESULT_INVALID", field
            )
    require_equal(
        result.get("next_node"),
        NEXT_NODE_ID,
        "MAIN_EXECUTION_PACKAGE_VALIDATION_RESULT_INVALID",
        "next_node",
    )
    require_equal(
        result.get("produced_capabilities"),
        PRODUCED_CAPABILITIES,
        "MAIN_EXECUTION_PACKAGE_VALIDATION_RESULT_INVALID",
        "produced_capabilities",
    )
    require_equal(
        result.get("result_sha256"),
        hash_without(result, "result_sha256"),
        "MAIN_EXECUTION_PACKAGE_VALIDATION_RESULT_INVALID",
        "result_sha256",
    )


def _tree_snapshot(root: Path) -> dict[str, str]:
    if not root.is_dir() or root.is_symlink():
        raise ContractError(
            "MATERIALIZED_REPOSITORY_INVALID",
            "materialized repository must be a regular directory",
        )
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ContractError(
                "MATERIALIZED_REPOSITORY_INVALID",
                f"symlink is forbidden: {path.relative_to(root)}",
            )
        if path.is_file():
            snapshot[path.relative_to(root).as_posix()] = file_hash(path)
    return snapshot


def _validate_materialized_repository(
    repository_root: Path,
    predecessor: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    before = _tree_snapshot(repository_root)
    observed_tree_sha = json_hash(before)
    top_level = sorted({Path(relative).parts[0] for relative in before})
    postflight = predecessor.get("postflight")
    independent = predecessor.get("independent_review")
    if (
        predecessor.get("status") != "PASS"
        or predecessor.get("node_id") != PREDECESSOR_NODE_ID
        or predecessor.get("workpack_id") != WORKPACK_ID
        or predecessor.get("validation_scope") != VALIDATION_SCOPE
        or predecessor.get("produced_capabilities")
        != [
            "MAIN_EXECUTION_PACKAGE_MATERIALIZED_PASS",
            "MAIN_EXECUTION_PACKAGE_MATERIALIZED_READY",
        ]
        or predecessor.get("successor_started") is not False
        or predecessor.get("result_sha256")
        != hash_without(predecessor, "result_sha256")
        or not isinstance(postflight, Mapping)
        or postflight.get("status") != "PASS"
        or postflight.get("validation_scope") != VALIDATION_SCOPE
        or postflight.get("tree_sha256") != observed_tree_sha
        or not isinstance(independent, Mapping)
        or independent.get("status") != "PASS"
        or independent.get("validation_scope") != VALIDATION_SCOPE
        or independent.get("tree_sha256") != observed_tree_sha
        or not set(REQUIRED_TOP_LEVEL_ENTRIES).issubset(top_level)
        or not before
    ):
        raise ContractError(
            "MATERIALIZED_REPOSITORY_STRUCTURAL_VALIDATION_FAILED",
            "actual repository bytes do not satisfy the predecessor-bound structure",
        )
    validation = {
        "status": "PASS",
        "validator_id": "MAIN_EXECUTION_PACKAGE_STRUCTURAL_VALIDATOR_V1",
        "validation_scope": VALIDATION_SCOPE,
        "required_top_level_entries": REQUIRED_TOP_LEVEL_ENTRIES,
        "observed_top_level_entries": top_level,
        "file_count": len(before),
        "repository_tree_sha256": observed_tree_sha,
        "executed_repository_code": False,
        "accepted_predecessor_self_report_without_byte_check": False,
    }
    validation["validation_sha256"] = json_hash(validation)
    if before != _tree_snapshot(repository_root):
        raise ContractError(
            "PREDECESSOR_REPOSITORY_MUTATED",
            "structural validation changed predecessor repository bytes",
        )
    return validation, before


def _validate_runtime_inputs(
    candidate_root: Path,
    execution_root: Path,
    command_path: Path,
    authorization_path: Path,
) -> dict[str, Any]:
    contract = validate_static_contract(candidate_root)
    schema = read_json(
        candidate_root / RESULT_SCHEMA_REF,
        "MAIN_EXECUTION_PACKAGE_VALIDATION_RESULT_SCHEMA_INVALID",
    )
    candidate_sha = candidate_identity(candidate_root)
    inputs = base._resolve_candidate_inputs(candidate_root)
    predecessor_path = execution_root / PREDECESSOR_RESULT_REF
    predecessor = read_json(
        predecessor_path, "MAIN_EXECUTION_PACKAGE_MATERIALIZATION_RESULT_INVALID"
    )
    predecessor_sha = file_hash(predecessor_path)
    require_equal(
        predecessor.get("candidate_tree_sha256"),
        candidate_sha,
        "MAIN_EXECUTION_PACKAGE_MATERIALIZATION_RESULT_INVALID",
        "candidate_tree_sha256",
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
    entrypoint_sha = file_hash(candidate_root / ENTRYPOINT_REF)
    action_contract_sha = file_hash(candidate_root / ACTION_CONTRACT_REF)
    result_schema_sha = file_hash(candidate_root / RESULT_SCHEMA_REF)
    repository_root = execution_root / REPOSITORY_REF
    structural_validation, repository_before = _validate_materialized_repository(
        repository_root, predecessor
    )
    repository_tree_sha = structural_validation["repository_tree_sha256"]

    required_command_fields = contract["runtime_input_contract"][
        "command_manifest_required_fields"
    ]
    if set(command) != set(required_command_fields):
        raise ContractError(
            "COMMAND_MANIFEST_INVALID",
            "command fields do not exactly match the action contract",
        )
    command_checks = {
        "action_id": ACTION_ID,
        "node_id": NODE_ID,
        "authorization_id": authorization.get("authorization_id"),
        "candidate_tree_sha256": candidate_sha,
        "requirement_ir_sha256": inputs["requirement_ir_sha256"],
        "executor_implementation_ref": IMPLEMENTATION_REF,
        "executor_implementation_sha256": implementation_sha,
        "runtime_entrypoint_ref": ENTRYPOINT_REF,
        "runtime_entrypoint_sha256": entrypoint_sha,
        "action_contract_sha256": action_contract_sha,
        "result_schema_sha256": result_schema_sha,
        "materialization_result_sha256": predecessor_sha,
        "materialized_repository_tree_sha256": repository_tree_sha,
        "expected_control_state_sha256": state_file_sha,
        "expected_event_tip": state.get("last_event_hash"),
        "node_evidence_write_ref": NODE_EVIDENCE_WRITE_REF,
        "validation_scope": VALIDATION_SCOPE,
    }
    for field, expected in command_checks.items():
        require_equal(command.get(field), expected, "COMMAND_MANIFEST_INVALID", field)

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
            "PROJECT_VALIDATION_AUTHORIZATION_REVOKED", "authorization is revoked"
        )
    expected_scope = {
        "program_id": inputs["program_id"],
        "node_id": NODE_ID,
        "allowed_action_id": ACTION_ID,
        "execution_mode": "PROJECT_VALIDATION",
        "validation_scope": VALIDATION_SCOPE,
        "predecessor_repository_ref": (
            "harness-resource://execution/project_start_packages/main_build/repository"
        ),
        "predecessor_repository_write_allowed": False,
        "node_evidence_write_ref": NODE_EVIDENCE_WRITE_REF,
        "runtime_internal_write_refs": RUNTIME_INTERNAL_WRITE_REFS,
        "automatic_successor_advance_allowed": False,
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
        "runtime_entrypoint_sha256": entrypoint_sha,
        "materialization_result_sha256": predecessor_sha,
        "materialized_repository_tree_sha256": repository_tree_sha,
        "expected_control_state_sha256": state_file_sha,
        "expected_event_tip": state.get("last_event_hash"),
        "node_evidence_write_ref": NODE_EVIDENCE_WRITE_REF,
        "validation_scope": VALIDATION_SCOPE,
        "max_transitions": 1,
        "max_loop_rounds": 1,
        "real_target_install_allowed": False,
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
    try:
        issued_at = datetime.fromisoformat(
            str(authorization.get("issued_at")).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        not_before = datetime.fromisoformat(
            str(authorization.get("not_before")).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        expires_at = datetime.fromisoformat(
            str(authorization.get("expires_at")).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
    except ValueError:
        raise ContractError(
            "PROJECT_VALIDATION_AUTHORIZATION_INVALID",
            "authorization validity is invalid",
        ) from None
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
    state_checks = {
        "program_id": inputs["program_id"],
        "epoch_domains": inputs["epoch_domains"],
        "control_plane_epoch": inputs["execution_control_plane_epoch"],
        "last_completed_node": PREDECESSOR_NODE_ID,
        "next_node": NODE_ID,
        "authorization_status": "GRANTED",
        "active_authorization_id": authorization.get("authorization_id"),
        "remaining_transition_budget": 1,
        "driver_started": False,
        "active_workpack": None,
    }
    for field, expected in state_checks.items():
        require_equal(
            state.get(field), expected, "PROGRAM_CONTROL_STATE_INVALID", field
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
        raise ContractError("FENCING_TOKEN_INVALID", "fencing_token must be positive")
    require_equal(
        fencing,
        state.get("next_fencing_token"),
        "FENCING_TOKEN_REGRESSION",
        "fencing_token",
    )
    require_equal(
        command.get("fencing_token"), fencing, "COMMAND_MANIFEST_INVALID", "fencing_token"
    )
    lease_id = authorization.get("lease_id")
    if not isinstance(lease_id, str) or not lease_id:
        raise ContractError("LEASE_ID_INVALID", "lease_id is required")
    require_equal(
        command.get("lease_id"), lease_id, "COMMAND_MANIFEST_INVALID", "lease_id"
    )
    expected_idempotency = json_hash(
        {
            "action_id": ACTION_ID,
            "authorization_id": authorization.get("authorization_id"),
            "candidate_tree_sha256": candidate_sha,
            "fencing_token": fencing,
            "lease_id": lease_id,
            "materialization_result_sha256": predecessor_sha,
            "materialized_repository_tree_sha256": repository_tree_sha,
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
        "repository_root": repository_root,
        "repository_before": repository_before,
        "repository_tree_sha": repository_tree_sha,
        "structural_validation": structural_validation,
        "idempotency_key": expected_idempotency,
        "lease_id": lease_id,
        "fencing_token": fencing,
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
            "UNKNOWN_COMMIT_STATE", "existing transaction is not safely committed"
        )
    result = read_json(
        execution_root / RESULT_REF,
        "MAIN_EXECUTION_PACKAGE_VALIDATION_RESULT_INVALID",
    )
    state = read_json(execution_root / CONTROL_STATE_REF, "PROGRAM_CONTROL_STATE_INVALID")
    event = transaction.get("event_payload")
    events = read_events(execution_root / CONTROL_EVENTS_REF)
    matches = [
        item
        for item in events
        if item.get("idempotency_key") == transaction.get("idempotency_key")
    ]
    if (
        not isinstance(event, Mapping)
        or len(matches) != 1
        or matches[0] != event
        or file_hash_from_value(result) != transaction.get("result_file_sha256")
        or state.get("state_sha256")
        != transaction.get("next_state_payload", {}).get("state_sha256")
    ):
        raise ContractError(
            "UNKNOWN_COMMIT_STATE", "committed outputs do not reconcile"
        )
    return result


def execute_action(
    candidate_root: Path,
    execution_root: Path,
    command_manifest_path: Path,
    authorization_path: Path,
) -> dict[str, Any]:
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
        if supplied.is_symlink() or not supplied.resolve().is_relative_to(execution):
            raise ContractError(
                "CONTROL_ACTION_INPUT_INVALID",
                f"{label} must be under the Execution Root",
            )

    transaction_path = execution / TRANSACTION_REF
    if transaction_path.exists():
        result = _validate_committed_transaction(
            execution, read_json(transaction_path, "TRANSACTION_JOURNAL_INVALID")
        )
        return {"status": "PASS", "disposition": "ALREADY_COMMITTED", "result": result}

    runtime = _validate_runtime_inputs(
        candidate,
        execution,
        command_manifest_path.resolve(),
        authorization_path.resolve(),
    )
    lease = {
        "schema_version": "1.0",
        "action_id": ACTION_ID,
        "lease_id": runtime["lease_id"],
        "idempotency_key": runtime["idempotency_key"],
        "fencing_token": runtime["fencing_token"],
        "status": "ACQUIRED",
    }
    try:
        exclusive_json(execution / LEASE_REF, lease)
    except FileExistsError:
        require_equal(
            read_json(execution / LEASE_REF), lease, "LEASE_CONFLICT", "lease"
        )

    result = {
        "schema_version": "1.0",
        "result_id": f"{NODE_ID}-{runtime['idempotency_key'][:16]}",
        "program_id": runtime["inputs"]["program_id"],
        "node_id": NODE_ID,
        "next_node": NEXT_NODE_ID,
        "status": "PASS",
        "execution_mode": "PROJECT_VALIDATION",
        "control_plane_epoch": runtime["inputs"]["execution_control_plane_epoch"],
        "candidate_tree_sha256": runtime["candidate_sha"],
        "requirement_ir_sha256": runtime["inputs"]["requirement_ir_sha256"],
        "materialization_result_sha256": runtime["predecessor_sha"],
        "materialized_repository_tree_sha256": runtime["repository_tree_sha"],
        "observed_repository_tree_sha256": runtime["repository_tree_sha"],
        "structural_validation": runtime["structural_validation"],
        "command_manifest_sha256": runtime["command_sha"],
        "executor_implementation_sha256": runtime["implementation_sha"],
        "runtime_entrypoint_sha256": runtime["entrypoint_sha"],
        "action_contract_sha256": runtime["action_contract_sha"],
        "result_schema_sha256": runtime["result_schema_sha"],
        "authorization_id": runtime["authorization"]["authorization_id"],
        "authorization_sha256": runtime["authorization_sha"],
        "idempotency_key": runtime["idempotency_key"],
        "lease_id": runtime["lease_id"],
        "fencing_token": runtime["fencing_token"],
        "produced_capabilities": PRODUCED_CAPABILITIES,
        "predecessor_repository_read_only": True,
        "successor_started": False,
        "started_at": utc_now(),
        "completed_at": utc_now(),
        "result_sha256": "",
    }
    result["result_sha256"] = hash_without(result, "result_sha256")
    validate_result_document(result, runtime["schema"])
    if runtime["repository_before"] != _tree_snapshot(runtime["repository_root"]):
        raise ContractError(
            "PREDECESSOR_REPOSITORY_MUTATED",
            "repository bytes changed before result promotion",
        )
    event = {
        "schema_version": "1.0",
        "event_type": "MAIN_EXECUTION_PACKAGE_VALIDATION_COMMITTED",
        "program_id": runtime["inputs"]["program_id"],
        "node_id": NODE_ID,
        "idempotency_key": runtime["idempotency_key"],
        "authorization_id": runtime["authorization"]["authorization_id"],
        "authorization_sha256": runtime["authorization_sha"],
        "executor_implementation_sha256": runtime["implementation_sha"],
        "materialization_result_sha256": runtime["predecessor_sha"],
        "materialized_repository_tree_sha256": runtime["repository_tree_sha"],
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
    try:
        exclusive_json(transaction_path, transaction)
    except FileExistsError:
        raise ContractError(
            "TRANSACTION_CONFLICT", "another executor created the transaction"
        ) from None
    atomic_json(execution / RESULT_REF, result)
    append_event(execution / CONTROL_EVENTS_REF, event)
    if file_hash(execution / CONTROL_STATE_REF) != runtime["state_file_sha"]:
        raise ContractError("UNKNOWN_COMMIT_STATE", "control state CAS failed")
    atomic_json(execution / CONTROL_STATE_REF, next_state)
    transaction["transaction_state"] = "COMMITTED"
    transaction["transaction_sha256"] = hash_without(
        transaction, "transaction_sha256"
    )
    atomic_json(transaction_path, transaction)
    if runtime["repository_before"] != _tree_snapshot(runtime["repository_root"]):
        raise ContractError(
            "PREDECESSOR_REPOSITORY_MUTATED",
            "validation promotion changed predecessor repository bytes",
        )
    return {"status": "PASS", "disposition": "COMMITTED", "result": result}


__all__ = [
    "ContractError",
    "execute_action",
    "validate_result_document",
    "validate_static_contract",
]
