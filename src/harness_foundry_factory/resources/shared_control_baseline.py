#!/usr/bin/env python3
"""Execute the bounded Shared Control Baseline registration action.

This module is copied byte-for-byte into a portable Start Package Candidate.
It intentionally uses only the Python standard library, never starts the
Program Driver or a Workpack, and writes only to the supplied execution root.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Mapping


ACTION_ID = "DERIVE-AND-LOCK-SHARED-CONTROL-BASELINE"
NODE_ID = "SHARED_CONTROL_BASELINE_LOCK"
IMPLEMENTATION_REF = "tools/shared_control_baseline.py"
ACTION_CONTRACT_REF = "validation/SHARED_CONTROL_BASELINE_ACTION_CONTRACT.json"
RESULT_SCHEMA_REF = "contracts/SHARED_CONTROL_BASELINE_RESULT.schema.json"
HUMAN_APPROVAL_REF = "evidence/engineering_dag/START_PACKAGE_HUMAN_APPROVAL/result.json"
CONTROL_STATE_REF = ".harness-foundry/control/PROGRAM_CONTROL_STATE.json"
CONTROL_EVENTS_REF = ".harness-foundry/control/PROGRAM_CONTROL_EVENTS.jsonl"
TRANSACTION_REF = ".harness-foundry/control/transactions/SHARED_CONTROL_BASELINE_LOCK.transaction.json"
LEASE_REF = ".harness-foundry/control/leases/SHARED_CONTROL_BASELINE_LOCK.lease.json"
RESULT_REF = "evidence/engineering_dag/SHARED_CONTROL_BASELINE_LOCK/result.json"
RECOVERY_REF = "evidence/engineering_dag/SHARED_CONTROL_BASELINE_LOCK/recovery_receipt.json"
CRASH_POINTS = {
    "AFTER_PREPARE_BEFORE_RESULT_RENAME",
    "AFTER_RESULT_RENAME_BEFORE_EVENT_APPEND",
    "AFTER_EVENT_APPEND_BEFORE_STATE_REPLACE",
    "AFTER_STATE_REPLACE_BEFORE_RESPONSE",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PRODUCED_CAPABILITIES = [
    "SHARED_CONTROL_BASELINE_LOCK_PASS",
    "CHARTER_LOCK_VALID",
    "SHARED_PROTOCOL_LOCK_VALID",
]


class ContractError(RuntimeError):
    """A stable fail-closed contract error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class InjectedCrash(RuntimeError):
    """Test-only interruption at a declared transaction boundary."""

    def __init__(self, point: str):
        super().__init__(point)
        self.point = point


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def json_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_without(value: Mapping[str, Any], field: str) -> str:
    return json_hash({key: item for key, item in value.items() if key != field})


def read_json(path: Path, code: str = "CONTROL_ACTION_INPUT_INVALID") -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(code, f"{path.name}: {exc}") from None
    if not isinstance(value, dict):
        raise ContractError(code, f"{path.name} must contain a JSON object")
    return value


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    """Create one durable JSON record without overwriting a concurrent owner."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        value, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8") + b"\n"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    fsync_directory(path.parent)


def append_event(path: Path, event: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_bytes(event) + b"\n"
    with path.open("ab") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    fsync_directory(path.parent)


def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("event is not an object")
                events.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ContractError("CONTROL_EVENT_LEDGER_INVALID", str(exc)) from None
    previous: str | None = None
    for event in events:
        if (
            event.get("previous_event_hash") != previous
            or event.get("event_hash") != hash_without(event, "event_hash")
        ):
            raise ContractError(
                "CONTROL_EVENT_LEDGER_INVALID", "event hash chain is invalid"
            )
        previous = str(event["event_hash"])
    return events


def parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ContractError("REGISTRATION_AUTHORIZATION_INVALID", f"{field} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ContractError("REGISTRATION_AUTHORIZATION_INVALID", f"{field} is invalid") from None
    if parsed.tzinfo is None:
        raise ContractError("REGISTRATION_AUTHORIZATION_INVALID", f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def require_equal(actual: Any, expected: Any, code: str, field: str) -> None:
    if actual != expected:
        raise ContractError(code, f"{field} does not match the executable contract")


def candidate_identity(candidate_root: Path) -> str:
    manifest = read_json(
        candidate_root / "validation/PORTABLE_FILE_MANIFEST.json",
        "CANDIDATE_PORTABLE_MANIFEST_INVALID",
    )
    files = manifest.get("files")
    excluded = manifest.get("excluded_files")
    if not isinstance(files, dict) or not files:
        raise ContractError(
            "CANDIDATE_PORTABLE_MANIFEST_INVALID", "portable file inventory is missing"
        )
    if not isinstance(excluded, list):
        raise ContractError(
            "CANDIDATE_PORTABLE_MANIFEST_INVALID", "excluded file inventory is missing"
        )
    actual: set[str] = set()
    for path in candidate_root.rglob("*"):
        if path.is_symlink():
            raise ContractError(
                "CANDIDATE_PORTABLE_MANIFEST_INVALID",
                f"symlink is forbidden: {path.relative_to(candidate_root)}",
            )
        if path.is_file():
            relative = path.relative_to(candidate_root).as_posix()
            if relative not in excluded:
                actual.add(relative)
    if actual != set(files):
        raise ContractError(
            "CANDIDATE_PORTABLE_MANIFEST_INVALID",
            "portable file inventory differs from the Candidate",
        )
    for relative, expected in files.items():
        relative_path = Path(str(relative))
        path = candidate_root / relative_path
        if (
            relative_path.is_absolute()
            or ".." in relative_path.parts
            or not path.is_file()
            or not isinstance(expected, str)
            or file_hash(path) != expected
        ):
            raise ContractError(
                "CANDIDATE_PORTABLE_MANIFEST_INVALID", str(relative)
            )
    return json_hash(files)


def validate_static_contract(candidate_root: Path) -> dict[str, Any]:
    action_path = candidate_root / IMPLEMENTATION_REF
    contract_path = candidate_root / ACTION_CONTRACT_REF
    schema_path = candidate_root / RESULT_SCHEMA_REF
    for path in (action_path, contract_path, schema_path):
        if not path.is_file():
            raise ContractError("SHARED_CONTROL_BASELINE_CONTRACT_INVALID", path.name)
    contract = read_json(contract_path, "SHARED_CONTROL_BASELINE_CONTRACT_INVALID")
    schema = read_json(schema_path, "SHARED_CONTROL_BASELINE_RESULT_SCHEMA_INVALID")
    manifest = read_json(
        candidate_root / "THREE_PROJECT_PROGRAM_MANIFEST.json",
        "SHARED_CONTROL_BASELINE_CONTRACT_INVALID",
    )
    epoch_domains = manifest.get("epoch_domains")
    if (
        contract.get("action_id") != ACTION_ID
        or contract.get("node_id") != NODE_ID
        or contract.get("implementation_ref") != IMPLEMENTATION_REF
        or contract.get("result_schema_ref") != RESULT_SCHEMA_REF
        or contract.get("executor_implementation_sha256") != file_hash(action_path)
        or contract.get("result_schema_sha256") != file_hash(schema_path)
        or not isinstance(epoch_domains, Mapping)
        or contract.get("epoch_domain_contract") != epoch_domains
        or contract.get("contract_sha256") != hash_without(contract, "contract_sha256")
    ):
        raise ContractError(
            "SHARED_CONTROL_BASELINE_CONTRACT_INVALID", "static hash binding failed"
        )
    required = contract.get("execution_contract", {}).get("required_result_fields")
    if (
        not isinstance(required, list)
        or schema.get("required") != required
        or set(schema.get("properties", {})) != set(required)
        or schema.get("additionalProperties") is not False
    ):
        raise ContractError(
            "SHARED_CONTROL_BASELINE_RESULT_SCHEMA_INVALID",
            "schema does not exactly close over the declared result fields",
        )
    return contract


def validate_result_document(
    result: Mapping[str, Any], schema: Mapping[str, Any], contract: Mapping[str, Any]
) -> None:
    required = schema.get("required")
    properties = schema.get("properties")
    if not isinstance(required, list) or not isinstance(properties, Mapping):
        raise ContractError("SHARED_CONTROL_BASELINE_RESULT_SCHEMA_INVALID", "invalid schema")
    if set(result) != set(required):
        raise ContractError("SHARED_CONTROL_BASELINE_RESULT_INVALID", "result fields are not exact")
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
            raise ContractError("SHARED_CONTROL_BASELINE_RESULT_SCHEMA_INVALID", field)
        expected_type = type_map.get(str(rule.get("type")))
        value = result.get(field)
        if expected_type is None or not isinstance(value, expected_type) or (
            expected_type is int and isinstance(value, bool)
        ):
            raise ContractError("SHARED_CONTROL_BASELINE_RESULT_INVALID", field)
        if "const" in rule and value != rule["const"]:
            raise ContractError("SHARED_CONTROL_BASELINE_RESULT_INVALID", field)
        if "enum" in rule and value not in rule["enum"]:
            raise ContractError("SHARED_CONTROL_BASELINE_RESULT_INVALID", field)
        pattern = rule.get("pattern")
        if pattern and (not isinstance(value, str) or re.fullmatch(str(pattern), value) is None):
            raise ContractError("SHARED_CONTROL_BASELINE_RESULT_INVALID", field)
        if isinstance(value, list):
            if len(value) < int(rule.get("minItems", 0)):
                raise ContractError("SHARED_CONTROL_BASELINE_RESULT_INVALID", field)
            if rule.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
                raise ContractError("SHARED_CONTROL_BASELINE_RESULT_INVALID", field)
    require_equal(result.get("produced_capabilities"), contract["execution_contract"]["produced_capabilities"], "SHARED_CONTROL_BASELINE_RESULT_INVALID", "produced_capabilities")
    require_equal(result.get("result_sha256"), hash_without(result, "result_sha256"), "SHARED_CONTROL_BASELINE_RESULT_INVALID", "result_sha256")


def _resolve_candidate_inputs(candidate_root: Path) -> dict[str, Any]:
    refs = {
        "charter_sha256": "PROGRAM_CHARTER.md",
        "profile_lock_sha256": "PROFILE_LOCK.json",
        "authorization_policy_sha256": "AUTHORIZATION_POLICY.json",
        "shared_protocol_sha256": "build_program/conformance/CONFORMANCE_INTERFACE.json",
        "schema_bundle_sha256": "constitution/RUNTIME_ATTESTATION_POLICY.json",
        "normative_atom_catalog_sha256": "canonical_sources/NORMATIVE_ATOM_CATALOG.json",
        "source_manifest_sha256": "canonical_sources/SOURCE_MANIFEST.json",
    }
    hashes: dict[str, str] = {}
    for field, relative in refs.items():
        path = candidate_root / relative
        if not path.is_file():
            raise ContractError("CONTROL_ACTION_INPUT_INVALID", relative)
        hashes[field] = file_hash(path)
    charter_lock = read_json(candidate_root / "CHARTER_LOCK.json")
    manifest = read_json(candidate_root / "THREE_PROJECT_PROGRAM_MANIFEST.json")
    frozen = read_json(candidate_root / "canonical_sources/FROZEN_REQUIREMENT_IR.json")
    provenance = read_json(candidate_root / "FACTORY_PROVENANCE.json")
    require_equal(charter_lock.get("charter_sha256"), hashes["charter_sha256"], "CONTROL_ACTION_INPUT_HASH_MISMATCH", "charter_sha256")
    require_equal(manifest.get("program_id"), frozen.get("program_id"), "CONTROL_ACTION_INPUT_HASH_MISMATCH", "program_id")
    hashes["program_id"] = str(frozen.get("program_id"))
    portable_requirement_sha = json_hash(frozen)
    require_equal(
        provenance.get("portable_requirement_ir_sha256"),
        portable_requirement_sha,
        "CONTROL_ACTION_INPUT_HASH_MISMATCH",
        "portable_requirement_ir_sha256",
    )
    requirement_sha = provenance.get("requirement_ir_sha256")
    if not isinstance(requirement_sha, str) or SHA256_RE.fullmatch(requirement_sha) is None:
        raise ContractError("CONTROL_ACTION_INPUT_HASH_MISMATCH", "requirement_ir_sha256")
    hashes["requirement_ir_sha256"] = requirement_sha
    target = frozen.get("target")
    epoch_domains = manifest.get("epoch_domains")
    if not isinstance(target, Mapping) or not isinstance(epoch_domains, Mapping):
        raise ContractError(
            "CONTROL_ACTION_EPOCH_DOMAIN_INVALID",
            "explicit architecture and execution epoch domains are required",
        )
    architecture_epoch = target.get("architecture_epoch")
    architecture_control_plane_epoch = target.get("control_plane_epoch")
    requirement_architecture_epoch = architecture_epoch
    requirement_architecture_control_plane_epoch = architecture_control_plane_epoch
    unbound_zero_semantics = architecture_epoch is None and architecture_control_plane_epoch is None
    if architecture_epoch is None and architecture_control_plane_epoch is None:
        architecture_epoch = 0
        architecture_control_plane_epoch = 0
    expected_epoch_domains = {
        "schema_version": "1.0",
        "architecture_epoch": architecture_epoch,
        "architecture_control_plane_epoch": architecture_control_plane_epoch,
        "execution_control_plane_epoch": 0,
        "legacy_control_plane_epoch_alias": "execution_control_plane_epoch",
        "requirement_architecture_epoch": requirement_architecture_epoch,
        "requirement_architecture_control_plane_epoch": requirement_architecture_control_plane_epoch,
        "projection_rule": (
            "NULL_REQUIREMENT_EPOCHS_TO_EXPLICIT_UNBOUND_ZERO_SENTINEL"
            if unbound_zero_semantics
            else "IDENTITY_REQUIREMENT_EPOCH_PROJECTION"
        ),
        "unbound_zero_semantics": unbound_zero_semantics,
    }
    require_equal(
        epoch_domains,
        expected_epoch_domains,
        "CONTROL_ACTION_EPOCH_DOMAIN_INVALID",
        "epoch_domains",
    )
    require_equal(
        manifest.get("control_plane_epoch"),
        epoch_domains["execution_control_plane_epoch"],
        "CONTROL_ACTION_EPOCH_DOMAIN_INVALID",
        "legacy control_plane_epoch alias",
    )
    hashes["epoch_domains"] = dict(epoch_domains)
    hashes["architecture_control_plane_epoch"] = epoch_domains[
        "architecture_control_plane_epoch"
    ]
    hashes["execution_control_plane_epoch"] = epoch_domains[
        "execution_control_plane_epoch"
    ]
    hashes["control_plane_epoch"] = epoch_domains[
        "execution_control_plane_epoch"
    ]
    return hashes


def _validate_runtime_inputs(
    candidate_root: Path,
    execution_root: Path,
    command_path: Path,
    authorization_path: Path,
) -> dict[str, Any]:
    contract = validate_static_contract(candidate_root)
    implementation_sha = file_hash(candidate_root / IMPLEMENTATION_REF)
    schema_sha = file_hash(candidate_root / RESULT_SCHEMA_REF)
    candidate_sha = candidate_identity(candidate_root)
    inputs = _resolve_candidate_inputs(candidate_root)
    human_path = execution_root / HUMAN_APPROVAL_REF
    state_path = execution_root / CONTROL_STATE_REF
    human = read_json(human_path, "HUMAN_APPROVAL_RECEIPT_INVALID")
    state = read_json(state_path, "PROGRAM_CONTROL_STATE_INVALID")
    command = read_json(command_path, "COMMAND_MANIFEST_INVALID")
    authorization = read_json(authorization_path, "REGISTRATION_AUTHORIZATION_INVALID")
    command_sha = file_hash(command_path)
    authorization_sha = file_hash(authorization_path)
    human_sha = file_hash(human_path)
    state_sha = file_hash(state_path)

    require_equal(command.get("action_id"), ACTION_ID, "COMMAND_MANIFEST_INVALID", "action_id")
    require_equal(command.get("node_id"), NODE_ID, "COMMAND_MANIFEST_INVALID", "node_id")
    require_equal(command.get("executor_implementation_ref"), IMPLEMENTATION_REF, "UNBOUND_OR_DRIFTED_CONTROL_ACTION_IMPLEMENTATION", "executor_implementation_ref")
    require_equal(command.get("executor_implementation_sha256"), implementation_sha, "UNBOUND_OR_DRIFTED_CONTROL_ACTION_IMPLEMENTATION", "command executor hash")
    require_equal(command.get("action_contract_sha256"), file_hash(candidate_root / ACTION_CONTRACT_REF), "COMMAND_MANIFEST_INVALID", "action_contract_sha256")
    require_equal(command.get("result_schema_sha256"), schema_sha, "COMMAND_MANIFEST_INVALID", "result_schema_sha256")
    require_equal(command.get("candidate_tree_sha256"), candidate_sha, "COMMAND_MANIFEST_INVALID", "candidate_tree_sha256")
    require_equal(command.get("requirement_ir_sha256"), inputs["requirement_ir_sha256"], "COMMAND_MANIFEST_INVALID", "requirement_ir_sha256")
    require_equal(command.get("human_approval_receipt_sha256"), human_sha, "COMMAND_MANIFEST_INVALID", "human_approval_receipt_sha256")
    require_equal(command.get("expected_control_state_sha256"), state_sha, "COMMAND_MANIFEST_INVALID", "expected_control_state_sha256")

    if authorization.get("status") == "REVOKED":
        raise ContractError("REGISTRATION_AUTHORIZATION_REVOKED", "authorization is revoked")
    require_equal(authorization.get("status"), "GRANTED", "REGISTRATION_AUTHORIZATION_INVALID", "status")
    require_equal(authorization.get("authorization_class"), "REGISTRATION_AUTHORIZATION", "REGISTRATION_AUTHORIZATION_INVALID", "authorization_class")
    require_equal(authorization.get("one_shot"), True, "REGISTRATION_AUTHORIZATION_INVALID", "one_shot")
    require_equal(authorization.get("program_id"), inputs["program_id"], "REGISTRATION_AUTHORIZATION_INVALID", "program_id")
    require_equal(authorization.get("node_id"), NODE_ID, "REGISTRATION_AUTHORIZATION_INVALID", "node_id")
    require_equal(authorization.get("allowed_action_id"), ACTION_ID, "REGISTRATION_AUTHORIZATION_INVALID", "allowed_action_id")
    require_equal(authorization.get("command_manifest_sha256"), command_sha, "REGISTRATION_AUTHORIZATION_INVALID", "command_manifest_sha256")
    require_equal(authorization.get("candidate_tree_sha256"), candidate_sha, "REGISTRATION_AUTHORIZATION_INVALID", "candidate_tree_sha256")
    require_equal(authorization.get("requirement_ir_sha256"), inputs["requirement_ir_sha256"], "REGISTRATION_AUTHORIZATION_INVALID", "requirement_ir_sha256")
    require_equal(authorization.get("executor_implementation_sha256"), implementation_sha, "UNBOUND_OR_DRIFTED_CONTROL_ACTION_IMPLEMENTATION", "authorization executor hash")
    require_equal(authorization.get("human_approval_receipt_sha256"), human_sha, "REGISTRATION_AUTHORIZATION_INVALID", "human_approval_receipt_sha256")
    require_equal(authorization.get("expected_control_state_sha256"), state_sha, "REGISTRATION_AUTHORIZATION_INVALID", "expected_control_state_sha256")
    if parse_time(authorization.get("not_before"), "not_before") > datetime.now(timezone.utc) or parse_time(authorization.get("expires_at"), "expires_at") <= datetime.now(timezone.utc):
        raise ContractError("REGISTRATION_AUTHORIZATION_INVALID", "authorization is outside its validity window")

    require_equal(human.get("decision"), "APPROVED", "HUMAN_APPROVAL_RECEIPT_INVALID", "decision")
    require_equal(human.get("program_id"), inputs["program_id"], "HUMAN_APPROVAL_RECEIPT_INVALID", "program_id")
    require_equal(human.get("candidate_tree_sha256"), candidate_sha, "HUMAN_APPROVAL_RECEIPT_INVALID", "candidate_tree_sha256")
    require_equal(human.get("requirement_ir_sha256"), inputs["requirement_ir_sha256"], "HUMAN_APPROVAL_RECEIPT_INVALID", "requirement_ir_sha256")
    require_equal(human.get("next_node"), NODE_ID, "HUMAN_APPROVAL_RECEIPT_INVALID", "next_node")
    for forbidden in ("driver_start_authorized", "workpack_execution_authorized", "target_install_authorized"):
        require_equal(human.get(forbidden), False, "HUMAN_APPROVAL_RECEIPT_INVALID", forbidden)

    require_equal(state.get("state_sha256"), hash_without(state, "state_sha256"), "PROGRAM_CONTROL_STATE_INVALID", "state_sha256")
    require_equal(state.get("program_id"), inputs["program_id"], "PROGRAM_CONTROL_STATE_INVALID", "program_id")
    require_equal(state.get("epoch_domains"), inputs["epoch_domains"], "PROGRAM_CONTROL_STATE_INVALID", "epoch_domains")
    require_equal(state.get("control_plane_epoch"), inputs["execution_control_plane_epoch"], "PROGRAM_CONTROL_STATE_INVALID", "control_plane_epoch")
    require_equal(state.get("next_node"), NODE_ID, "PROGRAM_CONTROL_STATE_INVALID", "next_node")
    require_equal(state.get("authorization_status"), "GRANTED", "PROGRAM_CONTROL_STATE_INVALID", "authorization_status")
    require_equal(state.get("active_authorization_id"), authorization.get("authorization_id"), "PROGRAM_CONTROL_STATE_INVALID", "active_authorization_id")
    require_equal(state.get("remaining_transition_budget"), 1, "PROGRAM_CONTROL_STATE_INVALID", "remaining_transition_budget")
    require_equal(state.get("driver_started"), False, "PROGRAM_CONTROL_STATE_INVALID", "driver_started")
    require_equal(state.get("active_workpack"), None, "PROGRAM_CONTROL_STATE_INVALID", "active_workpack")
    fencing = authorization.get("fencing_token")
    if not isinstance(fencing, int) or isinstance(fencing, bool) or fencing < 1:
        raise ContractError("FENCING_TOKEN_INVALID", "fencing_token must be a positive integer")
    require_equal(fencing, state.get("next_fencing_token"), "FENCING_TOKEN_REGRESSION", "fencing_token")
    require_equal(command.get("fencing_token"), fencing, "COMMAND_MANIFEST_INVALID", "fencing_token")
    lease_id = authorization.get("lease_id")
    if not isinstance(lease_id, str) or not lease_id:
        raise ContractError("LEASE_ID_INVALID", "lease_id is required")
    require_equal(command.get("lease_id"), lease_id, "COMMAND_MANIFEST_INVALID", "lease_id")
    expected_idempotency = json_hash({
        "action_id": ACTION_ID,
        "authorization_id": authorization.get("authorization_id"),
        "candidate_tree_sha256": candidate_sha,
        "fencing_token": fencing,
        "lease_id": lease_id,
        "requirement_ir_sha256": inputs["requirement_ir_sha256"],
    })
    require_equal(command.get("idempotency_key"), expected_idempotency, "IDEMPOTENCY_KEY_INVALID", "command idempotency_key")
    require_equal(authorization.get("idempotency_key"), expected_idempotency, "IDEMPOTENCY_KEY_INVALID", "authorization idempotency_key")
    require_equal(command.get("authorization_id"), authorization.get("authorization_id"), "COMMAND_MANIFEST_INVALID", "authorization_id")

    return {
        "contract": contract,
        "inputs": inputs,
        "command": command,
        "command_sha": command_sha,
        "authorization": authorization,
        "authorization_sha": authorization_sha,
        "human_sha": human_sha,
        "state": state,
        "state_sha": state_sha,
        "candidate_sha": candidate_sha,
        "implementation_sha": implementation_sha,
        "schema_sha": schema_sha,
        "idempotency_key": expected_idempotency,
        "lease_id": lease_id,
        "fencing_token": fencing,
    }


def _crash(point: str, crash_after: str | None) -> None:
    if crash_after == point:
        raise InjectedCrash(point)


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
    if transaction.get("transaction_sha256") != hash_without(
        transaction, "transaction_sha256"
    ):
        raise ContractError(
            "TRANSACTION_JOURNAL_INVALID", "transaction hash is invalid"
        )
    recovered_from = str(transaction.get("transaction_state"))

    if transaction["transaction_state"] == "PREPARED":
        _crash("AFTER_PREPARE_BEFORE_RESULT_RENAME", crash_after)
        if result_path.exists():
            require_equal(file_hash(result_path), transaction["result_file_sha256"], "UNKNOWN_COMMIT_STATE", "result")
        else:
            atomic_json(result_path, transaction["result_payload"])
        transaction["transaction_state"] = "RESULT_COMMITTED"
        transaction["transaction_sha256"] = hash_without(
            transaction, "transaction_sha256"
        )
        atomic_json(transaction_path, transaction)

    if transaction["transaction_state"] == "RESULT_COMMITTED":
        _crash("AFTER_RESULT_RENAME_BEFORE_EVENT_APPEND", crash_after)
        events = read_events(event_path)
        matches = [event for event in events if event.get("idempotency_key") == transaction["idempotency_key"]]
        if len(matches) > 1:
            raise ContractError("DUPLICATE_CONTROL_EVENT", "more than one event uses the idempotency key")
        if matches:
            require_equal(matches[0], transaction["event_payload"], "UNKNOWN_COMMIT_STATE", "event")
        else:
            append_event(event_path, transaction["event_payload"])
        transaction["transaction_state"] = "CONTROL_EVENT_COMMITTED"
        transaction["transaction_sha256"] = hash_without(
            transaction, "transaction_sha256"
        )
        atomic_json(transaction_path, transaction)

    if transaction["transaction_state"] == "CONTROL_EVENT_COMMITTED":
        _crash("AFTER_EVENT_APPEND_BEFORE_STATE_REPLACE", crash_after)
        if state_path.exists():
            current = read_json(state_path, "PROGRAM_CONTROL_STATE_INVALID")
            if current.get("state_sha256") == transaction["next_state_payload"]["state_sha256"]:
                pass
            elif file_hash(state_path) == transaction["previous_state_file_sha256"]:
                atomic_json(state_path, transaction["next_state_payload"])
            else:
                raise ContractError("UNKNOWN_COMMIT_STATE", "control state is neither prior nor committed")
        else:
            raise ContractError("UNKNOWN_COMMIT_STATE", "control state disappeared")
        transaction["transaction_state"] = "STATE_COMMITTED"
        transaction["transaction_sha256"] = hash_without(
            transaction, "transaction_sha256"
        )
        atomic_json(transaction_path, transaction)

    if transaction["transaction_state"] != "STATE_COMMITTED":
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


def _prepare_transaction(candidate_root: Path, execution_root: Path, runtime: Mapping[str, Any]) -> dict[str, Any]:
    """Build validated payloads; never commit a lease, journal, result or state."""
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
        "charter_sha256": runtime["inputs"]["charter_sha256"],
        "profile_lock_sha256": runtime["inputs"]["profile_lock_sha256"],
        "authorization_policy_sha256": runtime["inputs"]["authorization_policy_sha256"],
        "shared_protocol_sha256": runtime["inputs"]["shared_protocol_sha256"],
        "schema_bundle_sha256": runtime["inputs"]["schema_bundle_sha256"],
        "normative_atom_catalog_sha256": runtime["inputs"]["normative_atom_catalog_sha256"],
        "source_manifest_sha256": runtime["inputs"]["source_manifest_sha256"],
        "human_approval_receipt_sha256": runtime["human_sha"],
        "command_manifest_sha256": runtime["command_sha"],
        "executor_implementation_sha256": runtime["implementation_sha"],
        "authorization_id": runtime["authorization"]["authorization_id"],
        "authorization_sha256": runtime["authorization_sha"],
        "idempotency_key": runtime["idempotency_key"],
        "lease_id": runtime["lease_id"],
        "fencing_token": runtime["fencing_token"],
        "produced_capabilities": list(PRODUCED_CAPABILITIES),
        "started_at": started_at,
        "completed_at": utc_now(),
        "result_sha256": "",
    }
    result["result_sha256"] = hash_without(result, "result_sha256")
    schema = read_json(candidate_root / RESULT_SCHEMA_REF)
    validate_result_document(result, schema, runtime["contract"])

    previous_event_hash = runtime["state"].get("last_event_hash")
    events = read_events(execution_root / CONTROL_EVENTS_REF)
    actual_previous = events[-1]["event_hash"] if events else None
    require_equal(actual_previous, previous_event_hash, "CONTROL_EVENT_LEDGER_INVALID", "last_event_hash")
    event = {
        "schema_version": "1.0",
        "event_type": "SHARED_CONTROL_BASELINE_LOCK_COMMITTED",
        "program_id": runtime["inputs"]["program_id"],
        "node_id": NODE_ID,
        "idempotency_key": runtime["idempotency_key"],
        "authorization_id": runtime["authorization"]["authorization_id"],
        "authorization_sha256": runtime["authorization_sha"],
        "executor_implementation_sha256": runtime["implementation_sha"],
        "result_sha256": file_hash_from_value(result),
        "previous_event_hash": previous_event_hash,
        "fencing_token": runtime["fencing_token"],
    }
    event["event_hash"] = hash_without(event, "event_hash")
    next_state = dict(runtime["state"])
    next_state.update({
        "revision": int(runtime["state"].get("revision", 0)) + 1,
        "last_completed_node": NODE_ID,
        "next_node": "CONTROL_PLANE_REGISTRATION",
        "authorization_status": "CONSUMED",
        "active_authorization_id": None,
        "remaining_transition_budget": 0,
        "next_fencing_token": runtime["fencing_token"] + 1,
        "last_event_hash": event["event_hash"],
        "driver_started": False,
        "active_workpack": None,
    })
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
    prepared["transaction_sha256"] = hash_without(
        prepared, "transaction_sha256"
    )
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
        raise ContractError(
            "CANDIDATE_EXECUTION_ROOT_OVERLAP", "root symlinks are forbidden"
        )
    candidate_root = candidate_root.resolve()
    execution_root = execution_root.resolve()
    if candidate_root == execution_root or candidate_root in execution_root.parents or execution_root in candidate_root.parents:
        raise ContractError("CANDIDATE_EXECUTION_ROOT_OVERLAP", "Candidate and execution roots must be disjoint")
    if crash_after is not None and crash_after not in CRASH_POINTS:
        raise ContractError("CRASH_POINT_INVALID", crash_after)
    for supplied, label in (
        (command_manifest_path, "command manifest"),
        (authorization_path, "authorization"),
    ):
        resolved = supplied.resolve()
        if supplied.is_symlink() or not resolved.is_relative_to(execution_root):
            raise ContractError(
                "CONTROL_ACTION_INPUT_INVALID",
                f"{label} must be a non-symlink file under the execution root",
            )

    transaction_path = execution_root / TRANSACTION_REF
    if transaction_path.exists():
        transaction = read_json(transaction_path, "TRANSACTION_JOURNAL_INVALID")
        runtime = _validate_runtime_inputs_for_recovery(
            candidate_root, execution_root, command_manifest_path, authorization_path, transaction
        )
        require_equal(transaction.get("idempotency_key"), runtime["idempotency_key"], "IDEMPOTENCY_KEY_CONFLICT", "idempotency_key")
        _validate_transaction_payloads(
            transaction,
            runtime["contract"],
            read_json(candidate_root / RESULT_SCHEMA_REF),
        )
        disposition = _commit_transaction(
            execution_root, transaction, crash_after, was_recovery=True
        )
        result = read_json(execution_root / RESULT_REF, "SHARED_CONTROL_BASELINE_RESULT_INVALID")
        validate_result_document(result, read_json(candidate_root / RESULT_SCHEMA_REF), runtime["contract"])
        return {"status": "PASS", "disposition": disposition, "result": result}

    runtime = _validate_runtime_inputs(
        candidate_root, execution_root, command_manifest_path, authorization_path
    )
    lease_path = execution_root / LEASE_REF
    if lease_path.exists():
        lease = read_json(lease_path, "LEASE_ID_INVALID")
        if lease.get("idempotency_key") != runtime["idempotency_key"] or lease.get("lease_id") != runtime["lease_id"]:
            raise ContractError("LEASE_CONFLICT", "another lease already exists")
    else:
        try:
            exclusive_json(lease_path, {
                "schema_version": "1.0",
                "action_id": ACTION_ID,
                "lease_id": runtime["lease_id"],
                "idempotency_key": runtime["idempotency_key"],
                "fencing_token": runtime["fencing_token"],
                "status": "ACQUIRED",
            })
        except FileExistsError:
            lease = read_json(lease_path, "LEASE_ID_INVALID")
            if lease.get("idempotency_key") != runtime["idempotency_key"] or lease.get("lease_id") != runtime["lease_id"]:
                raise ContractError("LEASE_CONFLICT", "another lease won the race") from None

    prepared = _prepare_transaction(candidate_root, execution_root, runtime)
    result = prepared["result_payload"]
    try:
        exclusive_json(transaction_path, prepared)
    except FileExistsError:
        raise ContractError(
            "TRANSACTION_CONFLICT",
            "another executor created the transaction; retry for reconciliation",
        ) from None
    disposition = _commit_transaction(
        execution_root, prepared, crash_after, was_recovery=False
    )
    return {"status": "PASS", "disposition": disposition, "result": result}


def file_hash_from_value(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    return hashlib.sha256(payload).hexdigest()


def _validate_transaction_payloads(
    transaction: Mapping[str, Any],
    contract: Mapping[str, Any],
    schema: Mapping[str, Any],
) -> None:
    result = transaction.get("result_payload")
    event = transaction.get("event_payload")
    next_state = transaction.get("next_state_payload")
    prior_state = transaction.get("prior_state_payload")
    if not all(
        isinstance(value, Mapping)
        for value in (result, event, next_state, prior_state)
    ):
        raise ContractError(
            "TRANSACTION_JOURNAL_INVALID", "transaction payload is incomplete"
        )
    validate_result_document(result, schema, contract)
    require_equal(
        transaction.get("result_file_sha256"),
        file_hash_from_value(result),
        "TRANSACTION_JOURNAL_INVALID",
        "result_file_sha256",
    )
    require_equal(
        event.get("event_hash"),
        hash_without(event, "event_hash"),
        "TRANSACTION_JOURNAL_INVALID",
        "event_hash",
    )
    require_equal(
        next_state.get("state_sha256"),
        hash_without(next_state, "state_sha256"),
        "TRANSACTION_JOURNAL_INVALID",
        "next state hash",
    )
    require_equal(
        prior_state.get("state_sha256"),
        hash_without(prior_state, "state_sha256"),
        "TRANSACTION_JOURNAL_INVALID",
        "prior state hash",
    )


def _validate_runtime_inputs_for_recovery(
    candidate_root: Path,
    execution_root: Path,
    command_path: Path,
    authorization_path: Path,
    transaction: Mapping[str, Any],
) -> dict[str, Any]:
    state_path = execution_root / CONTROL_STATE_REF
    current = read_json(state_path, "PROGRAM_CONTROL_STATE_INVALID")
    final_state = transaction.get("next_state_payload")
    if isinstance(final_state, Mapping) and current.get("state_sha256") == final_state.get("state_sha256"):
        contract = validate_static_contract(candidate_root)
        candidate_sha = candidate_identity(candidate_root)
        inputs = _resolve_candidate_inputs(candidate_root)
        command = read_json(command_path, "COMMAND_MANIFEST_INVALID")
        authorization = read_json(authorization_path, "REGISTRATION_AUTHORIZATION_INVALID")
        human_path = execution_root / HUMAN_APPROVAL_REF
        human = read_json(human_path, "HUMAN_APPROVAL_RECEIPT_INVALID")
        require_equal(candidate_sha, transaction.get("candidate_tree_sha256"), "UNKNOWN_COMMIT_STATE", "candidate")
        require_equal(command.get("idempotency_key"), transaction.get("idempotency_key"), "IDEMPOTENCY_KEY_CONFLICT", "command idempotency_key")
        require_equal(authorization.get("idempotency_key"), transaction.get("idempotency_key"), "IDEMPOTENCY_KEY_CONFLICT", "authorization idempotency_key")
        require_equal(authorization.get("status"), "GRANTED", "REGISTRATION_AUTHORIZATION_INVALID", "status")
        require_equal(authorization.get("requirement_ir_sha256"), inputs["requirement_ir_sha256"], "REGISTRATION_AUTHORIZATION_INVALID", "requirement_ir_sha256")
        require_equal(command.get("human_approval_receipt_sha256"), file_hash(human_path), "HUMAN_APPROVAL_RECEIPT_INVALID", "human_approval_receipt_sha256")
        require_equal(authorization.get("human_approval_receipt_sha256"), file_hash(human_path), "HUMAN_APPROVAL_RECEIPT_INVALID", "authorization human approval hash")
        require_equal(human.get("decision"), "APPROVED", "HUMAN_APPROVAL_RECEIPT_INVALID", "decision")
        if parse_time(authorization.get("not_before"), "not_before") > datetime.now(timezone.utc) or parse_time(authorization.get("expires_at"), "expires_at") <= datetime.now(timezone.utc):
            raise ContractError("REGISTRATION_AUTHORIZATION_INVALID", "authorization is outside its validity window")
        require_equal(file_hash(candidate_root / IMPLEMENTATION_REF), transaction.get("executor_implementation_sha256"), "UNBOUND_OR_DRIFTED_CONTROL_ACTION_IMPLEMENTATION", "executor hash")
        require_equal(file_hash(command_path), transaction.get("command_manifest_sha256"), "UNKNOWN_COMMIT_STATE", "command manifest")
        require_equal(file_hash(authorization_path), transaction.get("authorization_sha256"), "UNKNOWN_COMMIT_STATE", "authorization")
        return {
            "contract": contract,
            "command": command,
            "authorization": authorization,
            "idempotency_key": transaction.get("idempotency_key"),
        }
    runtime = _validate_runtime_inputs(candidate_root, execution_root, command_path, authorization_path)
    require_equal(runtime["candidate_sha"], transaction.get("candidate_tree_sha256"), "UNKNOWN_COMMIT_STATE", "candidate")
    require_equal(runtime["command_sha"], transaction.get("command_manifest_sha256"), "UNKNOWN_COMMIT_STATE", "command")
    require_equal(runtime["authorization_sha"], transaction.get("authorization_sha256"), "UNKNOWN_COMMIT_STATE", "authorization")
    return runtime


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
            output = {"status": "PASS", "action_id": contract["action_id"], "executor_implementation_sha256": contract["executor_implementation_sha256"]}
        else:
            output = execute_action(
                args.candidate_root,
                args.execution_root,
                args.command_manifest.resolve(),
                args.authorization.resolve(),
            )
    except ContractError as exc:
        output = {"status": "FAIL", "code": exc.code, "message": exc.message}
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
