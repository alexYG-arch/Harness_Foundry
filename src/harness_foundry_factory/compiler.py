"""Deterministically compile a frozen Requirement IR into a v2.8 candidate."""

from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Mapping, Sequence

from .constants import (
    BASELINE_FACTORY_ID,
    DAG_WORKPACK_BINDINGS,
    DAG_WORKPACK_SEQUENCE_BINDINGS,
    ENGINEERING_NODE_ORDER,
    EPOCH38_LOCAL_RELEASE_REQUIREMENT_SOURCES,
    EPOCH38_LOCAL_RELEASE_REQUIRES,
    EPOCH38_LOCAL_ROOT_MATERIALIZATION_REQUIREMENT_SOURCES,
    EPOCH38_LOCAL_ROOT_MATERIALIZATION_REQUIRES,
    EPOCH38_LOCAL_TOOL_DISTRIBUTION_REQUIREMENT,
    FACTORY_ID,
    PHASE_ORDER,
    PROJECT_WORKPACK_CONTRACTS,
    PROJECTS,
    RELEASE_WORKPACK_BINDINGS,
    RELEASE_STEP_ORDER,
    ROOT_LAYER_BEHAVIORAL_ATOM_POLICY,
    ROOT_LAYER_VALIDATION_SCOPE,
    ROOT_MATERIALIZATION_COMMAND_IDS,
    ROOT_MATERIALIZATION_PRODUCES,
    ROOT_MATERIALIZATION_REQUIRES,
    TARGET_CANDIDATE_STATE,
    default_spec_root,
)
from .control_kernel import AUTHORITY_PRECEDENCE
from .assurance_profiles import assurance_profile_for_start_package, LOCAL_EXEC_UNTRUSTED_INPUT
from .startup_contracts import shared_control_default
from .artifact_descriptors import JOB_ARTIFACT_DESCRIPTOR_SCHEMA
from .case_read_plans import REGISTRY_READ_PROTOCOL, registry_schema_read_plans
from .registry_evidence import RESULT_SCHEMA_REF, RECEIPT_SCHEMA_REF, REGISTRY_CASE_RESULT_SCHEMA, REGISTRY_CASE_EXECUTION_RECEIPT_SCHEMA
from .semantic_contracts import (
    ARTIFACT_MANIFEST_REF,
    CASE_EVIDENCE_WRITER_WORKPACK_ID,
    CASE_EXECUTION_RESULT_ROOT_REF,
    ORACLE_EVALUATOR_REGISTRY_REF,
    PUBLIC_SKILL_JOB_INTERFACE_REF,
    PUBLIC_SKILL_METAMORPHIC_CASE_ID,
    PUBLIC_SKILL_SOURCE_RESOLUTION_ENTRYPOINT,
    PUBLIC_SKILL_JOB_PIPELINE_ENTRYPOINT,
    build_artifact_obligation_manifest,
    compile_declared_production_contracts,
    explicit_production_enabled,
    negative_case_specs_with_mandatory_controls,
    oracle_evaluator_registry,
    public_skill_job_interface,
    case_result_ref,
    registry_case_result_ref,
    required_artifact_kinds_for_case,
    repository_job_bindings,
    task_bundle_for_workpack,
    validate_explicit_production_contracts,
)
from .store import control_event_store_schema_contract
from .traceability import WORKPACK_PROJECTS, normalize_ir_coverage


PLACEHOLDER_RE = re.compile(r"<(?!\d)[^<>]+>")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
OPAQUE_AUTHORITY_HISTORY_SUBTREES = {
    "canonical_sources/FROZEN_REQUIREMENT_IR.json": (
        ("assumptions",),
        ("open_questions",),
        ("decisions",),
        ("user_adjustments",),
    ),
    "canonical_sources/REQUIREMENT_DECISIONS.json": (
        ("assumptions",),
        ("open_questions",),
        ("decisions",),
        ("user_adjustments",),
    ),
    "canonical_sources/USER_ADJUSTMENT_RECORD.json": (("adjustments",),),
}
PORTABLE_MODE = "LOGICAL_RESOURCE_URI"
LOGICAL_CANDIDATE_ROOT = "harness-resource://candidate"
LOGICAL_EXECUTION_ROOT = "harness-resource://execution"
FACTORY_REGRESSION_EXECUTION_RECEIPT_REF = (
    "validation/FACTORY_REGRESSION_EXECUTION_RECEIPT.json"
)
CORRECTION_COVERAGE_REF = "canonical_sources/CORRECTION_COVERAGE_MATRIX.json"
CORRECTION_VALIDATION_REFS = (
    "tools/self_check.py",
    "validation/HUMAN_REVIEW_CLOSURE_RECEIPT.json",
    "validation/START_PACKAGE_VALIDATION_REPORT.json",
)
FACTORY_IMPLEMENTATION_PATHS = (
    "src/harness_foundry_factory/compiler.py",
    "src/harness_foundry_factory/startup_contracts.py",
    "src/harness_foundry_factory/validator.py",
    "src/harness_foundry_factory/control_kernel.py",
    "src/harness_foundry_factory/requirement_completion.py",
    "src/harness_foundry_factory/semantic_contracts.py",
    "src/harness_foundry_factory/resources/shared_control_baseline.py",
    "src/harness_foundry_factory/resources/control_plane_registration.py",
    "src/harness_foundry_factory/resources/program_driver.py",
    "src/harness_foundry_factory/resources/program_driver_runtime_verification.py",
    "src/harness_foundry_factory/resources/workpack_runtime.py",
    "src/harness_foundry_factory/resources/main_execution_package_validation.py",
    "src/harness_foundry_factory/workpack_runtime.py",
    "src/harness_foundry_factory/coding_protocol.py",
    "src/harness_foundry_factory/coding_process.py",
    "src/harness_foundry_factory/coding_runtime.py",
    "src/harness_foundry_factory/workpack_acceptance.py",
    "src/harness_foundry_factory/workpack_evidence.py",
    "src/harness_foundry_factory/lab_protocol.py",
    "src/harness_foundry_factory/lab_protocol_checks.py",
    "src/harness_foundry_factory/project_verification.py",
    "src/harness_foundry_factory/resources/lab_protocol_worker.py",
    "src/harness_foundry_factory/main_execution_package_validation.py",
    "src/harness_foundry_factory/service.py",
    "src/harness_foundry_factory/models.py",
    "src/harness_foundry_factory/store.py",
    "src/harness_foundry_factory/identity_derivation.py",
    "src/harness_foundry_factory/recovery_decision.py",
    "src/harness_foundry_factory/complexity_governor.py",
    "src/harness_foundry_factory/closure_lanes.py",
    "src/harness_foundry_factory/authority_adapter.py",
    "src/harness_foundry_factory/evidence_projection.py",
    "src/harness_foundry_factory/generation_readiness.py",
    "tools/hffactory.py",
)
EPOCH2_MODE = "EPOCH2_RELEASE_CLOSURE_CONTROL_PLANE"
EPOCH1_MODE = "EPOCH1_GENERIC_CONTROL_KERNEL_COMPATIBILITY_BASELINE"
EPOCH4_MODE = "EPOCH4_SELF_USE_LOCAL_CORE_ROUTE"
LEGACY_MODE = "LEGACY_SHARED_CONTROL_BASELINE"
EPOCH2_MANIFEST_REF = "V2_9_RELEASE_CLOSURE_CONTROL_PLANE_MANIFEST.json"
EPOCH2_COVERAGE_REF = (
    "canonical_sources/RELEASE_CLOSURE_CORRECTION_COVERAGE_MATRIX.json"
)
SOURCE_AUTHORITY_POLICY_LOCK_ID = "V29_SOURCE_AUTHORITY_POLICY_LOCK_V4"
SOURCE_AUTHORITY_TRUST_ANCHOR_ID = "V29_SOURCE_AUTHORITY_TRUST_ANCHOR_V1"
SOURCE_AUTHORITY_SIGNATURE_ALGORITHM = "ED25519"
VALIDATION_REPORT_REF = "validation/START_PACKAGE_VALIDATION_REPORT.json"
VALIDATION_REPORT_RECEIPT_REF = (
    "validation/START_PACKAGE_VALIDATION_REPORT_RECEIPT.json"
)
VALIDATION_REPORT_RECEIPT_SCHEMA_REF = (
    "contracts/v2_9_release_closure/VALIDATION_REPORT_RECEIPT.schema.json"
)


def _source_authority_semantic_sources(sources: Any) -> list[dict[str, Any]]:
    """Project the authoritative registry without receiver-local locators."""

    if not isinstance(sources, list) or not all(
        isinstance(item, Mapping) for item in sources
    ):
        raise ValueError("authoritative source registry must be a list of objects")
    semantic_sources: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    for raw in sources:
        source_id = str(raw.get("source_id") or "")
        content_sha256 = str(raw.get("sha256") or "")
        declared_authority = str(raw.get("authority_level") or "")
        canonical_authority = {
            "NORMATIVE_USER_SELECTED": "HUMAN_APPROVED",
            "HUMAN_PROVIDED_SUPPLEMENT": "HUMAN_PROVIDED",
            "HUMAN_AUTHORIZED_AUTHORING_PROPOSAL": "HUMAN_APPROVED",
            "HUMAN_VIA_CODEX_CHAT_REVIEW_EVIDENCE": "HUMAN_VIA_CODEX_CHAT",
        }.get(declared_authority, declared_authority)
        if (
            not SAFE_ID_RE.fullmatch(source_id)
            or source_id in source_ids
            or not re.fullmatch(r"[0-9a-f]{64}", content_sha256)
            or canonical_authority
            not in {
                "HUMAN_APPROVED",
                "HUMAN_PROVIDED",
                "HUMAN_VIA_CODEX_CHAT",
                "LOCKED_SPECIFICATION",
            }
        ):
            raise ValueError("authoritative source semantic identity is invalid")
        source_ids.add(source_id)
        semantic_sources.append(
            {
                "source_id": source_id,
                "content_sha256": content_sha256,
                "copy_policy": raw.get("copy_policy") or "REFERENCE_ONLY",
                "loaded_completely": bool(raw.get("loaded_completely", True)),
                "declared_authority_level": declared_authority,
                "canonical_authority_level": canonical_authority,
            }
        )
    return semantic_sources


def source_authority_registry_tip_sha256(sources: Any) -> str:
    return _json_hash(_source_authority_semantic_sources(sources))


def _release_history_semantic_entries(
    requirement_ir: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Project Candidate successor facts from authoritative Requirement IR."""

    target = requirement_ir.get("target")
    if not isinstance(target, Mapping):
        raise ValueError("authoritative Requirement IR target is required")
    entries: list[dict[str, Any]] = []
    for requirement_key, raw in sorted(target.items()):
        if not isinstance(raw, Mapping) or raw.get(
            "replacement_identity_cross_check_required"
        ) is not True:
            continue
        active = raw.get("active_epochs")
        successor = raw.get("successor_binding")
        if not isinstance(active, Mapping) or not isinstance(successor, Mapping):
            raise ValueError("release-history authority entry is incomplete")
        entry = {
            "requirement_key": str(requirement_key),
            "closure_requirement_epoch": active.get("requirement_epoch"),
            "superseded_candidate": raw.get("superseded_candidate"),
            "replacement_candidate": raw.get("replacement_candidate"),
            "successor_candidate_version": successor.get("candidate_version"),
        }
        version = entry["successor_candidate_version"]
        if (
            not isinstance(entry["closure_requirement_epoch"], int)
            or entry["closure_requirement_epoch"] < 0
            or not isinstance(entry["superseded_candidate"], str)
            or not entry["superseded_candidate"]
            or not isinstance(version, str)
            or re.fullmatch(r"v0_[1-9][0-9]*", version) is None
            or entry["replacement_candidate"] != f"candidate-{version}"
        ):
            raise ValueError("release-history authority identity is invalid")
        entries.append(entry)
    keys = [entry["requirement_key"] for entry in entries]
    if len(keys) != len(set(keys)):
        raise ValueError("release-history authority contains duplicate keys")
    return sorted(
        entries,
        key=lambda entry: (
            entry["closure_requirement_epoch"], entry["requirement_key"]
        ),
    )


def source_authority_trust_anchor(
    public_key_bytes: bytes,
    *,
    program_id: str,
    requirement_epoch: int,
    issuer_id: str,
    key_id: str,
    issuance_event_id: str,
    issuance_event_revision: int,
    issuance_event_sha256: str,
    source_registry_revision: int,
    source_registry_tip_sha256: str,
    release_history_tip_sha256: str,
) -> dict[str, Any]:
    """Build receiver-pinned verification metadata, never Candidate authority."""

    if (
        len(public_key_bytes) != 32
        or not SAFE_ID_RE.fullmatch(program_id)
        or not SAFE_ID_RE.fullmatch(issuer_id)
        or not SAFE_ID_RE.fullmatch(key_id)
        or not SAFE_ID_RE.fullmatch(issuance_event_id)
        or requirement_epoch < 0
        or issuance_event_revision < 0
        or source_registry_revision < 0
        or not re.fullmatch(r"[0-9a-f]{64}", issuance_event_sha256)
        or not re.fullmatch(r"[0-9a-f]{64}", source_registry_tip_sha256)
        or not re.fullmatch(r"[0-9a-f]{64}", release_history_tip_sha256)
    ):
        raise ValueError("source authority Trust Anchor identity is invalid")
    issuance_event = {
        "event_id": issuance_event_id,
        "event_revision": issuance_event_revision,
        "event_type": "SOURCE_AUTHORITY_POLICY_ISSUED",
        "program_id": program_id,
        "requirement_epoch": requirement_epoch,
        "source_registry_revision": source_registry_revision,
        "source_registry_tip_sha256": source_registry_tip_sha256,
        "release_history_tip_sha256": release_history_tip_sha256,
    }
    if issuance_event_sha256 != _json_hash(issuance_event):
        raise ValueError("issuance Event Hash does not bind the declared Event")
    body = {
        "schema_version": "2.9",
        "anchor_id": SOURCE_AUTHORITY_TRUST_ANCHOR_ID,
        "authority_source": "RECEIVER_CONTROL_PLANE_EXTERNAL_TO_CANDIDATE",
        "signature_algorithm": SOURCE_AUTHORITY_SIGNATURE_ALGORITHM,
        "issuer_id": issuer_id,
        "key_id": key_id,
        "public_key_raw_base64": base64.b64encode(public_key_bytes).decode("ascii"),
        "program_id": program_id,
        "requirement_epoch": requirement_epoch,
        "issuance_event_id": issuance_event_id,
        "issuance_event_revision": issuance_event_revision,
        "issuance_event_sha256": issuance_event_sha256,
        "source_registry_revision": source_registry_revision,
        "source_registry_tip_sha256": source_registry_tip_sha256,
        "release_history_tip_sha256": release_history_tip_sha256,
    }
    body["anchor_sha256"] = _hash_without_field(body, "anchor_sha256")
    return body


def source_authority_policy_lock(
    sources: Any,
    *,
    release_history: list[dict[str, Any]],
    signer_private_key: Ed25519PrivateKey,
    trust_anchor: Mapping[str, Any],
    validation_report_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Sign the receiver policy against an independently pinned Trust Anchor."""

    semantic_sources = _source_authority_semantic_sources(sources)
    anchor_fields = {
        "anchor_id",
        "issuer_id",
        "key_id",
        "program_id",
        "requirement_epoch",
        "issuance_event_id",
        "issuance_event_revision",
        "issuance_event_sha256",
        "source_registry_revision",
        "source_registry_tip_sha256",
        "release_history_tip_sha256",
    }
    if not anchor_fields.issubset(trust_anchor):
        raise ValueError("source authority Trust Anchor is incomplete")
    if trust_anchor.get("source_registry_tip_sha256") != _json_hash(
        semantic_sources
    ):
        raise ValueError("Trust Anchor source-registry tip does not bind sources")
    if trust_anchor.get("release_history_tip_sha256") != _json_hash(
        release_history
    ):
        raise ValueError("Trust Anchor release-history tip does not bind history")
    report_binding_required = int(trust_anchor["requirement_epoch"]) >= 30
    if report_binding_required:
        expected_report_binding_fields = {
            "report_ref",
            "report_sha256",
            "receipt_ref",
            "receipt_sha256",
        }
        if (
            not isinstance(validation_report_binding, Mapping)
            or set(validation_report_binding) != expected_report_binding_fields
            or validation_report_binding.get("report_ref")
            != VALIDATION_REPORT_REF
            or validation_report_binding.get("receipt_ref")
            != VALIDATION_REPORT_RECEIPT_REF
            or any(
                re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(validation_report_binding.get(field) or ""),
                )
                is None
                for field in ("report_sha256", "receipt_sha256")
            )
        ):
            raise ValueError(
                "validation report binding is incomplete or invalid"
            )
    body = {
        "schema_version": "2.9",
        "lock_id": SOURCE_AUTHORITY_POLICY_LOCK_ID,
        "authority_source": "RECEIVER_CONTROL_PLANE_EXTERNAL_TO_CANDIDATE",
        "trust_anchor_id": trust_anchor["anchor_id"],
        "issuer_binding": {
            field: trust_anchor[field]
            for field in sorted(anchor_fields - {"anchor_id"})
        },
        "authority_normalization": {
            "NORMATIVE_USER_SELECTED": "HUMAN_APPROVED",
            "HUMAN_PROVIDED_SUPPLEMENT": "HUMAN_PROVIDED",
            "HUMAN_AUTHORIZED_AUTHORING_PROPOSAL": "HUMAN_APPROVED",
            "HUMAN_VIA_CODEX_CHAT_REVIEW_EVIDENCE": "HUMAN_VIA_CODEX_CHAT",
        },
        "canonical_authority_levels": [
            "HUMAN_APPROVED",
            "HUMAN_PROVIDED",
            "HUMAN_VIA_CODEX_CHAT",
            "LOCKED_SPECIFICATION",
        ],
        "semantic_projection_fields": [
            "source_id",
            "content_sha256",
            "copy_policy",
            "loaded_completely",
            "declared_authority_level",
            "canonical_authority_level",
        ],
        "sources": semantic_sources,
        "release_history_tip_sha256": _json_hash(release_history),
        "release_history": release_history,
    }
    if report_binding_required:
        body["validation_report_binding"] = dict(validation_report_binding)
    payload = json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    lock = {
        **body,
        "policy_payload_sha256": hashlib.sha256(payload).hexdigest(),
        "signature_algorithm": SOURCE_AUTHORITY_SIGNATURE_ALGORITHM,
        "signature_base64": base64.b64encode(
            signer_private_key.sign(payload)
        ).decode("ascii"),
    }
    lock["lock_sha256"] = _hash_without_field(lock, "lock_sha256")
    return lock


def _producer_epoch24_route_is_complete(remediation: Mapping[str, Any]) -> bool:
    route = remediation.get("producer_validator_route_contract")
    return isinstance(route, Mapping) and all(
        route.get(field) is True
        for field in (
            "epoch23_requirements_consumed_by_producer",
            "epoch23_requirements_consumed_by_standalone",
            "epoch23_requirements_consumed_by_factory_validator",
        )
    )


def _producer_epoch25_route_is_complete(remediation: Mapping[str, Any]) -> bool:
    route = remediation.get("producer_validator_route_contract")
    return isinstance(route, Mapping) and all(
        route.get(field) is True
        for field in (
            "semantic_policy_projection_consumed_by_producer",
            "semantic_policy_projection_consumed_by_standalone",
            "portable_uri_projection_consumed_by_factory_validator",
        )
    )


def _current_requirement_epoch(target: Mapping[str, Any]) -> int:
    epochs = [
        int(active["requirement_epoch"])
        for value in target.values()
        if isinstance(value, Mapping)
        and isinstance((active := value.get("active_epochs")), Mapping)
        and isinstance(active.get("requirement_epoch"), int)
    ]
    direct = target.get("requirement_epoch")
    if isinstance(direct, int):
        epochs.append(direct)
    return max(epochs, default=0)


def _current_candidate_version(target: Mapping[str, Any]) -> str | None:
    explicit = target.get("candidate_version")
    if isinstance(explicit, str) and re.fullmatch(r"v0_[1-9][0-9]*", explicit):
        return explicit
    versions = [
        str(value.get("candidate_version"))
        for value in target.values()
        if isinstance(value, Mapping)
        and re.fullmatch(
            r"v0_[1-9][0-9]*", str(value.get("candidate_version") or "")
        )
    ]
    return max(versions, key=lambda value: int(value.split("_")[-1]), default=None)


def _current_package_version(target: Mapping[str, Any]) -> str:
    """Return a human-facing package version without inferring it from a path."""

    for field in ("package_version", "version"):
        value = target.get(field)
        if isinstance(value, str) and re.fullmatch(
            r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?", value
        ):
            return value
    candidate_version = _current_candidate_version(target)
    return candidate_version or "UNVERSIONED-CANDIDATE"


def _validation_report_external_binding(
    candidate_root: Path,
) -> dict[str, str]:
    report_path = candidate_root / VALIDATION_REPORT_REF
    receipt_path = candidate_root / VALIDATION_REPORT_RECEIPT_REF
    if not report_path.is_file() or not receipt_path.is_file():
        raise ValueError("validation report and detached receipt are required")
    return {
        "report_ref": VALIDATION_REPORT_REF,
        "report_sha256": _file_hash(report_path),
        "receipt_ref": VALIDATION_REPORT_RECEIPT_REF,
        "receipt_sha256": _file_hash(receipt_path),
    }


def _ephemeral_source_authority_fixture(
    requirement_ir: Mapping[str, Any],
    candidate_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create a non-persisted signer fixture solely for generation self-check."""

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    sources = requirement_ir.get("sources", [])
    semantic_sources = _source_authority_semantic_sources(sources)
    target = requirement_ir.get("target")
    if not isinstance(target, Mapping):
        raise ValueError("target is required for source authority fixture")
    program_id = str(requirement_ir.get("program_id") or "")
    requirement_epoch = _current_requirement_epoch(target)
    source_registry_tip = _json_hash(semantic_sources)
    release_history = _release_history_semantic_entries(requirement_ir)
    release_history_tip = _json_hash(release_history)
    issuance_event_id = f"SOURCE-POLICY-ISSUED-EPOCH-{requirement_epoch}"
    issuance_event = {
        "event_id": issuance_event_id,
        "event_revision": requirement_epoch,
        "event_type": "SOURCE_AUTHORITY_POLICY_ISSUED",
        "program_id": program_id,
        "requirement_epoch": requirement_epoch,
        "source_registry_revision": requirement_epoch,
        "source_registry_tip_sha256": source_registry_tip,
        "release_history_tip_sha256": release_history_tip,
    }
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    anchor = source_authority_trust_anchor(
        public_key,
        program_id=program_id,
        requirement_epoch=requirement_epoch,
        issuer_id="FACTORY-GENERATION-SELF-CHECK",
        key_id="EPHEMERAL-NON-PERSISTED-KEY",
        issuance_event_id=issuance_event_id,
        issuance_event_revision=requirement_epoch,
        issuance_event_sha256=_json_hash(issuance_event),
        source_registry_revision=requirement_epoch,
        source_registry_tip_sha256=source_registry_tip,
        release_history_tip_sha256=release_history_tip,
    )
    policy = source_authority_policy_lock(
        sources,
        release_history=release_history,
        signer_private_key=private_key,
        trust_anchor=anchor,
        validation_report_binding=(
            _validation_report_external_binding(candidate_root)
            if requirement_epoch >= 30 else None
        ),
    )
    return policy, anchor
EPOCH2_CORRECTION_IDS = tuple(f"CORR-29-{index:03d}" for index in range(9, 14))
EPOCH2_RUNTIME_MODULES = (
    "authority_adapter.py",
    "identity_derivation.py",
    "recovery_decision.py",
    "complexity_governor.py",
    "closure_lanes.py",
    "evidence_projection.py",
    "store.py",
    "models.py",
    "constants.py",
)
EPOCH32_RUNTIME_MODULE_REFS = (
    "tools/harness_foundry_runtime/store.py",
    "tools/harness_foundry_runtime/models.py",
    "tools/harness_foundry_runtime/constants.py",
)
EPOCH40_CONTROL_RUNTIME_MODULE_REFS = (
    "tools/harness_foundry_runtime/control_kernel.py",
    "tools/harness_foundry_runtime/local_runtime.py",
    "tools/harness_foundry_runtime/local_process.py",
    "tools/harness_foundry_runtime/startup_runtime.py",
    *EPOCH32_RUNTIME_MODULE_REFS,
)
EPOCH45_WORKPACK_RUNTIME_MODULE_REF = (
    "tools/harness_foundry_runtime/workpack_runtime.py"
)
EPOCH49_PACKAGE_VALIDATION_RUNTIME_MODULE_REF = (
    "tools/harness_foundry_runtime/main_execution_package_validation.py"
)
EPOCH32_URI_ADVERSARIAL_CASES = (
    "DANGLING_CANDIDATE_RESOURCE_URI",
    "CANDIDATE_RESOURCE_URI_OUTSIDE_PORTABLE_INVENTORY",
    "MISSING_PACKAGED_RUNTIME_RELATIVE_IMPORT",
    "BINDER_FAILURE_LEAVES_FRESH_EXECUTION_ROOT_ABSENT",
)

EPOCH33_REVIEW_FINDING_IDS = (
    "HR-V032-001-BINDER-PREFLIGHT-INCOMPLETE",
    "HR-V032-002-ADVERSARIAL-DOMAIN-MISROUTED",
    "HR-V032-003-BINDER-HASH-ATOMICITY-UNBOUND",
    "HR-V032-004-STANDALONE-CASCADE-FALSE-FINDING",
)
EPOCH34_REVIEW_FINDING_IDS = (
    "HR-V033-001-EXISTING-EXECUTION-ROOT-OVERWRITE",
    "HR-V033-002-REQUIRED-BINDER-REGRESSION-NOT-EXECUTED",
)
EPOCH34_REQUIRED_REGRESSION_TESTS = (
    "test_epoch33_review_remediation_routes_to_producer_and_both_oracles",
    "test_runtime_binder_rejects_missing_dependency_before_root_write",
    "test_runtime_binder_rejects_dangling_uri_without_creating_root",
    "test_runtime_binder_rejects_portable_inventory_gap_without_creating_root",
    "test_runtime_binder_rejects_existing_root_by_default_and_allows_exact_reentry",
    "test_standalone_requires_receiver_side_source_authority_policy",
)
EPOCH35_REVIEW_FINDING_IDS = (
    "HR-V034-001-RUNTIME-BINDER-EXECUTION-ROOT-SYMLINK-BYPASS",
    "HR-V034-002-RUNTIME-BINDER-ATOMIC-PUBLISH-TOCTOU",
    "HR-V034-003-RUNTIME-BINDER-CLOSURE-OVERCLAIM",
)
EPOCH35_REQUIRED_REGRESSION_TESTS = (
    *EPOCH34_REQUIRED_REGRESSION_TESTS,
    "test_epoch35_remediation_contract_is_accepted_by_both_oracles",
    "test_runtime_binder_rejects_dangling_execution_root_symlink",
    "test_runtime_binder_rejects_execution_root_symlink_to_existing_directory",
    "test_runtime_binder_atomic_noreplace_rejects_appeared_empty_root",
    "test_runtime_binder_rejects_parent_identity_swap",
    "test_runtime_binder_atomic_noreplace_rejects_target_symlink_swap",
)


def _epoch32_runtime_binding_remediation_is_complete(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    uri_contract = value.get("candidate_resource_uri_closure_contract")
    dependency_contract = value.get("runtime_dependency_closure_contract")
    binder_contract = value.get("runtime_binder_atomicity_contract")
    oracles = value.get("independent_oracle_contract")
    return (
        value.get("status") == "REQUIRED_IN_REPLACEMENT_CANDIDATE"
        and value.get("active_epochs")
        == {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 32,
        }
        and value.get("closure_receipt_required") is True
        and isinstance(uri_contract, Mapping)
        and all(
            uri_contract.get(field) is True
            for field in (
                "scan_all_portable_text_resources",
                "candidate_root_uri_may_resolve_to_root_directory",
                "non_root_candidate_uri_must_resolve_to_physical_file",
                "target_must_be_in_portable_manifest_files_or_declared_exclusions",
            )
        )
        and uri_contract.get("missing_or_uninventoried_behavior")
        == "FAIL_CLOSED_BEFORE_PUBLICATION_OR_BINDING"
        and isinstance(dependency_contract, Mapping)
        and dependency_contract.get("retained_store_contract") is True
        and dependency_contract.get("relative_import_dependency_scan_required")
        is True
        and tuple(dependency_contract.get("required_runtime_module_refs") or ())
        == EPOCH32_RUNTIME_MODULE_REFS
        and dependency_contract.get("missing_dependency_behavior")
        == "FAIL_CLOSED"
        and isinstance(binder_contract, Mapping)
        and all(
            binder_contract.get(field) is True
            for field in (
                "validate_complete_uri_and_inventory_before_first_execution_root_write",
                "fresh_root_same_parent_staging_required",
                "fresh_root_atomic_publish_required",
                "failure_cleanup_keeps_fresh_root_absent",
            )
        )
        and binder_contract.get("candidate_write_allowed") is False
        and binder_contract.get(
            "human_gate_consumption_before_binding_success_allowed"
        )
        is False
        and isinstance(oracles, Mapping)
        and oracles.get("factory_validator_full_uri_closure_required") is True
        and oracles.get("standalone_full_uri_closure_required") is True
        and oracles.get("factory_validator_calls_standalone") is False
        and oracles.get("standalone_calls_factory_validator") is False
        and set(value.get("required_adversarial_cases") or ())
        == set(EPOCH32_URI_ADVERSARIAL_CASES)
    )


def _epoch33_runtime_binding_review_remediation_is_complete(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    preflight = value.get("runtime_binder_preflight_contract")
    routing = value.get("adversarial_domain_contract")
    binding = value.get("setup_runtime_binding_contract")
    standalone = value.get("standalone_missing_authority_contract")
    return (
        value.get("status") == "REQUIRED_IN_REPLACEMENT_CANDIDATE"
        and value.get("active_epochs")
        == {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 33,
        }
        and value.get("closure_receipt_required") is True
        and value.get("closure_receipt_status")
        == "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT"
        and set(value.get("finding_ids") or ()) == set(EPOCH33_REVIEW_FINDING_IDS)
        and isinstance(preflight, Mapping)
        and all(
            preflight.get(field) is True
            for field in (
                "portable_manifest_before_first_execution_root_write",
                "all_candidate_uri_closure_before_first_execution_root_write",
                "runtime_dependency_closure_before_first_execution_root_write",
                "necessary_receiver_authority_before_first_execution_root_write",
            )
        )
        and isinstance(routing, Mapping)
        and routing.get("epoch32_uri_binder_cases_owner") == "RUNTIME_BINDER"
        and routing.get("source_authority_domain_excludes_runtime_binder_cases")
        is True
        and set(routing.get("runtime_binder_required_adversarial_cases") or ())
        == set(EPOCH32_URI_ADVERSARIAL_CASES)
        and isinstance(binding, Mapping)
        and all(
            binding.get(field) is True
            for field in (
                "runtime_binding_contract_binds_setup_runtime_sha256",
                "closure_receipt_binds_setup_runtime_sha256",
                "validation_before_first_execution_root_write",
                "fresh_root_same_parent_staging_required",
                "fresh_root_atomic_publish_required",
                "failure_cleanup_keeps_fresh_root_absent",
            )
        )
        and isinstance(standalone, Mapping)
        and standalone.get("missing_external_authority_root_finding_preserved")
        is True
        and standalone.get("dependent_adversarial_false_findings_suppressed")
        is True
    )


def _epoch34_runtime_binding_review_remediation_is_complete(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    existing_root = value.get("existing_execution_root_contract")
    execution = value.get("required_regression_execution_contract")
    implementation = value.get("implementation_evidence")
    return (
        value.get("status") == "REQUIRED_IN_REPLACEMENT_CANDIDATE"
        and value.get("active_epochs")
        == {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 34,
        }
        and value.get("closure_receipt_required") is True
        and value.get("closure_receipt_status")
        == "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT"
        and set(value.get("finding_ids") or ())
        == set(EPOCH34_REVIEW_FINDING_IDS)
        and tuple(value.get("required_regression_tests") or ())
        == EPOCH34_REQUIRED_REGRESSION_TESTS
        and isinstance(existing_root, Mapping)
        and existing_root.get("fail_closed_by_default") is True
        and existing_root.get("explicit_idempotent_reentry_allowed") is True
        and existing_root.get("exact_existing_receipt_required") is True
        and existing_root.get("receipt_overwrite_allowed") is False
        and isinstance(execution, Mapping)
        and execution.get("factory_validator_executes_exact_hash_bound_tests")
        is True
        and execution.get("candidate_publication_blocked_on_missing_test") is True
        and execution.get("candidate_publication_blocked_on_failed_test") is True
        and execution.get("closure_pass_requires_execution_receipt") is True
        and isinstance(implementation, Mapping)
        and implementation.get("regression_test_ref")
        == "tests/test_release_closure_candidate.py"
        and re.fullmatch(
            r"[0-9a-f]{64}",
            str(implementation.get("regression_test_sha256") or ""),
        )
        is not None
    )


def _epoch35_runtime_binding_path_atomicity_remediation_is_complete(
    value: Any,
) -> bool:
    if not isinstance(value, Mapping):
        return False
    raw_path = value.get("receiver_raw_path_identity_contract")
    parent = value.get("parent_directory_identity_contract")
    publication = value.get("atomic_noreplace_publication_contract")
    receipt = value.get("idempotent_reentry_nofollow_contract")
    execution = value.get("required_regression_execution_contract")
    implementation = value.get("implementation_evidence")
    return (
        value.get("status") == "REQUIRED_IN_REPLACEMENT_CANDIDATE"
        and value.get("active_epochs")
        == {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 35,
        }
        and value.get("closure_receipt_required") is True
        and value.get("closure_receipt_status")
        == "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT"
        and set(value.get("finding_ids") or ()) == set(EPOCH35_REVIEW_FINDING_IDS)
        and tuple(value.get("required_regression_tests") or ())
        == EPOCH35_REQUIRED_REGRESSION_TESTS
        and isinstance(raw_path, Mapping)
        and all(
            raw_path.get(field) is True
            for field in (
                "receiver_argument_preserved_before_resolution",
                "final_component_lstat_nofollow_required",
                "dangling_symlink_rejected",
                "existing_target_symlink_rejected",
            )
        )
        and isinstance(parent, Mapping)
        and all(
            parent.get(field) is True
            for field in (
                "opened_parent_directory_identity_pinned",
                "parent_identity_revalidated_before_publish",
                "publication_uses_pinned_parent_descriptor",
            )
        )
        and isinstance(publication, Mapping)
        and publication.get("destination_noreplace_required") is True
        and publication.get("macos_renameatx_np_rename_excl") is True
        and publication.get("linux_renameat2_rename_noreplace") is True
        and publication.get("unsafe_replace_fallback_allowed") is False
        and publication.get("unsupported_platform_behavior") == "FAIL_CLOSED"
        and isinstance(receipt, Mapping)
        and receipt.get("execution_root_identity_stable_for_reentry") is True
        and receipt.get("receipt_directory_nofollow") is True
        and receipt.get("receipt_file_nofollow") is True
        and receipt.get("receipt_overwrite_allowed") is False
        and isinstance(execution, Mapping)
        and execution.get("factory_validator_executes_exact_hash_bound_tests")
        is True
        and execution.get("candidate_publication_blocked_on_missing_test") is True
        and execution.get("candidate_publication_blocked_on_failed_test") is True
        and execution.get("closure_pass_requires_execution_receipt") is True
        and isinstance(implementation, Mapping)
        and implementation.get("compiler_ref")
        == "src/harness_foundry_factory/compiler.py"
        and implementation.get("factory_validator_ref")
        == "src/harness_foundry_factory/validator.py"
        and implementation.get("regression_test_ref")
        == "tests/test_release_closure_candidate.py"
        and all(
            re.fullmatch(r"[0-9a-f]{64}", str(implementation.get(field) or ""))
            is not None
            for field in (
                "compiler_sha256",
                "factory_validator_sha256",
                "regression_test_sha256",
            )
        )
    )


def compile_candidate(
    requirement_ir: Mapping[str, Any],
    spec_root: str | Path,
    staging_root: str | Path,
    target_root: str | Path,
    created_at: str,
    spec_lock: Mapping[str, Any] | None = None,
    *,
    authority_provenance: Mapping[str, Any] | None = None,
    generation_readiness: Mapping[str, Any] | None = None,
    active_requirement_epoch: int | None = None,
) -> dict[str, Any]:
    """Compatibility entrypoint consumed by ``FactoryService``."""

    return compile_start_package(
        requirement_ir,
        spec_root=spec_root,
        staging_root=staging_root,
        candidate_root=target_root,
        created_at=created_at,
        spec_lock=spec_lock,
        authority_provenance=authority_provenance,
        generation_readiness=generation_readiness,
        active_requirement_epoch=active_requirement_epoch,
    )


def compile_requirement_architecture_contract(
    requirement_ir: Mapping[str, Any],
    *,
    requirement_lock: Mapping[str, Any],
    architecture_readback: Mapping[str, Any],
    architecture_lock: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile the two approved authoring locks without writing artifacts."""

    ir = deepcopy(dict(requirement_ir))
    requirement_ir_sha256 = _json_hash(ir)
    if (
        requirement_lock.get("status") != "LOCKED"
        or requirement_lock.get("requirement_ir_sha256")
        != requirement_ir_sha256
    ):
        raise ValueError("REQUIREMENT_LOCK_STALE")
    requirement_lock_sha256 = _hash_without_field(
        requirement_lock, "requirement_lock_sha256"
    )
    if requirement_lock.get("requirement_lock_sha256") != requirement_lock_sha256:
        raise ValueError("REQUIREMENT_LOCK_STALE")

    required_architecture_sections = (
        "capabilities",
        "stages",
        "subharnesses",
        "modules",
        "rules",
        "policies",
        "tools",
        "interfaces",
        "failure_returns",
        "unresolved_decisions",
    )
    if any(
        not isinstance(architecture_readback.get(field), list)
        for field in required_architecture_sections
    ) or architecture_readback.get("unresolved_decisions"):
        raise ValueError("ARCHITECTURE_DECISION_INCOMPLETE")
    architecture_readback_sha256 = _json_hash(architecture_readback)
    if (
        architecture_lock.get("status") != "LOCKED"
        or architecture_lock.get("architecture_readback_sha256")
        != architecture_readback_sha256
        or architecture_lock.get("requirement_lock_sha256")
        != requirement_lock_sha256
    ):
        raise ValueError("ARCHITECTURE_LOCK_STALE")
    architecture_lock_sha256 = _hash_without_field(
        architecture_lock, "architecture_lock_sha256"
    )
    if architecture_lock.get("architecture_lock_sha256") != architecture_lock_sha256:
        raise ValueError("ARCHITECTURE_LOCK_STALE")

    target = ir.get("target")
    if not isinstance(target, Mapping):
        raise ValueError("REQUIREMENT_IR_TARGET_MISSING")
    architecture_epoch = target.get("architecture_epoch")
    control_plane_epoch = target.get("control_plane_epoch")
    if (
        not isinstance(architecture_epoch, int)
        or not isinstance(control_plane_epoch, int)
        or architecture_epoch != control_plane_epoch
        or architecture_lock.get("architecture_epoch") != architecture_epoch
        or architecture_lock.get("control_plane_epoch") != control_plane_epoch
    ):
        raise ValueError("MIXED_EPOCH")

    topology = {
        field: deepcopy(architecture_readback[field])
        for field in (
            "capabilities",
            "stages",
            "subharnesses",
            "modules",
            "rules",
            "policies",
            "tools",
            "interfaces",
        )
    }
    if architecture_lock.get("topology_sha256") != _json_hash(topology):
        raise ValueError("ARCHITECTURE_LOCK_STALE")
    if architecture_lock.get("failure_return_map_sha256") != _json_hash(
        architecture_readback["failure_returns"]
    ):
        raise ValueError("ARCHITECTURE_LOCK_STALE")

    normalized_ir = normalize_ir_coverage(ir)
    findings = validate_explicit_production_contracts(normalized_ir)
    if findings:
        raise ValueError(
            "PRODUCTION_CONTRACT_INVALID:"
            + ",".join(sorted({str(item["code"]) for item in findings}))
        )
    atom_catalog_sha256 = _json_hash(normalized_ir.get("atoms", []))
    coverage_matrix_sha256 = _json_hash(normalized_ir.get("coverage_edges", []))
    target_id = str(target.get("id") or "TARGET")
    program_id = str(normalized_ir.get("program_id") or "PROGRAM")
    manifest = build_artifact_obligation_manifest(
        normalized_ir,
        target_id=target_id,
        program_id=program_id,
        requirement_ir_sha256=requirement_ir_sha256,
        atom_catalog_sha256=atom_catalog_sha256,
        coverage_matrix_sha256=coverage_matrix_sha256,
    )
    task_bundles: list[dict[str, Any]] = []
    if isinstance(manifest, Mapping):
        for workpack_id in sorted(manifest.get("reverse_workpack_index", {})):
            bundle = task_bundle_for_workpack(
                manifest,
                workpack_id=str(workpack_id),
                project_id=WORKPACK_PROJECTS.get(str(workpack_id), "UNASSIGNED"),
                program_id=program_id,
                target_id=target_id,
                structural_contract=PROJECT_WORKPACK_CONTRACTS.get(
                    str(workpack_id)
                ),
            )
            if bundle is not None:
                task_bundles.append(bundle)

    result = {
        "schema_version": "2.9",
        "status": "PASS",
        "compilation_kind": "REQUIREMENT_ARCHITECTURE_CORE_CONTRACT",
        "program_id": program_id,
        "target_id": target_id,
        "requirement_epoch": requirement_lock.get("requirement_epoch"),
        "architecture_epoch": architecture_epoch,
        "control_plane_epoch": control_plane_epoch,
        "bindings": {
            "requirement_ir_sha256": requirement_ir_sha256,
            "requirement_lock_sha256": requirement_lock_sha256,
            "architecture_readback_sha256": architecture_readback_sha256,
            "architecture_lock_sha256": architecture_lock_sha256,
        },
        "requirement_atom_index": [
            {
                "atom_id": item.get("atom_id"),
                "delivery_tier": item.get("delivery_tier"),
                "owner": item.get("owner"),
            }
            for item in normalized_ir.get("atoms", [])
            if isinstance(item, Mapping)
        ],
        "architecture": topology,
        "artifact_obligation_manifest": manifest,
        "task_bundles": task_bundles,
        "writes_performed": False,
        "execution_started": False,
    }
    result["compiled_contract_sha256"] = _hash_without_field(
        result, "compiled_contract_sha256"
    )
    return result


def compile_start_package(
    requirement_ir: Mapping[str, Any],
    *,
    spec_root: str | Path | None = None,
    staging_root: str | Path,
    candidate_root: str | Path,
    created_at: str,
    spec_lock: Mapping[str, Any] | None = None,
    authority_provenance: Mapping[str, Any] | None = None,
    generation_readiness: Mapping[str, Any] | None = None,
    active_requirement_epoch: int | None = None,
) -> dict[str, Any]:
    """Compile, fully materialize, and atomically publish one authoring candidate."""

    normalized_ir = normalize_ir_coverage(requirement_ir)
    source_requirement_ir_sha256 = _json_hash(normalized_ir)
    ir = compile_declared_production_contracts(normalized_ir)
    target = _validate_ir(ir)
    control_plane_mode = _control_plane_generation_mode(ir)
    factory_epoch_supplied = (
        isinstance(active_requirement_epoch, int)
        and not isinstance(active_requirement_epoch, bool)
        and active_requirement_epoch >= 0
    )
    frozen_requirement_epoch = (
        int(active_requirement_epoch)
        if factory_epoch_supplied
        else _current_requirement_epoch(target)
    )
    if control_plane_mode == EPOCH4_MODE:
        _validate_epoch4_generation_readiness(ir, generation_readiness)
        assert isinstance(generation_readiness, Mapping)
        readiness_epoch = int(generation_readiness["requirement_epoch"])
        if factory_epoch_supplied and frozen_requirement_epoch != readiness_epoch:
            raise ValueError("generation readiness and Factory Requirement epochs differ")
        frozen_requirement_epoch = readiness_epoch
    portable_mode = str(target.get("portability_mode") or PORTABLE_MODE)
    spec = Path(spec_root or default_spec_root()).expanduser().resolve()
    staging = Path(staging_root).expanduser().resolve()
    candidate = Path(candidate_root).expanduser().resolve()
    program_id = str(ir.get("program_id") or f"PROGRAM-{target['id']}")
    execution_root_value = target.get("execution_root")
    if execution_root_value in (None, ""):
        execution = candidate.with_name(
            f".{candidate.name}.hffactory-planned-execution-{program_id}"
        )
        if os.path.lexists(execution):
            raise ValueError("planned Execution Root identity already exists")
    else:
        execution = Path(
            str(execution_root_value or candidate)
        ).expanduser().resolve()
    if (
        candidate == execution
        or candidate.is_relative_to(execution)
        or execution.is_relative_to(candidate)
    ):
        raise ValueError("Candidate and Execution Root identities must be disjoint")
    if not spec.is_dir():
        raise ValueError(f"v2.8 spec root does not exist: {spec}")
    target_id = str(target["id"])
    target_name = str(target["name"])
    target_type = str(target["type"]).upper()
    profile = str(target["profile"]).upper()
    package_id = f"{target_id}-START-PACKAGE"
    ir_hash = source_requirement_ir_sha256
    compiled_ir_hash = _json_hash(ir)
    if spec_lock is None:
        from .spec_lock import load_verified_spec_lock

        spec_lock = load_verified_spec_lock(spec)
    spec_files = spec_lock.get("files") if isinstance(spec_lock, Mapping) else None
    if not isinstance(spec_files, Mapping) or not spec_lock.get("content_sha256"):
        raise ValueError("a complete verified v2.8 spec lock is required")
    spec_hash = str(spec_lock["content_sha256"])
    spec_file_count = int(spec_lock.get("file_count", len(spec_files)))
    recovered = _recover_existing_candidate(
        candidate,
        requirement_ir_sha256=ir_hash,
        spec_content_sha256=spec_hash,
        authoritative_sources=ir.get("sources", []),
        authoritative_requirement_ir=ir,
        authority_provenance=authority_provenance,
    )
    if recovered is not None:
        return recovered
    if staging.exists():
        provenance_path = staging / "FACTORY_PROVENANCE.json"
        try:
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise FileExistsError(f"staging root already exists: {staging}") from None
        if (
            provenance.get("requirement_ir_sha256") != ir_hash
            or provenance.get("spec_content_sha256") != spec_hash
        ):
            raise FileExistsError(f"staging root belongs to another compilation: {staging}")
        shutil.rmtree(staging)
    if candidate.exists() and candidate.is_dir():
        candidate.rmdir()
    first_workpack_id = f"WP-{target_id}-G0-001"
    context = {
        "program_id": program_id,
        "target_id": target_id,
        "target_name": target_name,
        "target_type": target_type,
        "profile": profile,
        "package_id": package_id,
        "candidate_root": str(candidate),
        "execution_root": str(execution),
        "candidate_root_access": (
            "READ_ONLY_AFTER_ATOMIC_PUBLICATION"
            if execution != candidate
            else "INVALID_COMBINED_CANDIDATE_AND_EXECUTION_ROOT"
        ),
        "created_at": created_at,
        "ir_hash": ir_hash,
        "first_workpack_id": first_workpack_id,
        "primary_runtime": str(target["primary_runtime"]),
        "portability_mode": portable_mode,
        "requirement_epoch": frozen_requirement_epoch,
    }

    for directory in (
        "canonical_sources",
        "workpacks",
        "capsules",
        "commands",
        "results",
        "loops",
        "evidence",
        "validation",
        "contracts",
        "build_program/conformance",
        "constitution",
        "project_start_packages/external_lab",
        "project_start_packages/linkage_review",
        "project_start_packages/main_build",
    ):
        (staging / directory).mkdir(parents=True, exist_ok=True)

    _write_json(
        staging / "FACTORY_PROVENANCE.json",
        {
            "schema_version": "1.0",
            "factory_id": FACTORY_ID,
            "baseline_factory_id": BASELINE_FACTORY_ID,
            "factory_lineage": "V2_8_CODE_BASELINE_WITH_V2_9_CONTROL_AND_PORTABILITY_UPGRADE",
            "program_id": program_id,
            "target_id": target_id,
            "requirement_epoch": frozen_requirement_epoch,
            "requirement_ir_sha256": ir_hash,
            "compiled_requirement_ir_sha256": compiled_ir_hash,
            **(
                {
                    "authority_requirement_ir_sha256": authority_provenance.get(
                        "requirement_ir_sha256"
                    )
                }
                if _current_requirement_epoch(target) >= 31
                and isinstance(authority_provenance, Mapping)
                else {}
            ),
            "spec_content_sha256": spec_hash,
            "spec_file_count": spec_file_count,
            "created_at": created_at,
            "execution_started": False,
        },
    )
    _write_factory_implementation_manifest(staging)

    source_manifest = _source_manifest(ir, context)
    _write_json(staging / "canonical_sources/SOURCE_MANIFEST.json", source_manifest)
    _write_baseline_migration_contract(staging, ir, context)
    atom_catalog = _atom_catalog(ir, source_manifest, context)
    atom_catalog["source_manifest_sha256"] = _file_hash(
        staging / "canonical_sources/SOURCE_MANIFEST.json"
    )
    _write_json(staging / "canonical_sources/NORMATIVE_ATOM_CATALOG.json", atom_catalog)
    coverage = _coverage_matrix(ir, source_manifest, atom_catalog, context)
    coverage["source_manifest_sha256"] = _file_hash(
        staging / "canonical_sources/SOURCE_MANIFEST.json"
    )
    coverage["normative_atom_catalog_sha256"] = _file_hash(
        staging / "canonical_sources/NORMATIVE_ATOM_CATALOG.json"
    )
    _write_json(staging / "canonical_sources/ATOM_COVERAGE_MATRIX.json", coverage)
    _write_json(
        staging / "canonical_sources/TRACEABILITY_GRAPH.json",
        _traceability_graph(atom_catalog, coverage, context),
    )
    artifact_manifest = build_artifact_obligation_manifest(
        ir,
        target_id=target_id,
        program_id=program_id,
        requirement_ir_sha256=ir_hash,
        atom_catalog_sha256=_file_hash(
            staging / "canonical_sources/NORMATIVE_ATOM_CATALOG.json"
        ),
        coverage_matrix_sha256=_file_hash(
            staging / "canonical_sources/ATOM_COVERAGE_MATRIX.json"
        ),
    )
    if artifact_manifest is not None:
        _write_json(
            staging / "canonical_sources/ARTIFACT_OBLIGATION_MANIFEST.json",
            artifact_manifest,
        )
    _write_markdown_documents(staging, ir, context, artifact_manifest)
    _write_json(
        staging / "canonical_sources/REQUIREMENT_DECISIONS.json",
        {
            "schema_version": "2.8",
            "program_id": program_id,
            "assumptions": ir.get("assumptions", []),
            "open_questions": ir.get("open_questions", []),
            "decisions": ir.get("decisions", []),
            "user_adjustments": ir.get("user_adjustments", []),
            "automation": ir.get("automation", {}),
        },
    )
    _write_json(staging / "canonical_sources/FROZEN_REQUIREMENT_IR.json", ir)
    _write_json(
        staging / "validation/ACCEPTANCE_CASES.json",
        {
            "schema_version": "2.9",
            "target_id": target_id,
            "cases": _compile_acceptance_cases(ir),
            "status": "PLANNED_NOT_RUN",
        },
    )
    _write_json(
        staging / "validation/NEGATIVE_CASES.json",
        {
            "schema_version": "2.8",
            "target_id": target_id,
            "cases": _mandatory_negative_cases(ir),
            "status": "PLANNED_NOT_RUN",
        },
    )
    _write_json(
        staging / "canonical_sources/USER_ADJUSTMENT_RECORD.json",
        {
            "schema_version": "2.8",
            "target_id": target_id,
            "adjustments": ir.get("user_adjustments", []),
            "unapproved_invariant_weakening": [],
        },
    )

    template_root = spec / "templates/target_start_package"
    json_map = {
        "PACKAGE_MANIFEST.json": "TARGET_PACKAGE_MANIFEST.template.json",
        "START_CONTEXT.json": "START_CONTEXT.template.json",
        "PROFILE_LOCK.json": "PROFILE_LOCK.template.json",
        "CHARTER_LOCK.json": "CHARTER_LOCK.template.json",
        "PROGRAM_STATE.json": "PROGRAM_STATE.template.json",
        "THREE_PROJECT_PROGRAM_MANIFEST.json": "THREE_PROJECT_PROGRAM_MANIFEST.template.json",
        "ENGINEERING_PROJECT_DAG.json": "ENGINEERING_PROJECT_DAG.template.json",
        "PHASE_DEPENDENCY_MANIFEST.json": "PHASE_DEPENDENCY_MANIFEST.template.json",
        "WORKPACK_INDEX.json": "WORKPACK_INDEX.template.json",
        "WORKPACK_RESULT.json": "WORKPACK_RESULT.template.json",
        "COMMAND_MANIFEST.json": "COMMAND_MANIFEST.template.json",
        "CAPSULE.json": "CAPSULE.template.json",
        "RELEASE_PIPELINE_MANIFEST.json": "RELEASE_PIPELINE_MANIFEST.template.json",
        "PROGRAM_DRIVER_CONTRACT.json": "PROGRAM_DRIVER_CONTRACT.template.json",
        "PROGRAM_DRIVER_STATE.json": "PROGRAM_DRIVER_STATE.template.json",
        "PROGRAM_AUTOMATION_POLICY.json": "PROGRAM_AUTOMATION_POLICY.template.json",
        "AUTHORIZATION_POLICY.json": "AUTHORIZATION_POLICY.template.json",
        "EXECUTION_AUTHORIZATION.json": "EXECUTION_AUTHORIZATION.template.json",
        "REAL_TARGET_INSTALL_AUTHORIZATION.json": "REAL_TARGET_INSTALL_AUTHORIZATION.template.json",
        "LOOP_POLICY.json": "LOOP_POLICY.template.json",
        "LOOP_STATE.json": "LOOP_STATE.template.json",
        "FINDING_SCHEMA.json": "FINDING_SCHEMA.template.json",
        "REPAIR_ROUTING_RULES.json": "REPAIR_ROUTING_RULES.template.json",
        "INVALIDATION_DAG.json": "INVALIDATION_DAG.template.json",
        "REENTRY_PLAN.json": "REENTRY_PLAN.template.json",
        "PACKAGE_ROLES.json": "PACKAGE_ROLES.template.json",
        "build_program/conformance/CONFORMANCE_INTERFACE.json": "CONFORMANCE_INTERFACE.template.json",
        "constitution/RUNTIME_ATTESTATION_POLICY.json": "RUNTIME_ATTESTATION_POLICY.template.json",
    }
    documents: dict[str, Any] = {}
    for destination, template_name in json_map.items():
        template = json.loads((template_root / template_name).read_text(encoding="utf-8"))
        documents[destination] = _resolve_value(template, context, destination)

    _patch_critical_documents(
        documents,
        ir,
        context,
        staging,
        candidate,
        artifact_manifest,
    )
    for destination, document in documents.items():
        _write_json(staging / destination, document)
    _write_json(
        staging / "constitution/RUNTIME_OWNERSHIP.json",
        _runtime_ownership(context, candidate),
    )

    _materialize_workpack_files(staging, ir, context, documents)
    _materialize_project_packages(
        staging,
        spec,
        ir,
        context,
        candidate,
        artifact_manifest,
    )
    if (staging / "project_start_packages/external_lab/COMMAND_MANIFEST.json").is_file():
        # The Lab's native verifier declares this support even on compatibility
        # routes without the local Workpack runtime. Materialize by dependency,
        # not by a historical control-plane profile or Requirement epoch.
        _write_lab_protocol_support(staging)
    if control_plane_mode == EPOCH4_MODE:
        _write_epoch4_generation_profile(staging, generation_readiness)
        _apply_epoch4_default_route_selection(staging)
    _write_ledgers(staging, context)
    if control_plane_mode == EPOCH1_MODE:
        _write_control_kernel_bundle(staging, ir, context)
        _retire_legacy_control_paths(staging)
    elif control_plane_mode == EPOCH2_MODE:
        _write_shared_control_baseline_contract(staging, ir)
        _write_release_closure_control_plane_bundle(staging, ir, context)
        _retire_legacy_control_paths_for_epoch2(staging)
    elif control_plane_mode == EPOCH4_MODE:
        _write_shared_control_baseline_contract(staging, ir)
        _write_epoch4_runtime_store_dependency_closure(
            staging,
            include_workpack_runtime=frozen_requirement_epoch >= 45,
            include_package_validation_runtime=frozen_requirement_epoch >= 49,
        )
        _write_controlled_workpack_runtime_contract(
            staging,
            context,
            active_requirement_epoch=frozen_requirement_epoch,
        )
        _write_control_plane_registration_contract(staging)
        _write_program_driver_runtime_verification_contract(staging)
        _write_main_execution_package_validation_contract(
            staging,
            active_requirement_epoch=frozen_requirement_epoch,
        )
    else:
        _write_shared_control_baseline_contract(staging, ir)
        if assurance_profile_for_start_package(ir).profile_id == LOCAL_EXEC_UNTRUSTED_INPUT:
            # Operational capability is selected by the declared local profile,
            # not by the epoch number of Foundry's historical self-upgrade.
            profile_ref = "validation/CONTROL_STARTUP_PROFILE.json"
            _write_json(staging / profile_ref, {
                "schema_version": "1.0",
                "start_package_assurance_profile": LOCAL_EXEC_UNTRUSTED_INPUT,
                "assurance_profile": "SELF_USE_LOCAL_TRUSTED_OPERATOR",
                "profile_source": "FROZEN_REQUIREMENT_ASSURANCE_RESOLUTION",
                "sqlite_controller_contract": {
                    "mode": "START_PACKAGE_SQLITE_REGISTRATION",
                    "authority_ref": "harness-resource://execution/.harness-foundry/control.sqlite3",
                    "preparation_entrypoint": "prepare_action",
                    "proposal_is_commit": False,
                    "transaction_journal": "SQLITE_CONTROL_EVENTS",
                    "legacy_transaction_protocol": "NOT_EXECUTED_BY_SQLITE_ROUTE",
                    "compatibility_files_authoritative": False,
                    "legacy_writer_when_sqlite_present": "REJECT",
                    "driver_start_allowed": False,
                    "workpack_execution_allowed": False,
                },
                "execution_authorized": False,
            })
            _write_epoch4_runtime_store_dependency_closure(staging, include_workpack_runtime=True)
            _write_control_plane_registration_contract(staging, profile_ref=profile_ref)
            _write_program_driver_runtime_verification_contract(staging, profile_ref=profile_ref)
            _write_controlled_workpack_runtime_contract(
                staging, context, active_requirement_epoch=frozen_requirement_epoch,
                profile_ref=profile_ref,
            )
    _write_validation_report(staging, context)
    _bind_case_execution_contracts(staging, ir)

    if portable_mode == PORTABLE_MODE:
        source_bindings = _write_portable_source_evidence(staging, ir)
        _portableize_candidate(staging, ir, context, source_bindings)
        _repair_portable_project_bindings(staging)
        _repair_structural_hashes(staging)
        _repair_semantic_production_bindings(staging)
    _write_dag_path_containment_matrix(staging)
    _write_human_review_closure_receipt(staging, context)
    if portable_mode == PORTABLE_MODE:
        _write_portable_file_manifest(staging)

    unresolved = _scan_placeholders(staging)
    if unresolved:
        raise ValueError(f"compiler left unresolved template placeholders: {unresolved[:5]}")
    template_files = [path for path in staging.rglob("*") if path.is_file() and ".template." in path.name]
    if template_files:
        raise ValueError("compiler copied template filenames into the candidate")

    from .validator import (
        _validate_prepublication_staging_candidate,
        validate_candidate,
    )

    staging_report = validate_candidate(
        staging,
        expected_target_root=candidate,
        require_internal_report=False,
        authoritative_sources=requirement_ir.get("sources", []),
        authoritative_requirement_ir=requirement_ir,
        authority_provenance=authority_provenance,
    )
    repair_attempts = 0
    while staging_report.get("status") != "PASS" and repair_attempts < 3:
        repair_attempts += 1
        _repair_structural_hashes(staging)
        _repair_semantic_production_bindings(staging)
        _write_dag_path_containment_matrix(staging)
        _write_human_review_closure_receipt(staging, context)
        if portable_mode == PORTABLE_MODE:
            _write_portable_file_manifest(staging)
        staging_report = validate_candidate(
            staging,
            expected_target_root=candidate,
            require_internal_report=False,
            authoritative_sources=requirement_ir.get("sources", []),
            authoritative_requirement_ir=requirement_ir,
            authority_provenance=authority_provenance,
        )
    if staging_report.get("status") != "PASS":
        _write_json(staging / "validation/STAGING_VALIDATION_FAILURE.json", staging_report)
        codes = [item.get("code") for item in staging_report.get("blocking_findings", [])]
        raise ValueError(f"candidate staging validation failed: {codes}")
    _write_factory_regression_execution_receipt(
        staging,
        context,
        validator_report=staging_report,
    )
    _write_validation_report(
        staging,
        context,
        validator_report=staging_report,
        repair_attempts=repair_attempts,
    )
    if _current_requirement_epoch(requirement_ir.get("target", {})) >= 30:
        _write_validation_report_receipt(
            staging,
            context,
            authority_provenance=authority_provenance,
            local_profile=control_plane_mode == EPOCH4_MODE,
        )
    _write_human_review_closure_receipt(staging, context)
    if portable_mode == PORTABLE_MODE:
        _write_portable_file_manifest(staging)
    final_staging_report = _validate_prepublication_staging_candidate(
        staging,
        expected_target_root=candidate,
        authoritative_sources=requirement_ir.get("sources", []),
        authoritative_requirement_ir=requirement_ir,
        authority_provenance=authority_provenance,
    )
    if final_staging_report.get("status") != "PASS":
        raise ValueError(
            "candidate final staging validation failed: "
            f"{[item.get('code') for item in final_staging_report.get('blocking_findings', [])]}"
        )
    if control_plane_mode == EPOCH2_MODE:
        self_check_environment = dict(os.environ)
        self_check_environment["PYTHONDONTWRITEBYTECODE"] = "1"
        with tempfile.TemporaryDirectory(
            prefix="hffactory-source-authority-policy-"
        ) as policy_directory:
            policy_path = Path(policy_directory) / "SOURCE_AUTHORITY_POLICY_LOCK.json"
            trust_anchor_path = (
                Path(policy_directory) / "SOURCE_AUTHORITY_TRUST_ANCHOR.json"
            )
            policy, trust_anchor = _ephemeral_source_authority_fixture(
                requirement_ir,
                staging,
            )
            _write_json(policy_path, policy)
            _write_json(trust_anchor_path, trust_anchor)
            self_check_environment["HF_SOURCE_AUTHORITY_POLICY_LOCK"] = str(
                policy_path
            )
            self_check_environment["HF_SOURCE_AUTHORITY_TRUST_ANCHOR"] = str(
                trust_anchor_path
            )
            self_check_environment[
                "HF_SOURCE_AUTHORITY_TRUST_ANCHOR_SHA256"
            ] = _file_hash(trust_anchor_path)
            self_check = subprocess.run(
                ["python3", "tools/self_check.py"],
                cwd=staging,
                env=self_check_environment,
                capture_output=True,
                text=True,
                check=False,
            )
        try:
            self_check_report = json.loads(self_check.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "candidate standalone self-check returned non-JSON output: "
                f"{self_check.stderr.strip()}"
            ) from exc
        if (
            self_check.returncode != 0
            or self_check_report.get("status") != "PASS"
        ):
            raise ValueError(
                "candidate standalone self-check failed: "
                f"{self_check_report.get('findings', [])}"
            )

    candidate.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, candidate)
    _seal_candidate_tree(candidate)
    content_hash, file_count = _tree_hash(candidate)
    return {
        "program_id": program_id,
        "target_id": target_id,
        "candidate_path": str(candidate),
        "manifest_path": str(candidate / "PACKAGE_MANIFEST.json"),
        "file_count": file_count,
        "content_sha256": content_hash,
        "_prepublication_validation_report": final_staging_report,
        "authoring_terminal_state": TARGET_CANDIDATE_STATE,
        "execution_started": False,
    }


def _validate_ir(ir: Mapping[str, Any]) -> dict[str, Any]:
    target = ir.get("target")
    if not isinstance(target, Mapping):
        raise ValueError("requirement_ir.target must be an object")
    required = ("id", "name", "type", "profile", "output_root", "mission", "scope", "non_goals", "primary_runtime")
    missing = [key for key in required if key not in target or target[key] in (None, "")]
    if missing:
        raise ValueError(f"requirement_ir.target missing: {', '.join(missing)}")
    if str(target["type"]).upper() not in {"AGENT", "HARNESS", "HYBRID"}:
        raise ValueError("target.type must be AGENT, HARNESS, or HYBRID")
    if str(target["profile"]).upper() not in {"FULL", "STANDARD", "LITE"}:
        raise ValueError("target.profile must be FULL, STANDARD, or LITE")
    portability_mode = str(target.get("portability_mode") or PORTABLE_MODE)
    if portability_mode not in {"LEGACY_ABSOLUTE_PATHS", PORTABLE_MODE}:
        raise ValueError(
            "target.portability_mode must be LEGACY_ABSOLUTE_PATHS or "
            "LOGICAL_RESOURCE_URI"
        )
    target_id = str(target["id"])
    program_id = str(ir.get("program_id") or f"PROGRAM-{target_id}")
    for label, value in (("target.id", target_id), ("program_id", program_id)):
        if not SAFE_ID_RE.fullmatch(value) or ".." in value:
            raise ValueError(f"{label} must be a path-safe identifier")
    output_root = Path(str(target["output_root"])).expanduser()
    if not output_root.is_absolute():
        raise ValueError("target.output_root must be absolute")
    execution_root_value = target.get("execution_root")
    if execution_root_value not in (None, ""):
        execution_root = Path(str(execution_root_value)).expanduser()
        if not execution_root.is_absolute():
            raise ValueError("target.execution_root must be absolute")
        output_root = output_root.resolve()
        execution_root = execution_root.resolve()
        if output_root.is_relative_to(execution_root) or execution_root.is_relative_to(
            output_root
        ):
            raise ValueError(
                "target.output_root and target.execution_root must not overlap"
            )
    # A physical Execution Root is a later runtime binding, not a Candidate
    # authoring input.  When it is absent the compiler reserves a disjoint,
    # still-absent identity and exports only the logical execution Resource URI.
    for key in ("sources", "atoms", "acceptance_cases", "negative_cases"):
        if not isinstance(ir.get(key), list) or not ir[key]:
            raise ValueError(f"requirement_ir.{key} must be a non-empty array")
    atom_ids = {
        str(item.get("atom_id"))
        for item in ir.get("atoms", [])
        if isinstance(item, Mapping) and item.get("atom_id")
    }
    coverage_edges = [
        item for item in ir.get("coverage_edges", []) if isinstance(item, Mapping)
    ]
    coverage_atom_ids = [str(item.get("atom_id")) for item in coverage_edges]
    if (
        len(coverage_edges) != len(ir.get("coverage_edges", []))
        or len(set(coverage_atom_ids)) != len(coverage_atom_ids)
        or set(coverage_atom_ids) != atom_ids
        or any(
            not item.get("workpack_ids")
            or not set(item.get("workpack_ids", [])).issubset(WORKPACK_PROJECTS)
            or not item.get("stage_ids")
            or not set(item.get("stage_ids", [])).issubset(PHASE_ORDER)
            or not set(item.get("release_step_ids", [])).issubset(
                RELEASE_STEP_ORDER
            )
            or set(item.get("owner_project_ids", []))
            != {
                WORKPACK_PROJECTS[workpack_id]
                for workpack_id in item.get("workpack_ids", [])
            }
            for item in coverage_edges
        )
    ):
        raise ValueError("requirement_ir.coverage_edges must cover every Atom with resolvable engineering targets")
    blocking = [q for q in ir.get("open_questions", []) if isinstance(q, Mapping) and q.get("blocking") is True and q.get("status") not in {"RESOLVED", "CLOSED"}]
    if blocking:
        raise ValueError("blocking open questions must be resolved before compilation")
    unresolved_conflicts = [
        item
        for item in ir.get("source_conflicts", [])
        if isinstance(item, Mapping)
        and str(item.get("status", "OPEN")).upper() not in {"RESOLVED", "CLOSED"}
    ]
    if unresolved_conflicts:
        raise ValueError("source conflicts must be resolved before compilation")
    automation = ir.get("automation", {})
    if not isinstance(automation, Mapping):
        raise ValueError("requirement_ir.automation must be an object")
    for key in ("max_transitions", "max_loop_rounds"):
        if key in automation and (
            not isinstance(automation[key], int) or automation[key] <= 0
        ):
            raise ValueError(f"requirement_ir.automation.{key} must be a positive integer")
    production_findings = validate_explicit_production_contracts(ir)
    if production_findings:
        raise ValueError(
            "requirement_ir explicit production contracts invalid: "
            f"{[item['code'] for item in production_findings]}"
        )
    return dict(target)


def _write_factory_implementation_manifest(staging: Path) -> None:
    """Bind the exact producer implementation without exporting local paths."""

    repository_root = Path(__file__).resolve().parents[2]
    files: dict[str, str] = {}
    for relative in FACTORY_IMPLEMENTATION_PATHS:
        path = repository_root / relative
        if not path.is_file():
            raise ValueError(f"Factory implementation file is missing: {relative}")
        files[relative] = _file_hash(path)
    manifest = {
        "schema_version": "1.0",
        "factory_id": FACTORY_ID,
        "baseline_factory_id": BASELINE_FACTORY_ID,
        "hash_algorithm": "sha256",
        "identity_mode": "REPOSITORY_RELATIVE_SELECTED_IMPLEMENTATION_TREE",
        "implementation_tree_sha256": _json_hash(files),
        "files": files,
    }
    manifest_path = staging / "FACTORY_IMPLEMENTATION_MANIFEST.json"
    _write_json(manifest_path, manifest)
    provenance_path = staging / "FACTORY_PROVENANCE.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance.update(
        {
            "factory_implementation_manifest_ref": (
                "FACTORY_IMPLEMENTATION_MANIFEST.json"
            ),
            "factory_implementation_manifest_sha256": _file_hash(manifest_path),
            "factory_implementation_tree_sha256": manifest[
                "implementation_tree_sha256"
            ],
            "compiler_implementation_sha256": files[
                "src/harness_foundry_factory/compiler.py"
            ],
            "validator_implementation_sha256": files[
                "src/harness_foundry_factory/validator.py"
            ],
            "semantic_contracts_implementation_sha256": files[
                "src/harness_foundry_factory/semantic_contracts.py"
            ],
        }
    )
    _write_json(provenance_path, provenance)


def _source_evidence_uri(source_id: str, suffix: str) -> str:
    return (
        f"{LOGICAL_CANDIDATE_ROOT}/canonical_sources/evidence/"
        f"{source_id}.{suffix}"
    )


def _write_portable_source_evidence(
    staging: Path, ir: Mapping[str, Any]
) -> dict[str, dict[str, str | None]]:
    """Make every exported source reference resolve inside the Candidate.

    Immutable file snapshots are base64 encoded so their exact bytes remain
    recoverable even when the source text contains examples of forbidden local
    paths. Event-ledger sources receive a local receipt and point to the frozen
    semantic projection; the receipt explicitly does not claim to embed the
    unavailable original chat payload.
    """

    evidence_root = staging / "canonical_sources/evidence"
    evidence_root.mkdir(parents=True, exist_ok=True)
    manifest_path = staging / "canonical_sources/SOURCE_MANIFEST.json"
    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_sources = {
        str(item.get("source_id")): item
        for item in source_manifest.get("sources", [])
        if isinstance(item, dict) and item.get("source_id")
    }
    bindings: dict[str, dict[str, str | None]] = {}
    index_entries: list[dict[str, Any]] = []
    for index, raw in enumerate(ir.get("sources", []), 1):
        item = raw if isinstance(raw, Mapping) else {}
        source_id = str(item.get("source_id") or f"SRC-{index:03d}")
        source = manifest_sources[source_id]
        source_hash = str(source["sha256"])
        receipt_relative = (
            f"canonical_sources/evidence/{source_id}.source_receipt.json"
        )
        receipt_uri = _source_evidence_uri(source_id, "source_receipt.json")
        payload_relative: str | None = None
        payload_uri: str | None = None
        payload_embedded = False
        repository_metadata = {
            field: deepcopy(source[field])
            for field in (
                "repository_url",
                "revision",
                "commit_sha",
                "git_tree_oid",
                "tree_sha256",
                "license_spdx",
                "license_ref",
                "retrieved_at",
            )
            if source.get(field) not in (None, "")
        }
        snapshot_path = item.get("snapshot_path")
        if (
            source.get("copy_policy") == "COPY_IMMUTABLE_SNAPSHOT"
            and isinstance(snapshot_path, str)
            and snapshot_path
        ):
            snapshot = Path(snapshot_path).expanduser()
            if not snapshot.is_file():
                raise ValueError(
                    f"immutable source snapshot missing at compile time: {source_id}"
                )
            payload = snapshot.read_bytes()
            if hashlib.sha256(payload).hexdigest() != source_hash:
                raise ValueError(
                    f"immutable source snapshot hash mismatch: {source_id}"
                )
            payload_relative = (
                f"canonical_sources/evidence/{source_id}.payload.b64"
            )
            payload_uri = _source_evidence_uri(source_id, "payload.b64")
            _write_text(
                staging / payload_relative,
                base64.b64encode(payload).decode("ascii"),
            )
            payload_embedded = True
        receipt = {
            "schema_version": "1.0",
            "source_id": source_id,
            "source_sha256": source_hash,
            "authority_level": source.get("authority_level"),
            "copy_policy": source.get("copy_policy"),
            "repository_metadata": repository_metadata or None,
            "origin_locator_sha256": hashlib.sha256(
                str(item.get("path_or_uri") or item.get("path") or "").encode(
                    "utf-8"
                )
            ).hexdigest(),
            "payload_embedded": payload_embedded,
            "payload_ref": payload_uri,
            "payload_encoding": "BASE64" if payload_embedded else None,
            "semantic_projection_refs": [
                f"{LOGICAL_CANDIDATE_ROOT}/canonical_sources/FROZEN_REQUIREMENT_IR.json",
                f"{LOGICAL_CANDIDATE_ROOT}/canonical_sources/REQUIREMENT_DECISIONS.json",
            ],
            "non_claim": (
                None
                if payload_embedded
                else "ORIGINAL_EVENT_PAYLOAD_NOT_EMBEDDED; RECEIPT_RESOLVES_IDENTITY_AND_FROZEN_SEMANTICS_ONLY"
            ),
        }
        _write_json(staging / receipt_relative, receipt)
        source.update(
            {
                "path_or_uri": receipt_uri,
                "portable_evidence_ref": receipt_uri,
                "snapshot_path": payload_uri or receipt_uri,
                "payload_embedded": payload_embedded,
            }
        )
        binding = {"receipt_uri": receipt_uri, "payload_uri": payload_uri}
        bindings[source_id] = binding
        index_entries.append(
            {
                "source_id": source_id,
                "source_sha256": source_hash,
                "copy_policy": source.get("copy_policy"),
                "repository_metadata": repository_metadata or None,
                "receipt_ref": receipt_uri,
                "receipt_sha256": _file_hash(staging / receipt_relative),
                "payload_ref": payload_uri,
                "payload_file_sha256": (
                    _file_hash(staging / payload_relative)
                    if payload_relative is not None
                    else None
                ),
                "payload_embedded": payload_embedded,
            }
        )
    _write_json(manifest_path, source_manifest)
    _write_json(
        staging / "canonical_sources/PORTABLE_SOURCE_INDEX.json",
        {
            "schema_version": "1.0",
            "candidate_root": LOGICAL_CANDIDATE_ROOT,
            "source_count": len(index_entries),
            "all_source_references_resolve_in_candidate": True,
            "all_copy_immutable_snapshots_embedded": all(
                entry["payload_embedded"]
                for entry in index_entries
                if entry["copy_policy"] == "COPY_IMMUTABLE_SNAPSHOT"
            ),
            "sources": index_entries,
        },
    )
    return bindings


def _effective_required_tools(value: Any) -> list[dict[str, Any]]:
    aliases = {
        "python 3.12": ("python", ">=3.12,<3.13", "python.org or operating-system vendor"),
        "node.js 22 lts": ("node", ">=22,<23", "nodejs.org or declared package manager"),
        "remotion": ("remotion", "PIN_EXACT_IN_MAIN_PROJECT_LOCK", "npm registry or declared mirror"),
        "ffmpeg": ("ffmpeg", "PIN_EXACT_BEFORE_WORKPACK_EXECUTION", "ffmpeg.org or operating-system package manager"),
        "ffprobe": ("ffprobe", "SAME_DISTRIBUTION_AS_FFMPEG", "ffmpeg.org or operating-system package manager"),
        "mlx-audio": ("mlx-audio", "PIN_EXACT_IN_MAIN_PROJECT_LOCK", "Python Package Index or declared mirror"),
        "qwen3-tts 0.6b 8-bit": ("qwen3-tts-model", "0.6B-8BIT-PIN_EXACT_MODEL_HASH", "declared local model registry"),
        "qwen3 forcedaligner 0.6b 8-bit": ("qwen3-forced-aligner-model", "0.6B-8BIT-PIN_EXACT_MODEL_HASH", "declared local model registry"),
        "kokoro 82m fallback": ("kokoro-82m-model", "82M-PIN_EXACT_MODEL_HASH", "declared local model registry"),
        "pinned video-shotcraft": ("video-shotcraft", "PIN_EXACT_FROZEN_SOURCE_COMMIT_BEFORE_EXECUTION", "frozen source repository"),
    }

    def normalize(item: Any) -> dict[str, Any] | None:
        if isinstance(item, Mapping):
            raw = dict(item)
            if raw.get("tool_id"):
                return raw
            label = raw.get("name") or raw.get("requirement_label")
            if not isinstance(label, str) or not label.strip():
                return None
            normalized = normalize(label)
            if normalized is None:
                return None
            normalized.update(raw)
            normalized.pop("name", None)
            normalized["requirement_label"] = label
            return normalized
        if not isinstance(item, str) or not item.strip():
            return None
        label = item.strip()
        key = re.sub(r"\s+", " ", label).casefold()
        tool_id, version, installation_source = aliases.get(
            key,
            (
                re.sub(r"[^a-z0-9]+", "-", key).strip("-") or "declared-tool",
                "PIN_EXACT_BEFORE_WORKPACK_EXECUTION",
                "human-declared distribution source",
            ),
        )
        return {
            "tool_id": tool_id,
            "requirement_label": label,
            "version_constraint": version,
            "purpose": f"Frozen target-required tool: {label}",
            "availability_phase": "TARGET_TOOLCHAIN_MATERIALIZATION",
            "required_for_self_check": False,
            "installation_source": installation_source,
        }

    declared: list[dict[str, Any]] = []
    raw_values = [value] if isinstance(value, (str, Mapping)) else value or []
    for item in raw_values:
        normalized = normalize(item)
        if normalized is not None:
            declared.append(normalized)
    defaults = (
        {
            "tool_id": "python",
            "version_constraint": ">=3.11,<4",
            "purpose": "Candidate self-check, runtime setup, project virtual environments and standard-library unittest",
            "availability_phase": "RECEIVER_PRECONDITION",
            "required_for_self_check": True,
            "installation_source": "python.org or operating-system vendor",
        },
        {
            "tool_id": "python-package-cryptography",
            "version_constraint": ">=45,<49",
            "purpose": "Ed25519 verification of the pinned external authority root in Candidate self-check and production Event Store Adapter",
            "availability_phase": "RECEIVER_PRECONDITION",
            "required_for_self_check": True,
            "installation_source": "Python Package Index or declared mirror",
        },
        {
            "tool_id": "codex-cli",
            "version_constraint": "PIN_EXACT_BEFORE_EXECUTION_AUTHORIZATION",
            "purpose": "planned coding executor for generated Workpacks",
            "availability_phase": "AUTHORING_EXECUTION_PRECONDITION",
            "installation_source": "official OpenAI distribution",
        },
        {
            "tool_id": "pytest",
            "version_constraint": "PIN_EXACT_IN_MAIN_PROJECT_LOCK",
            "purpose": "planned main-build test module",
            "availability_phase": "MAIN_PROJECT_ENVIRONMENT_MATERIALIZATION",
            "installation_source": "Python Package Index or declared mirror",
        },
        {
            "tool_id": "build",
            "version_constraint": "PIN_EXACT_IN_MAIN_PROJECT_LOCK",
            "purpose": "planned Python wheel build module",
            "availability_phase": "MAIN_PROJECT_ENVIRONMENT_MATERIALIZATION",
            "installation_source": "Python Package Index or declared mirror",
        },
        {
            "tool_id": "program-driver",
            "version_constraint": "BUILT_AND_HASH_BOUND_BEFORE_USE",
            "purpose": "planned bounded Program Driver executable",
            "availability_phase": "CONTROL_PLANE_BUILD_OUTPUT",
            "installation_source": "generated and verified by this Program",
        },
        {
            "tool_id": "linkage-review-cli",
            "version_constraint": "BUILT_AND_HASH_BOUND_BEFORE_USE",
            "purpose": "planned read-only linkage review executable",
            "availability_phase": "LINKAGE_PROJECT_BUILD_OUTPUT",
            "installation_source": "generated and verified by this Program",
        },
        {
            "tool_id": "linkage-review-module",
            "version_constraint": "BUILT_AND_HASH_BOUND_BEFORE_USE",
            "purpose": "planned linkage_review Python module",
            "availability_phase": "LINKAGE_PROJECT_BUILD_OUTPUT",
            "installation_source": "generated and verified by this Program",
        },
        {
            "tool_id": "external-lab-module",
            "version_constraint": "BUILT_AND_HASH_BOUND_BEFORE_USE",
            "purpose": "planned external_lab Python module",
            "availability_phase": "LAB_PROJECT_BUILD_OUTPUT",
            "installation_source": "generated and verified by this Program",
        },
    )
    by_id = {
        str(item.get("tool_id")): item
        for item in declared
        if item.get("tool_id")
    }
    for default in defaults:
        tool_id = str(default["tool_id"])
        if tool_id not in by_id:
            declared.append(dict(default))
            by_id[tool_id] = declared[-1]
    return declared


def _local_profile_external_authority_not_applicable(
    staging: Path,
    target: Mapping[str, Any],
) -> bool:
    """Return whether the active local profile explicitly disables external certification."""

    try:
        profile = json.loads(
            (staging / "EPOCH38_GENERATION_PROFILE.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    correction = target.get("v2_9_charter_architecture_correction_epoch38")
    threat_model = (
        correction.get("threat_model")
        if isinstance(correction, Mapping)
        else None
    )
    return bool(
        target.get("architecture_epoch") == 4
        and target.get("control_plane_epoch") == 4
        and target.get("assurance_profile_id")
        == "SELF_USE_LOCAL_TRUSTED_OPERATOR"
        and target.get("operating_assurance_profile")
        == "SELF_USE_LOCAL_TRUSTED_OPERATOR"
        and isinstance(threat_model, Mapping)
        and threat_model.get("external_trust_anchor") == "NOT_APPLICABLE"
        and threat_model.get("external_certification_offered") is False
        and isinstance(profile, Mapping)
        and profile.get("profile_kind")
        == "SELF_USE_LOCAL_CORE_CANDIDATE_ROUTE"
        and profile.get("assurance_profile")
        == "SELF_USE_LOCAL_TRUSTED_OPERATOR"
        and profile.get("external_certification_claimed") is False
        and profile.get("optional_security_hardening")
        in {"NOT_APPLICABLE", "NOT_RUN"}
        and profile.get("external_trust_anchor") == "NOT_APPLICABLE"
    )


def _external_receiver_authority_required(
    staging: Path,
    target: Mapping[str, Any],
) -> bool:
    if _local_profile_external_authority_not_applicable(staging, target):
        return False
    try:
        profile = json.loads(
            (staging / "EPOCH38_GENERATION_PROFILE.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        profile = None
    declared_profile = target.get("operating_assurance_profile") or target.get(
        "assurance_profile_id"
    )
    epoch4_active = bool(
        target.get("architecture_epoch") == 4
        and target.get("control_plane_epoch") == 4
    )
    return bool(
        isinstance(target.get("v0_24_human_review_remediation"), Mapping)
        or (
            epoch4_active
            and (
                isinstance(declared_profile, str)
                or (
                    isinstance(profile, Mapping)
                    and (
                        profile.get("external_certification_claimed") is not False
                        or profile.get("optional_security_hardening")
                        not in {"NOT_APPLICABLE", "NOT_RUN"}
                        or profile.get("external_trust_anchor") != "NOT_APPLICABLE"
                    )
                )
            )
        )
    )


def _external_receiver_authority_disposition(
    staging: Path,
    target: Mapping[str, Any],
) -> str:
    if _local_profile_external_authority_not_applicable(staging, target):
        return "NOT_APPLICABLE_SELF_USE_LOCAL_TRUSTED_OPERATOR"
    if _external_receiver_authority_required(staging, target):
        return "REQUIRED_FOR_EXTERNAL_CERTIFICATION"
    return "NOT_APPLICABLE_NO_EXTERNAL_CERTIFICATION_PROFILE"


def _portableize_candidate(
    staging: Path,
    ir: Mapping[str, Any],
    context: Mapping[str, str],
    source_bindings: Mapping[str, Mapping[str, str | None]],
) -> None:
    """Project local authoring bindings into portable logical references.

    The authoritative Requirement IR hash continues to commit to the local
    Program state.  The candidate carries a path-redacted projection plus its
    own hash; no resolved author-machine path is exported.
    """

    replacements: list[tuple[str, str]] = [
        (str(context["execution_root"]), LOGICAL_EXECUTION_ROOT),
        (str(context["candidate_root"]), LOGICAL_CANDIDATE_ROOT),
    ]
    target = ir.get("target") if isinstance(ir.get("target"), Mapping) else {}
    declared_output_root = target.get("output_root")
    if isinstance(declared_output_root, str) and declared_output_root:
        replacements.append((declared_output_root, LOGICAL_CANDIDATE_ROOT))
    declared_execution_root = target.get("execution_root")
    if isinstance(declared_execution_root, str) and declared_execution_root:
        replacements.append((declared_execution_root, LOGICAL_EXECUTION_ROOT))
    candidate_workspace = Path(str(context["candidate_root"])).parent
    execution_workspace = Path(str(context["execution_root"])).parent
    replacements.append(
        (str(candidate_workspace), "local-binding://candidate-workspace")
    )
    if execution_workspace != candidate_workspace:
        replacements.append(
            (str(execution_workspace), "local-binding://execution-workspace")
        )
    previous_output_root = target.get("previous_output_root")
    if isinstance(previous_output_root, str) and previous_output_root:
        replacements.append(
            (previous_output_root, "local-binding://previous-output-root")
        )
    previous_execution_root = target.get("previous_execution_root")
    if isinstance(previous_execution_root, str) and previous_execution_root:
        replacements.append(
            (previous_execution_root, "local-binding://previous-execution-root")
        )
    for index, raw_source in enumerate(ir.get("sources", []), 1):
        if not isinstance(raw_source, Mapping):
            continue
        source_id = str(raw_source.get("source_id") or f"SRC-{index:03d}")
        binding = source_bindings.get(source_id, {})
        receipt_uri = str(
            binding.get("receipt_uri")
            or f"{LOGICAL_CANDIDATE_ROOT}/canonical_sources/evidence/{source_id}.source_receipt.json"
        )
        payload_uri = str(binding.get("payload_uri") or receipt_uri)
        snapshot_path = raw_source.get("snapshot_path")
        if isinstance(snapshot_path, str) and snapshot_path:
            replacements.append((snapshot_path, payload_uri))
        source_path = raw_source.get("path_or_uri") or raw_source.get("path")
        if (
            isinstance(source_path, str)
            and source_path
            and "://" not in source_path
        ):
            replacements.append((source_path, receipt_uri))
    replacements.sort(key=lambda item: len(item[0]), reverse=True)

    def project_string(value: str) -> str:
        projected = value
        for local_value, logical_value in replacements:
            projected = projected.replace(local_value, logical_value)
        return projected

    def project(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: project(item) for key, item in value.items()}
        if isinstance(value, list):
            return [project(item) for item in value]
        if isinstance(value, str):
            return project_string(value)
        return value

    for path in sorted(staging.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix == ".json":
            value = json.loads(path.read_text(encoding="utf-8"))
            _write_json(path, project(value))
        elif path.suffix == ".jsonl":
            lines = []
            for line in path.read_text(encoding="utf-8").splitlines():
                lines.append(
                    json.dumps(
                        project(json.loads(line)),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    if line.strip()
                    else ""
                )
            _write_text(path, "\n".join(lines))
        elif path.suffix == ".md":
            _write_text(path, project_string(path.read_text(encoding="utf-8")))

    frozen_path = staging / "canonical_sources/FROZEN_REQUIREMENT_IR.json"
    frozen_ir = json.loads(frozen_path.read_text(encoding="utf-8"))
    frozen_ir["portable_projection"] = {
        "schema_version": "1.0",
        "portability_mode": PORTABLE_MODE,
        "source_requirement_ir_sha256": context["ir_hash"],
        "local_binding_policy": "LOCAL_ONLY_NON_EXPORTABLE",
        "logical_roots": {
            "candidate": LOGICAL_CANDIDATE_ROOT,
            "execution": LOGICAL_EXECUTION_ROOT,
        },
    }
    _write_json(frozen_path, frozen_ir)
    portable_ir_hash = _file_json_hash(frozen_path)

    provenance_path = staging / "FACTORY_PROVENANCE.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance.update(
        {
            "portability_mode": PORTABLE_MODE,
            "local_binding_policy": "LOCAL_ONLY_NON_EXPORTABLE",
            "portable_requirement_ir_sha256": portable_ir_hash,
        }
    )
    _write_json(provenance_path, provenance)
    required_tools = _effective_required_tools(target.get("required_tools"))
    local_external_authority_not_applicable = (
        _local_profile_external_authority_not_applicable(staging, target)
    )
    external_receiver_authority_required = (
        _external_receiver_authority_required(staging, target)
    )
    release_requirements = {
        "primary_runtime": str(target.get("primary_runtime") or "UNDECLARED"),
        "required_tools": required_tools,
        "required_plugins": list(target.get("required_plugins") or []),
        "required_mcp_servers": list(target.get("required_mcp_servers") or []),
        "environment_contract_refs": list(
            target.get("environment_contract_refs") or []
        ),
        "self_check": {
            "command": "python3 tools/self_check.py",
            "python_version_constraint": ">=3.11,<4",
            "standard_library_only": False,
            "network_required": False,
            "external_packages": ["cryptography>=45,<49"],
            "receiver_authority_preflight_mode": "PROFILE_AWARE",
            **(
                {
                    "external_receiver_authority_required": True,
                    "external_receiver_authority_disposition": (
                        "REQUIRED_FOR_EXTERNAL_CERTIFICATION"
                    ),
                    "required_receiver_environment": [
                        "HF_SOURCE_AUTHORITY_POLICY_LOCK",
                        "HF_SOURCE_AUTHORITY_TRUST_ANCHOR",
                        "HF_SOURCE_AUTHORITY_TRUST_ANCHOR_SHA256",
                    ],
                    "receiver_policy_must_be_external_to_candidate": True,
                    "receiver_trust_anchor_must_be_external_to_candidate": True,
                    "receiver_trust_anchor_hash_must_be_pinned_outside_candidate": True,
                }
                if external_receiver_authority_required
                else {
                    "external_receiver_authority_required": False,
                    "external_receiver_authority_disposition": (
                        "NOT_APPLICABLE_SELF_USE_LOCAL_TRUSTED_OPERATOR"
                    ),
                    "external_certification_claimed": False,
                    "optional_security_hardening": str(
                        json.loads(
                            (
                                staging / "EPOCH38_GENERATION_PROFILE.json"
                            ).read_text(encoding="utf-8")
                        ).get("optional_security_hardening")
                    ),
                }
                if local_external_authority_not_applicable
                else {
                    "external_receiver_authority_required": False,
                    "external_receiver_authority_disposition": (
                        "NOT_APPLICABLE_NO_EXTERNAL_CERTIFICATION_PROFILE"
                    ),
                }
            ),
        },
        "runtime_setup": {
            "command": "python3 tools/setup_runtime.py --execution-root ../Harness_Foundry_execution",
            "python_version_constraint": ">=3.11,<4",
            "standard_library_only": True,
            "network_required": False,
            "writes_candidate": False,
            "binding_receipt_location": "harness-resource://execution/.harness-foundry/runtime_binding.json",
        },
    }
    _write_json(
        staging / "validation/PORTABILITY_MANIFEST.json",
        {
            "schema_version": "1.0",
            "portability_mode": PORTABLE_MODE,
            "local_binding_policy": "LOCAL_ONLY_NON_EXPORTABLE",
            "logical_roots": {
                "candidate": LOGICAL_CANDIDATE_ROOT,
                "execution": LOGICAL_EXECUTION_ROOT,
            },
            "source_requirement_ir_sha256": context["ir_hash"],
            "portable_requirement_ir_sha256": portable_ir_hash,
            "resolved_paths_persisted": False,
            "external_symlinks_allowed": False,
            "release_requirements": release_requirements,
        },
    )
    readme_path = staging / "README.md"
    readme = readme_path.read_text(encoding="utf-8").rstrip()
    tools = ", ".join(
        _dependency_label(item) for item in release_requirements["required_tools"]
    ) or "none declared"
    plugins = ", ".join(
        _dependency_label(item) for item in release_requirements["required_plugins"]
    ) or "none declared"
    mcp_servers = (
        ", ".join(
            _dependency_label(item)
            for item in release_requirements["required_mcp_servers"]
        )
        or "none declared"
    )
    environment_refs = (
        ", ".join(release_requirements["environment_contract_refs"])
        or "none declared"
    )
    control_kernel_section = ""
    if (staging / "V2_9_CONTROL_KERNEL_MANIFEST.json").is_file():
        control_kernel_section = """

### v2.9 Generic Control Kernel

`V2_9_CONTROL_KERNEL_MANIFEST.json` is the hash-bound index for the generic
control runtime. `ASSURANCE_PROFILE.json` selects risk and assurance facts;
`CONTROL_PLANE_PROGRAM_GRAPH.json` instantiates the Profile-driven graph;
`DECISION_POLICY.json` and `TRANSITION_CONTRACTS.json` bind fail-closed rules
and transitions. `canonical_sources/CORRECTION_COVERAGE_MATRIX.json` shows
exactly how CORR-29-001 through CORR-29-008 map to frozen P0 Atoms,
implementation artifacts, validation, and Candidate-static versus
Runtime-pending evidence.

`PROFILE_READ_VALIDATION_ADAPTER_BINDING.json` describes the planned adapter
identity without inventing an implementation path or Hash. A Runtime may bind
it only by producing a new transition contract whose Hash is also carried by
the attempt-scoped Derived Grant. `CONTROL_EVENT_STORE_ACTIVATION_CONTRACT.json`
binds the Candidate-native SQLite tables, ordered columns, append-only database
triggers, implementation Hash, and the separate bootstrap-import authorization
boundary. Candidate authoring creates or migrates no execution database.

`VALIDATION_FAILED` means a declared deterministic check failed and no unknown
side effect occurred. The Engine consumes that one attempt Grant and appends a
durable `DETERMINISTIC_VALIDATION_FAILURE` stop without retrying or asking for
new human authority. It is neither PASS, a transient failure, nor an
unknown-side-effect emergency.

A human may approve a bounded Parent Risk Envelope; only the machine may derive
an attempt-scoped Derived Grant inside that envelope. This Candidate grants
neither. All command adapters remain `PLANNED_NOT_BOUND`, so the graph is a
verified executable contract bundle, not evidence that Runtime work occurred.
The standalone command `python3 tools/self_check.py` independently checks these
semantic bindings as well as file hashes. Candidate PASS proves static package
closure only; it does not prove Driver start, Workpack execution, installation,
publication, Runtime success, or certification.
"""
    epoch24_self_check_note = (
        " Before running it, the receiver launcher must provide the three "
        "external bindings documented below; Candidate-local files are rejected."
        if external_receiver_authority_required
        else (
            " Under `SELF_USE_LOCAL_TRUSTED_OPERATOR`, external receiver "
            "Authority is `NOT_APPLICABLE`; the check remains diagnostic and "
            "does not claim external certification."
            if local_external_authority_not_applicable
            else ""
        )
    )
    _write_text(
        readme_path,
        f"""{readme}

## Portable release binding

This Candidate uses true logical Resource URIs.
`{LOGICAL_CANDIDATE_ROOT}` identifies the read-only directory containing this
package; `{LOGICAL_EXECUTION_ROOT}` identifies a separate writable runtime
directory selected on the receiving machine. A launcher must resolve both URIs
locally, enforce root containment, and never persist resolved machine paths in
the Candidate.

- Primary runtime: {release_requirements['primary_runtime']}
- Required tools: {tools}
- Required plugins: {plugins}
- Required MCP servers: {mcp_servers}
- Environment contract references: {environment_refs}
- Binding authority: `validation/PORTABILITY_MANIFEST.json`

### Local runtime binding

From the Candidate root, run
`python3 tools/setup_runtime.py --execution-root ../Harness_Foundry_execution`.
The setup tool resolves every Candidate and execution Resource URI, rejects
root overlap and traversal, verifies the complete portable inventory, runtime
Python dependency closure, its own Hash-bound atomicity contract, and the
profile-aware receiver-Authority disposition through the standalone self-check
before its first write to the execution root. It leaves the Candidate byte-for-byte unchanged
and writes the machine-local binding receipt only under the selected execution
root. A failed preflight leaves a fresh execution root absent. The receipt is
deliberately excluded from Git and from this Candidate.

The default command requires an absent execution root. Reusing an existing root
fails closed. An explicit `--allow-idempotent-reentry` is accepted only when the
existing binding receipt is byte-semantically identical to the newly computed
receipt; the Binder never overwrites an existing receipt during re-entry.

The Binder preserves the receiver's raw Execution Root identity until it has
checked the final path component with no-follow `lstat`; both dangling symlinks
and symlinks to existing targets are rejected. It pins the opened parent
directory identity through preflight and publishes through that descriptor.
Fresh-root publication uses `renameatx_np(RENAME_EXCL)` on macOS or
`renameat2(RENAME_NOREPLACE)` on Linux, so a Root that appears concurrently is
never replaced. A platform without a verified atomic no-replace primitive fails
closed instead of falling back to `os.replace`. Exact idempotent re-entry also
opens the Root, receipt directory, and receipt file with no-follow semantics.

### Offline self-check

Run `python3 tools/self_check.py` from the Candidate root.{epoch24_self_check_note} The check requires
Python 3.11+ and the declared `cryptography>=45,<49` package, but no network at
check time. It verifies the portable file manifest, independently recomputes
every engineering DAG success-output
containment relationship, verifies the Human Review closure receipt, rejects
machine-local paths and symlinks, and can run after the Candidate is copied or
cloned to another directory.

### Receiver Source Authority bootstrap (external-certification profiles only)

Under `SELF_USE_LOCAL_TRUSTED_OPERATOR`, when external certification is false
and optional security hardening is not run, this bootstrap is not applicable
to core runtime binding. Enabling an external-certification profile or claim
restores the fail-closed requirements below. This is a one-time receiver
control-plane configuration, not a per-Candidate manual approval:

1. Provision an Ed25519 Trust Anchor outside the Candidate and store its exact
   file SHA-256 in the receiver launcher, CI protected variable, or equivalent
   trusted configuration channel.
2. Have the receiver's source-registry and release-history authority issue and sign
   `SOURCE_AUTHORITY_POLICY_LOCK.json`. Its signed body must bind the issuer ID,
   key ID, Program ID, Requirement Epoch, issuance Event ID/revision/Hash, and
   source-registry revision/tip Hash as well as every semantic source field. It
   must also bind the canonical Release History entries and history-tip Hash;
   Candidate closure declarations and their recomputed Hashes do not establish
   historical authority. For Requirement Epoch 30 and later, the same signed
   body also binds the exact byte Hashes of
   `validation/START_PACKAGE_VALIDATION_REPORT.json` and its non-circular
   detached `validation/START_PACKAGE_VALIDATION_REPORT_RECEIPT.json`.
3. The trusted launcher supplies `HF_SOURCE_AUTHORITY_POLICY_LOCK`,
   `HF_SOURCE_AUTHORITY_TRUST_ANCHOR`, and
   `HF_SOURCE_AUTHORITY_TRUST_ANCHOR_SHA256`. The first two values are local
   receiver paths; the third is the separately pinned file Hash. None is saved
   in the Candidate.
4. Run the self-check. Missing bindings, Candidate-local files, anchor Hash
   mismatch, issuer/event mismatch, bad signature, stale registry or release
   history tip, deleted or changed validation reports/receipts, unknown fields,
   or semantic disagreement all fail closed. Recomputing Candidate-local
   manifests and receipt Hashes cannot replace the receiver-signed binding.

Copying Candidate metadata to an external path does not create authority. A
receiver that lets an untrusted Candidate choose all three environment values
has bypassed its own trust boundary. Key rotation updates the receiver Trust
Anchor and pinned Hash through the receiver's normal secure configuration
process; it does not require editing this portable Candidate.
{control_kernel_section}

No plugin, MCP server, sibling repository, credential, or machine-local tool
may be assumed when it is not declared above. Empty declarations mean that no
such dependency is currently required, not that an implicit local dependency
is allowed.
""",
    )
    _write_portable_self_check(staging)
    _write_runtime_binding_support(staging)
    _write_toolchain_manifest(staging, release_requirements)


def _file_json_hash(path: Path) -> str:
    return _json_hash(json.loads(path.read_text(encoding="utf-8")))


def _repair_portable_project_bindings(staging: Path) -> None:
    """Rebind derived project hashes after local paths become logical roots."""

    for _project_id, directory in PROJECTS:
        output = staging / "project_start_packages" / directory
        manifest_path = output / "COMMAND_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for command in manifest.get("commands", []):
            if isinstance(command, dict):
                command["command_sha256"] = _hash_without_field(
                    command, "command_sha256"
                )
        manifest["manifest_sha256"] = _hash_without_field(
            manifest, "manifest_sha256"
        )
        _write_json(manifest_path, manifest)
        commands_by_id = {
            str(item["command_id"]): item
            for item in manifest.get("commands", [])
            if isinstance(item, dict) and item.get("command_id")
        }
        manifest_sha256 = _file_hash(manifest_path)
        index_path = output / "WORKPACK_INDEX.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        for item in index.get("workpacks", []):
            if not isinstance(item, dict):
                continue
            command_path = output / str(item["command_manifest_ref"])
            capsule_path = output / str(item["capsule_ref"])
            result_path = output / str(item["result_ref"])
            workpack_path = output / str(item["workpack_ref"])
            loop_path = output / str(item["loop_state_ref"])

            commands = json.loads(command_path.read_text(encoding="utf-8"))
            commands["source_project_command_manifest_sha256"] = manifest_sha256
            required_artifact_refs = list(
                item.get("required_artifact_refs") or []
            )
            artifact_write_roots = list(
                dict.fromkeys(
                    artifact_ref.rsplit("/", 1)[0]
                    for artifact_ref in required_artifact_refs
                )
            )
            auxiliary_write_roots = (
                [CASE_EXECUTION_RESULT_ROOT_REF]
                if item.get("workpack_id")
                == CASE_EVIDENCE_WRITER_WORKPACK_ID
                else []
            )
            artifact_read_roots = [
                str(root)
                for scope in item.get("job_artifact_read_scopes", [])
                if isinstance(scope, Mapping)
                for root in scope.get("allowed_read_roots", [])
            ]
            commands["commands"] = (
                _bind_commands_to_workpack_artifact_roots(
                    commands_by_id,
                    [str(value) for value in item.get("command_ids", [])],
                    list(
                        dict.fromkeys(
                            [*artifact_write_roots, *auxiliary_write_roots]
                        )
                    ),
                    artifact_read_roots,
                    workpack_id=str(item.get("workpack_id") or ""),
                    workpack_read_roots=item.get("allowed_read_paths", []),
                )
            )
            if required_artifact_refs:
                commands["workpack_artifact_write_roots"] = (
                    artifact_write_roots
                )
            commands["workpack_auxiliary_write_roots"] = (
                auxiliary_write_roots
            )
            commands["manifest_sha256"] = _hash_without_field(
                commands, "manifest_sha256"
            )
            _write_json(command_path, commands)

            capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
            capsule["command_manifest_sha256"] = _file_hash(command_path)
            _write_json(capsule_path, capsule)

            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["command_manifest_sha256"] = _file_hash(command_path)
            result["capsule_sha256"] = _file_hash(capsule_path)
            _write_json(result_path, result)

            item["workpack_sha256"] = _file_hash(workpack_path)
            item["command_manifest_sha256"] = _file_hash(command_path)
            item["capsule_sha256"] = _file_hash(capsule_path)
            item["result_sha256"] = _file_hash(result_path)
            item["loop_state_sha256"] = _file_hash(loop_path)
        _write_json(index_path, index)


def _repair_semantic_production_bindings(staging: Path) -> None:
    """Rebuild derived semantic hashes after portable projection or repair."""

    frozen_path = staging / "canonical_sources/FROZEN_REQUIREMENT_IR.json"
    provenance_path = staging / "FACTORY_PROVENANCE.json"
    catalog_path = staging / "canonical_sources/NORMATIVE_ATOM_CATALOG.json"
    coverage_path = staging / "canonical_sources/ATOM_COVERAGE_MATRIX.json"
    if not all(
        path.is_file()
        for path in (frozen_path, provenance_path, catalog_path, coverage_path)
    ):
        return
    frozen_ir = json.loads(frozen_path.read_text(encoding="utf-8"))
    if not explicit_production_enabled(frozen_ir):
        return
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    manifest = build_artifact_obligation_manifest(
        frozen_ir,
        target_id=str(frozen_ir.get("target", {}).get("id")),
        program_id=str(frozen_ir.get("program_id")),
        requirement_ir_sha256=str(provenance.get("requirement_ir_sha256")),
        atom_catalog_sha256=_file_hash(catalog_path),
        coverage_matrix_sha256=_file_hash(coverage_path),
    )
    if manifest is None:
        return
    _write_json(
        staging / "canonical_sources/ARTIFACT_OBLIGATION_MANIFEST.json",
        manifest,
    )

    for project_id, directory in PROJECTS:
        output = staging / "project_start_packages" / directory
        index_path = output / "WORKPACK_INDEX.json"
        if not index_path.is_file():
            continue
        index = json.loads(index_path.read_text(encoding="utf-8"))
        for workpack in index.get("workpacks", []):
            if not isinstance(workpack, dict) or not workpack.get("workpack_id"):
                continue
            workpack_id = str(workpack["workpack_id"])
            bundle = task_bundle_for_workpack(
                manifest,
                workpack_id=workpack_id,
                project_id=project_id,
                program_id=str(frozen_ir.get("program_id")),
                target_id=str(frozen_ir.get("target", {}).get("id")),
                structural_contract=PROJECT_WORKPACK_CONTRACTS.get(workpack_id),
            )
            if bundle is None:
                continue
            bundle_ref = f"task_bundles/{workpack_id}.task_bundle.json"
            bundle_path = output / bundle_ref
            _write_json(bundle_path, bundle)
            bundle_hash = _file_hash(bundle_path)
            required_ids = list(bundle["required_artifact_ids"])
            required_refs = list(bundle["required_artifact_refs"])
            acceptance_write_roots = list(dict.fromkeys(
                ref.rsplit("/", 1)[0] for ref in _acceptance_artifact_refs(bundle)
            ))
            artifact_write_roots = list(
                dict.fromkeys(
                    artifact_ref.rsplit("/", 1)[0]
                    for artifact_ref in required_refs
                )
            )
            auxiliary_write_roots = (
                [CASE_EXECUTION_RESULT_ROOT_REF]
                if workpack_id == CASE_EVIDENCE_WRITER_WORKPACK_ID
                else []
            )
            command_write_roots = list(
                dict.fromkeys(
                    [*artifact_write_roots, *auxiliary_write_roots]
                )
            )
            artifact_read_roots = _artifact_dependency_read_refs(
                manifest, required_ids
            )
            shared_artifact_read_roots = [
                root for root in artifact_read_roots if "/jobs/" not in root
            ]
            job_artifact_read_scopes = _job_artifact_scopes(
                artifact_read_roots, roots_field="allowed_read_roots"
            )
            contract_ids = list(bundle["production_contract_ids"])
            common_binding = {
                "semantic_hydration_complete": True,
                "task_bundle_ref": bundle_ref,
                "task_bundle_sha256": bundle_hash,
                "artifact_obligation_manifest_ref": ARTIFACT_MANIFEST_REF,
                "artifact_obligation_manifest_sha256": manifest["manifest_sha256"],
                "production_contract_ids": contract_ids,
            }

            command_path = output / str(workpack["command_manifest_ref"])
            commands = json.loads(command_path.read_text(encoding="utf-8"))
            commands.update(
                {
                    "semantic_task_bundle_ref": bundle_ref,
                    "semantic_task_bundle_sha256": bundle_hash,
                    "artifact_obligation_manifest_ref": ARTIFACT_MANIFEST_REF,
                    "artifact_obligation_manifest_sha256": manifest[
                        "manifest_sha256"
                    ],
                    "required_artifact_ids": required_ids,
                    "required_artifact_refs": required_refs,
                    "workpack_artifact_write_roots": artifact_write_roots,
                    "workpack_acceptance_write_roots": acceptance_write_roots,
                    "workpack_auxiliary_write_roots": auxiliary_write_roots,
                    "workpack_artifact_read_roots": artifact_read_roots,
                    "workpack_shared_artifact_read_roots": (
                        shared_artifact_read_roots
                    ),
                }
            )
            existing_commands = [
                command
                for command in commands.get("commands", [])
                if isinstance(command, Mapping) and command.get("command_id")
            ]
            commands["commands"] = _bind_commands_to_workpack_artifact_roots(
                {
                    str(command["command_id"]): command
                    for command in existing_commands
                },
                [str(command["command_id"]) for command in existing_commands],
                command_write_roots,
                artifact_read_roots,
                workpack_id=workpack_id,
                workpack_read_roots=workpack.get("allowed_read_paths", []),
                acceptance_write_roots=acceptance_write_roots,
            )
            commands["manifest_sha256"] = _hash_without_field(
                commands, "manifest_sha256"
            )
            _write_json(command_path, commands)
            command_hash = _file_hash(command_path)

            capsule_path = output / str(workpack["capsule_ref"])
            capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
            capsule.update(common_binding)
            capsule.update(
                {
                    "command_manifest_sha256": command_hash,
                    "required_artifact_ids": required_ids,
                    "required_artifact_refs": required_refs,
                    "job_artifact_read_scopes": job_artifact_read_scopes,
                    "allowed_read_paths": list(
                        dict.fromkeys(
                            [LOGICAL_CANDIDATE_ROOT,
                             f"{LOGICAL_EXECUTION_ROOT}/project_start_packages/{directory}/repository",
                             *shared_artifact_read_roots]
                        )
                    ),
                    "case_result_write_root": (
                        auxiliary_write_roots[0]
                        if auxiliary_write_roots
                        else None
                    ),
                }
            )
            _write_json(capsule_path, capsule)
            capsule_hash = _file_hash(capsule_path)

            result_path = output / str(workpack["result_ref"])
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result.update(common_binding)
            result.update(
                {
                    "command_manifest_sha256": command_hash,
                    "capsule_sha256": capsule_hash,
                    "expected_artifact_ids": required_ids,
                    "expected_artifact_refs": required_refs,
                }
            )
            _write_json(result_path, result)

            workpack.update(common_binding)
            workpack.update(
                {
                    "semantic_contract_status": "FROZEN",
                    "success_rule": bundle["completion_rule"],
                    "required_artifact_ids": required_ids,
                    "required_artifact_refs": required_refs,
                    "job_artifact_read_scopes": job_artifact_read_scopes,
                    "allowed_read_paths": list(
                        dict.fromkeys(
                            [LOGICAL_CANDIDATE_ROOT,
                             f"{LOGICAL_EXECUTION_ROOT}/project_start_packages/{directory}/repository",
                             *shared_artifact_read_roots]
                        )
                    ),
                    "workpack_sha256": _file_hash(
                        output / str(workpack["workpack_ref"])
                    ),
                    "command_manifest_sha256": command_hash,
                    "capsule_sha256": capsule_hash,
                    "result_sha256": _file_hash(result_path),
                    "loop_state_sha256": _file_hash(
                        output / str(workpack["loop_state_ref"])
                    ),
                }
            )
        _write_json(index_path, index)


def _dependency_label(item: Any) -> str:
    if not isinstance(item, Mapping):
        return str(item)
    identity = str(
        item.get("tool_id")
        or item.get("plugin_id")
        or item.get("server_id")
        or item.get("id")
        or "unnamed"
    )
    version = str(item.get("version_constraint") or "version not applicable")
    purpose = str(item.get("purpose") or "declared dependency")
    return f"{identity} ({version}; {purpose})"


def _command_dependency_provider(executable: str) -> str:
    if executable.endswith("/codex"):
        return "codex-cli"
    if executable.endswith("/program-driver"):
        return "program-driver"
    if executable.endswith("/linkage-review"):
        return "linkage-review-cli"
    if executable.endswith("/python") or executable.endswith("/python3"):
        return "python"
    return "UNDECLARED"


def _python_module_provider(module: str) -> str:
    return {
        "unittest": "python",
        "pytest": "pytest",
        "build": "build",
        "linkage_review": "linkage-review-module",
        "external_lab": "external-lab-module",
    }.get(module, "UNDECLARED")


def _collect_command_dependencies(staging: Path) -> list[dict[str, str]]:
    dependencies: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for path in sorted(staging.rglob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(document, dict) or not isinstance(
            document.get("commands"), list
        ):
            continue
        relative = path.relative_to(staging).as_posix()
        for index, command in enumerate(document["commands"]):
            if not isinstance(command, dict):
                continue
            executable = command.get("executable_abs") or command.get("executable")
            if not isinstance(executable, str) or not executable:
                continue
            command_id = str(command.get("command_id") or f"INDEX-{index}")
            items = [
                (
                    "EXECUTABLE",
                    executable,
                    _command_dependency_provider(executable),
                )
            ]
            argv = command.get("argv")
            if (
                isinstance(argv, list)
                and len(argv) >= 3
                and argv[1] == "-m"
                and isinstance(argv[2], str)
            ):
                items.append(
                    (
                        "PYTHON_MODULE",
                        argv[2],
                        _python_module_provider(argv[2]),
                    )
                )
            for dependency_kind, dependency_ref, provider_tool_id in items:
                key = (relative, command_id, dependency_kind, dependency_ref)
                if key in seen:
                    continue
                seen.add(key)
                dependencies.append(
                    {
                        "command_file_ref": f"{LOGICAL_CANDIDATE_ROOT}/{relative}",
                        "command_id": command_id,
                        "dependency_kind": dependency_kind,
                        "dependency_ref": dependency_ref,
                        "provider_tool_id": provider_tool_id,
                    }
                )
    return dependencies


def _write_toolchain_manifest(
    staging: Path, release_requirements: Mapping[str, Any]
) -> None:
    declared_tools = [
        dict(item)
        for item in release_requirements.get("required_tools", [])
        if isinstance(item, Mapping)
    ]
    declared_ids = {
        str(item.get("tool_id")) for item in declared_tools if item.get("tool_id")
    }
    dependencies = _collect_command_dependencies(staging)
    undeclared = sorted(
        {
            item["provider_tool_id"]
            for item in dependencies
            if item["provider_tool_id"] not in declared_ids
        }
    )
    _write_json(
        staging / "validation/TOOLCHAIN_MANIFEST.json",
        {
            "schema_version": "1.0",
            "declaration_policy": "EVERY_PLANNED_COMMAND_DEPENDENCY_MUST_HAVE_ONE_DECLARED_PROVIDER",
            "required_tools": declared_tools,
            "required_plugins": list(
                release_requirements.get("required_plugins", [])
            ),
            "required_mcp_servers": list(
                release_requirements.get("required_mcp_servers", [])
            ),
            "command_dependency_count": len(dependencies),
            "command_dependencies": dependencies,
            "undeclared_provider_ids": undeclared,
            "coverage_status": "PASS" if not undeclared else "FAIL",
        },
    )


def _write_runtime_binding_support(staging: Path) -> None:
    frozen_ir = json.loads(
        (staging / "canonical_sources/FROZEN_REQUIREMENT_IR.json").read_text(
            encoding="utf-8"
        )
    )
    target = frozen_ir.get("target")
    local_external_authority_not_applicable = bool(
        isinstance(target, Mapping)
        and _local_profile_external_authority_not_applicable(staging, target)
    )
    external_receiver_authority_required = bool(
        isinstance(target, Mapping)
        and _external_receiver_authority_required(staging, target)
    )
    setup_command = (
        "python3 tools/setup_runtime.py --execution-root "
        "../Harness_Foundry_execution"
    )
    setup_path = staging / "tools/setup_runtime.py"
    _write_text(
        setup_path,
        '''#!/usr/bin/env python3
"""Validate the portable Candidate, then atomically bind a local runtime."""

from __future__ import annotations

import argparse
import ast
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile


URI_RE = re.compile(r"harness-resource://(?:candidate|execution)(?:/[A-Za-z0-9._/-]+)?")
TEXT_SUFFIXES = {".json", ".jsonl", ".md", ".py", ".sh", ".toml", ".txt", ".yaml", ".yml"}


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lexical_absolute(path: Path) -> Path:
    """Make a receiver path absolute without following its final symlink."""

    expanded = path.expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded
    return Path(os.path.abspath(os.fspath(expanded)))


def identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def pin_parent(raw_parent: Path) -> tuple[Path, int, tuple[int, int]]:
    """Open the resolved parent and bind its identity through publication."""

    if os.name != "posix" or not hasattr(os, "O_DIRECTORY"):
        raise ValueError("safe parent identity binding is unsupported on this platform")
    try:
        resolved = raw_parent.resolve(strict=True)
        descriptor = os.open(resolved, os.O_RDONLY | os.O_DIRECTORY)
    except (FileNotFoundError, NotADirectoryError, OSError) as exc:
        raise ValueError(f"execution root parent must be an existing directory: {exc}") from exc
    try:
        pinned = os.fstat(descriptor)
        if not stat.S_ISDIR(pinned.st_mode):
            raise ValueError("execution root parent must be a directory")
        validate_parent_identity(raw_parent, resolved, descriptor, identity(pinned))
    except Exception:
        os.close(descriptor)
        raise
    return resolved, descriptor, identity(pinned)


def validate_parent_identity(
    raw_parent: Path,
    resolved_parent: Path,
    descriptor: int,
    expected_identity: tuple[int, int],
) -> None:
    try:
        current_resolved = raw_parent.resolve(strict=True)
        current_path = os.stat(raw_parent, follow_symlinks=True)
        current_descriptor = os.fstat(descriptor)
    except (FileNotFoundError, NotADirectoryError, OSError) as exc:
        raise ValueError(f"execution root parent identity is unavailable: {exc}") from exc
    if (
        current_resolved != resolved_parent
        or identity(current_path) != expected_identity
        or identity(current_descriptor) != expected_identity
    ):
        raise ValueError("execution root parent identity changed during binding")


def lstat_at(parent_descriptor: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None


def atomic_publish_noreplace(
    staging: Path,
    execution: Path,
    parent_descriptor: int,
    raw_parent: Path,
    resolved_parent: Path,
    parent_identity: tuple[int, int],
) -> None:
    """Publish one prepared directory without ever replacing a destination."""

    validate_parent_identity(
        raw_parent,
        resolved_parent,
        parent_descriptor,
        parent_identity,
    )
    if lstat_at(parent_descriptor, execution.name) is not None:
        raise ValueError("execution root appeared during atomic binding")
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename = getattr(library, "renameatx_np", None)
        flag = 0x00000004  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        rename = getattr(library, "renameat2", None)
        flag = 0x00000001  # RENAME_NOREPLACE
    else:
        rename = None
        flag = 0
    if rename is None:
        raise ValueError("atomic no-replace directory publication is unsupported")
    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int
    result = rename(
        parent_descriptor,
        os.fsencode(staging.name),
        parent_descriptor,
        os.fsencode(execution.name),
        flag,
    )
    if result == 0:
        return
    error = ctypes.get_errno()
    if error in {errno.EEXIST, errno.ENOTEMPTY}:
        raise ValueError("execution root appeared during atomic binding")
    unsupported = {
        errno.ENOSYS,
        errno.EINVAL,
        getattr(errno, "ENOTSUP", errno.EINVAL),
        getattr(errno, "EOPNOTSUPP", errno.EINVAL),
    }
    if error in unsupported:
        raise ValueError("atomic no-replace directory publication is unsupported")
    raise OSError(error, os.strerror(error), os.fspath(execution))


def read_existing_receipt(
    parent_descriptor: int,
    execution_name: str,
    expected_root_identity: tuple[int, int],
) -> dict:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        raise ValueError("safe no-follow receipt reading is unsupported")
    root_descriptor = receipt_descriptor = file_descriptor = None
    try:
        root_descriptor = os.open(
            execution_name,
            os.O_RDONLY | os.O_DIRECTORY | nofollow,
            dir_fd=parent_descriptor,
        )
        if identity(os.fstat(root_descriptor)) != expected_root_identity:
            raise ValueError("existing execution root identity changed during binding")
        receipt_descriptor = os.open(
            ".harness-foundry",
            os.O_RDONLY | os.O_DIRECTORY | nofollow,
            dir_fd=root_descriptor,
        )
        file_descriptor = os.open(
            "runtime_binding.json",
            os.O_RDONLY | nofollow,
            dir_fd=receipt_descriptor,
        )
        if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            raise ValueError("existing binding receipt must be a regular file")
        with os.fdopen(file_descriptor, "r", encoding="utf-8") as stream:
            file_descriptor = None
            value = json.load(stream)
    except (FileNotFoundError, NotADirectoryError, OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"existing execution root lacks an exact binding receipt: {exc}") from exc
    finally:
        for descriptor in (file_descriptor, receipt_descriptor, root_descriptor):
            if descriptor is not None:
                os.close(descriptor)
    if not isinstance(value, dict):
        raise ValueError("existing binding receipt must be a JSON object")
    return value


def contained(base: Path, suffix: str) -> Path:
    if any(part in {"", ".", ".."} for part in Path(suffix).parts):
        raise ValueError(f"unsafe Resource URI suffix: {suffix}")
    resolved = (base / suffix).resolve()
    if not resolved.is_relative_to(base):
        raise ValueError(f"Resource URI escaped its declared root: {suffix}")
    return resolved


def discover_uris(candidate: Path) -> list[str]:
    uris: set[str] = set()
    for path in sorted(candidate.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlink is forbidden: {path.relative_to(candidate)}")
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        uris.update(URI_RE.findall(text))
    return sorted(uris)


def portable_inventory(candidate: Path) -> set[str]:
    manifest_path = candidate / "validation/PORTABLE_FILE_MANIFEST.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"portable file manifest is unreadable: {exc}") from exc
    files = manifest.get("files")
    excluded = manifest.get("excluded_files")
    if not isinstance(files, dict) or not isinstance(excluded, list):
        raise ValueError("portable file manifest inventory is invalid")
    excluded_set = set(excluded)
    actual = {
        path.relative_to(candidate).as_posix(): path
        for path in candidate.rglob("*")
        if path.is_file()
        and path.relative_to(candidate).as_posix() not in excluded_set
    }
    if set(files) != set(actual):
        raise ValueError("portable file manifest does not cover Candidate bytes")
    for relative, expected_hash in files.items():
        if file_hash(actual[relative]) != expected_hash:
            raise ValueError(f"portable file manifest hash mismatch: {relative}")
    return set(files) | excluded_set


def validate_runtime_dependency_closure(candidate: Path, inventory: set[str]) -> None:
    runtime_root = candidate / "tools/harness_foundry_runtime"
    for source in sorted(runtime_root.glob("*.py")):
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, SyntaxError) as exc:
            raise ValueError(f"portable runtime module is invalid: {source.name}: {exc}") from exc
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level != 1:
                continue
            dependencies = (
                [node.module.split(".", 1)[0]]
                if node.module
                else [alias.name.split(".", 1)[0] for alias in node.names]
            )
            for dependency in dependencies:
                module = runtime_root / f"{dependency}.py"
                package = runtime_root / dependency / "__init__.py"
                target = module if module.is_file() else package
                if not target.is_file():
                    raise ValueError(
                        f"portable runtime dependency is missing: {source.name}: .{dependency}"
                    )
                relative = target.relative_to(candidate).as_posix()
                if relative not in inventory:
                    raise ValueError(
                        f"portable runtime dependency is outside inventory: {relative}"
                    )


def local_profile_external_authority_not_applicable(candidate: Path) -> bool:
    try:
        frozen_ir = json.loads(
            (candidate / "canonical_sources/FROZEN_REQUIREMENT_IR.json").read_text(
                encoding="utf-8"
            )
        )
        profile = json.loads(
            (candidate / "EPOCH38_GENERATION_PROFILE.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    target = frozen_ir.get("target") if isinstance(frozen_ir, dict) else None
    correction = (
        target.get("v2_9_charter_architecture_correction_epoch38")
        if isinstance(target, dict)
        else None
    )
    threat_model = (
        correction.get("threat_model")
        if isinstance(correction, dict)
        else None
    )
    return bool(
        isinstance(target, dict)
        and target.get("architecture_epoch") == 4
        and target.get("control_plane_epoch") == 4
        and target.get("assurance_profile_id")
        == "SELF_USE_LOCAL_TRUSTED_OPERATOR"
        and target.get("operating_assurance_profile")
        == "SELF_USE_LOCAL_TRUSTED_OPERATOR"
        and isinstance(threat_model, dict)
        and threat_model.get("external_trust_anchor") == "NOT_APPLICABLE"
        and threat_model.get("external_certification_offered") is False
        and isinstance(profile, dict)
        and profile.get("profile_kind")
        == "SELF_USE_LOCAL_CORE_CANDIDATE_ROUTE"
        and profile.get("assurance_profile")
        == "SELF_USE_LOCAL_TRUSTED_OPERATOR"
        and profile.get("external_certification_claimed") is False
        and profile.get("optional_security_hardening")
        in {"NOT_APPLICABLE", "NOT_RUN"}
        and profile.get("external_trust_anchor") == "NOT_APPLICABLE"
    )


def external_receiver_authority_required(candidate: Path) -> bool:
    if local_profile_external_authority_not_applicable(candidate):
        return False
    try:
        frozen_ir = json.loads(
            (candidate / "canonical_sources/FROZEN_REQUIREMENT_IR.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        frozen_ir = {}
    try:
        profile = json.loads(
            (candidate / "EPOCH38_GENERATION_PROFILE.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        profile = None
    target = frozen_ir.get("target") if isinstance(frozen_ir, dict) else None
    declared_profile = (
        target.get("operating_assurance_profile")
        or target.get("assurance_profile_id")
        if isinstance(target, dict)
        else None
    )
    epoch4_active = bool(
        isinstance(target, dict)
        and target.get("architecture_epoch") == 4
        and target.get("control_plane_epoch") == 4
    )
    return bool(
        isinstance(target, dict)
        and (
            isinstance(target.get("v0_24_human_review_remediation"), dict)
            or (
                epoch4_active
                and (
                    isinstance(declared_profile, str)
                    or (
                        isinstance(profile, dict)
                        and (
                            profile.get("external_certification_claimed") is not False
                            or profile.get("optional_security_hardening")
                            not in {"NOT_APPLICABLE", "NOT_RUN"}
                            or profile.get("external_trust_anchor")
                            != "NOT_APPLICABLE"
                        )
                    )
                )
            )
        )
    )


def external_receiver_authority_disposition(candidate: Path) -> str:
    if local_profile_external_authority_not_applicable(candidate):
        return "NOT_APPLICABLE_SELF_USE_LOCAL_TRUSTED_OPERATOR"
    if external_receiver_authority_required(candidate):
        return "REQUIRED_FOR_EXTERNAL_CERTIFICATION"
    return "NOT_APPLICABLE_NO_EXTERNAL_CERTIFICATION_PROFILE"


def validate_binding_contract(candidate: Path) -> None:
    contract_path = candidate / "validation/RUNTIME_BINDING_CONTRACT.json"
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"runtime binding contract is unreadable: {exc}") from exc
    required_true = (
        "validation_before_first_execution_root_write",
        "portable_manifest_preflight_required",
        "candidate_uri_preflight_required",
        "runtime_dependency_closure_required",
        "receiver_authority_preflight_required",
        "fresh_root_same_parent_staging_required",
        "fresh_root_atomic_publish_required",
        "failure_cleanup_keeps_fresh_root_absent",
        "existing_root_fail_closed_by_default",
        "idempotent_reentry_requires_explicit_flag",
        "idempotent_reentry_requires_exact_receipt",
        "receiver_raw_execution_path_identity_required",
        "final_component_lstat_before_resolution_required",
        "parent_directory_identity_pinned_through_publish",
        "fresh_root_atomic_noreplace_required",
        "existing_receipt_nofollow_read_required",
    )
    local_authority_na = local_profile_external_authority_not_applicable(
        candidate
    )
    if (
        contract.get("setup_ref")
        != "harness-resource://candidate/tools/setup_runtime.py"
        or contract.get("setup_sha256") != file_hash(Path(__file__).resolve())
        or any(contract.get(field) is not True for field in required_true)
        or contract.get("candidate_write_policy") != "FORBIDDEN"
        or contract.get("existing_binding_overwrite_allowed") is not False
        or contract.get("receiver_authority_preflight_mode") != "PROFILE_AWARE"
        or contract.get("external_receiver_authority_required")
        != external_receiver_authority_required(candidate)
        or contract.get("external_receiver_authority_disposition")
        != external_receiver_authority_disposition(candidate)
    ):
        raise ValueError("runtime binding contract or setup_runtime.py Hash is invalid")


def validate_receiver_authority(candidate: Path) -> None:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "tools/self_check.py"],
        cwd=candidate,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("standalone authority/integrity preflight returned invalid JSON") from exc
    if completed.returncode != 0 or report.get("status") != "PASS":
        codes = sorted(
            str(item.get("code"))
            for item in report.get("findings", [])
            if isinstance(item, dict) and item.get("code")
        )
        raise ValueError(
            "standalone authority/integrity preflight failed: " + ",".join(codes)
        )


def write_receipt(root: Path, receipt: dict) -> None:
    receipt_dir = root / ".harness-foundry"
    if receipt_dir.exists() and receipt_dir.is_symlink():
        raise ValueError("runtime receipt directory must not be a symlink")
    receipt_dir.mkdir(parents=True, exist_ok=True)
    temporary = receipt_dir / f"runtime_binding.json.tmp-{os.getpid()}"
    temporary.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\\n",
        encoding="utf-8",
    )
    os.replace(temporary, receipt_dir / "runtime_binding.json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execution-root", required=True)
    parser.add_argument("--allow-idempotent-reentry", action="store_true")
    args = parser.parse_args()
    candidate = Path(__file__).resolve().parents[1]
    raw_execution = lexical_absolute(Path(args.execution_root))
    parent_descriptor = None
    try:
        if not raw_execution.name:
            raise ValueError("execution root must name a directory below an existing parent")
        resolved_parent, parent_descriptor, parent_identity = pin_parent(raw_execution.parent)
        execution = resolved_parent / raw_execution.name
        if candidate == execution or candidate.is_relative_to(execution) or execution.is_relative_to(candidate):
            raise ValueError("Candidate and execution roots must not overlap")
        initial_root = lstat_at(parent_descriptor, execution.name)
        if initial_root is not None and stat.S_ISLNK(initial_root.st_mode):
            raise ValueError("execution root must not be a symlink")
        if initial_root is not None and not stat.S_ISDIR(initial_root.st_mode):
            raise ValueError("execution root must be a directory")
        if initial_root is not None and not args.allow_idempotent_reentry:
            raise ValueError(
                "execution root already exists; use a fresh root or explicit exact idempotent re-entry"
            )
        inventory = portable_inventory(candidate)
        bindings = []
        for uri in discover_uris(candidate):
            if uri == "harness-resource://candidate":
                resolved = candidate
                must_exist = True
            elif uri.startswith("harness-resource://candidate/"):
                resolved = contained(candidate, uri.removeprefix("harness-resource://candidate/"))
                must_exist = True
            elif uri == "harness-resource://execution":
                resolved = execution
                must_exist = False
            else:
                resolved = contained(execution, uri.removeprefix("harness-resource://execution/"))
                must_exist = False
            if must_exist and not resolved.exists():
                raise ValueError(f"Candidate Resource URI is dangling: {uri}")
            if must_exist and uri != "harness-resource://candidate":
                relative = resolved.relative_to(candidate).as_posix()
                if not resolved.is_file():
                    raise ValueError(f"Candidate Resource URI is not a physical file: {uri}")
                if relative not in inventory:
                    raise ValueError(f"Candidate Resource URI is outside portable inventory: {uri}")
            bindings.append(
                {
                    "uri": uri,
                    "resolved_path": str(resolved),
                    "status": "BOUND_EXISTING" if must_exist else "BOUND_PLANNED",
                }
            )
        validate_runtime_dependency_closure(candidate, inventory)
        validate_binding_contract(candidate)
        validate_receiver_authority(candidate)
        binding_hash = hashlib.sha256(
            json.dumps(bindings, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        receipt = {
            "schema_version": "1.0",
            "binding_mode": "LOCAL_ONLY_NON_EXPORTABLE",
            "candidate_root": str(candidate),
            "execution_root": str(execution),
            "candidate_manifest_sha256": file_hash(candidate / "validation/PORTABLE_FILE_MANIFEST.json"),
            "binding_count": len(bindings),
            "bindings_sha256": binding_hash,
            "bindings": bindings,
            "candidate_write_performed": False,
        }
        reused_existing_binding = False
        validate_parent_identity(
            raw_execution.parent,
            resolved_parent,
            parent_descriptor,
            parent_identity,
        )
        current_root = lstat_at(parent_descriptor, execution.name)
        if initial_root is not None:
            if (
                current_root is None
                or stat.S_ISLNK(current_root.st_mode)
                or not stat.S_ISDIR(current_root.st_mode)
                or identity(current_root) != identity(initial_root)
            ):
                raise ValueError("existing execution root identity changed during binding")
            existing_receipt = read_existing_receipt(
                parent_descriptor,
                execution.name,
                identity(initial_root),
            )
            if existing_receipt != receipt:
                raise ValueError("existing execution root binding does not exactly match")
            reused_existing_binding = True
        else:
            staging_root = Path(
                tempfile.mkdtemp(
                    prefix=f".{execution.name}.runtime-binding-",
                    dir=resolved_parent,
                )
            )
            try:
                write_receipt(staging_root, receipt)
                atomic_publish_noreplace(
                    staging_root,
                    execution,
                    parent_descriptor,
                    raw_execution.parent,
                    resolved_parent,
                    parent_identity,
                )
                staging_root = None
            finally:
                if staging_root is not None:
                    shutil.rmtree(staging_root, ignore_errors=True)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1
    finally:
        if parent_descriptor is not None:
            os.close(parent_descriptor)
    print(json.dumps({"status": "PASS", "binding_count": len(bindings), "receipt": "harness-resource://execution/.harness-foundry/runtime_binding.json", "reused_existing_binding": reused_existing_binding}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
''',
    )
    setup_sha256 = _file_hash(setup_path)
    contract = {
        "schema_version": "1.3",
        "binding_mode": "LOCAL_ONLY_NON_EXPORTABLE",
        "setup_command": setup_command,
        "setup_ref": "harness-resource://candidate/tools/setup_runtime.py",
        "setup_sha256": setup_sha256,
        "candidate_root_source": "SETUP_SCRIPT_LOCATION",
        "execution_root_source": "RECEIVER_ARGUMENT",
        "binding_receipt_ref": (
            "harness-resource://execution/.harness-foundry/runtime_binding.json"
        ),
        "candidate_write_policy": "FORBIDDEN",
        "root_overlap_policy": "REJECT",
        "candidate_reference_policy": "MUST_EXIST_AND_BE_CONTAINED",
        "execution_reference_policy": "MAY_BE_PLANNED_BUT_MUST_BE_CONTAINED",
        "resolved_machine_paths_exported": False,
        "validation_before_first_execution_root_write": True,
        "portable_manifest_preflight_required": True,
        "candidate_uri_preflight_required": True,
        "runtime_dependency_closure_required": True,
        "receiver_authority_preflight_required": True,
        "receiver_authority_preflight_mode": "PROFILE_AWARE",
        "external_receiver_authority_required": (
            external_receiver_authority_required
        ),
        "external_receiver_authority_disposition": (
            _external_receiver_authority_disposition(staging, target)
        ),
        "fresh_root_same_parent_staging_required": True,
        "fresh_root_atomic_publish_required": True,
        "failure_cleanup_keeps_fresh_root_absent": True,
        "human_gate_consumption_before_binding_success_allowed": False,
        "existing_root_fail_closed_by_default": True,
        "idempotent_reentry_requires_explicit_flag": True,
        "idempotent_reentry_requires_exact_receipt": True,
        "existing_binding_overwrite_allowed": False,
        "receiver_raw_execution_path_identity_required": True,
        "final_component_lstat_before_resolution_required": True,
        "parent_directory_identity_pinned_through_publish": True,
        "fresh_root_atomic_noreplace_required": True,
        "existing_receipt_nofollow_read_required": True,
        "unsupported_noreplace_platform_behavior": "FAIL_CLOSED",
    }
    _write_json(staging / "validation/RUNTIME_BINDING_CONTRACT.json", contract)
    portability_path = staging / "validation/PORTABILITY_MANIFEST.json"
    portability = json.loads(portability_path.read_text(encoding="utf-8"))
    portability["release_requirements"]["runtime_setup"].update(
        {
            "standard_library_only": False,
            "external_packages": ["cryptography>=45,<49"],
            "setup_ref": contract["setup_ref"],
            "setup_sha256": setup_sha256,
            "validation_before_first_execution_root_write": True,
            "portable_manifest_preflight_required": True,
            "candidate_uri_preflight_required": True,
            "runtime_dependency_closure_required": True,
            "receiver_authority_preflight_required": True,
            "receiver_authority_preflight_mode": "PROFILE_AWARE",
            "external_receiver_authority_required": (
            external_receiver_authority_required
            ),
            "external_receiver_authority_disposition": (
                _external_receiver_authority_disposition(staging, target)
            ),
            "fresh_root_atomic_publish_required": True,
            "failure_cleanup_keeps_fresh_root_absent": True,
            "existing_root_fail_closed_by_default": True,
            "idempotent_reentry_requires_explicit_flag": True,
            "idempotent_reentry_requires_exact_receipt": True,
            "existing_binding_overwrite_allowed": False,
            "receiver_raw_execution_path_identity_required": True,
            "final_component_lstat_before_resolution_required": True,
            "parent_directory_identity_pinned_through_publish": True,
            "fresh_root_atomic_noreplace_required": True,
            "existing_receipt_nofollow_read_required": True,
            "unsupported_noreplace_platform_behavior": "FAIL_CLOSED",
        }
    )
    _write_json(portability_path, portability)


def _write_portable_self_check(staging: Path) -> None:
    _write_text(
        staging / "tools/self_check.py",
        '''#!/usr/bin/env python3
"""Offline, standalone portability, integrity, and DAG containment check."""

from __future__ import annotations

import base64
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

sys.dont_write_bytecode = True


CANDIDATE_URI = "harness-resource://candidate"
EXECUTION_URI = "harness-resource://execution"
RESOURCE_URI_RE = re.compile(r"harness-resource://(?:candidate|execution)(?:/[A-Za-z0-9._/-]+)?")
TEXT_SUFFIXES = {".json", ".jsonl", ".md", ".py", ".sh", ".toml", ".txt", ".yaml", ".yml"}
LOCAL_PATH_RE = re.compile(
    r"(?:^|[\\s\\\"'=:(])(?:/(?:Users|home|private|tmp|Volumes)/[^/\\s]+|"
    r"/(?:opt|usr/local)/[^/\\s]+|[A-Za-z]:\\\\Users\\\\[^\\\\\\s]+)"
)
CLOSURE_DECLARATION_STATUS = (
    "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT"
)
AUTHORITY_NORMALIZATION = {
    "NORMATIVE_USER_SELECTED": "HUMAN_APPROVED",
    "HUMAN_PROVIDED_SUPPLEMENT": "HUMAN_PROVIDED",
    "HUMAN_AUTHORIZED_AUTHORING_PROPOSAL": "HUMAN_APPROVED",
    "HUMAN_VIA_CODEX_CHAT_REVIEW_EVIDENCE": "HUMAN_VIA_CODEX_CHAT",
}
CANONICAL_AUTHORITY_LEVELS = {
    "HUMAN_APPROVED",
    "HUMAN_PROVIDED",
    "HUMAN_VIA_CODEX_CHAT",
    "LOCKED_SPECIFICATION",
}


def local_profile_external_authority_disposition(
    root: Path,
    frozen_ir: Mapping[str, Any],
) -> tuple[bool, list[dict[str, str]]]:
    target = frozen_ir.get("target")
    local_profile_declared = bool(
        isinstance(target, Mapping)
        and target.get("architecture_epoch") == 4
        and target.get("control_plane_epoch") == 4
        and target.get("assurance_profile_id")
        == "SELF_USE_LOCAL_TRUSTED_OPERATOR"
        and target.get("operating_assurance_profile")
        == "SELF_USE_LOCAL_TRUSTED_OPERATOR"
    )
    if not local_profile_declared:
        return False, []
    try:
        profile = json.loads(
            (root / "EPOCH38_GENERATION_PROFILE.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return False, [{
            "code": "LOCAL_RUNTIME_AUTHORITY_PROFILE_INVALID",
            "message": str(exc),
        }]
    correction = target.get("v2_9_charter_architecture_correction_epoch38")
    threat_model = (
        correction.get("threat_model")
        if isinstance(correction, Mapping)
        else None
    )
    valid = bool(
        isinstance(threat_model, Mapping)
        and threat_model.get("external_trust_anchor") == "NOT_APPLICABLE"
        and threat_model.get("external_certification_offered") is False
        and isinstance(profile, Mapping)
        and profile.get("profile_kind")
        == "SELF_USE_LOCAL_CORE_CANDIDATE_ROUTE"
        and profile.get("assurance_profile")
        == "SELF_USE_LOCAL_TRUSTED_OPERATOR"
        and profile.get("external_certification_claimed") is False
        and profile.get("optional_security_hardening")
        in {"NOT_APPLICABLE", "NOT_RUN"}
        and profile.get("external_trust_anchor") == "NOT_APPLICABLE"
    )
    if not valid:
        return False, [{
            "code": "LOCAL_RUNTIME_AUTHORITY_PROFILE_INVALID",
            "message": (
                "local external-Authority N/A requires no external certification "
                "claim and optional security hardening not run"
            ),
        }]
    return True, []


def external_receiver_authority_required(
    root: Path,
    frozen_ir: Mapping[str, Any],
) -> bool:
    local_authority_na, _ = local_profile_external_authority_disposition(
        root, frozen_ir
    )
    if local_authority_na:
        return False
    target = frozen_ir.get("target")
    if not isinstance(target, Mapping):
        return False
    declared_profile = target.get("operating_assurance_profile") or target.get(
        "assurance_profile_id"
    )
    epoch4_active = bool(
        target.get("architecture_epoch") == 4
        and target.get("control_plane_epoch") == 4
    )
    try:
        profile = json.loads(
            (root / "EPOCH38_GENERATION_PROFILE.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        profile = None
    return bool(
        isinstance(target.get("v0_24_human_review_remediation"), Mapping)
        or (
            epoch4_active
            and (
                isinstance(declared_profile, str)
                or (
                    isinstance(profile, Mapping)
                    and (
                        profile.get("external_certification_claimed") is not False
                        or profile.get("optional_security_hardening")
                        not in {"NOT_APPLICABLE", "NOT_RUN"}
                        or profile.get("external_trust_anchor") != "NOT_APPLICABLE"
                    )
                )
            )
        )
    )


def _epoch34_runtime_binding_review_remediation_is_complete(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    existing_root = value.get("existing_execution_root_contract")
    execution = value.get("required_regression_execution_contract")
    implementation = value.get("implementation_evidence")
    required_tests = (
        "test_epoch33_review_remediation_routes_to_producer_and_both_oracles",
        "test_runtime_binder_rejects_missing_dependency_before_root_write",
        "test_runtime_binder_rejects_dangling_uri_without_creating_root",
        "test_runtime_binder_rejects_portable_inventory_gap_without_creating_root",
        "test_runtime_binder_rejects_existing_root_by_default_and_allows_exact_reentry",
        "test_standalone_requires_receiver_side_source_authority_policy",
    )
    return (
        value.get("status") == "REQUIRED_IN_REPLACEMENT_CANDIDATE"
        and value.get("active_epochs")
        == {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 34,
        }
        and value.get("closure_receipt_required") is True
        and value.get("closure_receipt_status") == CLOSURE_DECLARATION_STATUS
        and set(value.get("finding_ids") or ())
        == {
            "HR-V033-001-EXISTING-EXECUTION-ROOT-OVERWRITE",
            "HR-V033-002-REQUIRED-BINDER-REGRESSION-NOT-EXECUTED",
        }
        and tuple(value.get("required_regression_tests") or ()) == required_tests
        and isinstance(existing_root, Mapping)
        and existing_root.get("fail_closed_by_default") is True
        and existing_root.get("explicit_idempotent_reentry_allowed") is True
        and existing_root.get("exact_existing_receipt_required") is True
        and existing_root.get("receipt_overwrite_allowed") is False
        and isinstance(execution, Mapping)
        and execution.get("factory_validator_executes_exact_hash_bound_tests")
        is True
        and execution.get("candidate_publication_blocked_on_missing_test") is True
        and execution.get("candidate_publication_blocked_on_failed_test") is True
        and execution.get("closure_pass_requires_execution_receipt") is True
        and isinstance(implementation, Mapping)
        and implementation.get("regression_test_ref")
        == "tests/test_release_closure_candidate.py"
        and re.fullmatch(
            r"[0-9a-f]{64}",
            str(implementation.get("regression_test_sha256") or ""),
        )
        is not None
    )


def _epoch35_runtime_binding_path_atomicity_remediation_is_complete(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    required_tests = (
        "test_epoch33_review_remediation_routes_to_producer_and_both_oracles",
        "test_runtime_binder_rejects_missing_dependency_before_root_write",
        "test_runtime_binder_rejects_dangling_uri_without_creating_root",
        "test_runtime_binder_rejects_portable_inventory_gap_without_creating_root",
        "test_runtime_binder_rejects_existing_root_by_default_and_allows_exact_reentry",
        "test_standalone_requires_receiver_side_source_authority_policy",
        "test_epoch35_remediation_contract_is_accepted_by_both_oracles",
        "test_runtime_binder_rejects_dangling_execution_root_symlink",
        "test_runtime_binder_rejects_execution_root_symlink_to_existing_directory",
        "test_runtime_binder_atomic_noreplace_rejects_appeared_empty_root",
        "test_runtime_binder_rejects_parent_identity_swap",
        "test_runtime_binder_atomic_noreplace_rejects_target_symlink_swap",
    )
    raw_path = value.get("receiver_raw_path_identity_contract")
    parent = value.get("parent_directory_identity_contract")
    publication = value.get("atomic_noreplace_publication_contract")
    receipt = value.get("idempotent_reentry_nofollow_contract")
    execution = value.get("required_regression_execution_contract")
    implementation = value.get("implementation_evidence")
    return (
        value.get("status") == "REQUIRED_IN_REPLACEMENT_CANDIDATE"
        and value.get("active_epochs")
        == {"architecture_epoch": 2, "control_plane_epoch": 2, "requirement_epoch": 35}
        and value.get("closure_receipt_required") is True
        and value.get("closure_receipt_status") == CLOSURE_DECLARATION_STATUS
        and set(value.get("finding_ids") or ())
        == {
            "HR-V034-001-RUNTIME-BINDER-EXECUTION-ROOT-SYMLINK-BYPASS",
            "HR-V034-002-RUNTIME-BINDER-ATOMIC-PUBLISH-TOCTOU",
            "HR-V034-003-RUNTIME-BINDER-CLOSURE-OVERCLAIM",
        }
        and tuple(value.get("required_regression_tests") or ()) == required_tests
        and isinstance(raw_path, Mapping)
        and all(raw_path.get(field) is True for field in (
            "receiver_argument_preserved_before_resolution",
            "final_component_lstat_nofollow_required",
            "dangling_symlink_rejected",
            "existing_target_symlink_rejected",
        ))
        and isinstance(parent, Mapping)
        and all(parent.get(field) is True for field in (
            "opened_parent_directory_identity_pinned",
            "parent_identity_revalidated_before_publish",
            "publication_uses_pinned_parent_descriptor",
        ))
        and isinstance(publication, Mapping)
        and publication.get("destination_noreplace_required") is True
        and publication.get("macos_renameatx_np_rename_excl") is True
        and publication.get("linux_renameat2_rename_noreplace") is True
        and publication.get("unsafe_replace_fallback_allowed") is False
        and publication.get("unsupported_platform_behavior") == "FAIL_CLOSED"
        and isinstance(receipt, Mapping)
        and receipt.get("execution_root_identity_stable_for_reentry") is True
        and receipt.get("receipt_directory_nofollow") is True
        and receipt.get("receipt_file_nofollow") is True
        and receipt.get("receipt_overwrite_allowed") is False
        and isinstance(execution, Mapping)
        and execution.get("factory_validator_executes_exact_hash_bound_tests") is True
        and execution.get("candidate_publication_blocked_on_missing_test") is True
        and execution.get("candidate_publication_blocked_on_failed_test") is True
        and execution.get("closure_pass_requires_execution_receipt") is True
        and isinstance(implementation, Mapping)
        and implementation.get("compiler_ref") == "src/harness_foundry_factory/compiler.py"
        and implementation.get("factory_validator_ref") == "src/harness_foundry_factory/validator.py"
        and implementation.get("regression_test_ref") == "tests/test_release_closure_candidate.py"
        and all(re.fullmatch(r"[0-9a-f]{64}", str(implementation.get(field) or "")) is not None for field in (
            "compiler_sha256", "factory_validator_sha256", "regression_test_sha256"
        ))
    )


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_candidate_uri_closure(
    root: Path, inventory: set[str]
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for source in sorted(root.rglob("*")):
        if not source.is_file() or source.suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = source.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        for uri in RESOURCE_URI_RE.findall(text):
            if uri == CANDIDATE_URI:
                continue
            if not uri.startswith(f"{CANDIDATE_URI}/"):
                continue
            suffix = uri.removeprefix(f"{CANDIDATE_URI}/")
            parts = Path(suffix).parts
            target = (root / suffix).resolve()
            if (
                not suffix
                or any(part in {"", ".", ".."} for part in parts)
                or not target.is_relative_to(root.resolve())
                or not target.is_file()
                or target.is_symlink()
            ):
                finding = ("CANDIDATE_RESOURCE_URI_DANGLING", uri)
            elif target.relative_to(root).as_posix() not in inventory:
                finding = ("CANDIDATE_RESOURCE_URI_OUTSIDE_PORTABLE_INVENTORY", uri)
            else:
                continue
            if finding not in seen:
                seen.add(finding)
                findings.append({"code": finding[0], "message": finding[1]})
    return findings


def check_runtime_dependency_closure(
    root: Path, inventory: set[str]
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    runtime_root = root / "tools/harness_foundry_runtime"
    for source in sorted(runtime_root.glob("*.py")):
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, SyntaxError) as exc:
            findings.append({"code": "PORTABLE_RUNTIME_MODULE_INVALID", "message": f"{source.name}: {exc}"})
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level != 1:
                continue
            dependencies = (
                [node.module.split(".", 1)[0]]
                if node.module
                else [alias.name.split(".", 1)[0] for alias in node.names]
            )
            for dependency in dependencies:
                module = runtime_root / f"{dependency}.py"
                package = runtime_root / dependency / "__init__.py"
                target = module if module.is_file() else package
                if not target.is_file():
                    findings.append({"code": "PORTABLE_RUNTIME_DEPENDENCY_MISSING", "message": f"{source.name}: .{dependency}"})
                    continue
                relative = target.relative_to(root).as_posix()
                if relative not in inventory:
                    findings.append({"code": "PORTABLE_RUNTIME_DEPENDENCY_OUTSIDE_INVENTORY", "message": relative})
    return findings


def check_runtime_binding_contract(
    root: Path, portability: Mapping[str, Any]
) -> list[dict[str, str]]:
    contract_path = root / "validation/RUNTIME_BINDING_CONTRACT.json"
    setup_path = root / "tools/setup_runtime.py"
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [{"code": "RUNTIME_BINDING_CONTRACT_INVALID", "message": str(exc)}]
    runtime_setup = portability.get("release_requirements", {}).get("runtime_setup")
    setup_sha256 = file_hash(setup_path) if setup_path.is_file() else None
    required_true = (
        "validation_before_first_execution_root_write",
        "portable_manifest_preflight_required",
        "candidate_uri_preflight_required",
        "runtime_dependency_closure_required",
        "receiver_authority_preflight_required",
        "fresh_root_atomic_publish_required",
        "failure_cleanup_keeps_fresh_root_absent",
        "existing_root_fail_closed_by_default",
        "idempotent_reentry_requires_explicit_flag",
        "idempotent_reentry_requires_exact_receipt",
        "receiver_raw_execution_path_identity_required",
        "final_component_lstat_before_resolution_required",
        "parent_directory_identity_pinned_through_publish",
        "fresh_root_atomic_noreplace_required",
        "existing_receipt_nofollow_read_required",
    )
    invalid = (
        not setup_path.is_file()
        or contract.get("setup_ref")
        != "harness-resource://candidate/tools/setup_runtime.py"
        or contract.get("setup_sha256") != setup_sha256
        or contract.get("candidate_write_policy") != "FORBIDDEN"
        or contract.get("fresh_root_same_parent_staging_required") is not True
        or contract.get("human_gate_consumption_before_binding_success_allowed")
        is not False
        or contract.get("existing_binding_overwrite_allowed") is not False
        or any(contract.get(field) is not True for field in required_true)
        or not isinstance(runtime_setup, Mapping)
        or runtime_setup.get("setup_ref") != contract.get("setup_ref")
        or runtime_setup.get("setup_sha256") != setup_sha256
        or any(runtime_setup.get(field) is not True for field in required_true)
        or runtime_setup.get("existing_binding_overwrite_allowed") is not False
        or contract.get("unsupported_noreplace_platform_behavior") != "FAIL_CLOSED"
        or runtime_setup.get("unsupported_noreplace_platform_behavior") != "FAIL_CLOSED"
    )
    return ([{
        "code": "RUNTIME_BINDING_CONTRACT_INVALID",
        "message": "setup_runtime.py Hash or atomic preflight contract drifted",
    }] if invalid else [])


def json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def contract_parts(value: Any) -> tuple[str, ...] | None:
    text = str(value)
    for uri, identity in (
        (CANDIDATE_URI, ("resource", "candidate")),
        (EXECUTION_URI, ("resource", "execution")),
    ):
        if text == uri:
            return identity
        prefix = f"{uri}/"
        if text.startswith(prefix):
            pieces = text[len(prefix) :].split("/")
            if not pieces or any(piece in {"", ".", ".."} for piece in pieces):
                return None
            return (*identity, *pieces)
    return None


def contained(value: Any, allowed_root: Any) -> bool:
    value_parts = contract_parts(value)
    root_parts = contract_parts(allowed_root)
    return bool(
        value_parts is not None
        and root_parts is not None
        and value_parts[: len(root_parts)] == root_parts
    )


def expected_matrix(dag_path: Path, dag: Mapping[str, Any]) -> dict[str, Any]:
    root = dag_path.parent
    workpack_artifact_refs_by_node: dict[str, list[str]] = {}
    for directory in ("external_lab", "linkage_review", "main_build"):
        index_path = (
            root
            / "project_start_packages"
            / directory
            / "WORKPACK_INDEX.json"
        )
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        for raw_workpack in index.get("workpacks", []):
            workpack = raw_workpack if isinstance(raw_workpack, Mapping) else {}
            if workpack.get("program_control_surface") != "ENGINEERING_PROJECT_DAG":
                continue
            node_id = str(workpack.get("program_control_node_id") or "")
            if not node_id:
                continue
            refs = workpack_artifact_refs_by_node.setdefault(node_id, [])
            for artifact_ref in workpack.get("required_artifact_refs", []):
                if isinstance(artifact_ref, str) and artifact_ref not in refs:
                    refs.append(artifact_ref)
    rows: list[dict[str, Any]] = []
    for raw_node in dag.get("nodes", []):
        node = raw_node if isinstance(raw_node, Mapping) else {}
        node_id = str(node.get("node_id") or "")
        allowed = list(node.get("allowed_write_paths") or [])
        outputs = list(node.get("success_output_refs") or [])
        workpack_artifact_refs = workpack_artifact_refs_by_node.get(
            node_id, []
        )
        inside = [
            output
            for output in outputs
            if any(contained(output, root) for root in allowed)
        ]
        outside = [output for output in outputs if output not in inside]
        inside_workpack_artifact_refs = [
            artifact_ref
            for artifact_ref in workpack_artifact_refs
            if any(contained(artifact_ref, root) for root in allowed)
        ]
        outside_workpack_artifact_refs = [
            artifact_ref
            for artifact_ref in workpack_artifact_refs
            if artifact_ref not in inside_workpack_artifact_refs
        ]
        rows.append(
            {
                "node_id": node.get("node_id"),
                "allowed_write_paths": allowed,
                "success_output_refs": outputs,
                "contained_success_output_refs": inside,
                "outside_success_output_refs": outside,
                "workpack_artifact_refs": workpack_artifact_refs,
                "contained_workpack_artifact_refs": (
                    inside_workpack_artifact_refs
                ),
                "outside_workpack_artifact_refs": (
                    outside_workpack_artifact_refs
                ),
                "status": "PASS"
                if (
                    outputs
                    and len(inside) == len(outputs)
                    and not outside_workpack_artifact_refs
                )
                else "FAIL",
            }
        )
    pass_count = sum(row["status"] == "PASS" for row in rows)
    return {
        "schema_version": "1.0",
        "matrix_id": "DAG_PATH_CONTAINMENT_MATRIX",
        "dag_ref": "ENGINEERING_PROJECT_DAG.json",
        "dag_sha256": file_hash(dag_path),
        "containment_contract": (
            "STRICT_RESOLVED_RESOURCE_IDENTITY_CONTAINMENT_NOT_STRING_PREFIX"
        ),
        "finding_code": (
            "ENGINEERING_DAG_SUCCESS_OUTPUT_OUTSIDE_ALLOWED_WRITE_PATHS"
        ),
        "workpack_artifact_finding_code": (
            "ENGINEERING_DAG_WORKPACK_ARTIFACT_OUTSIDE_ALLOWED_WRITE_PATHS"
        ),
        "node_count": len(rows),
        "pass_count": pass_count,
        "rows": rows,
        "status": "PASS" if rows and pass_count == len(rows) else "FAIL",
    }


def acceptance_write_roots(bundle: Mapping[str, Any] | None) -> list[str] | None:
    if bundle is None:
        return []
    roots: list[str] = []
    try:
        for task in bundle["task_contracts"]:
            for artifact in task["artifact_obligations"]:
                control = artifact.get("artifact_kind") == "WORKPACK_CONTROL_RESULT"
                if control != (artifact.get("production_owner") == "WORKPACK_ACCEPTANCE_CONTROLLER"):
                    return None
                if control:
                    if artifact.get("production_timing") != "AFTER_NATIVE_COMMANDS_AND_ORACLES":
                        return None
                    root = artifact["artifact_ref"].rsplit("/", 1)[0]
                    if root not in roots:
                        roots.append(root)
    except (KeyError, TypeError, AttributeError):
        return None
    return roots


def check_project_workpack_write_projection(
    root: Path, dag: Mapping[str, Any]
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    project_directories = {
        "EXTERNAL_CONFORMANCE_LAB": "external_lab",
        "CONFORMANCE_LINKAGE_REVIEW": "linkage_review",
        "MAIN_HARNESS_BUILD": "main_build",
    }
    nodes = {
        str(item.get("node_id")): item
        for item in dag.get("nodes", [])
        if isinstance(item, Mapping) and item.get("node_id")
    }
    projected_by_node: dict[str, list[str]] = {}
    for project_id, directory in project_directories.items():
        index_path = (
            root
            / "project_start_packages"
            / directory
            / "WORKPACK_INDEX.json"
        )
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            findings.append(
                {
                    "code": "PROJECT_WORKPACK_WRITE_ROOT_CONTRACT_INVALID",
                    "message": f"{directory}: {exc}",
                }
            )
            continue
        for raw_item in index.get("workpacks", []):
            if not isinstance(raw_item, Mapping) or not raw_item.get("workpack_id"):
                findings.append(
                    {
                        "code": "PROJECT_WORKPACK_WRITE_ROOT_CONTRACT_INVALID",
                        "message": f"{directory}: invalid Workpack row",
                    }
                )
                continue
            item = raw_item
            workpack_id = str(item["workpack_id"])
            expected = [
                f"{EXECUTION_URI}/evidence/project_workpacks/"
                f"{project_id}/{workpack_id}"
            ]
            command_ids = item.get("command_ids")
            if isinstance(command_ids, list) and any(
                str(command_id).endswith("CODEX-CODING")
                for command_id in command_ids
            ):
                expected.append(
                    f"{EXECUTION_URI}/project_start_packages/"
                    f"{directory}/repository"
                )
            artifact_refs = item.get("required_artifact_refs", [])
            artifact_write_roots: list[str] = []
            artifact_root_binding_valid = isinstance(artifact_refs, list)
            try:
                bundle = (json.loads((index_path.parent / f"task_bundles/{workpack_id}.task_bundle.json").read_text())
                          if item.get("task_bundle_ref") else None)
                controller_roots = acceptance_write_roots(bundle)
            except (OSError, UnicodeError, json.JSONDecodeError):
                controller_roots = None
            if controller_roots is None:
                artifact_root_binding_valid = False
                findings.append({"code": "WORKPACK_ARTIFACT_PRODUCTION_OWNER_INVALID", "message": workpack_id})
            for artifact_ref in artifact_refs if isinstance(artifact_refs, list) else []:
                prefix = f"{EXECUTION_URI}/"
                if (
                    not isinstance(artifact_ref, str)
                    or not artifact_ref.startswith(prefix)
                    or "/" not in artifact_ref[len(prefix) :]
                    or any(
                        part in {"", ".", ".."}
                        for part in artifact_ref[len(prefix) :].split("/")
                    )
                ):
                    artifact_root_binding_valid = False
                    continue
                artifact_root = artifact_ref.rsplit("/", 1)[0]
                if artifact_root not in artifact_write_roots:
                    artifact_write_roots.append(artifact_root)
                if artifact_root not in expected:
                    expected.append(artifact_root)
            auxiliary_write_roots = (
                [f"{EXECUTION_URI}/evidence/cases"]
                if workpack_id == "LAB-CERTIFICATION"
                else []
            )
            for auxiliary_root in auxiliary_write_roots:
                if auxiliary_root not in expected:
                    expected.append(auxiliary_root)
            command_write_roots = list(
                dict.fromkeys([*artifact_write_roots, *auxiliary_write_roots])
            )
            capsule_ref = item.get("capsule_ref")
            capsule_write_paths: Any = None
            if (
                isinstance(capsule_ref, str)
                and not Path(capsule_ref).is_absolute()
                and ".." not in Path(capsule_ref).parts
            ):
                try:
                    capsule = json.loads(
                        (index_path.parent / capsule_ref).read_text(
                            encoding="utf-8"
                        )
                    )
                    capsule_write_paths = capsule.get("allowed_write_paths")
                except (OSError, UnicodeError, json.JSONDecodeError):
                    capsule_write_paths = None
            command_write_binding_valid = True
            if command_write_roots:
                command_manifest_ref = item.get("command_manifest_ref")
                try:
                    if (
                        not isinstance(command_manifest_ref, str)
                        or Path(command_manifest_ref).is_absolute()
                        or ".." in Path(command_manifest_ref).parts
                    ):
                        raise ValueError("invalid command manifest ref")
                    command_manifest = json.loads(
                        (index_path.parent / command_manifest_ref).read_text(
                            encoding="utf-8"
                        )
                    )
                    commands = command_manifest.get("commands")
                    declared_command_roots: list[str] = []
                    command_scopes_valid = isinstance(commands, list)
                    for command in commands if isinstance(commands, list) else []:
                        if not isinstance(command, Mapping):
                            command_scopes_valid = False
                            continue
                        is_coding = str(command.get("command_id") or "").endswith(
                            "CODEX-CODING"
                        )
                        shared = command.get("shared_artifact_write_roots")
                        scopes = command.get("job_artifact_write_scopes")
                        if not isinstance(shared, list) or not isinstance(scopes, list):
                            command_scopes_valid = False
                            continue
                        if not is_coding and scopes:
                            command_scopes_valid = False
                        for declared_root in shared:
                            if declared_root not in declared_command_roots:
                                declared_command_roots.append(declared_root)
                        for scope in scopes:
                            if (
                                not isinstance(scope, Mapping)
                                or not isinstance(scope.get("job_id"), str)
                                or not isinstance(scope.get("allowed_write_roots"), list)
                                or any(
                                    f"/jobs/{scope.get('job_id')}/" not in scoped_root
                                    for scoped_root in scope.get("allowed_write_roots", [])
                                )
                            ):
                                command_scopes_valid = False
                                continue
                            for scoped_root in scope["allowed_write_roots"]:
                                if scoped_root not in declared_command_roots:
                                    declared_command_roots.append(scoped_root)
                        if any(
                            allowed_root in command_write_roots
                            and "/jobs/" in allowed_root
                            for allowed_root in command.get("allowed_write_roots", [])
                        ):
                            command_scopes_valid = False
                    command_write_binding_valid = bool(
                        command_manifest.get("workpack_artifact_write_roots")
                        == artifact_write_roots
                        and command_manifest.get("workpack_acceptance_write_roots") == controller_roots
                        and command_manifest.get("workpack_auxiliary_write_roots")
                        == auxiliary_write_roots
                        and isinstance(commands, list)
                        and commands
                        and command_scopes_valid
                        and set(declared_command_roots)
                        == set(command_write_roots) - set(controller_roots or [])
                        and len(declared_command_roots)
                        == len(set(command_write_roots) - set(controller_roots or []))
                        and all(not any(contained(root, allowed) for root in (controller_roots or [])
                                        for allowed in command.get("allowed_write_roots", []))
                                for command in commands)
                    )
                except (
                    OSError,
                    UnicodeError,
                    json.JSONDecodeError,
                    ValueError,
                ):
                    command_write_binding_valid = False
            if (
                not artifact_root_binding_valid
                or not command_write_binding_valid
                or item.get("allowed_write_paths") != expected
                or capsule_write_paths != expected
            ):
                findings.append(
                    {
                        "code": "PROJECT_WORKPACK_WRITE_ROOT_CONTRACT_INVALID",
                        "message": f"{directory}:{workpack_id}",
                    }
                )
            if item.get("program_control_surface") != "ENGINEERING_PROJECT_DAG":
                continue
            node_id = str(item.get("program_control_node_id") or "")
            node = nodes.get(node_id)
            if node is None or any(
                value not in node.get("allowed_write_paths", [])
                for value in expected
            ):
                findings.append(
                    {
                        "code": "ENGINEERING_WORKPACK_WRITE_ROOT_PROJECTION_INVALID",
                        "message": f"{node_id}:{workpack_id}",
                    }
                )
            projected_by_node.setdefault(node_id, [])
            for value in expected:
                if value not in projected_by_node[node_id]:
                    projected_by_node[node_id].append(value)
    for node_id, node in nodes.items():
        expected_node_paths = [
            f"{EXECUTION_URI}/evidence/engineering_dag/{node_id}"
        ]
        project_id = str(node.get("project_id") or "")
        directory = project_directories.get(project_id)
        if directory and (
            node.get("action_kind") == "WORKPACK_SEQUENCE"
            or node_id == "MAIN_EXECUTION_PACKAGE_MATERIALIZED"
        ):
            expected_node_paths.append(
                f"{EXECUTION_URI}/project_start_packages/"
                f"{directory}/repository"
            )
        for value in projected_by_node.get(node_id, []):
            if value not in expected_node_paths:
                expected_node_paths.append(value)
        actual_node_paths = node.get("allowed_write_paths")
        if (
            not isinstance(actual_node_paths, list)
            or len(actual_node_paths) != len(expected_node_paths)
            or set(actual_node_paths) != set(expected_node_paths)
        ):
            findings.append(
                {
                    "code": "ENGINEERING_NODE_WRITE_ROOT_SET_INVALID",
                    "message": node_id,
                }
            )
    return findings


def closure_requirements(
    frozen_ir: Mapping[str, Any],
) -> list[tuple[str, Mapping[str, Any]]]:
    target = frozen_ir.get("target")
    if not isinstance(target, Mapping):
        return []
    return sorted(
        (str(key), value)
        for key, value in target.items()
        if isinstance(value, Mapping)
        and (
            (
                str(key).startswith("human_review_")
                and str(key).endswith("_closure")
            )
            or value.get("closure_receipt_required") is True
        )
    )


def closure_requirement_status(closure: Mapping[str, Any]) -> Any:
    if closure.get("closure_receipt_required") is True:
        return closure.get("closure_receipt_status")
    return closure.get("status")


def check_source_authority_normalization(
    source_policy: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Standalone Oracle: compare compiled authority with receiver semantics."""

    findings: list[dict[str, str]] = []
    declared_items = source_policy.get("sources")
    compiled_items = source_manifest.get("sources")
    if not isinstance(declared_items, list) or not isinstance(compiled_items, list):
        return [{
            "code": "SOURCE_AUTHORITY_NORMALIZATION_CONTRACT_INVALID",
            "message": "source declarations or compiled manifest are not lists",
        }]
    declared = {
        str(item.get("source_id")): item
        for item in declared_items
        if isinstance(item, Mapping) and item.get("source_id")
    }
    compiled = {
        str(item.get("source_id")): item
        for item in compiled_items
        if isinstance(item, Mapping) and item.get("source_id")
    }
    if len(declared) != len(declared_items) or len(compiled) != len(compiled_items):
        findings.append({
            "code": "SOURCE_AUTHORITY_NORMALIZATION_CONTRACT_INVALID",
            "message": "source identities are missing or duplicated",
        })
    if set(declared) != set(compiled):
        findings.append({
            "code": "SOURCE_AUTHORITY_NORMALIZATION_CONTRACT_INVALID",
            "message": "compiled source identity set differs from frozen declarations",
        })
    semantic_policy = source_policy.get("lock_id") in {
        "V29_SOURCE_AUTHORITY_POLICY_LOCK_V2",
        "V29_SOURCE_AUTHORITY_POLICY_LOCK_V3",
        "V29_SOURCE_AUTHORITY_POLICY_LOCK_V4",
    }
    for source_id in sorted(set(declared) & set(compiled)):
        expected = declared[source_id]
        materialized = compiled[source_id]
        if semantic_policy:
            declared_authority = expected.get("declared_authority_level")
            canonical = expected.get("canonical_authority_level")
            content_sha256 = expected.get("content_sha256")
            copy_policy = expected.get("copy_policy")
            loaded_completely = expected.get("loaded_completely")
        else:
            declared_authority = expected.get(
                "declared_authority_level", expected.get("authority_level")
            )
            canonical = AUTHORITY_NORMALIZATION.get(
                declared_authority, declared_authority
            )
            content_sha256 = expected.get("sha256")
            copy_policy = expected.get("copy_policy") or "REFERENCE_ONLY"
            loaded_completely = bool(expected.get("loaded_completely", True))
        materialized_declared = materialized.get("declared_authority_level")
        if materialized_declared is None:
            materialized_declared = materialized.get("authority_level")
        if (
            canonical != AUTHORITY_NORMALIZATION.get(
                declared_authority, declared_authority
            )
            or canonical not in CANONICAL_AUTHORITY_LEVELS
            or materialized.get("authority_level") != canonical
            or materialized_declared != declared_authority
            or materialized.get("sha256") != content_sha256
            or materialized.get("copy_policy") != copy_policy
            or materialized.get("loaded_completely")
            is not loaded_completely
        ):
            findings.append({
                "code": "SOURCE_AUTHORITY_NORMALIZATION_CONTRACT_INVALID",
                "message": source_id,
            })
    return findings


def check_source_portable_uri_projection(
    root: Path,
    source_manifest: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Independently validate Candidate-local logical source references."""

    findings: list[dict[str, str]] = []
    sources = source_manifest.get("sources")
    if not isinstance(sources, list):
        return [{
            "code": "SOURCE_PORTABLE_URI_PROJECTION_INVALID",
            "message": "SOURCE_MANIFEST sources are not a list",
        }]
    seen: set[str] = set()
    for raw in sources:
        if not isinstance(raw, Mapping):
            findings.append({
                "code": "SOURCE_PORTABLE_URI_PROJECTION_INVALID",
                "message": "source entry is not an object",
            })
            continue
        source_id = str(raw.get("source_id") or "")
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", source_id)
            or ".." in source_id
            or source_id in seen
        ):
            findings.append({
                "code": "SOURCE_PORTABLE_URI_PROJECTION_INVALID",
                "message": source_id or "missing source_id",
            })
            continue
        seen.add(source_id)
        receipt_uri = (
            f"{CANDIDATE_URI}/canonical_sources/evidence/"
            f"{source_id}.source_receipt.json"
        )
        payload_uri = (
            f"{CANDIDATE_URI}/canonical_sources/evidence/"
            f"{source_id}.payload.b64"
        )
        payload_embedded = raw.get("payload_embedded") is True
        expected_snapshot = payload_uri if payload_embedded else receipt_uri
        receipt_path = (
            root / "canonical_sources/evidence" / f"{source_id}.source_receipt.json"
        )
        if (
            raw.get("path_or_uri") != receipt_uri
            or raw.get("portable_evidence_ref") != receipt_uri
            or raw.get("snapshot_path") != expected_snapshot
            or not receipt_path.is_file()
        ):
            findings.append({
                "code": "SOURCE_PORTABLE_URI_PROJECTION_INVALID",
                "message": source_id,
            })
            continue
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            findings.append({
                "code": "SOURCE_PORTABLE_URI_PROJECTION_INVALID",
                "message": source_id,
            })
            continue
        if (
            receipt.get("source_id") != source_id
            or receipt.get("source_sha256") != raw.get("sha256")
            or receipt.get("authority_level") != raw.get("authority_level")
            or receipt.get("copy_policy") != raw.get("copy_policy")
            or receipt.get("payload_embedded") is not payload_embedded
            or receipt.get("payload_ref")
            != (payload_uri if payload_embedded else None)
            or receipt.get("repository_metadata")
            != (
                {
                    field: raw[field]
                    for field in (
                        "repository_url",
                        "revision",
                        "commit_sha",
                        "git_tree_oid",
                        "tree_sha256",
                        "license_spdx",
                        "license_ref",
                        "retrieved_at",
                    )
                    if raw.get(field) not in (None, "")
                }
                or None
            )
        ):
            findings.append({
                "code": "SOURCE_PORTABLE_URI_PROJECTION_INVALID",
                "message": source_id,
            })
            continue
        if payload_embedded:
            payload_path = (
                root / "canonical_sources/evidence" / f"{source_id}.payload.b64"
            )
            try:
                payload = base64.b64decode(
                    payload_path.read_text(encoding="ascii").strip(),
                    validate=True,
                )
            except (OSError, UnicodeError, ValueError):
                findings.append({
                    "code": "SOURCE_PORTABLE_URI_PROJECTION_INVALID",
                    "message": source_id,
                })
                continue
            if hashlib.sha256(payload).hexdigest() != raw.get("sha256"):
                findings.append({
                    "code": "SOURCE_PORTABLE_URI_PROJECTION_INVALID",
                    "message": source_id,
                })
    return findings


def check_portable_source_index(
    root: Path,
    source_manifest: Mapping[str, Any],
    index_override: Mapping[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Standalone Oracle for Index meaning, independent of inventory Hashes."""

    code = "PORTABLE_SOURCE_INDEX_SEMANTICS_INVALID"
    if index_override is None:
        try:
            index = json.loads(
                (root / "canonical_sources/PORTABLE_SOURCE_INDEX.json").read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return [{"code": code, "message": str(exc)}]
    else:
        index = index_override
    top_fields = {
        "schema_version", "candidate_root", "source_count",
        "all_source_references_resolve_in_candidate",
        "all_copy_immutable_snapshots_embedded", "sources",
    }
    entry_fields = {
        "source_id", "source_sha256", "copy_policy", "receipt_ref",
        "receipt_sha256", "payload_ref", "payload_file_sha256",
        "payload_embedded", "repository_metadata",
    }
    manifest_items = source_manifest.get("sources")
    entries = index.get("sources") if isinstance(index, Mapping) else None
    if not isinstance(manifest_items, list) or not isinstance(entries, list):
        return [{"code": code, "message": "manifest or Index sources is not a list"}]
    sources = {
        str(item.get("source_id")): item
        for item in manifest_items
        if isinstance(item, Mapping) and item.get("source_id")
    }
    entry_ids = [
        str(item.get("source_id"))
        for item in entries
        if isinstance(item, Mapping) and item.get("source_id")
    ]
    expected_all_snapshots = all(
        source.get("payload_embedded") is True
        for source in sources.values()
        if source.get("copy_policy") == "COPY_IMMUTABLE_SNAPSHOT"
    )
    findings: list[dict[str, str]] = []
    if (
        not isinstance(index, Mapping)
        or set(index) != top_fields
        or index.get("schema_version") != "1.0"
        or index.get("candidate_root") != CANDIDATE_URI
        or index.get("source_count") != len(sources)
        or index.get("all_source_references_resolve_in_candidate") is not True
        or index.get("all_copy_immutable_snapshots_embedded")
        is not expected_all_snapshots
        or len(sources) != len(manifest_items)
        or len(entry_ids) != len(entries)
        or len(set(entry_ids)) != len(entry_ids)
        or set(entry_ids) != set(sources)
    ):
        findings.append({"code": code, "message": "Index coverage or top-level contract drifted"})
        return findings
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != entry_fields:
            findings.append({"code": code, "message": "Index entry shape drifted"})
            continue
        source_id = str(entry.get("source_id"))
        source = sources[source_id]
        receipt_ref = (
            f"{CANDIDATE_URI}/canonical_sources/evidence/"
            f"{source_id}.source_receipt.json"
        )
        payload_ref = (
            f"{CANDIDATE_URI}/canonical_sources/evidence/"
            f"{source_id}.payload.b64"
        )
        payload_embedded = source.get("payload_embedded") is True
        repository_metadata = {
            field: source[field]
            for field in (
                "repository_url", "revision", "commit_sha", "git_tree_oid",
                "tree_sha256", "license_spdx", "license_ref", "retrieved_at",
            )
            if source.get(field) not in (None, "")
        } or None
        receipt_path = (
            root / "canonical_sources/evidence" / f"{source_id}.source_receipt.json"
        )
        if (
            entry.get("source_sha256") != source.get("sha256")
            or entry.get("copy_policy") != source.get("copy_policy")
            or entry.get("repository_metadata") != repository_metadata
            or entry.get("receipt_ref") != receipt_ref
            or source.get("path_or_uri") != receipt_ref
            or source.get("portable_evidence_ref") != receipt_ref
            or entry.get("payload_embedded") is not payload_embedded
            or entry.get("payload_ref")
            != (payload_ref if payload_embedded else None)
            or source.get("snapshot_path")
            != (payload_ref if payload_embedded else receipt_ref)
            or not receipt_path.is_file()
            or entry.get("receipt_sha256") != file_hash(receipt_path)
        ):
            findings.append({"code": code, "message": source_id})
            continue
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            findings.append({"code": code, "message": source_id})
            continue
        if (
            receipt.get("source_id") != source_id
            or receipt.get("source_sha256") != source.get("sha256")
            or receipt.get("copy_policy") != source.get("copy_policy")
            or receipt.get("repository_metadata") != repository_metadata
            or receipt.get("payload_embedded") is not payload_embedded
            or receipt.get("payload_ref")
            != (payload_ref if payload_embedded else None)
        ):
            findings.append({"code": code, "message": source_id})
            continue
        if payload_embedded:
            payload_path = (
                root / "canonical_sources/evidence" / f"{source_id}.payload.b64"
            )
            try:
                payload = base64.b64decode(
                    payload_path.read_text(encoding="ascii").strip(),
                    validate=True,
                )
            except (OSError, UnicodeError, ValueError):
                findings.append({"code": code, "message": source_id})
                continue
            if (
                entry.get("payload_file_sha256") != file_hash(payload_path)
                or hashlib.sha256(payload).hexdigest() != source.get("sha256")
            ):
                findings.append({"code": code, "message": source_id})
        elif entry.get("payload_file_sha256") is not None:
            findings.append({"code": code, "message": source_id})
    return findings


def check_epoch26_portable_index_attack(
    root: Path,
    source_manifest: Mapping[str, Any],
) -> bool:
    """Prove semantic rejection survives synchronized downstream re-Hashing."""

    try:
        mutated = json.loads(
            (root / "canonical_sources/PORTABLE_SOURCE_INDEX.json").read_text(
                encoding="utf-8"
            )
        )
        entries = mutated.get("sources")
        if not isinstance(entries, list) or not entries:
            return False
        entry = entries[0]
        if not isinstance(entry, dict):
            return False
        if entry.get("payload_embedded") is True:
            entry["payload_ref"] = (
                f"{CANDIDATE_URI}/canonical_sources/evidence/"
                "ATTACKER.payload.b64"
            )
        else:
            entry["receipt_ref"] = (
                f"{CANDIDATE_URI}/canonical_sources/evidence/"
                "ATTACKER.source_receipt.json"
            )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return bool(check_portable_source_index(root, source_manifest, mutated))


def load_receiver_source_authority_policy(
    root: Path,
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    """Verify receiver-pinned signature and exact issuer/event freshness binding."""

    supplied = os.environ.get("HF_SOURCE_AUTHORITY_POLICY_LOCK")
    anchor_supplied = os.environ.get("HF_SOURCE_AUTHORITY_TRUST_ANCHOR")
    pinned_anchor_sha256 = os.environ.get(
        "HF_SOURCE_AUTHORITY_TRUST_ANCHOR_SHA256"
    )
    if not supplied or not anchor_supplied or not pinned_anchor_sha256:
        return None, [{
            "code": "SOURCE_AUTHORITY_POLICY_LOCK_REQUIRED",
            "message": (
                "set receiver-side policy path, Trust Anchor path, and pinned "
                "Trust Anchor file SHA-256"
            ),
        }]
    try:
        path = Path(supplied).expanduser().resolve(strict=True)
        anchor_path = Path(anchor_supplied).expanduser().resolve(strict=True)
        candidate_root = root.resolve(strict=True)
        if (
            path == anchor_path
            or path == candidate_root
            or candidate_root in path.parents
            or anchor_path == candidate_root
            or candidate_root in anchor_path.parents
        ):
            raise ValueError("policy and Trust Anchor must be distinct and external")
        if (
            re.fullmatch(r"[0-9a-f]{64}", pinned_anchor_sha256) is None
            or file_hash(anchor_path) != pinned_anchor_sha256
        ):
            raise ValueError("Trust Anchor does not match receiver-pinned file Hash")
        policy = json.loads(path.read_text(encoding="utf-8"))
        anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return None, [{
            "code": "SOURCE_AUTHORITY_POLICY_LOCK_INVALID",
            "message": str(exc),
        }]
    expected_fields = {
        "schema_version", "lock_id", "authority_source",
        "trust_anchor_id", "issuer_binding",
        "authority_normalization", "canonical_authority_levels",
        "semantic_projection_fields", "sources", "policy_payload_sha256",
        "release_history_tip_sha256", "release_history",
        "signature_algorithm", "signature_base64", "lock_sha256",
    }
    anchor_fields = {
        "schema_version", "anchor_id", "authority_source",
        "signature_algorithm", "issuer_id", "key_id",
        "public_key_raw_base64", "program_id", "requirement_epoch",
        "issuance_event_id", "issuance_event_revision",
        "issuance_event_sha256", "source_registry_revision",
        "source_registry_tip_sha256", "release_history_tip_sha256",
        "anchor_sha256",
    }
    issuer_fields = {
        "issuer_id", "key_id", "program_id", "requirement_epoch",
        "issuance_event_id", "issuance_event_revision",
        "issuance_event_sha256", "source_registry_revision",
        "source_registry_tip_sha256", "release_history_tip_sha256",
    }
    semantic_fields = {
        "source_id", "content_sha256", "copy_policy", "loaded_completely",
        "declared_authority_level", "canonical_authority_level",
    }
    history_fields = {
        "requirement_key", "closure_requirement_epoch",
        "superseded_candidate", "replacement_candidate",
        "successor_candidate_version",
    }
    policy_sources = policy.get("sources") if isinstance(policy, dict) else None
    policy_history = (
        policy.get("release_history") if isinstance(policy, dict) else None
    )
    report_binding = (
        policy.get("validation_report_binding")
        if isinstance(policy, dict) else None
    )
    report_binding_required = (
        isinstance(anchor, dict)
        and isinstance(anchor.get("requirement_epoch"), int)
        and anchor["requirement_epoch"] >= 30
    )
    if report_binding_required:
        expected_fields.add("validation_report_binding")
    issuer = policy.get("issuer_binding") if isinstance(policy, dict) else None
    signed_body = {
        key: value
        for key, value in policy.items()
        if key not in {
            "policy_payload_sha256", "signature_algorithm",
            "signature_base64", "lock_sha256",
        }
    } if isinstance(policy, dict) else {}
    expected_issuance_event = {
        "event_id": issuer.get("issuance_event_id"),
        "event_revision": issuer.get("issuance_event_revision"),
        "event_type": "SOURCE_AUTHORITY_POLICY_ISSUED",
        "program_id": issuer.get("program_id"),
        "requirement_epoch": issuer.get("requirement_epoch"),
        "source_registry_revision": issuer.get("source_registry_revision"),
        "source_registry_tip_sha256": issuer.get("source_registry_tip_sha256"),
        "release_history_tip_sha256": issuer.get("release_history_tip_sha256"),
    } if isinstance(issuer, Mapping) else {}
    if (
        not isinstance(policy, dict)
        or not isinstance(anchor, dict)
        or set(policy) != expected_fields
        or set(anchor) != anchor_fields
        or policy.get("schema_version") != "2.9"
        or anchor.get("schema_version") != "2.9"
        or policy.get("lock_id") != "V29_SOURCE_AUTHORITY_POLICY_LOCK_V4"
        or anchor.get("anchor_id") != "V29_SOURCE_AUTHORITY_TRUST_ANCHOR_V1"
        or policy.get("authority_source")
        != "RECEIVER_CONTROL_PLANE_EXTERNAL_TO_CANDIDATE"
        or anchor.get("authority_source")
        != "RECEIVER_CONTROL_PLANE_EXTERNAL_TO_CANDIDATE"
        or policy.get("trust_anchor_id") != anchor.get("anchor_id")
        or policy.get("signature_algorithm") != "ED25519"
        or anchor.get("signature_algorithm") != "ED25519"
        or anchor.get("anchor_sha256")
        != json_hash({key: value for key, value in anchor.items() if key != "anchor_sha256"})
        or not isinstance(issuer, dict)
        or set(issuer) != issuer_fields
        or any(issuer.get(field) != anchor.get(field) for field in issuer_fields)
        or issuer.get("issuance_event_sha256") != json_hash(expected_issuance_event)
        or issuer.get("source_registry_tip_sha256") != json_hash(policy_sources)
        or issuer.get("release_history_tip_sha256") != json_hash(policy_history)
        or policy.get("release_history_tip_sha256") != json_hash(policy_history)
        or (
            report_binding_required
            and (
                not isinstance(report_binding, dict)
                or set(report_binding) != {
                    "report_ref", "report_sha256",
                    "receipt_ref", "receipt_sha256",
                }
                or report_binding.get("report_ref")
                != "validation/START_PACKAGE_VALIDATION_REPORT.json"
                or report_binding.get("receipt_ref")
                != "validation/START_PACKAGE_VALIDATION_REPORT_RECEIPT.json"
                or any(
                    re.fullmatch(
                        r"[0-9a-f]{64}",
                        str(report_binding.get(field) or ""),
                    ) is None
                    for field in ("report_sha256", "receipt_sha256")
                )
            )
        )
        or (not report_binding_required and report_binding is not None)
        or not isinstance(issuer.get("requirement_epoch"), int)
        or issuer.get("requirement_epoch") < 0
        or not isinstance(issuer.get("issuance_event_revision"), int)
        or issuer.get("issuance_event_revision") < 0
        or not isinstance(issuer.get("source_registry_revision"), int)
        or issuer.get("source_registry_revision") < 0
        or any(
            re.fullmatch(r"[0-9a-f]{64}", str(issuer.get(field) or "")) is None
            for field in (
                "issuance_event_sha256", "source_registry_tip_sha256",
                "release_history_tip_sha256",
            )
        )
        or policy.get("authority_normalization") != AUTHORITY_NORMALIZATION
        or set(policy.get("canonical_authority_levels") or [])
        != CANONICAL_AUTHORITY_LEVELS
        or policy.get("semantic_projection_fields")
        != [
            "source_id", "content_sha256", "copy_policy", "loaded_completely",
            "declared_authority_level", "canonical_authority_level",
        ]
        or policy.get("lock_sha256")
        != json_hash({key: value for key, value in policy.items() if key != "lock_sha256"})
        or policy.get("policy_payload_sha256") != json_hash(signed_body)
        or not isinstance(policy_sources, list)
        or not policy_sources
        or any(
            not isinstance(item, dict)
            or set(item) != semantic_fields
            or not isinstance(item.get("source_id"), str)
            or not item.get("source_id")
            or not isinstance(item.get("content_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", item["content_sha256"]) is None
            or not isinstance(item.get("copy_policy"), str)
            or not isinstance(item.get("loaded_completely"), bool)
            or not isinstance(item.get("declared_authority_level"), str)
            or item.get("canonical_authority_level")
            != AUTHORITY_NORMALIZATION.get(
                item.get("declared_authority_level"),
                item.get("declared_authority_level"),
            )
            for item in policy_sources
        )
        or len({item["source_id"] for item in policy_sources})
        != len(policy_sources)
        or not isinstance(policy_history, list)
        or not policy_history
        or any(
            not isinstance(item, dict)
            or set(item) != history_fields
            or not isinstance(item.get("requirement_key"), str)
            or not item.get("requirement_key")
            or not isinstance(item.get("closure_requirement_epoch"), int)
            or item.get("closure_requirement_epoch") < 0
            or not isinstance(item.get("superseded_candidate"), str)
            or not item.get("superseded_candidate")
            or not isinstance(item.get("successor_candidate_version"), str)
            or re.fullmatch(
                r"v0_[1-9][0-9]*", item["successor_candidate_version"]
            ) is None
            or item.get("replacement_candidate")
            != f"candidate-{item['successor_candidate_version']}"
            for item in policy_history
        )
        or len({item["requirement_key"] for item in policy_history})
        != len(policy_history)
    ):
        return None, [{
            "code": "SOURCE_AUTHORITY_POLICY_LOCK_INVALID",
            "message": "receiver policy, Trust Anchor, issuer binding, or Hash is invalid",
        }]
    try:
        public_key_bytes = base64.b64decode(
            anchor["public_key_raw_base64"], validate=True
        )
        signature = base64.b64decode(policy["signature_base64"], validate=True)
        if len(public_key_bytes) != 32:
            raise ValueError("Ed25519 public key must be 32 bytes")
        payload = json.dumps(
            signed_body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
            signature, payload
        )
    except (InvalidSignature, ValueError, TypeError) as exc:
        return None, [{
            "code": "SOURCE_AUTHORITY_POLICY_SIGNATURE_INVALID",
            "message": str(exc) or "signature verification failed",
        }]
    return policy, []


def check_validation_report_binding(
    root: Path,
    policy: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Bind the late validation report through a non-circular signed receipt."""

    report_path = root / "validation/START_PACKAGE_VALIDATION_REPORT.json"
    receipt_path = (
        root / "validation/START_PACKAGE_VALIDATION_REPORT_RECEIPT.json"
    )
    if not report_path.is_file() or not receipt_path.is_file():
        return [{
            "code": "VALIDATION_REPORT_RECEIPT_MISSING",
            "message": "validation report or detached receipt is missing",
        }]
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        package = json.loads(
            (root / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8")
        )
        frozen_ir = json.loads(
            (root / "canonical_sources/FROZEN_REQUIREMENT_IR.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [{
            "code": "VALIDATION_REPORT_EXTERNAL_AUTHORITY_MISMATCH",
            "message": str(exc),
        }]
    binding = policy.get("validation_report_binding")
    receipt_fields = {
        "schema_version", "receipt_id", "report_ref", "report_sha256",
        "report_id", "program_id", "package_id", "candidate_version",
        "requirement_epoch", "requirement_ir_sha256",
        "authority_provenance", "external_authority_checks_sha256",
        "binding_authority", "receipt_sha256",
    }
    provenance_fields = {
        "event_store_revision", "event_store_tip_sha256",
        "requirement_epoch", "source_registry_sha256",
        "requirement_ir_sha256",
    }
    external_fields = {
        "check_id", "status", "finding_count", "evidence_refs",
        "authority_input", "authority_provenance",
    }
    external_checks = sorted(
        [
            check for check in report.get("checks", [])
            if isinstance(check, dict)
            and str(check.get("check_id") or "").startswith("FACTORY_EXTERNAL_")
        ],
        key=lambda check: str(check.get("check_id") or ""),
    ) if isinstance(report, dict) else []
    expected_ids = {
        "FACTORY_EXTERNAL_SOURCE_AUTHORITY_ORACLE": (
            "FACTORY_EVENT_STORE_SOURCE_REGISTRY"
        ),
        "FACTORY_EXTERNAL_RELEASE_HISTORY_ORACLE": (
            "FACTORY_EVENT_STORE_REQUIREMENT_IR"
        ),
    }
    invalid = (
        not isinstance(binding, Mapping)
        or binding.get("report_sha256") != file_hash(report_path)
        or binding.get("receipt_sha256") != file_hash(receipt_path)
        or not isinstance(receipt, dict)
        or set(receipt) != receipt_fields
        or receipt.get("schema_version") != "1.0"
        or receipt.get("receipt_id")
        != "START_PACKAGE_VALIDATION_REPORT_RECEIPT"
        or receipt.get("report_ref")
        != "validation/START_PACKAGE_VALIDATION_REPORT.json"
        or receipt.get("report_sha256") != file_hash(report_path)
        or receipt.get("report_id") != report.get("report_id")
        or receipt.get("program_id") != frozen_ir.get("program_id")
        or receipt.get("package_id") != package.get("package_id")
        or receipt.get("candidate_version") != package.get("candidate_version")
        or receipt.get("requirement_epoch") != package.get("requirement_epoch")
        or receipt.get("requirement_ir_sha256")
        != report.get("requirement_ir_sha256")
        or receipt.get("binding_authority")
        != "FACTORY_EVENT_STORE_AND_RECEIVER_SIGNED_SOURCE_AUTHORITY_POLICY"
        or receipt.get("receipt_sha256")
        != json_hash({
            key: value for key, value in receipt.items()
            if key != "receipt_sha256"
        })
        or not isinstance(receipt.get("authority_provenance"), dict)
        or set(receipt["authority_provenance"]) != provenance_fields
        or len(external_checks) != 2
        or {check.get("check_id") for check in external_checks}
        != set(expected_ids)
        or any(
            set(check) != external_fields
            or check.get("status") != "PASS"
            or check.get("finding_count") != 0
            or check.get("authority_input")
            != expected_ids.get(check.get("check_id"))
            or check.get("authority_provenance")
            != receipt.get("authority_provenance")
            for check in external_checks
        )
        or receipt.get("external_authority_checks_sha256")
        != json_hash(external_checks)
    )
    return ([{
        "code": "VALIDATION_REPORT_EXTERNAL_AUTHORITY_MISMATCH",
        "message": (
            "report, detached receipt, or receiver-signed report binding drifted"
        ),
    }] if invalid else [])


def check_source_authority_policy_context(
    frozen_ir: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> list[dict[str, str]]:
    target = frozen_ir.get("target")
    epochs = [
        active.get("requirement_epoch")
        for value in target.values()
        if isinstance(target, Mapping)
        and isinstance(value, Mapping)
        and isinstance((active := value.get("active_epochs")), Mapping)
        and isinstance(active.get("requirement_epoch"), int)
    ] if isinstance(target, Mapping) else []
    issuer = policy.get("issuer_binding")
    if (
        not isinstance(issuer, Mapping)
        or issuer.get("program_id") != frozen_ir.get("program_id")
        or issuer.get("requirement_epoch") != max(epochs, default=0)
    ):
        return [{
            "code": "SOURCE_AUTHORITY_POLICY_CONTEXT_INVALID",
            "message": "signed Program ID or Requirement Epoch is not current",
        }]
    return []


def check_release_history_authority(
    frozen_ir: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Standalone Oracle: external signed history, never Candidate agreement."""

    target = frozen_ir.get("target")
    authoritative = policy.get("release_history")
    if not isinstance(target, Mapping) or not isinstance(authoritative, list):
        return [{
            "code": "RELEASE_HISTORY_AUTHORITY_INVALID",
            "message": "target or signed release history is missing",
        }]
    candidate_entries: list[dict[str, Any]] = []
    for requirement_key, raw in sorted(target.items()):
        if not isinstance(raw, Mapping) or raw.get(
            "replacement_identity_cross_check_required"
        ) is not True:
            continue
        active = raw.get("active_epochs")
        successor = raw.get("successor_binding")
        candidate_entries.append({
            "requirement_key": str(requirement_key),
            "closure_requirement_epoch": (
                active.get("requirement_epoch")
                if isinstance(active, Mapping) else None
            ),
            "superseded_candidate": raw.get("superseded_candidate"),
            "replacement_candidate": raw.get("replacement_candidate"),
            "successor_candidate_version": (
                successor.get("candidate_version")
                if isinstance(successor, Mapping) else None
            ),
        })
    candidate_entries.sort(
        key=lambda item: (
            item.get("closure_requirement_epoch", -1),
            item.get("requirement_key", ""),
        )
    )
    if candidate_entries != authoritative:
        return [{
            "code": "RELEASE_HISTORY_AUTHORITY_MISMATCH",
            "message": (
                "Candidate successor history differs from receiver-pinned "
                "signed release history"
            ),
        }]
    return []


def epoch24_route_is_complete(remediation: Mapping[str, Any]) -> bool:
    route = remediation.get("producer_validator_route_contract")
    required = (
        "epoch23_requirements_consumed_by_producer",
        "epoch23_requirements_consumed_by_standalone",
        "epoch23_requirements_consumed_by_factory_validator",
    )
    return isinstance(route, Mapping) and all(
        route.get(field) is True for field in required
    )


def check_epoch24_route_and_missing_policy_attacks(
    root: Path,
    remediation: Mapping[str, Any],
) -> set[str]:
    """Prove the real route and external-input gates reject omissions."""

    rejected: set[str] = set()
    mutated = json.loads(json.dumps(remediation))
    route = mutated.get("producer_validator_route_contract")
    if isinstance(route, dict):
        route.pop("epoch23_requirements_consumed_by_producer", None)
    if epoch24_route_is_complete(remediation) and not epoch24_route_is_complete(
        mutated
    ):
        rejected.add("EPOCH23_PRODUCER_VALIDATOR_ROUTE_OMITTED")

    supplied = os.environ.pop("HF_SOURCE_AUTHORITY_POLICY_LOCK", None)
    try:
        policy, findings = load_receiver_source_authority_policy(root)
    finally:
        if supplied is not None:
            os.environ["HF_SOURCE_AUTHORITY_POLICY_LOCK"] = supplied
    if policy is None and {item.get("code") for item in findings} == {
        "SOURCE_AUTHORITY_POLICY_LOCK_REQUIRED"
    }:
        rejected.add("MISSING_RECEIVER_SOURCE_AUTHORITY_POLICY_LOCK")
    return rejected


def check_epoch24_synchronized_normalization_attack(
    frozen_ir: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    source_policy: Mapping[str, Any] | None,
) -> bool:
    """Use the real external-policy Oracle against two synchronized rewrites."""

    if source_policy is None:
        return False
    mutated_manifest = json.loads(json.dumps(source_manifest))
    mutated_frozen = json.loads(json.dumps(frozen_ir))
    manifest_sources = mutated_manifest.get("sources")
    frozen_sources = mutated_frozen.get("sources")
    if not (
        isinstance(manifest_sources, list)
        and manifest_sources
        and isinstance(frozen_sources, list)
        and frozen_sources
    ):
        return False
    manifest_sources[0]["authority_level"] = "HUMAN_PROVIDED"
    manifest_sources[0]["declared_authority_level"] = None
    frozen_sources[0]["authority_level"] = "HUMAN_PROVIDED"
    return bool(check_source_authority_normalization(source_policy, mutated_manifest))


def check_epoch24_gate_adversarial_cases(
    root: Path,
    frozen_ir: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    source_policy: Mapping[str, Any] | None,
) -> list[dict[str, str]]:
    target = frozen_ir.get("target")
    remediation = (
        target.get("v0_24_human_review_remediation")
        if isinstance(target, Mapping)
        else None
    )
    if not isinstance(remediation, Mapping):
        return [{"code": "V2_9_EPOCH24_GATE_ADVERSARIAL_CASES_INVALID", "message": "missing remediation"}]
    rejected = check_epoch24_route_and_missing_policy_attacks(root, remediation)
    expected = set(remediation.get("required_gate_adversarial_cases") or [])
    if source_policy is None:
        missing_authority_expected = {
            "EPOCH23_PRODUCER_VALIDATOR_ROUTE_OMITTED",
            "MISSING_RECEIVER_SOURCE_AUTHORITY_POLICY_LOCK",
        }
        if rejected != expected & missing_authority_expected:
            return [{"code": "V2_9_EPOCH24_GATE_ADVERSARIAL_CASES_INVALID", "message": f"expected_without_authority={sorted(expected & missing_authority_expected)} rejected={sorted(rejected)}"}]
        return []
    if check_epoch24_synchronized_normalization_attack(
        frozen_ir, source_manifest, source_policy
    ):
        rejected.add("SYNCHRONIZED_AUTHORITY_NORMALIZATION_RECOMPUTATION")
    if rejected != expected:
        return [{"code": "V2_9_EPOCH24_GATE_ADVERSARIAL_CASES_INVALID", "message": f"expected={sorted(expected)} rejected={sorted(rejected)}"}]
    return []


def check_epoch26_portable_index_adversarial_cases(
    root: Path,
    frozen_ir: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
) -> list[dict[str, str]]:
    target = frozen_ir.get("target")
    remediation = (
        target.get("v0_26_human_review_remediation")
        if isinstance(target, Mapping)
        else None
    )
    if not isinstance(remediation, Mapping):
        return []
    rejected: set[str] = set()
    if check_epoch26_portable_index_attack(root, source_manifest):
        rejected.add("PORTABLE_SOURCE_INDEX_SYNCHRONIZED_REHASH_TAMPER")
    expected = set(
        remediation.get("required_standalone_adversarial_cases") or []
    )
    if rejected != expected:
        return [{
            "code": "V2_9_EPOCH26_PORTABLE_INDEX_ADVERSARIAL_CASES_INVALID",
            "message": f"expected={sorted(expected)} rejected={sorted(rejected)}",
        }]
    return []


def closure_finding_ids(closure: Mapping[str, Any]) -> list[str]:
    finding_ids = closure.get("finding_ids")
    if isinstance(finding_ids, list):
        return [str(value) for value in finding_ids]
    finding_id = closure.get("finding_id")
    return [str(finding_id)] if finding_id else []


def check_closure_receipt(
    root: Path,
    frozen_ir: Mapping[str, Any],
    provenance: Mapping[str, Any],
    matrix: Mapping[str, Any],
    receipt: Mapping[str, Any],
    package_identity: Mapping[str, Any],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    requirements = closure_requirements(frozen_ir)
    expected_keys = [key for key, _closure in requirements]
    entries = receipt.get("closures")
    if not isinstance(entries, list):
        return [{"code": "HUMAN_REVIEW_CLOSURE_RECEIPT_INVALID", "message": "closures must be a list"}]
    by_key = {
        str(entry.get("requirement_key")): entry
        for entry in entries
        if isinstance(entry, Mapping)
    }
    target = frozen_ir.get("target")
    epoch38_local_profile = bool(
        isinstance(target, Mapping)
        and target.get("requirement_epoch") == 38
        and target.get("architecture_epoch") == 4
        and target.get("control_plane_epoch") == 4
        and target.get("assurance_profile_id")
        == "SELF_USE_LOCAL_TRUSTED_OPERATOR"
        and target.get("operating_assurance_profile")
        == "SELF_USE_LOCAL_TRUSTED_OPERATOR"
    )
    if (
        receipt.get("receipt_id") != "HUMAN_REVIEW_CLOSURE_RECEIPT"
        or receipt.get("closure_scope") != "CANDIDATE_STATIC_CONTRACT"
        or receipt.get("lifecycle_status_source")
        != "THIS_RECEIPT_NOT_IMMUTABLE_REQUIREMENT_DECLARATION"
        or receipt.get("source_requirement_ir_sha256")
        != provenance.get("requirement_ir_sha256")
        or receipt.get("portable_requirement_ir_sha256") != json_hash(frozen_ir)
        or receipt.get("closure_count") != len(requirements)
        or sorted(by_key) != expected_keys
        or receipt.get("status")
        != (
            "NOT_APPLICABLE_NO_CLOSURES"
            if epoch38_local_profile
            else "PASS"
        )
        or (
            epoch38_local_profile
            and (
                requirements
                or receipt.get("closure_claimed") is not False
                or receipt.get("human_review_approved") is not False
            )
        )
        or receipt.get("runtime_claims_verified") is not False
        or receipt.get("workpack_execution_authorized") is not False
        or receipt.get("program_driver_started") is not False
        or matrix.get("status") != "PASS"
    ):
        findings.append(
            {
                "code": "HUMAN_REVIEW_CLOSURE_RECEIPT_INVALID",
                "message": "receipt identity, requirement binding, nonclaims, or matrix gate is invalid",
            }
        )
    for requirement_key, closure in requirements:
        if closure_requirement_status(closure) != CLOSURE_DECLARATION_STATUS:
            findings.append(
                {
                    "code": "HUMAN_REVIEW_LIFECYCLE_STATE_IN_FROZEN_IR",
                    "message": requirement_key,
                }
            )
        entry = by_key.get(requirement_key)
        required_closures = list(closure.get("required_closures") or [])
        expected_ids = closure_finding_ids(closure)
        successor = closure.get("successor_binding")
        successor_version = (
            successor.get("candidate_version")
            if isinstance(successor, Mapping)
            else None
        )
        active_epochs = closure.get("active_epochs")
        closure_epoch = (
            active_epochs.get("requirement_epoch")
            if isinstance(active_epochs, Mapping)
            else None
        )
        identity_cross_check = closure.get(
            "replacement_identity_cross_check_required"
        ) is True
        replacement_identity_invalid = identity_cross_check and (
            not isinstance(entry, Mapping)
            or not isinstance(successor_version, str)
            or closure.get("replacement_candidate")
            != f"candidate-{successor_version}"
            or not isinstance(closure_epoch, int)
            or entry.get("replacement_candidate_version") != successor_version
            or entry.get("closure_requirement_epoch") != closure_epoch
            or entry.get("current_package_id") != package_identity.get("package_id")
            or entry.get("current_package_candidate_version")
            != package_identity.get("candidate_version")
            or entry.get("current_package_requirement_epoch")
            != package_identity.get("requirement_epoch")
            or not isinstance(package_identity.get("requirement_epoch"), int)
            or package_identity.get("requirement_epoch") < closure_epoch
        )
        if (
            not isinstance(entry, Mapping)
            or entry.get("finding_ids") != expected_ids
            or entry.get("superseded_candidate")
            != closure.get("superseded_candidate")
            or entry.get("replacement_candidate")
            != closure.get("replacement_candidate")
            or entry.get("required_closures") != required_closures
            or entry.get("required_closures_sha256")
            != json_hash(required_closures)
            or entry.get("closure_requirement_kind")
            != closure.get("closure_requirement_kind", "HUMAN_REVIEW_REMEDIATION")
            or entry.get("requirement_sha256") != json_hash(closure)
            or entry.get("status") != "PASS"
            or replacement_identity_invalid
        ):
            findings.append(
                {
                    "code": "HUMAN_REVIEW_CLOSURE_RECEIPT_INVALID",
                    "message": requirement_key,
                }
            )
            continue
        evidence_refs = entry.get("evidence_refs")
        evidence_hashes = entry.get("evidence_sha256")
        if not isinstance(evidence_refs, list) or not isinstance(
            evidence_hashes, Mapping
        ):
            findings.append(
                {
                    "code": "HUMAN_REVIEW_CLOSURE_RECEIPT_INVALID",
                    "message": f"{requirement_key}: evidence bindings missing",
                }
            )
            continue
        if any("DAG" in finding_id for finding_id in expected_ids) and not {
            "ENGINEERING_PROJECT_DAG.json",
            "validation/DAG_PATH_CONTAINMENT_MATRIX.json",
        }.issubset(set(evidence_refs)):
            findings.append(
                {
                    "code": "HUMAN_REVIEW_CLOSURE_RECEIPT_INVALID",
                    "message": f"{requirement_key}: DAG evidence missing",
                }
            )
        if any(
            "BINDER" in finding_id or "SETUP_RUNTIME" in finding_id
            for finding_id in expected_ids
        ) and not {
            "tools/setup_runtime.py",
            "validation/RUNTIME_BINDING_CONTRACT.json",
        }.issubset(set(evidence_refs)):
            findings.append(
                {
                    "code": "HUMAN_REVIEW_CLOSURE_RECEIPT_INVALID",
                    "message": f"{requirement_key}: Runtime Binder evidence missing",
                }
            )
        for relative in evidence_refs:
            path = root / str(relative)
            if (
                Path(str(relative)).is_absolute()
                or ".." in Path(str(relative)).parts
                or not path.is_file()
                or evidence_hashes.get(relative) != file_hash(path)
            ):
                findings.append(
                    {
                        "code": "HUMAN_REVIEW_CLOSURE_RECEIPT_INVALID",
                        "message": f"{requirement_key}: {relative}",
                    }
                )
    return findings


def without_hash(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    projected = dict(value)
    projected.pop(field, None)
    return projected


def correction_implementation_refs(correction_id: str) -> list[str]:
    refs = {
        "CORR-29-001": ["FACTORY_PROVENANCE.json", "canonical_sources/FROZEN_REQUIREMENT_IR.json", "V2_9_CONTROL_KERNEL_MANIFEST.json"],
        "CORR-29-002": ["DECISION_POLICY.json", "TRANSITION_CONTRACTS.json", "tools/harness_foundry_runtime/control_kernel.py"],
        "CORR-29-003": ["V2_9_CONTROL_KERNEL_MANIFEST.json", "tools/harness_foundry_runtime/store.py", "tools/harness_foundry_runtime/control_kernel.py"],
        "CORR-29-004": ["AUTHORIZATION_POLICY.json", "TRANSITION_CONTRACTS.json", "contracts/v2_9/PARENT_AUTHORIZATION.schema.json", "contracts/v2_9/DERIVED_GRANT.schema.json", "tools/harness_foundry_runtime/control_kernel.py"],
        "CORR-29-005": ["ASSURANCE_PROFILE.json", "tools/harness_foundry_runtime/requirement_completion.py"],
        "CORR-29-006": ["contracts/v2_9/MINIMUM_REQUIREMENT_COMPLETION.schema.json", "tools/harness_foundry_runtime/requirement_completion.py"],
        "CORR-29-007": ["ASSURANCE_PROFILE.json", "tools/harness_foundry_runtime/requirement_completion.py"],
        "CORR-29-008": ["FACTORY_PROVENANCE.json", "canonical_sources/SOURCE_MANIFEST.json", "validation/PORTABILITY_MANIFEST.json", "tools/setup_runtime.py"],
    }
    return list(refs.get(correction_id, []))


def expected_native_control_store_contract() -> dict[str, Any]:
    columns = {
        "control_events": [
            ("sequence", "INTEGER", False, 1),
            ("event_id", "TEXT", True, 0),
            ("program_id", "TEXT", True, 0),
            ("stream_revision", "INTEGER", True, 0),
            ("event_type", "TEXT", True, 0),
            ("payload_json", "TEXT", True, 0),
            ("previous_event_hash", "TEXT", False, 0),
            ("event_hash", "TEXT", True, 0),
            ("created_at", "TEXT", True, 0),
        ],
        "control_idempotency": [
            ("program_id", "TEXT", True, 1),
            ("idempotency_key", "TEXT", True, 2),
            ("request_sha256", "TEXT", True, 0),
            ("events_json", "TEXT", True, 0),
            ("created_at", "TEXT", True, 0),
        ],
    }
    contract = {
        "schema_version": "2.9",
        "authority_model": "SINGLE_APPEND_ONLY_SQLITE_CONTROL_EVENT_STORE",
        "tables": {
            table: [
                {
                    "name": name,
                    "type": column_type,
                    "not_null": not_null,
                    "primary_key_position": primary_key_position,
                }
                for name, column_type, not_null, primary_key_position in rows
            ]
            for table, rows in columns.items()
        },
        "append_only_triggers": {
            "control_events_reject_update": "CREATE TRIGGER control_events_reject_update BEFORE UPDATE ON control_events BEGIN SELECT RAISE(ABORT, 'control_events is append-only'); END",
            "control_events_reject_delete": "CREATE TRIGGER control_events_reject_delete BEFORE DELETE ON control_events BEGIN SELECT RAISE(ABORT, 'control_events is append-only'); END",
        },
        "preexisting_store_policy": "REJECT_BEFORE_SCHEMA_OR_JOURNAL_MUTATION",
    }
    contract["schema_contract_sha256"] = json_hash(contract)
    return contract


def check_control_kernel(
    root: Path,
    frozen_ir: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    target = frozen_ir.get("target")
    if not (
        isinstance(target, Mapping)
        and target.get("architecture_epoch") == 1
        and target.get("control_plane_epoch") == 1
    ):
        return findings
    correction = target.get("control_plane_architecture_correction") if isinstance(target, Mapping) else None
    traceability = correction.get("correction_traceability") if isinstance(correction, Mapping) else None
    if not isinstance(traceability, Mapping) or traceability.get("required") is not True:
        return findings
    paths = {
        "manifest": "V2_9_CONTROL_KERNEL_MANIFEST.json",
        "policy": "DECISION_POLICY.json",
        "profile": "ASSURANCE_PROFILE.json",
        "graph": "CONTROL_PLANE_PROGRAM_GRAPH.json",
        "transitions": "TRANSITION_CONTRACTS.json",
        "correction": "canonical_sources/CORRECTION_COVERAGE_MATRIX.json",
        "atoms": "canonical_sources/NORMATIVE_ATOM_CATALOG.json",
        "coverage": "canonical_sources/ATOM_COVERAGE_MATRIX.json",
    }
    integration = (
        target.get("v0_11_execution_integration_correction")
        if isinstance(target, Mapping)
        else None
    )
    if isinstance(integration, Mapping):
        paths.update(
            {
                "result_schema": "contracts/v2_9/TRANSITION_RESULT.schema.json",
                "adapter_schema": "contracts/v2_9/ADAPTER_BINDING.schema.json",
                "store_activation_schema": "contracts/v2_9/CONTROL_EVENT_STORE_ACTIVATION.schema.json",
                "adapter_binding": "PROFILE_READ_VALIDATION_ADAPTER_BINDING.json",
                "store_activation": "CONTROL_EVENT_STORE_ACTIVATION_CONTRACT.json",
            }
        )
    try:
        documents = {
            key: json.loads((root / relative).read_text(encoding="utf-8"))
            for key, relative in paths.items()
        }
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [{"code": "V2_9_CONTROL_KERNEL_MANIFEST_INVALID", "message": str(exc)}]
    manifest = documents["manifest"]
    policy = documents["policy"]
    profile = documents["profile"]
    graph = documents["graph"]
    transitions = documents["transitions"]
    matrix = documents["correction"]
    module_hashes = manifest.get("runtime_module_sha256")
    schema_hashes = manifest.get("schema_sha256")
    expected_modules = {
        "tools/harness_foundry_runtime/" + name for name in (
            "__init__.py", "constants.py", "models.py", "store.py", "control_kernel.py",
            "local_runtime.py", "local_process.py", "startup_runtime.py", "requirement_completion.py",
        )
    }
    actual_schemas = {
        path.relative_to(root).as_posix()
        for path in (root / "contracts/v2_9").glob("*.json")
        if path.is_file()
    }
    if (
        manifest.get("manifest_sha256") != json_hash(without_hash(manifest, "manifest_sha256"))
        or manifest.get("architecture_epoch") != 1
        or manifest.get("control_plane_epoch") != 1
        or manifest.get("persistent_authority") != "SINGLE_APPEND_ONLY_SQLITE_CONTROL_EVENT_STORE"
        or manifest.get("parent_authorization_status") != "NOT_GRANTED"
        or manifest.get("derived_grant_count") != 0
        or manifest.get("execution_started") is not False
        or manifest.get("status") != "FROZEN_IMPLEMENTATION_READY_NOT_AUTHORIZED"
        or manifest.get("architecture_lock_proposal_sha256") != correction.get("architecture_lock_proposal_sha256")
        or manifest.get("correction_coverage_ref") != paths["correction"]
        or manifest.get("correction_coverage_sha256") != file_hash(root / paths["correction"])
        or not isinstance(module_hashes, Mapping)
        or not isinstance(schema_hashes, Mapping)
    ):
        findings.append({"code": "V2_9_CONTROL_KERNEL_MANIFEST_INVALID", "message": "manifest authority or semantic binding is invalid"})
    if not isinstance(module_hashes, Mapping) or set(module_hashes) != expected_modules:
        findings.append({"code": "V2_9_CONTROL_KERNEL_MODULE_HASH_INVALID", "message": "runtime module inventory differs"})
    else:
        for relative, digest in module_hashes.items():
            if digest != file_hash(root / relative):
                findings.append({"code": "V2_9_CONTROL_KERNEL_MODULE_HASH_INVALID", "message": relative})
    if not isinstance(schema_hashes, Mapping) or set(schema_hashes) != actual_schemas:
        findings.append({"code": "V2_9_CONTROL_KERNEL_SCHEMA_HASH_INVALID", "message": "schema inventory differs"})
    else:
        for relative, digest in schema_hashes.items():
            if digest != file_hash(root / relative):
                findings.append({"code": "V2_9_CONTROL_KERNEL_SCHEMA_HASH_INVALID", "message": relative})

    evaluator = "tools/harness_foundry_runtime/control_kernel.py"
    expected_precedence = ["PLATFORM_SAFETY", "FROZEN_CHARTER", "FROZEN_REQUIREMENT", "ARCHITECTURE_POLICY", "TRANSITION_LOCAL"]
    if (
        policy.get("status") != "FROZEN"
        or policy.get("rule_language_id") != "HF29_DETERMINISTIC_JSON_RULES"
        or policy.get("rule_language_version") != "1.0"
        or policy.get("evaluator_ref") != f"harness-resource://candidate/{evaluator}"
        or policy.get("evaluator_sha256") != file_hash(root / evaluator)
        or policy.get("precedence") != expected_precedence
        or policy.get("conflict_policy") != "FAIL_CLOSED_POLICY_CONFLICT"
        or policy.get("unknown_policy") != "FAIL_CLOSED_POLICY_UNKNOWN"
    ):
        findings.append({"code": "V2_9_CONTROL_KERNEL_POLICY_INVALID", "message": "Decision Policy binding is invalid"})
    contracts = transitions.get("contracts")
    expected_kinds = {"READ_ONLY_VALIDATION", "INTERNAL_STATE_TRANSACTION", "BOUNDED_REVERSIBLE_FIXTURE_ACTION"}
    if (
        transitions.get("status") != "FROZEN_NOT_EXECUTED"
        or not isinstance(contracts, list)
        or transitions.get("contracts_sha256") != json_hash(contracts or [])
        or {item.get("node_kind") for item in contracts or [] if isinstance(item, Mapping)} != expected_kinds
        or any(
            item.get("decision_policy_sha256") != file_hash(root / paths["policy"])
            or item.get("rule_evaluator_sha256") != file_hash(root / evaluator)
            or item.get("required_authorization_class") != "PARENT_RISK_ENVELOPE"
            or item.get("execution_status") != "PLANNED_NOT_AUTHORIZED"
            for item in contracts or [] if isinstance(item, Mapping)
        )
    ):
        findings.append({"code": "V2_9_CONTROL_KERNEL_POLICY_INVALID", "message": "Transition Contract binding is invalid"})
    if isinstance(integration, Mapping):
        result_schema = documents["result_schema"]
        adapter = documents["adapter_binding"]
        activation = documents["store_activation"]
        result_statuses = (
            result_schema.get("properties", {}).get("status", {}).get("enum")
            if isinstance(result_schema, Mapping)
            else None
        )
        reason_condition = result_schema.get("allOf") if isinstance(result_schema, Mapping) else None
        profile_transition = next(
            (
                item
                for item in contracts or []
                if isinstance(item, Mapping)
                and item.get("transition_id") == "PROFILE_READ_VALIDATION"
            ),
            None,
        )
        command_contract = (
            profile_transition.get("command_contract")
            if isinstance(profile_transition, Mapping)
            else None
        )
        expected_statuses = [
            "PASS",
            "VALIDATION_FAILED",
            "TEMPORARY_FAILURE",
            "UNKNOWN_SIDE_EFFECT",
        ]
        kernel_source = (root / evaluator).read_text(encoding="utf-8")
        if (
            result_statuses != expected_statuses
            or not isinstance(reason_condition, list)
            or not any(
                isinstance(item, Mapping)
                and item.get("if", {}).get("properties", {}).get("status", {}).get("const") == "VALIDATION_FAILED"
                and "reason_code" in item.get("then", {}).get("required", [])
                for item in reason_condition
            )
            or "DETERMINISTIC_VALIDATION_FAILURE" not in kernel_source
            or '"outcome": "VALIDATION_FAILED"' not in kernel_source
            or 'if status == "VALIDATION_FAILED"' not in kernel_source
        ):
            findings.append({"code": "V2_9_DETERMINISTIC_FAILURE_CONTRACT_INVALID", "message": "deterministic non-retry failure semantics are not exact"})
        adapter_required_nulls = (
            adapter.get("implementation_ref"),
            adapter.get("implementation_sha256"),
            adapter.get("entrypoint"),
            adapter.get("runtime_transition_contract_sha256"),
        )
        if (
            adapter.get("binding_status") != "PLANNED_NOT_BOUND"
            or any(value is not None for value in adapter_required_nulls)
            or adapter.get("candidate_materializes_adapter") is not False
            or adapter.get("execution_started") is not False
            or adapter.get("result_schema_ref") != f"harness-resource://candidate/{paths['result_schema']}"
            or adapter.get("result_schema_sha256") != file_hash(root / paths["result_schema"])
            or adapter.get("derived_grant_binding_requirement") != "RUNTIME_TRANSITION_CONTRACT_SHA256_REQUIRED"
            or adapter.get("binding_contract_sha256") != json_hash(without_hash(adapter, "binding_contract_sha256"))
            or manifest.get("adapter_binding_ref") != paths["adapter_binding"]
            or manifest.get("adapter_binding_sha256") != file_hash(root / paths["adapter_binding"])
            or not isinstance(command_contract, Mapping)
            or command_contract.get("adapter_binding_ref") != f"harness-resource://candidate/{paths['adapter_binding']}"
            or command_contract.get("adapter_binding_sha256") != file_hash(root / paths["adapter_binding"])
            or command_contract.get("runtime_transition_contract_sha256") is not None
            or profile_transition.get("result_schema_sha256") != file_hash(root / paths["result_schema"])
        ):
            findings.append({"code": "V2_9_ADAPTER_BINDING_INVALID", "message": "planned Adapter Binding is not exact or invents Runtime authority"})
        expected_store = expected_native_control_store_contract()
        store_source = (
            root / "tools/harness_foundry_runtime/store.py"
        ).read_text(encoding="utf-8")
        bootstrap = activation.get("bootstrap_import")
        if (
            activation.get("activation_status") != "PLANNED_NOT_ACTIVATED"
            or activation.get("active_store_ref") != "harness-resource://execution/.harness-foundry/control/v2_9/control_event_store.sqlite3"
            or activation.get("implementation_ref") != f"{CANDIDATE_URI}/tools/harness_foundry_runtime/store.py"
            or activation.get("implementation_sha256") != file_hash(root / "tools/harness_foundry_runtime/store.py")
            or activation.get("schema_ref") != f"harness-resource://candidate/{paths['store_activation_schema']}"
            or activation.get("schema_sha256") != file_hash(root / paths["store_activation_schema"])
            or activation.get("native_schema_contract") != expected_store
            or activation.get("native_schema_contract_sha256") != expected_store["schema_contract_sha256"]
            or activation.get("preexisting_incompatible_store_policy") != "REJECT_BEFORE_SCHEMA_OR_JOURNAL_MUTATION"
            or activation.get("append_only_update_delete_triggers_required") is not True
            or activation.get("ad_hoc_same_filename_store_reuse_forbidden") is not True
            or not isinstance(bootstrap, Mapping)
            or bootstrap.get("status") != "PLANNED_NOT_EXECUTED"
            or bootstrap.get("separate_migration_authorization_required") is not True
            or bootstrap.get("migration_authorization_status") != "NOT_GRANTED"
            or bootstrap.get("historical_v0_11_event_hash") != integration.get("native_control_event_store_activation_contract", {}).get("historical_v0_11_event_hash")
            or activation.get("active_authority_count_after_activation") != 1
            or activation.get("store_created") is not False
            or activation.get("store_migrated") is not False
            or activation.get("execution_started") is not False
            or activation.get("contract_sha256") != json_hash(without_hash(activation, "contract_sha256"))
            or manifest.get("control_event_store_activation_contract_ref") != paths["store_activation"]
            or manifest.get("control_event_store_activation_contract_sha256") != file_hash(root / paths["store_activation"])
            or manifest.get("control_event_store_activation_status") != "PLANNED_NOT_ACTIVATED"
            or manifest.get("bootstrap_import_status") != "PLANNED_NOT_EXECUTED"
            or "def _require_exact_existing_schema" not in store_source
            or "control_events_reject_update" not in store_source
            or "control_events_reject_delete" not in store_source
        ):
            findings.append({"code": "V2_9_CONTROL_EVENT_STORE_ACTIVATION_INVALID", "message": "native Event Store activation or immutable schema binding is invalid"})
    nodes = graph.get("nodes")
    if (
        graph.get("status") != "INSTANTIATED_NOT_EXECUTED"
        or graph.get("program_graph_sha256") != json_hash(without_hash(graph, "program_graph_sha256"))
        or not isinstance(nodes, list)
        or {item.get("node_kind") for item in nodes if isinstance(item, Mapping)} != expected_kinds
        or graph.get("profile_sha256") != file_hash(root / paths["profile"])
        or profile.get("status") != "FROZEN"
        or profile.get("program_graph_template_id") != graph.get("program_graph_template_id")
    ):
        findings.append({"code": "V2_9_CONTROL_KERNEL_POLICY_INVALID", "message": "Profile or Program Graph binding is invalid"})

    expected_ids = [str(value) for value in traceability.get("expected_correction_ids", [])]
    raw_requirements = correction.get("correction_requirements")
    declarations = {str(item.get("correction_id")): item for item in raw_requirements or [] if isinstance(item, Mapping) and item.get("correction_id")}
    rows = matrix.get("rows")
    row_by_id = {str(item.get("correction_id")): item for item in rows or [] if isinstance(item, Mapping) and item.get("correction_id")}
    coverage_by_atom = {str(item.get("atom_id")): item for item in documents["coverage"].get("coverage", []) if isinstance(item, Mapping) and item.get("atom_id")}
    atom_ids = {str(item.get("atom_id")) for item in documents["atoms"].get("atoms", []) if isinstance(item, Mapping) and item.get("atom_id")}
    invalid_matrix = (
        not isinstance(raw_requirements, list)
        or len(declarations) != len(raw_requirements)
        or list(declarations) != expected_ids
        or not isinstance(rows, list)
        or len(row_by_id) != len(rows)
        or list(row_by_id) != expected_ids
        or matrix.get("expected_correction_ids") != expected_ids
        or matrix.get("correction_count") != len(expected_ids)
        or matrix.get("candidate_static_status") != "PASS"
        or matrix.get("runtime_evidence_status") != "PENDING_UNTIL_AUTHORIZED_EXECUTION"
        or matrix.get("execution_started") is not False
        or matrix.get("matrix_sha256") != json_hash(without_hash(matrix, "matrix_sha256"))
    )
    for correction_id in expected_ids:
        declaration = declarations.get(correction_id, {})
        row = row_by_id.get(correction_id, {})
        maps_to = [str(value) for value in declaration.get("maps_to", [])]
        expected_coverage = []
        for atom_id in maps_to:
            edge = coverage_by_atom.get(atom_id, {})
            expected_coverage.append({"atom_id": atom_id, "workpack_ids": list(edge.get("workpack_ids") or []), "stage_ids": list(edge.get("stage_ids") or []), "release_step_ids": list(edge.get("release_step_ids") or []), "owner_project_ids": list(edge.get("owner_project_ids") or []), "coverage_status": edge.get("status")})
        refs = correction_implementation_refs(correction_id)
        invalid_matrix = invalid_matrix or (
            not maps_to
            or len(set(maps_to)) != len(maps_to)
            or any(atom_id not in atom_ids or atom_id not in coverage_by_atom for atom_id in maps_to)
            or row.get("requirement") != declaration.get("requirement")
            or row.get("maps_to") != maps_to
            or row.get("mapped_atom_coverage") != expected_coverage
            or row.get("implementation_artifact_refs") != refs
            or row.get("validation_refs") != ["tools/self_check.py", "validation/HUMAN_REVIEW_CLOSURE_RECEIPT.json", "validation/START_PACKAGE_VALIDATION_REPORT.json"]
            or row.get("candidate_static_lifecycle") != "MATERIALIZED_AND_HASH_BOUND"
            or row.get("runtime_lifecycle") != "PENDING_UNTIL_AUTHORIZED_EXECUTION"
            or row.get("runtime_evidence_refs") != []
            or row.get("runtime_claims_verified") is not False
            or row.get("row_sha256") != json_hash(without_hash(row, "row_sha256"))
            or any(not (root / relative).is_file() for relative in refs)
        )
    if invalid_matrix:
        findings.append({"code": "V2_9_CORRECTION_COVERAGE_INVALID", "message": "CORR mapping or lifecycle does not match frozen requirements"})
    closure = next((item for item in receipt.get("closures", []) if isinstance(item, Mapping) and item.get("requirement_key") == "human_review_v0_10_closure"), None)
    if isinstance(target.get("human_review_v0_10_closure"), Mapping):
        required = {paths["correction"], paths["manifest"], paths["policy"], paths["profile"], paths["graph"], paths["transitions"], evaluator, "tools/harness_foundry_runtime/requirement_completion.py", "tools/harness_foundry_runtime/store.py", "tools/self_check.py"}
        evidence_refs = set(closure.get("evidence_refs") or []) if isinstance(closure, Mapping) else set()
        evidence_hashes = closure.get("evidence_sha256") if isinstance(closure, Mapping) else None
        if not isinstance(evidence_hashes, Mapping) or not required.issubset(evidence_refs) or any(evidence_hashes.get(relative) != file_hash(root / relative) for relative in required):
            findings.append({"code": "HUMAN_REVIEW_CLOSURE_RECEIPT_INVALID", "message": "v0.10 closure evidence is incomplete"})
    closure_v0_11 = next((item for item in receipt.get("closures", []) if isinstance(item, Mapping) and item.get("requirement_key") == "human_review_v0_11_closure"), None)
    if isinstance(target.get("human_review_v0_11_closure"), Mapping):
        required_v0_11 = {
            paths["manifest"],
            paths["transitions"],
            paths["result_schema"],
            paths["adapter_schema"],
            paths["store_activation_schema"],
            paths["adapter_binding"],
            paths["store_activation"],
            evaluator,
            "tools/harness_foundry_runtime/store.py",
            "tools/self_check.py",
        }
        evidence_refs = set(closure_v0_11.get("evidence_refs") or []) if isinstance(closure_v0_11, Mapping) else set()
        evidence_hashes = closure_v0_11.get("evidence_sha256") if isinstance(closure_v0_11, Mapping) else None
        if not isinstance(evidence_hashes, Mapping) or not required_v0_11.issubset(evidence_refs) or any(evidence_hashes.get(relative) != file_hash(root / relative) for relative in required_v0_11):
            findings.append({"code": "HUMAN_REVIEW_CLOSURE_RECEIPT_INVALID", "message": "v0.11 closure evidence is incomplete"})
    return findings


def epoch2_implementation_refs(correction_id: str) -> list[str]:
    refs = {
        "CORR-29-009": [
            "V2_9_RELEASE_CLOSURE_CONTROL_PLANE_MANIFEST.json",
            "SEMANTIC_IMPLEMENTATION_AUTHORIZATION_IDENTITY_CONTRACT.json",
            "contracts/v2_9_release_closure/IDENTITY_DERIVATION_INPUT.schema.json",
            "contracts/v2_9_release_closure/IDENTITY_BUNDLE.schema.json",
            "contracts/v2_9_release_closure/MACHINE_GRANT_BINDING.schema.json",
            "tools/harness_foundry_runtime/identity_derivation.py",
            "EVENT_STORE_AUTHORITY_ADAPTER_CONTRACT.json",
            "AUTHORITY_TRUST_ROOT.json",
            "contracts/v2_9_release_closure/EVENT_STORE_AUTHORITY_ADAPTER_BINDING.schema.json",
            "contracts/v2_9_release_closure/SOURCE_AUTHORITY_POLICY_LOCK.schema.json",
            "tools/harness_foundry_runtime/authority_adapter.py",
        ],
        "CORR-29-010": [
            "GENERIC_RECOVERY_DECISION_PROTOCOL.json",
            "contracts/v2_9_release_closure/RECOVERY_DECISION.schema.json",
            "tools/harness_foundry_runtime/recovery_decision.py",
        ],
        "CORR-29-011": [
            "COMPLEXITY_GOVERNOR.json",
            "contracts/v2_9_release_closure/COMPLEXITY_DECISION.schema.json",
            "tools/harness_foundry_runtime/complexity_governor.py",
        ],
        "CORR-29-012": [
            "PRODUCT_SAFETY_RELEASE_CLOSURE_GRAPH.json",
            "contracts/v2_9_release_closure/CLOSURE_RECEIPT.schema.json",
            "contracts/v2_9_release_closure/COMPATIBILITY_LINKAGE_RECEIPT.schema.json",
            "contracts/v2_9_release_closure/TRUSTED_RELEASE_CONTEXT.schema.json",
            "contracts/v2_9_release_closure/FINAL_RELEASE_DECISION.schema.json",
            "tools/harness_foundry_runtime/closure_lanes.py",
            "EVENT_STORE_AUTHORITY_ADAPTER_CONTRACT.json",
            "AUTHORITY_TRUST_ROOT.json",
            "contracts/v2_9_release_closure/EVENT_STORE_AUTHORITY_ADAPTER_BINDING.schema.json",
            "tools/harness_foundry_runtime/authority_adapter.py",
        ],
        "CORR-29-013": [
            "EVIDENCE_LIFECYCLE_AND_PROJECTION_CONTRACT.json",
            "contracts/v2_9_release_closure/EVIDENCE_INDEX_ENTRY.schema.json",
            "tools/harness_foundry_runtime/evidence_projection.py",
            "canonical_sources/RELEASE_CLOSURE_CORRECTION_COVERAGE_MATRIX.json",
        ],
    }
    return list(refs.get(correction_id, []))


def standalone_epoch17_adversarial_oracle() -> set[str]:
    """Independent reference oracle; it imports neither Factory nor runtime code."""

    lanes = ("PRODUCT", "SAFETY", "RELEASE")
    linkage_key = "COMPATIBILITY_LINKAGE"
    binding_fields = (
        "authority_scope", "instance_id", "requirement_epoch",
        "semantic_contract_identity_sha256",
        "authorization_risk_identity_sha256",
    )

    def seal(value: Mapping[str, Any], field: str) -> dict[str, Any]:
        body = dict(value)
        body.pop(field, None)
        return {**body, field: json_hash(body)}

    def context(consumed: list[str] | None = None) -> dict[str, Any]:
        body = {
            "schema_version": "2.9",
            "authority_scope": "PROGRAM",
            "instance_id": "INSTANCE-1",
            "requirement_epoch": 17,
            "semantic_contract_identity_sha256": "a" * 64,
            "authorization_risk_identity_sha256": "b" * 64,
            "state_revision": 50,
            "current_state_sha256": "c" * 64,
            "event_store_tip_sha256": "d" * 64,
            "authorized_issuers": {
                key: {
                    "issuer_control_domain_id": f"DOMAIN-{key}",
                    "issuance_event_id": f"EVENT-{key}",
                    "issuance_event_revision": index + 1,
                    "issuance_event_sha256": format(index + 10, "064x"),
                }
                for index, key in enumerate((*lanes, linkage_key))
            },
            "consumed_receipt_ids": list(consumed or []),
        }
        return seal(body, "release_context_sha256")

    def receipt(ctx: Mapping[str, Any], key: str, receipt_id: str) -> dict[str, Any]:
        anchor = ctx["authorized_issuers"][key]
        body = {
            "schema_version": "2.9",
            **({"lane_id": key} if key in lanes else {}),
            "status": "CLOSED" if key in lanes else "PASS",
            **{field: ctx[field] for field in binding_fields},
            "receipt_id": receipt_id,
            **anchor,
            "release_context_sha256": ctx["release_context_sha256"],
            "creates_authority": False,
        }
        anti = {
            field: body[field]
            for field in (
                "receipt_id", "release_context_sha256",
                "issuer_control_domain_id", "issuance_event_id",
                "issuance_event_revision", "issuance_event_sha256",
            )
        }
        body["anti_replay_token"] = json_hash(anti)
        return seal(body, "receipt_sha256")

    def accepts(
        ctx: Mapping[str, Any],
        lane_receipts: list[Mapping[str, Any]],
        linkage: Mapping[str, Any],
        current_tip: str,
    ) -> bool:
        context_body = without_hash(ctx, "release_context_sha256")
        if ctx.get("release_context_sha256") != json_hash(context_body):
            return False
        if current_tip != ctx.get("event_store_tip_sha256"):
            return False
        if {item.get("lane_id") for item in lane_receipts} != set(lanes):
            return False
        all_receipts = [*lane_receipts, linkage]
        ids: set[str] = set()
        tokens: set[str] = set()
        for item in all_receipts:
            kind = item.get("lane_id") or linkage_key
            if item.get("receipt_sha256") != json_hash(without_hash(item, "receipt_sha256")):
                return False
            if any(item.get(field) != ctx.get(field) for field in binding_fields):
                return False
            if item.get("release_context_sha256") != ctx.get("release_context_sha256"):
                return False
            anchor = ctx["authorized_issuers"].get(kind)
            if not isinstance(anchor, Mapping) or any(item.get(field) != value for field, value in anchor.items()):
                return False
            replay_fields = {
                field: item.get(field)
                for field in (
                    "receipt_id", "release_context_sha256",
                    "issuer_control_domain_id", "issuance_event_id",
                    "issuance_event_revision", "issuance_event_sha256",
                )
            }
            if item.get("anti_replay_token") != json_hash(replay_fields):
                return False
            receipt_id = item.get("receipt_id")
            token = item.get("anti_replay_token")
            if receipt_id in ids or receipt_id in ctx["consumed_receipt_ids"] or token in tokens:
                return False
            ids.add(receipt_id)
            tokens.add(token)
        return True

    trusted = context()
    valid_lanes = [receipt(trusted, lane, f"RECEIPT-{lane}") for lane in lanes]
    valid_linkage = receipt(trusted, linkage_key, "RECEIPT-LINKAGE")
    cases: dict[str, tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], str]] = {}

    stale = []
    for item in valid_lanes:
        body = without_hash(item, "receipt_sha256")
        body["requirement_epoch"] = 16
        body["anti_replay_token"] = json_hash({
            field: body[field] for field in (
                "receipt_id", "release_context_sha256", "issuer_control_domain_id",
                "issuance_event_id", "issuance_event_revision", "issuance_event_sha256",
            )
        })
        stale.append(seal(body, "receipt_sha256"))
    cases["UNIFORMLY_STALE_ALL_RECEIPTS"] = (trusted, stale, valid_linkage, "d" * 64)

    forged = []
    for item in valid_lanes:
        body = without_hash(item, "receipt_sha256")
        body["issuance_event_sha256"] = "e" * 64
        body["anti_replay_token"] = json_hash({
            field: body[field] for field in (
                "receipt_id", "release_context_sha256", "issuer_control_domain_id",
                "issuance_event_id", "issuance_event_revision", "issuance_event_sha256",
            )
        })
        forged.append(seal(body, "receipt_sha256"))
    cases["UNIFORMLY_FORGED_ALL_RECEIPTS"] = (trusted, forged, valid_linkage, "d" * 64)

    wrong_issuer = [dict(item) for item in valid_lanes]
    wrong_body = without_hash(wrong_issuer[0], "receipt_sha256")
    wrong_body["issuer_control_domain_id"] = "DOMAIN-WRONG"
    wrong_body["anti_replay_token"] = json_hash({
        field: wrong_body[field] for field in (
            "receipt_id", "release_context_sha256", "issuer_control_domain_id",
            "issuance_event_id", "issuance_event_revision", "issuance_event_sha256",
        )
    })
    wrong_issuer[0] = seal(wrong_body, "receipt_sha256")
    cases["WRONG_AUTHORIZED_ISSUER"] = (trusted, wrong_issuer, valid_linkage, "d" * 64)

    duplicate = [dict(item) for item in valid_lanes]
    duplicate_body = without_hash(duplicate[1], "receipt_sha256")
    duplicate_body["receipt_id"] = duplicate[0]["receipt_id"]
    duplicate_body["anti_replay_token"] = json_hash({
        field: duplicate_body[field] for field in (
            "receipt_id", "release_context_sha256", "issuer_control_domain_id",
            "issuance_event_id", "issuance_event_revision", "issuance_event_sha256",
        )
    })
    duplicate[1] = seal(duplicate_body, "receipt_sha256")
    cases["DUPLICATE_RECEIPT_ID"] = (trusted, duplicate, valid_linkage, "d" * 64)

    replay_context = context(["RECEIPT-PRODUCT"])
    replay_lanes = [receipt(replay_context, lane, f"RECEIPT-{lane}") for lane in lanes]
    replay_linkage = receipt(replay_context, linkage_key, "RECEIPT-LINKAGE")
    cases["ALREADY_CONSUMED_RECEIPT_REPLAY"] = (replay_context, replay_lanes, replay_linkage, "d" * 64)
    cases["EVENT_STORE_TIP_CHANGED_BEFORE_ATOMIC_COMMIT"] = (trusted, valid_lanes, valid_linkage, "f" * 64)

    rejected = {
        name
        for name, arguments in cases.items()
        if not accepts(*arguments)
    }
    authoritative_state = {
        "authority_scope": "PROGRAM", "instance_id": "INSTANCE-1",
        "state_revision": 50, "current_state_sha256": "c" * 64,
        "event_store_tip_sha256": "d" * 64,
    }
    stale_state = {**authoritative_state, "state_revision": 49, "current_state_sha256": "f" * 64}
    if stale_state != authoritative_state:
        rejected.add("RECOMPUTED_STALE_CURRENT_STATE_BUNDLE")
    return rejected


def standalone_epoch18_adversarial_oracle(
    include_epoch22_release_artifact_hash_cases: bool = False,
) -> set[str]:
    """Independent trust-boundary verdicts; imports no production module."""

    authoritative = {
        "adapter_type": "SQLiteEventStoreAuthorityAdapter",
        "implementation_sha256": "8" * 64,
        "database_identity_sha256": "9" * 64,
        "state_revision": 6,
        "event_store_tip_sha256": "a" * 64,
        "consumed_receipt_ids": set(),
    }
    rejected: set[str] = set()
    forged = {
        **authoritative,
        "state_revision": 99,
        "event_store_tip_sha256": "f" * 64,
    }
    if forged != authoritative:
        rejected.add("FULLY_FORGED_CONTEXT_AND_ALL_RECEIPTS_WITH_RECOMPUTED_HASHES")
    stale = {**authoritative, "state_revision": 5, "event_store_tip_sha256": "e" * 64}
    if stale != authoritative:
        rejected.add("RECOMPUTED_STALE_BUNDLE_PLUS_MATCHING_STALE_STATE")
    if "FakeAdapter" != authoritative["adapter_type"]:
        rejected.add("FAKE_ADAPTER_OBJECT")
    if "0" * 64 != authoritative["implementation_sha256"]:
        rejected.add("WRONG_ADAPTER_IMPLEMENTATION_SHA256")
    if "0" * 64 != authoritative["database_identity_sha256"]:
        rejected.add("FORGED_EVENT_STORE_WITH_WRONG_AUTHORIZED_DATABASE_IDENTITY")
    if "b" * 64 != authoritative["event_store_tip_sha256"]:
        rejected.add("EVENT_STORE_TIP_CHANGED_AFTER_EVALUATION_BEFORE_ATOMIC_COMMIT")
    consumed = {"RECEIPT-PRODUCT"}
    if consumed - authoritative["consumed_receipt_ids"]:
        rejected.add("RECEIPT_CONSUMED_AFTER_EVALUATION_BEFORE_ATOMIC_COMMIT")
    trusted_key = Ed25519PrivateKey.generate()
    attacker_key = Ed25519PrivateKey.generate()
    signed_body = {
        "authorization_purpose": "EVENT_STORE_ADAPTER_BINDING",
        "database_identity_sha256": authoritative["database_identity_sha256"],
        "adapter_contract_sha256": "c" * 64,
    }
    message = json.dumps(
        signed_body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    for case_name, signature in (
        ("UNSIGNED_MATCHING_EVENT_STORE_BINDING", b""),
        (
            "FORGED_EVENT_STORE_AND_MATCHING_BINDING_WITH_ATTACKER_SIGNATURE",
            attacker_key.sign(message),
        ),
    ):
        try:
            trusted_key.public_key().verify(signature, message)
        except InvalidSignature:
            rejected.add(case_name)
    if "0" * 64 != signed_body["adapter_contract_sha256"]:
        rejected.add("WRONG_ACTUAL_ADAPTER_CONTRACT_HASH")
    forged_commit = {
        "authorization_purpose": "RUNTIME_RELEASE_COMMIT",
        "authorization_id": "FORGED-AUTHORIZATION",
    }
    commit_message = json.dumps(
        forged_commit,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    try:
        trusted_key.public_key().verify(
            attacker_key.sign(commit_message),
            commit_message,
        )
    except InvalidSignature:
        rejected.add("SELF_ASSERTED_RELEASE_COMMIT_AUTHORIZATION")
    consumed_authorization_ids: set[str] = set()
    authorization_id = "SIGNED-ONE-SHOT-AUTHORIZATION"
    consumed_authorization_ids.add(authorization_id)
    if authorization_id in consumed_authorization_ids:
        rejected.add("REPLAYED_SIGNED_RELEASE_COMMIT_AUTHORIZATION")
    if include_epoch22_release_artifact_hash_cases:
        actual_release_artifacts = {
            "candidate_content_sha256": "2" * 64,
            "requirement_ir_sha256": "3" * 64,
            "executor_release_sha256": "4" * 64,
            "human_gate_receipt_sha256": "5" * 64,
        }
        for field, actual in actual_release_artifacts.items():
            if "f" * 64 != actual:
                rejected.add(
                    "VALID_SIGNATURE_WRONG_"
                    + field.removesuffix("_sha256").upper()
                    + "_SHA256"
                )
    return rejected


def check_release_closure_control_plane(
    root: Path,
    frozen_ir: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Independently execute the active Epoch 2 Candidate-static oracle."""

    findings: list[dict[str, str]] = []
    target = frozen_ir.get("target")
    if not (
        isinstance(target, Mapping)
        and target.get("architecture_epoch") == 2
        and target.get("control_plane_epoch") == 2
    ):
        return findings
    remediation = target.get("release_closure_control_plane_remediation")
    alignment = target.get(
        "v0_15_epoch2_producer_validator_alignment_correction"
    )
    human_review_remediation = target.get("v0_16_human_review_remediation")
    epoch17_remediation = target.get("v0_17_human_review_remediation")
    epoch18_remediation = target.get("v0_18_human_review_remediation")
    epoch20_remediation = target.get("v0_20_human_review_remediation")
    epoch22_remediation = target.get("v0_22_human_review_remediation")
    epoch24_remediation = target.get("v0_24_human_review_remediation")
    epoch25_remediation = target.get("v0_25_generation_failure_remediation")
    epoch26_remediation = target.get("v0_26_human_review_remediation")
    epoch28_remediation = target.get("v0_27_human_review_remediation")
    epoch29_remediation = target.get("v0_28_human_review_remediation")
    epoch30_remediation = target.get("v0_29_human_review_remediation")
    epoch31_remediation = target.get("v0_30_human_review_remediation")
    epoch32_remediation = target.get("v0_31_runtime_binding_failure_remediation")
    epoch33_remediation = target.get("v0_32_human_review_remediation")
    epoch34_remediation = target.get("v0_33_human_review_remediation")
    epoch35_remediation = target.get("v0_34_human_review_remediation")
    expected_requirement_epoch = (
        35
        if epoch35_remediation is not None
        else 34
        if epoch34_remediation is not None
        else 33
        if epoch33_remediation is not None
        else 32
        if epoch32_remediation is not None
        else 31
        if epoch31_remediation is not None
        else 30
        if epoch30_remediation is not None
        else 29
        if epoch29_remediation is not None
        else 28
        if epoch28_remediation is not None
        else 26
        if epoch26_remediation is not None
        else 25 if epoch25_remediation is not None else 24
    )
    expected_ids = [f"CORR-29-{index:03d}" for index in range(9, 14)]
    required_artifacts = [
        "V2_9_RELEASE_CLOSURE_CONTROL_PLANE_MANIFEST.json",
        "SEMANTIC_IMPLEMENTATION_AUTHORIZATION_IDENTITY_CONTRACT.json",
        "GENERIC_RECOVERY_DECISION_PROTOCOL.json",
        "COMPLEXITY_GOVERNOR.json",
        "PRODUCT_SAFETY_RELEASE_CLOSURE_GRAPH.json",
        "EVIDENCE_LIFECYCLE_AND_PROJECTION_CONTRACT.json",
        "EVENT_STORE_AUTHORITY_ADAPTER_CONTRACT.json",
        "AUTHORITY_TRUST_ROOT.json",
        "canonical_sources/RELEASE_CLOSURE_CORRECTION_COVERAGE_MATRIX.json",
        "contracts/v2_9_release_closure/IDENTITY_DERIVATION_INPUT.schema.json",
        "contracts/v2_9_release_closure/IDENTITY_BUNDLE.schema.json",
        "contracts/v2_9_release_closure/MACHINE_GRANT_BINDING.schema.json",
        "contracts/v2_9_release_closure/RECOVERY_DECISION.schema.json",
        "contracts/v2_9_release_closure/COMPLEXITY_DECISION.schema.json",
        "contracts/v2_9_release_closure/CLOSURE_RECEIPT.schema.json",
        "contracts/v2_9_release_closure/COMPATIBILITY_LINKAGE_RECEIPT.schema.json",
        "contracts/v2_9_release_closure/TRUSTED_RELEASE_CONTEXT.schema.json",
        "contracts/v2_9_release_closure/FINAL_RELEASE_DECISION.schema.json",
        "contracts/v2_9_release_closure/EVIDENCE_INDEX_ENTRY.schema.json",
        "contracts/v2_9_release_closure/EVENT_STORE_AUTHORITY_ADAPTER_BINDING.schema.json",
        "contracts/v2_9_release_closure/SOURCE_AUTHORITY_POLICY_LOCK.schema.json",
        "contracts/v2_9_release_closure/VALIDATION_REPORT_RECEIPT.schema.json",
        "tools/harness_foundry_runtime/authority_adapter.py",
        "tools/harness_foundry_runtime/identity_derivation.py",
        "tools/harness_foundry_runtime/recovery_decision.py",
        "tools/harness_foundry_runtime/complexity_governor.py",
        "tools/harness_foundry_runtime/closure_lanes.py",
        "tools/harness_foundry_runtime/evidence_projection.py",
        "tools/harness_foundry_runtime/store.py",
        "tools/harness_foundry_runtime/models.py",
        "tools/harness_foundry_runtime/constants.py",
    ]
    if epoch30_remediation is None:
        required_artifacts.remove(
            "contracts/v2_9_release_closure/VALIDATION_REPORT_RECEIPT.schema.json"
        )
    if (
        not isinstance(remediation, Mapping)
        or not isinstance(alignment, Mapping)
        or not isinstance(human_review_remediation, Mapping)
        or not isinstance(epoch17_remediation, Mapping)
        or not isinstance(epoch18_remediation, Mapping)
        or not isinstance(epoch20_remediation, Mapping)
        or not isinstance(epoch22_remediation, Mapping)
        or not isinstance(epoch24_remediation, Mapping)
        or remediation.get("architecture_epoch") != 2
        or remediation.get("control_plane_epoch") != 2
        or alignment.get("producer_first") is not True
        or alignment.get("correction_ids") != expected_ids
        or alignment.get("active_epoch_dispatch", {}).get("epoch_2_mode")
        != "EPOCH2_RELEASE_CLOSURE_CONTROL_PLANE"
        or human_review_remediation.get("status")
        != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
        or human_review_remediation.get("active_epochs")
        != {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 16,
        }
        or epoch17_remediation.get("status")
        != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
        or epoch17_remediation.get("active_epochs")
        != {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 17,
        }
        or epoch18_remediation.get("status")
        != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
        or epoch18_remediation.get("active_epochs")
        != {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 18,
        }
        or epoch18_remediation.get("independent_oracle_contract", {}).get(
            "standalone_executes_candidate_production_against_temporary_native_event_store"
        ) is not True
        or epoch20_remediation.get("status")
        != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
        or epoch20_remediation.get("active_epochs")
        != {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 20,
        }
        or epoch20_remediation.get("independent_oracle_contract", {}).get(
            "standalone_uses_exact_candidate_production_adapter"
        ) is not True
        or epoch22_remediation.get("status")
        != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
        or epoch22_remediation.get("active_epochs")
        != {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 22,
        }
        or epoch22_remediation.get("release_commit_actual_hash_contract", {}).get(
            "compare_inside_begin_immediate"
        ) is not True
        or epoch24_remediation.get("status")
        != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
        or epoch24_remediation.get("active_epochs")
        != {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 24,
        }
        or epoch24_remediation.get("producer_validator_route_contract", {}).get(
            "epoch23_requirements_consumed_by_standalone"
        ) is not True
        or epoch24_remediation.get("receiver_trust_anchor_contract", {}).get(
            "candidate_local_anchor_establishes_authority"
        ) is not False
        or epoch24_remediation.get(
            "authority_normalization_oracle_contract", {}
        ).get("standalone_requires_external_receiver_policy_lock") is not True
        or (
            epoch25_remediation is not None
            and (
                not isinstance(epoch25_remediation, Mapping)
                or epoch25_remediation.get("status")
                != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
                or epoch25_remediation.get("active_epochs")
                != {
                    "architecture_epoch": 2,
                    "control_plane_epoch": 2,
                    "requirement_epoch": 25,
                }
                or epoch25_remediation.get(
                    "producer_validator_route_contract", {}
                ).get("semantic_policy_projection_consumed_by_standalone")
                is not True
                or epoch25_remediation.get(
                    "source_authority_semantic_projection_contract", {}
                ).get("receiver_local_locator_fields_compared") is not False
                or epoch25_remediation.get(
                    "portable_uri_projection_contract", {}
                ).get("independent_mapping_validation_required") is not True
            )
        )
        or (
            epoch26_remediation is not None
            and (
                not isinstance(epoch26_remediation, Mapping)
                or epoch26_remediation.get("status")
                != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
                or epoch26_remediation.get("active_epochs")
                != {
                    "architecture_epoch": 2,
                    "control_plane_epoch": 2,
                    "requirement_epoch": 26,
                }
                or epoch26_remediation.get(
                    "portable_source_index_contract", {}
                ).get("standalone_independent_semantic_validation_required")
                is not True
                or epoch26_remediation.get(
                    "source_authority_policy_lock_contract", {}
                ).get("receiver_pinned_ed25519_signature_required") is not True
                or epoch26_remediation.get(
                    "closure_identity_contract", {}
                ).get("successor_package_epoch_cross_check_required") is not True
            )
        )
        or (
            epoch28_remediation is not None
            and (
                not isinstance(epoch28_remediation, Mapping)
                or epoch28_remediation.get("status")
                != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
                or epoch28_remediation.get("active_epochs")
                != {
                    "architecture_epoch": 2,
                    "control_plane_epoch": 2,
                    "requirement_epoch": 28,
                }
                or epoch28_remediation.get(
                    "receiver_release_history_authority_contract", {}
                ).get("receiver_pinned_ed25519_signature_required") is not True
                or epoch28_remediation.get(
                    "producer_history_authority_contract", {}
                ).get("source_authority_policy_version")
                != "V29_SOURCE_AUTHORITY_POLICY_LOCK_V4"
                or epoch28_remediation.get(
                    "dual_oracle_history_contract", {}
                ).get("factory_authority_input")
                != "FACTORY_EVENT_STORE_REQUIREMENT_IR"
            )
        )
        or (
            epoch29_remediation is not None
            and (
                not isinstance(epoch29_remediation, Mapping)
                or epoch29_remediation.get("status")
                != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
                or epoch29_remediation.get("active_epochs")
                != {
                    "architecture_epoch": 2,
                    "control_plane_epoch": 2,
                    "requirement_epoch": 29,
                }
                or epoch29_remediation.get(
                    "external_authority_fail_closed_contract", {}
                ).get("missing_authoritative_sources_overall_status")
                != "FAIL"
                or epoch29_remediation.get(
                    "external_authority_fail_closed_contract", {}
                ).get("missing_authoritative_requirement_ir_overall_status")
                != "FAIL"
                or epoch29_remediation.get(
                    "validation_report_authority_provenance_contract", {}
                ).get("authority_input_preserved") is not True
                or epoch29_remediation.get(
                    "validation_report_authority_provenance_contract", {}
                ).get("event_store_revision_tip_and_content_hashes_required")
                is not True
            )
        )
        or (
            epoch30_remediation is not None
            and (
                not isinstance(epoch30_remediation, Mapping)
                or epoch30_remediation.get("status")
                != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
                or epoch30_remediation.get("active_epochs")
                != {
                    "architecture_epoch": 2,
                    "control_plane_epoch": 2,
                    "requirement_epoch": 30,
                }
                or any(
                    epoch30_remediation.get(
                        "validation_report_integrity_contract", {}
                    ).get(field) is not True
                    for field in (
                        "factory_compares_embedded_external_checks_to_recomputed_checks",
                        "detached_report_receipt_required",
                        "receiver_signed_policy_binds_report_and_receipt_hashes",
                        "standalone_verifies_signed_report_binding",
                    )
                )
            )
        )
        or (
            epoch31_remediation is not None
            and (
                not isinstance(epoch31_remediation, Mapping)
                or epoch31_remediation.get("status")
                != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
                or epoch31_remediation.get("active_epochs")
                != {
                    "architecture_epoch": 2,
                    "control_plane_epoch": 2,
                    "requirement_epoch": 31,
                }
                or any(
                    epoch31_remediation.get(
                        "validation_basis_current_head_contract", {}
                    ).get(field) is not True
                    for field in (
                        "immutable_basis_must_be_verified_ancestor",
                        "current_head_may_advance_after_candidate_commit",
                    )
                )
                or epoch31_remediation.get(
                    "validation_basis_current_head_contract", {}
                ).get("basis_equals_mutable_head_required") is not False
                or epoch31_remediation.get(
                    "validation_basis_current_head_contract", {}
                ).get("forked_or_unrelated_basis_behavior") != "FAIL_CLOSED"
                or epoch31_remediation.get(
                    "candidate_generation_commit_contract", {}
                ).get("authority_source") != "FACTORY_APPEND_ONLY_EVENT_STORE"
                or epoch31_remediation.get(
                    "candidate_generation_commit_contract", {}
                ).get("event_type")
                != "START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW"
                or any(
                    epoch31_remediation.get(
                        "candidate_generation_commit_contract", {}
                    ).get(field) is not True
                    for field in (
                        "unique_matching_commit_required",
                        "commit_directly_descends_from_validation_basis",
                        "commit_binds_candidate_content_sha256",
                        "commit_binds_validation_report_sha256",
                        "commit_binds_validation_report_receipt_sha256",
                        "commit_binds_requirement_ir_sha256",
                        "commit_binds_validation_basis_revision_and_tip",
                    )
                )
                or epoch31_remediation.get(
                    "candidate_generation_commit_contract", {}
                ).get("replay_or_duplicate_commit_behavior") != "FAIL_CLOSED"
            )
        )
        or (
            epoch32_remediation is not None
            and (
                not isinstance(epoch32_remediation, Mapping)
                or epoch32_remediation.get("status")
                != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
                or epoch32_remediation.get("active_epochs")
                != {
                    "architecture_epoch": 2,
                    "control_plane_epoch": 2,
                    "requirement_epoch": 32,
                }
                or epoch32_remediation.get("closure_receipt_required") is not True
                or any(
                    epoch32_remediation.get(
                        "candidate_resource_uri_closure_contract", {}
                    ).get(field) is not True
                    for field in (
                        "scan_all_portable_text_resources",
                        "candidate_root_uri_may_resolve_to_root_directory",
                        "non_root_candidate_uri_must_resolve_to_physical_file",
                        "target_must_be_in_portable_manifest_files_or_declared_exclusions",
                    )
                )
                or epoch32_remediation.get(
                    "candidate_resource_uri_closure_contract", {}
                ).get("missing_or_uninventoried_behavior")
                != "FAIL_CLOSED_BEFORE_PUBLICATION_OR_BINDING"
                or epoch32_remediation.get(
                    "runtime_dependency_closure_contract", {}
                ).get("retained_store_contract") is not True
                or epoch32_remediation.get(
                    "runtime_dependency_closure_contract", {}
                ).get("relative_import_dependency_scan_required") is not True
                or tuple(
                    epoch32_remediation.get(
                        "runtime_dependency_closure_contract", {}
                    ).get("required_runtime_module_refs") or ()
                )
                != (
                    "tools/harness_foundry_runtime/store.py",
                    "tools/harness_foundry_runtime/models.py",
                    "tools/harness_foundry_runtime/constants.py",
                )
                or epoch32_remediation.get(
                    "runtime_dependency_closure_contract", {}
                ).get("missing_dependency_behavior") != "FAIL_CLOSED"
                or any(
                    epoch32_remediation.get(
                        "runtime_binder_atomicity_contract", {}
                    ).get(field) is not True
                    for field in (
                        "validate_complete_uri_and_inventory_before_first_execution_root_write",
                        "fresh_root_same_parent_staging_required",
                        "fresh_root_atomic_publish_required",
                        "failure_cleanup_keeps_fresh_root_absent",
                    )
                )
                or epoch32_remediation.get(
                    "runtime_binder_atomicity_contract", {}
                ).get("candidate_write_allowed") is not False
                or epoch32_remediation.get(
                    "runtime_binder_atomicity_contract", {}
                ).get("human_gate_consumption_before_binding_success_allowed")
                is not False
                or epoch32_remediation.get(
                    "independent_oracle_contract", {}
                ).get("factory_validator_full_uri_closure_required") is not True
                or epoch32_remediation.get(
                    "independent_oracle_contract", {}
                ).get("standalone_full_uri_closure_required") is not True
                or epoch32_remediation.get(
                    "independent_oracle_contract", {}
                ).get("factory_validator_calls_standalone") is not False
                or epoch32_remediation.get(
                    "independent_oracle_contract", {}
                ).get("standalone_calls_factory_validator") is not False
                or set(epoch32_remediation.get("required_adversarial_cases") or ())
                != {
                    "DANGLING_CANDIDATE_RESOURCE_URI",
                    "CANDIDATE_RESOURCE_URI_OUTSIDE_PORTABLE_INVENTORY",
                    "MISSING_PACKAGED_RUNTIME_RELATIVE_IMPORT",
                    "BINDER_FAILURE_LEAVES_FRESH_EXECUTION_ROOT_ABSENT",
                }
            )
        )
        or (
            epoch33_remediation is not None
            and (
                not isinstance(epoch33_remediation, Mapping)
                or epoch33_remediation.get("status")
                != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
                or epoch33_remediation.get("active_epochs")
                != {
                    "architecture_epoch": 2,
                    "control_plane_epoch": 2,
                    "requirement_epoch": 33,
                }
                or epoch33_remediation.get("closure_receipt_required") is not True
                or epoch33_remediation.get("closure_receipt_status")
                != "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT"
                or set(epoch33_remediation.get("finding_ids") or ())
                != {
                    "HR-V032-001-BINDER-PREFLIGHT-INCOMPLETE",
                    "HR-V032-002-ADVERSARIAL-DOMAIN-MISROUTED",
                    "HR-V032-003-BINDER-HASH-ATOMICITY-UNBOUND",
                    "HR-V032-004-STANDALONE-CASCADE-FALSE-FINDING",
                }
                or any(
                    epoch33_remediation.get(
                        "runtime_binder_preflight_contract", {}
                    ).get(field) is not True
                    for field in (
                        "portable_manifest_before_first_execution_root_write",
                        "all_candidate_uri_closure_before_first_execution_root_write",
                        "runtime_dependency_closure_before_first_execution_root_write",
                        "necessary_receiver_authority_before_first_execution_root_write",
                    )
                )
                or epoch33_remediation.get("adversarial_domain_contract", {}).get(
                    "epoch32_uri_binder_cases_owner"
                ) != "RUNTIME_BINDER"
                or epoch33_remediation.get("adversarial_domain_contract", {}).get(
                    "source_authority_domain_excludes_runtime_binder_cases"
                ) is not True
                or set(
                    epoch33_remediation.get("adversarial_domain_contract", {}).get(
                        "runtime_binder_required_adversarial_cases"
                    ) or ()
                )
                != {
                    "DANGLING_CANDIDATE_RESOURCE_URI",
                    "CANDIDATE_RESOURCE_URI_OUTSIDE_PORTABLE_INVENTORY",
                    "MISSING_PACKAGED_RUNTIME_RELATIVE_IMPORT",
                    "BINDER_FAILURE_LEAVES_FRESH_EXECUTION_ROOT_ABSENT",
                }
                or any(
                    epoch33_remediation.get(
                        "setup_runtime_binding_contract", {}
                    ).get(field) is not True
                    for field in (
                        "runtime_binding_contract_binds_setup_runtime_sha256",
                        "closure_receipt_binds_setup_runtime_sha256",
                        "validation_before_first_execution_root_write",
                        "fresh_root_same_parent_staging_required",
                        "fresh_root_atomic_publish_required",
                        "failure_cleanup_keeps_fresh_root_absent",
                    )
                )
                or epoch33_remediation.get(
                    "standalone_missing_authority_contract", {}
                ).get("missing_external_authority_root_finding_preserved") is not True
                or epoch33_remediation.get(
                    "standalone_missing_authority_contract", {}
                ).get("dependent_adversarial_false_findings_suppressed") is not True
            )
        )
        or (
            epoch34_remediation is not None
            and not _epoch34_runtime_binding_review_remediation_is_complete(
                epoch34_remediation
            )
        )
        or (
            epoch35_remediation is not None
            and not _epoch35_runtime_binding_path_atomicity_remediation_is_complete(
                epoch35_remediation
            )
        )
        or epoch17_remediation.get("independent_oracles", {}).get(
            "standalone_oracle_imports_factory_reference_oracle"
        ) is not False
    ):
        return [{
            "code": "V2_9_EPOCH2_DESCRIPTOR_INVALID",
            "message": "active Epoch 2 remediation or producer dispatch is invalid",
        }]

    base_runtime_cases = set(epoch20_remediation["required_adversarial_cases"])
    base_runtime_cases.update(epoch22_remediation["required_adversarial_cases"])
    epoch24_runtime_cases = set(
        epoch24_remediation.get("required_runtime_adversarial_cases") or []
    )
    epoch24_gate_cases = set(
        epoch24_remediation.get("required_gate_adversarial_cases") or []
    )
    epoch24_cases = set(epoch24_remediation["required_adversarial_cases"])
    if (
        not epoch24_runtime_cases
        or not epoch24_gate_cases
        or epoch24_runtime_cases & epoch24_gate_cases
        or epoch24_runtime_cases | epoch24_gate_cases != epoch24_cases
        or standalone_epoch18_adversarial_oracle(True) != base_runtime_cases
    ):
        return [{
            "code": "V2_9_EPOCH18_INDEPENDENT_ORACLE_INVALID",
            "message": "standalone runtime and gate adversarial coverage drifted",
        }]
    expected_cases = base_runtime_cases | epoch24_cases
    runtime_expected_cases = base_runtime_cases | epoch24_runtime_cases
    source_authority_expected_cases = sorted({
        *((epoch26_remediation.get("required_adversarial_cases") or [])
        if isinstance(epoch26_remediation, Mapping) else ()),
        *((epoch28_remediation.get("required_adversarial_cases") or [])
        if isinstance(epoch28_remediation, Mapping) else ()),
        *((epoch29_remediation.get("required_adversarial_cases") or [])
        if isinstance(epoch29_remediation, Mapping) else ()),
        *((epoch30_remediation.get("required_adversarial_cases") or [])
        if isinstance(epoch30_remediation, Mapping) else ()),
        *((epoch31_remediation.get("required_adversarial_cases") or [])
        if isinstance(epoch31_remediation, Mapping) else ()),
    })
    runtime_binder_expected_cases = sorted({
        *((
            epoch33_remediation.get("adversarial_domain_contract", {}).get(
                "runtime_binder_required_adversarial_cases"
            )
            if isinstance(epoch33_remediation, Mapping)
            else None
        ) or epoch32_remediation.get("required_adversarial_cases") or []),
        *((epoch35_remediation.get("required_adversarial_cases") or [])
        if isinstance(epoch35_remediation, Mapping) else ()),
    }) if isinstance(epoch32_remediation, Mapping) else []
    factory_required_regression_tests = list(
        (
            epoch35_remediation.get("required_regression_tests")
            if isinstance(epoch35_remediation, Mapping)
            else epoch34_remediation.get("required_regression_tests")
            if isinstance(epoch34_remediation, Mapping)
            else []
        )
        or []
    )

    paths = {
        "manifest": "V2_9_RELEASE_CLOSURE_CONTROL_PLANE_MANIFEST.json",
        "identity": "SEMANTIC_IMPLEMENTATION_AUTHORIZATION_IDENTITY_CONTRACT.json",
        "recovery": "GENERIC_RECOVERY_DECISION_PROTOCOL.json",
        "complexity": "COMPLEXITY_GOVERNOR.json",
        "closure": "PRODUCT_SAFETY_RELEASE_CLOSURE_GRAPH.json",
        "evidence": "EVIDENCE_LIFECYCLE_AND_PROJECTION_CONTRACT.json",
        "adapter": "EVENT_STORE_AUTHORITY_ADAPTER_CONTRACT.json",
        "trust_root": "AUTHORITY_TRUST_ROOT.json",
        "correction": "canonical_sources/RELEASE_CLOSURE_CORRECTION_COVERAGE_MATRIX.json",
        "atoms": "canonical_sources/NORMATIVE_ATOM_CATALOG.json",
        "coverage": "canonical_sources/ATOM_COVERAGE_MATRIX.json",
        "dag": "ENGINEERING_PROJECT_DAG.json",
        "legacy": "THREE_PROJECT_PROGRAM_MANIFEST.json",
    }
    missing = [
        relative
        for relative in required_artifacts + list(paths.values())
        if not (root / relative).is_file()
    ]
    if missing:
        return [{
            "code": "V2_9_EPOCH2_ARTIFACT_MISSING",
            "message": ", ".join(sorted(set(missing))),
        }]
    try:
        documents = {
            key: json.loads((root / relative).read_text(encoding="utf-8"))
            for key, relative in paths.items()
        }
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [{"code": "V2_9_EPOCH2_DOCUMENT_INVALID", "message": str(exc)}]

    manifest = documents["manifest"]
    contract_refs = {
        paths[key] for key in (
            "identity", "recovery", "complexity", "closure", "evidence", "adapter",
            "trust_root",
        )
    }
    expected_modules = {
        "tools/harness_foundry_runtime/__init__.py",
        "tools/harness_foundry_runtime/identity_derivation.py",
        "tools/harness_foundry_runtime/recovery_decision.py",
        "tools/harness_foundry_runtime/complexity_governor.py",
        "tools/harness_foundry_runtime/closure_lanes.py",
        "tools/harness_foundry_runtime/evidence_projection.py",
        "tools/harness_foundry_runtime/authority_adapter.py",
        "tools/harness_foundry_runtime/store.py",
        "tools/harness_foundry_runtime/models.py",
        "tools/harness_foundry_runtime/constants.py",
    }
    expected_schemas = {
        "contracts/v2_9_release_closure/IDENTITY_DERIVATION_INPUT.schema.json",
        "contracts/v2_9_release_closure/IDENTITY_BUNDLE.schema.json",
        "contracts/v2_9_release_closure/MACHINE_GRANT_BINDING.schema.json",
        "contracts/v2_9_release_closure/RECOVERY_DECISION.schema.json",
        "contracts/v2_9_release_closure/COMPLEXITY_DECISION.schema.json",
        "contracts/v2_9_release_closure/CLOSURE_RECEIPT.schema.json",
        "contracts/v2_9_release_closure/COMPATIBILITY_LINKAGE_RECEIPT.schema.json",
        "contracts/v2_9_release_closure/TRUSTED_RELEASE_CONTEXT.schema.json",
        "contracts/v2_9_release_closure/FINAL_RELEASE_DECISION.schema.json",
        "contracts/v2_9_release_closure/EVIDENCE_INDEX_ENTRY.schema.json",
        "contracts/v2_9_release_closure/EVENT_STORE_AUTHORITY_ADAPTER_BINDING.schema.json",
        "contracts/v2_9_release_closure/SOURCE_AUTHORITY_POLICY_LOCK.schema.json",
        "contracts/v2_9_release_closure/VALIDATION_REPORT_RECEIPT.schema.json",
    }
    if epoch30_remediation is None:
        expected_schemas.remove(
            "contracts/v2_9_release_closure/VALIDATION_REPORT_RECEIPT.schema.json"
        )
    module_hashes = manifest.get("runtime_module_sha256")
    schema_hashes = manifest.get("schema_sha256")
    contract_hashes = manifest.get("contract_sha256")
    if (
        manifest.get("manifest_sha256")
        != json_hash(without_hash(manifest, "manifest_sha256"))
        or manifest.get("architecture_epoch") != 2
        or manifest.get("control_plane_epoch") != 2
        or manifest.get("requirement_epoch") != expected_requirement_epoch
        or manifest.get("active_generation_mode")
        != "EPOCH2_RELEASE_CLOSURE_CONTROL_PLANE"
        or manifest.get("status")
        != "FROZEN_IMPLEMENTATION_READY_NOT_AUTHORIZED"
        or manifest.get("correction_ids") != expected_ids
        or manifest.get("correction_coverage_ref") != paths["correction"]
        or manifest.get("correction_coverage_sha256")
        != file_hash(root / paths["correction"])
        or manifest.get("legacy_epoch1_authority") is not False
        or manifest.get("legacy_v2_8_topology_role")
        != "COMPATIBILITY_ADAPTER_ONLY"
        or manifest.get("persistent_fact_authority")
        != "SINGLE_APPEND_ONLY_EVENT_STORE"
        or manifest.get("human_authorization_status") != "NOT_GRANTED"
        or manifest.get("machine_grant_count") != 0
        or manifest.get("driver_started") is not False
        or manifest.get("active_workpack") is not None
        or manifest.get("execution_started") is not False
        or set(manifest.get("required_adversarial_cases") or []) != expected_cases
        or manifest.get("source_authority_required_adversarial_cases")
        != source_authority_expected_cases
        or manifest.get("runtime_binder_required_adversarial_cases")
        != runtime_binder_expected_cases
        or manifest.get("factory_required_regression_tests")
        != factory_required_regression_tests
        or manifest.get("factory_oracle_imports_candidate_production_module") is not False
        or manifest.get("standalone_oracle_imports_factory_reference_oracle") is not False
        or not isinstance(module_hashes, Mapping)
        or set(module_hashes) != expected_modules
        or not isinstance(schema_hashes, Mapping)
        or set(schema_hashes) != expected_schemas
        or not isinstance(contract_hashes, Mapping)
        or set(contract_hashes) != contract_refs
    ):
        findings.append({
            "code": "V2_9_EPOCH2_MANIFEST_INVALID",
            "message": "Epoch 2 manifest identity, inventory, authority, or lifecycle drifted",
        })
    for hashes, expected, code in (
        (module_hashes, expected_modules, "V2_9_EPOCH2_MODULE_HASH_INVALID"),
        (schema_hashes, expected_schemas, "V2_9_EPOCH2_SCHEMA_HASH_INVALID"),
        (contract_hashes, contract_refs, "V2_9_EPOCH2_CONTRACT_HASH_INVALID"),
    ):
        if isinstance(hashes, Mapping):
            for relative in expected:
                if hashes.get(relative) != file_hash(root / relative):
                    findings.append({"code": code, "message": relative})

    schema_exact_fields = {
        "contracts/v2_9_release_closure/IDENTITY_DERIVATION_INPUT.schema.json": {
            "semantic_contract", "implementation_release",
            "authorization_risk", "authority_adapter_binding_sha256",
        },
        "contracts/v2_9_release_closure/IDENTITY_BUNDLE.schema.json": {
            "schema_version", "identity_derivation_id", "input_sha256",
            "semantic_contract_identity_sha256",
            "implementation_release_identity_sha256",
            "authorization_risk_identity_sha256", "authority_scope",
            "instance_id", "state_revision", "current_state_sha256",
            "event_store_tip_sha256",
            "creates_authority", "identity_bundle_sha256",
        },
        "contracts/v2_9_release_closure/MACHINE_GRANT_BINDING.schema.json": {
            "schema_version", "binding_id", "binding_status",
            "authorization_risk_identity_sha256",
            "semantic_contract_identity_sha256",
            "implementation_release_identity_sha256",
            "exact_executor_release_sha256", "exact_artifact_release_sha256",
            "authority_scope", "instance_id", "state_revision",
            "current_state_sha256", "event_store_tip_sha256",
            "authoritative_adapter_checked", "authority_adapter_binding_sha256",
            "human_authorization_granted",
            "machine_grant_issued", "creates_authority", "binding_sha256",
        },
        "contracts/v2_9_release_closure/COMPLEXITY_DECISION.schema.json": {
            "schema_version", "governor_id", "input_sha256", "decision",
            "reason_code", "violations", "outputs", "creates_authority",
            "assessment_sha256",
        },
        "contracts/v2_9_release_closure/CLOSURE_RECEIPT.schema.json": {
            "schema_version", "lane_id", "status", "authority_scope",
            "instance_id", "requirement_epoch",
            "semantic_contract_identity_sha256",
            "authorization_risk_identity_sha256", "receipt_id",
            "issuer_control_domain_id", "issuance_event_id",
            "issuance_event_revision", "issuance_event_sha256",
            "release_context_sha256", "anti_replay_token", "creates_authority",
            "receipt_sha256",
        },
        "contracts/v2_9_release_closure/COMPATIBILITY_LINKAGE_RECEIPT.schema.json": {
            "schema_version", "status", "authority_scope", "instance_id",
            "requirement_epoch", "semantic_contract_identity_sha256",
            "authorization_risk_identity_sha256", "receipt_id",
            "issuer_control_domain_id", "issuance_event_id",
            "issuance_event_revision", "issuance_event_sha256",
            "release_context_sha256", "anti_replay_token", "creates_authority",
            "receipt_sha256",
        },
        "contracts/v2_9_release_closure/TRUSTED_RELEASE_CONTEXT.schema.json": {
            "schema_version", "authority_scope", "instance_id",
            "requirement_epoch", "semantic_contract_identity_sha256",
            "authorization_risk_identity_sha256", "state_revision",
            "current_state_sha256", "event_store_tip_sha256",
            "candidate_content_sha256", "requirement_ir_sha256",
            "executor_release_sha256", "human_gate_receipt_sha256",
            "authorized_issuers", "consumed_receipt_ids",
            "release_context_sha256",
        },
        "contracts/v2_9_release_closure/FINAL_RELEASE_DECISION.schema.json": {
            "schema_version", "decision_id", "decision",
            "release_context_sha256", "expected_event_store_tip_sha256",
            "lane_receipt_ids", "lane_receipt_sha256",
            "compatibility_linkage_receipt_id",
            "compatibility_linkage_receipt_sha256",
            "atomic_event_store_commit_required", "receipt_set_consumed",
            "release_ready_committed", "creates_authority", "decision_sha256",
        },
        "contracts/v2_9_release_closure/EVENT_STORE_AUTHORITY_ADAPTER_BINDING.schema.json": {
            "schema_version", "adapter_id", "program_id", "authority_scope",
            "instance_id", "requirement_epoch", "database_identity_sha256",
            "logical_database_ref", "adapter_implementation_sha256",
            "adapter_entrypoint_sha256", "adapter_contract_sha256",
            "authority_binding_receipt",
            "binding_sha256",
        },
        "contracts/v2_9_release_closure/SOURCE_AUTHORITY_POLICY_LOCK.schema.json": {
            "schema_version", "lock_id", "authority_source",
            "trust_anchor_id", "issuer_binding",
            "authority_normalization", "canonical_authority_levels",
            "semantic_projection_fields", "sources",
            "release_history_tip_sha256", "release_history",
            "validation_report_binding",
            "policy_payload_sha256",
            "signature_algorithm", "signature_base64", "lock_sha256",
        },
        "contracts/v2_9_release_closure/VALIDATION_REPORT_RECEIPT.schema.json": {
            "schema_version", "receipt_id", "report_ref", "report_sha256",
            "report_id", "program_id", "package_id", "candidate_version",
            "requirement_epoch", "requirement_ir_sha256",
            "authority_provenance", "external_authority_checks_sha256",
            "binding_authority", "receipt_sha256",
        },
    }
    if epoch30_remediation is None:
        schema_exact_fields[
            "contracts/v2_9_release_closure/SOURCE_AUTHORITY_POLICY_LOCK.schema.json"
        ].remove("validation_report_binding")
        schema_exact_fields.pop(
            "contracts/v2_9_release_closure/VALIDATION_REPORT_RECEIPT.schema.json"
        )
    for relative, exact_fields in schema_exact_fields.items():
        try:
            schema = json.loads((root / relative).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            findings.append({"code": "V2_9_EPOCH2_OUTPUT_SCHEMA_INVALID", "message": relative})
            continue
        properties = schema.get("properties")
        required = schema.get("required")
        invalid = (
            schema.get("additionalProperties") is not False
            or not isinstance(properties, Mapping)
            or set(properties) != exact_fields
            or not isinstance(required, list)
            or set(required) != exact_fields
            or len(required) != len(exact_fields)
        )
        if relative.endswith("CLOSURE_RECEIPT.schema.json"):
            invalid = invalid or (
                properties.get("requirement_epoch") != {"type": "integer", "minimum": 0}
                or properties.get("receipt_sha256") != {"type": "string", "pattern": "^[0-9a-f]{64}$"}
            )
        if relative.endswith("COMPLEXITY_DECISION.schema.json"):
            outputs = properties.get("outputs") if isinstance(properties, Mapping) else None
            output_properties = outputs.get("properties") if isinstance(outputs, Mapping) else None
            exact_outputs = {
                "complexity_baseline", "complexity_delta", "retirement_manifest",
                "human_cost_result", "circuit_breaker_decision_receipt",
            }
            invalid = invalid or (
                not isinstance(outputs, Mapping)
                or outputs.get("additionalProperties") is not False
                or not isinstance(output_properties, Mapping)
                or set(output_properties) != exact_outputs
                or set(outputs.get("required") or []) != exact_outputs
            )
        if invalid:
            findings.append({"code": "V2_9_EPOCH2_OUTPUT_SCHEMA_INVALID", "message": relative})

    identity = documents["identity"]
    recovery = documents["recovery"]
    complexity = documents["complexity"]
    closure = documents["closure"]
    evidence = documents["evidence"]
    adapter_contract = documents["adapter"]
    declared_contracts = (
        (identity, remediation.get("identity_contract"), "contract_sha256"),
        (recovery, remediation.get("generic_recovery_protocol"), "contract_sha256"),
        (complexity, remediation.get("complexity_governor"), "contract_sha256"),
        (closure, remediation.get("closure_lanes"), "graph_sha256"),
        (evidence, remediation.get("evidence_and_projection"), "contract_sha256"),
    )
    for document, declaration, hash_field in declared_contracts:
        if (
            not isinstance(document, Mapping)
            or not isinstance(declaration, Mapping)
            or document.get(hash_field) != json_hash(without_hash(document, hash_field))
            or any(document.get(key) != value for key, value in declaration.items())
            or document.get("status") != "FROZEN_NOT_EXECUTED"
            or document.get("creates_authority") is not False
            or document.get("execution_started") is not False
        ):
            findings.append({
                "code": "V2_9_EPOCH2_CONTRACT_SEMANTICS_INVALID",
                "message": str(document.get("contract_id") or document.get("protocol_id") or document.get("governor_id") or document.get("graph_id")),
            })
    adapter_declaration = epoch18_remediation.get(
        "event_store_authority_adapter_contract"
    )
    adapter_entrypoint_descriptor = {
        "module": "tools.harness_foundry_runtime.authority_adapter",
        "class": "SQLiteEventStoreAuthorityAdapter",
        "required_methods": [
            "read_current_state", "read_release_context",
            "assert_receipt_issued", "validate_precommit",
            "atomic_commit_release_ready",
        ],
    }
    if (
        not isinstance(adapter_contract, Mapping)
        or not isinstance(adapter_declaration, Mapping)
        or adapter_contract.get("contract_sha256")
        != json_hash(without_hash(adapter_contract, "contract_sha256"))
        or any(
            adapter_contract.get(key) != value
            for key, value in adapter_declaration.items()
        )
        or any(
            adapter_contract.get(key) != value
            for declaration_key in (
                "artifact_bytes_resolver_contract",
                "receiver_trust_anchor_contract",
            )
            for key, value in epoch24_remediation[declaration_key].items()
        )
        or adapter_contract.get("candidate_local_trust_root_role")
        != "UNTRUSTED_DISTRIBUTION_METADATA_ONLY"
        or adapter_contract.get("runtime_trust_anchor_source")
        != "RECEIVER_CONTROL_PLANE_ARGUMENT_ONLY"
        or adapter_contract.get("artifact_resolver_class")
        != "ReleaseArtifactBytesResolver"
        or adapter_contract.get("implementation_ref")
        != "tools/harness_foundry_runtime/authority_adapter.py"
        or adapter_contract.get("implementation_sha256")
        != file_hash(root / "tools/harness_foundry_runtime/authority_adapter.py")
        or adapter_contract.get("binding_schema_ref")
        != "contracts/v2_9_release_closure/EVENT_STORE_AUTHORITY_ADAPTER_BINDING.schema.json"
        or adapter_contract.get("entrypoint_descriptor")
        != adapter_entrypoint_descriptor
        or adapter_contract.get("entrypoint_sha256")
        != json_hash(adapter_entrypoint_descriptor)
        or adapter_contract.get("release_artifact_hash_authority_event")
        != "CURRENT_STATE_COMMITTED"
        or adapter_contract.get("release_artifact_hash_fields")
        != [
            "candidate_content_sha256", "requirement_ir_sha256",
            "executor_release_sha256", "human_gate_receipt_sha256",
        ]
        or adapter_contract.get(
            "release_artifact_hashes_read_and_compared_inside_begin_immediate"
        ) is not True
        or adapter_contract.get(
            "valid_signature_with_wrong_release_artifact_hash_behavior"
        ) != "FAIL_CLOSED"
        or adapter_contract.get("database_path_in_shareable_contract") is not False
        or adapter_contract.get("event_store_activated") is not False
        or adapter_contract.get("authority_granted") is not False
        or adapter_contract.get("execution_started") is not False
    ):
        findings.append({
            "code": "V2_9_EVENT_STORE_AUTHORITY_ADAPTER_CONTRACT_INVALID",
            "message": "Hash-bound adapter contract or lifecycle drifted",
        })
    identity_ref = identity.get("implementation_ref")
    identity_input_schema_ref = identity.get("identity_derivation_input_schema_ref")
    identity_bundle_schema_ref = identity.get("identity_bundle_schema_ref")
    machine_grant_schema_ref = identity.get("machine_grant_binding_schema_ref")
    if (
        identity_ref != "tools/harness_foundry_runtime/identity_derivation.py"
        or identity_input_schema_ref
        != "contracts/v2_9_release_closure/IDENTITY_DERIVATION_INPUT.schema.json"
        or identity_bundle_schema_ref
        != "contracts/v2_9_release_closure/IDENTITY_BUNDLE.schema.json"
        or machine_grant_schema_ref
        != "contracts/v2_9_release_closure/MACHINE_GRANT_BINDING.schema.json"
        or identity.get("implementation_sha256") != file_hash(root / identity_ref)
        or identity.get("identity_derivation_input_schema_sha256")
        != file_hash(root / identity_input_schema_ref)
        or identity.get("identity_bundle_schema_sha256")
        != file_hash(root / identity_bundle_schema_ref)
        or identity.get("machine_grant_binding_schema_sha256")
        != file_hash(root / machine_grant_schema_ref)
        or identity.get("authority_adapter_contract_ref") != paths["adapter"]
        or identity.get("authority_adapter_contract_sha256")
        != adapter_contract.get("contract_sha256")
        or identity.get("authority_adapter_implementation_ref")
        != "tools/harness_foundry_runtime/authority_adapter.py"
        or identity.get("change_classes")
        != [
            "NO_REBIND_REQUIRED",
            "MACHINE_GRANT_REBIND_REQUIRED",
            "HUMAN_REAUTHORIZATION_REQUIRED",
        ]
    ):
        findings.append({
            "code": "V2_9_EPOCH2_IDENTITY_IMPLEMENTATION_INVALID",
            "message": "CORR-29-009 executable identity or output schemas drifted",
        })
    for document, impl_key, schema_key, schema_hash_key in (
        (recovery, "implementation_ref", "decision_schema_ref", "decision_schema_sha256"),
        (complexity, "implementation_ref", "decision_schema_ref", "decision_schema_sha256"),
        (closure, "implementation_ref", "closure_receipt_schema_ref", "closure_receipt_schema_sha256"),
        (evidence, "implementation_ref", "evidence_index_entry_schema_ref", "evidence_index_entry_schema_sha256"),
    ):
        impl_ref = document.get(impl_key)
        schema_ref = document.get(schema_key)
        if (
            not isinstance(impl_ref, str)
            or not isinstance(schema_ref, str)
            or impl_ref not in expected_modules
            or schema_ref not in expected_schemas
            or document.get("implementation_sha256") != file_hash(root / impl_ref)
            or document.get(schema_hash_key) != file_hash(root / schema_ref)
        ):
            findings.append({
                "code": "V2_9_EPOCH2_IMPLEMENTATION_BINDING_INVALID",
                "message": str(impl_ref),
            })
    linkage_schema_ref = closure.get("compatibility_linkage_receipt_schema_ref")
    trusted_context_schema_ref = closure.get("trusted_release_context_schema_ref")
    final_decision_schema_ref = closure.get("final_release_decision_schema_ref")
    required_binding_fields = [
        "authority_scope",
        "instance_id",
        "requirement_epoch",
        "semantic_contract_identity_sha256",
        "authorization_risk_identity_sha256",
        "candidate_content_sha256",
        "requirement_ir_sha256",
        "executor_release_sha256",
        "human_gate_receipt_sha256",
    ]
    if (
        linkage_schema_ref
        != "contracts/v2_9_release_closure/COMPATIBILITY_LINKAGE_RECEIPT.schema.json"
        or closure.get("compatibility_linkage_receipt_schema_sha256")
        != file_hash(root / linkage_schema_ref)
        or trusted_context_schema_ref
        != "contracts/v2_9_release_closure/TRUSTED_RELEASE_CONTEXT.schema.json"
        or closure.get("trusted_release_context_schema_sha256")
        != file_hash(root / trusted_context_schema_ref)
        or final_decision_schema_ref
        != "contracts/v2_9_release_closure/FINAL_RELEASE_DECISION.schema.json"
        or closure.get("final_release_decision_schema_sha256")
        != file_hash(root / final_decision_schema_ref)
        or closure.get("release_ready_binding_fields") != required_binding_fields
        or closure.get("evaluator_output")
        != "RELEASE_ELIGIBILITY_PROPOSAL_NOT_AUTHORITY"
        or closure.get("candidate_may_commit_release_ready") is not False
        or closure.get("authority_adapter_contract_ref") != paths["adapter"]
        or closure.get("authority_adapter_contract_sha256")
        != adapter_contract.get("contract_sha256")
        or closure.get("authority_adapter_implementation_ref")
        != "tools/harness_foundry_runtime/authority_adapter.py"
    ):
        findings.append({
            "code": "V2_9_EPOCH2_CLOSURE_BINDING_INVALID",
            "message": "linkage schema or cross-receipt identity tuple drifted",
        })
    expected_complexity_outputs = [
        "COMPLEXITY_BASELINE",
        "COMPLEXITY_DELTA",
        "RETIREMENT_MANIFEST",
        "HUMAN_COST_RESULT",
        "CIRCUIT_BREAKER_DECISION_RECEIPT",
    ]
    if (
        complexity.get("aggregate_output_id") != "COMPLEXITY_ASSESSMENT"
        or complexity.get("required_machine_outputs")
        != expected_complexity_outputs
        or complexity.get("aggregate_schema_required") is not True
        or complexity.get("canonical_assessment_hash_required") is not True
    ):
        findings.append({
            "code": "V2_9_EPOCH2_COMPLEXITY_OUTPUT_CONTRACT_INVALID",
            "message": "CORR-29-011 aggregate output declaration drifted",
        })

    matrix = documents["correction"]
    declarations = remediation.get("correction_requirements")
    declaration_by_id = {
        str(item.get("correction_id")): item
        for item in declarations or []
        if isinstance(item, Mapping) and item.get("correction_id")
    }
    rows = matrix.get("rows") if isinstance(matrix, Mapping) else None
    row_by_id = {
        str(item.get("correction_id")): item
        for item in rows or []
        if isinstance(item, Mapping) and item.get("correction_id")
    }
    atom_ids = {
        str(item.get("atom_id"))
        for item in documents["atoms"].get("atoms", [])
        if isinstance(item, Mapping) and item.get("atom_id")
    }
    coverage_by_atom = {
        str(item.get("atom_id")): item
        for item in documents["coverage"].get("coverage", [])
        if isinstance(item, Mapping) and item.get("atom_id")
    }
    matrix_invalid = (
        not isinstance(declarations, list)
        or list(declaration_by_id) != expected_ids
        or not isinstance(rows, list)
        or list(row_by_id) != expected_ids
        or matrix.get("expected_correction_ids") != expected_ids
        or matrix.get("correction_count") != 5
        or matrix.get("candidate_static_status") != "PASS"
        or matrix.get("runtime_evidence_status")
        != "PENDING_UNTIL_AUTHORIZED_EXECUTION"
        or matrix.get("execution_started") is not False
        or matrix.get("matrix_sha256")
        != json_hash(without_hash(matrix, "matrix_sha256"))
    )
    for correction_id in expected_ids:
        declaration = declaration_by_id.get(correction_id, {})
        row = row_by_id.get(correction_id, {})
        maps_to = [str(value) for value in declaration.get("maps_to", [])]
        expected_coverage = []
        for atom_id in maps_to:
            edge = coverage_by_atom.get(atom_id, {})
            expected_coverage.append({
                "atom_id": atom_id,
                "workpack_ids": list(edge.get("workpack_ids") or []),
                "stage_ids": list(edge.get("stage_ids") or []),
                "release_step_ids": list(edge.get("release_step_ids") or []),
                "owner_project_ids": list(edge.get("owner_project_ids") or []),
                "coverage_status": edge.get("status"),
            })
        refs = epoch2_implementation_refs(correction_id)
        matrix_invalid = matrix_invalid or (
            not maps_to
            or any(atom_id not in atom_ids or atom_id not in coverage_by_atom for atom_id in maps_to)
            or row.get("requirement") != declaration.get("requirement")
            or row.get("maps_to") != maps_to
            or row.get("mapped_atom_coverage") != expected_coverage
            or row.get("implementation_artifact_refs") != refs
            or any(not (root / relative).is_file() for relative in refs)
            or row.get("candidate_static_lifecycle")
            != "MATERIALIZED_AND_HASH_BOUND"
            or row.get("runtime_lifecycle")
            != "PENDING_UNTIL_AUTHORIZED_EXECUTION"
            or row.get("runtime_evidence_refs") != []
            or row.get("runtime_claims_verified") is not False
            or row.get("row_sha256") != json_hash(without_hash(row, "row_sha256"))
        )
    if matrix_invalid:
        findings.append({
            "code": "V2_9_EPOCH2_CORRECTION_COVERAGE_INVALID",
            "message": "CORR-29-009 through CORR-29-013 coverage is incomplete or drifted",
        })

    closure_by_key = {
        str(item.get("requirement_key")): item
        for item in receipt.get("closures", [])
        if isinstance(item, Mapping)
    }
    closure_entry = closure_by_key.get("human_review_v0_20_closure")
    if not isinstance(closure_entry, Mapping):
        findings.append({
            "code": "V2_9_EPOCH2_HUMAN_REVIEW_CLOSURE_INVALID",
            "message": "human_review_v0_20_closure is missing",
        })
    else:
        evidence_refs = set(closure_entry.get("evidence_refs") or [])
        evidence_hashes = closure_entry.get("evidence_sha256")
        required_closure_refs = set(required_artifacts)
        if (
            not required_closure_refs.issubset(evidence_refs)
            or not isinstance(evidence_hashes, Mapping)
            or any(
                evidence_hashes.get(relative) != file_hash(root / relative)
                for relative in required_closure_refs
            )
        ):
            findings.append({
                "code": "V2_9_EPOCH2_HUMAN_REVIEW_CLOSURE_INVALID",
                "message": "v0.20 Human Review closure is not bound to every replacement artifact",
            })

    dag = documents["dag"]
    legacy = documents["legacy"]
    if (
        dag.get("authority_role") != "V28_COMPATIBILITY_ADAPTER_ONLY"
        or legacy.get("authority_role") != "V28_COMPATIBILITY_ADAPTER_ONLY"
        or dag.get("active_control_plane_ref") != paths["manifest"]
        or legacy.get("active_control_plane_ref") != paths["manifest"]
        or dag.get("successor_execution_allowed") is not False
        or legacy.get("successor_execution_allowed") is not False
        or (root / "V2_9_CONTROL_KERNEL_MANIFEST.json").exists()
    ):
        findings.append({
            "code": "V2_9_EPOCH1_AUTHORITY_REACTIVATED",
            "message": "legacy topology or Epoch 1 descriptor regained active authority",
        })

    findings.extend(
        run_epoch18_candidate_runtime(
            root,
            {"required_adversarial_cases": sorted(runtime_expected_cases)},
        )
    )
    return findings

    try:
        from harness_foundry_runtime.closure_lanes import (
            ClosureLaneError,
            derive_anti_replay_token,
            evaluate_final_release,
            seal_receipt,
            seal_release_context,
        )
        from harness_foundry_runtime.complexity_governor import evaluate_complexity
        from harness_foundry_runtime.evidence_projection import (
            ProjectionConflictError,
            rebuild_projection,
        )
        from harness_foundry_runtime.recovery_decision import decide_recovery
        from harness_foundry_runtime.identity_derivation import (
            IdentityDerivationError,
            build_machine_grant_binding,
            classify_identity_change,
            derive_identity_bundle,
        )

        recovery_base = {
            "command_receipt_status": "VALID",
            "effect_certainty": "NO_EFFECT",
            "result_receipt_status": "MISSING",
            "event_commit_state": "NOT_COMMITTED",
            "grant_state": "ACTIVE",
            "checkpoint_status": "VALID",
            "retry_budget_remaining": 1,
        }
        decisions = {
            decide_recovery({**recovery_base, "result_receipt_status": "VALID", "event_commit_state": "COMMITTED"})["decision"],
            decide_recovery({**recovery_base, "effect_certainty": "COMMITTED", "result_receipt_status": "PRESENT_UNVALIDATED"})["decision"],
            decide_recovery(recovery_base)["decision"],
            decide_recovery({**recovery_base, "effect_certainty": "UNKNOWN"})["decision"],
        }
        if decisions != {
            "RESULT_VALIDATION_ONLY",
            "FINALIZATION_ONLY",
            "RETRY_EXECUTOR",
            "HUMAN_RISK_REVIEW",
        }:
            raise ValueError(f"recovery modes={sorted(decisions)}")
        complexity_base = {
            "active_bespoke_paths_before": 2,
            "active_bespoke_paths_after": 1,
            "new_node_specific_authorized_paths": 0,
            "new_fixed_attempt_or_receipt_ids_in_core": 0,
            "generic_path_added": True,
            "retired_authoritative_paths": 1,
            "human_gate_added": False,
            "human_gate_has_risk_delta_or_external_boundary": False,
            "control_fault_fingerprint_occurrences": 1,
        }
        complexity_result = evaluate_complexity(complexity_base)
        if complexity_result["decision"] != "PASS":
            raise ValueError("complexity PASS fixture failed")
        if set(complexity_result.get("outputs", {})) != {
            "complexity_baseline",
            "complexity_delta",
            "retirement_manifest",
            "human_cost_result",
            "circuit_breaker_decision_receipt",
        } or "assessment_sha256" not in complexity_result:
            raise ValueError("complexity aggregate output fixture failed")
        if evaluate_complexity({**complexity_base, "control_fault_fingerprint_occurrences": 2})["decision"] != "ARCHITECTURE_REVIEW_REQUIRED":
            raise ValueError("complexity circuit breaker fixture failed")
        def semantic_input(contract_id: str) -> dict[str, Any]:
            return {
                "contract_id": contract_id,
                "contract_version": "1",
                "normative_behavior_sha256": "1" * 64,
                "input_schema_sha256": "2" * 64,
                "output_schema_sha256": "3" * 64,
                "invariants_sha256": "4" * 64,
            }

        def implementation_input(release_id: str) -> dict[str, Any]:
            return {
                "release_id": release_id,
                "exact_executor_bytes_sha256": ("5" if release_id == "1" else "6") * 64,
                "artifact_bytes_sha256": "7" * 64,
                "sbom_sha256": "8" * 64,
                "provenance_sha256": "9" * 64,
                "toolchain_sha256": "a" * 64,
            }

        risk_input = {
            "risk_profile_id": "LOW",
            "scope_sha256": "b" * 64,
            "permissions_sha256": "c" * 64,
            "write_roots_sha256": "d" * 64,
            "network_policy_sha256": "e" * 64,
            "secret_access_policy_sha256": "f" * 64,
            "external_effect_class": "READ_ONLY",
            "budget_sha256": "0" * 64,
            "stop_gates_sha256": "1" * 64,
        }
        current_state = {
            "authority_scope": "PROGRAM",
            "instance_id": "INSTANCE-1",
            "state_revision": 50,
            "current_state_sha256": "2" * 64,
            "event_store_tip_sha256": "3" * 64,
        }
        identity_a = derive_identity_bundle(
            semantic_contract=semantic_input("A"),
            implementation_release=implementation_input("1"),
            authorization_risk=risk_input,
            current_state=current_state,
        )
        identity_impl = derive_identity_bundle(
            semantic_contract=semantic_input("A"),
            implementation_release=implementation_input("2"),
            authorization_risk=risk_input,
            current_state=current_state,
        )
        identity_semantic = derive_identity_bundle(
            semantic_contract=semantic_input("B"),
            implementation_release=implementation_input("2"),
            authorization_risk=risk_input,
            current_state=current_state,
        )
        if classify_identity_change(identity_a, identity_impl)["change_class"] != "MACHINE_GRANT_REBIND_REQUIRED":
            raise ValueError("implementation-only identity change was not machine-routed")
        if classify_identity_change(identity_impl, identity_semantic)["change_class"] != "HUMAN_REAUTHORIZATION_REQUIRED":
            raise ValueError("semantic identity change was not human-routed")
        grant_binding = build_machine_grant_binding(
            identity_impl,
            authoritative_current_state=current_state,
            exact_executor_release_sha256="b" * 64,
            exact_artifact_release_sha256="c" * 64,
        )
        if grant_binding.get("machine_grant_issued") is not False or grant_binding.get("creates_authority") is not False:
            raise ValueError("machine Grant binding created authority")
        try:
            derive_identity_bundle(
                semantic_contract=semantic_input("A"),
                implementation_release={},
                authorization_risk=risk_input,
                current_state=current_state,
            )
        except IdentityDerivationError:
            pass
        else:
            raise ValueError("omitted identity dimension did not fail closed")

        try:
            build_machine_grant_binding(
                identity_impl,
                authoritative_current_state={
                    **current_state,
                    "state_revision": 49,
                    "current_state_sha256": "4" * 64,
                },
                exact_executor_release_sha256="b" * 64,
                exact_artifact_release_sha256="c" * 64,
            )
        except IdentityDerivationError:
            pass
        else:
            raise ValueError("recomputed stale current state did not fail closed")

        binding = {
            "authority_scope": "PROGRAM",
            "instance_id": "INSTANCE-1",
            "requirement_epoch": 17,
            "semantic_contract_identity_sha256": identity_a[
                "semantic_contract_identity_sha256"
            ],
            "authorization_risk_identity_sha256": identity_a[
                "authorization_risk_identity_sha256"
            ],
        }
        issuer_keys = ("PRODUCT", "SAFETY", "RELEASE", "COMPATIBILITY_LINKAGE")
        context_body = {
            "schema_version": "2.9",
            **binding,
            "state_revision": 50,
            "current_state_sha256": "2" * 64,
            "event_store_tip_sha256": "3" * 64,
            "authorized_issuers": {
                key: {
                    "issuer_control_domain_id": f"DOMAIN-{key}",
                    "issuance_event_id": f"EVENT-{key}",
                    "issuance_event_revision": index + 1,
                    "issuance_event_sha256": format(index + 10, "064x"),
                }
                for index, key in enumerate(issuer_keys)
            },
            "consumed_receipt_ids": [],
        }
        trusted_context = seal_release_context(context_body)

        def runtime_receipt(kind: str, receipt_id: str, context: Mapping[str, Any]) -> dict[str, Any]:
            body = {
                "schema_version": "2.9",
                **({"lane_id": kind} if kind != "COMPATIBILITY_LINKAGE" else {}),
                "status": "CLOSED" if kind != "COMPATIBILITY_LINKAGE" else "PASS",
                **{field: context[field] for field in (
                    "authority_scope", "instance_id", "requirement_epoch",
                    "semantic_contract_identity_sha256",
                    "authorization_risk_identity_sha256",
                )},
                "receipt_id": receipt_id,
                **context["authorized_issuers"][kind],
                "release_context_sha256": context["release_context_sha256"],
                "creates_authority": False,
            }
            body["anti_replay_token"] = derive_anti_replay_token(body)
            return seal_receipt(body)

        lane_receipts = [
            runtime_receipt(lane, f"RECEIPT-{lane}", trusted_context)
            for lane in ("PRODUCT", "SAFETY", "RELEASE")
        ]
        linkage_receipt = runtime_receipt(
            "COMPATIBILITY_LINKAGE", "RECEIPT-LINKAGE", trusted_context
        )
        proposal = evaluate_final_release(
            lane_receipts,
            compatibility_linkage_receipt=linkage_receipt,
            trusted_release_context=trusted_context,
            current_event_store_tip_sha256=trusted_context["event_store_tip_sha256"],
        )
        if (
            proposal["decision"] != "RELEASE_ELIGIBILITY_PROPOSAL_NOT_AUTHORITY"
            or proposal["release_ready_committed"] is not False
            or proposal["creates_authority"] is not False
        ):
            raise ValueError("three-lane evaluator created release authority")

        def reseal(item: Mapping[str, Any], **updates: Any) -> dict[str, Any]:
            body = {key: value for key, value in item.items() if key != "receipt_sha256"}
            body.update(updates)
            body["anti_replay_token"] = derive_anti_replay_token(body)
            return seal_receipt(body)

        stale_all = [reseal(item, requirement_epoch=16) for item in lane_receipts]
        forged_all = [reseal(item, issuance_event_sha256="e" * 64) for item in lane_receipts]
        wrong_issuer = list(lane_receipts)
        wrong_issuer[0] = reseal(wrong_issuer[0], issuer_control_domain_id="DOMAIN-WRONG")
        duplicate = list(lane_receipts)
        duplicate[1] = reseal(duplicate[1], receipt_id=duplicate[0]["receipt_id"])
        closure_cases = {
            "UNIFORMLY_STALE_ALL_RECEIPTS": (stale_all, linkage_receipt, trusted_context, "3" * 64),
            "UNIFORMLY_FORGED_ALL_RECEIPTS": (forged_all, linkage_receipt, trusted_context, "3" * 64),
            "WRONG_AUTHORIZED_ISSUER": (wrong_issuer, linkage_receipt, trusted_context, "3" * 64),
            "DUPLICATE_RECEIPT_ID": (duplicate, linkage_receipt, trusted_context, "3" * 64),
            "EVENT_STORE_TIP_CHANGED_BEFORE_ATOMIC_COMMIT": (lane_receipts, linkage_receipt, trusted_context, "f" * 64),
        }
        consumed_context = seal_release_context({
            **{key: value for key, value in trusted_context.items() if key != "release_context_sha256"},
            "consumed_receipt_ids": ["RECEIPT-PRODUCT"],
        })
        consumed_lanes = [
            runtime_receipt(lane, f"RECEIPT-{lane}", consumed_context)
            for lane in ("PRODUCT", "SAFETY", "RELEASE")
        ]
        consumed_linkage = runtime_receipt(
            "COMPATIBILITY_LINKAGE", "RECEIPT-LINKAGE", consumed_context
        )
        closure_cases["ALREADY_CONSUMED_RECEIPT_REPLAY"] = (
            consumed_lanes, consumed_linkage, consumed_context, "3" * 64
        )
        rejected_cases = {"RECOMPUTED_STALE_CURRENT_STATE_BUNDLE"}
        for case_name, (case_lanes, case_linkage, case_context, case_tip) in closure_cases.items():
            try:
                evaluate_final_release(
                    case_lanes,
                    compatibility_linkage_receipt=case_linkage,
                    trusted_release_context=case_context,
                    current_event_store_tip_sha256=case_tip,
                )
            except ClosureLaneError:
                rejected_cases.add(case_name)
            else:
                raise ValueError(f"{case_name} did not fail closed")
        if rejected_cases != set(epoch17_remediation["required_adversarial_cases"]):
            raise ValueError("production adversarial verdict set drifted")
        events = [{
            "authority_scope": "PROGRAM",
            "instance_id": "P-1",
            "fact_key": "status",
            "fact_value": "READY",
            "revision": 1,
            "event_sha256": "a" * 64,
            "retention_class": "ACTIVE_BASELINE",
        }]
        if rebuild_projection(events).get("projection_rebuildable") is not True:
            raise ValueError("projection rebuild fixture failed")
        try:
            rebuild_projection(events + [{**events[0], "fact_value": "BLOCKED", "event_sha256": "b" * 64}])
        except ProjectionConflictError:
            pass
        else:
            raise ValueError("projection conflict did not fail closed")
    except Exception as exc:
        findings.append({
            "code": "V2_9_EPOCH2_RUNTIME_FIXTURE_INVALID",
            "message": str(exc),
        })
    return findings


def run_epoch18_candidate_runtime(
    root: Path,
    remediation: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Execute Candidate production against temporary native Event Stores."""

    expected = set(remediation.get("required_adversarial_cases") or [])
    rejected: set[str] = set()
    test_authority_temp: tempfile.TemporaryDirectory[str] | None = None
    original_candidate_root = None
    try:
        import harness_foundry_runtime.authority_adapter as adapter_module
        from harness_foundry_runtime.authority_adapter import (
            AuthorityAdapterError,
            LOGICAL_DATABASE_REF,
            ReleaseArtifactBytesResolver,
            SQLiteEventStoreAuthorityAdapter,
            adapter_entrypoint_sha256,
            build_adapter_binding,
        )
        from harness_foundry_runtime.closure_lanes import (
            ClosureLaneError,
            derive_anti_replay_token,
            evaluate_final_release,
            seal_receipt,
        )
        from harness_foundry_runtime.identity_derivation import (
            IdentityDerivationError,
            build_machine_grant_binding,
            derive_identity_bundle,
        )

        test_authority_temp = tempfile.TemporaryDirectory()
        test_candidate_root = Path(test_authority_temp.name).resolve()
        test_private_key = Ed25519PrivateKey.generate()
        public_bytes = test_private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        trust_root = {
            "schema_version": "2.9",
            "trust_root_id": "STANDALONE-SELF-CHECK-TRUST-ROOT",
            "algorithm": "ED25519",
            "public_key_base64": base64.b64encode(public_bytes).decode("ascii"),
            "public_key_sha256": hashlib.sha256(public_bytes).hexdigest(),
            "purpose": "VERIFY_EVENT_STORE_BINDING_AND_RELEASE_COMMIT_AUTHORIZATION",
            "private_key_packaged": False,
            "creates_authority": False,
            "status": "PINNED_VERIFICATION_ROOT_NOT_AUTHORIZATION",
        }
        trust_root["trust_root_sha256"] = json_hash(trust_root)
        (test_candidate_root / "AUTHORITY_TRUST_ROOT.json").write_text(
            json.dumps(trust_root, ensure_ascii=False, indent=2, sort_keys=True) + "\\n",
            encoding="utf-8",
        )
        adapter_contract = json.loads(
            (root / "EVENT_STORE_AUTHORITY_ADAPTER_CONTRACT.json").read_text(
                encoding="utf-8"
            )
        )
        (test_candidate_root / "EVENT_STORE_AUTHORITY_ADAPTER_CONTRACT.json").write_text(
            json.dumps(adapter_contract, ensure_ascii=False, indent=2, sort_keys=True) + "\\n",
            encoding="utf-8",
        )
        original_candidate_root = adapter_module._candidate_root
        adapter_module._candidate_root = lambda: test_candidate_root

        semantic = {
            "contract_id": "A", "contract_version": "1",
            "normative_behavior_sha256": "1" * 64,
            "input_schema_sha256": "2" * 64,
            "output_schema_sha256": "3" * 64,
            "invariants_sha256": "4" * 64,
        }
        implementation = {
            "release_id": "1", "exact_executor_bytes_sha256": "5" * 64,
            "artifact_bytes_sha256": "7" * 64, "sbom_sha256": "8" * 64,
            "provenance_sha256": "9" * 64, "toolchain_sha256": "a" * 64,
        }
        risk = {
            "risk_profile_id": "LOW", "scope_sha256": "b" * 64,
            "permissions_sha256": "c" * 64, "write_roots_sha256": "d" * 64,
            "network_policy_sha256": "e" * 64,
            "secret_access_policy_sha256": "f" * 64,
            "external_effect_class": "READ_ONLY", "budget_sha256": "0" * 64,
            "stop_gates_sha256": "1" * 64,
        }
        semantic_id = json_hash({
            "identity_id": "SEMANTIC_CONTRACT_IDENTITY",
            "normative_fields": semantic,
        })
        risk_id = json_hash({
            "identity_id": "AUTHORIZATION_RISK_IDENTITY",
            "normative_fields": risk,
        })
        program_id = "PROGRAM-EPOCH18-STANDALONE"
        database_identity = "9" * 64
        authority = {
            "authority_scope": "PROGRAM",
            "instance_id": "INSTANCE-1",
            "requirement_epoch": 18,
            "semantic_contract_identity_sha256": semantic_id,
            "authorization_risk_identity_sha256": risk_id,
        }
        artifact_paths = {
            "candidate_content_sha256": test_candidate_root / "candidate.bundle",
            "requirement_ir_sha256": test_candidate_root / "requirement-ir.json",
            "executor_release_sha256": test_candidate_root / "executor.bin",
            "human_gate_receipt_sha256": test_candidate_root / "human-gate.json",
        }
        for index, path in enumerate(artifact_paths.values(), 1):
            path.write_bytes(f"standalone-release-artifact-{index}".encode("utf-8"))
        artifact_resolver = ReleaseArtifactBytesResolver(artifact_paths)
        release_artifacts = artifact_resolver.resolve_hashes()

        def create_store(
            path: Path,
            artifact_hashes: Mapping[str, str] | None = None,
        ) -> str:
            connection = sqlite3.connect(str(path))
            connection.executescript("""
                CREATE TABLE control_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    program_id TEXT NOT NULL,
                    stream_revision INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_event_hash TEXT,
                    event_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    UNIQUE(program_id, stream_revision)
                );
                CREATE TABLE control_idempotency (
                    program_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    events_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(program_id, idempotency_key)
                );
                CREATE TRIGGER control_events_reject_update
                BEFORE UPDATE ON control_events BEGIN
                    SELECT RAISE(ABORT, 'control_events is append-only'); END;
                CREATE TRIGGER control_events_reject_delete
                BEFORE DELETE ON control_events BEGIN
                    SELECT RAISE(ABORT, 'control_events is append-only'); END;
            """)
            connection.commit()
            connection.close()
            tip: str | None = None
            events = [
                ("CONTROL_EVENT_STORE_ACTIVATED", {
                    "database_identity_sha256": database_identity,
                    "logical_database_ref": LOGICAL_DATABASE_REF,
                }),
                ("CURRENT_STATE_COMMITTED", {
                    **authority,
                    "current_state_sha256": "c" * 64,
                    **dict(artifact_hashes or release_artifacts),
                }),
                *[("CLOSURE_RECEIPT_ISSUED", {
                    "receipt_kind": kind,
                    "receipt_id": f"RECEIPT-{kind}" if kind != "COMPATIBILITY_LINKAGE" else "RECEIPT-LINKAGE",
                    "issuer_control_domain_id": f"DOMAIN-{kind}",
                    **authority,
                }) for kind in ("PRODUCT", "SAFETY", "RELEASE", "COMPATIBILITY_LINKAGE")],
            ]
            for event_type, payload in events:
                tip = append_event(path, event_type, payload, tip)
            return str(tip)

        def append_event(
            path: Path,
            event_type: str,
            payload: Mapping[str, Any],
            previous: str | None,
        ) -> str:
            connection = sqlite3.connect(str(path))
            revision = int(connection.execute(
                "SELECT COUNT(*) FROM control_events WHERE program_id = ?",
                (program_id,),
            ).fetchone()[0]) + 1
            identity = {
                "program_id": program_id,
                "stream_revision": revision,
                "event_type": event_type,
                "payload": dict(payload),
                "previous_event_hash": previous,
                "created_at": "2026-08-06T00:00:00Z",
            }
            event_id = f"CEVT-{json_hash(identity)[:32].upper()}"
            event = {"schema_version": "2.9", "event_id": event_id, **identity}
            event_hash = json_hash(event)
            connection.execute(
                "INSERT INTO control_events(event_id, program_id, stream_revision, event_type, payload_json, previous_event_hash, event_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, program_id, revision, event_type,
                 json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                 previous, event_hash, "2026-08-06T00:00:00Z"),
            )
            connection.commit()
            connection.close()
            return event_hash

        def make_adapter(
            path: Path,
            *,
            authority_key: Ed25519PrivateKey | None = None,
            unsigned: bool = False,
            artifact_resolver_override: Any = None,
            **updates: Any,
        ) -> SQLiteEventStoreAuthorityAdapter:
            body = {
                "schema_version": "2.9",
                "adapter_id": "V29_SQLITE_EVENT_STORE_AUTHORITY_ADAPTER_V1",
                "program_id": program_id,
                "authority_scope": "PROGRAM",
                "instance_id": "INSTANCE-1",
                "requirement_epoch": 18,
                "database_identity_sha256": database_identity,
                "logical_database_ref": LOGICAL_DATABASE_REF,
                "adapter_implementation_sha256": file_hash(Path(adapter_module.__file__)),
                "adapter_entrypoint_sha256": adapter_entrypoint_sha256(),
                "adapter_contract_sha256": adapter_contract["contract_sha256"],
            }
            body.update(updates)
            authority_receipt = {
                "schema_version": "2.9",
                "receipt_kind": "AUTHORITY_BINDING_RECEIPT",
                "receipt_id": "STANDALONE-BINDING-AUTHORITY",
                "issuer_role": "CONTROL_PLANE_AUTHORITY",
                "trust_root_id": trust_root["trust_root_id"],
                "issued_at": "2026-08-01T00:00:00Z",
                "not_before": "2026-08-01T00:00:00Z",
                "expires_at": "2099-08-01T00:00:00Z",
                "revoked": False,
                "one_shot": False,
                "authorization_purpose": "EVENT_STORE_ADAPTER_BINDING",
                **{key: value for key, value in body.items() if key != "adapter_id"},
            }
            signing_key = authority_key or test_private_key
            authority_receipt["signature_base64"] = (
                "" if unsigned else base64.b64encode(
                signing_key.sign(
                    json.dumps(
                        authority_receipt,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ).encode("utf-8")
                )
            ).decode("ascii"))
            body["authority_binding_receipt"] = authority_receipt
            return SQLiteEventStoreAuthorityAdapter(
                path,
                build_adapter_binding(
                    body,
                    receiver_trust_anchor=trust_root,
                ),
                receiver_trust_anchor=trust_root,
                artifact_resolver=(
                    artifact_resolver
                    if artifact_resolver_override is None
                    else artifact_resolver_override
                ),
            )

        def receipts(adapter: SQLiteEventStoreAuthorityAdapter) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            context = adapter.read_release_context()
            def receipt(kind: str, receipt_id: str) -> dict[str, Any]:
                body = {
                    "schema_version": "2.9",
                    **({"lane_id": kind} if kind != "COMPATIBILITY_LINKAGE" else {}),
                    "status": "CLOSED" if kind != "COMPATIBILITY_LINKAGE" else "PASS",
                    **{field: context[field] for field in authority},
                    "receipt_id": receipt_id,
                    **context["authorized_issuers"][kind],
                    "release_context_sha256": context["release_context_sha256"],
                    "creates_authority": False,
                }
                body["anti_replay_token"] = derive_anti_replay_token(body)
                return seal_receipt(body)
            return (
                [receipt(lane, f"RECEIPT-{lane}") for lane in ("PRODUCT", "SAFETY", "RELEASE")],
                receipt("COMPATIBILITY_LINKAGE", "RECEIPT-LINKAGE"),
            )

        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "control-events.sqlite3"
            tip = create_store(database)
            adapter = make_adapter(database)
            lane_receipts, linkage = receipts(adapter)
            proposal = evaluate_final_release(
                lane_receipts,
                compatibility_linkage_receipt=linkage,
                authority_adapter=adapter,
            )
            if proposal.get("decision") != "RELEASE_ELIGIBILITY_PROPOSAL_NOT_AUTHORITY":
                raise ValueError("production release proposal fixture failed")

            class FakeAdapter:
                pass
            try:
                evaluate_final_release(
                    lane_receipts,
                    compatibility_linkage_receipt=linkage,
                    authority_adapter=FakeAdapter(),
                )
            except ClosureLaneError:
                rejected.update({
                    "FULLY_FORGED_CONTEXT_AND_ALL_RECEIPTS_WITH_RECOMPUTED_HASHES",
                    "FAKE_ADAPTER_OBJECT",
                })
            try:
                make_adapter(database, adapter_implementation_sha256="0" * 64)
            except AuthorityAdapterError:
                rejected.add("WRONG_ADAPTER_IMPLEMENTATION_SHA256")
            try:
                make_adapter(database, database_identity_sha256="0" * 64)
            except AuthorityAdapterError:
                rejected.add("FORGED_EVENT_STORE_WITH_WRONG_AUTHORIZED_DATABASE_IDENTITY")
            try:
                make_adapter(database, unsigned=True)
            except AuthorityAdapterError:
                rejected.add("UNSIGNED_MATCHING_EVENT_STORE_BINDING")
            try:
                make_adapter(database, authority_key=Ed25519PrivateKey.generate())
            except AuthorityAdapterError:
                rejected.update({
                    "FORGED_EVENT_STORE_AND_MATCHING_BINDING_WITH_ATTACKER_SIGNATURE",
                    "CANDIDATE_LOCAL_TRUST_ANCHOR_SUBSTITUTION",
                })
            try:
                make_adapter(database, artifact_resolver_override=object())
            except AuthorityAdapterError:
                rejected.add("FAKE_ARTIFACT_BYTES_RESOLVER")
            try:
                make_adapter(database, adapter_contract_sha256="0" * 64)
            except AuthorityAdapterError:
                rejected.add("WRONG_ACTUAL_ADAPTER_CONTRACT_HASH")

            bundle = derive_identity_bundle(
                semantic_contract=semantic,
                implementation_release=implementation,
                authorization_risk=risk,
                authority_adapter=adapter,
            )
            tip = append_event(database, "CURRENT_STATE_COMMITTED", {
                **authority,
                "current_state_sha256": "d" * 64,
                **release_artifacts,
            }, tip)
            try:
                build_machine_grant_binding(
                    bundle,
                    authority_adapter=adapter,
                    exact_executor_release_sha256="b" * 64,
                    exact_artifact_release_sha256="c" * 64,
                )
            except IdentityDerivationError:
                rejected.add("RECOMPUTED_STALE_BUNDLE_PLUS_MATCHING_STALE_STATE")
            try:
                adapter.validate_precommit(proposal)
            except AuthorityAdapterError:
                rejected.add("EVENT_STORE_TIP_CHANGED_AFTER_EVALUATION_BEFORE_ATOMIC_COMMIT")

        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "control-events.sqlite3"
            tip = create_store(database)
            adapter = make_adapter(database)
            lane_receipts, linkage = receipts(adapter)
            proposal = evaluate_final_release(
                lane_receipts,
                compatibility_linkage_receipt=linkage,
                authority_adapter=adapter,
            )
            append_event(database, "CLOSURE_RECEIPT_SET_CONSUMED", {
                "receipt_ids": ["RECEIPT-PRODUCT"],
                "decision_sha256": proposal["decision_sha256"],
            }, tip)
            try:
                adapter.validate_precommit(proposal)
            except AuthorityAdapterError:
                rejected.add("RECEIPT_CONSUMED_AFTER_EVALUATION_BEFORE_ATOMIC_COMMIT")

        def release_authorization(
            proposal: Mapping[str, Any],
            context: Mapping[str, Any],
            signing_key: Ed25519PrivateKey,
        ) -> dict[str, Any]:
            body = {
                "schema_version": "2.9",
                "authorization_id": "AUTH-STANDALONE-RELEASE",
                "authorization_purpose": "RUNTIME_RELEASE_COMMIT",
                "issuer_role": "CONTROL_PLANE_AUTHORITY",
                "trust_root_id": trust_root["trust_root_id"],
                "issued_at": "2026-08-01T00:00:00Z",
                "not_before": "2026-08-01T00:00:00Z",
                "expires_at": "2099-08-01T00:00:00Z",
                "revoked": False,
                "one_shot": True,
                "program_id": program_id,
                **authority,
                **{
                    field: context[field]
                    for field in (
                        "candidate_content_sha256",
                        "requirement_ir_sha256",
                        "executor_release_sha256",
                        "human_gate_receipt_sha256",
                    )
                },
                "expected_control_state_sha256": context["current_state_sha256"],
                "authorized_event_store_tip_sha256": proposal[
                    "expected_event_store_tip_sha256"
                ],
                "proposal_decision_sha256": proposal["decision_sha256"],
                "lease_id": "LEASE-STANDALONE-RELEASE",
                "lease_expires_at": "2099-08-01T00:00:00Z",
                "fencing_token": 1,
                "idempotency_key": "IDEM-STANDALONE-RELEASE",
                "status": "AUTHORIZED",
            }
            body["signature_base64"] = base64.b64encode(
                signing_key.sign(
                    json.dumps(
                        body,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ).encode("utf-8")
                )
            ).decode("ascii")
            return body

        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "control-events.sqlite3"
            tip = create_store(database)
            adapter = make_adapter(database)
            lane_receipts, linkage = receipts(adapter)
            proposal = evaluate_final_release(
                lane_receipts,
                compatibility_linkage_receipt=linkage,
                authority_adapter=adapter,
            )
            forged = release_authorization(
                proposal,
                adapter.read_release_context(),
                Ed25519PrivateKey.generate(),
            )
            append_event(database, "RELEASE_COMMIT_AUTHORIZED", forged, tip)
            try:
                adapter.atomic_commit_release_ready(
                    proposal,
                    created_at="2026-08-06T00:02:00Z",
                )
            except AuthorityAdapterError:
                rejected.add("SELF_ASSERTED_RELEASE_COMMIT_AUTHORIZATION")

        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "control-events.sqlite3"
            synchronized_wrong = {
                field: "f" * 64 for field in release_artifacts
            }
            tip = create_store(database, synchronized_wrong)
            adapter = make_adapter(database)
            lane_receipts, linkage = receipts(adapter)
            proposal = evaluate_final_release(
                lane_receipts,
                compatibility_linkage_receipt=linkage,
                authority_adapter=adapter,
            )
            authorization = release_authorization(
                proposal,
                adapter.read_release_context(),
                test_private_key,
            )
            append_event(database, "RELEASE_COMMIT_AUTHORIZED", authorization, tip)
            try:
                adapter.atomic_commit_release_ready(
                    proposal,
                    created_at="2026-08-06T00:02:00Z",
                )
            except AuthorityAdapterError:
                rejected.add(
                    "SYNCHRONIZED_WRONG_ARTIFACT_HASHES_WITH_VALID_SIGNATURE"
                )

        for field in (
            "candidate_content_sha256",
            "requirement_ir_sha256",
            "executor_release_sha256",
            "human_gate_receipt_sha256",
        ):
            with tempfile.TemporaryDirectory() as temporary:
                database = Path(temporary) / "control-events.sqlite3"
                tip = create_store(database)
                adapter = make_adapter(database)
                lane_receipts, linkage = receipts(adapter)
                proposal = evaluate_final_release(
                    lane_receipts,
                    compatibility_linkage_receipt=linkage,
                    authority_adapter=adapter,
                )
                wrong = release_authorization(
                    proposal,
                    adapter.read_release_context(),
                    test_private_key,
                )
                wrong.pop("signature_base64")
                wrong[field] = "f" * 64
                wrong["signature_base64"] = base64.b64encode(
                    test_private_key.sign(
                        json.dumps(
                            wrong,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        ).encode("utf-8")
                    )
                ).decode("ascii")
                append_event(database, "RELEASE_COMMIT_AUTHORIZED", wrong, tip)
                try:
                    adapter.atomic_commit_release_ready(
                        proposal,
                        created_at="2026-08-06T00:02:00Z",
                    )
                except AuthorityAdapterError:
                    rejected.add(
                        "VALID_SIGNATURE_WRONG_" + field.removesuffix("_sha256").upper()
                        + "_SHA256"
                    )

        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "control-events.sqlite3"
            tip = create_store(database)
            adapter = make_adapter(database)
            lane_receipts, linkage = receipts(adapter)
            proposal = evaluate_final_release(
                lane_receipts,
                compatibility_linkage_receipt=linkage,
                authority_adapter=adapter,
            )
            authorized = release_authorization(
                proposal,
                adapter.read_release_context(),
                test_private_key,
            )
            append_event(database, "RELEASE_COMMIT_AUTHORIZED", authorized, tip)
            adapter.atomic_commit_release_ready(
                proposal,
                created_at="2026-08-06T00:02:00Z",
            )
            try:
                adapter.atomic_commit_release_ready(
                    proposal,
                    created_at="2026-08-06T00:03:00Z",
                )
            except AuthorityAdapterError:
                rejected.add("REPLAYED_SIGNED_RELEASE_COMMIT_AUTHORIZATION")
    except Exception as exc:
        if original_candidate_root is not None:
            adapter_module._candidate_root = original_candidate_root
        if test_authority_temp is not None:
            test_authority_temp.cleanup()
        return [{
            "code": "V2_9_EPOCH2_RUNTIME_FIXTURE_INVALID",
            "message": str(exc),
        }]
    if original_candidate_root is not None:
        adapter_module._candidate_root = original_candidate_root
    if test_authority_temp is not None:
        test_authority_temp.cleanup()
    if rejected != expected:
        return [{
            "code": "V2_9_EPOCH18_PRODUCTION_ADVERSARIAL_CASES_INVALID",
            "message": f"rejected={sorted(rejected)} expected={sorted(expected)}",
        }]
    return []


def check_parent_budget_isolation(
    frozen_ir: Mapping[str, Any],
) -> list[dict[str, str]]:
    target = frozen_ir.get("target")
    if not (
        isinstance(target, Mapping)
        and target.get("architecture_epoch") == 1
        and target.get("control_plane_epoch") == 1
    ):
        return []
    correction = (
        target.get("control_plane_architecture_correction")
        if isinstance(target, Mapping)
        else None
    )
    engine = (
        correction.get("generic_transition_engine")
        if isinstance(correction, Mapping)
        else None
    )
    if not isinstance(engine, Mapping) or not isinstance(
        engine.get("parent_budget_accounting"), Mapping
    ):
        return []
    try:
        from harness_foundry_runtime.control_kernel import _parent_usage

        projections = {
            "grant_ledger": {
                "derived_grants": {
                    "GRANT-A-1": {
                        "parent_authorization_id": "PARENT-A",
                        "outcome": "TEMPORARY_FAILURE",
                    },
                    "GRANT-A-2": {
                        "parent_authorization_id": "PARENT-A",
                        "outcome": "PASS",
                    },
                    "GRANT-B-1": {
                        "parent_authorization_id": "PARENT-B",
                        "outcome": "PASS",
                    },
                }
            },
            "program_control_state": {
                "completed_transitions": {
                    "PROFILE_READ_VALIDATION": {"grant_id": "GRANT-A-2"},
                    "PROFILE_INTERNAL_STATE": {"grant_id": "GRANT-B-1"},
                }
            },
            "human_cost_result": {"bounded_retry_count": 1},
        }
        first = _parent_usage(projections, "PARENT-A")
        second = _parent_usage(projections, "PARENT-B")
    except Exception as exc:
        return [
            {
                "code": "V2_9_PARENT_BUDGET_ISOLATION_INVALID",
                "message": str(exc),
            }
        ]
    if first != {"attempts": 2, "retries": 1, "transitions": 1} or second != {
        "attempts": 1,
        "retries": 0,
        "transitions": 1,
    }:
        return [
            {
                "code": "V2_9_PARENT_BUDGET_ISOLATION_INVALID",
                "message": f"PARENT-A={first}; PARENT-B={second}",
            }
        ]
    return []


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    findings: list[dict[str, str]] = []
    manifest_path = root / "validation/PORTABLE_FILE_MANIFEST.json"
    dag_path = root / "ENGINEERING_PROJECT_DAG.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        portability = json.loads(
            (root / "validation/PORTABILITY_MANIFEST.json").read_text(encoding="utf-8")
        )
        context = json.loads((root / "START_CONTEXT.json").read_text(encoding="utf-8"))
        package_identity = json.loads(
            (root / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8")
        )
        dag = json.loads(dag_path.read_text(encoding="utf-8"))
        matrix = json.loads(
            (root / "validation/DAG_PATH_CONTAINMENT_MATRIX.json").read_text(
                encoding="utf-8"
            )
        )
        receipt = json.loads(
            (root / "validation/HUMAN_REVIEW_CLOSURE_RECEIPT.json").read_text(
                encoding="utf-8"
            )
        )
        frozen_ir = json.loads(
            (root / "canonical_sources/FROZEN_REQUIREMENT_IR.json").read_text(
                encoding="utf-8"
            )
        )
        provenance = json.loads(
            (root / "FACTORY_PROVENANCE.json").read_text(encoding="utf-8")
        )
        source_manifest = json.loads(
            (root / "canonical_sources/SOURCE_MANIFEST.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "findings": [{"code": "MANIFEST_READ_ERROR", "message": str(exc)}]}, sort_keys=True))
        return 1

    expected_roots = {"candidate": CANDIDATE_URI, "execution": EXECUTION_URI}
    if (
        portability.get("logical_roots") != expected_roots
        or portability.get("resolved_paths_persisted") is not False
        or context.get("candidate_root") != CANDIDATE_URI
        or context.get("target_root") != CANDIDATE_URI
        or context.get("execution_root") != EXECUTION_URI
    ):
        findings.append({"code": "LOGICAL_ROOT_CONTRACT_INVALID", "message": "portable roots do not match the declared Resource URIs"})

    excluded = set(manifest.get("excluded_files", []))
    actual_files = {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file() and path.relative_to(root).as_posix() not in excluded
    }
    expected_files = manifest.get("files", {})
    if set(actual_files) != set(expected_files):
        findings.append({"code": "PORTABLE_INVENTORY_MISMATCH", "message": "file inventory differs from the signed portable manifest"})
    for relative, expected_hash in expected_files.items():
        path = actual_files.get(relative)
        if path is None or file_hash(path) != expected_hash:
            findings.append({"code": "PORTABLE_FILE_HASH_MISMATCH", "message": relative})
    portable_inventory = set(expected_files) | excluded
    findings.extend(check_candidate_uri_closure(root, portable_inventory))
    findings.extend(check_runtime_dependency_closure(root, portable_inventory))
    findings.extend(check_runtime_binding_contract(root, portability))

    recomputed_matrix = expected_matrix(dag_path, dag)
    if any(row["outside_success_output_refs"] for row in recomputed_matrix["rows"]):
        findings.append(
            {
                "code": "ENGINEERING_DAG_SUCCESS_OUTPUT_OUTSIDE_ALLOWED_WRITE_PATHS",
                "message": "one or more success outputs escape the declared write roots",
            }
        )
    if any(
        row["outside_workpack_artifact_refs"]
        for row in recomputed_matrix["rows"]
    ):
        findings.append(
            {
                "code": "ENGINEERING_DAG_WORKPACK_ARTIFACT_OUTSIDE_ALLOWED_WRITE_PATHS",
                "message": "one or more Workpack artifacts escape the declared write roots",
            }
        )
    if matrix != recomputed_matrix:
        findings.append(
            {
                "code": "DAG_PATH_CONTAINMENT_MATRIX_INVALID",
                "message": "the persisted matrix does not equal standalone recomputation",
            }
        )
    findings.extend(check_project_workpack_write_projection(root, dag))
    findings.extend(
        check_closure_receipt(
            root, frozen_ir, provenance, matrix, receipt, package_identity
        )
    )
    target = frozen_ir.get("target")
    epoch24_active = isinstance(target, Mapping) and isinstance(
        target.get("v0_24_human_review_remediation"), Mapping
    )
    local_authority_na, local_profile_findings = (
        local_profile_external_authority_disposition(root, frozen_ir)
    )
    findings.extend(local_profile_findings)
    receiver_authority_required = external_receiver_authority_required(
        root, frozen_ir
    )
    if receiver_authority_required:
        source_policy, source_policy_findings = load_receiver_source_authority_policy(
            root
        )
    else:
        source_policy, source_policy_findings = frozen_ir, []
    findings.extend(source_policy_findings)
    if source_policy is not None:
        if receiver_authority_required:
            findings.extend(
                check_source_authority_policy_context(frozen_ir, source_policy)
            )
            if "validation_report_binding" in source_policy:
                findings.extend(
                    check_validation_report_binding(root, source_policy)
                )
        findings.extend(
            check_source_authority_normalization(source_policy, source_manifest)
        )
        if receiver_authority_required:
            findings.extend(
                check_release_history_authority(frozen_ir, source_policy)
            )
    if epoch24_active:
        findings.extend(check_source_portable_uri_projection(root, source_manifest))
        findings.extend(check_portable_source_index(root, source_manifest))
    if receiver_authority_required and epoch24_active:
        findings.extend(
            check_epoch24_gate_adversarial_cases(
                root, frozen_ir, source_manifest, source_policy
            )
        )
        findings.extend(
            check_epoch26_portable_index_adversarial_cases(
                root, frozen_ir, source_manifest
            )
        )
    findings.extend(check_control_kernel(root, frozen_ir, receipt))
    findings.extend(
        check_release_closure_control_plane(root, frozen_ir, receipt)
    )
    findings.extend(check_parent_budget_isolation(frozen_ir))

    forbidden_scheme = "file" + "://"
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            findings.append({"code": "EXTERNAL_SYMLINK_FORBIDDEN", "message": relative})
            continue
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            findings.append({"code": "NON_UTF8_PORTABLE_TEXT", "message": relative})
            continue
        if LOCAL_PATH_RE.search(text) or forbidden_scheme in text:
            findings.append({"code": "LOCAL_PATH_BINDING", "message": relative})

    status = "PASS" if not findings else "FAIL"
    print(json.dumps({"schema_version": "1.0", "self_check_id": "HARNESS_FOUNDRY_PORTABLE_CANDIDATE_SELF_CHECK", "status": status, "candidate_root": CANDIDATE_URI, "file_count": len(actual_files), "findings": findings}, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
''',
    )


def _contract_identity_parts(value: Any) -> tuple[str, ...] | None:
    """Return a strict, comparable identity for a logical URI or absolute path."""

    text = str(value)
    for uri, identity in (
        (LOGICAL_CANDIDATE_ROOT, ("resource", "candidate")),
        (LOGICAL_EXECUTION_ROOT, ("resource", "execution")),
    ):
        if text == uri:
            return identity
        prefix = f"{uri}/"
        if text.startswith(prefix):
            suffix = text[len(prefix) :]
            pieces = suffix.split("/")
            if not pieces or any(piece in {"", ".", ".."} for piece in pieces):
                return None
            return (*identity, *pieces)
    if "://" in text:
        return None
    path = Path(text)
    raw_pieces = text.replace("\\", "/").split("/")
    if (
        not path.is_absolute()
        or any(piece in {".", ".."} for piece in raw_pieces)
    ):
        return None
    return ("filesystem", path.anchor, *path.parts[1:])


def _contract_path_is_contained(value: Any, allowed_root: Any) -> bool:
    value_parts = _contract_identity_parts(value)
    root_parts = _contract_identity_parts(allowed_root)
    return bool(
        value_parts is not None
        and root_parts is not None
        and value_parts[: len(root_parts)] == root_parts
    )


def _dag_path_containment_matrix(staging: Path) -> dict[str, Any]:
    dag_path = staging / "ENGINEERING_PROJECT_DAG.json"
    dag = json.loads(dag_path.read_text(encoding="utf-8"))
    workpack_artifact_refs_by_node: dict[str, list[str]] = {}
    for _project_id, directory in PROJECTS:
        index_path = (
            staging
            / "project_start_packages"
            / directory
            / "WORKPACK_INDEX.json"
        )
        if not index_path.is_file():
            continue
        index = json.loads(index_path.read_text(encoding="utf-8"))
        for raw_workpack in index.get("workpacks", []):
            workpack = raw_workpack if isinstance(raw_workpack, Mapping) else {}
            if workpack.get("program_control_surface") != "ENGINEERING_PROJECT_DAG":
                continue
            node_id = str(workpack.get("program_control_node_id") or "")
            if not node_id:
                continue
            refs = workpack_artifact_refs_by_node.setdefault(node_id, [])
            for artifact_ref in workpack.get("required_artifact_refs", []):
                if isinstance(artifact_ref, str) and artifact_ref not in refs:
                    refs.append(artifact_ref)
    rows: list[dict[str, Any]] = []
    for raw_node in dag.get("nodes", []):
        node = raw_node if isinstance(raw_node, Mapping) else {}
        node_id = str(node.get("node_id") or "")
        allowed = list(node.get("allowed_write_paths") or [])
        outputs = list(node.get("success_output_refs") or [])
        workpack_artifact_refs = workpack_artifact_refs_by_node.get(
            node_id, []
        )
        contained = [
            output
            for output in outputs
            if any(_contract_path_is_contained(output, root) for root in allowed)
        ]
        outside = [output for output in outputs if output not in contained]
        contained_workpack_artifact_refs = [
            artifact_ref
            for artifact_ref in workpack_artifact_refs
            if any(
                _contract_path_is_contained(artifact_ref, root)
                for root in allowed
            )
        ]
        outside_workpack_artifact_refs = [
            artifact_ref
            for artifact_ref in workpack_artifact_refs
            if artifact_ref not in contained_workpack_artifact_refs
        ]
        rows.append(
            {
                "node_id": node.get("node_id"),
                "allowed_write_paths": allowed,
                "success_output_refs": outputs,
                "contained_success_output_refs": contained,
                "outside_success_output_refs": outside,
                "workpack_artifact_refs": workpack_artifact_refs,
                "contained_workpack_artifact_refs": (
                    contained_workpack_artifact_refs
                ),
                "outside_workpack_artifact_refs": (
                    outside_workpack_artifact_refs
                ),
                "status": "PASS"
                if (
                    outputs
                    and len(contained) == len(outputs)
                    and not outside_workpack_artifact_refs
                )
                else "FAIL",
            }
        )
    pass_count = sum(row["status"] == "PASS" for row in rows)
    return {
        "schema_version": "1.0",
        "matrix_id": "DAG_PATH_CONTAINMENT_MATRIX",
        "dag_ref": "ENGINEERING_PROJECT_DAG.json",
        "dag_sha256": _file_hash(dag_path),
        "containment_contract": (
            "STRICT_RESOLVED_RESOURCE_IDENTITY_CONTAINMENT_NOT_STRING_PREFIX"
        ),
        "finding_code": (
            "ENGINEERING_DAG_SUCCESS_OUTPUT_OUTSIDE_ALLOWED_WRITE_PATHS"
        ),
        "workpack_artifact_finding_code": (
            "ENGINEERING_DAG_WORKPACK_ARTIFACT_OUTSIDE_ALLOWED_WRITE_PATHS"
        ),
        "node_count": len(rows),
        "pass_count": pass_count,
        "rows": rows,
        "status": "PASS" if rows and pass_count == len(rows) else "FAIL",
    }


def _write_dag_path_containment_matrix(staging: Path) -> None:
    _write_json(
        staging / "validation/DAG_PATH_CONTAINMENT_MATRIX.json",
        _dag_path_containment_matrix(staging),
    )


def _control_plane_generation_mode(requirement_ir: Mapping[str, Any]) -> str:
    target = requirement_ir.get("target")
    if not isinstance(target, Mapping):
        return LEGACY_MODE
    architecture_epoch = target.get("architecture_epoch")
    control_plane_epoch = target.get("control_plane_epoch")
    if architecture_epoch is None and control_plane_epoch is None:
        return LEGACY_MODE
    if architecture_epoch == 1 and control_plane_epoch == 1:
        correction = target.get("control_plane_architecture_correction")
        if not isinstance(correction, Mapping):
            raise ValueError("Epoch 1 control-plane correction is missing")
        return EPOCH1_MODE
    if architecture_epoch == 2 and control_plane_epoch == 2:
        remediation = target.get("release_closure_control_plane_remediation")
        alignment = target.get(
            "v0_15_epoch2_producer_validator_alignment_correction"
        )
        if not isinstance(remediation, Mapping) or not isinstance(
            alignment, Mapping
        ):
            raise ValueError("Epoch 2 remediation or alignment contract is missing")
        return EPOCH2_MODE
    if architecture_epoch == 4 and control_plane_epoch == 4:
        epoch4 = target.get("epoch4_architecture_control_plane_contract")
        epoch38 = target.get("v2_9_charter_architecture_correction_epoch38")
        if (
            not isinstance(epoch4, Mapping)
            or not isinstance(epoch38, Mapping)
            or epoch4.get("contract_status") != "NORMATIVE_REQUIREMENT"
            or epoch4.get("requirement_epoch") != 38
            or epoch4.get("architecture_epoch") != 4
            or epoch4.get("control_plane_epoch") != 4
            or epoch4.get("assurance_profile_id")
            != "SELF_USE_LOCAL_TRUSTED_OPERATOR"
            or target.get("assurance_profile_id")
            != "SELF_USE_LOCAL_TRUSTED_OPERATOR"
        ):
            raise ValueError("Epoch 4 local core generation contract is missing")
        return EPOCH4_MODE
    raise ValueError(
        "unsupported or mixed Architecture/Control Plane Epoch pair: "
        f"{architecture_epoch}/{control_plane_epoch}"
    )


def _validate_epoch4_generation_readiness(
    requirement_ir: Mapping[str, Any],
    readiness: Mapping[str, Any] | None,
) -> None:
    target = requirement_ir.get("target")
    if not isinstance(target, Mapping) or not isinstance(readiness, Mapping):
        raise ValueError("Epoch 4 generation requires a prewrite readiness binding")
    material = dict(readiness)
    claimed_sha256 = material.pop("generation_readiness_sha256", None)
    route = readiness.get("route_selection")
    bindings = readiness.get("bindings")
    active_requirement_epoch = readiness.get("requirement_epoch")
    if (
        claimed_sha256 != _json_hash(material)
        or readiness.get("status") != "PASS"
        or readiness.get("readiness_kind")
        != "EPOCH38_PROFILE_AWARE_CANDIDATE_GENERATION_PREFLIGHT"
        or readiness.get("program_id") != requirement_ir.get("program_id")
        or isinstance(active_requirement_epoch, bool)
        or not isinstance(active_requirement_epoch, int)
        or active_requirement_epoch < 38
        or readiness.get("architecture_epoch") != 4
        or readiness.get("control_plane_epoch") != 4
        or readiness.get("writes_performed") is not False
        or readiness.get("candidate_or_execution_root_created") is not False
        or readiness.get("execution_started") is not False
        or not isinstance(route, Mapping)
        or readiness.get("route_selection_sha256") != _json_hash(route)
        or route.get("assurance_profile")
        != "SELF_USE_LOCAL_TRUSTED_OPERATOR"
        or route.get("local_engineering_completion") != "CORE_RELEASE_READY_LOCAL"
        or route.get("external_certification_claimed") is not False
        or route.get("optional_security_hardening")
        not in {"NOT_APPLICABLE", "NOT_RUN"}
        or not isinstance(bindings, Mapping)
        or bindings.get("requirement_ir_sha256") != _json_hash(requirement_ir)
    ):
        raise ValueError("Epoch 4 generation readiness binding is stale or invalid")


def _epoch51_runtime_authority_negative_cases() -> list[dict[str, Any]]:
    return [
        {
            "case_id": "NEG-V29-E51-LOCAL-RUNTIME-AUTHORITY-CLAIM-DRIFT",
            "atom_ids": ["ATOM-V29-P0-08", "ATOM-V29-P0-10"],
            "description": (
                "A local runtime profile that claims external certification "
                "cannot treat receiver Authority as not applicable."
            ),
            "expected_failure": "SOURCE_AUTHORITY_POLICY_LOCK_REQUIRED",
            "fixture_kind": "NON_EXECUTABLE_JSON",
            "input_fixture": {
                "assurance_profile": "SELF_USE_LOCAL_TRUSTED_OPERATOR",
                "external_certification_claimed": True,
                "optional_security_hardening": "NOT_RUN",
                "receiver_authority_environment_present": False,
            },
            "origin": "EPOCH51_SELF_USE_LOCAL_RUNTIME_BIND_AUTHORITY_NA",
        },
        {
            "case_id": "NEG-V29-E51-OPTIONAL-HARDENING-AUTHORITY-OMISSION",
            "atom_ids": ["ATOM-V29-P0-08", "ATOM-V29-P0-10"],
            "description": (
                "Enabling optional security hardening without receiver "
                "Authority must fail closed."
            ),
            "expected_failure": "SOURCE_AUTHORITY_POLICY_LOCK_REQUIRED",
            "fixture_kind": "NON_EXECUTABLE_JSON",
            "input_fixture": {
                "assurance_profile": "SELF_USE_LOCAL_TRUSTED_OPERATOR",
                "external_certification_claimed": False,
                "optional_security_hardening": "ENABLED",
                "receiver_authority_environment_present": False,
            },
            "origin": "EPOCH51_SELF_USE_LOCAL_RUNTIME_BIND_AUTHORITY_NA",
        },
    ]


def _write_epoch4_generation_profile(
    staging: Path, readiness: Mapping[str, Any]
) -> None:
    route = dict(readiness["route_selection"])
    _write_json(
        staging / "EPOCH38_GENERATION_PROFILE.json",
        {
            "schema_version": "2.9",
            "profile_kind": "SELF_USE_LOCAL_CORE_CANDIDATE_ROUTE",
            "profile_origin_requirement_epoch": 38,
            "active_requirement_epoch": readiness["requirement_epoch"],
            "assurance_profile": route["assurance_profile"],
            "local_engineering_completion": route[
                "local_engineering_completion"
            ],
            "core_routes": route["core_routes"],
            "default_generation_release_steps": route[
                "default_generation_release_steps"
            ],
            "excluded_default_release_steps": route[
                "excluded_default_release_steps"
            ],
            "optional_security_routes": route["optional_security_routes"],
            "optional_security_hardening": route[
                "optional_security_hardening"
            ],
            "external_certification_claimed": False,
            "generation_readiness_sha256": readiness[
                "generation_readiness_sha256"
            ],
            "bindings": dict(readiness["bindings"]),
            "candidate_static_result": "DIAGNOSTIC_ONLY",
            "route_selection_authority": "EPOCH38_GENERATION_PROFILE.json",
            "legacy_three_project_topology_role": (
                "COMPATIBILITY_CATALOG_NOT_DEFAULT_EXECUTION_ROUTE"
            ),
            "external_trust_anchor": "NOT_APPLICABLE",
            "independent_oracle": "NOT_APPLICABLE",
            "dual_formal_validator_certification": "NOT_APPLICABLE",
            "dynamic_adversarial_or_tamper_proof": "NOT_APPLICABLE",
            "execution_started": False,
        },
    )
    if readiness["requirement_epoch"] >= 51:
        negative_path = staging / "validation/NEGATIVE_CASES.json"
        negative = json.loads(negative_path.read_text(encoding="utf-8"))
        cases = list(negative.get("cases") or [])
        existing = {
            str(case.get("case_id"))
            for case in cases
            if isinstance(case, Mapping)
        }
        additions = _epoch51_runtime_authority_negative_cases()
        cases.extend(
            case for case in additions if case["case_id"] not in existing
        )
        negative["cases"] = cases
        _write_json(negative_path, negative)


def _apply_epoch4_default_route_selection(staging: Path) -> None:
    """Annotate existing compatibility catalogs with the Epoch 38 active route."""

    profile_ref = "EPOCH38_GENERATION_PROFILE.json"
    profile_sha256 = _file_hash(staging / profile_ref)
    dag_path = staging / "ENGINEERING_PROJECT_DAG.json"
    dag = json.loads(dag_path.read_text(encoding="utf-8"))
    optional_nodes = [
        str(item.get("node_id"))
        for item in dag.get("nodes", [])
        if isinstance(item, Mapping)
        and str(item.get("node_id", "")).startswith(("LAB_", "LINKAGE_"))
    ]
    default_nodes = [
        str(item.get("node_id"))
        for item in dag.get("nodes", [])
        if isinstance(item, Mapping)
        and str(item.get("node_id")) not in optional_nodes
    ]
    default_edges = [
        {"from": left, "to": right}
        for left, right in zip(default_nodes, default_nodes[1:])
    ]
    compatibility_edges = list(dag.get("edges") or [])
    compatibility_only_progressions = {
        "MAIN_EXECUTION_BEFORE_LAB_AND_LINKAGE_SELF_VALIDATION",
        "MAIN_EXECUTION_PACKAGE_BEFORE_LAB_AND_LINKAGE_RELEASE",
    }
    legacy_forbidden_progressions = list(
        dag.get("forbidden_progressions") or []
    )
    active_forbidden_progressions = [
        value
        for value in legacy_forbidden_progressions
        if value not in compatibility_only_progressions
    ]
    optional_security_forbidden_progressions = [
        value
        for value in legacy_forbidden_progressions
        if value in compatibility_only_progressions
    ]
    for item in dag.get("nodes", []):
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("node_id"))
        selected = node_id in default_nodes
        item["default_route_selected"] = selected
        item["delivery_tier"] = (
            "CORE_IMPLEMENTATION" if selected else "OPTIONAL_SECURITY_HARDENING"
        )
        if selected:
            index = default_nodes.index(node_id)
            default_predecessors = (
                [default_nodes[index - 1]] if index else []
            )
            default_successors = (
                [default_nodes[index + 1]]
                if index + 1 < len(default_nodes)
                else []
            )
            item["default_route_predecessor_node_ids"] = default_predecessors
            item["default_route_next_node_ids"] = default_successors
            item["required_predecessor_nodes"] = default_predecessors
            item["requires"] = default_predecessors
            item["allowed_next_nodes"] = default_successors
            item["failure_return_node"] = (
                default_predecessors[0]
                if default_predecessors
                else item.get("failure_return_node")
            )
            item["required_tool_distribution_hashes"] = dict(
                EPOCH38_LOCAL_TOOL_DISTRIBUTION_REQUIREMENT
            )
            item["default_profile_required_capabilities"] = (
                list(EPOCH38_LOCAL_ROOT_MATERIALIZATION_REQUIRES)
                if node_id == "MAIN_EXECUTION_PACKAGE_MATERIALIZED"
                else []
            )
            if node_id == "START_PACKAGE_HUMAN_APPROVAL":
                item["produces_capabilities"] = list(
                    dict.fromkeys(
                        [*item.get("produces_capabilities", []), "PROFILE_LOCK_VALID"]
                    )
                )
            elif node_id == "MAIN_EXECUTION_PACKAGE_MATERIALIZED":
                item["project_workpack_required_capabilities"] = list(
                    EPOCH38_LOCAL_ROOT_MATERIALIZATION_REQUIRES
                )
        else:
            item["default_profile_disposition"] = "NOT_APPLICABLE_NOT_STARTED"
    dag.update(
        {
            "route_selection_authority_ref": profile_ref,
            "route_selection_authority_sha256": profile_sha256,
            "default_route_node_ids": default_nodes,
            "default_route_edges": default_edges,
            "active_route_edge_field": "default_route_edges",
            "edges_role": (
                "COMPATIBILITY_CATALOG_NOT_ACTIVE_DEFAULT_EXECUTION_ROUTE"
            ),
            "compatibility_catalog_edges": compatibility_edges,
            "optional_security_node_ids": optional_nodes,
            "fixed_node_order_role": (
                "COMPATIBILITY_CATALOG_ORDER_NOT_DEFAULT_EXECUTION_ROUTE"
            ),
            "forbidden_progressions": active_forbidden_progressions,
            "forbidden_progressions_role": "ACTIVE_DEFAULT_ROUTE_ONLY",
            "optional_security_forbidden_progressions": (
                optional_security_forbidden_progressions
            ),
            "optional_security_forbidden_progressions_role": (
                "OPTIONAL_SECURITY_HARDENING_ONLY_NOT_ACTIVE_DEFAULT_ROUTE"
            ),
        }
    )
    _write_json(dag_path, dag)

    root_index_path = staging / "WORKPACK_INDEX.json"
    if root_index_path.is_file():
        root_index = json.loads(root_index_path.read_text(encoding="utf-8"))
        root_workpacks = root_index.get("workpacks", [])
        if root_workpacks and isinstance(root_workpacks[0], dict):
            root_workpack = root_workpacks[0]
            root_workpack["requires"] = list(
                EPOCH38_LOCAL_ROOT_MATERIALIZATION_REQUIRES
            )
            root_workpack["requirement_sources"] = dict(
                EPOCH38_LOCAL_ROOT_MATERIALIZATION_REQUIREMENT_SOURCES
            )
            capsule_path = staging / str(root_workpack.get("capsule_ref"))
            if capsule_path.is_file():
                capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
                capsule["requires"] = list(
                    EPOCH38_LOCAL_ROOT_MATERIALIZATION_REQUIRES
                )
                capsule["requirement_sources"] = dict(
                    EPOCH38_LOCAL_ROOT_MATERIALIZATION_REQUIREMENT_SOURCES
                )
                _write_json(capsule_path, capsule)
                _write_json(staging / "CAPSULE.json", capsule)
            workpack_path = staging / str(root_workpack.get("workpack_ref"))
            if workpack_path.is_file():
                workpack_text = workpack_path.read_text(encoding="utf-8")
                workpack_text = re.sub(
                    r"(?m)^- Required capabilities:.*$",
                    "- Required capabilities: "
                    + ", ".join(EPOCH38_LOCAL_ROOT_MATERIALIZATION_REQUIRES),
                    workpack_text,
                )
                _write_text(workpack_path, workpack_text)
        _write_json(root_index_path, root_index)

    release_path = staging / "RELEASE_PIPELINE_MANIFEST.json"
    release = json.loads(release_path.read_text(encoding="utf-8"))
    default_steps = ["P4_RELEASE_CANDIDATE_LOCK"]
    explicitly_excluded = {
        "P4_CERTIFIED_RELEASE_LOCK",
        "LAB_INSTALLED_POSITIVE_NEGATIVE_TAMPER_TESTS",
        "LINKAGE_A_INTERFACE_COMPLETENESS",
        "LINKAGE_D_INSTALLED_HANDSHAKE",
    }
    for item in release.get("steps", []):
        if not isinstance(item, dict):
            continue
        step_id = str(item.get("step_id"))
        item["default_route_selected"] = step_id in default_steps
        item["default_profile_disposition"] = (
            "POST_IMPLEMENTATION_VALIDATION"
            if step_id in default_steps
            else "OPTIONAL_SECURITY_HARDENING_NOT_SELECTED"
            if step_id in explicitly_excluded
            else "LEGACY_COMPATIBILITY_CATALOG_NOT_SELECTED"
        )
        if step_id in default_steps:
            item["default_profile_requires"] = list(
                EPOCH38_LOCAL_RELEASE_REQUIRES
            )
            item["default_route_predecessor_step_ids"] = []
            item["default_route_next_step_ids"] = []
            item["required_predecessor_step_ids"] = []
            item["requires"] = list(EPOCH38_LOCAL_RELEASE_REQUIRES)
            item["allowed_next_step_ids"] = []
            item["failure_return_step_id"] = "MAIN_P4_LOCAL_CLOSURE"
            item["required_tool_distribution_hashes"] = dict(
                EPOCH38_LOCAL_TOOL_DISTRIBUTION_REQUIREMENT
            )
            item["project_workpack_required_capabilities"] = list(
                EPOCH38_LOCAL_RELEASE_REQUIRES
            )
    release.update(
        {
            "route_selection_authority_ref": profile_ref,
            "route_selection_authority_sha256": profile_sha256,
            "default_route_step_ids": default_steps,
            "excluded_default_step_ids": sorted(explicitly_excluded),
            "fixed_step_order_role": (
                "COMPATIBILITY_CATALOG_ORDER_NOT_DEFAULT_EXECUTION_ROUTE"
            ),
        }
    )
    _write_json(release_path, release)

    projects_path = staging / "THREE_PROJECT_PROGRAM_MANIFEST.json"
    projects = json.loads(projects_path.read_text(encoding="utf-8"))
    for item in projects.get("projects", []):
        if not isinstance(item, dict):
            continue
        selected = item.get("project_id") == "MAIN_HARNESS_BUILD"
        item["default_route_selected"] = selected
        item["delivery_tier"] = (
            "CORE_IMPLEMENTATION" if selected else "OPTIONAL_SECURITY_HARDENING"
        )
        if not selected:
            item["default_profile_disposition"] = "NOT_APPLICABLE_NOT_STARTED"
    projects.update(
        {
            "route_selection_authority_ref": profile_ref,
            "route_selection_authority_sha256": profile_sha256,
            "default_route_project_ids": ["MAIN_HARNESS_BUILD"],
            "compatibility_catalog_retained": True,
        }
    )
    _write_json(projects_path, projects)

    main_index_path = staging / "project_start_packages/main_build/WORKPACK_INDEX.json"
    main_index = json.loads(main_index_path.read_text(encoding="utf-8"))
    for item in main_index.get("workpacks", []):
        if not isinstance(item, dict):
            continue
        item["default_route_selected"] = item.get("workpack_id") in {
            "MB-G0",
            "MB-P1",
            "MB-P2",
            "MB-P3",
            "MB-P4",
            "MB-RELEASE-CANDIDATE",
        }
        if item.get("workpack_id") == "MB-RELEASE-CANDIDATE":
            item["default_profile_requires"] = list(
                EPOCH38_LOCAL_RELEASE_REQUIRES
            )
            item["requires"] = list(EPOCH38_LOCAL_RELEASE_REQUIRES)
            item["requirement_sources"] = dict(
                EPOCH38_LOCAL_RELEASE_REQUIREMENT_SOURCES
            )
            capsule_path = main_index_path.parent / str(item.get("capsule_ref"))
            if capsule_path.is_file():
                capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
                capsule["requires"] = list(EPOCH38_LOCAL_RELEASE_REQUIRES)
                capsule["requirement_sources"] = dict(
                    EPOCH38_LOCAL_RELEASE_REQUIREMENT_SOURCES
                )
                _write_json(capsule_path, capsule)
            result_path = main_index_path.parent / str(item.get("result_ref"))
            if result_path.is_file():
                result = json.loads(result_path.read_text(encoding="utf-8"))
                result["required_capabilities"] = list(
                    EPOCH38_LOCAL_RELEASE_REQUIRES
                )
                _write_json(result_path, result)
            workpack_path = main_index_path.parent / str(item.get("workpack_ref"))
            if workpack_path.is_file():
                workpack_text = workpack_path.read_text(encoding="utf-8")
                workpack_text = re.sub(
                    r"(?m)^- Requires:.*$",
                    "- Requires: " + ", ".join(EPOCH38_LOCAL_RELEASE_REQUIRES),
                    workpack_text,
                )
                workpack_text = re.sub(
                    r"(?m)^- Requirement sources:.*$",
                    "- Requirement sources: "
                    + json.dumps(
                        EPOCH38_LOCAL_RELEASE_REQUIREMENT_SOURCES,
                        sort_keys=True,
                    ),
                    workpack_text,
                )
                _write_text(workpack_path, workpack_text)
    main_index.update(
        {
            "route_selection_authority_ref": profile_ref,
            "route_selection_authority_sha256": profile_sha256,
        }
    )
    _write_json(main_index_path, main_index)


def _control_plane_correction_enabled(requirement_ir: Mapping[str, Any]) -> bool:
    """Compatibility helper retained for callers that mean the Epoch 1 bundle."""

    return _control_plane_generation_mode(requirement_ir) == EPOCH1_MODE


def _correction_implementation_refs(correction_id: str) -> list[str]:
    refs = {
        "CORR-29-001": [
            "FACTORY_PROVENANCE.json",
            "canonical_sources/FROZEN_REQUIREMENT_IR.json",
            "V2_9_CONTROL_KERNEL_MANIFEST.json",
        ],
        "CORR-29-002": [
            "DECISION_POLICY.json",
            "TRANSITION_CONTRACTS.json",
            "tools/harness_foundry_runtime/control_kernel.py",
        ],
        "CORR-29-003": [
            "V2_9_CONTROL_KERNEL_MANIFEST.json",
            "tools/harness_foundry_runtime/store.py",
            "tools/harness_foundry_runtime/control_kernel.py",
        ],
        "CORR-29-004": [
            "AUTHORIZATION_POLICY.json",
            "TRANSITION_CONTRACTS.json",
            "contracts/v2_9/PARENT_AUTHORIZATION.schema.json",
            "contracts/v2_9/DERIVED_GRANT.schema.json",
            "tools/harness_foundry_runtime/control_kernel.py",
        ],
        "CORR-29-005": [
            "ASSURANCE_PROFILE.json",
            "tools/harness_foundry_runtime/requirement_completion.py",
        ],
        "CORR-29-006": [
            "contracts/v2_9/MINIMUM_REQUIREMENT_COMPLETION.schema.json",
            "tools/harness_foundry_runtime/requirement_completion.py",
        ],
        "CORR-29-007": [
            "ASSURANCE_PROFILE.json",
            "tools/harness_foundry_runtime/requirement_completion.py",
        ],
        "CORR-29-008": [
            "FACTORY_PROVENANCE.json",
            "canonical_sources/SOURCE_MANIFEST.json",
            "validation/PORTABILITY_MANIFEST.json",
            "tools/setup_runtime.py",
        ],
    }
    return list(refs.get(correction_id, []))


def _correction_coverage_matrix(
    staging: Path,
    requirement_ir: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Compile frozen CORR requirements into an explicit, reviewable closure."""

    target = requirement_ir.get("target")
    correction = (
        target.get("control_plane_architecture_correction")
        if isinstance(target, Mapping)
        else None
    )
    traceability = (
        correction.get("correction_traceability")
        if isinstance(correction, Mapping)
        else None
    )
    if not isinstance(traceability, Mapping) or traceability.get("required") is not True:
        return None
    expected_ids = [str(value) for value in traceability.get("expected_correction_ids", [])]
    raw_requirements = correction.get("correction_requirements")
    if not isinstance(raw_requirements, list):
        raise ValueError("correction traceability requires correction_requirements")
    correction_by_id = {
        str(item.get("correction_id")): item
        for item in raw_requirements
        if isinstance(item, Mapping) and item.get("correction_id")
    }
    if (
        len(correction_by_id) != len(raw_requirements)
        or list(correction_by_id) != expected_ids
        or traceability.get("candidate_artifact_ref") != CORRECTION_COVERAGE_REF
        or traceability.get("mapping_source")
        != "target.control_plane_architecture_correction.correction_requirements"
        or traceability.get("validator_mode")
        != "FAIL_CLOSED_EXACT_MAPPING_AND_HASH_BINDING"
        or traceability.get("standalone_self_check_required") is not True
        or traceability.get("runtime_evidence_must_remain_pending_until_execution")
        is not True
    ):
        raise ValueError("correction traceability declaration is not exact or fail-closed")

    atom_catalog = json.loads(
        (staging / "canonical_sources/NORMATIVE_ATOM_CATALOG.json").read_text(
            encoding="utf-8"
        )
    )
    coverage_matrix = json.loads(
        (staging / "canonical_sources/ATOM_COVERAGE_MATRIX.json").read_text(
            encoding="utf-8"
        )
    )
    atom_ids = {
        str(item.get("atom_id"))
        for item in atom_catalog.get("atoms", [])
        if isinstance(item, Mapping) and item.get("atom_id")
    }
    coverage_by_atom = {
        str(item.get("atom_id")): item
        for item in coverage_matrix.get("coverage", [])
        if isinstance(item, Mapping) and item.get("atom_id")
    }
    rows: list[dict[str, Any]] = []
    for correction_id in expected_ids:
        declaration = correction_by_id[correction_id]
        maps_to = [str(value) for value in declaration.get("maps_to", [])]
        if (
            not maps_to
            or len(set(maps_to)) != len(maps_to)
            or any(atom_id not in atom_ids or atom_id not in coverage_by_atom for atom_id in maps_to)
        ):
            raise ValueError(f"invalid Atom mapping for {correction_id}")
        mapped_coverage = []
        for atom_id in maps_to:
            edge = coverage_by_atom[atom_id]
            mapped_coverage.append(
                {
                    "atom_id": atom_id,
                    "workpack_ids": list(edge.get("workpack_ids") or []),
                    "stage_ids": list(edge.get("stage_ids") or []),
                    "release_step_ids": list(edge.get("release_step_ids") or []),
                    "owner_project_ids": list(edge.get("owner_project_ids") or []),
                    "coverage_status": edge.get("status"),
                }
            )
        row = {
            "correction_id": correction_id,
            "requirement": declaration.get("requirement"),
            "maps_to": maps_to,
            "mapped_atom_coverage": mapped_coverage,
            "implementation_artifact_refs": _correction_implementation_refs(
                correction_id
            ),
            "validation_refs": list(CORRECTION_VALIDATION_REFS),
            "candidate_static_lifecycle": "MATERIALIZED_AND_HASH_BOUND",
            "runtime_lifecycle": "PENDING_UNTIL_AUTHORIZED_EXECUTION",
            "runtime_evidence_refs": [],
            "runtime_claims_verified": False,
        }
        row["row_sha256"] = _hash_without_field(row, "row_sha256")
        rows.append(row)
    matrix = {
        "schema_version": "2.9",
        "matrix_id": "V29-CORRECTION-COVERAGE-EPOCH1",
        "mapping_source": traceability["mapping_source"],
        "expected_correction_ids": expected_ids,
        "correction_count": len(rows),
        "rows": rows,
        "candidate_static_status": "PASS",
        "runtime_evidence_status": "PENDING_UNTIL_AUTHORIZED_EXECUTION",
        "execution_started": False,
    }
    matrix["matrix_sha256"] = _hash_without_field(matrix, "matrix_sha256")
    return matrix


def _release_closure_schemas(
    *,
    require_validation_report_binding: bool = False,
) -> dict[str, dict[str, Any]]:
    object_schema = "https://json-schema.org/draft/2020-12/schema"
    hash_field = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    non_empty_string = {"type": "string", "minLength": 1}
    binding_properties = {
        "authority_scope": non_empty_string,
        "instance_id": non_empty_string,
        "requirement_epoch": {"type": "integer", "minimum": 0},
        "semantic_contract_identity_sha256": hash_field,
        "authorization_risk_identity_sha256": hash_field,
    }
    binding_required = list(binding_properties)
    current_state_properties = {
        "state_revision": {"type": "integer", "minimum": 0},
        "current_state_sha256": hash_field,
        "event_store_tip_sha256": hash_field,
    }
    release_artifact_hash_properties = {
        "candidate_content_sha256": hash_field,
        "requirement_ir_sha256": hash_field,
        "executor_release_sha256": hash_field,
        "human_gate_receipt_sha256": hash_field,
    }
    issuer_anchor_properties = {
        "issuer_control_domain_id": non_empty_string,
        "issuance_event_id": non_empty_string,
        "issuance_event_revision": {"type": "integer", "minimum": 0},
        "issuance_event_sha256": hash_field,
    }
    issuer_anchor_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": list(issuer_anchor_properties),
        "properties": issuer_anchor_properties,
    }
    authority_proof_properties = {
        "receipt_id": non_empty_string,
        **issuer_anchor_properties,
        "release_context_sha256": hash_field,
        "anti_replay_token": hash_field,
    }
    authority_proof_required = list(authority_proof_properties)
    schemas = {
        "IDENTITY_DERIVATION_INPUT.schema.json": {
            "$schema": object_schema,
            "$id": (
                "harness-resource://candidate/contracts/v2_9_release_closure/"
                "IDENTITY_DERIVATION_INPUT.schema.json"
            ),
            "type": "object",
            "additionalProperties": False,
            "required": [
                "semantic_contract",
                "implementation_release",
                "authorization_risk",
                "authority_adapter_binding_sha256",
            ],
            "properties": {
                "semantic_contract": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "contract_id",
                        "contract_version",
                        "normative_behavior_sha256",
                        "input_schema_sha256",
                        "output_schema_sha256",
                        "invariants_sha256",
                    ],
                    "properties": {
                        "contract_id": non_empty_string,
                        "contract_version": non_empty_string,
                        "normative_behavior_sha256": hash_field,
                        "input_schema_sha256": hash_field,
                        "output_schema_sha256": hash_field,
                        "invariants_sha256": hash_field,
                    },
                },
                "implementation_release": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "release_id",
                        "exact_executor_bytes_sha256",
                        "artifact_bytes_sha256",
                        "sbom_sha256",
                        "provenance_sha256",
                        "toolchain_sha256",
                    ],
                    "properties": {
                        "release_id": non_empty_string,
                        "exact_executor_bytes_sha256": hash_field,
                        "artifact_bytes_sha256": hash_field,
                        "sbom_sha256": hash_field,
                        "provenance_sha256": hash_field,
                        "toolchain_sha256": hash_field,
                    },
                },
                "authorization_risk": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "risk_profile_id",
                        "scope_sha256",
                        "permissions_sha256",
                        "write_roots_sha256",
                        "network_policy_sha256",
                        "secret_access_policy_sha256",
                        "external_effect_class",
                        "budget_sha256",
                        "stop_gates_sha256",
                    ],
                    "properties": {
                        "risk_profile_id": non_empty_string,
                        "scope_sha256": hash_field,
                        "permissions_sha256": hash_field,
                        "write_roots_sha256": hash_field,
                        "network_policy_sha256": hash_field,
                        "secret_access_policy_sha256": hash_field,
                        "external_effect_class": non_empty_string,
                        "budget_sha256": hash_field,
                        "stop_gates_sha256": hash_field,
                    },
                },
                "authority_adapter_binding_sha256": hash_field,
            },
        },
        "IDENTITY_BUNDLE.schema.json": {
            "$schema": object_schema,
            "$id": (
                "harness-resource://candidate/contracts/v2_9_release_closure/"
                "IDENTITY_BUNDLE.schema.json"
            ),
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema_version",
                "identity_derivation_id",
                "input_sha256",
                "semantic_contract_identity_sha256",
                "implementation_release_identity_sha256",
                "authorization_risk_identity_sha256",
                "authority_scope",
                "instance_id",
                "state_revision",
                "current_state_sha256",
                "event_store_tip_sha256",
                "creates_authority",
                "identity_bundle_sha256",
            ],
            "properties": {
                "schema_version": {"const": "2.9"},
                "identity_derivation_id": {
                    "const": "V29_THREE_LAYER_IDENTITY_DERIVATION_V2"
                },
                "input_sha256": hash_field,
                "semantic_contract_identity_sha256": hash_field,
                "implementation_release_identity_sha256": hash_field,
                "authorization_risk_identity_sha256": hash_field,
                "authority_scope": non_empty_string,
                "instance_id": non_empty_string,
                **current_state_properties,
                "creates_authority": {"const": False},
                "identity_bundle_sha256": hash_field,
            },
        },
        "MACHINE_GRANT_BINDING.schema.json": {
            "$schema": object_schema,
            "$id": (
                "harness-resource://candidate/contracts/v2_9_release_closure/"
                "MACHINE_GRANT_BINDING.schema.json"
            ),
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema_version",
                "binding_id",
                "binding_status",
                "authorization_risk_identity_sha256",
                "semantic_contract_identity_sha256",
                "implementation_release_identity_sha256",
                "exact_executor_release_sha256",
                "exact_artifact_release_sha256",
                "authority_scope",
                "instance_id",
                "state_revision",
                "current_state_sha256",
                "event_store_tip_sha256",
                "authoritative_adapter_checked",
                "authority_adapter_binding_sha256",
                "human_authorization_granted",
                "machine_grant_issued",
                "creates_authority",
                "binding_sha256",
            ],
            "properties": {
                "schema_version": {"const": "2.9"},
                "binding_id": {"const": "V29_MACHINE_GRANT_BINDING_V2"},
                "binding_status": {"const": "PLANNED_NOT_GRANTED"},
                "authorization_risk_identity_sha256": hash_field,
                "semantic_contract_identity_sha256": hash_field,
                "implementation_release_identity_sha256": hash_field,
                "exact_executor_release_sha256": hash_field,
                "exact_artifact_release_sha256": hash_field,
                "authority_scope": non_empty_string,
                "instance_id": non_empty_string,
                **current_state_properties,
                "authoritative_adapter_checked": {"const": True},
                "authority_adapter_binding_sha256": hash_field,
                "human_authorization_granted": {"const": False},
                "machine_grant_issued": {"const": False},
                "creates_authority": {"const": False},
                "binding_sha256": hash_field,
            },
        },
        "EVENT_STORE_AUTHORITY_ADAPTER_BINDING.schema.json": {
            "$schema": object_schema,
            "$id": (
                "harness-resource://candidate/contracts/v2_9_release_closure/"
                "EVENT_STORE_AUTHORITY_ADAPTER_BINDING.schema.json"
            ),
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema_version",
                "adapter_id",
                "program_id",
                "authority_scope",
                "instance_id",
                "requirement_epoch",
                "database_identity_sha256",
                "logical_database_ref",
                "adapter_implementation_sha256",
                "adapter_entrypoint_sha256",
                "adapter_contract_sha256",
                "authority_binding_receipt",
                "binding_sha256",
            ],
            "properties": {
                "schema_version": {"const": "2.9"},
                "adapter_id": {
                    "const": "V29_SQLITE_EVENT_STORE_AUTHORITY_ADAPTER_V1"
                },
                "program_id": non_empty_string,
                "authority_scope": non_empty_string,
                "instance_id": non_empty_string,
                "requirement_epoch": {"type": "integer", "minimum": 0},
                "database_identity_sha256": hash_field,
                "logical_database_ref": {
                    "const": (
                        "harness-resource://execution/control/"
                        "control-events.sqlite3"
                    )
                },
                "adapter_implementation_sha256": hash_field,
                "adapter_entrypoint_sha256": hash_field,
                "adapter_contract_sha256": hash_field,
                "authority_binding_receipt": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "schema_version", "receipt_kind", "receipt_id",
                        "issuer_role", "trust_root_id", "issued_at",
                        "not_before", "expires_at", "revoked", "one_shot",
                        "authorization_purpose", "program_id", "authority_scope",
                        "instance_id", "requirement_epoch",
                        "database_identity_sha256", "logical_database_ref",
                        "adapter_implementation_sha256",
                        "adapter_entrypoint_sha256", "adapter_contract_sha256",
                        "signature_base64",
                    ],
                    "properties": {
                        "schema_version": {"const": "2.9"},
                        "receipt_kind": {"const": "AUTHORITY_BINDING_RECEIPT"},
                        "receipt_id": non_empty_string,
                        "issuer_role": {"const": "CONTROL_PLANE_AUTHORITY"},
                        "trust_root_id": non_empty_string,
                        "issued_at": non_empty_string,
                        "not_before": non_empty_string,
                        "expires_at": non_empty_string,
                        "revoked": {"const": False},
                        "one_shot": {"const": False},
                        "authorization_purpose": {
                            "const": "EVENT_STORE_ADAPTER_BINDING"
                        },
                        "program_id": non_empty_string,
                        "authority_scope": non_empty_string,
                        "instance_id": non_empty_string,
                        "requirement_epoch": {"type": "integer", "minimum": 0},
                        "database_identity_sha256": hash_field,
                        "logical_database_ref": {
                            "const": (
                                "harness-resource://execution/control/"
                                "control-events.sqlite3"
                            )
                        },
                        "adapter_implementation_sha256": hash_field,
                        "adapter_entrypoint_sha256": hash_field,
                        "adapter_contract_sha256": hash_field,
                        "signature_base64": non_empty_string,
                    },
                },
                "binding_sha256": hash_field,
            },
        },
        "RECOVERY_DECISION.schema.json": {
            "$schema": object_schema,
            "$id": (
                "harness-resource://candidate/contracts/v2_9_release_closure/"
                "RECOVERY_DECISION.schema.json"
            ),
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema_version",
                "protocol_id",
                "input_sha256",
                "decision",
                "reason_code",
                "creates_authority",
                "executor_invoked",
                "allowed_decision_modes",
                "decision_sha256",
            ],
            "properties": {
                "schema_version": {"const": "2.9"},
                "protocol_id": {"type": "string"},
                "input_sha256": hash_field,
                "decision": {
                    "enum": [
                        "RESULT_VALIDATION_ONLY",
                        "FINALIZATION_ONLY",
                        "RETRY_EXECUTOR",
                        "HUMAN_RISK_REVIEW",
                    ]
                },
                "reason_code": {"type": "string"},
                "creates_authority": {"const": False},
                "executor_invoked": {"const": False},
                "allowed_decision_modes": {"type": "array", "minItems": 4},
                "decision_sha256": hash_field,
            },
        },
        "COMPLEXITY_DECISION.schema.json": {
            "$schema": object_schema,
            "$id": (
                "harness-resource://candidate/contracts/v2_9_release_closure/"
                "COMPLEXITY_DECISION.schema.json"
            ),
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema_version",
                "governor_id",
                "input_sha256",
                "decision",
                "reason_code",
                "violations",
                "outputs",
                "creates_authority",
                "assessment_sha256",
            ],
            "properties": {
                "schema_version": {"const": "2.9"},
                "governor_id": {
                    "const": "V29_EXECUTABLE_COMPLEXITY_GOVERNOR_V2"
                },
                "input_sha256": hash_field,
                "decision": {
                    "enum": ["PASS", "FAIL", "ARCHITECTURE_REVIEW_REQUIRED"]
                },
                "reason_code": {"type": "string"},
                "violations": {"type": "array", "items": {"type": "string"}},
                "outputs": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "complexity_baseline",
                        "complexity_delta",
                        "retirement_manifest",
                        "human_cost_result",
                        "circuit_breaker_decision_receipt",
                    ],
                    "properties": {
                        "complexity_baseline": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "active_bespoke_paths_before",
                                "new_node_specific_authorized_paths",
                                "new_fixed_attempt_or_receipt_ids_in_core",
                            ],
                            "properties": {
                                "active_bespoke_paths_before": {"type": "integer", "minimum": 0},
                                "new_node_specific_authorized_paths": {"type": "integer", "minimum": 0},
                                "new_fixed_attempt_or_receipt_ids_in_core": {"type": "integer", "minimum": 0},
                            },
                        },
                        "complexity_delta": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "active_bespoke_paths_after",
                                "active_bespoke_path_delta",
                                "delta_is_negative",
                            ],
                            "properties": {
                                "active_bespoke_paths_after": {"type": "integer", "minimum": 0},
                                "active_bespoke_path_delta": {"type": "integer"},
                                "delta_is_negative": {"type": "boolean"},
                            },
                        },
                        "retirement_manifest": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "generic_path_added",
                                "retired_authoritative_paths",
                                "retirement_required",
                                "retirement_satisfied",
                            ],
                            "properties": {
                                "generic_path_added": {"type": "boolean"},
                                "retired_authoritative_paths": {"type": "integer", "minimum": 0},
                                "retirement_required": {"type": "boolean"},
                                "retirement_satisfied": {"type": "boolean"},
                            },
                        },
                        "human_cost_result": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "human_gate_added",
                                "risk_delta_or_external_boundary",
                                "human_gate_justified",
                            ],
                            "properties": {
                                "human_gate_added": {"type": "boolean"},
                                "risk_delta_or_external_boundary": {"type": "boolean"},
                                "human_gate_justified": {"type": "boolean"},
                            },
                        },
                        "circuit_breaker_decision_receipt": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "control_fault_fingerprint_occurrences",
                                "threshold",
                                "circuit_breaker_open",
                                "decision",
                                "reason_code",
                            ],
                            "properties": {
                                "control_fault_fingerprint_occurrences": {"type": "integer", "minimum": 0},
                                "threshold": {"const": 2},
                                "circuit_breaker_open": {"type": "boolean"},
                                "decision": {"enum": ["CONTINUE", "ARCHITECTURE_REVIEW_REQUIRED"]},
                                "reason_code": {"type": "string"},
                            },
                        },
                    },
                },
                "creates_authority": {"const": False},
                "assessment_sha256": hash_field,
            },
        },
        "CLOSURE_RECEIPT.schema.json": {
            "$schema": object_schema,
            "$id": (
                "harness-resource://candidate/contracts/v2_9_release_closure/"
                "CLOSURE_RECEIPT.schema.json"
            ),
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema_version",
                "lane_id",
                "status",
                "authority_scope",
                "instance_id",
                "requirement_epoch",
                "semantic_contract_identity_sha256",
                "authorization_risk_identity_sha256",
                *authority_proof_required,
                "creates_authority",
                "receipt_sha256",
            ],
            "properties": {
                "schema_version": {"const": "2.9"},
                "lane_id": {"enum": ["PRODUCT", "SAFETY", "RELEASE"]},
                "status": {"const": "CLOSED"},
                **binding_properties,
                **authority_proof_properties,
                "creates_authority": {"const": False},
                "receipt_sha256": hash_field,
            },
        },
        "COMPATIBILITY_LINKAGE_RECEIPT.schema.json": {
            "$schema": object_schema,
            "$id": (
                "harness-resource://candidate/contracts/v2_9_release_closure/"
                "COMPATIBILITY_LINKAGE_RECEIPT.schema.json"
            ),
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema_version",
                "status",
                *binding_required,
                *authority_proof_required,
                "creates_authority",
                "receipt_sha256",
            ],
            "properties": {
                "schema_version": {"const": "2.9"},
                "status": {"const": "PASS"},
                **binding_properties,
                **authority_proof_properties,
                "creates_authority": {"const": False},
                "receipt_sha256": hash_field,
            },
        },
        "TRUSTED_RELEASE_CONTEXT.schema.json": {
            "$schema": object_schema,
            "$id": (
                "harness-resource://candidate/contracts/v2_9_release_closure/"
                "TRUSTED_RELEASE_CONTEXT.schema.json"
            ),
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema_version",
                *binding_required,
                *current_state_properties,
                *release_artifact_hash_properties,
                "authorized_issuers",
                "consumed_receipt_ids",
                "release_context_sha256",
            ],
            "properties": {
                "schema_version": {"const": "2.9"},
                **binding_properties,
                **current_state_properties,
                **release_artifact_hash_properties,
                "authorized_issuers": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "PRODUCT",
                        "SAFETY",
                        "RELEASE",
                        "COMPATIBILITY_LINKAGE",
                    ],
                    "properties": {
                        "PRODUCT": issuer_anchor_schema,
                        "SAFETY": issuer_anchor_schema,
                        "RELEASE": issuer_anchor_schema,
                        "COMPATIBILITY_LINKAGE": issuer_anchor_schema,
                    },
                },
                "consumed_receipt_ids": {
                    "type": "array",
                    "uniqueItems": True,
                    "items": non_empty_string,
                },
                "release_context_sha256": hash_field,
            },
        },
        "FINAL_RELEASE_DECISION.schema.json": {
            "$schema": object_schema,
            "$id": (
                "harness-resource://candidate/contracts/v2_9_release_closure/"
                "FINAL_RELEASE_DECISION.schema.json"
            ),
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema_version",
                "decision_id",
                "decision",
                "release_context_sha256",
                "expected_event_store_tip_sha256",
                "lane_receipt_ids",
                "lane_receipt_sha256",
                "compatibility_linkage_receipt_id",
                "compatibility_linkage_receipt_sha256",
                "atomic_event_store_commit_required",
                "receipt_set_consumed",
                "release_ready_committed",
                "creates_authority",
                "decision_sha256",
            ],
            "properties": {
                "schema_version": {"const": "2.9"},
                "decision_id": {"const": "V29_FINAL_RELEASE_DECISION_V3"},
                "decision": {
                    "const": "RELEASE_ELIGIBILITY_PROPOSAL_NOT_AUTHORITY"
                },
                "release_context_sha256": hash_field,
                "expected_event_store_tip_sha256": hash_field,
                "lane_receipt_ids": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["PRODUCT", "SAFETY", "RELEASE"],
                    "properties": {
                        "PRODUCT": non_empty_string,
                        "SAFETY": non_empty_string,
                        "RELEASE": non_empty_string,
                    },
                },
                "lane_receipt_sha256": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["PRODUCT", "SAFETY", "RELEASE"],
                    "properties": {
                        "PRODUCT": hash_field,
                        "SAFETY": hash_field,
                        "RELEASE": hash_field,
                    },
                },
                "compatibility_linkage_receipt_id": non_empty_string,
                "compatibility_linkage_receipt_sha256": hash_field,
                "atomic_event_store_commit_required": {"const": True},
                "receipt_set_consumed": {"const": False},
                "release_ready_committed": {"const": False},
                "creates_authority": {"const": False},
                "decision_sha256": hash_field,
            },
        },
        "EVIDENCE_INDEX_ENTRY.schema.json": {
            "$schema": object_schema,
            "$id": (
                "harness-resource://candidate/contracts/v2_9_release_closure/"
                "EVIDENCE_INDEX_ENTRY.schema.json"
            ),
            "type": "object",
            "additionalProperties": False,
            "required": [
                "authority_scope",
                "instance_id",
                "fact_key",
                "event_sha256",
                "retention_class",
                "creates_authority",
            ],
            "properties": {
                "authority_scope": {"type": "string"},
                "instance_id": {"type": "string"},
                "fact_key": {"type": "string"},
                "event_sha256": hash_field,
                "retention_class": {
                    "enum": [
                        "ACTIVE_BASELINE",
                        "HISTORICAL_REGRESSION",
                        "SUPERSEDED",
                        "ARCHIVED",
                    ]
                },
                "creates_authority": {"const": False},
            },
        },
        "SOURCE_AUTHORITY_POLICY_LOCK.schema.json": {
            "$schema": object_schema,
            "$id": (
                "harness-resource://candidate/contracts/v2_9_release_closure/"
                "SOURCE_AUTHORITY_POLICY_LOCK.schema.json"
            ),
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema_version",
                "lock_id",
                "authority_source",
                "trust_anchor_id",
                "issuer_binding",
                "authority_normalization",
                "canonical_authority_levels",
                "semantic_projection_fields",
                "sources",
                "release_history_tip_sha256",
                "release_history",
                "validation_report_binding",
                "policy_payload_sha256",
                "signature_algorithm",
                "signature_base64",
                "lock_sha256",
            ],
            "properties": {
                "schema_version": {"const": "2.9"},
                "lock_id": {"const": "V29_SOURCE_AUTHORITY_POLICY_LOCK_V4"},
                "authority_source": {
                    "const": "RECEIVER_CONTROL_PLANE_EXTERNAL_TO_CANDIDATE"
                },
                "trust_anchor_id": {
                    "const": "V29_SOURCE_AUTHORITY_TRUST_ANCHOR_V1"
                },
                "issuer_binding": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "issuer_id",
                        "key_id",
                        "program_id",
                        "requirement_epoch",
                        "issuance_event_id",
                        "issuance_event_revision",
                        "issuance_event_sha256",
                        "source_registry_revision",
                        "source_registry_tip_sha256",
                        "release_history_tip_sha256",
                    ],
                    "properties": {
                        "issuer_id": non_empty_string,
                        "key_id": non_empty_string,
                        "program_id": non_empty_string,
                        "requirement_epoch": {"type": "integer", "minimum": 0},
                        "issuance_event_id": non_empty_string,
                        "issuance_event_revision": {"type": "integer", "minimum": 0},
                        "issuance_event_sha256": hash_field,
                        "source_registry_revision": {"type": "integer", "minimum": 0},
                        "source_registry_tip_sha256": hash_field,
                        "release_history_tip_sha256": hash_field,
                    },
                },
                "authority_normalization": {"type": "object"},
                "canonical_authority_levels": {
                    "type": "array",
                    "minItems": 4,
                    "uniqueItems": True,
                },
                "semantic_projection_fields": {
                    "const": [
                        "source_id",
                        "content_sha256",
                        "copy_policy",
                        "loaded_completely",
                        "declared_authority_level",
                        "canonical_authority_level",
                    ]
                },
                "sources": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "source_id",
                            "content_sha256",
                            "copy_policy",
                            "loaded_completely",
                            "declared_authority_level",
                            "canonical_authority_level",
                        ],
                        "properties": {
                            "source_id": non_empty_string,
                            "content_sha256": hash_field,
                            "copy_policy": non_empty_string,
                            "loaded_completely": {"type": "boolean"},
                            "declared_authority_level": non_empty_string,
                            "canonical_authority_level": non_empty_string,
                        },
                    },
                },
                "release_history_tip_sha256": hash_field,
                "release_history": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "requirement_key",
                            "closure_requirement_epoch",
                            "superseded_candidate",
                            "replacement_candidate",
                            "successor_candidate_version",
                        ],
                        "properties": {
                            "requirement_key": non_empty_string,
                            "closure_requirement_epoch": {
                                "type": "integer", "minimum": 0
                            },
                            "superseded_candidate": non_empty_string,
                            "replacement_candidate": non_empty_string,
                            "successor_candidate_version": non_empty_string,
                        },
                    },
                },
                "validation_report_binding": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "report_ref", "report_sha256",
                        "receipt_ref", "receipt_sha256",
                    ],
                    "properties": {
                        "report_ref": {
                            "const": "validation/START_PACKAGE_VALIDATION_REPORT.json"
                        },
                        "report_sha256": hash_field,
                        "receipt_ref": {
                            "const": "validation/START_PACKAGE_VALIDATION_REPORT_RECEIPT.json"
                        },
                        "receipt_sha256": hash_field,
                    },
                },
                "policy_payload_sha256": hash_field,
                "signature_algorithm": {"const": "ED25519"},
                "signature_base64": {"type": "string", "minLength": 1},
                "lock_sha256": hash_field,
            },
        },
        "VALIDATION_REPORT_RECEIPT.schema.json": {
            "$schema": object_schema,
            "$id": (
                "harness-resource://candidate/contracts/v2_9_release_closure/"
                "VALIDATION_REPORT_RECEIPT.schema.json"
            ),
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema_version", "receipt_id", "report_ref", "report_sha256",
                "report_id", "program_id", "package_id", "candidate_version",
                "requirement_epoch", "requirement_ir_sha256",
                "authority_provenance", "external_authority_checks_sha256",
                "binding_authority", "receipt_sha256",
            ],
            "properties": {
                "schema_version": {"const": "1.0"},
                "receipt_id": {
                    "const": "START_PACKAGE_VALIDATION_REPORT_RECEIPT"
                },
                "report_ref": {
                    "const": "validation/START_PACKAGE_VALIDATION_REPORT.json"
                },
                "report_sha256": hash_field,
                "report_id": non_empty_string,
                "program_id": non_empty_string,
                "package_id": non_empty_string,
                "candidate_version": non_empty_string,
                "requirement_epoch": {"type": "integer", "minimum": 0},
                "requirement_ir_sha256": hash_field,
                "authority_provenance": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "event_store_revision", "event_store_tip_sha256",
                        "requirement_epoch", "source_registry_sha256",
                        "requirement_ir_sha256",
                    ],
                    "properties": {
                        "event_store_revision": {"type": "integer", "minimum": 0},
                        "event_store_tip_sha256": hash_field,
                        "requirement_epoch": {"type": "integer", "minimum": 0},
                        "source_registry_sha256": hash_field,
                        "requirement_ir_sha256": hash_field,
                    },
                },
                "external_authority_checks_sha256": hash_field,
                "binding_authority": {
                    "const": "FACTORY_EVENT_STORE_AND_RECEIVER_SIGNED_SOURCE_AUTHORITY_POLICY"
                },
                "receipt_sha256": hash_field,
            },
        },
    }
    if not require_validation_report_binding:
        policy = schemas["SOURCE_AUTHORITY_POLICY_LOCK.schema.json"]
        policy["required"].remove("validation_report_binding")
        policy["properties"].pop("validation_report_binding")
        schemas.pop("VALIDATION_REPORT_RECEIPT.schema.json")
    return schemas


def _epoch2_implementation_refs(correction_id: str) -> list[str]:
    refs = {
        "CORR-29-009": [
            EPOCH2_MANIFEST_REF,
            "SEMANTIC_IMPLEMENTATION_AUTHORIZATION_IDENTITY_CONTRACT.json",
            "contracts/v2_9_release_closure/IDENTITY_DERIVATION_INPUT.schema.json",
            "contracts/v2_9_release_closure/IDENTITY_BUNDLE.schema.json",
            "contracts/v2_9_release_closure/MACHINE_GRANT_BINDING.schema.json",
            "tools/harness_foundry_runtime/identity_derivation.py",
            "EVENT_STORE_AUTHORITY_ADAPTER_CONTRACT.json",
            "AUTHORITY_TRUST_ROOT.json",
            "contracts/v2_9_release_closure/EVENT_STORE_AUTHORITY_ADAPTER_BINDING.schema.json",
            "contracts/v2_9_release_closure/SOURCE_AUTHORITY_POLICY_LOCK.schema.json",
            "tools/harness_foundry_runtime/authority_adapter.py",
        ],
        "CORR-29-010": [
            "GENERIC_RECOVERY_DECISION_PROTOCOL.json",
            "contracts/v2_9_release_closure/RECOVERY_DECISION.schema.json",
            "tools/harness_foundry_runtime/recovery_decision.py",
        ],
        "CORR-29-011": [
            "COMPLEXITY_GOVERNOR.json",
            "contracts/v2_9_release_closure/COMPLEXITY_DECISION.schema.json",
            "tools/harness_foundry_runtime/complexity_governor.py",
        ],
        "CORR-29-012": [
            "PRODUCT_SAFETY_RELEASE_CLOSURE_GRAPH.json",
            "contracts/v2_9_release_closure/CLOSURE_RECEIPT.schema.json",
            "contracts/v2_9_release_closure/COMPATIBILITY_LINKAGE_RECEIPT.schema.json",
            "contracts/v2_9_release_closure/TRUSTED_RELEASE_CONTEXT.schema.json",
            "contracts/v2_9_release_closure/FINAL_RELEASE_DECISION.schema.json",
            "tools/harness_foundry_runtime/closure_lanes.py",
            "EVENT_STORE_AUTHORITY_ADAPTER_CONTRACT.json",
            "AUTHORITY_TRUST_ROOT.json",
            "contracts/v2_9_release_closure/EVENT_STORE_AUTHORITY_ADAPTER_BINDING.schema.json",
            "tools/harness_foundry_runtime/authority_adapter.py",
        ],
        "CORR-29-013": [
            "EVIDENCE_LIFECYCLE_AND_PROJECTION_CONTRACT.json",
            "contracts/v2_9_release_closure/EVIDENCE_INDEX_ENTRY.schema.json",
            "tools/harness_foundry_runtime/evidence_projection.py",
            EPOCH2_COVERAGE_REF,
        ],
    }
    return list(refs.get(correction_id, []))


def _release_closure_coverage_matrix(
    staging: Path,
    remediation: Mapping[str, Any],
) -> dict[str, Any]:
    declarations = remediation.get("correction_requirements")
    if not isinstance(declarations, list):
        raise ValueError("Epoch 2 correction requirements are missing")
    by_id = {
        str(item.get("correction_id")): item
        for item in declarations
        if isinstance(item, Mapping) and item.get("correction_id")
    }
    if tuple(by_id) != EPOCH2_CORRECTION_IDS:
        raise ValueError("Epoch 2 correction ID set or order drifted")
    atom_catalog = json.loads(
        (staging / "canonical_sources/NORMATIVE_ATOM_CATALOG.json").read_text(
            encoding="utf-8"
        )
    )
    coverage_matrix = json.loads(
        (staging / "canonical_sources/ATOM_COVERAGE_MATRIX.json").read_text(
            encoding="utf-8"
        )
    )
    atom_ids = {
        str(item.get("atom_id"))
        for item in atom_catalog.get("atoms", [])
        if isinstance(item, Mapping) and item.get("atom_id")
    }
    coverage_by_atom = {
        str(item.get("atom_id")): item
        for item in coverage_matrix.get("coverage", [])
        if isinstance(item, Mapping) and item.get("atom_id")
    }
    rows: list[dict[str, Any]] = []
    for correction_id in EPOCH2_CORRECTION_IDS:
        declaration = by_id[correction_id]
        maps_to = [str(value) for value in declaration.get("maps_to", [])]
        if (
            not maps_to
            or len(set(maps_to)) != len(maps_to)
            or any(atom not in atom_ids or atom not in coverage_by_atom for atom in maps_to)
        ):
            raise ValueError(f"invalid Epoch 2 Atom mapping for {correction_id}")
        mapped_coverage = []
        for atom_id in maps_to:
            edge = coverage_by_atom[atom_id]
            mapped_coverage.append(
                {
                    "atom_id": atom_id,
                    "workpack_ids": list(edge.get("workpack_ids") or []),
                    "stage_ids": list(edge.get("stage_ids") or []),
                    "release_step_ids": list(edge.get("release_step_ids") or []),
                    "owner_project_ids": list(edge.get("owner_project_ids") or []),
                    "coverage_status": edge.get("status"),
                }
            )
        row = {
            "correction_id": correction_id,
            "requirement": declaration.get("requirement"),
            "maps_to": maps_to,
            "mapped_atom_coverage": mapped_coverage,
            "implementation_artifact_refs": _epoch2_implementation_refs(
                correction_id
            ),
            "validation_refs": [
                "tools/self_check.py",
                "validation/HUMAN_REVIEW_CLOSURE_RECEIPT.json",
                "validation/START_PACKAGE_VALIDATION_REPORT.json",
            ],
            "candidate_static_lifecycle": "MATERIALIZED_AND_HASH_BOUND",
            "runtime_lifecycle": "PENDING_UNTIL_AUTHORIZED_EXECUTION",
            "runtime_evidence_refs": [],
            "runtime_claims_verified": False,
        }
        row["row_sha256"] = _hash_without_field(row, "row_sha256")
        rows.append(row)
    matrix = {
        "schema_version": "2.9",
        "matrix_id": "V29-RELEASE-CLOSURE-CORRECTION-COVERAGE-EPOCH2",
        "expected_correction_ids": list(EPOCH2_CORRECTION_IDS),
        "correction_count": len(rows),
        "rows": rows,
        "candidate_static_status": "PASS",
        "runtime_evidence_status": "PENDING_UNTIL_AUTHORIZED_EXECUTION",
        "execution_started": False,
    }
    matrix["matrix_sha256"] = _hash_without_field(matrix, "matrix_sha256")
    return matrix


def _write_release_closure_control_plane_bundle(
    staging: Path,
    requirement_ir: Mapping[str, Any],
    context: Mapping[str, str],
) -> None:
    """Materialize the active Epoch 2 contracts before either validator runs."""

    target = requirement_ir["target"]
    remediation = target["release_closure_control_plane_remediation"]
    alignment = target["v0_15_epoch2_producer_validator_alignment_correction"]
    human_review_remediation = target.get("v0_16_human_review_remediation")
    epoch17_remediation = target.get("v0_17_human_review_remediation")
    epoch18_remediation = target.get("v0_18_human_review_remediation")
    epoch20_remediation = target.get("v0_20_human_review_remediation")
    epoch22_remediation = target.get("v0_22_human_review_remediation")
    epoch24_remediation = target.get("v0_24_human_review_remediation")
    epoch25_remediation = target.get("v0_25_generation_failure_remediation")
    epoch26_remediation = target.get("v0_26_human_review_remediation")
    epoch28_remediation = target.get("v0_27_human_review_remediation")
    epoch29_remediation = target.get("v0_28_human_review_remediation")
    epoch30_remediation = target.get("v0_29_human_review_remediation")
    epoch31_remediation = target.get("v0_30_human_review_remediation")
    epoch32_remediation = target.get("v0_31_runtime_binding_failure_remediation")
    epoch33_remediation = target.get("v0_32_human_review_remediation")
    epoch34_remediation = target.get("v0_33_human_review_remediation")
    epoch35_remediation = target.get("v0_34_human_review_remediation")
    if (
        remediation.get("architecture_epoch") != 2
        or remediation.get("control_plane_epoch") != 2
        or alignment.get("producer_first") is not True
        or alignment.get("status") != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
        or not isinstance(human_review_remediation, Mapping)
        or human_review_remediation.get("status")
        != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
        or human_review_remediation.get("active_epochs")
        != {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 16,
        }
        or not isinstance(epoch17_remediation, Mapping)
        or epoch17_remediation.get("status")
        != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
        or epoch17_remediation.get("active_epochs")
        != {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 17,
        }
        or not isinstance(epoch18_remediation, Mapping)
        or epoch18_remediation.get("status")
        != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
        or epoch18_remediation.get("active_epochs")
        != {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 18,
        }
        or not isinstance(epoch20_remediation, Mapping)
        or epoch20_remediation.get("status")
        != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
        or epoch20_remediation.get("active_epochs")
        != {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 20,
        }
        or not isinstance(epoch22_remediation, Mapping)
        or epoch22_remediation.get("status")
        != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
        or epoch22_remediation.get("active_epochs")
        != {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 22,
        }
        or not isinstance(epoch24_remediation, Mapping)
        or epoch24_remediation.get("status")
        != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
        or epoch24_remediation.get("active_epochs")
        != {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 24,
        }
        or not _producer_epoch24_route_is_complete(epoch24_remediation)
        or epoch24_remediation.get("artifact_bytes_resolver_contract", {}).get(
            "resolve_inside_begin_immediate"
        ) is not True
        or epoch24_remediation.get("receiver_trust_anchor_contract", {}).get(
            "receiver_supplied_external_anchor_required"
        ) is not True
        or (
            epoch25_remediation is not None
            and (
                not isinstance(epoch25_remediation, Mapping)
                or epoch25_remediation.get("status")
                != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
                or epoch25_remediation.get("active_epochs")
                != {
                    "architecture_epoch": 2,
                    "control_plane_epoch": 2,
                    "requirement_epoch": 25,
                }
                or not _producer_epoch25_route_is_complete(epoch25_remediation)
                or epoch25_remediation.get(
                    "source_authority_semantic_projection_contract", {}
                ).get("receiver_local_locator_fields_compared") is not False
                or epoch25_remediation.get(
                    "portable_uri_projection_contract", {}
                ).get("independent_mapping_validation_required") is not True
            )
        )
        or (
            epoch26_remediation is not None
            and (
                not isinstance(epoch26_remediation, Mapping)
                or epoch26_remediation.get("status")
                != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
                or epoch26_remediation.get("active_epochs")
                != {
                    "architecture_epoch": 2,
                    "control_plane_epoch": 2,
                    "requirement_epoch": 26,
                }
                or epoch26_remediation.get(
                    "portable_source_index_contract", {}
                ).get("standalone_independent_semantic_validation_required")
                is not True
                or epoch26_remediation.get(
                    "source_authority_policy_lock_contract", {}
                ).get("receiver_pinned_ed25519_signature_required") is not True
                or epoch26_remediation.get(
                    "closure_identity_contract", {}
                ).get("successor_package_epoch_cross_check_required") is not True
            )
        )
        or (
            epoch28_remediation is not None
            and (
                not isinstance(epoch28_remediation, Mapping)
                or epoch28_remediation.get("status")
                != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
                or epoch28_remediation.get("active_epochs")
                != {
                    "architecture_epoch": 2,
                    "control_plane_epoch": 2,
                    "requirement_epoch": 28,
                }
                or epoch28_remediation.get(
                    "receiver_release_history_authority_contract", {}
                ).get("receiver_pinned_ed25519_signature_required") is not True
                or epoch28_remediation.get(
                    "producer_history_authority_contract", {}
                ).get("source_authority_policy_version")
                != "V29_SOURCE_AUTHORITY_POLICY_LOCK_V4"
                or epoch28_remediation.get(
                    "dual_oracle_history_contract", {}
                ).get("standalone_authority_input")
                != "RECEIVER_PINNED_SIGNED_RELEASE_HISTORY_POLICY"
            )
        )
        or (
            epoch29_remediation is not None
            and (
                not isinstance(epoch29_remediation, Mapping)
                or epoch29_remediation.get("status")
                != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
                or epoch29_remediation.get("active_epochs")
                != {
                    "architecture_epoch": 2,
                    "control_plane_epoch": 2,
                    "requirement_epoch": 29,
                }
                or epoch29_remediation.get(
                    "external_authority_fail_closed_contract", {}
                ).get("missing_authoritative_sources_overall_status")
                != "FAIL"
                or epoch29_remediation.get(
                    "external_authority_fail_closed_contract", {}
                ).get("missing_authoritative_requirement_ir_overall_status")
                != "FAIL"
                or epoch29_remediation.get(
                    "validation_report_authority_provenance_contract", {}
                ).get("authority_input_preserved") is not True
                or epoch29_remediation.get(
                    "validation_report_authority_provenance_contract", {}
                ).get("event_store_revision_tip_and_content_hashes_required")
                is not True
            )
        )
        or (
            epoch30_remediation is not None
            and (
                not isinstance(epoch30_remediation, Mapping)
                or epoch30_remediation.get("status")
                != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
                or epoch30_remediation.get("active_epochs")
                != {
                    "architecture_epoch": 2,
                    "control_plane_epoch": 2,
                    "requirement_epoch": 30,
                }
                or any(
                    epoch30_remediation.get(
                        "validation_report_integrity_contract", {}
                    ).get(field) is not True
                    for field in (
                        "factory_compares_embedded_external_checks_to_recomputed_checks",
                        "detached_report_receipt_required",
                        "receiver_signed_policy_binds_report_and_receipt_hashes",
                        "standalone_verifies_signed_report_binding",
                    )
                )
            )
        )
        or (
            epoch31_remediation is not None
            and (
                not isinstance(epoch31_remediation, Mapping)
                or epoch31_remediation.get("status")
                != "REQUIRED_IN_REPLACEMENT_CANDIDATE"
                or epoch31_remediation.get("active_epochs")
                != {
                    "architecture_epoch": 2,
                    "control_plane_epoch": 2,
                    "requirement_epoch": 31,
                }
                or any(
                    epoch31_remediation.get(
                        "validation_basis_current_head_contract", {}
                    ).get(field) is not True
                    for field in (
                        "immutable_basis_must_be_verified_ancestor",
                        "current_head_may_advance_after_candidate_commit",
                    )
                )
                or epoch31_remediation.get(
                    "validation_basis_current_head_contract", {}
                ).get("basis_equals_mutable_head_required") is not False
                or epoch31_remediation.get(
                    "validation_basis_current_head_contract", {}
                ).get("forked_or_unrelated_basis_behavior") != "FAIL_CLOSED"
                or epoch31_remediation.get(
                    "candidate_generation_commit_contract", {}
                ).get("authority_source") != "FACTORY_APPEND_ONLY_EVENT_STORE"
                or epoch31_remediation.get(
                    "candidate_generation_commit_contract", {}
                ).get("event_type")
                != "START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW"
                or any(
                    epoch31_remediation.get(
                        "candidate_generation_commit_contract", {}
                    ).get(field) is not True
                    for field in (
                        "unique_matching_commit_required",
                        "commit_directly_descends_from_validation_basis",
                        "commit_binds_candidate_content_sha256",
                        "commit_binds_validation_report_sha256",
                        "commit_binds_validation_report_receipt_sha256",
                        "commit_binds_requirement_ir_sha256",
                        "commit_binds_validation_basis_revision_and_tip",
                    )
                )
                or epoch31_remediation.get(
                    "candidate_generation_commit_contract", {}
                ).get("replay_or_duplicate_commit_behavior") != "FAIL_CLOSED"
            )
        )
        or (
            epoch32_remediation is not None
            and not _epoch32_runtime_binding_remediation_is_complete(
                epoch32_remediation
            )
        )
        or (
            epoch33_remediation is not None
            and not _epoch33_runtime_binding_review_remediation_is_complete(
                epoch33_remediation
            )
        )
        or (
            epoch34_remediation is not None
            and not _epoch34_runtime_binding_review_remediation_is_complete(
                epoch34_remediation
            )
        )
        or (
            epoch35_remediation is not None
            and not _epoch35_runtime_binding_path_atomicity_remediation_is_complete(
                epoch35_remediation
            )
        )
    ):
        raise ValueError(
            "Epoch 24/25/26/28/29 remediation or Epoch 30/31/32/33/34/35 rule drifted"
        )

    repository_root = Path(__file__).resolve().parents[2]
    runtime_root = staging / "tools/harness_foundry_runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    _write_text(
        runtime_root / "__init__.py",
        '\"\"\"Portable Harness Foundry v2.9 release-closure runtime.\"\"\"\n',
    )
    for filename in EPOCH2_RUNTIME_MODULES:
        source = repository_root / "src/harness_foundry_factory" / filename
        if not source.is_file():
            raise ValueError(f"Epoch 2 runtime source is missing: {filename}")
        _write_text(runtime_root / filename, source.read_text(encoding="utf-8"))
    # This control-plane manifest owns its declared module set, not every
    # component colocated in the portable runtime namespace.
    module_hashes = {
        (runtime_root / filename).relative_to(staging).as_posix(): _file_hash(runtime_root / filename)
        for filename in sorted(("__init__.py", *EPOCH2_RUNTIME_MODULES))
    }

    trust_root_source = repository_root / "AUTHORITY_TRUST_ROOT.json"
    if not trust_root_source.is_file():
        raise ValueError("pinned Authority Trust Root is missing")
    trust_root = json.loads(trust_root_source.read_text(encoding="utf-8"))
    if (
        not isinstance(trust_root, Mapping)
        or trust_root.get("trust_root_sha256")
        != _hash_without_field(trust_root, "trust_root_sha256")
        or trust_root.get("algorithm") != "ED25519"
        or trust_root.get("private_key_packaged") is not False
        or trust_root.get("creates_authority") is not False
    ):
        raise ValueError("pinned Authority Trust Root is invalid")
    _write_json(staging / "AUTHORITY_TRUST_ROOT.json", trust_root)

    schema_root = staging / "contracts/v2_9_release_closure"
    schema_root.mkdir(parents=True, exist_ok=True)
    for filename, schema in _release_closure_schemas(
        require_validation_report_binding=epoch30_remediation is not None
    ).items():
        _write_json(schema_root / filename, schema)
    schema_hashes = {
        path.relative_to(staging).as_posix(): _file_hash(path)
        for path in sorted(schema_root.glob("*.json"))
    }

    adapter_ref = "tools/harness_foundry_runtime/authority_adapter.py"
    adapter_schema_ref = (
        "contracts/v2_9_release_closure/"
        "EVENT_STORE_AUTHORITY_ADAPTER_BINDING.schema.json"
    )
    entrypoint_descriptor = {
        "module": "tools.harness_foundry_runtime.authority_adapter",
        "class": "SQLiteEventStoreAuthorityAdapter",
        "required_methods": [
            "read_current_state",
            "read_release_context",
            "assert_receipt_issued",
            "validate_precommit",
            "atomic_commit_release_ready",
        ],
    }
    adapter_contract = {
        "schema_version": "2.9",
        "contract_id": "V29_EVENT_STORE_AUTHORITY_ADAPTER_CONTRACT_V1",
        "status": "FROZEN_NOT_ACTIVATED_NOT_AUTHORIZED",
        **dict(epoch18_remediation["event_store_authority_adapter_contract"]),
        **dict(epoch18_remediation["verified_release_context_read_contract"]),
        **dict(epoch18_remediation["verified_current_state_read_contract"]),
        **dict(epoch18_remediation["atomic_release_commit_contract"]),
        **dict(epoch20_remediation["trust_root_contract"]),
        **dict(epoch20_remediation["release_commit_authorization_contract"]),
        **dict(epoch20_remediation["independent_oracle_contract"]),
        **dict(epoch22_remediation["release_commit_actual_hash_contract"]),
        **dict(epoch24_remediation["artifact_bytes_resolver_contract"]),
        **dict(epoch24_remediation["receiver_trust_anchor_contract"]),
        "implementation_ref": adapter_ref,
        "implementation_sha256": module_hashes[adapter_ref],
        "entrypoint_descriptor": entrypoint_descriptor,
        "entrypoint_sha256": _json_hash(entrypoint_descriptor),
        "binding_schema_ref": adapter_schema_ref,
        "binding_schema_sha256": schema_hashes[adapter_schema_ref],
        "trust_root_ref": "AUTHORITY_TRUST_ROOT.json",
        "trust_root_file_sha256": _file_hash(staging / "AUTHORITY_TRUST_ROOT.json"),
        "trust_root_sha256": trust_root["trust_root_sha256"],
        "candidate_local_trust_root_role": "UNTRUSTED_DISTRIBUTION_METADATA_ONLY",
        "runtime_trust_anchor_source": "RECEIVER_CONTROL_PLANE_ARGUMENT_ONLY",
        "artifact_resolver_class": "ReleaseArtifactBytesResolver",
        "artifact_resolver_runtime_paths_persisted_in_candidate": False,
        "signature_algorithm": "ED25519",
        "authority_binding_signature_required": True,
        "release_commit_signature_required": True,
        "release_commit_authorization_one_shot": True,
        "release_commit_authorization_consumed_atomically": True,
        "release_artifact_hash_authority_event": "CURRENT_STATE_COMMITTED",
        "release_artifact_hash_fields": [
            "candidate_content_sha256",
            "requirement_ir_sha256",
            "executor_release_sha256",
            "human_gate_receipt_sha256",
        ],
        "release_artifact_hashes_read_and_compared_inside_begin_immediate": True,
        "valid_signature_with_wrong_release_artifact_hash_behavior": "FAIL_CLOSED",
        "unsigned_or_attacker_signed_authority_behavior": "FAIL_CLOSED",
        "database_path_in_shareable_contract": False,
        "event_store_activated": False,
        "authority_granted": False,
        "execution_started": False,
    }
    adapter_contract["contract_sha256"] = _hash_without_field(
        adapter_contract, "contract_sha256"
    )
    _write_json(
        staging / "EVENT_STORE_AUTHORITY_ADAPTER_CONTRACT.json",
        adapter_contract,
    )

    identity_ref = "tools/harness_foundry_runtime/identity_derivation.py"
    identity_bundle_schema_ref = (
        "contracts/v2_9_release_closure/IDENTITY_BUNDLE.schema.json"
    )
    identity_input_schema_ref = (
        "contracts/v2_9_release_closure/IDENTITY_DERIVATION_INPUT.schema.json"
    )
    machine_grant_schema_ref = (
        "contracts/v2_9_release_closure/MACHINE_GRANT_BINDING.schema.json"
    )
    identity = {
        "schema_version": "2.9",
        "contract_id": "V29_THREE_LAYER_IDENTITY_CONTRACT_V1",
        "status": "FROZEN_NOT_EXECUTED",
        **dict(remediation["identity_contract"]),
        **dict(human_review_remediation["identity_implementation_contract"]),
        **dict(epoch17_remediation["identity_input_contract"]),
        **dict(epoch17_remediation["current_state_freshness_contract"]),
        **dict(epoch18_remediation["verified_current_state_read_contract"]),
        "implementation_ref": identity_ref,
        "implementation_sha256": module_hashes[identity_ref],
        "identity_bundle_schema_ref": identity_bundle_schema_ref,
        "identity_bundle_schema_sha256": schema_hashes[
            identity_bundle_schema_ref
        ],
        "identity_derivation_input_schema_ref": identity_input_schema_ref,
        "identity_derivation_input_schema_sha256": schema_hashes[
            identity_input_schema_ref
        ],
        "machine_grant_binding_schema_ref": machine_grant_schema_ref,
        "machine_grant_binding_schema_sha256": schema_hashes[
            machine_grant_schema_ref
        ],
        "authority_adapter_contract_ref": (
            "EVENT_STORE_AUTHORITY_ADAPTER_CONTRACT.json"
        ),
        "authority_adapter_contract_sha256": adapter_contract[
            "contract_sha256"
        ],
        "authority_adapter_implementation_ref": adapter_ref,
        "authority_adapter_implementation_sha256": module_hashes[adapter_ref],
        "semantic_contract_identity_binds": [
            "CONTRACT_ID",
            "CONTRACT_VERSION",
            "NORMATIVE_BEHAVIOR",
            "INPUT_OUTPUT_SCHEMA",
            "INVARIANTS",
        ],
        "implementation_release_identity_binds": [
            "EXACT_EXECUTOR_BYTES",
            "ARTIFACT_BYTES",
            "SBOM",
            "PROVENANCE",
            "TOOLCHAIN",
        ],
        "human_authorization_granted": False,
        "machine_grant_issued": False,
        "creates_authority": False,
        "execution_started": False,
    }
    identity["contract_sha256"] = _hash_without_field(identity, "contract_sha256")
    _write_json(
        staging / "SEMANTIC_IMPLEMENTATION_AUTHORIZATION_IDENTITY_CONTRACT.json",
        identity,
    )

    recovery_ref = "tools/harness_foundry_runtime/recovery_decision.py"
    recovery_schema_ref = (
        "contracts/v2_9_release_closure/RECOVERY_DECISION.schema.json"
    )
    recovery = {
        "schema_version": "2.9",
        "protocol_id": "V29_GENERIC_RECOVERY_DECISION_PROTOCOL_V1",
        "status": "FROZEN_NOT_EXECUTED",
        **dict(remediation["generic_recovery_protocol"]),
        "implementation_ref": recovery_ref,
        "implementation_sha256": module_hashes[recovery_ref],
        "decision_schema_ref": recovery_schema_ref,
        "decision_schema_sha256": schema_hashes[recovery_schema_ref],
        "required_inputs": [
            "COMMAND_RECEIPT",
            "EFFECT_CERTAINTY",
            "RESULT_RECEIPT",
            "EVENT_COMMIT_STATE",
            "GRANT_STATE",
            "CHECKPOINT",
            "RETRY_BUDGET",
        ],
        "creates_authority": False,
        "execution_started": False,
    }
    recovery["contract_sha256"] = _hash_without_field(recovery, "contract_sha256")
    _write_json(staging / "GENERIC_RECOVERY_DECISION_PROTOCOL.json", recovery)

    complexity_ref = "tools/harness_foundry_runtime/complexity_governor.py"
    complexity_schema_ref = (
        "contracts/v2_9_release_closure/COMPLEXITY_DECISION.schema.json"
    )
    complexity = {
        "schema_version": "2.9",
        "governor_id": "V29_EXECUTABLE_COMPLEXITY_GOVERNOR_V2",
        "status": "FROZEN_NOT_EXECUTED",
        **dict(remediation["complexity_governor"]),
        **dict(human_review_remediation["complexity_output_contract"]),
        "implementation_ref": complexity_ref,
        "implementation_sha256": module_hashes[complexity_ref],
        "decision_schema_ref": complexity_schema_ref,
        "decision_schema_sha256": schema_hashes[complexity_schema_ref],
        "creates_authority": False,
        "execution_started": False,
    }
    complexity["contract_sha256"] = _hash_without_field(
        complexity, "contract_sha256"
    )
    _write_json(staging / "COMPLEXITY_GOVERNOR.json", complexity)

    closure_ref = "tools/harness_foundry_runtime/closure_lanes.py"
    closure_schema_ref = (
        "contracts/v2_9_release_closure/CLOSURE_RECEIPT.schema.json"
    )
    linkage_schema_ref = (
        "contracts/v2_9_release_closure/"
        "COMPATIBILITY_LINKAGE_RECEIPT.schema.json"
    )
    trusted_context_schema_ref = (
        "contracts/v2_9_release_closure/TRUSTED_RELEASE_CONTEXT.schema.json"
    )
    final_decision_schema_ref = (
        "contracts/v2_9_release_closure/FINAL_RELEASE_DECISION.schema.json"
    )
    closure_graph = {
        "schema_version": "2.9",
        "graph_id": "V29_PRODUCT_SAFETY_RELEASE_CLOSURE_GRAPH_V1",
        "status": "FROZEN_NOT_EXECUTED",
        **dict(remediation["closure_lanes"]),
        **dict(human_review_remediation["closure_lane_contract"]),
        **dict(epoch17_remediation["trusted_release_context_contract"]),
        **dict(epoch17_remediation["closure_receipt_authority_contract"]),
        **dict(epoch18_remediation["verified_release_context_read_contract"]),
        **dict(epoch18_remediation["atomic_release_commit_contract"]),
        "implementation_ref": closure_ref,
        "implementation_sha256": module_hashes[closure_ref],
        "closure_receipt_schema_ref": closure_schema_ref,
        "closure_receipt_schema_sha256": schema_hashes[closure_schema_ref],
        "compatibility_linkage_receipt_schema_ref": linkage_schema_ref,
        "compatibility_linkage_receipt_schema_sha256": schema_hashes[
            linkage_schema_ref
        ],
        "trusted_release_context_schema_ref": trusted_context_schema_ref,
        "trusted_release_context_schema_sha256": schema_hashes[
            trusted_context_schema_ref
        ],
        "final_release_decision_schema_ref": final_decision_schema_ref,
        "final_release_decision_schema_sha256": schema_hashes[
            final_decision_schema_ref
        ],
        "authority_adapter_contract_ref": (
            "EVENT_STORE_AUTHORITY_ADAPTER_CONTRACT.json"
        ),
        "authority_adapter_contract_sha256": adapter_contract[
            "contract_sha256"
        ],
        "authority_adapter_implementation_ref": adapter_ref,
        "authority_adapter_implementation_sha256": module_hashes[adapter_ref],
        "release_ready_binding_fields": [
            "authority_scope",
            "instance_id",
            "requirement_epoch",
            "semantic_contract_identity_sha256",
            "authorization_risk_identity_sha256",
            "candidate_content_sha256",
            "requirement_ir_sha256",
            "executor_release_sha256",
            "human_gate_receipt_sha256",
        ],
        "lane_states": {
            lane: "PLANNED_NOT_EXECUTED"
            for lane in remediation["closure_lanes"]["lane_ids"]
        },
        "final_release_decision": "NOT_EVALUATED",
        "real_release_ready_requires_atomic_event_store_commit": True,
        "candidate_may_commit_release_ready": False,
        "creates_authority": False,
        "execution_started": False,
    }
    closure_graph["graph_sha256"] = _hash_without_field(
        closure_graph, "graph_sha256"
    )
    _write_json(
        staging / "PRODUCT_SAFETY_RELEASE_CLOSURE_GRAPH.json", closure_graph
    )

    projection_ref = "tools/harness_foundry_runtime/evidence_projection.py"
    evidence_schema_ref = (
        "contracts/v2_9_release_closure/EVIDENCE_INDEX_ENTRY.schema.json"
    )
    evidence = {
        "schema_version": "2.9",
        "contract_id": "V29_EVIDENCE_LIFECYCLE_AND_PROJECTION_V1",
        "status": "FROZEN_NOT_EXECUTED",
        **dict(remediation["evidence_and_projection"]),
        "implementation_ref": projection_ref,
        "implementation_sha256": module_hashes[projection_ref],
        "evidence_index_entry_schema_ref": evidence_schema_ref,
        "evidence_index_entry_schema_sha256": schema_hashes[evidence_schema_ref],
        "creates_authority": False,
        "execution_started": False,
    }
    evidence["contract_sha256"] = _hash_without_field(evidence, "contract_sha256")
    _write_json(
        staging / "EVIDENCE_LIFECYCLE_AND_PROJECTION_CONTRACT.json", evidence
    )

    coverage = _release_closure_coverage_matrix(staging, remediation)
    _write_json(staging / EPOCH2_COVERAGE_REF, coverage)

    contract_refs = [
        "SEMANTIC_IMPLEMENTATION_AUTHORIZATION_IDENTITY_CONTRACT.json",
        "GENERIC_RECOVERY_DECISION_PROTOCOL.json",
        "COMPLEXITY_GOVERNOR.json",
        "PRODUCT_SAFETY_RELEASE_CLOSURE_GRAPH.json",
        "EVIDENCE_LIFECYCLE_AND_PROJECTION_CONTRACT.json",
        "EVENT_STORE_AUTHORITY_ADAPTER_CONTRACT.json",
        "AUTHORITY_TRUST_ROOT.json",
    ]
    manifest = {
        "schema_version": "2.9",
        "manifest_id": "V29_RELEASE_CLOSURE_CONTROL_PLANE_EPOCH2",
        "program_id": context["program_id"],
        "architecture_epoch": 2,
        "control_plane_epoch": 2,
        "active_generation_mode": EPOCH2_MODE,
        "status": "FROZEN_IMPLEMENTATION_READY_NOT_AUTHORIZED",
        "correction_ids": list(EPOCH2_CORRECTION_IDS),
        "correction_coverage_ref": EPOCH2_COVERAGE_REF,
        "correction_coverage_sha256": _file_hash(staging / EPOCH2_COVERAGE_REF),
        "requirement_epoch": _current_requirement_epoch(target),
        "source_authority_required_adversarial_cases": sorted({
            *((epoch26_remediation.get("required_adversarial_cases") or [])
            if isinstance(epoch26_remediation, Mapping) else ()),
            *((epoch28_remediation.get("required_adversarial_cases") or [])
            if isinstance(epoch28_remediation, Mapping) else ()),
            *((epoch29_remediation.get("required_adversarial_cases") or [])
            if isinstance(epoch29_remediation, Mapping) else ()),
            *((epoch30_remediation.get("required_adversarial_cases") or [])
            if isinstance(epoch30_remediation, Mapping) else ()),
            *((epoch31_remediation.get("required_adversarial_cases") or [])
            if isinstance(epoch31_remediation, Mapping) else ()),
        }),
        "runtime_binder_required_adversarial_cases": sorted({
            *((
                epoch33_remediation.get("adversarial_domain_contract", {}).get(
                    "runtime_binder_required_adversarial_cases"
                )
                if isinstance(epoch33_remediation, Mapping)
                else None
            ) or epoch32_remediation.get("required_adversarial_cases") or []),
            *((epoch35_remediation.get("required_adversarial_cases") or [])
            if isinstance(epoch35_remediation, Mapping) else ()),
        }) if isinstance(epoch32_remediation, Mapping) else [],
        "factory_required_regression_tests": list(
            (
                epoch35_remediation.get("required_regression_tests")
                if isinstance(epoch35_remediation, Mapping)
                else epoch34_remediation.get("required_regression_tests")
                if isinstance(epoch34_remediation, Mapping)
                else []
            )
            or []
        ),
        "required_adversarial_cases": sorted(
            {
                *epoch20_remediation["required_adversarial_cases"],
                *epoch22_remediation["required_adversarial_cases"],
                *epoch24_remediation["required_adversarial_cases"],
            }
        ),
        "factory_oracle_imports_candidate_production_module": False,
        "standalone_oracle_imports_factory_reference_oracle": False,
        "contract_sha256": {
            relative: _file_hash(staging / relative) for relative in contract_refs
        },
        "runtime_module_sha256": module_hashes,
        "schema_sha256": schema_hashes,
        "legacy_epoch1_authority": False,
        "legacy_v2_8_topology_role": "COMPATIBILITY_ADAPTER_ONLY",
        "persistent_fact_authority": "SINGLE_APPEND_ONLY_EVENT_STORE",
        "human_authorization_status": "NOT_GRANTED",
        "machine_grant_count": 0,
        "driver_started": False,
        "active_workpack": None,
        "execution_started": False,
    }
    manifest["manifest_sha256"] = _hash_without_field(
        manifest, "manifest_sha256"
    )
    _write_json(staging / EPOCH2_MANIFEST_REF, manifest)


def _retire_legacy_control_paths_for_epoch2(staging: Path) -> None:
    """Keep old topology readable but remove it from Epoch 2 authority."""

    dag_path = staging / "ENGINEERING_PROJECT_DAG.json"
    dag = json.loads(dag_path.read_text(encoding="utf-8"))
    dag.update(
        {
            "authority_role": "V28_COMPATIBILITY_ADAPTER_ONLY",
            "successor_execution_allowed": False,
            "active_control_plane_ref": EPOCH2_MANIFEST_REF,
        }
    )
    for node in dag.get("nodes", []):
        if isinstance(node, dict):
            node["authority_role"] = "V28_COMPATIBILITY_ADAPTER_ONLY"
            node["auto_advance_eligible"] = False
    _write_json(dag_path, dag)

    manifest_path = staging / "THREE_PROJECT_PROGRAM_MANIFEST.json"
    legacy = json.loads(manifest_path.read_text(encoding="utf-8"))
    legacy.update(
        {
            "authority_role": "V28_COMPATIBILITY_ADAPTER_ONLY",
            "successor_execution_allowed": False,
            "active_control_plane_ref": EPOCH2_MANIFEST_REF,
        }
    )
    _write_json(manifest_path, legacy)

    driver_path = staging / "PROGRAM_DRIVER_CONTRACT.json"
    driver = json.loads(driver_path.read_text(encoding="utf-8"))
    driver.update(
        {
            "active_program_graph_ref": (
                "PRODUCT_SAFETY_RELEASE_CLOSURE_GRAPH.json"
            ),
            "legacy_topology_successor_execution_allowed": False,
        }
    )
    _write_json(driver_path, driver)

    automation_path = staging / "PROGRAM_AUTOMATION_POLICY.json"
    automation = json.loads(automation_path.read_text(encoding="utf-8"))
    automation.update(
        {
            "active_control_plane_ref": EPOCH2_MANIFEST_REF,
            "legacy_topology_authority": False,
        }
    )
    _write_json(automation_path, automation)

    authorization_path = staging / "AUTHORIZATION_POLICY.json"
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    authorization.update(
        {
            "v2_9_authorization_mode": (
                "THREE_LAYER_IDENTITY_WITH_MACHINE_IMPLEMENTATION_REBINDING"
            ),
            "human_authorization_status": "NOT_GRANTED",
            "machine_grant_count": 0,
            "authoring_may_create_grant": False,
        }
    )
    _write_json(authorization_path, authorization)


def _write_control_kernel_bundle(
    staging: Path,
    requirement_ir: Mapping[str, Any],
    context: Mapping[str, str],
) -> None:
    """Materialize the frozen v2.9 producer contracts without Runtime authority."""

    target = requirement_ir["target"]
    correction = target["control_plane_architecture_correction"]
    repository_root = Path(__file__).resolve().parents[2]
    runtime_root = staging / "tools/harness_foundry_runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    _write_text(
        runtime_root / "__init__.py",
        '"""Portable Harness Foundry v2.9 control runtime contracts."""\n',
    )
    runtime_sources = (
        "constants.py",
        "models.py",
        "store.py",
        "control_kernel.py",
        "local_runtime.py",
        "local_process.py",
        "startup_runtime.py",
        "requirement_completion.py",
    )
    for filename in runtime_sources:
        source = repository_root / "src/harness_foundry_factory" / filename
        if not source.is_file():
            raise ValueError(f"v2.9 control runtime source is missing: {filename}")
        _write_text(runtime_root / filename, source.read_text(encoding="utf-8"))

    # Keep unrelated project support in the whole-package inventory, not in
    # this control kernel's authority-bearing implementation manifest.
    module_hashes = {
        (runtime_root / filename).relative_to(staging).as_posix(): _file_hash(runtime_root / filename)
        for filename in sorted(("__init__.py", *runtime_sources))
    }
    evaluator_ref = "tools/harness_foundry_runtime/control_kernel.py"
    evaluator_sha256 = module_hashes[evaluator_ref]
    schema_root = staging / "contracts/v2_9"
    schema_root.mkdir(parents=True, exist_ok=True)
    schemas = _control_kernel_schemas()
    for filename, schema in schemas.items():
        _write_json(schema_root / filename, schema)
    schema_hashes = {
        path.relative_to(staging).as_posix(): _file_hash(path)
        for path in sorted(schema_root.glob("*.json"))
    }
    declared_input_schema = schemas["DECISION_INPUT.schema.json"]
    integration_correction = target.get(
        "v0_11_execution_integration_correction"
    )
    integration_enabled = isinstance(integration_correction, Mapping)
    decision_policy = {
        "schema_version": "1.0",
        "policy_id": "POLICY-V29-CONTROL-PLANE-EPOCH1",
        "status": "FROZEN",
        "rule_language_id": "HF29_DETERMINISTIC_JSON_RULES",
        "rule_language_version": "1.0",
        "evaluator_ref": f"harness-resource://candidate/{evaluator_ref}",
        "evaluator_sha256": evaluator_sha256,
        "declared_input_schema_ref": (
            "harness-resource://candidate/contracts/v2_9/DECISION_INPUT.schema.json"
        ),
        "rules": [
            {
                "rule_id": "RULE-V29-SCOPE-UNCHANGED",
                "authority_layer": "FROZEN_REQUIREMENT",
                "when": {"approved": True, "risk_delta": "NONE"},
                "decision": "MACHINE_CONTINUE",
                "reason_code": "FROZEN_SCOPE_UNCHANGED",
                "next_transition_selector": None,
            },
            {
                "rule_id": "RULE-V29-RISK-EXPANDED",
                "authority_layer": "FROZEN_REQUIREMENT",
                "when": {"approved": True, "risk_delta": "EXPANDED"},
                "decision": "HUMAN_AUTHORITY_REQUIRED",
                "reason_code": "REAL_RISK_DELTA",
                "next_transition_selector": None,
            },
            {
                "rule_id": "RULE-V29-UNKNOWN-SIDE-EFFECT",
                "authority_layer": "PLATFORM_SAFETY",
                "when": {"approved": True, "risk_delta": "UNKNOWN_SIDE_EFFECT"},
                "decision": "HARD_STOP_UNKNOWN_SIDE_EFFECT",
                "reason_code": "UNKNOWN_SIDE_EFFECT",
                "next_transition_selector": None,
            },
        ],
        "precedence": [
            "PLATFORM_SAFETY",
            "FROZEN_CHARTER",
            "FROZEN_REQUIREMENT",
            "ARCHITECTURE_POLICY",
            "TRANSITION_LOCAL",
        ],
        "conflict_policy": "FAIL_CLOSED_POLICY_CONFLICT",
        "unknown_policy": "FAIL_CLOSED_POLICY_UNKNOWN",
        "semantic_slot_authority": "PROPOSAL_ONLY_NO_DIRECT_STATE_TRANSITION",
        "decision_receipt_schema_ref": (
            "harness-resource://candidate/contracts/v2_9/DECISION_RECEIPT.schema.json"
        ),
    }
    policy_path = staging / "DECISION_POLICY.json"
    _write_json(policy_path, decision_policy)

    profile = {
        "schema_version": "1.0",
        "profile_id": target.get(
            "assurance_profile_id", "V29_CONTROL_PLANE_CORRECTION_AUTHORING"
        ),
        "status": "FROZEN",
        "risk_inputs": {
            "external_effect": "NONE",
            "irreversibility": "REVERSIBLE",
            "data_sensitivity": "INTERNAL",
            "network_mode": "DENY",
            "secret_access": False,
            "semantic_uncertainty": "LOW",
            "recovery_difficulty": "LOW",
            "certification_level": "NONE",
            "common_mode_failure_risk": "MEDIUM",
        },
        "activated_capabilities": ["CONTROL_KERNEL_VERTICAL_FIXTURE"],
        "control_domain_template_id": "CONTROL-DOMAIN-COORDINATED-AUTHORING",
        "program_graph_template_id": "PROGRAM-GRAPH-V29-GENERIC-V1",
        "human_attention_budget": {
            "max_architecture_freezes": 1,
            "max_parent_risk_authorizations": 1,
            "max_manual_hash_inputs": 0,
            "internal_flow_human_gates": 0,
        },
    }
    _write_json(staging / "ASSURANCE_PROFILE.json", profile)

    adapter_binding_ref: str | None = None
    adapter_binding_sha256: str | None = None
    activation_contract_ref: str | None = None
    activation_contract_sha256: str | None = None
    if integration_enabled:
        adapter_requirement = integration_correction.get(
            "adapter_binding_contract"
        )
        store_requirement = integration_correction.get(
            "native_control_event_store_activation_contract"
        )
        if not isinstance(adapter_requirement, Mapping) or not isinstance(
            store_requirement, Mapping
        ):
            raise ValueError(
                "v0.11 execution integration correction contracts are incomplete"
            )
        adapter_binding_ref = str(
            adapter_requirement["candidate_artifact_ref"]
        )
        adapter_binding = {
            "schema_version": "2.9",
            "binding_id": "PROFILE-READ-VALIDATION-ADAPTER-BINDING",
            "adapter_id": "PROFILE-READ-VALIDATION-ADAPTER",
            "program_id": context["program_id"],
            "transition_id": "PROFILE_READ_VALIDATION",
            "command_class": "READ_ONLY_VALIDATION",
            "binding_status": "PLANNED_NOT_BOUND",
            "implementation_ref": None,
            "implementation_sha256": None,
            "entrypoint": None,
            "result_schema_ref": (
                "harness-resource://candidate/contracts/v2_9/"
                "TRANSITION_RESULT.schema.json"
            ),
            "result_schema_sha256": schema_hashes[
                "contracts/v2_9/TRANSITION_RESULT.schema.json"
            ],
            "runtime_transition_contract_sha256": None,
            "derived_grant_binding_requirement": (
                "RUNTIME_TRANSITION_CONTRACT_SHA256_REQUIRED"
            ),
            "candidate_materializes_adapter": False,
            "execution_started": False,
        }
        adapter_binding["binding_contract_sha256"] = _hash_without_field(
            adapter_binding, "binding_contract_sha256"
        )
        _write_json(staging / adapter_binding_ref, adapter_binding)
        adapter_binding_sha256 = _file_hash(staging / adapter_binding_ref)

        activation_contract_ref = str(
            store_requirement["candidate_artifact_ref"]
        )
        native_schema = control_event_store_schema_contract()
        store_module_ref = "tools/harness_foundry_runtime/store.py"
        activation_contract = {
            "schema_version": "2.9",
            "contract_id": "CONTROL-EVENT-STORE-ACTIVATION-CONTRACT",
            "program_id": context["program_id"],
            "activation_status": "PLANNED_NOT_ACTIVATED",
            "active_store_ref": store_requirement["active_store_ref"],
            "implementation_ref": (
                f"harness-resource://candidate/{store_module_ref}"
            ),
            "implementation_sha256": module_hashes[store_module_ref],
            "schema_ref": (
                "harness-resource://candidate/contracts/v2_9/"
                "CONTROL_EVENT_STORE_ACTIVATION.schema.json"
            ),
            "schema_sha256": schema_hashes[
                "contracts/v2_9/CONTROL_EVENT_STORE_ACTIVATION.schema.json"
            ],
            "native_schema_contract": native_schema,
            "native_schema_contract_sha256": native_schema[
                "schema_contract_sha256"
            ],
            "preexisting_incompatible_store_policy": (
                "REJECT_BEFORE_SCHEMA_OR_JOURNAL_MUTATION"
            ),
            "append_only_update_delete_triggers_required": True,
            "ad_hoc_same_filename_store_reuse_forbidden": True,
            "bootstrap_import": {
                "status": "PLANNED_NOT_EXECUTED",
                "separate_migration_authorization_required": True,
                "migration_authorization_status": "NOT_GRANTED",
                "historical_v0_11_event_hash": store_requirement[
                    "historical_v0_11_event_hash"
                ],
            },
            "active_authority_count_after_activation": 1,
            "store_created": False,
            "store_migrated": False,
            "execution_started": False,
        }
        activation_contract["contract_sha256"] = _hash_without_field(
            activation_contract, "contract_sha256"
        )
        _write_json(staging / activation_contract_ref, activation_contract)
        activation_contract_sha256 = _file_hash(
            staging / activation_contract_ref
        )

    node_specs = (
        (
            "PROFILE_READ_VALIDATION",
            "READ_ONLY_VALIDATION",
            "READ_ONLY_VALIDATION",
            "PROFILE_INTERNAL_STATE",
            None,
        ),
        (
            "PROFILE_INTERNAL_STATE",
            "INTERNAL_STATE_TRANSACTION",
            "INTERNAL_STATE_TRANSACTION",
            "PROFILE_REVERSIBLE_FIXTURE",
            None,
        ),
        (
            "PROFILE_REVERSIBLE_FIXTURE",
            "BOUNDED_REVERSIBLE_FIXTURE_ACTION",
            "BOUNDED_REVERSIBLE_FIXTURE_ACTION",
            None,
            "RISK_GATE",
        ),
    )
    transitions: list[dict[str, Any]] = []
    for transition_id, node_kind, command_class, successor, stop_gate in node_specs:
        transitions.append(
            {
                "schema_version": "2.9",
                "transition_id": transition_id,
                "node_kind": node_kind,
                "precondition_claims": [],
                "input_refs": [],
                "allowed_read_roots": ["harness-resource://candidate"],
                "allowed_write_roots": [
                    "harness-resource://execution/evidence/control_kernel/"
                    f"{transition_id}"
                ],
                "required_authorization_class": "PARENT_RISK_ENVELOPE",
                "command_contract": {
                    "command_class": command_class,
                    "adapter_status": "PLANNED_NOT_BOUND",
                    **(
                        {
                            "adapter_binding_ref": (
                                "harness-resource://candidate/"
                                f"{adapter_binding_ref}"
                            ),
                            "adapter_binding_sha256": adapter_binding_sha256,
                            "runtime_transition_contract_sha256": None,
                            "derived_grant_binding_requirement": (
                                "RUNTIME_TRANSITION_CONTRACT_SHA256_REQUIRED"
                            ),
                        }
                        if integration_enabled
                        and transition_id == "PROFILE_READ_VALIDATION"
                        else {}
                    ),
                },
                "result_schema_ref": (
                    "harness-resource://candidate/contracts/v2_9/"
                    "TRANSITION_RESULT.schema.json"
                ),
                "result_schema_sha256": schema_hashes[
                    "contracts/v2_9/TRANSITION_RESULT.schema.json"
                ],
                "evidence_obligations": [f"EVIDENCE-{transition_id}"],
                "decision_policy_ref": "harness-resource://candidate/DECISION_POLICY.json",
                "decision_policy_sha256": _file_hash(policy_path),
                "rule_language_id": "HF29_DETERMINISTIC_JSON_RULES",
                "rule_language_version": "1.0",
                "rule_evaluator_ref": f"harness-resource://candidate/{evaluator_ref}",
                "rule_evaluator_sha256": evaluator_sha256,
                "declared_input_schema_ref": decision_policy[
                    "declared_input_schema_ref"
                ],
                "success_rule_ids": ["RULE-V29-SCOPE-UNCHANGED"],
                "failure_rule_ids": [
                    "RULE-V29-RISK-EXPANDED",
                    "RULE-V29-UNKNOWN-SIDE-EFFECT",
                ],
                "retry_policy": {"max_retries": 1},
                "checkpoint_policy": {"resume_requires_revalidation": True},
                "invalidation_rule_ids": ["DIRECT_DECLARED_DEPENDENCY_CHANGE"],
                "next_transition_rule_ids": ["RULE-V29-SCOPE-UNCHANGED"],
                "rule_precedence_table": list(AUTHORITY_PRECEDENCE),
                "conflict_policy": "FAIL_CLOSED_POLICY_CONFLICT",
                "unknown_policy": "FAIL_CLOSED_POLICY_UNKNOWN",
                "decision_receipt_schema_ref": decision_policy[
                    "decision_receipt_schema_ref"
                ],
                "risk": {
                    "permissions": ["WRITE_DECLARED_EVIDENCE"],
                    "network_mode": "DENY",
                    "secret_access": False,
                    "external_effect_class": "LOCAL_REVERSIBLE",
                },
                "next_transition_id": successor,
                "stop_gate": stop_gate,
                "execution_status": "PLANNED_NOT_AUTHORIZED",
            }
        )
    transition_path = staging / "TRANSITION_CONTRACTS.json"
    transition_document = {
        "schema_version": "2.9",
        "program_id": context["program_id"],
        "contracts": transitions,
        "status": "FROZEN_NOT_EXECUTED",
    }
    transition_document["contracts_sha256"] = _json_hash(transitions)
    _write_json(transition_path, transition_document)

    graph = {
        "schema_version": "2.9",
        "program_id": context["program_id"],
        "profile_ref": "harness-resource://candidate/ASSURANCE_PROFILE.json",
        "profile_sha256": _file_hash(staging / "ASSURANCE_PROFILE.json"),
        "program_graph_template_id": profile["program_graph_template_id"],
        "nodes": [
            {"transition_id": item[0], "node_kind": item[1]}
            for item in node_specs
        ],
        "edges": [
            {"from": node_specs[0][0], "to": node_specs[1][0]},
            {"from": node_specs[1][0], "to": node_specs[2][0]},
        ],
        "start_transition_id": node_specs[0][0],
        "declared_stop_gate": "RISK_GATE",
        "status": "INSTANTIATED_NOT_EXECUTED",
    }
    graph["program_graph_sha256"] = _hash_without_field(
        graph, "program_graph_sha256"
    )
    _write_json(staging / "CONTROL_PLANE_PROGRAM_GRAPH.json", graph)

    correction_coverage = _correction_coverage_matrix(staging, requirement_ir)
    if correction_coverage is not None:
        _write_json(staging / CORRECTION_COVERAGE_REF, correction_coverage)
    manifest = {
        "schema_version": "2.9",
        "manifest_id": "V29-CONTROL-KERNEL-EPOCH1",
        "program_id": context["program_id"],
        "architecture_epoch": target["architecture_epoch"],
        "control_plane_epoch": target["control_plane_epoch"],
        "architecture_lock_proposal_sha256": correction[
            "architecture_lock_proposal_sha256"
        ],
        "persistent_authority": "SINGLE_APPEND_ONLY_SQLITE_CONTROL_EVENT_STORE",
        "rebuildable_projections": [
            "GRANT_LEDGER",
            "PROGRAM_CONTROL_STATE",
            "DECISION_RECEIPTS",
            "HUMAN_COST_RESULT",
        ],
        "runtime_module_sha256": module_hashes,
        "schema_sha256": schema_hashes,
        "decision_policy_ref": "DECISION_POLICY.json",
        "decision_policy_sha256": _file_hash(policy_path),
        "assurance_profile_ref": "ASSURANCE_PROFILE.json",
        "assurance_profile_sha256": _file_hash(
            staging / "ASSURANCE_PROFILE.json"
        ),
        "program_graph_ref": "CONTROL_PLANE_PROGRAM_GRAPH.json",
        "program_graph_sha256": _file_hash(
            staging / "CONTROL_PLANE_PROGRAM_GRAPH.json"
        ),
        "transition_contracts_ref": "TRANSITION_CONTRACTS.json",
        "transition_contracts_sha256": _file_hash(transition_path),
        "adapter_binding_ref": adapter_binding_ref,
        "adapter_binding_sha256": adapter_binding_sha256,
        "control_event_store_activation_contract_ref": activation_contract_ref,
        "control_event_store_activation_contract_sha256": (
            activation_contract_sha256
        ),
        "control_event_store_activation_status": (
            "PLANNED_NOT_ACTIVATED" if integration_enabled else None
        ),
        "bootstrap_import_status": (
            "PLANNED_NOT_EXECUTED" if integration_enabled else None
        ),
        "correction_coverage_ref": (
            CORRECTION_COVERAGE_REF if correction_coverage is not None else None
        ),
        "correction_coverage_sha256": (
            _file_hash(staging / CORRECTION_COVERAGE_REF)
            if correction_coverage is not None
            else None
        ),
        "parent_authorization_status": "NOT_GRANTED",
        "derived_grant_count": 0,
        "execution_started": False,
        "legacy_v0_9_role": "READ_ONLY_GOLDEN_FIXTURE_NO_SUCCESSOR_AUTHORITY",
        "status": "FROZEN_IMPLEMENTATION_READY_NOT_AUTHORIZED",
        "non_claims": [
            "PARENT_AUTHORIZATION_GRANTED",
            "RUNTIME_EXECUTED",
            "WORKPACK_EXECUTED",
            "DRIVER_STARTED",
            "CONFORMANCE_CERTIFIED",
        ],
    }
    manifest["manifest_sha256"] = _hash_without_field(
        manifest, "manifest_sha256"
    )
    _write_json(staging / "V2_9_CONTROL_KERNEL_MANIFEST.json", manifest)


def _control_kernel_schemas() -> dict[str, dict[str, Any]]:
    object_schema = "https://json-schema.org/draft/2020-12/schema"
    return {
        "DECISION_INPUT.schema.json": {
            "$schema": object_schema,
            "$id": "harness-resource://candidate/contracts/v2_9/DECISION_INPUT.schema.json",
            "type": "object",
            "additionalProperties": False,
            "required": ["approved", "risk_delta"],
            "properties": {
                "approved": {"type": "boolean"},
                "risk_delta": {
                    "type": "string",
                    "enum": ["NONE", "EXPANDED", "UNKNOWN_SIDE_EFFECT"],
                },
            },
        },
        "CONTROL_EVENT.schema.json": {
            "$schema": object_schema,
            "$id": "harness-resource://candidate/contracts/v2_9/CONTROL_EVENT.schema.json",
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema_version",
                "event_id",
                "program_id",
                "stream_revision",
                "event_type",
                "payload",
                "previous_event_hash",
                "created_at",
                "event_hash",
            ],
            "properties": {
                "schema_version": {"const": "2.9"},
                "event_id": {"type": "string"},
                "program_id": {"type": "string"},
                "stream_revision": {"type": "integer", "minimum": 1},
                "event_type": {"type": "string"},
                "payload": {"type": "object"},
                "previous_event_hash": {"type": ["string", "null"]},
                "created_at": {"type": "string"},
                "event_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            },
        },
        "PARENT_AUTHORIZATION.schema.json": {
            "$schema": object_schema,
            "$id": "harness-resource://candidate/contracts/v2_9/PARENT_AUTHORIZATION.schema.json",
            "type": "object",
            "required": [
                "authorization_id",
                "authorization_class",
                "status",
                "program_id",
                "allowed_write_roots",
                "command_classes",
                "permissions",
                "network_mode",
                "secret_access",
                "external_effect_class",
                "budgets",
                "expires_at",
                "revocation_epoch",
                "stop_gates",
            ],
            "properties": {
                "authorization_class": {"const": "PARENT_RISK_ENVELOPE"},
                "status": {"enum": ["GRANTED", "ACTIVE", "REVOKED", "EXPIRED"]},
            },
        },
        "DERIVED_GRANT.schema.json": {
            "$schema": object_schema,
            "$id": "harness-resource://candidate/contracts/v2_9/DERIVED_GRANT.schema.json",
            "type": "object",
            "required": [
                "grant_id",
                "parent_authorization_id",
                "parent_authorization_sha256",
                "attempt_id",
                "transition_contract_sha256",
                "input_state_sha256",
                "scope",
                "expires_at",
                "revocation_epoch",
                "fencing_token",
                "status",
                "grant_sha256",
            ],
        },
        "TRANSITION_RESULT.schema.json": {
            "$schema": object_schema,
            "$id": "harness-resource://candidate/contracts/v2_9/TRANSITION_RESULT.schema.json",
            "type": "object",
            "additionalProperties": False,
            "required": ["status", "artifact_id"],
            "properties": {
                "status": {
                    "type": "string",
                    "enum": [
                        "PASS",
                        "VALIDATION_FAILED",
                        "TEMPORARY_FAILURE",
                        "UNKNOWN_SIDE_EFFECT",
                    ],
                },
                "artifact_id": {"type": "string"},
                "reason_code": {"type": "string"},
                "applied_count": {"type": "integer"},
            },
            "allOf": [
                {
                    "if": {
                        "properties": {
                            "status": {"const": "VALIDATION_FAILED"}
                        },
                        "required": ["status"],
                    },
                    "then": {"required": ["reason_code"]},
                }
            ],
        },
        "ADAPTER_BINDING.schema.json": {
            "$schema": object_schema,
            "$id": "harness-resource://candidate/contracts/v2_9/ADAPTER_BINDING.schema.json",
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema_version",
                "binding_id",
                "adapter_id",
                "program_id",
                "transition_id",
                "command_class",
                "binding_status",
                "implementation_ref",
                "implementation_sha256",
                "entrypoint",
                "result_schema_ref",
                "result_schema_sha256",
                "runtime_transition_contract_sha256",
                "derived_grant_binding_requirement",
                "candidate_materializes_adapter",
                "execution_started",
                "binding_contract_sha256",
            ],
            "properties": {
                "schema_version": {"const": "2.9"},
                "binding_id": {"type": "string"},
                "adapter_id": {"type": "string"},
                "program_id": {"type": "string"},
                "transition_id": {"type": "string"},
                "command_class": {"type": "string"},
                "binding_status": {
                    "enum": ["PLANNED_NOT_BOUND", "BOUND"]
                },
                "implementation_ref": {"type": ["string", "null"]},
                "implementation_sha256": {
                    "type": ["string", "null"],
                    "pattern": "^[0-9a-f]{64}$",
                },
                "entrypoint": {"type": ["string", "null"]},
                "result_schema_ref": {"type": "string"},
                "result_schema_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "runtime_transition_contract_sha256": {
                    "type": ["string", "null"],
                    "pattern": "^[0-9a-f]{64}$",
                },
                "derived_grant_binding_requirement": {
                    "const": "RUNTIME_TRANSITION_CONTRACT_SHA256_REQUIRED"
                },
                "candidate_materializes_adapter": {"const": False},
                "execution_started": {"const": False},
                "binding_contract_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
            },
            "allOf": [
                {
                    "if": {
                        "properties": {"binding_status": {"const": "BOUND"}},
                        "required": ["binding_status"],
                    },
                    "then": {
                        "properties": {
                            "implementation_ref": {"type": "string"},
                            "implementation_sha256": {
                                "type": "string",
                                "pattern": "^[0-9a-f]{64}$",
                            },
                            "entrypoint": {"type": "string"},
                            "runtime_transition_contract_sha256": {
                                "type": "string",
                                "pattern": "^[0-9a-f]{64}$",
                            },
                        }
                    },
                }
            ],
        },
        "CONTROL_EVENT_STORE_ACTIVATION.schema.json": {
            "$schema": object_schema,
            "$id": "harness-resource://candidate/contracts/v2_9/CONTROL_EVENT_STORE_ACTIVATION.schema.json",
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema_version",
                "contract_id",
                "program_id",
                "activation_status",
                "active_store_ref",
                "implementation_ref",
                "implementation_sha256",
                "schema_ref",
                "schema_sha256",
                "native_schema_contract",
                "native_schema_contract_sha256",
                "preexisting_incompatible_store_policy",
                "append_only_update_delete_triggers_required",
                "ad_hoc_same_filename_store_reuse_forbidden",
                "bootstrap_import",
                "active_authority_count_after_activation",
                "store_created",
                "store_migrated",
                "execution_started",
                "contract_sha256",
            ],
            "properties": {
                "schema_version": {"const": "2.9"},
                "contract_id": {"type": "string"},
                "program_id": {"type": "string"},
                "activation_status": {
                    "enum": ["PLANNED_NOT_ACTIVATED", "ACTIVATED"]
                },
                "active_store_ref": {"type": "string"},
                "implementation_ref": {"type": "string"},
                "implementation_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "schema_ref": {"type": "string"},
                "schema_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "native_schema_contract": {"type": "object"},
                "native_schema_contract_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "preexisting_incompatible_store_policy": {
                    "const": "REJECT_BEFORE_SCHEMA_OR_JOURNAL_MUTATION"
                },
                "append_only_update_delete_triggers_required": {
                    "const": True
                },
                "ad_hoc_same_filename_store_reuse_forbidden": {
                    "const": True
                },
                "bootstrap_import": {"type": "object"},
                "active_authority_count_after_activation": {"const": 1},
                "store_created": {"const": False},
                "store_migrated": {"const": False},
                "execution_started": {"const": False},
                "contract_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
            },
        },
        "DECISION_RECEIPT.schema.json": {
            "$schema": object_schema,
            "$id": "harness-resource://candidate/contracts/v2_9/DECISION_RECEIPT.schema.json",
            "type": "object",
            "required": [
                "policy_sha256",
                "evaluator_sha256",
                "transition_contract_sha256",
                "input_sha256",
                "decision",
                "matched_rule_ids",
                "reason_codes",
                "receipt_sha256",
            ],
        },
        "MINIMUM_REQUIREMENT_COMPLETION.schema.json": {
            "$schema": object_schema,
            "$id": "harness-resource://candidate/contracts/v2_9/MINIMUM_REQUIREMENT_COMPLETION.schema.json",
            "type": "object",
            "required": [
                "requirement_id",
                "instance_id",
                "state",
                "verification_level",
                "completion_rule",
                "blockers",
                "contract_sha256",
                "record_sha256",
            ],
            "properties": {
                "state": {
                    "enum": [
                        "NOT_APPLICABLE",
                        "PLANNED",
                        "PARTIAL",
                        "SATISFIED",
                        "BLOCKED",
                        "INVALIDATED",
                    ]
                },
                "verification_level": {
                    "enum": ["STATIC", "TEST", "FIXTURE", "LIVE", "INSTALLED"]
                },
            },
        },
    }


def _retire_legacy_control_paths(staging: Path) -> None:
    """Keep v2.8 artifacts readable while removing their successor authority."""

    dag_path = staging / "ENGINEERING_PROJECT_DAG.json"
    dag = json.loads(dag_path.read_text(encoding="utf-8"))
    dag.update(
        {
            "authority_role": "V28_COMPATIBILITY_FIXTURE_ONLY",
            "successor_execution_allowed": False,
            "active_control_plane_ref": "V2_9_CONTROL_KERNEL_MANIFEST.json",
        }
    )
    for node in dag.get("nodes", []):
        if isinstance(node, dict):
            node["authority_role"] = "V28_COMPATIBILITY_FIXTURE_ONLY"
            node["auto_advance_eligible"] = False
    _write_json(dag_path, dag)

    manifest_path = staging / "THREE_PROJECT_PROGRAM_MANIFEST.json"
    legacy = json.loads(manifest_path.read_text(encoding="utf-8"))
    legacy.update(
        {
            "authority_role": "V28_COMPATIBILITY_FIXTURE_ONLY",
            "successor_execution_allowed": False,
            "active_control_plane_ref": "V2_9_CONTROL_KERNEL_MANIFEST.json",
        }
    )
    _write_json(manifest_path, legacy)

    driver_path = staging / "PROGRAM_DRIVER_CONTRACT.json"
    driver = json.loads(driver_path.read_text(encoding="utf-8"))
    driver.update(
        {
            "active_program_graph_ref": "CONTROL_PLANE_PROGRAM_GRAPH.json",
            "legacy_topology_successor_execution_allowed": False,
        }
    )
    _write_json(driver_path, driver)

    automation_path = staging / "PROGRAM_AUTOMATION_POLICY.json"
    automation = json.loads(automation_path.read_text(encoding="utf-8"))
    automation.update(
        {
            "active_control_plane_ref": "V2_9_CONTROL_KERNEL_MANIFEST.json",
            "legacy_topology_authority": False,
        }
    )
    _write_json(automation_path, automation)

    authorization_path = staging / "AUTHORIZATION_POLICY.json"
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    authorization.update(
        {
            "v2_9_authorization_mode": (
                "PARENT_RISK_ENVELOPE_WITH_MACHINE_DERIVED_ATTEMPT_GRANTS"
            ),
            "parent_authorization_status": "NOT_GRANTED",
            "derived_grant_count": 0,
            "authoring_may_create_grant": False,
        }
    )
    _write_json(authorization_path, authorization)


def _shared_control_baseline_result_schema(
    execution_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the exact portable result schema declared by the frozen IR."""

    required = list(execution_contract.get("required_result_fields") or [])
    string_fields = set(required) - {
        "control_plane_epoch",
        "fencing_token",
        "produced_capabilities",
    }
    properties: dict[str, Any] = {
        field: {"type": "string"} for field in required if field in string_fields
    }
    for field in (
        "candidate_tree_sha256",
        "requirement_ir_sha256",
        "charter_sha256",
        "profile_lock_sha256",
        "authorization_policy_sha256",
        "shared_protocol_sha256",
        "schema_bundle_sha256",
        "normative_atom_catalog_sha256",
        "source_manifest_sha256",
        "human_approval_receipt_sha256",
        "command_manifest_sha256",
        "executor_implementation_sha256",
        "authorization_sha256",
        "idempotency_key",
        "result_sha256",
    ):
        if field in properties:
            properties[field]["pattern"] = "^[0-9a-f]{64}$"
    constants = {
        "schema_version": "1.0",
        "node_id": "SHARED_CONTROL_BASELINE_LOCK",
        "status": "PASS",
        "execution_mode": "REGISTRATION_ONLY",
    }
    for field, value in constants.items():
        if field in properties:
            properties[field]["const"] = value
    for field in ("started_at", "completed_at"):
        if field in properties:
            properties[field]["pattern"] = (
                r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
            )
    if "control_plane_epoch" in required:
        properties["control_plane_epoch"] = {"type": "integer", "minimum": 0}
    if "fencing_token" in required:
        properties["fencing_token"] = {"type": "integer", "minimum": 1}
    if "produced_capabilities" in required:
        properties["produced_capabilities"] = {
            "type": "array",
            "items": {"type": "string"},
            "minItems": len(execution_contract.get("produced_capabilities") or []),
            "uniqueItems": True,
        }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "harness-resource://candidate/contracts/SHARED_CONTROL_BASELINE_RESULT.schema.json",
        "title": "Shared Control Baseline Result",
        "description": (
            "Exact successful result contract for the bounded registration-only "
            "Shared Control Baseline action."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def _write_shared_control_baseline_contract(
    staging: Path,
    ir: Mapping[str, Any],
) -> None:
    """Materialize the v0.9 executable control action and exact hash bindings."""

    target = ir.get("target")
    if not isinstance(target, Mapping):
        return
    execution_contract = target.get("shared_control_baseline_execution_contract")
    default_protocol = shared_control_default()
    if execution_contract is None:
        dag = json.loads((staging / "ENGINEERING_PROJECT_DAG.json").read_text(encoding="utf-8"))
        if not any(node.get("node_id") == "SHARED_CONTROL_BASELINE_LOCK" for node in dag.get("nodes", [])):
            return
        execution_contract = default_protocol["execution_contract"]
    if not isinstance(execution_contract, Mapping):
        raise ValueError("Shared Control Baseline execution contract must be an object")
    implementation_ref = str(execution_contract.get("implementation_ref") or "")
    schema_ref = str(execution_contract.get("result_schema_ref") or "")
    action_contract_ref = str(execution_contract.get("action_contract_ref") or "")
    if (
        implementation_ref != "tools/shared_control_baseline.py"
        or schema_ref != "contracts/SHARED_CONTROL_BASELINE_RESULT.schema.json"
        or action_contract_ref
        != "validation/SHARED_CONTROL_BASELINE_ACTION_CONTRACT.json"
    ):
        raise ValueError(
            "Shared Control Baseline implementation, schema, and contract refs must use the portable v0.9 locations"
        )
    resource = (
        Path(__file__).resolve().parent
        / "resources"
        / "shared_control_baseline.py"
    )
    if not resource.is_file():
        raise ValueError("Shared Control Baseline production implementation is missing")
    implementation_path = staging / implementation_ref
    _write_text(implementation_path, resource.read_text(encoding="utf-8"))
    implementation_path.chmod(0o755)
    schema = _shared_control_baseline_result_schema(execution_contract)
    schema_path = staging / schema_ref
    _write_json(schema_path, schema)

    required_command_fields = [
        "schema_version",
        "command_id",
        "action_id",
        "node_id",
        "authorization_id",
        "candidate_tree_sha256",
        "requirement_ir_sha256",
        "executor_implementation_ref",
        "executor_implementation_sha256",
        "action_contract_sha256",
        "result_schema_sha256",
        "human_approval_receipt_sha256",
        "expected_control_state_sha256",
        "idempotency_key",
        "lease_id",
        "fencing_token",
    ]
    required_authorization_fields = [
        "schema_version",
        "authorization_id",
        "authorization_class",
        "status",
        "one_shot",
        "program_id",
        "node_id",
        "allowed_action_id",
        "command_manifest_sha256",
        "candidate_tree_sha256",
        "requirement_ir_sha256",
        "executor_implementation_sha256",
        "human_approval_receipt_sha256",
        "expected_control_state_sha256",
        "idempotency_key",
        "lease_id",
        "fencing_token",
        "not_before",
        "expires_at",
    ]
    program_manifest = json.loads(
        (staging / "THREE_PROJECT_PROGRAM_MANIFEST.json").read_text(
            encoding="utf-8"
        )
    )
    epoch_domain_contract = program_manifest.get("epoch_domains")
    if not isinstance(epoch_domain_contract, Mapping):
        raise ValueError(
            "Shared Control Baseline requires explicit architecture and execution epoch domains"
        )
    action_contract = {
        "schema_version": "1.0",
        "contract_id": execution_contract.get("contract_id"),
        "action_id": execution_contract.get("action_id"),
        "node_id": execution_contract.get("node_id"),
        "action_kind": execution_contract.get("action_kind"),
        "implementation_ref": implementation_ref,
        "executor_implementation_sha256": _file_hash(implementation_path),
        "result_schema_ref": schema_ref,
        "result_schema_sha256": _file_hash(schema_path),
        "epoch_domain_contract": deepcopy(dict(epoch_domain_contract)),
        "execution_contract": deepcopy(dict(execution_contract)),
        "test_contract": deepcopy(
            dict(target.get("shared_control_baseline_test_contract") or default_protocol["test_contract"])
        ),
        "runtime_input_contract": {
            "command_manifest_location": "EXECUTION_ROOT_LOCAL_EXPLICIT_PATH",
            "command_manifest_required_fields": required_command_fields,
            "authorization_location": "EXECUTION_ROOT_LOCAL_EXPLICIT_PATH",
            "authorization_required_fields": required_authorization_fields,
            "human_approval_receipt_ref": (
                "harness-resource://execution/evidence/engineering_dag/"
                "START_PACKAGE_HUMAN_APPROVAL/result.json"
            ),
            "control_state_ref": (
                "harness-resource://execution/.harness-foundry/control/"
                "PROGRAM_CONTROL_STATE.json"
            ),
            "candidate_identity": (
                "CANONICAL_SHA256_OF_PORTABLE_FILE_MANIFEST_FILES_MAP"
            ),
            "idempotency_derivation_fields": [
                "action_id",
                "authorization_id",
                "candidate_tree_sha256",
                "fencing_token",
                "lease_id",
                "requirement_ir_sha256",
            ],
        },
        "persistence_contract": {
            "result_ref": execution_contract.get("result_ref"),
            "transaction_journal_ref": (
                "harness-resource://execution/.harness-foundry/control/transactions/"
                "SHARED_CONTROL_BASELINE_LOCK.transaction.json"
            ),
            "lease_ref": (
                "harness-resource://execution/.harness-foundry/control/leases/"
                "SHARED_CONTROL_BASELINE_LOCK.lease.json"
            ),
            "control_event_ledger_ref": (
                "harness-resource://execution/.harness-foundry/control/"
                "PROGRAM_CONTROL_EVENTS.jsonl"
            ),
            "recovery_receipt_ref": (
                "harness-resource://execution/evidence/engineering_dag/"
                "SHARED_CONTROL_BASELINE_LOCK/recovery_receipt.json"
            ),
            "authorization_consumption_location": "PROGRAM_CONTROL_STATE_AND_EVENT_LEDGER",
        },
        "failure_codes": [
            "CANDIDATE_PORTABLE_MANIFEST_INVALID",
            "CONTROL_ACTION_INPUT_HASH_MISMATCH",
            "CONTROL_ACTION_EPOCH_DOMAIN_INVALID",
            "HUMAN_APPROVAL_RECEIPT_INVALID",
            "COMMAND_MANIFEST_INVALID",
            "REGISTRATION_AUTHORIZATION_INVALID",
            "REGISTRATION_AUTHORIZATION_REVOKED",
            "UNBOUND_OR_DRIFTED_CONTROL_ACTION_IMPLEMENTATION",
            "IDEMPOTENCY_KEY_INVALID",
            "IDEMPOTENCY_KEY_CONFLICT",
            "LEASE_CONFLICT",
            "FENCING_TOKEN_REGRESSION",
            "UNKNOWN_COMMIT_STATE",
            "SHARED_CONTROL_BASELINE_RESULT_INVALID",
        ],
        "contract_sha256": "",
    }
    action_contract["contract_sha256"] = _hash_without_field(
        action_contract, "contract_sha256"
    )
    action_contract_path = staging / action_contract_ref
    _write_json(action_contract_path, action_contract)

    dag_path = staging / "ENGINEERING_PROJECT_DAG.json"
    dag = json.loads(dag_path.read_text(encoding="utf-8"))
    node = next(
        (
            item
            for item in dag.get("nodes", [])
            if isinstance(item, dict)
            and item.get("node_id") == "SHARED_CONTROL_BASELINE_LOCK"
        ),
        None,
    )
    if not isinstance(node, dict):
        raise ValueError("Shared Control Baseline DAG node is missing")
    node.update(
        {
            "executor_action_kind": execution_contract.get("action_kind"),
            "action_id": execution_contract.get("action_id"),
            "action_contract_ref": action_contract_ref,
            "action_contract_sha256": _file_hash(action_contract_path),
            "executor_implementation_ref": implementation_ref,
            "executor_implementation_sha256": _file_hash(implementation_path),
            "result_schema_ref": schema_ref,
            "result_schema_sha256": _file_hash(schema_path),
            "transaction_protocol": "JOURNALED_ATOMIC_RECONCILIATION_V1",
        }
    )
    _write_json(dag_path, dag)

    manifest_path = staging / "THREE_PROJECT_PROGRAM_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    baseline = manifest.setdefault("shared_control_baseline", {})
    baseline.update(
        {
            "action_contract_ref": action_contract_ref,
            "action_contract_sha256": _file_hash(action_contract_path),
            "executor_implementation_ref": implementation_ref,
            "executor_implementation_sha256": _file_hash(implementation_path),
            "result_schema_ref": schema_ref,
            "result_schema_sha256": _file_hash(schema_path),
            "runtime_status": "NOT_EXECUTED",
        }
    )
    _write_json(manifest_path, manifest)

    driver_path = staging / "PROGRAM_DRIVER_CONTRACT.json"
    driver = json.loads(driver_path.read_text(encoding="utf-8"))
    registration_actions = driver.setdefault("registration_control_actions", {})
    registration_actions["SHARED_CONTROL_BASELINE_LOCK"] = {
            "action_contract_ref": action_contract_ref,
            "executor_implementation_ref": implementation_ref,
            "required_execution_mode": "REGISTRATION_ONLY",
            "automatic_successor_advance_allowed": False,
    }
    _write_json(driver_path, driver)

    policy_path = staging / "AUTHORIZATION_POLICY.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    token_fields = list(policy.get("required_token_fields") or [])
    for field in required_authorization_fields:
        if field not in token_fields:
            token_fields.append(field)
    policy["required_token_fields"] = token_fields
    policy.setdefault("validation_rules", {}).update(
        {
            "executor_implementation_hash_required": True,
            "command_manifest_hash_required": True,
            "idempotency_lease_and_fencing_required": True,
            "revoked_authorization_reuse_forbidden": True,
        }
    )
    _write_json(policy_path, policy)

    readme_path = staging / "README.md"
    readme = readme_path.read_text(encoding="utf-8")
    _write_text(
        readme_path,
        f"""{readme}

## Executable Shared Control Baseline

The `SHARED_CONTROL_BASELINE_LOCK` registration node has a real, standard-library
executor at `{implementation_ref}`. Its exact executable contract is
`{action_contract_ref}` and its successful result must match `{schema_ref}`.
The action verifies its own SHA-256 through the Candidate contract, runtime
Command Manifest, one-shot Registration Authorization, and committed result.

Run `python3 {implementation_ref} validate-contract` to verify the static
Candidate bindings. Runtime execution additionally requires an independently
created execution root containing a Human Gate receipt, control state, Command
Manifest, and unexpired Registration Authorization. The action never starts the
Driver or a Workpack and never automatically advances its successor node.
""",
    )


def _write_lab_protocol_support(staging: Path) -> None:
    runtime_root = staging / "tools/harness_foundry_runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    if not (runtime_root / "__init__.py").exists():
        _write_text(runtime_root / "__init__.py", '"""Portable Foundry protocol support."""\n')
    for filename in ("lab_protocol.py", "lab_protocol_checks.py"):
        _write_text(runtime_root / filename, (Path(__file__).parent / filename).read_text(encoding="utf-8"))
    _write_text(staging / "tools/lab_protocol_worker.py",
                (Path(__file__).parent / "resources/lab_protocol_worker.py").read_text(encoding="utf-8"))


def _write_epoch4_runtime_store_dependency_closure(
    staging: Path,
    *,
    include_workpack_runtime: bool = False,
    include_package_validation_runtime: bool = False,
) -> None:
    """Package the real local control kernel and its runtime dependencies."""

    repository_root = Path(__file__).resolve().parents[2]
    runtime_root = staging / "tools/harness_foundry_runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    _write_text(
        runtime_root / "__init__.py",
        '"""Portable Harness Foundry v2.9 runtime store contract."""\n',
    )
    module_refs = list(EPOCH40_CONTROL_RUNTIME_MODULE_REFS)
    if include_workpack_runtime:
        module_refs.extend((EPOCH45_WORKPACK_RUNTIME_MODULE_REF,
                            "tools/harness_foundry_runtime/coding_protocol.py",
                            "tools/harness_foundry_runtime/coding_process.py",
                            "tools/harness_foundry_runtime/coding_runtime.py",
                            "tools/harness_foundry_runtime/workpack_acceptance.py",
                            "tools/harness_foundry_runtime/workpack_evidence.py",
                            "tools/harness_foundry_runtime/project_verification.py"))
    if include_package_validation_runtime:
        module_refs.append(EPOCH49_PACKAGE_VALIDATION_RUNTIME_MODULE_REF)
    for module_ref in module_refs:
        filename = Path(module_ref).name
        source = repository_root / "src/harness_foundry_factory" / filename
        if not source.is_file():
            raise ValueError(f"Epoch 4 runtime store dependency is missing: {filename}")
        _write_text(runtime_root / filename, source.read_text(encoding="utf-8"))
    if include_workpack_runtime:
        _write_lab_protocol_support(staging)


def _control_plane_registration_result_schema() -> dict[str, Any]:
    required = [
        "schema_version",
        "result_id",
        "program_id",
        "node_id",
        "status",
        "execution_mode",
        "control_plane_epoch",
        "candidate_tree_sha256",
        "requirement_ir_sha256",
        "shared_control_baseline_result_sha256",
        "control_runtime_module_sha256s",
        "control_runtime_bundle_sha256",
        "command_manifest_sha256",
        "executor_implementation_sha256",
        "action_contract_sha256",
        "result_schema_sha256",
        "authorization_id",
        "authorization_sha256",
        "idempotency_key",
        "lease_id",
        "fencing_token",
        "produced_capabilities",
        "driver_started",
        "workpack_started",
        "started_at",
        "completed_at",
        "result_sha256",
    ]
    sha_fields = {
        "candidate_tree_sha256",
        "requirement_ir_sha256",
        "shared_control_baseline_result_sha256",
        "control_runtime_bundle_sha256",
        "command_manifest_sha256",
        "executor_implementation_sha256",
        "action_contract_sha256",
        "result_schema_sha256",
        "authorization_sha256",
        "idempotency_key",
        "result_sha256",
    }
    properties: dict[str, Any] = {
        field: {"type": "string"} for field in required
    }
    properties.update(
        {
            "schema_version": {"type": "string", "const": "1.0"},
            "node_id": {"type": "string", "const": "CONTROL_PLANE_REGISTRATION"},
            "status": {"type": "string", "const": "PASS"},
            "execution_mode": {"type": "string", "const": "REGISTRATION_ONLY"},
            "control_plane_epoch": {"type": "integer", "minimum": 0},
            "control_runtime_module_sha256s": {
                "type": "object",
                "additionalProperties": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
            },
            "fencing_token": {"type": "integer", "minimum": 1},
            "produced_capabilities": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "uniqueItems": True,
            },
            "driver_started": {"type": "boolean", "const": False},
            "workpack_started": {"type": "boolean", "const": False},
        }
    )
    for field in sha_fields:
        properties[field]["pattern"] = "^[0-9a-f]{64}$"
    for field in ("started_at", "completed_at"):
        properties[field]["pattern"] = (
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
        )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "harness-resource://candidate/contracts/CONTROL_PLANE_REGISTRATION_RESULT.schema.json",
        "title": "Control Plane Registration Result",
        "description": (
            "Exact registration-only result for the portable v2.9 control-plane "
            "executable closure. It does not prove or start the Program Driver."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def _write_control_plane_registration_contract(
    staging: Path, *, profile_ref: str = "EPOCH38_GENERATION_PROFILE.json"
) -> None:
    """Bind the CONTROL_PLANE_REGISTRATION node to a real one-shot action."""

    implementation_ref = "tools/control_plane_registration.py"
    action_contract_ref = (
        "validation/CONTROL_PLANE_REGISTRATION_ACTION_CONTRACT.json"
    )
    result_schema_ref = (
        "contracts/CONTROL_PLANE_REGISTRATION_RESULT.schema.json"
    )
    profile_path = staging / profile_ref
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assurance_profile = str(profile.get("assurance_profile") or "")
    if assurance_profile != "SELF_USE_LOCAL_TRUSTED_OPERATOR":
        raise ValueError(
            "Control Plane Registration local authorization schema requires "
            "SELF_USE_LOCAL_TRUSTED_OPERATOR"
        )
    resource = (
        Path(__file__).resolve().parent
        / "resources"
        / "control_plane_registration.py"
    )
    if not resource.is_file():
        raise ValueError("Control Plane Registration production implementation is missing")
    implementation_path = staging / implementation_ref
    _write_text(implementation_path, resource.read_text(encoding="utf-8"))
    implementation_path.chmod(0o755)
    schema_path = staging / result_schema_ref
    _write_json(schema_path, _control_plane_registration_result_schema())

    runtime_module_refs = list(EPOCH40_CONTROL_RUNTIME_MODULE_REFS)
    runtime_module_sha256s = {
        ref: _file_hash(staging / ref) for ref in runtime_module_refs
    }
    required_command_fields = [
        "schema_version",
        "command_id",
        "action_id",
        "node_id",
        "authorization_id",
        "candidate_tree_sha256",
        "requirement_ir_sha256",
        "executor_implementation_ref",
        "executor_implementation_sha256",
        "action_contract_sha256",
        "result_schema_sha256",
        "shared_control_baseline_result_sha256",
        "control_runtime_bundle_sha256",
        "expected_control_state_sha256",
        "idempotency_key",
        "lease_id",
        "fencing_token",
    ]
    required_authorization_fields = [
        "schema_version",
        "authorization_id",
        "authorization_class",
        "status",
        "one_shot",
        "program_id",
        "issuer_role",
        "issued_at",
        "node_id",
        "allowed_action_id",
        "scope",
        "command_manifest_hashes",
        "command_manifest_sha256",
        "candidate_tree_sha256",
        "requirement_ir_sha256",
        "executor_implementation_sha256",
        "human_approval_receipt_sha256",
        "shared_control_baseline_result_sha256",
        "control_runtime_bundle_sha256",
        "expected_control_state_sha256",
        "idempotency_key",
        "lease_id",
        "fencing_token",
        "max_transitions",
        "delegation_allowed",
        "signature_policy",
        "signature",
        "not_before",
        "expires_at",
    ]
    runtime_internal_write_refs = [
        (
            "harness-resource://execution/.harness-foundry/control/"
            "PROGRAM_CONTROL_STATE.json"
        ),
        (
            "harness-resource://execution/.harness-foundry/control/"
            "PROGRAM_CONTROL_EVENTS.jsonl"
        ),
        (
            "harness-resource://execution/.harness-foundry/control/transactions/"
            "CONTROL_PLANE_REGISTRATION.transaction.json"
        ),
        (
            "harness-resource://execution/.harness-foundry/control/leases/"
            "CONTROL_PLANE_REGISTRATION.lease.json"
        ),
        (
            "harness-resource://execution/evidence/engineering_dag/"
            "CONTROL_PLANE_REGISTRATION/result.json"
        ),
        (
            "harness-resource://execution/evidence/engineering_dag/"
            "CONTROL_PLANE_REGISTRATION/recovery_receipt.json"
        ),
    ]
    authorization_profile = {
        "schema_id": "EPOCH41_LOCAL_REGISTRATION_AUTHORIZATION_V1",
        "assurance_profile": assurance_profile,
        "authorization_class": "REGISTRATION_AUTHORIZATION",
        "issuer_role": "LOCAL_TRUSTED_OPERATOR",
        "max_transitions": 1,
        "delegation_allowed": False,
        "signature_policy": "NOT_APPLICABLE_SELF_USE_LOCAL_TRUSTED_OPERATOR",
        "signature_value": None,
        "external_cryptographic_signature_required": False,
        "required_fields": required_authorization_fields,
        "scope_contract": {
            "required_fields": [
                "program_id",
                "node_id",
                "allowed_action_id",
                "execution_mode",
                "runtime_internal_write_refs",
            ],
            "program_id_binding": "EXACT_ACTIVE_PROGRAM_ID",
            "node_id": "CONTROL_PLANE_REGISTRATION",
            "allowed_action_id": "REGISTER-CONTROL-PLANE-EXECUTABLE-CLOSURE",
            "execution_mode": "REGISTRATION_ONLY",
            "runtime_internal_write_refs": runtime_internal_write_refs,
        },
    }
    execution_contract = {
        "schema_version": "1.0",
        "contract_id": "CONTROL_PLANE_REGISTRATION_EXECUTABLE_CLOSURE_V1",
        "action_id": "REGISTER-CONTROL-PLANE-EXECUTABLE-CLOSURE",
        "node_id": "CONTROL_PLANE_REGISTRATION",
        "action_kind": "REGISTRATION_ONLY",
        "successor_node_id": "PROGRAM_DRIVER_RUNTIME_VERIFIED",
        "required_predecessor_node_id": "SHARED_CONTROL_BASELINE_LOCK",
        "required_predecessor_result_ref": (
            "harness-resource://execution/evidence/engineering_dag/"
            "SHARED_CONTROL_BASELINE_LOCK/result.json"
        ),
        "produced_capabilities": ["CONTROL_PLANE_REGISTRATION_PASS"],
        "required_result_fields": _control_plane_registration_result_schema()[
            "required"
        ],
        "driver_start_allowed": False,
        "workpack_start_allowed": False,
        "automatic_successor_advance_allowed": False,
        "transaction_protocol": "JOURNALED_ATOMIC_RECONCILIATION_V1",
        "recovery_contract": {
            "crash_points": [
                "AFTER_PREPARE_BEFORE_RESULT_RENAME",
                "AFTER_RESULT_RENAME_BEFORE_EVENT_APPEND",
                "AFTER_EVENT_APPEND_BEFORE_STATE_REPLACE",
                "AFTER_STATE_REPLACE_BEFORE_RESPONSE",
            ],
            "duplicate_side_effect_count_required": 0,
        },
    }
    program_manifest = json.loads(
        (staging / "THREE_PROJECT_PROGRAM_MANIFEST.json").read_text(
            encoding="utf-8"
        )
    )
    epoch_domain_contract = program_manifest.get("epoch_domains")
    if not isinstance(epoch_domain_contract, Mapping):
        raise ValueError(
            "Control Plane Registration requires explicit architecture and execution epoch domains"
        )
    action_contract = {
        "schema_version": "1.0",
        "contract_id": execution_contract["contract_id"],
        "action_id": execution_contract["action_id"],
        "node_id": execution_contract["node_id"],
        "action_kind": execution_contract["action_kind"],
        "implementation_ref": implementation_ref,
        "generation_profile_ref": profile_ref,
        "executor_implementation_sha256": _file_hash(implementation_path),
        "result_schema_ref": result_schema_ref,
        "result_schema_sha256": _file_hash(schema_path),
        "epoch_domain_contract": deepcopy(dict(epoch_domain_contract)),
        "runtime_module_refs": runtime_module_refs,
        "runtime_module_sha256s": runtime_module_sha256s,
        "runtime_bundle_sha256": _json_hash(runtime_module_sha256s),
        "authorization_profile": authorization_profile,
        "runtime_internal_write_refs": runtime_internal_write_refs,
        "execution_contract": execution_contract,
        "runtime_input_contract": {
            "command_manifest_required_fields": required_command_fields,
            "authorization_required_fields": required_authorization_fields,
            "predecessor_result_ref": execution_contract[
                "required_predecessor_result_ref"
            ],
            "control_state_ref": (
                "harness-resource://execution/.harness-foundry/control/"
                "PROGRAM_CONTROL_STATE.json"
            ),
            "control_event_ledger_ref": (
                "harness-resource://execution/.harness-foundry/control/"
                "PROGRAM_CONTROL_EVENTS.jsonl"
            ),
            "idempotency_derivation_fields": [
                "action_id",
                "authorization_id",
                "candidate_tree_sha256",
                "control_runtime_bundle_sha256",
                "fencing_token",
                "lease_id",
                "requirement_ir_sha256",
                "shared_control_baseline_result_sha256",
            ],
        },
        "persistence_contract": {
            "result_ref": (
                "harness-resource://execution/evidence/engineering_dag/"
                "CONTROL_PLANE_REGISTRATION/result.json"
            ),
            "transaction_journal_ref": (
                "harness-resource://execution/.harness-foundry/control/"
                "transactions/CONTROL_PLANE_REGISTRATION.transaction.json"
            ),
            "lease_ref": (
                "harness-resource://execution/.harness-foundry/control/"
                "leases/CONTROL_PLANE_REGISTRATION.lease.json"
            ),
            "control_state_ref": runtime_internal_write_refs[0],
            "control_event_ledger_ref": runtime_internal_write_refs[1],
            "recovery_receipt_ref": runtime_internal_write_refs[5],
            "authorization_consumption_location": (
                "PROGRAM_CONTROL_STATE_AND_EVENT_LEDGER"
            ),
        },
        "failure_codes": [
            "CONTROL_PLANE_REGISTRATION_CONTRACT_INVALID",
            "CONTROL_PLANE_RUNTIME_MODULE_INVALID",
            "CONTROL_ACTION_EPOCH_DOMAIN_INVALID",
            "SHARED_CONTROL_BASELINE_RESULT_INVALID",
            "COMMAND_MANIFEST_INVALID",
            "REGISTRATION_AUTHORIZATION_INVALID",
            "REGISTRATION_AUTHORIZATION_REVOKED",
            "UNBOUND_OR_DRIFTED_CONTROL_ACTION_IMPLEMENTATION",
            "IDEMPOTENCY_KEY_INVALID",
            "LEASE_CONFLICT",
            "FENCING_TOKEN_REGRESSION",
            "CONTROL_EVENT_LEDGER_INVALID",
            "UNKNOWN_COMMIT_STATE",
        ],
        "contract_sha256": "",
    }
    action_contract["contract_sha256"] = _hash_without_field(
        action_contract, "contract_sha256"
    )
    action_contract_path = staging / action_contract_ref
    _write_json(action_contract_path, action_contract)

    dag_path = staging / "ENGINEERING_PROJECT_DAG.json"
    dag = json.loads(dag_path.read_text(encoding="utf-8"))
    node = next(
        (
            item
            for item in dag.get("nodes", [])
            if isinstance(item, dict)
            and item.get("node_id") == "CONTROL_PLANE_REGISTRATION"
        ),
        None,
    )
    if not isinstance(node, dict):
        raise ValueError("Control Plane Registration DAG node is missing")
    node.update(
        {
            "executor_action_kind": "REGISTRATION_ONLY",
            "action_id": execution_contract["action_id"],
            "action_contract_ref": action_contract_ref,
            "action_contract_sha256": _file_hash(action_contract_path),
            "executor_implementation_ref": implementation_ref,
            "executor_implementation_sha256": _file_hash(implementation_path),
            "result_schema_ref": result_schema_ref,
            "result_schema_sha256": _file_hash(schema_path),
            "runtime_bundle_sha256": action_contract["runtime_bundle_sha256"],
            "transaction_protocol": "JOURNALED_ATOMIC_RECONCILIATION_V1",
            "runtime_internal_write_refs": runtime_internal_write_refs,
        }
    )
    _write_json(dag_path, dag)

    manifest_path = staging / "THREE_PROJECT_PROGRAM_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["control_plane_registration"] = {
        "action_contract_ref": action_contract_ref,
        "action_contract_sha256": _file_hash(action_contract_path),
        "executor_implementation_ref": implementation_ref,
        "executor_implementation_sha256": _file_hash(implementation_path),
        "result_schema_ref": result_schema_ref,
        "result_schema_sha256": _file_hash(schema_path),
        "runtime_module_sha256s": runtime_module_sha256s,
        "runtime_bundle_sha256": action_contract["runtime_bundle_sha256"],
        "runtime_status": "NOT_EXECUTED",
        "driver_started": False,
        "workpack_started": False,
    }
    _write_json(manifest_path, manifest)

    driver_path = staging / "PROGRAM_DRIVER_CONTRACT.json"
    driver = json.loads(driver_path.read_text(encoding="utf-8"))
    actions = driver.setdefault("registration_control_actions", {})
    actions["CONTROL_PLANE_REGISTRATION"] = {
        "action_contract_ref": action_contract_ref,
        "executor_implementation_ref": implementation_ref,
        "required_execution_mode": "REGISTRATION_ONLY",
        "automatic_successor_advance_allowed": False,
        "driver_start_allowed": False,
        "workpack_start_allowed": False,
    }
    _write_json(driver_path, driver)

    policy_path = staging / "AUTHORIZATION_POLICY.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    token_fields = list(policy.get("required_token_fields") or [])
    for field in required_authorization_fields:
        if field not in token_fields:
            token_fields.append(field)
    policy["required_token_fields"] = token_fields
    policy.setdefault("profile_authorization_schemas", {}).setdefault(
        assurance_profile, {}
    )["REGISTRATION_AUTHORIZATION"] = deepcopy(authorization_profile)
    policy.setdefault("validation_rules", {}).update(
        {
            "registration_predecessor_hash_required": True,
            "control_runtime_bundle_hash_required": True,
            "registration_state_cas_required": True,
            "registration_event_tip_required": True,
            "registration_one_shot_idempotency_fencing_required": True,
            "registration_profile_schema_exact_match_required": True,
            "registration_runtime_internal_write_containment_required": True,
        }
    )
    _write_json(policy_path, policy)

    negative_path = staging / "validation/NEGATIVE_CASES.json"
    negative = json.loads(negative_path.read_text(encoding="utf-8"))
    cases = list(negative.get("cases") or [])
    existing_case_ids = {
        str(case.get("case_id"))
        for case in cases
        if isinstance(case, Mapping)
    }
    registration_cases = [
        {
            "case_id": "NEG-V29-E41-REGISTRATION-AUTHORITY-SCOPE",
            "atom_ids": ["ATOM-V29-P0-04", "ATOM-V29-P0-05"],
            "description": (
                "Registration authorization missing the local issuer, exact scope, "
                "one-transition budget, or nondelegation binding must fail."
            ),
            "expected_failure": "REGISTRATION_AUTHORIZATION_INVALID",
            "fixture_kind": "NON_EXECUTABLE_JSON",
            "input_fixture": {
                "issuer_role": None,
                "scope": {"node_id": "WRONG_NODE"},
                "max_transitions": 2,
                "delegation_allowed": True,
            },
            "origin": "EPOCH41_REGISTRATION_AUTHORIZATION_POLICY_CLOSURE",
        },
        {
            "case_id": "NEG-V29-E41-REGISTRATION-HUMAN-SIGNATURE-PROFILE",
            "atom_ids": ["ATOM-V29-P0-05"],
            "description": (
                "Registration authorization without the approved Human Review receipt "
                "or with a non-local signature policy must fail."
            ),
            "expected_failure": "REGISTRATION_AUTHORIZATION_INVALID",
            "fixture_kind": "NON_EXECUTABLE_JSON",
            "input_fixture": {
                "human_approval_receipt_sha256": "0" * 64,
                "signature_policy": "EXTERNAL_SIGNATURE_REQUIRED",
                "signature": "FORGED",
            },
            "origin": "EPOCH41_REGISTRATION_AUTHORIZATION_POLICY_CLOSURE",
        },
        {
            "case_id": "NEG-V29-E41-REGISTRATION-INTERNAL-WRITE-CONTAINMENT",
            "atom_ids": ["ATOM-V29-P0-04", "ATOM-V29-P0-07"],
            "description": (
                "Any Registration runtime-internal write outside the declared Execution "
                "Root resource set must fail before transaction preparation."
            ),
            "expected_failure": "CONTROL_PLANE_REGISTRATION_CONTRACT_INVALID",
            "fixture_kind": "NON_EXECUTABLE_JSON",
            "input_fixture": {
                "runtime_internal_write_refs": [
                    "FORBIDDEN_CANDIDATE_WRITE_REF"
                ]
            },
            "origin": "EPOCH41_REGISTRATION_AUTHORIZATION_POLICY_CLOSURE",
        },
    ]
    cases.extend(
        case for case in registration_cases
        if profile_ref == "EPOCH38_GENERATION_PROFILE.json"
        and case["case_id"] not in existing_case_ids
    )
    negative["cases"] = cases
    _write_json(negative_path, negative)

    readme_path = staging / "README.md"
    readme = readme_path.read_text(encoding="utf-8")
    _write_text(
        readme_path,
        f"""{readme}

## Executable Control Plane Registration

The `CONTROL_PLANE_REGISTRATION` node is bound to the standard-library action
`{implementation_ref}`, its exact contract `{action_contract_ref}`, and result
schema `{result_schema_ref}`. The action registers the Hash-bound portable
`GenericTransitionEngine` runtime closure after validating the committed Shared
Control Baseline receipt, one-shot authorization, fencing token, event tip, and
control-state CAS. Under `SELF_USE_LOCAL_TRUSTED_OPERATOR`, the authorization is
bound to the local operator, exact scope, one-transition budget, Human Review
receipt, and an explicit non-applicable external-signature policy. Runtime-owned
control writes are separately enumerated and contained within the Execution Root.
The action neither starts the Program Driver nor executes a Workpack.
""",
    )


def _program_driver_runtime_verification_result_schema(
    successor_node_id: str = "MAIN_EXECUTION_PACKAGE_MATERIALIZED",
) -> dict[str, Any]:
    required = [
        "schema_version",
        "result_id",
        "program_id",
        "node_id",
        "next_node",
        "status",
        "execution_mode",
        "control_plane_epoch",
        "candidate_tree_sha256",
        "requirement_ir_sha256",
        "control_plane_registration_result_sha256",
        "driver_entrypoint_ref",
        "driver_entrypoint_sha256",
        "command_manifest_sha256",
        "executor_implementation_sha256",
        "action_contract_sha256",
        "result_schema_sha256",
        "authorization_id",
        "authorization_sha256",
        "idempotency_key",
        "lease_id",
        "fencing_token",
        "probe_commands",
        "probe_results",
        "probe_bundle_sha256",
        "produced_capabilities",
        "driver_started",
        "workpack_started",
        "side_effects_allowed",
        "started_at",
        "completed_at",
        "result_sha256",
    ]
    sha_fields = {
        "candidate_tree_sha256",
        "requirement_ir_sha256",
        "control_plane_registration_result_sha256",
        "driver_entrypoint_sha256",
        "command_manifest_sha256",
        "executor_implementation_sha256",
        "action_contract_sha256",
        "result_schema_sha256",
        "authorization_sha256",
        "idempotency_key",
        "probe_bundle_sha256",
        "result_sha256",
    }
    properties: dict[str, Any] = {
        field: {"type": "string"} for field in required
    }
    properties.update(
        {
            "schema_version": {"type": "string", "const": "1.0"},
            "node_id": {
                "type": "string",
                "const": "PROGRAM_DRIVER_RUNTIME_VERIFIED",
            },
            "next_node": {
                "type": "string",
                "const": successor_node_id,
            },
            "status": {"type": "string", "const": "PASS"},
            "execution_mode": {
                "type": "string",
                "const": "PROJECT_VALIDATION",
            },
            "control_plane_epoch": {"type": "integer", "minimum": 0},
            "fencing_token": {"type": "integer", "minimum": 1},
            "probe_commands": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 3,
                "uniqueItems": True,
            },
            "probe_results": {"type": "object"},
            "produced_capabilities": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "uniqueItems": True,
            },
            "driver_started": {"type": "boolean", "const": False},
            "workpack_started": {"type": "boolean", "const": False},
            "side_effects_allowed": {"type": "boolean", "const": False},
        }
    )
    for field in sha_fields:
        properties[field]["pattern"] = "^[0-9a-f]{64}$"
    for field in ("started_at", "completed_at"):
        properties[field]["pattern"] = (
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
        )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            "harness-resource://candidate/contracts/"
            "PROGRAM_DRIVER_RUNTIME_VERIFICATION_RESULT.schema.json"
        ),
        "title": "Program Driver Runtime Verification Result",
        "description": (
            "Hash-bound read-only pre-start verification result for the "
            "portable Program Driver. It does not start the Driver or a Workpack."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def _write_program_driver_runtime_verification_contract(
    staging: Path, *, profile_ref: str = "EPOCH38_GENERATION_PROFILE.json"
) -> None:
    """Bind PROGRAM_DRIVER_RUNTIME_VERIFIED to a real read-only action."""

    implementation_ref = "tools/program_driver_runtime_verification.py"
    entrypoint_ref = "tools/program_driver.py"
    action_contract_ref = (
        "validation/PROGRAM_DRIVER_RUNTIME_VERIFICATION_ACTION_CONTRACT.json"
    )
    result_schema_ref = (
        "contracts/PROGRAM_DRIVER_RUNTIME_VERIFICATION_RESULT.schema.json"
    )
    dag = json.loads((staging / "ENGINEERING_PROJECT_DAG.json").read_text(encoding="utf-8"))
    driver_nodes = [node for node in dag.get("nodes", [])
                    if node.get("node_id") == "PROGRAM_DRIVER_RUNTIME_VERIFIED"]
    successors = driver_nodes[0].get("allowed_next_nodes") if len(driver_nodes) == 1 else None
    if not isinstance(successors, list) or len(successors) != 1:
        raise ValueError("Program Driver verifier requires one explicit DAG successor")
    successor_node_id = successors[0]
    resources = Path(__file__).resolve().parent / "resources"
    for source_name, destination_ref in (
        ("program_driver.py", entrypoint_ref),
        ("program_driver_runtime_verification.py", implementation_ref),
    ):
        source = resources / source_name
        if not source.is_file():
            raise ValueError(
                f"Program Driver runtime resource is missing: {source_name}"
            )
        destination = staging / destination_ref
        _write_text(destination, source.read_text(encoding="utf-8"))
        destination.chmod(0o755)

    schema_path = staging / result_schema_ref
    _write_json(
        schema_path, _program_driver_runtime_verification_result_schema(successor_node_id)
    )
    profile = json.loads(
        (staging / profile_ref).read_text(
            encoding="utf-8"
        )
    )
    assurance_profile = str(profile.get("assurance_profile") or "")
    if assurance_profile != "SELF_USE_LOCAL_TRUSTED_OPERATOR":
        raise ValueError(
            "Program Driver verification local authorization schema requires "
            "SELF_USE_LOCAL_TRUSTED_OPERATOR"
        )

    probe_commands = ["status", "plan-next", "validate-transition"]
    required_command_fields = [
        "schema_version",
        "command_id",
        "action_id",
        "node_id",
        "authorization_id",
        "candidate_tree_sha256",
        "requirement_ir_sha256",
        "executor_implementation_ref",
        "executor_implementation_sha256",
        "driver_entrypoint_ref",
        "driver_entrypoint_sha256",
        "action_contract_sha256",
        "result_schema_sha256",
        "control_plane_registration_result_sha256",
        "expected_control_state_sha256",
        "expected_event_tip",
        "read_only_probe_commands",
        "idempotency_key",
        "lease_id",
        "fencing_token",
    ]
    required_authorization_fields = [
        "schema_version",
        "authorization_id",
        "authorization_class",
        "status",
        "one_shot",
        "program_id",
        "issuer_role",
        "issued_at",
        "node_id",
        "allowed_action_id",
        "scope",
        "command_manifest_hashes",
        "command_manifest_sha256",
        "candidate_tree_sha256",
        "requirement_ir_sha256",
        "executor_implementation_sha256",
        "driver_entrypoint_sha256",
        "human_approval_receipt_sha256",
        "control_plane_registration_result_sha256",
        "expected_control_state_sha256",
        "expected_event_tip",
        "read_only_probe_commands",
        "forbidden_actions",
        "idempotency_key",
        "lease_id",
        "fencing_token",
        "max_transitions",
        "delegation_allowed",
        "signature_policy",
        "signature",
        "not_before",
        "expires_at",
    ]
    runtime_internal_write_refs = [
        (
            "harness-resource://execution/.harness-foundry/control/"
            "PROGRAM_CONTROL_STATE.json"
        ),
        (
            "harness-resource://execution/.harness-foundry/control/"
            "PROGRAM_CONTROL_EVENTS.jsonl"
        ),
        (
            "harness-resource://execution/.harness-foundry/control/"
            "transactions/PROGRAM_DRIVER_RUNTIME_VERIFIED.transaction.json"
        ),
        (
            "harness-resource://execution/.harness-foundry/control/"
            "leases/PROGRAM_DRIVER_RUNTIME_VERIFIED.lease.json"
        ),
        (
            "harness-resource://execution/evidence/engineering_dag/"
            "PROGRAM_DRIVER_RUNTIME_VERIFIED/result.json"
        ),
    ]
    authorization_profile = {
        "schema_id": "EPOCH43_LOCAL_PROJECT_VALIDATION_AUTHORIZATION_V1",
        "assurance_profile": assurance_profile,
        "authorization_class": "PROJECT_VALIDATION_AUTHORIZATION",
        "issuer_role": "LOCAL_TRUSTED_OPERATOR",
        "max_transitions": 1,
        "delegation_allowed": False,
        "signature_policy": "NOT_APPLICABLE_SELF_USE_LOCAL_TRUSTED_OPERATOR",
        "signature_value": None,
        "external_cryptographic_signature_required": False,
        "required_fields": required_authorization_fields,
        "scope_contract": {
            "required_fields": [
                "program_id",
                "node_id",
                "allowed_action_id",
                "execution_mode",
                "read_only_probe_commands",
                "runtime_internal_write_refs",
            ],
            "program_id_binding": "EXACT_ACTIVE_PROGRAM_ID",
            "node_id": "PROGRAM_DRIVER_RUNTIME_VERIFIED",
            "allowed_action_id": "VERIFY-PORTABLE-PROGRAM-DRIVER-RUNTIME",
            "execution_mode": "PROJECT_VALIDATION",
            "read_only_probe_commands": probe_commands,
            "runtime_internal_write_refs": runtime_internal_write_refs,
        },
    }
    execution_contract = {
        "schema_version": "1.0",
        "contract_id": "PROGRAM_DRIVER_RUNTIME_VERIFICATION_CLOSURE_V1",
        "action_id": "VERIFY-PORTABLE-PROGRAM-DRIVER-RUNTIME",
        "node_id": "PROGRAM_DRIVER_RUNTIME_VERIFIED",
        "action_kind": "PROJECT_VALIDATION",
        "successor_node_id": successor_node_id,
        "required_predecessor_node_id": "CONTROL_PLANE_REGISTRATION",
        "required_predecessor_result_ref": (
            "harness-resource://execution/evidence/engineering_dag/"
            "CONTROL_PLANE_REGISTRATION/result.json"
        ),
        "produced_capabilities": ["PROGRAM_DRIVER_RUNTIME_VERIFIED_PASS"],
        "required_result_fields": (
            _program_driver_runtime_verification_result_schema(successor_node_id)["required"]
        ),
        "read_only_probe_commands": probe_commands,
        "driver_start_allowed": False,
        "workpack_start_allowed": False,
        "automatic_successor_advance_allowed": False,
        "transaction_protocol": "JOURNALED_ONE_SHOT_STATE_CAS_V1",
        "unknown_commit_state_policy": "FAIL_CLOSED_NO_REPLAY",
    }
    manifest = json.loads(
        (staging / "THREE_PROJECT_PROGRAM_MANIFEST.json").read_text(
            encoding="utf-8"
        )
    )
    epoch_domains = manifest.get("epoch_domains")
    if not isinstance(epoch_domains, Mapping):
        raise ValueError(
            "Program Driver verification requires explicit epoch domains"
        )
    action_contract = {
        "schema_version": "1.0",
        "contract_id": execution_contract["contract_id"],
        "action_id": execution_contract["action_id"],
        "node_id": execution_contract["node_id"],
        "action_kind": execution_contract["action_kind"],
        "implementation_ref": implementation_ref,
        "generation_profile_ref": profile_ref,
        "executor_implementation_sha256": _file_hash(
            staging / implementation_ref
        ),
        "driver_entrypoint_ref": entrypoint_ref,
        "driver_entrypoint_sha256": _file_hash(staging / entrypoint_ref),
        "result_schema_ref": result_schema_ref,
        "result_schema_sha256": _file_hash(schema_path),
        "epoch_domain_contract": deepcopy(dict(epoch_domains)),
        "read_only_probe_commands": probe_commands,
        "authorization_profile": authorization_profile,
        "runtime_internal_write_refs": runtime_internal_write_refs,
        "execution_contract": execution_contract,
        "runtime_input_contract": {
            "command_manifest_required_fields": required_command_fields,
            "authorization_required_fields": required_authorization_fields,
            "predecessor_result_ref": execution_contract[
                "required_predecessor_result_ref"
            ],
            "control_state_ref": runtime_internal_write_refs[0],
            "control_event_ledger_ref": runtime_internal_write_refs[1],
            "idempotency_derivation_fields": [
                "action_id",
                "authorization_id",
                "candidate_tree_sha256",
                "control_plane_registration_result_sha256",
                "driver_entrypoint_sha256",
                "fencing_token",
                "lease_id",
                "requirement_ir_sha256",
            ],
        },
        "persistence_contract": {
            "control_state_ref": runtime_internal_write_refs[0],
            "control_event_ledger_ref": runtime_internal_write_refs[1],
            "transaction_journal_ref": runtime_internal_write_refs[2],
            "lease_ref": runtime_internal_write_refs[3],
            "result_ref": runtime_internal_write_refs[4],
        },
        "failure_codes": [
            "PROGRAM_DRIVER_RUNTIME_VERIFICATION_CONTRACT_INVALID",
            "PROGRAM_DRIVER_RUNTIME_VERIFICATION_RESULT_INVALID",
            "PROJECT_VALIDATION_AUTHORIZATION_INVALID",
            "PROJECT_VALIDATION_AUTHORIZATION_REVOKED",
            "PROGRAM_DRIVER_READ_ONLY_PROBE_FAILED",
            "PROGRAM_DRIVER_READ_ONLY_PROBE_MUTATION",
            "UNBOUND_OR_DRIFTED_PROGRAM_DRIVER_ENTRYPOINT",
            "IDEMPOTENCY_KEY_INVALID",
            "LEASE_CONFLICT",
            "FENCING_TOKEN_REGRESSION",
            "CONTROL_EVENT_LEDGER_INVALID",
            "UNKNOWN_COMMIT_STATE",
        ],
        "contract_sha256": "",
    }
    action_contract["contract_sha256"] = _hash_without_field(
        action_contract, "contract_sha256"
    )
    action_contract_path = staging / action_contract_ref
    _write_json(action_contract_path, action_contract)

    dag_path = staging / "ENGINEERING_PROJECT_DAG.json"
    dag = json.loads(dag_path.read_text(encoding="utf-8"))
    node = next(
        (
            item
            for item in dag.get("nodes", [])
            if isinstance(item, dict)
            and item.get("node_id") == "PROGRAM_DRIVER_RUNTIME_VERIFIED"
        ),
        None,
    )
    if not isinstance(node, dict):
        raise ValueError("Program Driver verification DAG node is missing")
    node.update(
        {
            "executor_action_kind": "PROJECT_VALIDATION",
            "action_id": execution_contract["action_id"],
            "action_contract_ref": action_contract_ref,
            "action_contract_sha256": _file_hash(action_contract_path),
            "executor_implementation_ref": implementation_ref,
            "executor_implementation_sha256": _file_hash(
                staging / implementation_ref
            ),
            "driver_entrypoint_ref": entrypoint_ref,
            "driver_entrypoint_sha256": _file_hash(staging / entrypoint_ref),
            "result_schema_ref": result_schema_ref,
            "result_schema_sha256": _file_hash(schema_path),
            "read_only_probe_commands": probe_commands,
            "transaction_protocol": "JOURNALED_ONE_SHOT_STATE_CAS_V1",
            "runtime_internal_write_refs": runtime_internal_write_refs,
        }
    )
    _write_json(dag_path, dag)

    manifest["program_driver_runtime_verification"] = {
        "action_contract_ref": action_contract_ref,
        "action_contract_sha256": _file_hash(action_contract_path),
        "executor_implementation_ref": implementation_ref,
        "executor_implementation_sha256": _file_hash(
            staging / implementation_ref
        ),
        "driver_entrypoint_ref": entrypoint_ref,
        "driver_entrypoint_sha256": _file_hash(staging / entrypoint_ref),
        "result_schema_ref": result_schema_ref,
        "result_schema_sha256": _file_hash(schema_path),
        "read_only_probe_commands": probe_commands,
        "runtime_status": "NOT_EXECUTED",
        "driver_started": False,
        "workpack_started": False,
    }
    _write_json(staging / "THREE_PROJECT_PROGRAM_MANIFEST.json", manifest)

    driver_path = staging / "PROGRAM_DRIVER_CONTRACT.json"
    driver = json.loads(driver_path.read_text(encoding="utf-8"))
    driver["driver_entrypoint_ref"] = entrypoint_ref
    driver["driver_entrypoint_sha256"] = _file_hash(staging / entrypoint_ref)
    driver["runtime_verification_ref"] = action_contract_ref
    driver["runtime_verification_sha256"] = _file_hash(action_contract_path)
    driver.setdefault("project_validation_actions", {})[
        "PROGRAM_DRIVER_RUNTIME_VERIFIED"
    ] = {
        "action_contract_ref": action_contract_ref,
        "executor_implementation_ref": implementation_ref,
        "required_execution_mode": "PROJECT_VALIDATION",
        "read_only_probe_commands": probe_commands,
        "automatic_successor_advance_allowed": False,
        "driver_start_allowed": False,
        "workpack_start_allowed": False,
    }
    _write_json(driver_path, driver)

    policy_path = staging / "AUTHORIZATION_POLICY.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    token_fields = list(policy.get("required_token_fields") or [])
    for field in required_authorization_fields:
        if field not in token_fields:
            token_fields.append(field)
    policy["required_token_fields"] = token_fields
    policy.setdefault("profile_authorization_schemas", {}).setdefault(
        assurance_profile, {}
    )["PROJECT_VALIDATION_AUTHORIZATION"] = deepcopy(authorization_profile)
    policy.setdefault("validation_rules", {}).update(
        {
            "project_validation_predecessor_hash_required": True,
            "program_driver_entrypoint_hash_required": True,
            "project_validation_state_cas_required": True,
            "project_validation_event_tip_required": True,
            "project_validation_one_shot_idempotency_fencing_required": True,
            "project_validation_profile_schema_exact_match_required": True,
            "project_validation_read_only_probe_set_required": True,
            "project_validation_runtime_internal_write_containment_required": True,
        }
    )
    _write_json(policy_path, policy)

    negative_path = staging / "validation/NEGATIVE_CASES.json"
    negative = json.loads(negative_path.read_text(encoding="utf-8"))
    cases = list(negative.get("cases") or [])
    existing = {
        str(case.get("case_id"))
        for case in cases
        if isinstance(case, Mapping)
    }
    verification_cases = [
        {
            "case_id": "NEG-V29-E43-DRIVER-VERIFY-AUTHORITY-SCOPE",
            "atom_ids": ["ATOM-V29-P0-04", "ATOM-V29-P0-05"],
            "description": (
                "A local Project Validation authorization with a wrong issuer, "
                "scope, budget, delegation, or forbidden-action set must fail."
            ),
            "expected_failure": "PROJECT_VALIDATION_AUTHORIZATION_INVALID",
            "fixture_kind": "NON_EXECUTABLE_JSON",
            "input_fixture": {
                "issuer_role": None,
                "scope": {"node_id": "WRONG_NODE"},
                "max_transitions": 2,
                "delegation_allowed": True,
                "forbidden_actions": [],
            },
            "origin": "EPOCH43_PROGRAM_DRIVER_RUNTIME_VERIFICATION_CLOSURE",
        },
        {
            "case_id": "NEG-V29-E43-DRIVER-VERIFY-ENTRYPOINT-HASH",
            "atom_ids": ["ATOM-V29-P0-04", "ATOM-V29-P0-08"],
            "description": (
                "A missing or mismatched portable Program Driver entrypoint Hash "
                "must fail before any transition write."
            ),
            "expected_failure": "UNBOUND_OR_DRIFTED_PROGRAM_DRIVER_ENTRYPOINT",
            "fixture_kind": "NON_EXECUTABLE_JSON",
            "input_fixture": {"driver_entrypoint_sha256": "0" * 64},
            "origin": "EPOCH43_PROGRAM_DRIVER_RUNTIME_VERIFICATION_CLOSURE",
        },
        {
            "case_id": "NEG-V29-E43-DRIVER-VERIFY-READ-ONLY-BOUNDARY",
            "atom_ids": ["ATOM-V29-P0-04", "ATOM-V29-P0-07"],
            "description": (
                "Any pre-verification Driver probe outside status, plan-next, "
                "and validate-transition, or any probe filesystem mutation, must fail."
            ),
            "expected_failure": "PROGRAM_DRIVER_READ_ONLY_PROBE_MUTATION",
            "fixture_kind": "NON_EXECUTABLE_JSON",
            "input_fixture": {
                "read_only_probe_commands": ["advance"],
                "filesystem_mutation": True,
            },
            "origin": "EPOCH43_PROGRAM_DRIVER_RUNTIME_VERIFICATION_CLOSURE",
        },
    ]
    cases.extend(
        case for case in verification_cases
        if profile_ref == "EPOCH38_GENERATION_PROFILE.json"
        and case["case_id"] not in existing
    )
    negative["cases"] = cases
    _write_json(negative_path, negative)

    readme_path = staging / "README.md"
    readme = readme_path.read_text(encoding="utf-8")
    _write_text(
        readme_path,
        f"""{readme}

## Program Driver Runtime Verification

`PROGRAM_DRIVER_RUNTIME_VERIFIED` is bound to the portable read-only entrypoint
`{entrypoint_ref}`, verification action `{implementation_ref}`, exact contract
`{action_contract_ref}`, and result schema `{result_schema_ref}`. Before Driver
start, only `status`, `plan-next`, and `validate-transition` are callable. The
verification action proves those probes leave Candidate and Execution Root bytes
unchanged, then commits one Hash-bound result, event, and state CAS. It does not
start the Driver, execute a Workpack, install anything, or use an external Trust
Anchor, independent Oracle, adversarial route, or optional-security route.
""",
    )


def _write_controlled_workpack_runtime_contract(
    staging: Path,
    context: Mapping[str, str],
    *,
    active_requirement_epoch: int,
    profile_ref: str = "EPOCH38_GENERATION_PROFILE.json",
) -> None:
    """Package the real sibling-Runtime provider for the first Workpack."""

    node_id = "MAIN_EXECUTION_PACKAGE_MATERIALIZED"
    legacy = profile_ref == "EPOCH38_GENERATION_PROFILE.json"
    if legacy and active_requirement_epoch < 45:
        return
    workpack_id = context["first_workpack_id"]
    if legacy and workpack_id != "WP-HARNESS-FOUNDRY-V2-9-CHAT-FACTORY-G0-001":
        raise ValueError("Epoch 45 controlled Runtime Workpack identity drifted")
    provider_ref = "tools/harness_foundry_runtime/workpack_runtime.py"
    entrypoint_ref = "tools/workpack_runtime.py"
    contract_ref = "validation/CONTROLLED_WORKPACK_RUNTIME_CONTRACT.json"
    command_manifest_ref = f"commands/{workpack_id}.commands.json"
    capsule_ref = f"capsules/{workpack_id}.capsule.json"
    allowed_write_refs = [
        (
            "harness-resource://execution/evidence/engineering_dag/"
            "MAIN_EXECUTION_PACKAGE_MATERIALIZED"
        ),
        (
            "harness-resource://execution/project_start_packages/"
            "main_build/repository"
        ),
    ]
    resources = Path(__file__).resolve().parent / "resources"
    entrypoint_source = resources / "workpack_runtime.py"
    provider_path = staging / provider_ref
    entrypoint_path = staging / entrypoint_ref
    if not provider_path.is_file():
        raise ValueError("controlled Workpack provider dependency is missing")
    if not entrypoint_source.is_file():
        raise ValueError("controlled Workpack runtime entrypoint is missing")
    _write_text(
        entrypoint_path, entrypoint_source.read_text(encoding="utf-8")
    )
    entrypoint_path.chmod(0o755)

    required_authorization_fields = [
        "schema_version",
        "authorization_id",
        "authorization_class",
        "status",
        "one_shot",
        "program_id",
        "node_id",
        "workpack_id",
        "candidate_tree_sha256",
        "hydration_sha256",
        "resolved_command_sha256s",
        "provider_implementation_sha256",
        "codex_executable_sha256",
        "codex_cli_help_sha256",
        "allowed_write_roots",
        "max_transitions",
        "max_loop_rounds",
        "real_target_install_allowed",
        "validation_scope",
        "network_allowed",
        "target_install_allowed",
        "delegation_allowed",
        "not_before",
        "expires_at",
    ]
    authorization_profile = {
        "schema_id": (
            "EPOCH45_LOCAL_PROJECT_BOOTSTRAP_A3_V1" if legacy
            else "LOCAL_PROJECT_MATERIALIZATION_A3_V1"
        ),
        "assurance_profile": "SELF_USE_LOCAL_TRUSTED_OPERATOR",
        "authorization_class": "A3_PROGRAM_BOUNDED",
        "issuer_role": "LOCAL_TRUSTED_OPERATOR",
        "one_shot": True,
        "max_transitions": 1,
        "max_loop_rounds": 1,
        "delegation_allowed": False,
        "external_cryptographic_signature_required": False,
        "signature_policy": "NOT_APPLICABLE_SELF_USE_LOCAL_TRUSTED_OPERATOR",
        "signature_value": None,
        "required_fields": required_authorization_fields,
        "scope_contract": {
            "program_id_binding": "EXACT_ACTIVE_PROGRAM_ID",
            "node_id": node_id,
            "workpack_id": workpack_id,
            "execution_mode": "WORKPACK_EXECUTION",
            "validation_scope": "STRUCTURAL_PACKAGE_CONTRACT_ONLY",
            "allowed_write_refs": allowed_write_refs,
            "network_allowed": False,
            "real_target_install_allowed": False,
            "automatic_successor_advance_allowed": False,
        },
    }
    contract = {
        "schema_version": "1.0",
        "contract_id": (
            "EPOCH45_CONTROLLED_WORKPACK_RUNTIME_V1" if legacy
            else "LOCAL_CONTROLLED_WORKPACK_RUNTIME_V1"
        ),
        "active_requirement_epoch": active_requirement_epoch,
        "assurance_profile": "SELF_USE_LOCAL_TRUSTED_OPERATOR",
        "node_id": node_id,
        "workpack_id": workpack_id,
        "provider_kind": "CODEX_WORKPACK_PROVIDER",
        "provider_implementation_ref": provider_ref,
        "provider_implementation_sha256": _file_hash(provider_path),
        "runtime_entrypoint_ref": entrypoint_ref,
        "runtime_entrypoint_sha256": _file_hash(entrypoint_path),
        "candidate_input_refs": [
            "ENGINEERING_PROJECT_DAG.json",
            "WORKPACK_INDEX.json",
            command_manifest_ref,
            capsule_ref,
            "validation/PORTABLE_FILE_MANIFEST.json",
        ],
        "command_overlay_contract": {
            "required": True,
            "command_ids": [
                "ROOT-CODEX-CODING",
                "ROOT-MATERIALIZATION-VERIFY",
            ],
            "absolute_executable_and_sha256_required": True,
            "exact_argv_required": True,
            "shell_reparse_allowed": False,
            "codex_cli_schema_probe": ["codex", "exec", "--help"],
            "codex_required_flags": [
                "--sandbox",
                "--skip-git-repo-check",
            ],
            "codex_required_sandbox": "workspace-write",
            "forbidden_flags": [
                "--dangerously-bypass-approvals-and-sandbox",
                "--sandbox=danger-full-access",
            ],
        },
        "hydration_contract": {
            "side_effect_free": True,
            "candidate_must_remain_read_only": True,
            "candidate_planned_state_required": True,
            "current_control_state_and_event_tip_required": True,
            "predecessor_result_hash_required": True,
            "status_after_hydration": "READY_FOR_A3_PREPARATION",
            "execution_authorized_after_hydration": False,
        },
        "authorization_profile": authorization_profile,
        "execution_contract": {
            "max_transitions": 1,
            "max_loop_rounds": 1,
            "validation_scope": "STRUCTURAL_PACKAGE_CONTRACT_ONLY",
            "fresh_hydration_inputs_required_before_writes": True,
            "allowed_write_refs": allowed_write_refs,
            "network_allowed": False,
            "real_target_install_allowed": False,
            "candidate_write_allowed": False,
            "automatic_postflight_required": True,
            "independent_structural_review_required": True,
            "automatic_successor_advance_allowed": False,
            "result_ref": (
                "harness-resource://execution/evidence/engineering_dag/"
                "MAIN_EXECUTION_PACKAGE_MATERIALIZED/result.json"
            ),
        },
        "factory_execution_allowed": False,
        "sibling_controlled_runtime_required": True,
        "test_adapter_or_schema_only_closure_allowed": False,
        "external_runtime_state_reuse_allowed": False,
        "contract_sha256": "",
    }
    if legacy:
        contract["profile_origin_requirement_epoch"] = 38
    contract["contract_sha256"] = _hash_without_field(
        contract, "contract_sha256"
    )
    contract_path = staging / contract_ref
    _write_json(contract_path, contract)

    dag_path = staging / "ENGINEERING_PROJECT_DAG.json"
    dag = json.loads(dag_path.read_text(encoding="utf-8"))
    node = next(
        (
            item
            for item in dag.get("nodes", [])
            if isinstance(item, dict) and item.get("node_id") == node_id
        ),
        None,
    )
    if not isinstance(node, dict):
        raise ValueError("Main execution package DAG node is missing")
    node.update(
        {
            "runtime_provider_kind": "CODEX_WORKPACK_PROVIDER",
            "runtime_provider_ref": provider_ref,
            "runtime_provider_sha256": _file_hash(provider_path),
            "runtime_entrypoint_ref": entrypoint_ref,
            "runtime_entrypoint_sha256": _file_hash(entrypoint_path),
            "runtime_contract_ref": contract_ref,
            "runtime_contract_sha256": _file_hash(contract_path),
            "active_requirement_epoch": active_requirement_epoch,
            "runtime_hydration_required": True,
            "command_overlay_required": True,
            "max_transitions": 1,
            "max_loop_rounds": 1,
            "real_target_install_allowed": False,
            "automatic_postflight_required": True,
            "independent_structural_review_required": True,
            "automatic_successor_advance_allowed": False,
        }
    )
    _write_json(dag_path, dag)

    manifest_path = staging / "THREE_PROJECT_PROGRAM_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["main_execution_package_runtime"] = {
        "node_id": node_id,
        "workpack_id": workpack_id,
        "runtime_provider_ref": provider_ref,
        "runtime_provider_sha256": _file_hash(provider_path),
        "runtime_entrypoint_ref": entrypoint_ref,
        "runtime_entrypoint_sha256": _file_hash(entrypoint_path),
        "runtime_contract_ref": contract_ref,
        "runtime_contract_sha256": _file_hash(contract_path),
        "active_requirement_epoch": active_requirement_epoch,
        "runtime_status": "PLANNED_NOT_HYDRATED",
        "execution_authorized": False,
        "workpack_executed": False,
    }
    _write_json(manifest_path, manifest)

    driver_path = staging / "PROGRAM_DRIVER_CONTRACT.json"
    driver = json.loads(driver_path.read_text(encoding="utf-8"))
    driver.setdefault("workpack_execution_actions", {})[node_id] = {
        "workpack_id": workpack_id,
        "runtime_provider_ref": provider_ref,
        "runtime_entrypoint_ref": entrypoint_ref,
        "runtime_contract_ref": contract_ref,
        "active_requirement_epoch": active_requirement_epoch,
        "required_execution_mode": "WORKPACK_EXECUTION",
        "required_authorization_class": "A3_PROGRAM_BOUNDED",
        "max_transitions": 1,
        "max_loop_rounds": 1,
        "automatic_successor_advance_allowed": False,
        "factory_execution_allowed": False,
    }
    _write_json(driver_path, driver)

    for relative in ("WORKPACK_INDEX.json", command_manifest_ref, capsule_ref):
        path = staging / relative
        document = json.loads(path.read_text(encoding="utf-8"))
        document.update(
            {
                "runtime_provider_ref": provider_ref,
                "runtime_provider_sha256": _file_hash(provider_path),
                "runtime_entrypoint_ref": entrypoint_ref,
                "runtime_entrypoint_sha256": _file_hash(entrypoint_path),
                "runtime_contract_ref": contract_ref,
                "runtime_contract_sha256": _file_hash(contract_path),
                "active_requirement_epoch": active_requirement_epoch,
                "runtime_hydration_required": True,
                "command_overlay_required": True,
            }
        )
        if relative == "WORKPACK_INDEX.json":
            document["dag_status"] = "PLANNED_RUNTIME_PROVIDER_AVAILABLE"
        _write_json(path, document)

    policy_path = staging / "AUTHORIZATION_POLICY.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    token_fields = list(policy.get("required_token_fields") or [])
    for field in required_authorization_fields:
        if field not in token_fields:
            token_fields.append(field)
    policy["required_token_fields"] = token_fields
    policy.setdefault("profile_authorization_schemas", {}).setdefault(
        "SELF_USE_LOCAL_TRUSTED_OPERATOR", {}
    )["PROJECT_BOOTSTRAP_AUTHORIZATION"] = deepcopy(authorization_profile)
    policy.setdefault("validation_rules", {}).update(
        {
            "workpack_runtime_provider_hash_required": True,
            "workpack_runtime_overlay_hash_required": True,
            "workpack_runtime_cli_schema_hash_required": True,
            "workpack_runtime_candidate_hydration_required": True,
            "workpack_runtime_exact_write_roots_required": True,
            "workpack_runtime_a3_exact_scope_required": True,
            "workpack_runtime_external_state_reuse_forbidden": True,
        }
    )
    _write_json(policy_path, policy)

    negative_path = staging / "validation/NEGATIVE_CASES.json"
    negative = json.loads(negative_path.read_text(encoding="utf-8"))
    cases = list(negative.get("cases") or [])
    existing = {
        str(case.get("case_id"))
        for case in cases
        if isinstance(case, Mapping)
    }
    runtime_cases = [
        {
            "case_id": "NEG-V29-E45-WORKPACK-RUNTIME-CODEX-HASH",
            "atom_ids": ["ATOM-V29-P0-04", "ATOM-V29-P0-08"],
            "description": "Codex executable or CLI schema Hash drift must fail before A3 preparation.",
            "expected_failure": "CODEX_HASH_MISMATCH",
            "fixture_kind": "NON_EXECUTABLE_JSON",
            "input_fixture": {"codex_executable_sha256": "0" * 64},
            "origin": "EPOCH45_CONTROLLED_RUNTIME_WORKPACK_EXECUTABLE_CLOSURE",
        },
        {
            "case_id": "NEG-V29-E45-WORKPACK-RUNTIME-WRITE-ROOT",
            "atom_ids": ["ATOM-V29-P0-04", "ATOM-V29-P0-07"],
            "description": "Any Candidate write or undeclared Runtime write root must fail before execution.",
            "expected_failure": "COMMAND_OVERLAY_WRITE_ROOT_INVALID",
            "fixture_kind": "NON_EXECUTABLE_JSON",
            "input_fixture": {"allowed_write_roots": ["harness-resource://candidate"]},
            "origin": "EPOCH45_CONTROLLED_RUNTIME_WORKPACK_EXECUTABLE_CLOSURE",
        },
        {
            "case_id": "NEG-V29-E45-WORKPACK-RUNTIME-A3-SCOPE",
            "atom_ids": ["ATOM-V29-P0-05", "ATOM-V29-P0-06"],
            "description": "A stale, widened, reusable, or non-Hash-bound A3 must fail before subprocess execution.",
            "expected_failure": "A3_AUTHORIZATION_INVALID",
            "fixture_kind": "NON_EXECUTABLE_JSON",
            "input_fixture": {
                "max_transitions": 2,
                "max_loop_rounds": 2,
                "real_target_install_allowed": True,
            },
            "origin": "EPOCH45_CONTROLLED_RUNTIME_WORKPACK_EXECUTABLE_CLOSURE",
        },
    ]
    cases.extend(case for case in runtime_cases if legacy and case["case_id"] not in existing)
    negative["cases"] = cases
    _write_json(negative_path, negative)

    readme_path = staging / "README.md"
    readme = readme_path.read_text(encoding="utf-8")
    _write_text(
        readme_path,
        f"""{readme}

## Controlled Workpack Runtime Provider

`{node_id}` is bound to `{provider_ref}`, portable entrypoint
`{entrypoint_ref}`, and contract `{contract_ref}`. Hydration validates the
planned Candidate manifests, current control-state/event tip, exact executable
Hashes, Codex `exec` CLI schema, two declared write roots, one transition, one
bounded loop round, no network, and no target install. Hydration does not grant
or consume A3 and does not execute the Workpack. The Factory cannot invoke the
provider; only a separately authorized sibling Execution Runtime may do so.

The entrypoint also exposes `plan --candidate-root . --node-id LAB_BOOTSTRAP`
for read-only inspection of the DAG's ordered Workpacks, commands and native
task bundles. Planning does not hydrate or execute Lab, Linkage or Main, and
does not grant execution authority. It suppresses Python bytecode writes even
when the Candidate directory is physically writable.
""",
    )


def _main_execution_package_validation_result_schema() -> dict[str, Any]:
    required = [
        "schema_version",
        "result_id",
        "program_id",
        "node_id",
        "next_node",
        "status",
        "execution_mode",
        "control_plane_epoch",
        "candidate_tree_sha256",
        "requirement_ir_sha256",
        "materialization_result_sha256",
        "materialized_repository_tree_sha256",
        "observed_repository_tree_sha256",
        "structural_validation",
        "command_manifest_sha256",
        "executor_implementation_sha256",
        "runtime_entrypoint_sha256",
        "action_contract_sha256",
        "result_schema_sha256",
        "authorization_id",
        "authorization_sha256",
        "idempotency_key",
        "lease_id",
        "fencing_token",
        "produced_capabilities",
        "predecessor_repository_read_only",
        "successor_started",
        "started_at",
        "completed_at",
        "result_sha256",
    ]
    properties: dict[str, Any] = {
        field: {"type": "string"} for field in required
    }
    properties.update(
        {
            "schema_version": {"type": "string", "const": "1.0"},
            "node_id": {
                "type": "string",
                "const": "MAIN_EXECUTION_PACKAGE_VALIDATED",
            },
            "next_node": {"type": "string", "const": "MAIN_PROGRAM_REGISTRATION"},
            "status": {"type": "string", "const": "PASS"},
            "execution_mode": {"type": "string", "const": "PROJECT_VALIDATION"},
            "control_plane_epoch": {"type": "integer", "minimum": 0},
            "structural_validation": {"type": "object"},
            "fencing_token": {"type": "integer", "minimum": 1},
            "produced_capabilities": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "uniqueItems": True,
            },
            "predecessor_repository_read_only": {
                "type": "boolean",
                "const": True,
            },
            "successor_started": {"type": "boolean", "const": False},
        }
    )
    for field in (
        "candidate_tree_sha256",
        "requirement_ir_sha256",
        "materialization_result_sha256",
        "materialized_repository_tree_sha256",
        "observed_repository_tree_sha256",
        "command_manifest_sha256",
        "executor_implementation_sha256",
        "runtime_entrypoint_sha256",
        "action_contract_sha256",
        "result_schema_sha256",
        "authorization_sha256",
        "idempotency_key",
        "result_sha256",
    ):
        properties[field]["pattern"] = "^[0-9a-f]{64}$"
    for field in ("started_at", "completed_at"):
        properties[field]["pattern"] = (
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
        )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            "harness-resource://candidate/contracts/"
            "MAIN_EXECUTION_PACKAGE_VALIDATION_RESULT.schema.json"
        ),
        "title": "Main Execution Package Structural Validation Result",
        "description": (
            "One-shot byte-backed structural validation result. It does not "
            "execute repository code or start MAIN_PROGRAM_REGISTRATION."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def _write_main_execution_package_validation_contract(
    staging: Path,
    *,
    active_requirement_epoch: int,
) -> None:
    """Bind MAIN_EXECUTION_PACKAGE_VALIDATED to a real read-only provider."""

    if active_requirement_epoch < 49:
        return
    node_id = "MAIN_EXECUTION_PACKAGE_VALIDATED"
    predecessor_node_id = "MAIN_EXECUTION_PACKAGE_MATERIALIZED"
    implementation_ref = (
        "tools/harness_foundry_runtime/main_execution_package_validation.py"
    )
    entrypoint_ref = "tools/main_execution_package_validation.py"
    action_contract_ref = (
        "validation/MAIN_EXECUTION_PACKAGE_VALIDATION_ACTION_CONTRACT.json"
    )
    result_schema_ref = (
        "contracts/MAIN_EXECUTION_PACKAGE_VALIDATION_RESULT.schema.json"
    )
    repository_ref = (
        "harness-resource://execution/project_start_packages/main_build/repository"
    )
    node_evidence_write_ref = (
        "harness-resource://execution/evidence/engineering_dag/"
        "MAIN_EXECUTION_PACKAGE_VALIDATED"
    )
    entrypoint_source = (
        Path(__file__).resolve().parent
        / "resources"
        / "main_execution_package_validation.py"
    )
    implementation_path = staging / implementation_ref
    if not implementation_path.is_file():
        raise ValueError("Main package validation provider dependency is missing")
    if not entrypoint_source.is_file():
        raise ValueError("Main package validation entrypoint is missing")
    entrypoint_path = staging / entrypoint_ref
    _write_text(entrypoint_path, entrypoint_source.read_text(encoding="utf-8"))
    entrypoint_path.chmod(0o755)
    schema_path = staging / result_schema_ref
    schema = _main_execution_package_validation_result_schema()
    _write_json(schema_path, schema)

    profile = json.loads(
        (staging / "EPOCH38_GENERATION_PROFILE.json").read_text(encoding="utf-8")
    )
    assurance_profile = str(profile.get("assurance_profile") or "")
    if assurance_profile != "SELF_USE_LOCAL_TRUSTED_OPERATOR":
        raise ValueError("Main package validation requires the local self-use profile")
    manifest_path = staging / "THREE_PROJECT_PROGRAM_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    epoch_domains = manifest.get("epoch_domains")
    if not isinstance(epoch_domains, Mapping):
        raise ValueError("Main package validation requires explicit epoch domains")

    runtime_internal_write_refs = [
        (
            "harness-resource://execution/.harness-foundry/control/"
            "PROGRAM_CONTROL_STATE.json"
        ),
        (
            "harness-resource://execution/.harness-foundry/control/"
            "PROGRAM_CONTROL_EVENTS.jsonl"
        ),
        (
            "harness-resource://execution/.harness-foundry/control/transactions/"
            "MAIN_EXECUTION_PACKAGE_VALIDATED.transaction.json"
        ),
        (
            "harness-resource://execution/.harness-foundry/control/leases/"
            "MAIN_EXECUTION_PACKAGE_VALIDATED.lease.json"
        ),
        f"{node_evidence_write_ref}/result.json",
    ]
    required_command_fields = [
        "schema_version",
        "command_id",
        "action_id",
        "node_id",
        "authorization_id",
        "candidate_tree_sha256",
        "requirement_ir_sha256",
        "executor_implementation_ref",
        "executor_implementation_sha256",
        "runtime_entrypoint_ref",
        "runtime_entrypoint_sha256",
        "action_contract_sha256",
        "result_schema_sha256",
        "materialization_result_sha256",
        "materialized_repository_tree_sha256",
        "expected_control_state_sha256",
        "expected_event_tip",
        "node_evidence_write_ref",
        "validation_scope",
        "idempotency_key",
        "lease_id",
        "fencing_token",
    ]
    required_authorization_fields = [
        "schema_version",
        "authorization_id",
        "authorization_class",
        "status",
        "one_shot",
        "program_id",
        "issuer_role",
        "issued_at",
        "node_id",
        "allowed_action_id",
        "scope",
        "command_manifest_hashes",
        "command_manifest_sha256",
        "candidate_tree_sha256",
        "requirement_ir_sha256",
        "executor_implementation_sha256",
        "runtime_entrypoint_sha256",
        "materialization_result_sha256",
        "materialized_repository_tree_sha256",
        "expected_control_state_sha256",
        "expected_event_tip",
        "node_evidence_write_ref",
        "validation_scope",
        "idempotency_key",
        "lease_id",
        "fencing_token",
        "max_transitions",
        "max_loop_rounds",
        "real_target_install_allowed",
        "delegation_allowed",
        "signature_policy",
        "signature",
        "not_before",
        "expires_at",
    ]
    authorization_profile = {
        "schema_id": "EPOCH49_LOCAL_PACKAGE_VALIDATION_AUTHORIZATION_V1",
        "assurance_profile": assurance_profile,
        "authorization_class": "PROJECT_VALIDATION_AUTHORIZATION",
        "issuer_role": "LOCAL_TRUSTED_OPERATOR",
        "max_transitions": 1,
        "max_loop_rounds": 1,
        "delegation_allowed": False,
        "signature_policy": "NOT_APPLICABLE_SELF_USE_LOCAL_TRUSTED_OPERATOR",
        "signature_value": None,
        "external_cryptographic_signature_required": False,
        "required_fields": required_authorization_fields,
        "scope_contract": {
            "program_id_binding": "EXACT_ACTIVE_PROGRAM_ID",
            "node_id": node_id,
            "allowed_action_id": "VALIDATE-MAIN-EXECUTION-PACKAGE-STRUCTURE",
            "execution_mode": "PROJECT_VALIDATION",
            "validation_scope": "STRUCTURAL_PACKAGE_CONTRACT_ONLY",
            "predecessor_repository_ref": repository_ref,
            "predecessor_repository_write_allowed": False,
            "node_evidence_write_ref": node_evidence_write_ref,
            "runtime_internal_write_refs": runtime_internal_write_refs,
            "automatic_successor_advance_allowed": False,
        },
    }
    execution_contract = {
        "schema_version": "1.0",
        "contract_id": "MAIN_EXECUTION_PACKAGE_VALIDATION_CLOSURE_V1",
        "action_id": "VALIDATE-MAIN-EXECUTION-PACKAGE-STRUCTURE",
        "node_id": node_id,
        "action_kind": "PROJECT_VALIDATION",
        "successor_node_id": "MAIN_PROGRAM_REGISTRATION",
        "required_predecessor_node_id": predecessor_node_id,
        "required_predecessor_result_ref": (
            "harness-resource://execution/evidence/engineering_dag/"
            "MAIN_EXECUTION_PACKAGE_MATERIALIZED/result.json"
        ),
        "predecessor_repository_ref": repository_ref,
        "predecessor_repository_write_allowed": False,
        "node_evidence_write_ref": node_evidence_write_ref,
        "validation_scope": "STRUCTURAL_PACKAGE_CONTRACT_ONLY",
        "produced_capabilities": ["MAIN_EXECUTION_PACKAGE_VALIDATED_PASS"],
        "required_result_fields": schema["required"],
        "max_transitions": 1,
        "max_loop_rounds": 1,
        "real_target_install_allowed": False,
        "automatic_successor_advance_allowed": False,
        "transaction_protocol": "JOURNALED_ONE_SHOT_STATE_CAS_V1",
        "unknown_commit_state_policy": "FAIL_CLOSED_NO_REPLAY",
    }
    action_contract = {
        "schema_version": "1.0",
        "contract_id": execution_contract["contract_id"],
        "active_requirement_epoch": active_requirement_epoch,
        "assurance_profile": assurance_profile,
        "action_id": execution_contract["action_id"],
        "node_id": node_id,
        "action_kind": execution_contract["action_kind"],
        "implementation_ref": implementation_ref,
        "executor_implementation_sha256": _file_hash(implementation_path),
        "runtime_entrypoint_ref": entrypoint_ref,
        "runtime_entrypoint_sha256": _file_hash(entrypoint_path),
        "result_schema_ref": result_schema_ref,
        "result_schema_sha256": _file_hash(schema_path),
        "epoch_domain_contract": deepcopy(dict(epoch_domains)),
        "validation_scope": "STRUCTURAL_PACKAGE_CONTRACT_ONLY",
        "predecessor_repository_write_allowed": False,
        "automatic_successor_advance_allowed": False,
        "authorization_profile": authorization_profile,
        "runtime_input_contract": {
            "command_manifest_required_fields": required_command_fields,
            "authorization_required_fields": required_authorization_fields,
            "predecessor_result_ref": execution_contract[
                "required_predecessor_result_ref"
            ],
            "predecessor_repository_ref": repository_ref,
            "control_state_ref": runtime_internal_write_refs[0],
            "control_event_ledger_ref": runtime_internal_write_refs[1],
            "idempotency_derivation_fields": [
                "action_id",
                "authorization_id",
                "candidate_tree_sha256",
                "fencing_token",
                "lease_id",
                "materialization_result_sha256",
                "materialized_repository_tree_sha256",
                "requirement_ir_sha256",
            ],
        },
        "persistence_contract": {
            "control_state_ref": runtime_internal_write_refs[0],
            "control_event_ledger_ref": runtime_internal_write_refs[1],
            "transaction_journal_ref": runtime_internal_write_refs[2],
            "lease_ref": runtime_internal_write_refs[3],
            "result_ref": runtime_internal_write_refs[4],
        },
        "execution_contract": execution_contract,
        "failure_codes": [
            "MAIN_EXECUTION_PACKAGE_VALIDATION_CONTRACT_INVALID",
            "MAIN_EXECUTION_PACKAGE_MATERIALIZATION_RESULT_INVALID",
            "MATERIALIZED_REPOSITORY_STRUCTURAL_VALIDATION_FAILED",
            "PREDECESSOR_REPOSITORY_MUTATED",
            "PROJECT_VALIDATION_AUTHORIZATION_INVALID",
            "PROJECT_VALIDATION_AUTHORIZATION_REVOKED",
            "IDEMPOTENCY_KEY_INVALID",
            "FENCING_TOKEN_REGRESSION",
            "CONTROL_EVENT_LEDGER_INVALID",
            "UNKNOWN_COMMIT_STATE",
        ],
        "contract_sha256": "",
    }
    action_contract["contract_sha256"] = _hash_without_field(
        action_contract, "contract_sha256"
    )
    action_contract_path = staging / action_contract_ref
    _write_json(action_contract_path, action_contract)

    dag_path = staging / "ENGINEERING_PROJECT_DAG.json"
    dag = json.loads(dag_path.read_text(encoding="utf-8"))
    node = next(
        (
            item
            for item in dag.get("nodes", [])
            if isinstance(item, dict) and item.get("node_id") == node_id
        ),
        None,
    )
    if not isinstance(node, dict):
        raise ValueError("Main package validation DAG node is missing")
    node.update(
        {
            "executor_action_kind": "PROJECT_VALIDATION",
            "action_id": execution_contract["action_id"],
            "action_contract_ref": action_contract_ref,
            "action_contract_sha256": _file_hash(action_contract_path),
            "executor_implementation_ref": implementation_ref,
            "executor_implementation_sha256": _file_hash(implementation_path),
            "runtime_entrypoint_ref": entrypoint_ref,
            "runtime_entrypoint_sha256": _file_hash(entrypoint_path),
            "result_schema_ref": result_schema_ref,
            "result_schema_sha256": _file_hash(schema_path),
            "validation_scope": "STRUCTURAL_PACKAGE_CONTRACT_ONLY",
            "predecessor_repository_ref": repository_ref,
            "predecessor_repository_write_allowed": False,
            "runtime_internal_write_refs": runtime_internal_write_refs,
            "max_transitions": 1,
            "max_loop_rounds": 1,
            "automatic_successor_advance_allowed": False,
            "active_requirement_epoch": active_requirement_epoch,
        }
    )
    _write_json(dag_path, dag)

    manifest["main_execution_package_validation"] = {
        "node_id": node_id,
        "action_contract_ref": action_contract_ref,
        "action_contract_sha256": _file_hash(action_contract_path),
        "executor_implementation_ref": implementation_ref,
        "executor_implementation_sha256": _file_hash(implementation_path),
        "runtime_entrypoint_ref": entrypoint_ref,
        "runtime_entrypoint_sha256": _file_hash(entrypoint_path),
        "result_schema_ref": result_schema_ref,
        "result_schema_sha256": _file_hash(schema_path),
        "predecessor_repository_ref": repository_ref,
        "predecessor_repository_write_allowed": False,
        "node_evidence_write_ref": node_evidence_write_ref,
        "runtime_status": "NOT_EXECUTED",
        "successor_started": False,
        "active_requirement_epoch": active_requirement_epoch,
    }
    _write_json(manifest_path, manifest)

    driver_path = staging / "PROGRAM_DRIVER_CONTRACT.json"
    driver = json.loads(driver_path.read_text(encoding="utf-8"))
    driver.setdefault("project_validation_actions", {})[node_id] = {
        "action_contract_ref": action_contract_ref,
        "executor_implementation_ref": implementation_ref,
        "runtime_entrypoint_ref": entrypoint_ref,
        "required_execution_mode": "PROJECT_VALIDATION",
        "validation_scope": "STRUCTURAL_PACKAGE_CONTRACT_ONLY",
        "predecessor_repository_write_allowed": False,
        "node_evidence_write_ref": node_evidence_write_ref,
        "automatic_successor_advance_allowed": False,
    }
    _write_json(driver_path, driver)

    policy_path = staging / "AUTHORIZATION_POLICY.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    token_fields = list(policy.get("required_token_fields") or [])
    for field in required_authorization_fields:
        if field not in token_fields:
            token_fields.append(field)
    policy["required_token_fields"] = token_fields
    policy.setdefault("profile_authorization_schemas", {}).setdefault(
        assurance_profile, {}
    )["MAIN_EXECUTION_PACKAGE_VALIDATION_AUTHORIZATION"] = deepcopy(
        authorization_profile
    )
    policy.setdefault("validation_rules", {}).update(
        {
            "main_package_validation_predecessor_result_hash_required": True,
            "main_package_validation_repository_tree_hash_required": True,
            "main_package_validation_predecessor_repository_read_only": True,
            "main_package_validation_node_evidence_only_command_write": True,
            "main_package_validation_one_shot_state_cas_required": True,
            "main_package_validation_no_successor_auto_advance": True,
            "main_package_validation_self_report_only_forbidden": True,
        }
    )
    _write_json(policy_path, policy)

    negative_path = staging / "validation/NEGATIVE_CASES.json"
    negative = json.loads(negative_path.read_text(encoding="utf-8"))
    cases = list(negative.get("cases") or [])
    existing = {
        str(case.get("case_id"))
        for case in cases
        if isinstance(case, Mapping)
    }
    new_cases = [
        {
            "case_id": "NEG-V29-E49-MAIN-PACKAGE-VALIDATION-REPOSITORY-DRIFT",
            "atom_ids": ["ATOM-V29-P0-04", "ATOM-V29-P0-08"],
            "description": "Repository tree drift from the predecessor result must fail before promotion.",
            "expected_failure": "MATERIALIZED_REPOSITORY_STRUCTURAL_VALIDATION_FAILED",
            "fixture_kind": "NON_EXECUTABLE_JSON",
            "input_fixture": {"materialized_repository_tree_sha256": "0" * 64},
            "origin": "EPOCH49_MAIN_EXECUTION_PACKAGE_VALIDATION_CLOSURE",
        },
        {
            "case_id": "NEG-V29-E49-MAIN-PACKAGE-VALIDATION-WRITE-ROOT",
            "atom_ids": ["ATOM-V29-P0-04", "ATOM-V29-P0-07"],
            "description": "Candidate or predecessor-repository write authority must fail.",
            "expected_failure": "PROJECT_VALIDATION_AUTHORIZATION_INVALID",
            "fixture_kind": "NON_EXECUTABLE_JSON",
            "input_fixture": {
                "predecessor_repository_write_allowed": True,
                "node_evidence_write_ref": repository_ref,
            },
            "origin": "EPOCH49_MAIN_EXECUTION_PACKAGE_VALIDATION_CLOSURE",
        },
        {
            "case_id": "NEG-V29-E49-MAIN-PACKAGE-VALIDATION-SELF-REPORT",
            "atom_ids": ["ATOM-V29-P0-08"],
            "description": "A predecessor PASS self-report without matching repository bytes must fail.",
            "expected_failure": "MATERIALIZED_REPOSITORY_STRUCTURAL_VALIDATION_FAILED",
            "fixture_kind": "NON_EXECUTABLE_JSON",
            "input_fixture": {
                "status": "PASS",
                "actual_repository_bytes_verified": False,
            },
            "origin": "EPOCH49_MAIN_EXECUTION_PACKAGE_VALIDATION_CLOSURE",
        },
    ]
    cases.extend(case for case in new_cases if case["case_id"] not in existing)
    negative["cases"] = cases
    _write_json(negative_path, negative)

    readme_path = staging / "README.md"
    readme = readme_path.read_text(encoding="utf-8")
    _write_text(
        readme_path,
        f"""{readme}

## Main Execution Package Structural Validation

`{node_id}` is bound to `{implementation_ref}`, portable entrypoint
`{entrypoint_ref}`, action contract `{action_contract_ref}`, and result schema
`{result_schema_ref}`. It compares the actual materialized repository bytes to
the predecessor result, writes only its node evidence plus Runtime-internal
transaction state, and promotes the control state to `MAIN_PROGRAM_REGISTRATION`
with one event and one CAS. It never executes repository code, writes the
predecessor repository, starts the successor, installs anything, or runs an
adversarial or optional-security route.
""",
    )


def _human_review_closure_requirements(
    frozen_ir: Mapping[str, Any],
) -> list[tuple[str, Mapping[str, Any]]]:
    target = frozen_ir.get("target")
    if not isinstance(target, Mapping):
        return []
    return sorted(
        (
            str(key),
            value,
        )
        for key, value in target.items()
        if isinstance(value, Mapping)
        and (
            (
                str(key).startswith("human_review_")
                and str(key).endswith("_closure")
            )
            or value.get("closure_receipt_required") is True
        )
    )


def _closure_finding_ids(closure: Mapping[str, Any]) -> list[str]:
    finding_ids = closure.get("finding_ids")
    if isinstance(finding_ids, list):
        return [str(value) for value in finding_ids]
    finding_id = closure.get("finding_id")
    return [str(finding_id)] if finding_id else []


def _closure_evidence_refs(
    staging: Path,
    frozen_ir: Mapping[str, Any],
) -> list[str]:
    self_referential_or_late_bound = {
        "validation/HUMAN_REVIEW_CLOSURE_RECEIPT.json",
        "validation/PORTABLE_FILE_MANIFEST.json",
        "validation/START_PACKAGE_VALIDATION_REPORT.json",
    }
    target = frozen_ir.get("target")
    declared = (
        list(target.get("environment_contract_refs") or [])
        if isinstance(target, Mapping)
        else []
    )
    candidates = [
        "ENGINEERING_PROJECT_DAG.json",
        "validation/DAG_PATH_CONTAINMENT_MATRIX.json",
        "FACTORY_IMPLEMENTATION_MANIFEST.json",
        "canonical_sources/SOURCE_MANIFEST.json",
        CORRECTION_COVERAGE_REF,
        "V2_9_CONTROL_KERNEL_MANIFEST.json",
        "DECISION_POLICY.json",
        "ASSURANCE_PROFILE.json",
        "CONTROL_PLANE_PROGRAM_GRAPH.json",
        "TRANSITION_CONTRACTS.json",
        "PROFILE_READ_VALIDATION_ADAPTER_BINDING.json",
        "CONTROL_EVENT_STORE_ACTIVATION_CONTRACT.json",
        "contracts/v2_9/TRANSITION_RESULT.schema.json",
        "contracts/v2_9/ADAPTER_BINDING.schema.json",
        "contracts/v2_9/CONTROL_EVENT_STORE_ACTIVATION.schema.json",
        "tools/harness_foundry_runtime/control_kernel.py",
        "tools/harness_foundry_runtime/requirement_completion.py",
        "tools/harness_foundry_runtime/store.py",
        EPOCH2_MANIFEST_REF,
        EPOCH2_COVERAGE_REF,
        "SEMANTIC_IMPLEMENTATION_AUTHORIZATION_IDENTITY_CONTRACT.json",
        "GENERIC_RECOVERY_DECISION_PROTOCOL.json",
        "COMPLEXITY_GOVERNOR.json",
        "PRODUCT_SAFETY_RELEASE_CLOSURE_GRAPH.json",
        "EVIDENCE_LIFECYCLE_AND_PROJECTION_CONTRACT.json",
        "EVENT_STORE_AUTHORITY_ADAPTER_CONTRACT.json",
        "AUTHORITY_TRUST_ROOT.json",
        "contracts/v2_9_release_closure/IDENTITY_DERIVATION_INPUT.schema.json",
        "contracts/v2_9_release_closure/IDENTITY_BUNDLE.schema.json",
        "contracts/v2_9_release_closure/MACHINE_GRANT_BINDING.schema.json",
        "contracts/v2_9_release_closure/RECOVERY_DECISION.schema.json",
        "contracts/v2_9_release_closure/COMPLEXITY_DECISION.schema.json",
        "contracts/v2_9_release_closure/CLOSURE_RECEIPT.schema.json",
        "contracts/v2_9_release_closure/COMPATIBILITY_LINKAGE_RECEIPT.schema.json",
        "contracts/v2_9_release_closure/TRUSTED_RELEASE_CONTEXT.schema.json",
        "contracts/v2_9_release_closure/FINAL_RELEASE_DECISION.schema.json",
        "contracts/v2_9_release_closure/EVIDENCE_INDEX_ENTRY.schema.json",
        "contracts/v2_9_release_closure/EVENT_STORE_AUTHORITY_ADAPTER_BINDING.schema.json",
        "contracts/v2_9_release_closure/SOURCE_AUTHORITY_POLICY_LOCK.schema.json",
        VALIDATION_REPORT_RECEIPT_SCHEMA_REF,
        VALIDATION_REPORT_RECEIPT_REF,
        FACTORY_REGRESSION_EXECUTION_RECEIPT_REF,
        "tools/harness_foundry_runtime/authority_adapter.py",
        "tools/harness_foundry_runtime/identity_derivation.py",
        "tools/harness_foundry_runtime/recovery_decision.py",
        "tools/harness_foundry_runtime/complexity_governor.py",
        "tools/harness_foundry_runtime/closure_lanes.py",
        "tools/harness_foundry_runtime/evidence_projection.py",
        "tools/harness_foundry_runtime/models.py",
        "tools/harness_foundry_runtime/constants.py",
        "tools/self_check.py",
        "tools/setup_runtime.py",
        "validation/RUNTIME_BINDING_CONTRACT.json",
        "validation/SHARED_CONTROL_BASELINE_ACTION_CONTRACT.json",
        "contracts/SHARED_CONTROL_BASELINE_RESULT.schema.json",
        "tools/shared_control_baseline.py",
        *[str(value).split("#", 1)[0] for value in declared],
    ]
    refs: list[str] = []
    for relative in candidates:
        if (
            relative
            and relative not in refs
            and relative not in self_referential_or_late_bound
            and not Path(relative).is_absolute()
            and ".." not in Path(relative).parts
            and (staging / relative).is_file()
        ):
            refs.append(relative)
    return refs


def _write_human_review_closure_receipt(
    staging: Path,
    context: Mapping[str, str],
) -> None:
    frozen_path = staging / "canonical_sources/FROZEN_REQUIREMENT_IR.json"
    frozen_ir = json.loads(frozen_path.read_text(encoding="utf-8"))
    package_identity = json.loads(
        (staging / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8")
    )
    evidence_refs = _closure_evidence_refs(staging, frozen_ir)
    evidence_sha256 = {
        relative: _file_hash(staging / relative) for relative in evidence_refs
    }
    entries = []
    for requirement_key, closure in _human_review_closure_requirements(frozen_ir):
        successor = closure.get("successor_binding")
        successor_version = (
            successor.get("candidate_version")
            if isinstance(successor, Mapping)
            else None
        )
        active_epochs = closure.get("active_epochs")
        closure_epoch = (
            active_epochs.get("requirement_epoch")
            if isinstance(active_epochs, Mapping)
            else None
        )
        entries.append(
            {
                "requirement_key": requirement_key,
                "finding_ids": _closure_finding_ids(closure),
                "superseded_candidate": closure.get("superseded_candidate"),
                "replacement_candidate": closure.get("replacement_candidate"),
                "replacement_candidate_version": successor_version,
                "closure_requirement_epoch": closure_epoch,
                "current_package_id": package_identity.get("package_id"),
                "current_package_candidate_version": package_identity.get(
                    "candidate_version"
                ),
                "current_package_requirement_epoch": package_identity.get(
                    "requirement_epoch"
                ),
                "required_closures": list(closure.get("required_closures") or []),
                "required_closures_sha256": _json_hash(
                    list(closure.get("required_closures") or [])
                ),
                "closure_requirement_kind": closure.get(
                    "closure_requirement_kind", "HUMAN_REVIEW_REMEDIATION"
                ),
                "requirement_sha256": _json_hash(closure),
                "evidence_refs": evidence_refs,
                "evidence_sha256": evidence_sha256,
                "status": "PASS",
            }
        )
    target = frozen_ir.get("target")
    epoch38_local_profile = bool(
        isinstance(target, Mapping)
        and target.get("requirement_epoch") == 38
        and target.get("architecture_epoch") == 4
        and target.get("control_plane_epoch") == 4
        and target.get("assurance_profile_id")
        == "SELF_USE_LOCAL_TRUSTED_OPERATOR"
        and target.get("operating_assurance_profile")
        == "SELF_USE_LOCAL_TRUSTED_OPERATOR"
    )
    if epoch38_local_profile and entries:
        raise ValueError(
            "Epoch 38 local profile cannot claim historical Human Review closures"
        )
    _write_json(
        staging / "validation/HUMAN_REVIEW_CLOSURE_RECEIPT.json",
        {
            "schema_version": "1.0",
            "receipt_id": "HUMAN_REVIEW_CLOSURE_RECEIPT",
            "closure_scope": "CANDIDATE_STATIC_CONTRACT",
            "lifecycle_status_source": (
                "THIS_RECEIPT_NOT_IMMUTABLE_REQUIREMENT_DECLARATION"
            ),
            "source_requirement_ir_sha256": context["ir_hash"],
            "portable_requirement_ir_sha256": _file_json_hash(frozen_path),
            "closure_count": len(entries),
            "closures": entries,
            "status": (
                "NOT_APPLICABLE_NO_CLOSURES"
                if epoch38_local_profile
                else "PASS"
            ),
            **(
                {
                    "closure_claimed": False,
                    "human_review_approved": False,
                }
                if epoch38_local_profile
                else {}
            ),
            "runtime_claims_verified": False,
            "workpack_execution_authorized": False,
            "program_driver_started": False,
        },
    )


def _write_portable_file_manifest(staging: Path) -> None:
    excluded = {
        "validation/PORTABLE_FILE_MANIFEST.json",
        "validation/START_PACKAGE_VALIDATION_REPORT.json",
    }
    files = {
        path.relative_to(staging).as_posix(): _file_hash(path)
        for path in sorted(staging.rglob("*"))
        if path.is_file() and path.relative_to(staging).as_posix() not in excluded
    }
    _write_json(
        staging / "validation/PORTABLE_FILE_MANIFEST.json",
        {
            "schema_version": "1.0",
            "hash_algorithm": "sha256",
            "excluded_files": sorted(excluded),
            "file_count": len(files),
            "files": files,
        },
    )


def _source_manifest(ir: Mapping[str, Any], context: Mapping[str, str]) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    for index, raw in enumerate(ir["sources"], 1):
        item = dict(raw) if isinstance(raw, Mapping) else {"path_or_uri": str(raw)}
        source_id = str(item.get("source_id") or f"SRC-{index:03d}")
        path_or_uri = str(item.get("path_or_uri") or item.get("path") or f"chat://{context['program_id']}/source/{index}")
        sha = str(item.get("sha256") or _stable_hash({"path_or_uri": path_or_uri, "item": item}))
        declared_authority = str(item.get("authority_level") or "HUMAN_APPROVED")
        authority_aliases = {
            "NORMATIVE_USER_SELECTED": "HUMAN_APPROVED",
            "HUMAN_PROVIDED_SUPPLEMENT": "HUMAN_PROVIDED",
            "HUMAN_AUTHORIZED_AUTHORING_PROPOSAL": "HUMAN_APPROVED",
            "HUMAN_VIA_CODEX_CHAT_REVIEW_EVIDENCE": "HUMAN_VIA_CODEX_CHAT",
        }
        source = {
            "source_id": source_id,
            "path_or_uri": path_or_uri,
            "sha256": sha,
            "authority_level": authority_aliases.get(
                declared_authority, declared_authority
            ),
            "scope": str(item.get("scope") or "Target requirements"),
            "loaded_completely": bool(item.get("loaded_completely", True)),
            "copy_policy": str(item.get("copy_policy") or "REFERENCE_ONLY"),
            "snapshot_path": item.get("snapshot_path"),
        }
        if source["authority_level"] != declared_authority:
            source["declared_authority_level"] = declared_authority
        for field in (
            "repository_url",
            "revision",
            "commit_sha",
            "git_tree_oid",
            "tree_sha256",
            "license_spdx",
            "license_ref",
            "retrieved_at",
        ):
            if item.get(field) not in (None, ""):
                source[field] = deepcopy(item[field])
        sources.append(source)
    return {
        "schema_version": "2.8",
        "target_id": context["target_id"],
        "sources": sources,
        "conflict_resolution_order": [
            "HUMAN_APPROVED_CHARTER_LOCK",
            "APPROVED_NORMATIVE_SOURCES",
            "LOCKED_CONTRACTS_AND_RULES",
            "WORKPACK",
            "IMPLEMENTATION_NOTE",
            "EXAMPLE",
        ],
        "source_conflicts": deepcopy(ir.get("source_conflicts", [])),
        "unresolved_source_conflicts": [
            item.get("conflict_id")
            for item in ir.get("source_conflicts", [])
            if isinstance(item, Mapping)
            and str(item.get("status", "OPEN")).upper() not in {"RESOLVED", "CLOSED"}
        ],
    }


_WORKPACK_DELIVERY_ORDER = {
    "MB-G0": 0,
    "MB-P1": 1,
    "MB-P2": 2,
    "MB-P3": 3,
    "MB-P4": 4,
    "MB-RELEASE-CANDIDATE": 5,
}


def _resolve_baseline_artifact_ids(
    ir: Mapping[str, Any], declared_ids: list[str]
) -> list[str]:
    artifacts: list[tuple[str, str, str, str]] = []
    atom_ids: list[str] = []
    target = ir.get("target")
    schema_catalog = (
        target.get("artifact_schema_catalog")
        if isinstance(target, Mapping)
        else None
    )
    primary_kind_by_atom = {
        str(atom_id): str(entry.get("artifact_kind"))
        for atom_id, entry in (schema_catalog or {}).items()
        if isinstance(entry, Mapping) and entry.get("artifact_kind")
    }
    for atom in ir.get("atoms", []):
        if not isinstance(atom, Mapping) or not atom.get("atom_id"):
            continue
        atom_id = str(atom["atom_id"])
        atom_ids.append(atom_id)
        contract = atom.get("production_contract")
        if not isinstance(contract, Mapping):
            continue
        for obligation in contract.get("workpack_obligations", []):
            if not isinstance(obligation, Mapping):
                continue
            workpack_id = str(obligation.get("workpack_id") or "")
            for artifact in obligation.get("artifact_obligations", []):
                if isinstance(artifact, Mapping) and artifact.get("artifact_id"):
                    artifacts.append(
                        (
                            str(artifact["artifact_id"]),
                            atom_id,
                            workpack_id,
                            str(artifact.get("artifact_kind") or ""),
                        )
                    )
    known_ids = {artifact_id for artifact_id, _, _, _ in artifacts}
    resolved: list[str] = []
    for declared_id in declared_ids:
        if declared_id in known_ids:
            selected = declared_id
        else:
            atom_id = next(
                (
                    value
                    for value in sorted(atom_ids, key=len, reverse=True)
                    if declared_id.startswith(f"ART-{value}-")
                ),
                None,
            )
            candidates = [
                item for item in artifacts if atom_id is not None and item[1] == atom_id
            ]
            if not candidates:
                raise ValueError(
                    f"baseline target artifact is unresolved: {declared_id}"
                )
            primary_kind = primary_kind_by_atom.get(str(atom_id))
            primary_candidates = [
                item for item in candidates if item[3] == primary_kind
            ]
            selected = max(
                primary_candidates or candidates,
                key=lambda item: (
                    _WORKPACK_DELIVERY_ORDER.get(item[2], -1),
                    item[2],
                    item[0],
                ),
            )[0]
        if selected not in resolved:
            resolved.append(selected)
    return resolved


def _write_baseline_migration_contract(
    staging: Path,
    ir: Mapping[str, Any],
    context: Mapping[str, Any],
) -> None:
    target = ir.get("target")
    contract = (
        target.get("baseline_migration_contract")
        if isinstance(target, Mapping)
        else None
    )
    if not isinstance(contract, Mapping):
        return
    rows = contract.get("disposition_rows")
    required_row_fields = {
        "baseline_capability_id",
        "target_disposition",
        "target_artifact_ids",
        "regression_case_ids",
        "rationale",
    }
    if (
        not contract.get("baseline_source_id")
        or not contract.get("baseline_version")
        or not contract.get("target_version")
        or not isinstance(rows, list)
        or not rows
        or any(
            not isinstance(row, Mapping)
            or not required_row_fields.issubset(row)
            or row.get("target_disposition")
            not in {"RETAIN", "UPGRADE", "REPLACE", "REMOVE"}
            or not isinstance(row.get("target_artifact_ids"), list)
            or not row.get("target_artifact_ids")
            or not isinstance(row.get("regression_case_ids"), list)
            or not row.get("regression_case_ids")
            for row in rows
        )
    ):
        raise ValueError("baseline_migration_contract is incomplete")
    acceptance_case_ids = {
        str(item.get("case_id"))
        for item in ir.get("acceptance_cases", [])
        if isinstance(item, Mapping) and item.get("case_id")
    }
    resolved_rows: list[dict[str, Any]] = []
    for row in rows:
        regression_case_ids = [str(value) for value in row["regression_case_ids"]]
        missing_cases = sorted(set(regression_case_ids) - acceptance_case_ids)
        if missing_cases:
            raise ValueError(
                "baseline regression cases are unresolved: "
                + ",".join(missing_cases)
            )
        resolved_row = deepcopy(dict(row))
        declared_ids = [str(value) for value in row["target_artifact_ids"]]
        resolved_row["declared_target_artifact_ids"] = declared_ids
        resolved_row["target_artifact_ids"] = _resolve_baseline_artifact_ids(
            ir, declared_ids
        )
        resolved_rows.append(resolved_row)

    document = {
        "schema_version": "1.0",
        "contract_id": f"BASELINE-MIGRATION-{context['target_id']}",
        "program_id": context["program_id"],
        "target_id": context["target_id"],
        "requirement_epoch": int(context["requirement_epoch"]),
        "baseline_source_id": contract["baseline_source_id"],
        "baseline_version": contract["baseline_version"],
        "target_version": contract["target_version"],
        "disposition_rows": resolved_rows,
        "completion_rule": (
            "EVERY_BASELINE_CAPABILITY_HAS_ONE_DISPOSITION_AND_ONE_REGRESSION_ORACLE"
        ),
        "status": "FROZEN_NOT_EXECUTED",
    }
    document["contract_sha256"] = _hash_without_field(
        document, "contract_sha256"
    )
    _write_json(
        staging / "canonical_sources/BASELINE_MIGRATION_MATRIX.json",
        document,
    )


def _atom_catalog(ir: Mapping[str, Any], source_manifest: Mapping[str, Any], context: Mapping[str, str]) -> dict[str, Any]:
    default_source = source_manifest["sources"][0]["source_id"]
    atoms: list[dict[str, Any]] = []
    for index, raw in enumerate(ir["atoms"], 1):
        item = dict(raw) if isinstance(raw, Mapping) else {"text_or_lossless_paraphrase": str(raw)}
        atom_id = str(item.get("atom_id") or f"ATOM-{index:03d}")
        catalog_atom = {
                "atom_id": atom_id,
                "source_id": str(item.get("source_id") or default_source),
                "source_locator": str(item.get("source_locator") or f"requirement-{index}"),
                "text_or_lossless_paraphrase": str(item.get("text_or_lossless_paraphrase") or item.get("statement") or item.get("text") or f"Requirement {index}"),
                "modality": str(item.get("modality") or "MUST"),
                "qualifiers": list(item.get("qualifiers") or []),
                "order_constraints": list(item.get("order_constraints") or []),
                "units": list(item.get("units") or []),
                "defaults": list(item.get("defaults") or []),
                "error_semantics": list(item.get("error_semantics") or []),
                "cancel_retry_timeout": list(item.get("cancel_retry_timeout") or []),
                "compatibility_constraints": list(item.get("compatibility_constraints") or []),
                "explicit_non_goals": list(item.get("explicit_non_goals") or []),
                "owner": str(item.get("owner") or "MAIN_HARNESS_BUILD"),
                "verification_mode": str(item.get("verification_mode") or "HUMAN_REVIEW"),
                "status": "PLANNED_NOT_VERIFIED",
            }
        if isinstance(item.get("production_contract"), Mapping):
            catalog_atom["production_contract"] = deepcopy(
                dict(item["production_contract"])
            )
        atoms.append(catalog_atom)
    return {
        "schema_version": "2.8",
        "catalog_id": f"CATALOG-{context['target_id']}",
        "source_manifest_sha256": _json_hash(source_manifest),
        "atoms": atoms,
        "release_blocking_counts": {"missing": 0, "distorted": 0, "unknown": 0, "unmapped": 0},
    }


def _coverage_matrix(ir: Mapping[str, Any], source_manifest: Mapping[str, Any], atom_catalog: Mapping[str, Any], context: Mapping[str, str]) -> dict[str, Any]:
    acceptance = [dict(item) for item in ir["acceptance_cases"] if isinstance(item, Mapping)]
    edge_by_atom = {
        str(item.get("atom_id")): item
        for item in ir.get("coverage_edges", [])
        if isinstance(item, Mapping) and item.get("atom_id")
    }
    coverage: list[dict[str, Any]] = []
    for atom in atom_catalog["atoms"]:
        atom_id = atom["atom_id"]
        cases = [str(item.get("case_id")) for item in acceptance if atom_id in item.get("atom_ids", [])]
        if not cases:
            cases = [f"AC-{atom_id}"]
        edge = edge_by_atom[atom_id]
        coverage.append(
            {
                "atom_id": atom_id,
                "outcome_ids": [f"PO-{atom_id}"],
                "workpack_ids": list(edge["workpack_ids"]),
                "stage_ids": list(edge["stage_ids"]),
                "release_step_ids": list(edge.get("release_step_ids", [])),
                "owner_project_ids": list(edge["owner_project_ids"]),
                "routing_basis": edge["routing_basis"],
                "scenario_ids": cases,
                "assertion_ids": [f"ASSERT-{atom_id}"],
                "required_evidence_types": [atom["verification_mode"]],
                "reverse_mapping_required": True,
                "status": "PLANNED_NOT_VERIFIED",
            }
        )
    return {
        "schema_version": "2.8",
        "matrix_id": f"MATRIX-{context['target_id']}",
        "source_manifest_sha256": _json_hash(source_manifest),
        "normative_atom_catalog_sha256": _json_hash(atom_catalog),
        "coverage": coverage,
        "required_atom_coverage_percent": 100,
        "missing_required_atoms": [],
        "release_ready": False,
    }


def _traceability_graph(
    atom_catalog: Mapping[str, Any],
    coverage_matrix: Mapping[str, Any],
    context: Mapping[str, str],
) -> dict[str, Any]:
    coverage = coverage_matrix.get("coverage", [])
    workpack_ids = list(
        dict.fromkeys(
            workpack_id
            for item in coverage
            for workpack_id in item.get("workpack_ids", [])
        )
    )
    stage_ids = list(
        dict.fromkeys(
            stage_id for item in coverage for stage_id in item.get("stage_ids", [])
        )
    )
    release_step_ids = list(
        dict.fromkeys(
            step_id
            for item in coverage
            for step_id in item.get("release_step_ids", [])
        )
    )
    return {
        "schema_version": "2.8",
        "graph_id": f"TRACE-{context['target_id']}",
        "atoms": [item.get("atom_id") for item in atom_catalog.get("atoms", [])],
        "outcomes": [
            {"outcome_id": item["outcome_ids"][0], "atom_id": item["atom_id"]}
            for item in coverage
        ],
        "workpacks": [
            {
                "workpack_id": workpack_id,
                "project_id": WORKPACK_PROJECTS[workpack_id],
                "role": "PROJECT_REQUIREMENT_IMPLEMENTATION_OR_VERIFICATION",
            }
            for workpack_id in workpack_ids
        ],
        "stages": stage_ids,
        "release_steps": release_step_ids,
        "scenarios": [
            {"scenario_id": scenario, "atom_id": item["atom_id"]}
            for item in coverage
            for scenario in item["scenario_ids"]
        ],
        "assertions": [
            {"assertion_id": item["assertion_ids"][0], "atom_id": item["atom_id"]}
            for item in coverage
        ],
        "evidence_requirements": [
            {
                "evidence_id": f"EVIDENCE-{item['atom_id']}",
                "atom_id": item["atom_id"],
                "types": item["required_evidence_types"],
            }
            for item in coverage
        ],
        "forward_edges": deepcopy(coverage),
        "reverse_index": {
            f"PO-{item['atom_id']}": item["atom_id"] for item in coverage
        }
        | {f"ASSERT-{item['atom_id']}": item["atom_id"] for item in coverage},
        "reverse_workpack_index": {
            workpack_id: [
                item["atom_id"]
                for item in coverage
                if workpack_id in item.get("workpack_ids", [])
            ]
            for workpack_id in workpack_ids
        },
        "reverse_stage_index": {
            stage_id: [
                item["atom_id"]
                for item in coverage
                if stage_id in item.get("stage_ids", [])
            ]
            for stage_id in stage_ids
        },
        "reverse_release_step_index": {
            step_id: [
                item["atom_id"]
                for item in coverage
                if step_id in item.get("release_step_ids", [])
            ]
            for step_id in release_step_ids
        },
        "status": "PLANNED_NOT_VERIFIED",
    }


def _required_target_authorization_classes(
    ir: Mapping[str, Any],
) -> list[str]:
    """Derive target-side side-effect gates from frozen Requirement Atoms."""

    classes = set(
        str(value)
        for value in ir.get("target", {}).get(
            "target_authorization_classes", []
        )
        if isinstance(value, str) and value
    )
    atom_ids: set[str] = set()
    error_codes: set[str] = set()
    for atom in ir.get("atoms", []):
        if not isinstance(atom, Mapping):
            continue
        atom_ids.add(str(atom.get("atom_id") or ""))
        error_codes.update(str(value) for value in atom.get("error_semantics", []))
    if (
        "ATOM-TARGET-SKILL-EXECUTION-GATE" in atom_ids
        or "TARGET_SKILL_EXECUTION_AUTHORIZATION_REQUIRED" in error_codes
    ):
        classes.add("TARGET_SKILL_EXECUTION_AUTHORIZATION")
    if (
        "ATOM-ASSET-ROUTING" in atom_ids
        or "CODEX_IMAGE_GENERATION_AUTHORIZATION_REQUIRED" in error_codes
    ):
        classes.add("CODEX_IMAGE_GENERATION_AUTHORIZATION")
    return sorted(classes)


def _patch_critical_documents(
    docs: dict[str, Any],
    ir: Mapping[str, Any],
    context: Mapping[str, str],
    staging: Path,
    candidate: Path,
    artifact_manifest: Mapping[str, Any] | None,
) -> None:
    target = ir["target"]
    execution = Path(context["execution_root"])
    candidate_version = _current_candidate_version(target)
    requirement_epoch = int(context["requirement_epoch"])
    package_version = _current_package_version(target)
    manifest = docs["PACKAGE_MANIFEST.json"]
    manifest.update(
        {
            "package_id": context["package_id"],
            "target_id": context["target_id"],
            "candidate_version": candidate_version,
            "requirement_epoch": requirement_epoch,
            "version": package_version,
            "status": "START_PACKAGE_AUTHORING_CANDIDATE",
        }
    )
    manifest["not_claimed"] = [
        "HARNESS_IMPLEMENTED",
        "HARNESS_RUNNABLE",
        "CONFORMANCE_CERTIFIED",
        "RELEASE_READY",
        "INSTALLED",
        "AUTO_PROGRESS_AUTHORIZED",
        "PROGRAM_DRIVER_STARTED",
    ]

    start = docs["START_CONTEXT.json"]
    start.update(
        {
            "start_context_id": f"START-CONTEXT-{context['target_id']}",
            "package_id": context["package_id"],
            "package_version": package_version,
            "candidate_version": candidate_version,
            "requirement_epoch": requirement_epoch,
            "target_id": context["target_id"],
            "target_type": context["target_type"],
            "primary_runtime": context["primary_runtime"],
            "runtime_ownership_ref": "constitution/RUNTIME_OWNERSHIP.json",
            "traceability_graph_ref": "canonical_sources/TRACEABILITY_GRAPH.json",
            "requirement_decisions_ref": "canonical_sources/REQUIREMENT_DECISIONS.json",
            "target_root": str(candidate),
            "candidate_root": str(candidate),
            "candidate_root_access": context["candidate_root_access"],
            "execution_root": str(execution),
            "execution_root_status": "PLANNED_NOT_CREATED",
            "candidate_execution_root_overlap": execution == candidate,
            "package_status": "DRAFT_AUTHORING_CANDIDATE",
            "current_state": TARGET_CANDIDATE_STATE,
            "selected_profile": context["profile"],
            "profile_lock_status": "PENDING_HUMAN_APPROVAL",
            "execution_authorization_ref": None,
            "real_target_install_authorization_ref": None,
            "auto_start_generated_workpacks": False,
            "program_driver_started": False,
            "program_driver_runtime_verified": False,
            "control_plane_registration_status": "NOT_REGISTERED",
            "active_workpack": None,
            "next_eligible_transition": "HUMAN_REVIEW_OF_START_PACKAGE",
            "unresolved_human_decisions": [],
            "unresolved_blockers": [],
            "created_at": context["created_at"],
        }
    )
    if explicit_production_enabled(ir):
        start.update(
            {
                "production_semantics_mode": ir["target"][
                    "production_semantics_mode"
                ],
                "artifact_obligation_manifest_ref": (
                    "canonical_sources/ARTIFACT_OBLIGATION_MANIFEST.json"
                ),
                "semantic_task_bundles_frozen": True,
                "runtime_task_binding_complete": False,
            }
        )
    start["controlled_auto_advance"].update(
        {"enabled": False, "authorization_status": "NOT_GRANTED", "real_target_install_excluded": True}
    )

    authorization_classes = _required_target_authorization_classes(ir)
    if authorization_classes:
        policy = docs["AUTHORIZATION_POLICY.json"]
        policy["authorization_classes"] = list(
            dict.fromkeys(
                [*policy.get("authorization_classes", []), *authorization_classes]
            )
        )
        policy["target_subauthorization_rules"] = {
            value: {
                "default_disposition": "DENY",
                "status": "NOT_GRANTED",
                "separate_exact_authorization_required": True,
                "may_not_be_included_in_program_execution_authorization": True,
                "one_time_use_required": True,
                "exact_target_and_input_hash_binding_required": True,
                "exact_job_commit_input_environment_and_output_binding_required": True,
                "environment_manifest_and_receipt_hash_required": True,
                "output_root_manifest_and_receipt_hash_required": True,
                "side_effect_preflight_required": True,
                "receipt_required": True,
            }
            for value in authorization_classes
        }
        for authorization_class in authorization_classes:
            docs[f"{authorization_class}.json"] = {
                "schema_version": "1.0",
                "authorization_class": authorization_class,
                "program_id": context["program_id"],
                "target_id": context["target_id"],
                "status": "NOT_GRANTED",
                "authorization_id": None,
                "issuer_role": None,
                "issued_at": None,
                "expires_at": None,
                "exact_scope": None,
                "exact_scope_contract": {
                    "required_fields": [
                        "target_skill_id",
                        "job_id",
                        "commit_sha",
                        "input_manifest_sha256",
                        "environment_id",
                        "environment_manifest_ref",
                        "environment_manifest_sha256",
                        "output_root_ref",
                        "output_manifest_sha256",
                    ],
                    "scope_kind": (
                        "EXACT_JOB_COMMIT_INPUT_ENVIRONMENT_AND_OUTPUT"
                    ),
                    "program_wide_scope_forbidden": True,
                },
                "input_hashes": [],
                "environment_receipt_ref": None,
                "environment_receipt_sha256": None,
                "output_receipt_ref": None,
                "output_receipt_sha256": None,
                "one_time_use": True,
                "consumed": False,
                "execution_started": False,
                "receipt_ref": None,
            }
        start["target_subauthorization_refs"] = [
            f"{value}.json" for value in authorization_classes
        ]

    docs["PROFILE_LOCK.json"].update(
        {
            "program_id": context["program_id"],
            "selected_profile": context["profile"],
            "selection_reason": f"Selected during frozen requirements for {context['target_name']}.",
            "status": "PENDING_HUMAN_APPROVAL",
            "approved_by": None,
            "sha256": None,
        }
    )
    charter_hash = _file_hash(staging / "PROGRAM_CHARTER.md")
    profile_hash = _json_hash(docs["PROFILE_LOCK.json"])
    source_hash = _file_hash(staging / "canonical_sources/SOURCE_MANIFEST.json")
    atom_hash = _file_hash(staging / "canonical_sources/NORMATIVE_ATOM_CATALOG.json")
    docs["CHARTER_LOCK.json"].update(
        {
            "program_id": context["program_id"],
            "charter_sha256": charter_hash,
            "profile_lock_sha256": profile_hash,
            "source_manifest_sha256": source_hash,
            "normative_atom_catalog_sha256": atom_hash,
            "blocking_open_decisions": [],
            "status": "PENDING_HUMAN_APPROVAL",
            "approved_by": None,
            "approved_at": None,
            "lock_sha256": None,
        }
    )

    state = docs["PROGRAM_STATE.json"]
    state.update(
        {
            "program_id": context["program_id"],
            "current_project_id": None,
            "current_phase": None,
            "current_phase_state": "WAITING_CHARTER_LOCK",
            "highest_touched_phase": None,
            "highest_locally_closed_phase": None,
            "valid_locks": [],
            "blockers": ["START_PACKAGE_HUMAN_REVIEW_REQUIRED"],
            "active_workpack": None,
            "authoring_activity": "BUILD_PROGRAM_AUTHORING",
            "active_execution_mode": "AUTHORING_ONLY",
            "auto_start_generated_workpacks": False,
        }
    )
    state["profile"] = {"value": context["profile"], "status": "PENDING_HUMAN_APPROVAL"}
    state["controlled_auto_advance"].update(
        {"enabled": False, "active_authorization_ref": None, "transition_budget_remaining": 0, "waiting_human_gate": "START_PACKAGE_HUMAN_APPROVAL"}
    )

    three = docs["THREE_PROJECT_PROGRAM_MANIFEST.json"]
    three.update({"program_id": context["program_id"], "target_id": context["target_id"]})
    roots = {
        name: str(execution / "project_start_packages" / directory)
        for name, directory in PROJECTS
    }
    for project in three["projects"]:
        project_id = project["project_id"]
        project["root_abs"] = roots[project_id]
        project["start_package_ref"] = f"project_start_packages/{dict(PROJECTS)[project_id]}"
        project["status"] = "PLANNED_NOT_STARTED"
        if "entrypoint_ref" in project:
            project["entrypoint_ref"] = f"{roots[project_id]}/.venv/bin/{dict(PROJECTS)[project_id]}"
            project["entrypoint_status"] = "PLANNED_NOT_INSTALLED"
        project["repository_root_abs"] = f"{roots[project_id]}/repository"
        project["repository_status"] = "PLANNED_NOT_CREATED"
        project["self_validation_ref"] = str(
            execution
            / "evidence/project_self_validation"
            / f"{project_id}.result.json"
        )
        project["self_validation_status"] = "PLANNED_NOT_RUN"
        project["tool_distribution_hash"] = None
        project["tool_distribution_status"] = "PLANNED_NOT_BUILT"
        if "build_driver_ref" in project:
            project["build_driver_ref"] = "PROGRAM_DRIVER_CONTRACT.json"
    three["shared_control_baseline"].update(
        {
            "protocol_ref": "build_program/conformance/CONFORMANCE_INTERFACE.json",
            "schema_bundle_ref": "constitution/RUNTIME_ATTESTATION_POLICY.json",
            "protocol_sha256": _json_hash(
                docs["build_program/conformance/CONFORMANCE_INTERFACE.json"]
            ),
            "schema_bundle_sha256": _json_hash(
                docs["constitution/RUNTIME_ATTESTATION_POLICY.json"]
            ),
            "hash_algorithm": "CANONICAL_JSON_SHA256",
            "charter_hash": charter_hash,
            "profile_lock_hash": profile_hash,
            "source_manifest_hash": source_hash,
            "normative_atom_catalog_hash": atom_hash,
            "control_plane_epoch": 0,
            "program_driver_runtime_verified": False,
        }
    )

    engineering_nodes = _engineering_nodes(
        context,
        candidate,
        required_artifact_refs_by_workpack=(
            _required_artifact_refs_by_workpack(
                artifact_manifest,
                context=context,
            )
        ),
        profile_hash=profile_hash,
        charter_hash=charter_hash,
    )
    docs["ENGINEERING_PROJECT_DAG.json"].update(
        {
            "program_id": context["program_id"],
            "dag_status": "PLANNED_NOT_EXECUTABLE",
            "fixed_node_order": list(ENGINEERING_NODE_ORDER),
            "implicit_edges_forbidden": True,
            "global_single_active_workpack": True,
            "nodes": engineering_nodes,
            "edges": [
                {"from": left["node_id"], "to": right["node_id"]}
                for left, right in zip(engineering_nodes, engineering_nodes[1:])
            ],
        }
    )
    docs["PHASE_DEPENDENCY_MANIFEST.json"].update({"profile": context["profile"], "profile_lock_ref": "PROFILE_LOCK.json"})
    docs["RELEASE_PIPELINE_MANIFEST.json"].update(
        {
            "program_id": context["program_id"],
            "target_id": context["target_id"],
            "pipeline_status": "PLANNED_NOT_ACTIVE",
            "active_step_id": None,
            "fixed_step_order": list(RELEASE_STEP_ORDER),
            "single_active_step": True,
            "implicit_edges_forbidden": True,
            "terminal_state": "REAL_TARGET_ACTIVE",
            "steps": _release_pipeline_steps(
                context,
                candidate,
                profile_hash=profile_hash,
                charter_hash=charter_hash,
            ),
        }
    )

    driver_state = docs["PROGRAM_DRIVER_STATE.json"]
    driver_state.update(
        {
            "program_id": context["program_id"],
            "driver_status": "NOT_STARTED_AUTHORING_ONLY",
            "driver_started": False,
            "runtime_verification_status": "NOT_VERIFIED",
            "side_effects_allowed": False,
            "controlled_auto_advance_enabled": False,
            "active_execution_authorization_ref": None,
            "active_project_id": None,
            "active_dag_node_id": None,
            "active_phase": None,
            "active_workpack_id": None,
            "next_eligible_transition": "START_PACKAGE_HUMAN_APPROVAL",
            "waiting_human_gate": "START_PACKAGE_HUMAN_APPROVAL",
            "open_blocker_ids": ["START_PACKAGE_HUMAN_REVIEW_REQUIRED"],
            "open_finding_ids": [],
            "unpropagated_invalidation_ids": [],
            "updated_at": context["created_at"],
        }
    )
    for project in driver_state.get("projects", {}).values():
        project["status"] = "PLANNED_NOT_STARTED"

    docs["PROGRAM_DRIVER_CONTRACT.json"].update(
        {
            "program_id": context["program_id"],
            "driver_entrypoint_abs": str(
                execution / "control_plane/.venv/bin/program-driver"
            ),
            "driver_started_by_authoring": False,
            "runtime_verification_ref": None,
            "transaction_contract": {
                "lease_and_fencing_token_required": True,
                "job_artifact_root_requires_exactly_one_active_job_lease": True,
                "job_artifact_lease_must_bind_command_workpack_job_and_scope_hash": True,
                "workpack_union_paths_are_catalog_only_not_active_grants": True,
                "stale_expired_or_consumed_job_artifact_lease_rejected": True,
                "idempotency_key_required": True,
                "command_completion_and_state_commit_atomic": True,
                "duplicate_side_effect_command_rejected": True,
                "single_next_action_or_block": True,
            },
            "crash_recovery_contract": {
                "readback_before_resume_required": True,
                "completed_command_receipt_reconciled_before_retry": True,
                "unknown_commit_state_blocks_reexecution": True,
                "resume_requires_current_authorization": True,
            },
        }
    )
    docs["PROGRAM_AUTOMATION_POLICY.json"].update(
        {
            "program_id": context["program_id"],
            "default_mode": "AUTHORING_ONLY",
            "automatic_progress_default": False,
            "authoring_may_start_driver": False,
            "planned_limits_from_frozen_ir": {
                "max_transitions": int(ir.get("automation", {}).get("max_transitions", 32)),
                "max_loop_rounds": int(ir.get("automation", {}).get("max_loop_rounds", 3)),
                "stop_gate": str(ir.get("automation", {}).get("stop_gate", "P4_CERTIFIED_RELEASE_LOCK")),
            },
        }
    )
    docs["EXECUTION_AUTHORIZATION.json"].update(
        {
            "program_id": context["program_id"],
            "status": "DRAFT_NOT_GRANTED",
            "may_auto_advance": False,
            "max_transitions": 0,
            "real_target_install_allowed": False,
            "signature": None,
        }
    )
    docs["REAL_TARGET_INSTALL_AUTHORIZATION.json"].update(
        {"program_id": context["program_id"], "status": "DRAFT_NOT_GRANTED", "signature": None}
    )
    docs["LOOP_STATE.json"].update(
        {"program_id": context["program_id"], "status": "NOT_STARTED", "authorization_ref": None, "current_iteration": 0, "promotion_eligible": False}
    )
    max_loop_rounds = int(ir.get("automation", {}).get("max_loop_rounds", 3))
    docs["LOOP_POLICY.json"].setdefault("loop_types", {})[
        "WORKPACK_EXECUTION"
    ] = {
        "auto_retry_allowed": False,
        "max_iterations": max_loop_rounds,
        "max_same_finding_repeats": 1,
        "max_oscillation_repeats": 1,
    }
    for loop_config in docs["LOOP_POLICY.json"].get("loop_types", {}).values():
        if isinstance(loop_config, dict):
            loop_config["max_iterations"] = min(
                int(loop_config.get("max_iterations", max_loop_rounds)),
                max_loop_rounds,
            )
    reentry = docs["REENTRY_PLAN.json"]
    reentry.update(
        {
            "program_id": context["program_id"],
            "status": "DRAFT_NOT_AUTHORIZED",
            "finding_ids": [],
            "repair_owner": None,
            "repair_workpack_id": None,
            "invalidation_event_refs": [],
            "earliest_required_reentry_gate": None,
            "authorization_ref": None,
        }
    )
    docs["PACKAGE_ROLES.json"].update({"target_id": context["target_id"]})
    docs["build_program/conformance/CONFORMANCE_INTERFACE.json"].update(
        {"target_id": context["target_id"], "selected_profile": context["profile"]}
    )
    three["shared_control_baseline"]["protocol_sha256"] = _json_hash(
        docs["build_program/conformance/CONFORMANCE_INTERFACE.json"]
    )
    three["shared_control_baseline"]["schema_bundle_sha256"] = _json_hash(
        docs["constitution/RUNTIME_ATTESTATION_POLICY.json"]
    )

    first_wp = context["first_workpack_id"]
    index = docs["WORKPACK_INDEX.json"]
    index.update({"program_id": context["program_id"], "active_workpack_id": None, "next_eligible_workpack_id": None})
    index["workpacks"][0].update(
        {
            "workpack_id": first_wp,
            "status": "PLANNED_NOT_ACTIVE",
            "workpack_ref": f"workpacks/{first_wp}.md",
            "capsule_ref": f"capsules/{first_wp}.capsule.json",
            "command_manifest_ref": f"commands/{first_wp}.commands.json",
            "result_ref": f"results/{first_wp}.result.json",
            "loop_state_ref": f"loops/{first_wp}.loop.json",
            "requires": list(ROOT_MATERIALIZATION_REQUIRES),
            "requirement_sources": {
                "LAB_TOOL_RELEASE_LOCK_VALID": "ENGINEERING_DAG:LAB_TOOL_RELEASE_LOCKED",
                "LINKAGE_TOOL_RELEASE_LOCK_VALID": "ENGINEERING_DAG:LINKAGE_TOOL_RELEASE_LOCKED",
            },
            "produces": list(ROOT_MATERIALIZATION_PRODUCES),
            "command_ids": list(ROOT_MATERIALIZATION_COMMAND_IDS),
            "command_execution_order": list(ROOT_MATERIALIZATION_COMMAND_IDS),
            "intent_atom_ids": [],
            "validation_scope": ROOT_LAYER_VALIDATION_SCOPE,
            "behavioral_atom_acceptance": ROOT_LAYER_BEHAVIORAL_ATOM_POLICY,
            "execution_authorization_ref": None,
            "auto_start": False,
        }
    )

    _patch_command_manifest(docs["COMMAND_MANIFEST.json"], context, candidate)
    docs["WORKPACK_RESULT.json"].update(
        {
            "program_id": context["program_id"],
            "project_id": "MAIN_HARNESS_BUILD",
            "workpack_id": first_wp,
            "status": "NOT_RUN",
            "execution_mode": "WORKPACK_EXECUTION",
            "authorization_ref": None,
            "capsule_ref": f"capsules/{first_wp}.capsule.json",
            "command_manifest_ref": f"commands/{first_wp}.commands.json",
            "promotion_eligible": False,
            "expected_capabilities": list(ROOT_MATERIALIZATION_PRODUCES),
            "intent_atom_ids": [],
            "validation_scope": ROOT_LAYER_VALIDATION_SCOPE,
            "behavioral_atom_acceptance": ROOT_LAYER_BEHAVIORAL_ATOM_POLICY,
        }
    )
    docs["CAPSULE.json"].update(
        {
            "workpack_id": first_wp,
            "program_id": context["program_id"],
            "profile_lock_hash": profile_hash,
            "charter_hash": charter_hash,
            "canonical_source_refs": ["canonical_sources/SOURCE_MANIFEST.json"],
            "canonical_source_hashes": [source_hash],
            "intent_atom_ids": [],
            "workspace_root_abs": str(
                execution / "project_start_packages/main_build/repository"
            ),
            "workspace_root_status": "PLANNED_NOT_CREATED",
            "allowed_write_paths": [
                str(execution / "project_start_packages/main_build/repository")
            ],
            "forbidden_write_paths": [
                *(
                    [str(candidate)]
                    if execution != candidate
                    else [
                        str(candidate / "project_start_packages/external_lab"),
                        str(candidate / "project_start_packages/linkage_review"),
                    ]
                ),
                str(execution / "real_target"),
                *[
                    str(Path(str(source.get("path_or_uri") or source.get("path"))).expanduser().resolve())
                    for source in ir.get("sources", [])
                    if isinstance(source, Mapping)
                    and isinstance(source.get("path_or_uri") or source.get("path"), str)
                    and "://" not in str(source.get("path_or_uri") or source.get("path"))
                ],
            ],
            "required_inputs": [
                "canonical_sources/SOURCE_MANIFEST.json",
                "canonical_sources/NORMATIVE_ATOM_CATALOG.json",
                "canonical_sources/ATOM_COVERAGE_MATRIX.json",
                "CHARTER_LOCK.json",
                "PROFILE_LOCK.json",
            ],
            "required_outputs": list(ROOT_MATERIALIZATION_PRODUCES),
            "requires": list(ROOT_MATERIALIZATION_REQUIRES),
            "requirement_sources": {
                "LAB_TOOL_RELEASE_LOCK_VALID": "ENGINEERING_DAG:LAB_TOOL_RELEASE_LOCKED",
                "LINKAGE_TOOL_RELEASE_LOCK_VALID": "ENGINEERING_DAG:LINKAGE_TOOL_RELEASE_LOCKED",
            },
            "produces": list(ROOT_MATERIALIZATION_PRODUCES),
            "command_ids": list(ROOT_MATERIALIZATION_COMMAND_IDS),
            "validation_scope": ROOT_LAYER_VALIDATION_SCOPE,
            "behavioral_atom_acceptance": ROOT_LAYER_BEHAVIORAL_ATOM_POLICY,
            "return_path": "REOPEN_OR_SINGLE_REPAIR_OWNER_VIA_REENTRY_PLAN",
            "command_manifest_ref": f"commands/{first_wp}.commands.json",
            "workpack_ref": f"workpacks/{first_wp}.md",
            "execution_mode": "WORKPACK_EXECUTION",
            "target_environment": "CANDIDATE_SANDBOX_PLANNED_NOT_CREATED",
            "hydration_complete": False,
            "execution_authorized": False,
            "execution_authorization_ref": None,
            "max_attempts": 0,
            "result_ref": f"results/{first_wp}.result.json",
        }
    )
    architecture_epoch = target.get("architecture_epoch")
    architecture_control_plane_epoch = target.get("control_plane_epoch")
    requirement_architecture_epoch = architecture_epoch
    requirement_architecture_control_plane_epoch = (
        architecture_control_plane_epoch
    )
    unbound_zero_semantics = (
        architecture_epoch is None
        and architecture_control_plane_epoch is None
    )
    if architecture_epoch is None and architecture_control_plane_epoch is None:
        architecture_epoch = 0
        architecture_control_plane_epoch = 0
    epoch_domains = None
    if (
        isinstance(architecture_epoch, int)
        and not isinstance(architecture_epoch, bool)
        and isinstance(architecture_control_plane_epoch, int)
        and not isinstance(architecture_control_plane_epoch, bool)
    ):
        epoch_domains = {
            "schema_version": "1.0",
            "architecture_epoch": architecture_epoch,
            "architecture_control_plane_epoch": (
                architecture_control_plane_epoch
            ),
            "execution_control_plane_epoch": 0,
            "legacy_control_plane_epoch_alias": (
                "execution_control_plane_epoch"
            ),
            "requirement_architecture_epoch": requirement_architecture_epoch,
            "requirement_architecture_control_plane_epoch": (
                requirement_architecture_control_plane_epoch
            ),
            "projection_rule": (
                "NULL_REQUIREMENT_EPOCHS_TO_EXPLICIT_UNBOUND_ZERO_SENTINEL"
                if unbound_zero_semantics
                else "IDENTITY_REQUIREMENT_EPOCH_PROJECTION"
            ),
            "unbound_zero_semantics": unbound_zero_semantics,
        }
    binding = {
        "program_id": context["program_id"],
        "profile_lock_hash": profile_hash,
        "charter_hash": charter_hash,
        "control_plane_epoch": 0,
    }
    if epoch_domains is not None:
        binding["epoch_domains"] = epoch_domains
    for asset_name in (
        "THREE_PROJECT_PROGRAM_MANIFEST.json",
        "ENGINEERING_PROJECT_DAG.json",
        "RELEASE_PIPELINE_MANIFEST.json",
        "PROGRAM_DRIVER_CONTRACT.json",
        "PROGRAM_DRIVER_STATE.json",
        "PROGRAM_AUTOMATION_POLICY.json",
        "AUTHORIZATION_POLICY.json",
        "EXECUTION_AUTHORIZATION.json",
        "REAL_TARGET_INSTALL_AUTHORIZATION.json",
        "LOOP_POLICY.json",
        "LOOP_STATE.json",
        "FINDING_SCHEMA.json",
        "REPAIR_ROUTING_RULES.json",
        "INVALIDATION_DAG.json",
        "REENTRY_PLAN.json",
        "PROGRAM_STATE.json",
        "PHASE_DEPENDENCY_MANIFEST.json",
        "WORKPACK_INDEX.json",
        "COMMAND_MANIFEST.json",
        "CAPSULE.json",
    ):
        docs[asset_name].update(binding)
    command_without_hash = dict(docs["COMMAND_MANIFEST.json"])
    command_without_hash.pop("manifest_sha256", None)
    docs["COMMAND_MANIFEST.json"]["manifest_sha256"] = _stable_hash(
        command_without_hash
    )


def _patch_command_manifest(document: dict[str, Any], context: Mapping[str, str], candidate: Path) -> None:
    execution = Path(context["execution_root"])
    python_path = execution / "project_start_packages/main_build/.venv/bin/python"
    workspace_root = execution / "project_start_packages/main_build/repository"
    workpack_id = context["first_workpack_id"]
    document.update(
        {
            "manifest_id": f"COMMANDS-{workpack_id}",
            "workpack_id": workpack_id,
            "workspace_root_ref": f"TARGET-ROOT:{candidate}",
            "default_disposition": "DECLARE_ONLY",
            "execution_authorization_ref": None,
            "execution_started": False,
        }
    )
    verification_commands = document.get("commands", [])
    for command in verification_commands:
        argv = [str(python_path), "-m", "unittest", "discover", "-s", "tests"]
        command.update(
            {
                "command_id": "ROOT-MATERIALIZATION-VERIFY",
                "command_kind": "LOCKED_TEMPLATE_VERIFICATION_COMMAND",
                "executable": str(python_path),
                "executable_abs": str(python_path),
                "executable_sha256": None,
                "executable_status": "PLANNED_NOT_INSTALLED",
                "preflight_gate": "PROGRAM_DRIVER_RUNTIME_VERIFIED",
                "argv": argv,
                "command_sha256": _stable_hash({"argv": argv, "cwd": str(workspace_root)}),
                "cwd_abs": str(workspace_root),
                "allowed_read_roots": [str(candidate), str(workspace_root)],
                "allowed_write_roots": [
                    str(workspace_root / ".test-artifacts")
                ],
                "authorization_ref": None,
                "auto_execute": False,
                "shell": False,
            }
        )
    codex_path = execution / "planned_executors/bin/codex"
    codex_command = {
        "command_id": "ROOT-CODEX-CODING",
        "command_kind": "PLANNED_EXECUTOR_INTERFACE",
        "executor_role": "CODEX_CODING_AGENT",
        "executable": str(codex_path),
        "executable_abs": str(codex_path),
        "executable_sha256": None,
        "executable_status": "PLANNED_NOT_INSTALLED",
        "argv": None,
        "invocation_contract_status": "REQUIRES_VERIFIED_CLI_SCHEMA_AND_PREFLIGHT",
        "unverified_cli_flags_forbidden": True,
        "cwd_abs": str(workspace_root),
        "allowed_read_roots": [str(candidate), str(workspace_root)],
        "authorization_ref": None,
        "preflight_gate": "PROGRAM_DRIVER_RUNTIME_VERIFIED_AND_CODEX_CLI_SCHEMA_VERIFIED",
        "allowed_modes": ["WORKPACK_EXECUTION"],
        "allowed_write_roots": [str(workspace_root)],
        "expected_exit_codes": [],
        "stdout_stderr_exit_code_required": True,
        "auto_execute": False,
        "shell": False,
    }
    codex_command["command_sha256"] = _hash_without_field(
        codex_command, "command_sha256"
    )
    document["commands"] = [codex_command, *verification_commands]
    document_without_hash = dict(document)
    document_without_hash.pop("manifest_sha256", None)
    document["manifest_sha256"] = _stable_hash(document_without_hash)


def _runtime_ownership(
    context: Mapping[str, str], candidate: Path
) -> dict[str, Any]:
    execution = Path(context["execution_root"])
    runtime = str(context["primary_runtime"])
    runtime_slug = _slug(runtime).lower() or "target-runtime"
    if "codex" in runtime.lower():
        runtime_slug = "codex"
        runtime_family = "CODEX"
    elif "python" in runtime.lower():
        runtime_slug = "python"
        runtime_family = "PYTHON"
    elif "node" in runtime.lower():
        runtime_slug = "node"
        runtime_family = "NODE"
    else:
        runtime_family = "OTHER_EXPLICIT"
    final_runtime_slug = _slug(context["target_id"]).lower()
    final_entrypoint = execution / "planned_runtime/bin" / final_runtime_slug
    required_executor = execution / "planned_executors/bin" / runtime_slug
    coding_agent_executor = execution / "planned_executors/bin/codex"
    driver_entrypoint = execution / "control_plane/.venv/bin/program-driver"
    return {
        "schema_version": "2.8",
        "target_id": context["target_id"],
        "target_type": context["target_type"],
        "primary_runtime": runtime,
        "runtime_family": runtime_family,
        "primary_runtime_semantic_role": "REQUIRED_EXECUTOR_OR_PROVIDER",
        "final_runtime_entrypoint_abs": str(final_entrypoint),
        "final_runtime_entrypoint_status": "PLANNED_NOT_INSTALLED",
        "build_program_driver_entrypoint_abs": str(driver_entrypoint),
        "build_program_driver_entrypoint_status": "PLANNED_NOT_INSTALLED",
        "entrypoints_must_be_distinct": True,
        "required_executor": {
            "name": runtime,
            "executable_abs": str(required_executor),
            "status": "PLANNED_NOT_INSTALLED",
            "invocation_argv": None,
            "invocation_contract_status": "REQUIRES_TARGET_SPECIFIC_CLI_SCHEMA_AND_PREFLIGHT",
            "unverified_cli_flags_forbidden": True,
        },
        "coding_agent_executor": {
            "name": "Codex",
            "semantic_role": "AUTHORIZED_ENGINEERING_WORKPACK_CODING_AGENT",
            "executable_abs": str(coding_agent_executor),
            "status": "PLANNED_NOT_INSTALLED",
            "invocation_argv": None,
            "invocation_contract_status": "REQUIRES_VERIFIED_CLI_SCHEMA_AND_PREFLIGHT",
            "unverified_cli_flags_forbidden": True,
        },
        "coding_agent_must_not_be_substituted_by_verification_runtime": True,
        "runtime_probe_argv": None,
        "runtime_probe_status": "PLANNED_REQUIRES_VERIFIED_CLI_SCHEMA",
        "runtime_attestation_required": True,
        "runtime_attestation_policy_ref": "constitution/RUNTIME_ATTESTATION_POLICY.json",
        "python_or_harness_self_report_may_prove_codex": False,
        "source_tree_entrypoint_fallback_allowed": False,
        "build_program_driver_fallback_allowed": False,
        "execution_status": "PLANNED_NOT_STARTED",
    }


def _acceptance_artifact_refs(bundle: Mapping[str, Any] | None) -> list[str]:
    """Control results remain Workpack outputs, but are not task-writable."""
    return [artifact["artifact_ref"]
            for task in (bundle or {}).get("task_contracts", [])
            for artifact in task["artifact_obligations"]
            if artifact.get("artifact_kind") == "WORKPACK_CONTROL_RESULT"]


def _required_artifact_refs_by_workpack(
    artifact_manifest: Mapping[str, Any] | None,
    *,
    context: Mapping[str, str],
) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = {}
    if not isinstance(artifact_manifest, Mapping):
        return refs
    for workpack_id, structural_contract in PROJECT_WORKPACK_CONTRACTS.items():
        project_id = str(structural_contract.get("project_id") or "")
        bundle = task_bundle_for_workpack(
            artifact_manifest,
            workpack_id=workpack_id,
            project_id=project_id,
            program_id=str(context["program_id"]),
            target_id=str(context["target_id"]),
            structural_contract=structural_contract,
        )
        if bundle is not None:
            refs[workpack_id] = list(bundle["required_artifact_refs"])
    return refs


def _artifact_write_paths(
    execution: Path, required_artifact_refs: Sequence[str]
) -> list[str]:
    prefix = f"{LOGICAL_EXECUTION_ROOT}/"
    roots: list[str] = []
    for artifact_ref in required_artifact_refs:
        if not artifact_ref.startswith(prefix) or "/" not in artifact_ref:
            raise ValueError(
                "required artifact ref must be below the logical Execution Root: "
                f"{artifact_ref}"
            )
        relative_parent = artifact_ref[len(prefix) :].rsplit("/", 1)[0]
        root = str(execution / relative_parent)
        if root not in roots:
            roots.append(root)
    return roots


def _artifact_dependency_read_refs(
    artifact_manifest: Mapping[str, Any] | None,
    required_artifact_ids: Sequence[str],
) -> list[str]:
    """Return logical roots containing the full prerequisite closure."""

    if not isinstance(artifact_manifest, Mapping):
        return []
    artifact_index = artifact_manifest.get("artifact_index")
    if not isinstance(artifact_index, Mapping):
        return []
    queue = [str(artifact_id) for artifact_id in required_artifact_ids]
    visited: set[str] = set()
    dependency_refs: list[str] = []
    evidence_refs: list[str] = []
    while queue:
        artifact_id = queue.pop(0)
        if artifact_id in visited:
            continue
        visited.add(artifact_id)
        artifact = artifact_index.get(artifact_id)
        if not isinstance(artifact, Mapping):
            continue
        for evidence_ref in artifact.get("depends_on_evidence_refs", []):
            value = str(evidence_ref or "")
            if value and value not in evidence_refs:
                evidence_refs.append(value)
        for dependency_id in artifact.get("depends_on_artifact_ids", []):
            dependency_key = str(dependency_id)
            dependency = artifact_index.get(dependency_key)
            if not isinstance(dependency, Mapping):
                continue
            dependency_ref = str(dependency.get("artifact_ref") or "")
            if dependency_ref and dependency_ref not in dependency_refs:
                dependency_refs.append(dependency_ref)
            if dependency_key not in visited:
                queue.append(dependency_key)
    return list(
        dict.fromkeys(
            value.rsplit("/", 1)[0]
            for value in [*dependency_refs, *evidence_refs]
            if value
        )
    )


def specialize_public_job_contracts(
    requirement_ir: Mapping[str, Any],
    resolved_job: Mapping[str, str],
    *,
    declared_provider_read_refs: Sequence[str],
) -> dict[str, Any]:
    """Pure reference model for the declared dynamic pipeline; grants no lease.

    Reuses the ordinary Producer and dependency traversal. The caller must
    independently resolve/verify source bytes and authorize runtime providers.
    Returned roots are a request, never execution authority or a receipt.
    """
    compiled = compile_declared_production_contracts(requirement_ir, resolved_job=resolved_job)
    index = {
        artifact["artifact_id"]: artifact
        for atom in compiled.get("atoms", [])
        for obligation in atom.get("production_contract", {}).get("workpack_obligations", [])
        for artifact in obligation.get("artifact_obligations", [])
    }
    job_id = resolved_job["job_id"]
    selected = {key: value for key, value in index.items() if value.get("job_id") == job_id}
    if not selected:
        raise ValueError("dynamic Job has no derived artifacts")
    queue = list(selected)
    visited = set()
    while queue:
        key = queue.pop()
        if key in visited:
            continue
        visited.add(key)
        if key not in index:
            raise ValueError("dynamic Job has an unresolved dependency")
        artifact = index[key]
        if artifact.get("job_id") not in (None, job_id):
            raise ValueError("dynamic Job depends on another Job")
        queue.extend(artifact.get("depends_on_artifact_ids", []))
    reads = _artifact_dependency_read_refs({"artifact_index": index}, list(selected))
    job_root = f"harness-resource://execution/jobs/{job_id}"
    source_reads = [resolved_job.get(field) for field in ("resolved_tree_ref", "resolution_receipt_ref")]
    if any(not isinstance(ref, str) or not ref for ref in source_reads):
        raise ValueError("dynamic Job needs the resolved source tree and receipt read references")
    reads = list(dict.fromkeys([LOGICAL_CANDIDATE_ROOT, *source_reads, *reads, *declared_provider_read_refs]))
    if any("/jobs/" in ref and not (ref == job_root or ref.startswith(job_root + "/")) for ref in reads):
        raise ValueError("dynamic Job read request crosses Job roots")
    if any(not value["artifact_ref"].startswith(job_root + "/") for value in selected.values()):
        raise ValueError("dynamic Job output escapes its write root")
    return {
        "status": "DECLARE_ONLY_NOT_RUN", "execution_started": False,
        "artifact_index": {key: index[key] for key in sorted(visited)},
        "lease_request": {"job_id": job_id, "allowed_read_roots": reads,
                          "allowed_write_roots": [job_root], "authorization_ref": None},
    }


def _artifact_dependency_read_paths(
    execution: Path,
    artifact_manifest: Mapping[str, Any] | None,
    required_artifact_ids: Sequence[str],
) -> list[str]:
    """Return physical execution roots containing the full prerequisites."""

    logical_roots = _artifact_dependency_read_refs(
        artifact_manifest, required_artifact_ids
    )
    return _artifact_write_paths(
        execution, [f"{root}/dependency.json" for root in logical_roots]
    )


def _job_artifact_scopes(
    artifact_roots: Sequence[str], *, roots_field: str
) -> list[dict[str, Any]]:
    scopes: dict[str, list[str]] = {}
    for artifact_root in artifact_roots:
        marker = "/jobs/"
        if marker not in artifact_root:
            continue
        suffix = artifact_root.split(marker, 1)[1]
        job_id = suffix.split("/", 1)[0]
        if job_id and artifact_root not in scopes.setdefault(job_id, []):
            scopes[job_id].append(artifact_root)
    return [
        {"job_id": job_id, roots_field: scopes[job_id]}
        for job_id in sorted(scopes)
    ]


def _job_artifact_lease_contract(
    *,
    command_id: str,
    workpack_id: str,
    read_scopes: Sequence[Mapping[str, Any]],
    write_scopes: Sequence[Mapping[str, Any]],
    selection_cardinality: str = "EXACTLY_ONE_ACTIVE_JOB_LEASE_PER_INVOCATION",
) -> dict[str, Any] | None:
    """Describe the one-Job runtime lease without granting one in authoring."""

    reads = {
        str(scope.get("job_id")): sorted(
            str(value) for value in scope.get("allowed_read_roots", [])
        )
        for scope in read_scopes
        if isinstance(scope, Mapping) and scope.get("job_id")
    }
    writes = {
        str(scope.get("job_id")): sorted(
            str(value) for value in scope.get("allowed_write_roots", [])
        )
        for scope in write_scopes
        if isinstance(scope, Mapping) and scope.get("job_id")
    }
    job_ids = sorted(set(reads) | set(writes))
    if not job_ids:
        return None
    bindings = []
    for job_id in job_ids:
        read_roots = reads.get(job_id, [])
        write_roots = writes.get(job_id, [])
        scope_document = {
            "job_id": job_id,
            "allowed_read_roots": read_roots,
            "allowed_write_roots": write_roots,
        }
        bindings.append(
            {
                **scope_document,
                "allowed_read_roots_sha256": _json_hash(read_roots),
                "allowed_write_roots_sha256": _json_hash(write_roots),
                "scope_sha256": _json_hash(scope_document),
                "lease_receipt_ref": (
                    f"{LOGICAL_EXECUTION_ROOT}/evidence/job_artifact_leases/"
                    f"{workpack_id}/{command_id}/{job_id}.lease.json"
                ),
            }
        )
    root_array = {
        "type": "array",
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1},
    }
    hash_field = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    return {
        "schema_version": "1.0",
        "contract_id": f"JOB-ARTIFACT-LEASE-{workpack_id}-{command_id}",
        "selection_cardinality": selection_cardinality,
        "job_scope_bindings": bindings,
        "receipt_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "lease_id",
                "program_id",
                "project_id",
                "workpack_id",
                "command_id",
                "job_id",
                "lease_receipt_ref",
                "allowed_read_roots",
                "allowed_read_roots_sha256",
                "allowed_write_roots",
                "allowed_write_roots_sha256",
                "scope_sha256",
                "holder_id",
                "fencing_token",
                "issued_at",
                "expires_at",
                "lease_state_sha256",
                "consumed",
                "status",
            ],
            "properties": {
                "lease_id": {"type": "string", "minLength": 1},
                "program_id": {"type": "string", "minLength": 1},
                "project_id": {"type": "string", "minLength": 1},
                "workpack_id": {"const": workpack_id},
                "command_id": {"const": command_id},
                "job_id": {"enum": job_ids},
                "lease_receipt_ref": {
                    "enum": [item["lease_receipt_ref"] for item in bindings]
                },
                "allowed_read_roots": deepcopy(root_array),
                "allowed_read_roots_sha256": deepcopy(hash_field),
                "allowed_write_roots": deepcopy(root_array),
                "allowed_write_roots_sha256": deepcopy(hash_field),
                "scope_sha256": deepcopy(hash_field),
                "holder_id": {"type": "string", "minLength": 1},
                "fencing_token": {"type": "integer", "minimum": 1},
                "issued_at": {"type": "string", "format": "date-time"},
                "expires_at": {"type": "string", "format": "date-time"},
                "lease_state_sha256": deepcopy(hash_field),
                "consumed": {"const": False},
                "status": {"const": "ACTIVE"},
            },
            "oneOf": [
                {
                    "properties": {
                        "job_id": {"const": item["job_id"]},
                        "lease_receipt_ref": {
                            "const": item["lease_receipt_ref"]
                        },
                        "allowed_read_roots": {
                            "const": item["allowed_read_roots"]
                        },
                        "allowed_read_roots_sha256": {
                            "const": item["allowed_read_roots_sha256"]
                        },
                        "allowed_write_roots": {
                            "const": item["allowed_write_roots"]
                        },
                        "allowed_write_roots_sha256": {
                            "const": item["allowed_write_roots_sha256"]
                        },
                        "scope_sha256": {"const": item["scope_sha256"]},
                    }
                }
                for item in bindings
            ],
            "x-invariants": [
                "LEASE_PROGRAM_PROJECT_WORKPACK_AND_COMMAND_MATCH_INVOCATION",
                "LEASE_JOB_ID_SELECTS_EXACTLY_ONE_DECLARED_SCOPE_BINDING",
                "LEASE_RECEIPT_REF_MATCHES_SELECTED_JOB_BINDING",
                "LEASE_READ_AND_WRITE_ROOTS_EQUAL_SELECTED_JOB_SCOPE",
                "LEASE_ROOT_AND_SCOPE_SHA256S_RECOMPUTE_FROM_CANONICAL_ARRAYS",
                "LEASE_FENCING_TOKEN_IS_CURRENT_AND_SINGLE_USE",
                "LEASE_ISSUED_AT_PRECEDES_EXPIRES_AT_AND_IS_NOT_EXPIRED",
            ],
        },
        "failure_codes": [
            "JOB_ARTIFACT_LEASE_MISSING",
            "JOB_ARTIFACT_LEASE_CARDINALITY_INVALID",
            "JOB_ARTIFACT_LEASE_SCOPE_MISMATCH",
            "JOB_ARTIFACT_LEASE_FENCING_TOKEN_INVALID",
            "JOB_ARTIFACT_LEASE_EXPIRED",
            "JOB_ARTIFACT_LEASE_REPLAYED",
        ],
    }


def _project_workpack_allowed_write_paths(
    execution: Path,
    *,
    project_id: str,
    directory: str,
    workpack_id: str,
    required_artifact_refs: Sequence[str] = (),
) -> list[str]:
    """Return the exact write roots declared by a project Workpack contract."""

    contract = PROJECT_WORKPACK_CONTRACTS[workpack_id]
    allowed_write_paths = [
        str(execution / "evidence/project_workpacks" / project_id / workpack_id)
    ]
    if any(
        command_id.endswith("CODEX-CODING")
        for command_id in contract["command_ids"]
    ):
        allowed_write_paths.append(
            str(execution / "project_start_packages" / directory / "repository")
        )
    for artifact_root in _artifact_write_paths(
        execution, required_artifact_refs
    ):
        if artifact_root not in allowed_write_paths:
            allowed_write_paths.append(artifact_root)
    if workpack_id == CASE_EVIDENCE_WRITER_WORKPACK_ID:
        case_root = str(execution / "evidence/cases")
        if case_root not in allowed_write_paths:
            allowed_write_paths.append(case_root)
    return allowed_write_paths


def _workpack_auxiliary_write_roots(
    execution: Path, workpack_id: str
) -> list[str]:
    if workpack_id == CASE_EVIDENCE_WRITER_WORKPACK_ID:
        return [str(execution / "evidence/cases")]
    return []


def _bind_commands_to_workpack_artifact_roots(
    commands_by_id: Mapping[str, Mapping[str, Any]],
    command_ids: Sequence[str],
    artifact_write_roots: Sequence[str],
    artifact_read_roots: Sequence[str] = (),
    *,
    workpack_id: str,
    workpack_read_roots: Sequence[str] = (),
    acceptance_write_roots: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Declare semantic roots without granting one command every Job root."""

    job_scopes: dict[str, list[str]] = {}
    shared_roots: list[str] = []
    for artifact_root in artifact_write_roots:
        if artifact_root in acceptance_write_roots:
            continue
        marker = "/jobs/"
        if marker in artifact_root:
            suffix = artifact_root.split(marker, 1)[1]
            job_id = suffix.split("/", 1)[0]
            if job_id:
                job_scopes.setdefault(job_id, []).append(artifact_root)
                continue
        shared_roots.append(artifact_root)
    shared_read_roots = [
        root for root in artifact_read_roots if "/jobs/" not in root
    ]

    commands: list[dict[str, Any]] = []
    for command_id in command_ids:
        command = deepcopy(dict(commands_by_id[command_id]))
        command.pop("workpack_artifact_write_roots", None)
        command.pop("shared_artifact_write_roots", None)
        command.pop("job_artifact_write_scopes", None)
        command.pop("job_artifact_read_scopes", None)
        command.pop("job_artifact_lease_contract", None)
        command.pop("shared_artifact_read_roots", None)
        roots = [
            root
            for root in command.get("allowed_write_roots") or []
            if root not in artifact_write_roots
        ]
        is_coding_command = command_id.endswith("CODEX-CODING")
        for artifact_root in shared_roots:
            if artifact_root not in roots:
                roots.append(artifact_root)
        command["allowed_write_roots"] = roots
        read_roots = [
            root
            for root in command.get("allowed_read_roots") or []
            if root not in artifact_read_roots
        ]
        for artifact_root in [*workpack_read_roots, *shared_read_roots]:
            if artifact_root not in read_roots:
                read_roots.append(artifact_root)
        command["allowed_read_roots"] = read_roots
        command["shared_artifact_read_roots"] = list(shared_read_roots)
        command["shared_artifact_write_roots"] = list(shared_roots)
        command["job_artifact_write_scopes"] = (
            [
                {"job_id": job_id, "allowed_write_roots": job_scopes[job_id]}
                for job_id in sorted(job_scopes)
            ]
            if is_coding_command
            else []
        )
        is_case_runner = command_id in {"LAB-RUN-CASE-PARTITION", "LAB-RUN-REGISTRY-CASE"}
        lease_eligible = is_coding_command or (
            workpack_id == CASE_EVIDENCE_WRITER_WORKPACK_ID
            and is_case_runner
        )
        command["job_artifact_read_scopes"] = (
            _job_artifact_scopes(
                artifact_read_roots, roots_field="allowed_read_roots"
            )
            if lease_eligible
            else []
        )
        command["artifact_read_scope_mode"] = (
            "ONE_JOB_LEASE_REQUIRED"
            if lease_eligible and command["job_artifact_read_scopes"]
            else "SHARED_ONLY"
            if shared_read_roots
            else "NONE"
        )
        command["artifact_write_scope_mode"] = (
            "ONE_JOB_LEASE_REQUIRED"
            if is_coding_command and job_scopes
            else "SHARED_ONLY"
            if shared_roots
            else "NONE"
        )
        lease_contract = (
            _job_artifact_lease_contract(
                command_id=command_id,
                workpack_id=workpack_id,
                read_scopes=command["job_artifact_read_scopes"],
                write_scopes=command["job_artifact_write_scopes"],
                selection_cardinality=(
                    "EXACTLY_ONE_ACTIVE_JOB_LEASE_PER_REGISTRY_READ_PARTITION"
                    if command_id == "LAB-RUN-REGISTRY-CASE"
                    else "EXACTLY_ONE_ACTIVE_JOB_LEASE_PER_CASE_PARTITION"
                    if is_case_runner
                    else "EXACTLY_ONE_ACTIVE_JOB_LEASE_PER_INVOCATION"
                ),
            )
            if lease_eligible
            else None
        )
        command["job_artifact_lease_required"] = lease_contract is not None
        command["job_artifact_lease_contract"] = lease_contract
        command["active_job_artifact_lease_ref"] = None
        command["job_artifact_scope_activation_policy"] = (
            "NO_JOB_ARTIFACT_ROOT_IS_ACTIVE_WITHOUT_EXACTLY_ONE_CURRENT_LEASE"
            if lease_contract is not None
            else "NO_JOB_ARTIFACT_SCOPE"
        )
        if command_id == "MB-TEST":
            executable = str(
                command.get("executable_abs") or command.get("executable") or ""
            )
            execution_root = executable.split("/project_start_packages/", 1)[0]
            test_temp_root = (
                f"{execution_root}/evidence/project_workpacks/"
                f"MAIN_HARNESS_BUILD/{workpack_id}/pytest-tmp"
            )
            command["argv"] = [
                executable,
                "-B",
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "--basetemp",
                test_temp_root,
                "tests",
            ]
            command["environment"] = {
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "PYTHONHASHSEED": "0",
            }
            command["allowed_write_roots"] = [test_temp_root]
            command["test_repository_write_policy"] = (
                "FORBIDDEN_VERIFY_SNAPSHOT_BEFORE_AFTER"
            )
        if command.get("executor_role") == "INDEPENDENT_PROJECT_VERIFIER":
            # The supervisor records stdout in the controller. The checked
            # implementation cannot rewrite itself or a structural PASS file.
            command["allowed_write_roots"] = []
            command["shared_artifact_write_roots"] = []
            command["artifact_write_scope_mode"] = "NONE"
        command["command_sha256"] = _hash_without_field(
            command, "command_sha256"
        )
        commands.append(command)
    return commands


def _engineering_nodes(
    context: Mapping[str, str],
    candidate: Path,
    *,
    required_artifact_refs_by_workpack: Mapping[str, Sequence[str]] | None = None,
    profile_hash: str,
    charter_hash: str,
) -> list[dict[str, Any]]:
    execution = Path(context["execution_root"])
    artifact_refs_by_workpack = required_artifact_refs_by_workpack or {}
    project_for_node = {
        "LAB_": "EXTERNAL_CONFORMANCE_LAB",
        "LINKAGE_": "CONFORMANCE_LINKAGE_REVIEW",
        "MAIN_": "MAIN_HARNESS_BUILD",
    }
    owner_for_node = {
        "LAB_": "EXTERNAL_CONFORMANCE_LAB_OWNER",
        "LINKAGE_": "READ_ONLY_LINKAGE_OWNER",
        "MAIN_": "MAIN_BUILD_OWNER",
    }
    nodes: list[dict[str, Any]] = []
    for index, node_id in enumerate(ENGINEERING_NODE_ORDER):
        predecessor = ENGINEERING_NODE_ORDER[index - 1] if index else None
        successor = (
            ENGINEERING_NODE_ORDER[index + 1]
            if index + 1 < len(ENGINEERING_NODE_ORDER)
            else None
        )
        prefix = next(
            (value for value in project_for_node if node_id.startswith(value)), None
        )
        project_id = project_for_node[prefix] if prefix else "PROGRAM_CONTROL"
        owner_role = owner_for_node[prefix] if prefix else "PROGRAM_CONTROL_OWNER"
        workpack_id = (
            context["first_workpack_id"]
            if node_id == "MAIN_EXECUTION_PACKAGE_MATERIALIZED"
            else DAG_WORKPACK_BINDINGS.get(node_id)
        )
        workpack_sequence = list(
            DAG_WORKPACK_SEQUENCE_BINDINGS.get(node_id, ())
        )
        if node_id == "START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW":
            node_kind = "AUTHORING_TERMINAL"
            mode = "AUTHORING_ONLY"
            authorization = None
        elif node_id == "START_PACKAGE_HUMAN_APPROVAL":
            node_kind = "HUMAN_GATE"
            mode = "REGISTRATION_ONLY"
            authorization = None
            owner_role = "HUMAN_GATE_OWNER"
        elif "SELF_CONFORMANCE" in node_id or node_id.endswith("VALIDATED") or node_id.endswith("VERIFIED"):
            node_kind = "INDEPENDENT_VALIDATION_GATE"
            mode = "PROJECT_VALIDATION"
            authorization = "PROJECT_VALIDATION_AUTHORIZATION"
        elif "RELEASE_LOCKED" in node_id:
            node_kind = "TOOL_RELEASE_GATE"
            mode = "PACKAGE_BUILD"
            authorization = "PACKAGE_BUILD_AUTHORIZATION"
        elif node_id in DAG_WORKPACK_BINDINGS and node_id.startswith("MAIN_"):
            node_kind = "MAIN_PHASE_GATE"
            mode = "WORKPACK_EXECUTION"
            authorization = "PROGRAM_EXECUTION_AUTHORIZATION"
        elif node_id in DAG_WORKPACK_SEQUENCE_BINDINGS:
            node_kind = "PROJECT_WORKPACK_SEQUENCE"
            mode = "WORKPACK_EXECUTION"
            authorization = "PROJECT_BOOTSTRAP_AUTHORIZATION"
        elif node_id == "MAIN_EXECUTION_PACKAGE_MATERIALIZED":
            node_kind = "PROJECT_MATERIALIZATION_ACTION"
            mode = "WORKPACK_EXECUTION"
            authorization = "PROJECT_BOOTSTRAP_AUTHORIZATION"
        elif node_id == "RELEASE_PIPELINE_HANDOFF":
            node_kind = "PIPELINE_HANDOFF"
            mode = "RELEASE_PIPELINE"
            authorization = "RELEASE_PIPELINE_AUTHORIZATION"
        else:
            node_kind = "CONTROL_REGISTRATION_GATE"
            mode = "REGISTRATION_ONLY"
            authorization = "REGISTRATION_AUTHORIZATION"
        if node_id == "MAIN_PROGRAM_REGISTRATION":
            owner_role = "BUILD_PROGRAM_DRIVER"
        elif node_id == "MAIN_EXECUTION_PACKAGE_VALIDATED":
            owner_role = "START_PACKAGE_VALIDATOR"
        elif node_id == "MAIN_EXECUTION_PACKAGE_MATERIALIZED":
            owner_role = "MAIN_PROGRAM_AUTHOR"
        elif node_id in DAG_WORKPACK_BINDINGS and node_id.startswith("MAIN_"):
            owner_role = "MAIN_DRIVER_AND_GATE_OWNER"
        project_dir = dict(PROJECTS).get(project_id)
        project_root = (
            execution / "project_start_packages" / project_dir
            if project_dir
            else execution / "control_plane"
        )
        node_evidence_root = execution / "evidence/engineering_dag" / node_id
        write_paths = [str(node_evidence_root)]
        if (
            node_id in DAG_WORKPACK_SEQUENCE_BINDINGS
            or node_id == "MAIN_EXECUTION_PACKAGE_MATERIALIZED"
            or node_id in DAG_WORKPACK_BINDINGS
            and node_id.startswith("MAIN_")
        ):
            write_paths.append(str(project_root / "repository"))
        human_gate = node_id == "START_PACKAGE_HUMAN_APPROVAL"
        action_kind = (
            "CONDITIONAL"
            if node_id == "MAIN_P3_C3_OR_APPROVED_NA"
            else "WORKPACK_SEQUENCE"
            if workpack_sequence
            else "WORKPACK"
            if workpack_id
            else "PIPELINE_ACTION"
        )
        conditional_branches = (
            {
                "IMPLEMENT": {
                    "workpack_id": "MB-P3",
                    "allowed_write_paths": [str(project_root / "repository")],
                    "completion_gate": "P3_BUILD_LOCK_AND_C3_PASS",
                },
                "APPROVED_NOT_APPLICABLE": {
                    "pipeline_action_id": "P3_NOT_APPLICABLE_LOCK",
                    "human_decision_required": True,
                    "allowed_write_paths": [
                        str(execution / "evidence/engineering_dag" / node_id)
                    ],
                    "completion_gate": "P3_NOT_APPLICABLE_LOCK_AND_C3_PASS",
                },
            }
            if node_id == "MAIN_P3_C3_OR_APPROVED_NA"
            else {}
        )
        bound_workpack_ids = [
            *([workpack_id] if workpack_id else []),
            *workpack_sequence,
        ]
        project_bound_workpack_ids = [
            value
            for value in bound_workpack_ids
            if value in PROJECT_WORKPACK_CONTRACTS
        ]
        if project_bound_workpack_ids and project_dir is None:
            raise ValueError(
                f"project Workpack node {node_id} has no project directory"
            )
        for bound_id in project_bound_workpack_ids:
            for allowed_root in _project_workpack_allowed_write_paths(
                execution,
                project_id=project_id,
                directory=str(project_dir),
                workpack_id=bound_id,
                required_artifact_refs=artifact_refs_by_workpack.get(
                    bound_id, ()
                ),
            ):
                if allowed_root not in write_paths:
                    write_paths.append(allowed_root)
        if node_id == "MAIN_P3_C3_OR_APPROVED_NA":
            conditional_branches["IMPLEMENT"]["allowed_write_paths"] = (
                _project_workpack_allowed_write_paths(
                    execution,
                    project_id=project_id,
                    directory=str(project_dir),
                    workpack_id="MB-P3",
                    required_artifact_refs=artifact_refs_by_workpack.get(
                        "MB-P3", ()
                    ),
                )
            )
        workpack_requires = list(
            dict.fromkeys(
                capability
                for bound_id in project_bound_workpack_ids
                for capability in PROJECT_WORKPACK_CONTRACTS[bound_id]["requires"]
            )
        )
        workpack_produces = list(
            dict.fromkeys(
                capability
                for bound_id in project_bound_workpack_ids
                for capability in PROJECT_WORKPACK_CONTRACTS[bound_id]["produces"]
            )
        )
        if node_id == "MAIN_EXECUTION_PACKAGE_MATERIALIZED":
            workpack_requires = list(ROOT_MATERIALIZATION_REQUIRES)
            workpack_produces = list(ROOT_MATERIALIZATION_PRODUCES)
        success_gate = f"{node_id}_PASS"
        special_capabilities = {
            "SHARED_CONTROL_BASELINE_LOCK": (
                "CHARTER_LOCK_VALID",
                "SHARED_PROTOCOL_LOCK_VALID",
            ),
            "LAB_TOOL_RELEASE_LOCKED": (
                "EXTERNAL_LAB_INTERFACE_REGISTERED",
                "LAB_TOOL_RELEASE_LOCK_VALID",
            ),
            "LINKAGE_TOOL_RELEASE_LOCKED": (
                "LINKAGE_REVIEW_INTERFACE_REGISTERED",
                "LINKAGE_TOOL_RELEASE_LOCK_VALID",
            ),
            "MAIN_PROGRAM_REGISTRATION": (
                "MAIN_INTERFACE_REGISTERED",
                "MAIN_AND_LAB_INTERFACES_REGISTERED",
            ),
            "MAIN_P3_C3_OR_APPROVED_NA": (
                "P3_BUILD_LOCK_OR_APPROVED_P3_NA_LOCK_VALID",
                "C3_CHECKPOINT_PASS",
            ),
        }
        produces_capabilities = list(
            dict.fromkeys(
                [
                    success_gate,
                    *workpack_produces,
                    *special_capabilities.get(node_id, ()),
                ]
            )
        )
        sequence_edges = [
            {
                "from_workpack_id": left,
                "to_workpack_id": right,
                "required_capabilities": [
                    capability
                    for capability in PROJECT_WORKPACK_CONTRACTS[left]["produces"]
                    if capability
                    in PROJECT_WORKPACK_CONTRACTS[right]["requires"]
                ],
            }
            for left, right in zip(workpack_sequence, workpack_sequence[1:])
        ]
        nodes.append(
            {
                "node_id": node_id,
                "project_id": project_id,
                "node_kind": node_kind,
                "owner_role": owner_role,
                "required_predecessor_nodes": [predecessor] if predecessor else [],
                "requires": [predecessor] if predecessor else [],
                "required_lock_refs": ["CHARTER_LOCK.json", "PROFILE_LOCK.json"],
                "required_input_hashes": {
                    "charter_hash": charter_hash,
                    "profile_lock_hash": profile_hash,
                },
                "required_tool_distribution_hashes": {
                    "lab_distribution_hash": None,
                    "linkage_distribution_hash": None,
                    "status": "PLANNED_NOT_AVAILABLE_UNTIL_TOOL_RELEASE",
                },
                "required_execution_mode": mode,
                "required_authorization_scope": authorization,
                "workpack_id": workpack_id,
                "project_workpack_sequence": workpack_sequence,
                "project_workpack_index_ref": (
                    "WORKPACK_INDEX.json"
                    if node_id == "MAIN_EXECUTION_PACKAGE_MATERIALIZED"
                    else f"project_start_packages/{project_dir}/WORKPACK_INDEX.json"
                    if project_dir
                    else None
                ),
                "pipeline_action_id": None if workpack_id else node_id,
                "action_kind": action_kind,
                "completion_rule": (
                    "SELECTED_BRANCH_RESULT_AND_C3_VALID"
                    if action_kind == "CONDITIONAL"
                    else "ALL_WORKPACK_RESULTS_VALID_IN_DECLARED_ORDER"
                    if action_kind == "WORKPACK_SEQUENCE"
                    else "WORKPACK_RESULT_AND_SUCCESS_GATE_VALID"
                    if action_kind == "WORKPACK"
                    else "PIPELINE_ACTION_RESULT_AND_SUCCESS_GATE_VALID"
                ),
                "single_active_workpack": True,
                "conditional_branches": conditional_branches,
                "project_workpack_required_capabilities": workpack_requires,
                "project_workpack_produced_capabilities": workpack_produces,
                "project_workpack_sequence_edges": sequence_edges,
                "produces_capabilities": produces_capabilities,
                "validation_scope": (
                    ROOT_LAYER_VALIDATION_SCOPE
                    if node_id
                    in {
                        "MAIN_EXECUTION_PACKAGE_MATERIALIZED",
                        "MAIN_EXECUTION_PACKAGE_VALIDATED",
                    }
                    else None
                ),
                "behavioral_atom_acceptance": (
                    ROOT_LAYER_BEHAVIORAL_ATOM_POLICY
                    if node_id
                    in {
                        "MAIN_EXECUTION_PACKAGE_MATERIALIZED",
                        "MAIN_EXECUTION_PACKAGE_VALIDATED",
                    }
                    else None
                ),
                "allowed_read_paths": [str(candidate)],
                "allowed_write_paths": write_paths,
                "environment_id": f"ENV-{_slug(node_id)}-PLANNED",
                "success_gate": success_gate,
                "success_output_refs": [str(node_evidence_root / "result.json")],
                "failure_return_node": predecessor or "AUTHORING_REOPEN_REQUIRED",
                "invalidates_on": [
                    "CHARTER_HASH_CHANGED",
                    "PROFILE_LOCK_HASH_CHANGED",
                    "CONTROL_PLANE_EPOCH_CHANGED",
                    "REQUIRED_INPUT_OR_TOOL_HASH_CHANGED",
                ],
                "allowed_next_nodes": [successor] if successor else [],
                "human_gate": human_gate,
                "human_gate_id": node_id if human_gate else None,
                "authorization_class": authorization,
                "auto_advance_eligible": index > 4 and not human_gate,
                "parallel_read_only_group": None,
                "status": (
                    "READY"
                    if index == 0
                    else "WAITING_HUMAN_GATE"
                    if human_gate
                    else "WAITING_PREDECESSOR"
                ),
            }
        )
    return nodes


def _release_pipeline_steps(
    context: Mapping[str, str],
    candidate: Path,
    *,
    profile_hash: str,
    charter_hash: str,
) -> list[dict[str, Any]]:
    execution = Path(context["execution_root"])
    output_by_step = {
        "P4_BUILD_INPUT_LOCK": "P4_BUILD_INPUT_LOCK_VALID",
        "PACK_DRAFT": "CONFORMANCE_PACK_DRAFT_READY",
        "LINKAGE_A_INTERFACE_COMPLETENESS": "LINKAGE_A_PASS",
        "LINKAGE_B0_NORMATIVE_BINDING": "PACK_B0_PASS",
        "LINKAGE_C_EVIDENCE_COMPATIBILITY": "LINKAGE_C_PASS",
        "IMMUTABLE_ARTIFACT_BUILD": "IMMUTABLE_RELEASE_ARTIFACT",
        "LINKAGE_B1_ARTIFACT_BINDING": "PACK_B1_PASS",
        "P4_INSTALLABILITY_ENV_CREATE": "P4_INSTALLABILITY_ENV_READY",
        "EXACT_ARTIFACT_INSTALL_AND_ORIGIN_CHECK": "EXACT_ARTIFACT_ORIGIN_VERIFIED",
        "P4_INSTALLABILITY_RECEIPT": "P4_INSTALLABILITY_PASS",
        "P4_RELEASE_CANDIDATE_LOCK": "P4_RELEASE_CANDIDATE_LOCK_VALID",
        "SINGLE_CERTIFICATION_ENV_CREATE": "SINGLE_CERTIFICATION_ENV_READY",
        "CERTIFICATION_INSTALL_ONCE": "CERTIFICATION_INSTALL_ONCE_PASS",
        "INSTALLED_TARGET_DESCRIPTOR": "INSTALLED_TARGET_DESCRIPTOR_VERIFIED",
        "LINKAGE_D_INSTALLED_HANDSHAKE": "LINKAGE_D_PASS",
        "LAB_INSTALLED_POSITIVE_NEGATIVE_TAMPER_TESTS": "LAB_INSTALLED_TEST_MATRIX_PASS",
        "C4_REPORT": "C4_CHECKPOINT_PASS",
        "CONFORMANCE_CERTIFICATE": "CONFORMANCE_CERTIFICATE_READY",
        "P4_CERTIFIED_RELEASE_LOCK": "P4_CERTIFIED_RELEASE_LOCK_VALID",
        "WAIT_REAL_TARGET_INSTALL_AUTHORIZATION": "REAL_TARGET_INSTALL_AUTHORIZATION_GRANTED",
        "REAL_TARGET_INSTALL": "REAL_TARGET_INSTALL_COMPLETED",
        "REAL_TARGET_INSTALLATION_RECEIPT": "REAL_TARGET_INSTALL_RECEIPT_VERIFIED",
        "ACTIVE_INSTANCE_MANIFEST": "REAL_TARGET_ACTIVE",
    }
    steps: list[dict[str, Any]] = []
    previous_step: str | None = None
    previous_output: str | None = None
    for order, step_id in enumerate(RELEASE_STEP_ORDER, 1):
        if step_id.startswith("LINKAGE_"):
            owner = "CONFORMANCE_LINKAGE_REVIEW"
            mode = "LINKAGE_READ_ONLY"
            authorization = "LINKAGE_EXECUTION_AUTHORIZATION"
        elif step_id.startswith("LAB_") or step_id in {"C4_REPORT", "CONFORMANCE_CERTIFICATE"}:
            owner = "EXTERNAL_CONFORMANCE_LAB"
            mode = "LAB_CERTIFICATION"
            authorization = "LAB_CERTIFICATION_AUTHORIZATION"
        elif any(term in step_id for term in ("ENV_CREATE", "INSTALL", "DESCRIPTOR", "ACTIVE_INSTANCE")):
            owner = "CERTIFICATION_INSTALLER"
            mode = "REAL_TARGET_INSTALL" if order >= 20 else "CERTIFICATION_INSTALL"
            authorization = (
                "REAL_TARGET_INSTALL_AUTHORIZATION"
                if order >= 20
                else "CERTIFICATION_INSTALL_AUTHORIZATION"
            )
        elif "LOCK" in step_id:
            owner = "BUILD_PROGRAM_DRIVER"
            mode = "REGISTRATION_ONLY"
            authorization = "CANDIDATE_PROMOTION_AUTHORIZATION"
        else:
            owner = "MAIN_HARNESS_BUILD"
            mode = "PACKAGE_BUILD" if "ARTIFACT" in step_id else "WORKPACK_EXECUTION"
            authorization = "RELEASE_PIPELINE_AUTHORIZATION"
        if step_id == "WAIT_REAL_TARGET_INSTALL_AUTHORIZATION":
            owner = "HUMAN_GATE_OWNER"
            mode = "REGISTRATION_ONLY"
            authorization = "REAL_TARGET_INSTALL_AUTHORIZATION"
        if 8 <= order <= 10:
            owner = "CERTIFICATION_INSTALLER"
            mode = "P4_INSTALLABILITY"
            authorization = "INSTALLABILITY_AUTHORIZATION"
        elif 12 <= order <= 14:
            owner = "CERTIFICATION_INSTALLER"
            mode = "CERTIFICATION_INSTALL"
            authorization = "CERTIFICATION_INSTALL_AUTHORIZATION"
        if step_id == "P4_CERTIFIED_RELEASE_LOCK":
            authorization = "CERTIFIED_RELEASE_PROMOTION_AUTHORIZATION"
        requires = [previous_output] if previous_output else [
            "P4_LOCAL_GATE_PASS",
            "P3_BUILD_LOCK_OR_APPROVED_NA_LOCK_VALID",
            "C3_CHECKPOINT_PASS",
        ]
        if step_id == "REAL_TARGET_INSTALL":
            requires = [
                "P4_CERTIFIED_RELEASE_LOCK_VALID",
                "REAL_TARGET_INSTALL_AUTHORIZATION_GRANTED",
            ]
        environment_id = (
            "P4_INSTALLABILITY_ENV"
            if 8 <= order <= 10
            else "SINGLE_CERTIFICATION_ENV"
            if 12 <= order <= 19
            else "REAL_TARGET_ENV"
            if order >= 20
            else "BUILD_WORKSPACE"
        )
        human_gate = step_id == "WAIT_REAL_TARGET_INSTALL_AUTHORIZATION"
        next_step = (
            RELEASE_STEP_ORDER[order] if order < len(RELEASE_STEP_ORDER) else None
        )
        project_workpack_id = RELEASE_WORKPACK_BINDINGS.get(step_id)
        if project_workpack_id and project_workpack_id.startswith("LAB-"):
            workpack_project_id = "EXTERNAL_CONFORMANCE_LAB"
            workpack_directory = "external_lab"
        elif project_workpack_id and project_workpack_id.startswith("LINK-"):
            workpack_project_id = "CONFORMANCE_LINKAGE_REVIEW"
            workpack_directory = "linkage_review"
        elif project_workpack_id and project_workpack_id.startswith("MB-"):
            workpack_project_id = "MAIN_HARNESS_BUILD"
            workpack_directory = "main_build"
        else:
            workpack_project_id = None
            workpack_directory = None
        project_workpack_contract = (
            PROJECT_WORKPACK_CONTRACTS[project_workpack_id]
            if project_workpack_id
            else None
        )
        steps.append(
            {
                "step_id": step_id,
                "pipeline_action_id": step_id,
                "project_workpack_id": project_workpack_id,
                "project_workpack_project_id": workpack_project_id,
                "project_workpack_index_ref": (
                    f"project_start_packages/{workpack_directory}/WORKPACK_INDEX.json"
                    if workpack_directory
                    else None
                ),
                "project_workpack_command_manifest_ref": (
                    f"project_start_packages/{workpack_directory}/commands/"
                    f"{project_workpack_id}.commands.json"
                    if workpack_directory and project_workpack_id
                    else None
                ),
                "project_workpack_required_capabilities": (
                    list(project_workpack_contract["requires"])
                    if project_workpack_contract
                    else []
                ),
                "project_workpack_produced_capabilities": (
                    list(project_workpack_contract["produces"])
                    if project_workpack_contract
                    else []
                ),
                "project_workpack_command_ids": (
                    list(project_workpack_contract["command_ids"])
                    if project_workpack_contract
                    else []
                ),
                "action_kind": (
                    "WORKPACK_THEN_PIPELINE_ACTION"
                    if step_id == "P4_RELEASE_CANDIDATE_LOCK"
                    else "PROJECT_WORKPACK"
                    if project_workpack_id
                    else "PIPELINE_ACTION"
                ),
                "project_workpack_completion_scope": (
                    "PREPARE_CANDIDATE_THEN_DRIVER_PROMOTES_LOCK"
                    if step_id == "P4_RELEASE_CANDIDATE_LOCK"
                    else "READ_ONLY_INTERFACE_PREFLIGHT"
                    if step_id == "LINKAGE_A_INTERFACE_COMPLETENESS"
                    else "READ_ONLY_INSTALLED_HANDSHAKE"
                    if step_id == "LINKAGE_D_INSTALLED_HANDSHAKE"
                    else "INSTALLED_TEST_EVIDENCE_ONLY_CERTIFICATE_FORBIDDEN"
                    if step_id
                    == "LAB_INSTALLED_POSITIVE_NEGATIVE_TAMPER_TESTS"
                    else None
                ),
                "order": order,
                "owner": owner,
                "mode": mode,
                "authorization_class": authorization,
                "required_predecessor_step_ids": [previous_step] if previous_step else [],
                "requires": requires,
                "produces": [output_by_step[step_id]],
                "required_lock_refs": ["CHARTER_LOCK.json", "PROFILE_LOCK.json"],
                "required_input_hashes": {
                    "charter_hash": charter_hash,
                    "profile_lock_hash": profile_hash,
                },
                "required_tool_distribution_hashes": {
                    "lab_distribution_hash": None,
                    "linkage_distribution_hash": None,
                    "status": "PLANNED_NOT_AVAILABLE_UNTIL_TOOL_RELEASE",
                },
                "allowed_read_paths": [str(candidate)],
                "allowed_write_paths": [
                    str(execution / "evidence/release_pipeline" / step_id)
                ],
                "environment_id": environment_id,
                "success_output_refs": [
                    str(execution / "evidence/release_pipeline" / f"{step_id}.result.json")
                ],
                "failure_return_step_id": previous_step or "MAIN_P4_LOCAL_CLOSURE",
                "invalidates_on": [
                    "CHARTER_HASH_CHANGED",
                    "PROFILE_LOCK_HASH_CHANGED",
                    "CONTROL_PLANE_EPOCH_CHANGED",
                    "UPSTREAM_OUTPUT_OR_TOOL_HASH_CHANGED",
                ],
                "allowed_next_step_ids": [next_step] if next_step else [],
                "human_gate": human_gate,
                "auto_advance_eligible": step_id not in {
                    "WAIT_REAL_TARGET_INSTALL_AUTHORIZATION",
                    "REAL_TARGET_INSTALL",
                },
            }
        )
        previous_step = step_id
        previous_output = output_by_step[step_id]
    return steps


def _repository_fixture_jobs(ir: Mapping[str, Any]) -> list[dict[str, Any]]:
    def artifact_ref(kind: str, job_id: str) -> str | None:
        for atom in ir.get("atoms", []):
            contract = atom.get("production_contract") if isinstance(atom, Mapping) else None
            if not isinstance(contract, Mapping):
                continue
            for obligation in contract.get("workpack_obligations", []):
                if not isinstance(obligation, Mapping):
                    continue
                for artifact in obligation.get("artifact_obligations", []):
                    if (
                        isinstance(artifact, Mapping)
                        and artifact.get("artifact_kind") == kind
                        and artifact.get("job_id") == job_id
                    ):
                        return str(artifact.get("artifact_ref") or "")
        return None

    jobs: list[dict[str, Any]] = []
    for raw_job in repository_job_bindings(ir):
        job = dict(raw_job)
        job_id = job["job_id"]
        claim_ref = artifact_ref("FUNCTION_SCENARIO_EFFECT_MATRIX", job_id) or (
            f"{LOGICAL_EXECUTION_ROOT}/jobs/{job_id}/"
            "semantic_expectations/function_scenario_effect_matrix.json"
        )
        demo_ref = artifact_ref("BEFORE_AFTER_DEMO_CONTRACT", job_id) or (
            f"{LOGICAL_EXECUTION_ROOT}/jobs/{job_id}/"
            "semantic_expectations/before_after_demo_contract.json"
        )
        job.update(
            {
                "input_skill_count": 1,
                "expected_output_count": 1,
                "expected_function": f"{claim_ref}#/claims/*/function",
                "expected_scenario": f"{claim_ref}#/claims/*/trigger_scenario",
                "expected_effect": f"{claim_ref}#/claims/*/effect",
                "demo_contract_ref": demo_ref,
            }
        )
        jobs.append(job)
    return jobs


def _case_artifact_expectations(
    ir: Mapping[str, Any], atom_ids: list[str],
    required_artifact_kinds: Sequence[str] = (),
) -> list[dict[str, Any]]:
    rank = _WORKPACK_DELIVERY_ORDER
    expectations: list[dict[str, Any]] = []
    required_kinds = {
        str(value) for value in required_artifact_kinds if str(value)
    }
    seen_artifact_ids: set[str] = set()
    for atom in ir.get("atoms", []):
        if not isinstance(atom, Mapping):
            continue
        contract = atom.get("production_contract")
        if not isinstance(contract, Mapping):
            continue
        obligations = [
            item
            for item in contract.get("workpack_obligations", [])
            if isinstance(item, Mapping)
        ]
        if not obligations:
            continue
        selected_artifacts: list[Mapping[str, Any]] = []
        if str(atom.get("atom_id")) in atom_ids:
            terminal = max(
                obligations,
                key=lambda item: (
                    rank.get(str(item.get("workpack_id") or ""), -1),
                    str(item.get("workpack_id") or ""),
                ),
            )
            selected_artifacts.extend(
                artifact
                for artifact in terminal.get("artifact_obligations", [])
                if isinstance(artifact, Mapping)
            )
        if required_kinds:
            selected_artifacts.extend(
                artifact
                for obligation in obligations
                for artifact in obligation.get("artifact_obligations", [])
                if isinstance(artifact, Mapping)
                and str(artifact.get("artifact_kind") or "") in required_kinds
            )
        for artifact in selected_artifacts:
            if not isinstance(artifact, Mapping):
                continue
            artifact_id = str(artifact.get("artifact_id") or "")
            if not artifact_id or artifact_id in seen_artifact_ids:
                continue
            seen_artifact_ids.add(artifact_id)
            schema = artifact.get("schema")
            expectations.append(
                {
                    "artifact_id": artifact_id,
                    "job_id": artifact.get("job_id"),
                    "source_id": artifact.get("source_id"),
                    "artifact_kind": str(artifact.get("artifact_kind") or ""),
                    "artifact_ref": str(artifact.get("artifact_ref") or ""),
                    "schema_sha256": _json_hash(schema) if isinstance(schema, Mapping) else None,
                    "depends_on_artifact_ids": list(
                        artifact.get("depends_on_artifact_ids") or []
                    ),
                }
            )
    return expectations


_NEGATIVE_MUTATION_ARTIFACT_TARGETS: dict[
    str, tuple[str, tuple[str, ...]]
] = {
    "video.duration_seconds": (
        "MEDIA_ACCEPTANCE_RECEIPT",
        ("/duration_seconds",),
    ),
    "video.format": (
        "MEDIA_ACCEPTANCE_RECEIPT",
        ("/width", "/height", "/fps"),
    ),
    "narration.playback_speed": (
        "NARRATION_SCRIPT",
        ("/playback_speed",),
    ),
    "tts.execution_mode": ("LOCAL_TTS_RECEIPT", ("/execution_mode",)),
    "alignment.max_anchor_error_seconds": (
        "AUDIO_ALIGNMENT_RECEIPT",
        ("/max_anchor_error_seconds",),
    ),
    "alignment.word_anchors": (
        "AUDIO_ALIGNMENT_RECEIPT",
        ("/word_anchors",),
    ),
    "motion.binding_granularity": (
        "OBJECT_MOTION_IR",
        ("/shots/0/objects/0/audio_anchor_id",),
    ),
    "motion.objects": ("OBJECT_MOTION_IR", ("/shots/0/objects",)),
    "asset.materialization_state": (
        "ASSET_PLAN",
        ("/assets/0/materialization_state",),
    ),
    "asset.provenance_refs": (
        "ASSET_PLAN",
        ("/assets/0/provenance_refs",),
    ),
    "asset_plan.materialization_state": (
        "ASSET_PLAN",
        ("/assets/0/materialization_state",),
    ),
    "before_after_demo.actual_skill_output": (
        "BEFORE_AFTER_DEMO_CONTRACT",
        ("/actual_skill_output",),
    ),
    "before_after_demo.target_skill_execution_receipt_ref": (
        "BEFORE_AFTER_DEMO_CONTRACT",
        ("/target_skill_execution_receipt_ref",),
    ),
    "claim.source_refs": (
        "FUNCTION_SCENARIO_EFFECT_MATRIX",
        ("/claims/0/source_refs",),
    ),
    "target_skill_gate.side_effects_started": (
        "TARGET_SKILL_EXECUTION_GATE_RECEIPT",
        ("/side_effects_started",),
    ),
    "target_skill_gate.authorization_scope": (
        "TARGET_SKILL_EXECUTION_GATE_RECEIPT",
        ("/authorization_scope",),
    ),
    "target_skill_gate.current_input_manifest_sha256": (
        "TARGET_SKILL_EXECUTION_GATE_RECEIPT",
        ("/current_input_manifest_sha256",),
    ),
    "target_skill_gate.authorization_consumed": (
        "TARGET_SKILL_EXECUTION_GATE_RECEIPT",
        ("/authorization_consumed",),
    ),
    "render.animation_engine": (
        "LOCAL_RENDER_RECEIPT",
        ("/external_text_to_video_used",),
    ),
    "render.renderer_commit_sha": (
        "LOCAL_RENDER_RECEIPT",
        ("/renderer_commit_sha",),
    ),
    "stage_receipt.predecessor_sha256": (
        "RESUMABLE_STAGE_RECEIPT",
        ("/previous_event_hash",),
    ),
    "resume.pending_action": (
        "RESUMABLE_STAGE_RECEIPT",
        ("/attempted_idempotency_keys",),
    ),
    "authoring_handoff.workpack_started": (
        "AUTHORING_STOP_RECEIPT",
        ("/authoring_workpack_started",),
    ),
    "authoring.workpack_started": (
        "AUTHORING_STOP_RECEIPT",
        ("/authoring_workpack_started",),
    ),
    "authoring.driver_started": (
        "AUTHORING_STOP_RECEIPT",
        ("/authoring_driver_started",),
    ),
    "authoring.media_render": (
        "AUTHORING_STOP_RECEIPT",
        ("/authoring_media_rendered",),
    ),
    "authoring.model_download": (
        "AUTHORING_STOP_RECEIPT",
        ("/authoring_model_downloaded",),
    ),
}


def _negative_fixture_ref(case_id: str) -> str:
    return (
        f"{LOGICAL_CANDIDATE_ROOT}/validation/case_fixtures/"
        f"negative-{_slug(case_id).lower()}.fixture.json"
    )


def _external_mutation_pointer(target_ref: str) -> str:
    _, separator, tail = target_ref.partition(".")
    path = tail if separator else target_ref
    tokens = [
        token.replace("~", "~0").replace("/", "~1")
        for token in path.split(".")
        if token
    ]
    return "/" + "/".join(tokens or ["value"])


def _bind_negative_mutation_targets(
    fixture: dict[str, Any],
    ir: Mapping[str, Any],
    case_id: str,
) -> None:
    """Bind every conceptual mutation target to an exact future input."""

    all_atom_ids = [
        str(atom.get("atom_id"))
        for atom in ir.get("atoms", [])
        if isinstance(atom, Mapping) and atom.get("atom_id")
    ]
    all_artifacts = _case_artifact_expectations(ir, all_atom_ids)
    fixture_jobs = [
        item
        for item in fixture.get("fixture_jobs", [])
        if isinstance(item, Mapping) and item.get("job_id")
    ]
    fixture_ref = _negative_fixture_ref(case_id)

    def bind(mutation: dict[str, Any]) -> None:
        target_ref = str(mutation.get("target_ref") or "")
        artifact_target = _NEGATIVE_MUTATION_ARTIFACT_TARGETS.get(
            target_ref
        )
        if artifact_target is not None:
            artifact_kind, json_pointers = artifact_target
            matches = sorted(
                (
                    item
                    for item in all_artifacts
                    if item.get("artifact_kind") == artifact_kind
                ),
                key=lambda item: str(item.get("artifact_id") or ""),
            )
            if matches:
                mutation["target_binding"] = {
                    "resolver": "ARTIFACT_MANIFEST_SCHEMA_POINTER_V1",
                    "resource_kind": "DECLARED_ARTIFACT_SET",
                    "artifact_kind": artifact_kind,
                    "artifact_ids": [
                        str(item["artifact_id"]) for item in matches
                    ],
                    "artifact_refs": [
                        str(item["artifact_ref"]) for item in matches
                    ],
                    "job_ids": sorted(
                        {
                            str(item["job_id"])
                            for item in matches
                            if item.get("job_id")
                        }
                    ),
                    "json_pointers": list(json_pointers),
                    "application_cardinality": "EVERY_MATCHED_ARTIFACT",
                }
                return
        root, _, _ = target_ref.partition(".")
        if root == "job" and fixture_jobs:
            mutation["target_binding"] = {
                "resolver": "FIXTURE_INPUT_JSON_POINTER_V1",
                "resource_kind": "FIXTURE_JOB_SET",
                "base_input_ref": f"{fixture_ref}#/input/fixture_jobs",
                "instance_selector": {
                    "match_field": "job_id",
                    "match_values": sorted(
                        str(item["job_id"]) for item in fixture_jobs
                    ),
                    "cardinality": "EXACT_DECLARED_JOB_SET",
                },
                "json_pointers": [_external_mutation_pointer(target_ref)],
            }
            return
        mutation["target_binding"] = {
            "resolver": "EXECUTION_INPUT_JSON_POINTER_V1",
            "resource_kind": "DECLARED_EXECUTION_VALIDATION_INPUT",
            "base_input_ref": (
                f"{LOGICAL_EXECUTION_ROOT}/validation-inputs/"
                f"{_slug(root or 'fixture').lower()}.json"
            ),
            "json_pointers": [_external_mutation_pointer(target_ref)],
            "materialization_requirement": (
                "MUST_EXIST_BEFORE_MUTATION_APPLICATION"
            ),
        }

    primary = fixture.get("mutation")
    if isinstance(primary, dict):
        bind(primary)
    for variant in fixture.get("mutation_variants", []):
        mutation = variant.get("mutation") if isinstance(variant, Mapping) else None
        if isinstance(mutation, dict):
            bind(mutation)
    variants = [
        {
            "variant_id": item["variant_id"],
            "mutation": deepcopy(item["mutation"]),
        }
        for item in fixture.get("mutation_variants", [])
        if isinstance(item, Mapping)
        and item.get("variant_id")
        and isinstance(item.get("mutation"), Mapping)
    ]
    fixture["mutation_manifest"] = variants
    fixture["mutation_manifest_sha256"] = _json_hash(variants)


def _acceptance_fixture_input(
    ir: Mapping[str, Any], case: Mapping[str, Any]
) -> dict[str, Any]:
    atom_ids = [str(value) for value in case.get("atom_ids", [])]
    required_artifact_kinds = required_artifact_kinds_for_case(case)
    artifact_expectations = _case_artifact_expectations(
        ir,
        atom_ids,
        required_artifact_kinds,
    )
    if not required_artifact_kinds and artifact_expectations:
        required_artifact_kinds = sorted(
            {
                str(expectation["artifact_kind"])
                for expectation in artifact_expectations
                if expectation.get("artifact_kind")
            }
        )
    evidence_closure_policy = case.get("evidence_closure_policy")
    if evidence_closure_policy in (None, "") and required_artifact_kinds:
        evidence_closure_policy = "ALL_CASE_BOUND_ARTIFACT_KINDS_REQUIRED"
    return {
        "declared_inputs": deepcopy(list(case.get("inputs") or [])),
        "fixture_jobs": _repository_fixture_jobs(ir),
        "artifact_expectations": artifact_expectations,
        "artifact_dependency_mode": (
            "DECLARED_PRODUCTION_ARTIFACTS"
            if artifact_expectations
            else "NO_DECLARED_PRODUCTION_ARTIFACTS"
        ),
        "evidence_type": str(
            case.get("evidence_type") or "DECLARED_ACCEPTANCE_EVIDENCE"
        ),
        "one_skill_per_job": True,
        "required_artifact_kinds": required_artifact_kinds,
        "evidence_closure_policy": evidence_closure_policy,
    }


def _structured_negative_input(case: Mapping[str, Any]) -> dict[str, Any]:
    case_id = str(case.get("case_id") or "NEG-UNNAMED")
    expected_failure = str(case.get("expected_failure") or "EXPECTED_REJECTION")
    fixture = deepcopy(dict(case.get("input_fixture") or {}))
    fixture.setdefault("fixture_id", f"FIXTURE-{case_id}")
    fixture.setdefault("atom_ids", list(case.get("atom_ids") or []))
    mutation = fixture.get("mutation")
    provided_mutation = (
        deepcopy(dict(mutation))
        if (
        isinstance(mutation, Mapping)
        and mutation.get("operation") != "INJECT_DECLARED_VIOLATION"
        and not str(mutation.get("target_ref") or "").startswith(
            "validation-input://"
        )
        and isinstance(mutation.get("violated_constraint"), Mapping)
        and bool(mutation.get("violated_constraint"))
        )
        else None
    )
    mutations: dict[str, dict[str, Any]] = {
        "VIDEO_CONTRACT_REJECTED": {
            "operation": "SET_FIELD",
            "target_ref": "job.input_skill_count",
            "invalid_value": 2,
            "violated_constraint": {"const": 1},
        },
        "CONTENT_EVIDENCE_MISMATCH": {
            "operation": "REMOVE_CONDITIONALLY_REQUIRED_FIELD",
            "target_ref": (
                "before_after_demo.target_skill_execution_receipt_ref"
            ),
            "invalid_value": None,
            "violated_constraint": {
                "when": {
                    "provenance_state": "AUTHORIZED_TARGET_SKILL_RUN"
                },
                "required": "target_skill_execution_receipt_ref",
            },
        },
        "MOTION_SYNC_TOLERANCE_EXCEEDED": {
            "operation": "SET_OUT_OF_RANGE_VALUE",
            "target_ref": "alignment.max_anchor_error_seconds",
            "invalid_value": 0.101,
            "violated_constraint": {"maximum": 0.1},
        },
        "ASSET_OR_RENDER_AUTHORITY_REJECTED": {
            "operation": "SET_FIELD",
            "target_ref": "asset_plan.materialization_state",
            "invalid_value": "CODEX_IMAGEGEN_AUTHORIZED_MATERIALIZED",
            "violated_constraint": {
                "requires_non_null": [
                    "generation_authorization_ref",
                    "generation_receipt_ref",
                    "asset_sha256",
                ],
                "provided": None,
            },
        },
        "TARGET_SKILL_EXECUTION_DISABLED": {
            "operation": "SET_FIELD",
            "target_ref": "target_skill_gate.side_effects_started",
            "invalid_value": True,
            "violated_constraint": {
                "when_status": "DENIED_NO_SIDE_EFFECT",
                "const": False,
            },
        },
        "AUTHORING_STOP": {
            "operation": "SET_FIELD",
            "target_ref": "authoring_handoff.workpack_started",
            "invalid_value": True,
            "violated_constraint": {"const": False},
        },
        "INVOCATION_UNVERIFIED": {
            "operation": "SET_FIELD",
            "target_ref": "runtime_receipt.invocation_verified",
            "invalid_value": False,
            "violated_constraint": {"const": True},
        },
        "ATTESTATION_REPLAY_REJECTED": {
            "operation": "REPLAY_ATTESTATION",
            "target_ref": "runtime_attestation.challenge_nonce",
            "invalid_value": "previously_consumed_nonce",
            "violated_constraint": {"fresh_and_single_use": True},
        },
        "OUTPUT_SUBSTITUTION_DETECTED": {
            "operation": "SUBSTITUTE_OUTPUT",
            "target_ref": "runtime_receipt.output_sha256",
            "invalid_value": "1" * 64,
            "violated_constraint": {"expected_sha256": "2" * 64},
        },
        "EXECUTOR_IDENTITY_UNTRUSTED": {
            "operation": "REPLACE_EXECUTOR",
            "target_ref": "runtime_receipt.executor_identity",
            "invalid_value": "STUB_EXECUTOR",
            "violated_constraint": {"allowed": ["PINNED_CODEX_RUNTIME"]},
        },
        "ILLEGAL_PHASE_TRANSITION": {
            "operation": "SET_ORDER",
            "target_ref": "phase_transition",
            "invalid_value": ["P2", "P4"],
            "violated_constraint": {"required_predecessor": "P3"},
        },
        "STALE_PREDECESSOR_HASH": {
            "operation": "REPLACE_HASH",
            "target_ref": "stage_receipt.predecessor_sha256",
            "invalid_value": "0" * 64,
            "violated_constraint": {"must_equal_current_predecessor": True},
        },
        "STAGE_RECEIPT_MISSING": {
            "operation": "OMIT_STAGE_RECEIPT",
            "target_ref": "release.required_stage_receipts.P2",
            "invalid_value": None,
            "violated_constraint": {"required": "P2"},
        },
        "RUNTIME_ENTRYPOINT_FALLBACK_REJECTED": {
            "operation": "SET_FIELD",
            "target_ref": "runtime.entrypoint_class",
            "invalid_value": "BUILD_PROGRAM_DRIVER",
            "violated_constraint": {"const": "INSTALLED_HARNESS_RUNTIME"},
        },
        "CERTIFICATE_INVALIDATED": {
            "operation": "REPLACE_HASH",
            "target_ref": "certificate.candidate_sha256",
            "invalid_value": "3" * 64,
            "violated_constraint": {"current_candidate_sha256": "4" * 64},
        },
        "AUTHORIZATION_INVALID": {
            "operation": "REMOVE_AUTHORIZATION",
            "target_ref": "action.authorization_ref",
            "invalid_value": None,
            "violated_constraint": {"authorization_status": "GRANTED_CURRENT"},
        },
        "STATE_CONFLICT": {
            "operation": "ADD_ACTIVE_LEASE",
            "target_ref": "control_state.active_next_actions",
            "invalid_value": ["ACTION-A", "ACTION-B"],
            "violated_constraint": {"maxItems": 1},
        },
        "RELEASE_PREDECESSOR_MISSING": {
            "operation": "SET_ORDER",
            "target_ref": "release.completed_steps",
            "invalid_value": ["A", "C4"],
            "violated_constraint": {
                "required_order": ["A", "B0", "C", "B1", "D", "C4"]
            },
        },
        "LOOP_ESCALATION_REQUIRED": {
            "operation": "SET_OUT_OF_RANGE_VALUE",
            "target_ref": "repair_loop.no_progress_count",
            "invalid_value": 4,
            "violated_constraint": {"maximum_before_escalation": 3},
        },
        "DUPLICATE_SIDE_EFFECT_REJECTED": {
            "operation": "DUPLICATE_SIDE_EFFECT",
            "target_ref": "resume.pending_action",
            "invalid_value": "REEXECUTE_ALREADY_COMMITTED_SIDE_EFFECT",
            "violated_constraint": {"at_most_once": True},
        },
        "DEPENDENT_STATE_INVALIDATED": {
            "operation": "INVALIDATE_UPSTREAM",
            "target_ref": "dependency.upstream_sha256",
            "invalid_value": "5" * 64,
            "violated_constraint": {"dependent_status_after_change": "INVALID"},
        },
        "REAL_TARGET_INSTALL_AUTHORIZATION_REQUIRED": {
            "operation": "REQUEST_FORBIDDEN_ACTION",
            "target_ref": "install.real_target",
            "invalid_value": {"requested": True, "authorization_ref": None},
            "violated_constraint": {
                "requires": "REAL_TARGET_INSTALL_AUTHORIZATION"
            },
        },
        "ENGINEERING_PREDECESSOR_MISSING": {
            "operation": "SET_ORDER",
            "target_ref": "engineering_projects.release_order",
            "invalid_value": ["MAIN", "LINKAGE", "LAB"],
            "violated_constraint": {
                "required_order": ["LAB", "LINKAGE", "MAIN"]
            },
        },
        "STATE_CONFLICT_HARD_STOP": {
            "operation": "ADD_ACTIVE_LEASE",
            "target_ref": "program.active_workpacks",
            "invalid_value": ["LAB-CERTIFICATION", "MB-P3"],
            "violated_constraint": {"maxItems": 1},
        },
        "CANDIDATE_HASH_MISMATCH": {
            "operation": "REPLACE_HASH",
            "target_ref": "lab.candidate_sha256",
            "invalid_value": "6" * 64,
            "violated_constraint": {"p4_candidate_sha256": "7" * 64},
        },
        "TOOL_DISTRIBUTION_HASH_CHANGED": {
            "operation": "CHANGE_LOCKED_HASH",
            "target_ref": "lab.tool_distribution_sha256",
            "invalid_value": "8" * 64,
            "violated_constraint": {"attempt_locked_sha256": "9" * 64},
        },
        "AUTHORITY_MISMATCH": {
            "operation": "REQUEST_FORBIDDEN_ACTION",
            "target_ref": "linkage.requested_authority",
            "invalid_value": ["MODIFY_REVIEWED_ASSET", "ISSUE_CERTIFICATE"],
            "violated_constraint": {"allowed": ["READ_ONLY_LINKAGE_REVIEW"]},
        },
    }
    selected = deepcopy(
        mutations.get(
            expected_failure,
            {
                "operation": "SET_FIELD",
                "target_ref": "fixture.declared_validity",
                "invalid_value": False,
                "violated_constraint": {"const": True},
            },
        )
    )
    if provided_mutation is not None:
        selected = provided_mutation
    selected["expected_failure"] = expected_failure
    fixture["mutation"] = selected
    def variant(
        variant_id: str,
        operation: str,
        target_ref: str,
        invalid_value: Any,
        violated_constraint: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "variant_id": variant_id,
            "mutation": {
                "operation": operation,
                "target_ref": target_ref,
                "invalid_value": deepcopy(invalid_value),
                "violated_constraint": deepcopy(dict(violated_constraint)),
                "expected_failure": expected_failure,
            },
        }

    case_variants: dict[str, list[dict[str, Any]]] = {
        "NEG-MULTI-SKILL-OR-DURATION-DRIFT": [
            variant("MULTI-SKILL", "SET_FIELD", "job.input_skill_count", 2, {"const": 1}),
            variant("DURATION-DRIFT", "SET_OUT_OF_RANGE_VALUE", "video.duration_seconds", 186, {"minimum": 175, "maximum": 185}),
            variant("WRONG-CANVAS-OR-FPS", "SET_FIELD", "video.format", {"width": 1280, "height": 720, "fps": 24}, {"const": {"width": 1920, "height": 1080, "fps": 30}}),
            variant("FORCED-NARRATION-SPEED", "SET_FIELD", "narration.playback_speed", 1.5, {"const": 1.0}),
        ],
        "NEG-UNSUPPORTED-EFFECT-OR-FAKE-DEMO": [
            variant("UNSUPPORTED-EFFECT", "SET_FIELD", "claim.source_refs", [], {"minItems": 1}),
            variant("ILLUSTRATION-LABELED-ACTUAL", "SET_FIELD", "before_after_demo.actual_skill_output", True, {"when": {"provenance_state": "CLEARLY_LABELED_ILLUSTRATION"}, "const": False}),
        ],
        "NEG-CLOUD-TTS-OR-APPROXIMATE-SYNC": [
            variant("CLOUD-TTS", "SET_FIELD", "tts.execution_mode", "CLOUD", {"const": "LOCAL_OFFLINE"}),
            variant("MISSING-FORCED-ALIGNMENT", "SET_FIELD", "alignment.word_anchors", [], {"minItems": 1}),
            variant("SCENE-ONLY-APPROXIMATE-TIMING", "REMOVE_REQUIRED_FIELD", "motion.binding_granularity", None, {"required": "shots[].objects[].audio_anchor_id"}),
            variant("INCOMPLETE-OBJECT-SET", "SET_FIELD", "motion.objects", [], {"minItems": 1}),
            variant("TIMING-TOLERANCE-EXCEEDED", "SET_OUT_OF_RANGE_VALUE", "alignment.max_anchor_error_seconds", 0.101, {"maximum": 0.1}),
        ],
        "NEG-UNROUTED-ASSET-OR-EXTERNAL-ANIMATION": [
            variant("OBJECT-WITHOUT-PROVENANCE", "SET_FIELD", "asset.provenance_refs", [], {"minItems": 1}),
            variant("UNAUTHORIZED-CODEX-IMAGEGEN", "SET_FIELD", "asset.materialization_state", "CODEX_IMAGEGEN_AUTHORIZED_MATERIALIZED", {"requires_non_null": ["generation_authorization_ref", "generation_receipt_ref", "generation_receipt_sha256", "asset_ref", "asset_sha256"]}),
            variant("EXTERNAL-TEXT-TO-VIDEO", "SET_FIELD", "render.animation_engine", True, {"field": "external_text_to_video_used", "const": False}),
            variant("UNPINNED-SHOTCRAFT", "REMOVE_REQUIRED_FIELD", "render.renderer_commit_sha", None, {"required": "renderer_commit_sha"}),
        ],
        "NEG-UNAUTHORIZED-TARGET-EXECUTION-OR-FALSE-RESUME": [
            variant("DENIED-GATE-SIDE-EFFECT", "SET_FIELD", "target_skill_gate.side_effects_started", True, {"when_status": "DENIED_NO_SIDE_EFFECT", "const": False}),
            variant("PROGRAM-WIDE-AUTHORIZATION-SUBSTITUTION", "SET_FIELD", "target_skill_gate.authorization_scope", "PROGRAM_WIDE", {"const": "EXACT_JOB_COMMIT_AND_INPUT_MANIFEST"}),
            variant("STALE-AUTHORIZATION-OR-INPUT-HASH", "REPLACE_HASH", "target_skill_gate.current_input_manifest_sha256", "a" * 64, {"must_equal": "target_skill_gate.authorized_input_manifest_sha256", "authorization_freshness": "CURRENT"}),
            variant("CONSUMED-AUTHORIZATION-REPLAY", "REPLAY_ATTESTATION", "target_skill_gate.authorization_consumed", True, {"single_use": True}),
            variant("FALSE-RESUME-SIDE-EFFECT-REPLAY", "DUPLICATE_SIDE_EFFECT", "resume.pending_action", "REEXECUTE_ALREADY_COMMITTED_SIDE_EFFECT", {"at_most_once": True}),
        ],
        "NEG-FIXTURE-NARRATIVE-PASS-OR-AUTHORING-EXECUTION": [
            variant("MISSING-FIXTURE-EVIDENCE", "REMOVE_REQUIRED_FIELD", "fixture.evidence_refs", None, {"required": "evidence_refs"}),
            variant("NARRATIVE-PASS", "SET_FIELD", "fixture.result_basis", "NARRATIVE_SELF_REPORT", {"allowed": ["HASH_BOUND_EXECUTION_EVIDENCE"]}),
            variant("DEPENDENCY-INSTALL", "REQUEST_FORBIDDEN_ACTION", "authoring.dependency_install", True, {"const": False}),
            variant("MODEL-DOWNLOAD", "REQUEST_FORBIDDEN_ACTION", "authoring.model_download", True, {"const": False}),
            variant("MEDIA-RENDER", "REQUEST_FORBIDDEN_ACTION", "authoring.media_render", True, {"const": False}),
            variant("WORKPACK-START", "REQUEST_FORBIDDEN_ACTION", "authoring.workpack_started", True, {"const": False}),
            variant("DRIVER-START", "REQUEST_FORBIDDEN_ACTION", "authoring.driver_started", True, {"const": False}),
            variant("EXECUTION-ROOT-CREATE", "REQUEST_FORBIDDEN_ACTION", "authoring.execution_root_created", True, {"const": False}),
        ],
        "NEG-HF28-B0-B1-ORDER": [
            variant(
                "B0-PREFILLED-ARTIFACT-HASH",
                "SET_FIELD",
                "release.steps.LINKAGE_B0_NORMATIVE_BINDING.artifact_sha256",
                "0" * 64,
                {
                    "must_be_absent_before": "IMMUTABLE_ARTIFACT_BUILD",
                    "bound_by": "LINKAGE_B1_ARTIFACT_BINDING",
                },
            ),
            variant(
                "B1-BEFORE-IMMUTABLE-ARTIFACT-BUILD",
                "SET_ORDER",
                "release.completed_steps",
                [
                    "P4_BUILD_INPUT_LOCK",
                    "PACK_DRAFT",
                    "LINKAGE_A_INTERFACE_COMPLETENESS",
                    "LINKAGE_B0_NORMATIVE_BINDING",
                    "LINKAGE_C_EVIDENCE_COMPATIBILITY",
                    "LINKAGE_B1_ARTIFACT_BINDING",
                    "IMMUTABLE_ARTIFACT_BUILD",
                ],
                {
                    "required_order": [
                        "P4_BUILD_INPUT_LOCK",
                        "PACK_DRAFT",
                        "LINKAGE_A_INTERFACE_COMPLETENESS",
                        "LINKAGE_B0_NORMATIVE_BINDING",
                        "LINKAGE_C_EVIDENCE_COMPATIBILITY",
                        "IMMUTABLE_ARTIFACT_BUILD",
                        "LINKAGE_B1_ARTIFACT_BINDING",
                    ]
                },
            ),
        ],
    }
    variants = case_variants.get(
        case_id,
        [
            {
                "variant_id": f"{case_id}-PRIMARY-MUTATION",
                "mutation": deepcopy(selected),
            }
        ],
    )
    fixture["mutation_variants"] = variants
    mutation_manifest = [
        {
            "variant_id": item["variant_id"],
            "mutation": deepcopy(item["mutation"]),
        }
        for item in variants
    ]
    fixture["mutation_manifest"] = mutation_manifest
    fixture["mutation_manifest_sha256"] = _json_hash(mutation_manifest)
    return fixture


def _case_oracle_bindings(
    fixture_input: Mapping[str, Any], assertions: list[Mapping[str, Any]]
) -> dict[str, Any]:
    assertion_manifest = [
        {
            "assertion_id": str(item.get("assertion_id") or ""),
            "operator": str(item.get("operator") or ""),
            "expected": deepcopy(item.get("expected")),
        }
        for item in assertions
    ]
    artifact_manifest = deepcopy(
        list(fixture_input.get("artifact_expectations") or [])
    )
    source_job_manifest = [
        {
            field: item[field]
            for field in ("job_id", "source_id", "repository_url", "commit_sha")
        }
        for item in fixture_input.get("fixture_jobs", [])
        if isinstance(item, Mapping)
        and all(
            field in item
            for field in ("job_id", "source_id", "repository_url", "commit_sha")
        )
    ]
    mutation_manifest = deepcopy(
        list(fixture_input.get("mutation_manifest") or [])
    )
    return {
        "evaluator_id": "EXACT_CASE_SET_ORACLE_V1",
        "evaluator_registry_ref": ORACLE_EVALUATOR_REGISTRY_REF,
        "assertion_manifest": assertion_manifest,
        "assertion_manifest_sha256": _json_hash(assertion_manifest),
        "artifact_manifest": artifact_manifest,
        "artifact_manifest_sha256": _json_hash(artifact_manifest),
        "source_job_manifest": source_job_manifest,
        "source_job_manifest_sha256": _json_hash(source_job_manifest),
        "mutation_manifest": mutation_manifest,
        "mutation_manifest_sha256": _json_hash(mutation_manifest),
        "set_equality_required": True,
    }


def _case_aggregation_receipt_schema(
    *,
    schema_id: str,
    case_id: str,
    case_kind: str,
    fragment_manifest_ref: str,
    fragment_refs: Sequence[str],
    result_ref: str,
) -> dict[str, Any]:
    """Bind one Case aggregate receipt to the exact partition fragments."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        "type": "object",
        "additionalProperties": False,
        "required": [
            "case_id",
            "case_kind",
            "fragment_manifest_ref",
            "fragment_manifest_sha256",
            "fragment_refs",
            "fragment_sha256s",
            "result_ref",
            "aggregation_command_receipt_ref",
            "aggregation_command_receipt_sha256",
            "status",
        ],
        "properties": {
            "case_id": {"const": case_id},
            "case_kind": {"const": case_kind},
            "fragment_manifest_ref": {"const": fragment_manifest_ref},
            "fragment_manifest_sha256": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
            "fragment_refs": {"const": list(fragment_refs)},
            "fragment_sha256s": {
                "type": "array",
                "minItems": len(fragment_refs),
                "maxItems": len(fragment_refs),
                "items": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            },
            "result_ref": {"const": result_ref},
            "aggregation_command_receipt_ref": {
                "type": "string",
                "minLength": 1,
            },
            "aggregation_command_receipt_sha256": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
            "status": {"const": "PASS"},
        },
        "x-ref-sha256-bindings": [
            {
                "ref_pointer": "/fragment_manifest_ref",
                "sha256_pointer": "/fragment_manifest_sha256",
                "pairing": "SINGLE",
            },
            {
                "ref_pointer": "/fragment_refs/*",
                "sha256_pointer": "/fragment_sha256s/*",
                "pairing": "SAME_INDEX_EXACT_CARDINALITY",
            },
            {
                "ref_pointer": "/aggregation_command_receipt_ref",
                "sha256_pointer": "/aggregation_command_receipt_sha256",
                "pairing": "SINGLE",
            },
        ],
        "x-byte-lineage-evaluator": {
            "evaluator_id": "CASE_AGGREGATION_REF_SHA256_LINEAGE_V1",
            "implementation_entrypoint": (
                "external_lab.oracle:verify_ref_sha256_bindings_v1"
            ),
            "algorithm_version": "1.0",
            "hash_algorithm": "SHA-256",
            "byte_mode": "EXACT_REFERENCED_BYTES_NO_REENCODING",
            "unknown_or_unresolved_ref_disposition": "FAIL_CLOSED",
            "failure_code": "CASE_AGGREGATION_BYTE_LINEAGE_MISMATCH",
        },
        "x-invariants": [
            "FRAGMENT_REFS_AND_SHA256S_HAVE_EQUAL_CARDINALITY",
            "EVERY_FRAGMENT_SHA256_MATCHES_REFERENCED_BYTES",
            "FRAGMENT_MANIFEST_SHA256_MATCHES_REFERENCED_BYTES",
            "AGGREGATION_COMMAND_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES",
        ],
    }


def _specialize_case_result_schema(
    base_schema: Mapping[str, Any],
    *,
    schema_id: str,
    case_id: str,
    case_kind: str,
    fixture_sha256: str,
    oracle_bindings: Mapping[str, Any],
    job_read_partitions: Sequence[Mapping[str, Any]],
    expected_failure: str | None,
) -> dict[str, Any]:
    schema = deepcopy(dict(base_schema))
    schema["$id"] = schema_id
    properties = schema["properties"]
    properties["case_id"] = {"const": case_id}
    properties["case_kind"] = {"const": case_kind}
    properties["fixture_sha256"] = {"const": fixture_sha256}
    properties["assertion_manifest_sha256"] = {
        "const": oracle_bindings["assertion_manifest_sha256"]
    }
    assertion_manifest = list(oracle_bindings["assertion_manifest"])
    assertion_results = properties["assertion_results"]
    assertion_results.update(
        {
            "minItems": len(assertion_manifest),
            "maxItems": len(assertion_manifest),
            "uniqueItems": True,
            "allOf": [
                {
                    "contains": {
                        "type": "object",
                        "properties": {
                            "assertion_id": {"const": item["assertion_id"]},
                            "operator": {"const": item["operator"]},
                            "expected": {"const": item["expected"]},
                        },
                        "required": ["assertion_id", "operator", "expected"],
                    },
                    "minContains": 1,
                    "maxContains": 1,
                }
                for item in assertion_manifest
            ],
        }
    )
    partition_manifest = [dict(item) for item in job_read_partitions]
    properties["job_partition_manifest_sha256"] = {
        "const": _json_hash(partition_manifest)
    }
    properties["aggregation_receipt_ref"] = {
        "const": (
            f"{CASE_EXECUTION_RESULT_ROOT_REF}/aggregation/"
            f"{case_kind.lower()}-{_slug(case_id).lower()}.receipt.json"
        )
    }
    partition_results = properties["job_partition_results"]
    partition_results.update(
        {
            "minItems": len(partition_manifest),
            "maxItems": len(partition_manifest),
            "uniqueItems": True,
            "allOf": [
                {
                    "contains": {
                        "type": "object",
                        "properties": {
                            "job_id": {"const": item["job_id"]},
                            "lease_receipt_ref": {
                                "const": item["lease_receipt_ref"]
                            },
                            "result_fragment_ref": {
                                "const": item["result_fragment_ref"]
                            },
                            "fragment_artifact_manifest_ref": {
                                "const": item[
                                    "fragment_artifact_manifest_ref"
                                ]
                            },
                        },
                        "required": [
                            "job_id",
                            "lease_receipt_ref",
                            "result_fragment_ref",
                            "fragment_artifact_manifest_ref",
                        ],
                    },
                    "minContains": 1,
                    "maxContains": 1,
                }
                for item in partition_manifest
            ],
        }
    )
    if case_kind == "ACCEPTANCE":
        for field in (
            "artifact_checks",
            "artifact_manifest_sha256",
            "source_job_bindings",
            "source_job_manifest_sha256",
        ):
            if field not in schema["required"]:
                schema["required"].append(field)
        artifact_manifest = list(oracle_bindings["artifact_manifest"])
        properties["artifact_manifest_sha256"] = {
            "const": oracle_bindings["artifact_manifest_sha256"]
        }
        artifact_checks = properties["artifact_checks"]
        artifact_checks.update(
            {
                "minItems": len(artifact_manifest),
                "maxItems": len(artifact_manifest),
                "uniqueItems": True,
                "allOf": [
                    {
                        "contains": {
                            "type": "object",
                            "properties": {
                                "artifact_id": {"const": item["artifact_id"]},
                                "job_id": {"const": item.get("job_id")},
                                "source_id": {"const": item.get("source_id")},
                                "artifact_ref": {"const": item["artifact_ref"]},
                                "schema_sha256": {
                                    "const": item["schema_sha256"]
                                },
                            },
                            "required": [
                                "artifact_id",
                                "job_id",
                                "source_id",
                                "artifact_ref",
                                "schema_sha256",
                            ],
                        },
                        "minContains": 1,
                        "maxContains": 1,
                    }
                    for item in artifact_manifest
                ],
            }
        )
        source_manifest = list(oracle_bindings["source_job_manifest"])
        properties["source_job_manifest_sha256"] = {
            "const": oracle_bindings["source_job_manifest_sha256"]
        }
        source_jobs = properties["source_job_bindings"]
        source_jobs.update(
            {
                "minItems": len(source_manifest),
                "maxItems": len(source_manifest),
                "uniqueItems": True,
                "allOf": [
                    {
                        "contains": {
                            "type": "object",
                            "properties": {
                                field: {"const": item[field]}
                                for field in (
                                    "job_id",
                                    "source_id",
                                    "repository_url",
                                    "commit_sha",
                                )
                            },
                            "required": [
                                "job_id",
                                "source_id",
                                "repository_url",
                                "commit_sha",
                            ],
                        },
                        "minContains": 1,
                        "maxContains": 1,
                    }
                    for item in source_manifest
                ],
            }
        )
    else:
        for field in (
            "observed_failure_code",
            "expected_failure_observed",
            "artifact_manifest_sha256",
            "source_job_manifest_sha256",
            "mutation_manifest_sha256",
            "mutation_variant_results",
            "side_effect_receipt_ref",
            "side_effect_receipt_sha256",
            "side_effects_started",
        ):
            if field not in schema["required"]:
                schema["required"].append(field)
        properties["observed_failure_code"] = {
            "const": str(expected_failure or "EXPECTED_REJECTION")
        }
        properties["expected_failure_observed"] = {"const": True}
        properties["side_effects_started"] = {"const": False}
        properties["artifact_manifest_sha256"] = {
            "const": oracle_bindings["artifact_manifest_sha256"]
        }
        properties["source_job_manifest_sha256"] = {
            "const": oracle_bindings["source_job_manifest_sha256"]
        }
        properties["mutation_manifest_sha256"] = {
            "const": oracle_bindings["mutation_manifest_sha256"]
        }
        mutation_manifest = list(oracle_bindings["mutation_manifest"])
        variant_results = properties["mutation_variant_results"]
        variant_results.update(
            {
                "minItems": len(mutation_manifest),
                "maxItems": len(mutation_manifest),
                "allOf": [
                    {
                        "contains": {
                            "type": "object",
                            "properties": {
                                "variant_id": {"const": item["variant_id"]},
                                "observed_failure_code": {
                                    "const": str(
                                        expected_failure or "EXPECTED_REJECTION"
                                    )
                                },
                            },
                            "required": [
                                "variant_id",
                                "observed_failure_code",
                            ],
                        },
                        "minContains": 1,
                        "maxContains": 1,
                    }
                    for item in mutation_manifest
                ],
            }
        )
    return schema


def _mandatory_negative_cases(ir: Mapping[str, Any]) -> list[dict[str, Any]]:
    atom_ids = [
        str(item.get("atom_id"))
        for item in ir.get("atoms", [])
        if isinstance(item, Mapping) and item.get("atom_id")
    ]
    cases = negative_case_specs_with_mandatory_controls(ir)
    for case in cases:
        case_id = str(case.get("case_id") or "NEG-UNNAMED")
        atom_ids_for_case = list(case.get("atom_ids") or atom_ids)
        case.setdefault("fixture_kind", "NON_EXECUTABLE_JSON")
        case.setdefault("atom_ids", atom_ids_for_case)
        fixture = _structured_negative_input(case)
        fixture["artifact_expectations"] = _case_artifact_expectations(
            ir, [str(value) for value in case.get("atom_ids", [])]
        )
        fixture["artifact_dependency_mode"] = (
            "DECLARED_PRODUCTION_ARTIFACTS"
            if fixture["artifact_expectations"]
            else "NO_DECLARED_PRODUCTION_ARTIFACTS"
        )
        fixture["fixture_jobs"] = _repository_fixture_jobs(ir)
        _bind_negative_mutation_targets(fixture, ir, case_id)
        case["input_fixture"] = fixture
        case.setdefault(
            "preconditions",
            [
                "Candidate hashes and frozen Requirement bindings are current",
                "No execution authorization is granted by this fixture",
            ],
        )
        case.setdefault(
            "steps",
            [
                {
                    "step_id": f"{case_id}-S1",
                    "action": "SUBMIT_NONEXECUTABLE_FIXTURE_TO_DECLARED_VALIDATOR",
                },
                {
                    "step_id": f"{case_id}-S2",
                    "action": "COMPARE_REJECTION_CODE_AND_SIDE_EFFECT_RECEIPT",
                },
            ],
        )
        case.setdefault(
            "assertions",
            [
                {
                    "assertion_id": f"ASSERT-{case_id}-REJECTED",
                    "operator": "EQUALS",
                    "actual_ref": "validator.finding.code",
                    "expected": case["expected_failure"],
                },
                {
                    "assertion_id": f"ASSERT-{case_id}-NO-SIDE-EFFECT",
                    "operator": "EQUALS",
                    "actual_ref": "receipt.side_effects_started",
                    "expected": False,
                },
            ],
        )
        case.setdefault(
            "oracle_contract",
            {
                "oracle_id": f"ORACLE-{case_id}",
                "owner": "INDEPENDENT_VALIDATOR",
                "decision_rule": (
                    "PASS_ONLY_WHEN_EXPECTED_REJECTION_AND_ZERO_SIDE_EFFECTS_ARE_OBSERVED"
                ),
                "evidence_required": [
                    "BASE_AND_MUTATED_INPUT_HASHES",
                    "MUTATION_RECEIPT",
                    "COMMAND_RECEIPT",
                    "VALIDATOR_FINDING",
                    "SIDE_EFFECT_BOUNDARY_RECEIPT",
                ],
                "common_mode_exclusions": [
                    "TARGET_SELF_REPORT_IS_NOT_ORACLE_EVIDENCE",
                    "FIXTURE_DESCRIPTION_IS_NOT_EXECUTION_EVIDENCE",
                ],
            },
        )
    return cases


def _compile_acceptance_cases(ir: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Compile prose acceptance rows into reviewable executable contracts."""

    cases: list[dict[str, Any]] = []
    for index, raw in enumerate(ir.get("acceptance_cases", []), 1):
        if not isinstance(raw, Mapping):
            continue
        case = deepcopy(dict(raw))
        case_id = str(case.get("case_id") or f"AC-{index:03d}")
        atom_ids = list(case.get("atom_ids") or [])
        evidence_type = str(
            case.get("evidence_type") or "DECLARED_ACCEPTANCE_EVIDENCE"
        )
        case.update(
            {
                "case_id": case_id,
                "inputs": case.get("inputs")
                or [
                    {
                        "input_id": f"INPUT-{case_id}-FROZEN-ATOMS",
                        "kind": "FROZEN_REQUIREMENT_ATOM_SET",
                        "atom_ids": atom_ids,
                    }
                ],
                "preconditions": case.get("preconditions")
                or [
                    "Exact source and Requirement hashes are current",
                    "Required runtime authorization is supplied only at execution time",
                    "Candidate authoring itself starts no command",
                ],
                "steps": case.get("steps")
                or [
                    {
                        "step_id": f"{case_id}-S1",
                        "action": "MATERIALIZE_DECLARED_INPUT_FIXTURE_IN_EXECUTION_ROOT",
                    },
                    {
                        "step_id": f"{case_id}-S2",
                        "action": "RUN_HASH_BOUND_TARGET_VALIDATION_INTERFACE",
                    },
                    {
                        "step_id": f"{case_id}-S3",
                        "action": "COLLECT_AND_PROBE_REQUIRED_EVIDENCE",
                    },
                ],
                "assertions": case.get("assertions")
                or [
                    {
                        "assertion_id": f"ASSERT-{case_id}-EVIDENCE",
                        "operator": "VALIDATED_RECEIPT_EXISTS",
                        "actual_ref": f"evidence/{case_id}.result.json",
                        "expected": evidence_type,
                    },
                    {
                        "assertion_id": f"ASSERT-{case_id}-ATOM-COVERAGE",
                        "operator": "SET_EQUALS",
                        "actual_ref": "receipt.verified_atom_ids",
                        "expected": atom_ids,
                    },
                ],
                "oracle_contract": case.get("oracle_contract")
                or {
                    "oracle_id": f"ORACLE-{case_id}",
                    "owner": "INDEPENDENT_VALIDATOR",
                    "decision_rule": (
                        "PASS_ONLY_WHEN_EVERY_ASSERTION_PASSES_AND_EVIDENCE_HASHES_MATCH"
                    ),
                    "evidence_required": [evidence_type],
                    "common_mode_exclusions": [
                        "TARGET_SELF_REPORT_IS_NOT_ORACLE_EVIDENCE",
                        "SCHEMA_VALIDITY_ALONE_IS_NOT_BEHAVIORAL_PROOF",
                    ],
                },
                "status": "PLANNED_NOT_RUN",
            }
        )
        cases.append(case)
    return cases


def _external_lab_case_command_contracts(
    *,
    executable: str,
    repository_root: str,
    candidate_root: str,
    execution_root: str,
) -> list[dict[str, Any]]:
    """Return the owned parameterized interfaces for every Lab Case lane."""

    result_root = f"{execution_root}/evidence/cases"
    contracts: list[dict[str, Any]] = []
    for command_id, subcommand, case_kinds, required_flags, read_result_root in (
        (
            "LAB-RUN-ACCEPTANCE-CASE",
            "run-acceptance-case",
            ["ACCEPTANCE"],
            ["--fixture-ref", "--result-ref"],
            True,
        ),
        (
            "LAB-RUN-NEGATIVE-CASE",
            "run-negative-case",
            ["NEGATIVE"],
            ["--fixture-ref", "--result-ref"],
            True,
        ),
        (
            "LAB-RUN-REGISTRY-CASE",
            "run-registry-case",
            ["INVARIANT", "SCHEMA_NATIVE"],
            ["--fixture-ref", "--result-ref", "--read-plan-ref"],
            False,
        ),
        (
            "LAB-RUN-CASE-PARTITION",
            "run-case-partition",
            ["ACCEPTANCE", "NEGATIVE"],
            [
                "--fixture-ref",
                "--job-id",
                "--lease-receipt-ref",
                "--result-fragment-ref",
                "--fragment-artifact-manifest-ref",
            ],
            False,
        ),
        (
            "LAB-AGGREGATE-CASE-PARTITIONS",
            "aggregate-case-partitions",
            ["ACCEPTANCE", "NEGATIVE"],
            [
                "--fixture-ref",
                "--fragment-manifest-ref",
                "--aggregation-receipt-ref",
                "--aggregation-receipt-schema-ref",
                "--result-ref",
            ],
            True,
        ),
        (
            "LAB-RUN-METAMORPHIC-CASE",
            "run-metamorphic-case",
            ["METAMORPHIC"],
            ["--fixture-ref", "--resolution-receipt-ref", "--result-ref"],
            False,
        ),
        (
            "LAB-EVALUATE-CASE-ORACLE",
            "evaluate-case-oracle",
            [
                "ACCEPTANCE",
                "NEGATIVE",
                "INVARIANT",
                "SCHEMA_NATIVE",
                "METAMORPHIC",
            ],
            ["--fixture-ref", "--result-ref"],
            True,
        ),
    ):
        command = {
            "command_id": command_id,
            "command_kind": "PARAMETERIZED_CASE_EXECUTION_INTERFACE",
            "executor_role": "EXTERNAL_CONFORMANCE_LAB_CASE_RUNNER",
            "owner_workpack_id": CASE_EVIDENCE_WRITER_WORKPACK_ID,
            "executable": executable,
            "executable_abs": executable,
            "executable_status": "PLANNED_NOT_INSTALLED",
            "argv": [executable, "-m", "external_lab", subcommand],
            "parameter_contract": {
                "required_flags": required_flags,
                "fixture_ref_contract": {
                    "scheme": "harness-resource",
                    "authority": "candidate",
                    "path_prefix": "validation/",
                },
                "result_ref_root": result_root,
                "case_kinds": case_kinds,
                "undeclared_parameters_forbidden": True,
            },
            "result_writer_contract": {
                "writer_workpack_id": CASE_EVIDENCE_WRITER_WORKPACK_ID,
                "writer_cardinality": "EXACTLY_ONE_WORKPACK",
                "result_root_ref": result_root,
                "atomic_write_required": True,
            },
            "invocation_contract_status": (
                "REQUIRES_EXTERNAL_LAB_CLI_SCHEMA_PREFLIGHT_AND_EXECUTION_"
                "AUTHORIZATION"
            ),
            "unverified_cli_flags_forbidden": True,
            "cwd_absolute": repository_root,
            "authorization_ref": None,
            "preflight_gate": (
                "LAB_SELFTEST_P4_RELEASE_LINKAGE_AND_INSTALL_GATES_VALID"
            ),
            "allowed_modes": ["LAB_CERTIFICATION"],
            "expected_exit_codes": [0, 2],
            "stdout_stderr_evidence_required": True,
            "allowed_read_roots": [
                candidate_root,
                *([result_root] if read_result_root else []),
            ],
            "allowed_write_roots": [result_root],
            "auto_execute": False,
            "shell": False,
        }
        if command_id == "LAB-RUN-METAMORPHIC-CASE":
            command["implementation_entrypoint"] = (
                PUBLIC_SKILL_JOB_PIPELINE_ENTRYPOINT
            )
            command["job_pipeline_contract"] = {
                "source_resolution_entrypoint": PUBLIC_SKILL_SOURCE_RESOLUTION_ENTRYPOINT,
                "specialization_ref": f"{PUBLIC_SKILL_JOB_INTERFACE_REF}#/dynamic_specialization_contract",
                "sequence": ["RESOLVE_AND_VERIFY_SOURCE", "DERIVE_JOB_ID", "SPECIALIZE_ARTIFACT_GRAPH",
                             "ACQUIRE_ONE_JOB_LEASE", "RUN_DECLARED_STAGES", "VERIFY_JOB_DESCRIPTORS"],
                "lease_authority": "EXISTING_EXECUTION_AUTHORIZATION_ONLY",
                "lease_job_id_pointer": "/derived_job_id",
                "leased_read_scope": "TRANSITIVE_ARTIFACT_INPUTS_AND_DECLARED_RUNTIME_PROVIDERS_FOR_ONE_JOB",
                "leased_write_root": {"root_ref": "harness-resource://execution/jobs",
                                      "child_from_pointer": "/derived_job_id"},
                "caller_write_scope": "CASE_RECEIPTS_ONLY",
                "descriptor_consumer": "external_lab.oracle:verify_job_artifact_descriptors_v1",
                "authoring_execution_forbidden": True,
            }
            command["parameter_contract"][
                "source_resolution_entrypoint"
            ] = PUBLIC_SKILL_SOURCE_RESOLUTION_ENTRYPOINT
            command["network_access_contract"] = {
                "mode": "READ_ONLY_HTTPS_FOR_DECLARED_PUBLIC_SKILL_URL",
                "allowed_hosts": ["github.com"],
                "request_url_pointer": "/input/skill_url",
                "resolution_receipt_required": True,
                "resolved_tree_bytes_required": True,
                "target_skill_execution_forbidden": True,
            }
        if command_id == "LAB-RUN-REGISTRY-CASE":
            command["registry_read_protocol"] = deepcopy(REGISTRY_READ_PROTOCOL)
        command["command_sha256"] = _hash_without_field(
            command, "command_sha256"
        )
        contracts.append(command)
    return contracts


def _bind_case_execution_contracts(
    staging: Path, ir: Mapping[str, Any]
) -> None:
    """Materialize machine-resolvable case fixtures and planned Lab commands."""

    artifact_contracts = [
        artifact
        for atom in ir.get("atoms", [])
        if isinstance(atom, Mapping)
        for obligation in (
            atom.get("production_contract", {}).get("workpack_obligations", [])
            if isinstance(atom.get("production_contract"), Mapping)
            else []
        )
        if isinstance(obligation, Mapping)
        for artifact in obligation.get("artifact_obligations", [])
        if isinstance(artifact, Mapping) and artifact.get("artifact_kind")
    ]
    artifact_kinds = {
        str(artifact.get("artifact_kind")) for artifact in artifact_contracts
    }
    registry = oracle_evaluator_registry(artifact_kinds, artifact_contracts)
    _write_json(staging / "validation/ORACLE_EVALUATOR_REGISTRY.json", registry)
    registry_sha256 = _file_hash(
        staging / "validation/ORACLE_EVALUATOR_REGISTRY.json"
    )
    public_job_interface = public_skill_job_interface(ir)
    public_job_interface_path = (
        staging / "validation/PUBLIC_SKILL_JOB_INTERFACE.json"
    )
    _write_json(public_job_interface_path, public_job_interface)
    public_job_interface_sha256 = _file_hash(public_job_interface_path)
    manifest_ref = (
        f"{LOGICAL_CANDIDATE_ROOT}/validation/CASE_EXECUTION_MANIFEST.json"
    )
    schema_ref = f"{LOGICAL_CANDIDATE_ROOT}/validation/schemas/CASE_RESULT.schema.json"
    planned_python = (
        f"{LOGICAL_EXECUTION_ROOT}/project_start_packages/external_lab/"
        ".venv/bin/python"
    )
    commands = _external_lab_case_command_contracts(
        executable=planned_python,
        repository_root=(
            f"{LOGICAL_EXECUTION_ROOT}/project_start_packages/"
            "external_lab/repository"
        ),
        candidate_root=LOGICAL_CANDIDATE_ROOT,
        execution_root=LOGICAL_EXECUTION_ROOT,
    )
    materialized_case_ids: dict[str, list[str]] = {}
    for case_kind, relative in (
        ("ACCEPTANCE", "validation/ACCEPTANCE_CASES.json"),
        ("NEGATIVE", "validation/NEGATIVE_CASES.json"),
    ):
        document = json.loads((staging / relative).read_text(encoding="utf-8"))
        materialized_case_ids[case_kind] = [
            str(case["case_id"])
            for case in document.get("cases", [])
            if isinstance(case, Mapping) and case.get("case_id")
        ]
    registry_case_invocations: list[dict[str, Any]] = []
    artifact_manifest_path = staging / "canonical_sources/ARTIFACT_OBLIGATION_MANIFEST.json"
    artifact_index = (json.loads(artifact_manifest_path.read_text(encoding="utf-8"))["artifact_index"]
                      if artifact_manifest_path.is_file() else {})
    registry_read_plans = registry_schema_read_plans(artifact_index)
    _write_json(staging / "validation/schemas/REGISTRY_CASE_RESULT.schema.json", REGISTRY_CASE_RESULT_SCHEMA)
    _write_json(staging / "validation/schemas/REGISTRY_CASE_EXECUTION_RECEIPT.schema.json", REGISTRY_CASE_EXECUTION_RECEIPT_SCHEMA)
    seen_registry_result_refs: set[str] = set()
    for matrix_field, case_kind in (
        ("invariant_negative_case_matrix", "INVARIANT"),
        ("schema_native_negative_case_matrix", "SCHEMA_NATIVE"),
    ):
        for case_index, case in enumerate(registry.get(matrix_field, [])):
            if not isinstance(case, Mapping) or not case.get("case_id"):
                continue
            for schema_sha256 in case.get("applicable_schema_sha256s", []):
                fixture_ref = (
                    f"{ORACLE_EVALUATOR_REGISTRY_REF}#/"
                    f"{matrix_field}/{case_index}"
                )
                result_ref = registry_case_result_ref(
                    case_kind,
                    str(case["case_id"]),
                    str(schema_sha256),
                )
                if result_ref in seen_registry_result_refs:
                    continue
                seen_registry_result_refs.add(result_ref)
                read_plan_ref = (f"{manifest_ref}#/registry_case_invocations/"
                                 f"{len(registry_case_invocations)}/read_plan")
                registry_case_invocations.append(
                    {
                        "case_id": str(case["case_id"]),
                        "case_kind": case_kind,
                        "schema_sha256": str(schema_sha256),
                        "owner_workpack_id": CASE_EVIDENCE_WRITER_WORKPACK_ID,
                        "executor_command_id": "LAB-RUN-REGISTRY-CASE",
                        "fixture_ref": fixture_ref,
                        "result_ref": result_ref,
                        "baseline_root_ref": result_ref.removesuffix(".result.json") + "/inputs",
                        "result_schema_ref": RESULT_SCHEMA_REF,
                        "command_receipt_ref": result_ref.removesuffix(".result.json") + ".command.json",
                        "command_receipt_schema_ref": RECEIPT_SCHEMA_REF,
                        "read_plan_ref": read_plan_ref,
                        "read_plan": deepcopy(registry_read_plans[(str(case["artifact_kind"]), str(schema_sha256))]),
                        "executor_argv": [
                            planned_python,
                            "-m",
                            "external_lab",
                            "run-registry-case",
                            "--fixture-ref",
                            fixture_ref,
                            "--result-ref",
                            result_ref,
                            "--read-plan-ref",
                            read_plan_ref,
                        ],
                    }
                )
    public_vector = public_job_interface["metamorphic_acceptance_vector"]
    public_case_id = str(public_vector["case_id"])
    if public_case_id != PUBLIC_SKILL_METAMORPHIC_CASE_ID:
        raise ValueError("public Skill metamorphic Case identity drifted")
    public_case_result_ref = case_result_ref("METAMORPHIC", public_case_id)
    public_case_schema_relative = (
        "validation/schemas/cases/"
        f"metamorphic-{_slug(public_case_id).lower()}.result.schema.json"
    )
    public_case_schema_ref = (
        f"{LOGICAL_CANDIDATE_ROOT}/{public_case_schema_relative}"
    )
    public_case_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": public_case_schema_ref,
        "type": "object",
        "additionalProperties": False,
        "required": [
            "case_id",
            "case_kind",
            "request_sha256",
            "request_id",
            "normalized_skill_url",
            "requested_revision",
            "skill_entrypoint_ref",
            "resolution_receipt_ref",
            "resolution_receipt_sha256",
            "resolved_commit_sha",
            "resolved_git_tree_oid",
            "resolved_tree_ref",
            "resolved_tree_sha256",
            "resolved_skill_entrypoint_sha256",
            "derived_job_id",
            "output_video_count",
            "source_is_frozen_before_analysis",
            "target_skill_execution_enabled",
            "command_receipt_ref",
            "command_receipt_sha256",
            "side_effects_started",
            "artifacts",
            "oracle_decision",
            "status",
        ],
        "properties": {
            "case_id": {"const": public_case_id},
            "case_kind": {"const": "METAMORPHIC"},
            "request_sha256": {"const": _json_hash(public_vector["input"])},
            "request_id": {
                "const": public_vector["input"]["request_id"]
            },
            "normalized_skill_url": {
                "const": public_vector["input"]["skill_url"]
                .removesuffix(".git")
                .rstrip("/")
            },
            "requested_revision": {
                "const": public_vector["input"]["requested_revision"]
            },
            "skill_entrypoint_ref": {
                "const": public_vector["input"]["skill_entrypoint_ref"]
            },
            "resolution_receipt_ref": {
                "const": public_vector["resolution_contract"][
                    "resolution_receipt_ref"
                ]
            },
            "resolution_receipt_sha256": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
            "resolved_commit_sha": {
                "type": "string",
                "pattern": "^[0-9a-f]{40}$",
            },
            "resolved_git_tree_oid": {
                "type": "string",
                "pattern": "^[0-9a-f]{40}$",
            },
            "resolved_tree_ref": {"type": "string", "minLength": 1},
            "resolved_tree_sha256": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
            "resolved_skill_entrypoint_sha256": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
            "derived_job_id": {
                "type": "string",
                "pattern": "^JOB-[0-9A-F]{16}$",
            },
            "output_video_count": {"const": 1},
            "source_is_frozen_before_analysis": {"const": True},
            "target_skill_execution_enabled": {"const": False},
            "command_receipt_ref": {"type": "string", "minLength": 1},
            "command_receipt_sha256": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
            "side_effects_started": {"type": "boolean"},
            "artifacts": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "video",
                    "media_acceptance_receipt",
                    "job_artifact_lease",
                ],
                "properties": {
                    "video": deepcopy(JOB_ARTIFACT_DESCRIPTOR_SCHEMA),
                    "media_acceptance_receipt": deepcopy(
                        JOB_ARTIFACT_DESCRIPTOR_SCHEMA
                    ),
                    "job_artifact_lease": deepcopy(
                        JOB_ARTIFACT_DESCRIPTOR_SCHEMA
                    ),
                },
            },
            "oracle_decision": {"enum": ["PASS", "FAIL"]},
            "status": {"enum": ["PASS", "FAIL"]},
        },
        "x-ref-sha256-bindings": [
            {
                "ref_pointer": "/resolution_receipt_ref",
                "sha256_pointer": "/resolution_receipt_sha256",
            },
            {
                "ref_pointer": "/resolved_tree_ref",
                "sha256_pointer": "/resolved_tree_sha256",
            },
            {
                "ref_pointer": "/skill_entrypoint_ref",
                "sha256_pointer": "/resolved_skill_entrypoint_sha256",
            },
            {
                "ref_pointer": "/command_receipt_ref",
                "sha256_pointer": "/command_receipt_sha256",
            },
        ],
        "x-job-artifact-binding": {
            "job_id_pointer": "/derived_job_id",
            "descriptor_names": ["video", "media_acceptance_receipt", "job_artifact_lease"],
            "descriptor_job_field": "producer_job_id",
            "verify_exact_bytes_and_size": True,
            "media_video_fields": ["video_ref", "video_sha256"],
            "receipt_job_field": "job_id",
            "lease_scope_field": "allowed_write_roots",
            "implementation_entrypoint": "external_lab.oracle:verify_job_artifact_descriptors_v1",
        },
        "x-job-identity-derivation": {
            "algorithm": "SHA256_CANONICAL_RESOLVED_JOB_IDENTITY_PREFIX_16",
            "canonicalization": (
                "UTF8_JSON_SORT_KEYS_COMPACT_SEPARATORS_PRESERVE_ARRAY_ORDER_V1"
            ),
            "identity_field_pointers": [
                "/request_id",
                "/normalized_skill_url",
                "/skill_entrypoint_ref",
                "/resolved_commit_sha",
                "/resolved_git_tree_oid",
                "/resolved_tree_sha256",
                "/resolved_skill_entrypoint_sha256",
            ],
            "output_pointer": "/derived_job_id",
            "output_format": "JOB-UPPERCASE-FIRST-16-SHA256-HEX",
            "resolution_receipt_field_equality_required": True,
        },
        "x-invariants": [
            "RESOLUTION_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES",
            "RESOLVED_TREE_SHA256_MATCHES_REFERENCED_BYTES",
            "RESULT_RESOLVED_FIELDS_EQUAL_HASH_VERIFIED_RESOLUTION_RECEIPT",
            "RESOLVED_SKILL_ENTRYPOINT_SHA256_MATCHES_TREE_MEMBER_BYTES",
            "DERIVED_JOB_ID_EQUALS_CANONICAL_RESOLVED_IDENTITY_HASH",
            "PASS_RESULT_HAS_VIDEO_MEDIA_ACCEPTANCE_AND_JOB_LEASE_DESCRIPTORS",
        ],
        "allOf": [
            {
                "if": {
                    "properties": {"status": {"const": "PASS"}},
                    "required": ["status"],
                },
                "then": {
                    "properties": {
                        "oracle_decision": {"const": "PASS"},
                        "side_effects_started": {"const": True},
                    }
                },
            }
        ],
    }
    _write_json(staging / public_case_schema_relative, public_case_schema)
    public_case_schema_sha256 = _file_hash(
        staging / public_case_schema_relative
    )
    public_fixture_ref = (
        f"{PUBLIC_SKILL_JOB_INTERFACE_REF}#/metamorphic_acceptance_vector"
    )
    metamorphic_case_invocations = [
        {
            "case_id": public_case_id,
            "case_kind": "METAMORPHIC",
            "owner_workpack_id": CASE_EVIDENCE_WRITER_WORKPACK_ID,
            "executor_command_id": "LAB-RUN-METAMORPHIC-CASE",
            "source_resolution_entrypoint": (
                PUBLIC_SKILL_SOURCE_RESOLUTION_ENTRYPOINT
            ),
            "fixture_ref": public_fixture_ref,
            "fixture_fragment_sha256": _json_hash(public_vector),
            "result_ref": public_case_result_ref,
            "result_schema_ref": public_case_schema_ref,
            "result_schema_sha256": public_case_schema_sha256,
            "executor_argv": [
                planned_python,
                "-m",
                "external_lab",
                "run-metamorphic-case",
                "--fixture-ref",
                public_fixture_ref,
                "--resolution-receipt-ref",
                public_vector["resolution_contract"]["resolution_receipt_ref"],
                "--result-ref",
                public_case_result_ref,
            ],
            "oracle_contract": {
                **deepcopy(public_vector["oracle"]),
                "executor_command_id": "LAB-EVALUATE-CASE-ORACLE",
                "result_schema_ref": public_case_schema_ref,
                "result_schema_sha256": public_case_schema_sha256,
            },
        }
    ]
    manifest = {
        "schema_version": "1.0",
        "status": "DECLARE_ONLY",
        "execution_started": False,
        "authorization_ref": None,
        "owner_project_id": "EXTERNAL_CONFORMANCE_LAB",
        "owner_workpack_id": CASE_EVIDENCE_WRITER_WORKPACK_ID,
        "result_root_ref": CASE_EXECUTION_RESULT_ROOT_REF,
        "result_writer_cardinality": "EXACTLY_ONE_WORKPACK",
        "job_read_partition_policy": (
            "EXACTLY_ONE_ACTIVE_JOB_LEASE_PER_CASE_PARTITION_THEN_"
            "HASH_BOUND_CASE_AGGREGATION"
        ),
        "job_read_partition_policy_case_kinds": ["ACCEPTANCE", "NEGATIVE"],
        "expected_case_result_refs": sorted(
            [
                *[
                    case_result_ref("ACCEPTANCE", case_id)
                    for case_id in materialized_case_ids["ACCEPTANCE"]
                ],
                *[
                    case_result_ref("NEGATIVE", case_id)
                    for case_id in materialized_case_ids["NEGATIVE"]
                ],
                *[
                    str(item["result_ref"])
                    for item in registry_case_invocations
                ],
                public_case_result_ref,
            ]
        ),
        "registry_case_invocations": registry_case_invocations,
        "metamorphic_case_invocations": metamorphic_case_invocations,
        "oracle_evaluator_registry_ref": ORACLE_EVALUATOR_REGISTRY_REF,
        "oracle_evaluator_registry_sha256": registry_sha256,
        "public_skill_job_interface_ref": PUBLIC_SKILL_JOB_INTERFACE_REF,
        "public_skill_job_interface_sha256": public_job_interface_sha256,
        "assertion_operators": [
            "VALIDATED_RECEIPT_EXISTS",
            "SET_EQUALS",
            "ALL_ARTIFACTS_SCHEMA_HASH_AND_ORACLE_PASS",
            "EXACT_SOURCE_JOBS_MATCH",
            "EQUALS",
        ],
        "commands": commands,
    }
    manifest["manifest_sha256"] = _hash_without_field(
        manifest, "manifest_sha256"
    )
    _write_json(staging / "validation/CASE_EXECUTION_MANIFEST.json", manifest)
    result_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_ref,
        "type": "object",
        "additionalProperties": False,
        "required": [
            "case_id",
            "case_kind",
            "fixture_sha256",
            "assertion_manifest_sha256",
            "command_receipt_ref",
            "command_receipt_sha256",
            "job_partition_results",
            "job_partition_manifest_sha256",
            "aggregation_receipt_ref",
            "aggregation_receipt_sha256",
            "assertion_results",
            "oracle_decision",
            "status",
        ],
        "properties": {
            "case_id": {"type": "string", "minLength": 1},
            "case_kind": {"enum": ["ACCEPTANCE", "NEGATIVE"]},
            "fixture_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "assertion_manifest_sha256": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
            "artifact_manifest_sha256": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
            "source_job_manifest_sha256": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
            "command_receipt_ref": {"type": "string", "minLength": 1},
            "command_receipt_sha256": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
            "job_partition_results": {
                "type": "array",
                "minItems": 0,
                "uniqueItems": True,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "job_id",
                        "lease_receipt_ref",
                        "lease_receipt_sha256",
                        "result_fragment_ref",
                        "result_fragment_sha256",
                        "fragment_artifact_manifest_ref",
                        "fragment_artifact_manifest_sha256",
                    ],
                    "properties": {
                        "job_id": {"type": "string", "minLength": 1},
                        "lease_receipt_ref": {
                            "type": "string",
                            "minLength": 1,
                        },
                        "lease_receipt_sha256": {
                            "type": "string",
                            "pattern": "^[0-9a-f]{64}$",
                        },
                        "result_fragment_ref": {
                            "type": "string",
                            "minLength": 1,
                        },
                        "result_fragment_sha256": {
                            "type": "string",
                            "pattern": "^[0-9a-f]{64}$",
                        },
                        "fragment_artifact_manifest_ref": {
                            "type": "string",
                            "minLength": 1,
                        },
                        "fragment_artifact_manifest_sha256": {
                            "type": "string",
                            "pattern": "^[0-9a-f]{64}$",
                        },
                    },
                },
            },
            "job_partition_manifest_sha256": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
            "aggregation_receipt_ref": {
                "type": "string",
                "minLength": 1,
            },
            "aggregation_receipt_sha256": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
            "assertion_results": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "assertion_id",
                        "operator",
                        "passed",
                        "actual",
                        "expected",
                        "evidence_refs",
                    ],
                    "properties": {
                        "assertion_id": {"type": "string", "minLength": 1},
                        "operator": {
                            "enum": [
                                "VALIDATED_RECEIPT_EXISTS",
                                "SET_EQUALS",
                                "ALL_ARTIFACTS_SCHEMA_HASH_AND_ORACLE_PASS",
                                "EXACT_SOURCE_JOBS_MATCH",
                                "EQUALS",
                            ]
                        },
                        "passed": {"type": "boolean"},
                        "actual": {},
                        "expected": {},
                        "evidence_refs": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
            "artifact_checks": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "artifact_id",
                        "job_id",
                        "source_id",
                        "artifact_ref",
                        "schema_sha256",
                        "oracle_pass",
                        "evidence_refs",
                    ],
                    "properties": {
                        "artifact_id": {"type": "string", "minLength": 1},
                        "job_id": {"type": ["string", "null"]},
                        "source_id": {"type": ["string", "null"]},
                        "artifact_ref": {"type": "string", "minLength": 1},
                        "schema_sha256": {
                            "type": "string",
                            "pattern": "^[0-9a-f]{64}$",
                        },
                        "oracle_pass": {"const": True},
                        "evidence_refs": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
            "source_job_bindings": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "job_id",
                        "source_id",
                        "repository_url",
                        "commit_sha",
                    ],
                    "properties": {
                        "job_id": {"type": "string", "minLength": 1},
                        "source_id": {"type": "string", "minLength": 1},
                        "repository_url": {"type": "string", "minLength": 1},
                        "commit_sha": {
                            "type": "string",
                            "pattern": "^[0-9a-f]{40}$",
                        },
                    },
                },
            },
            "observed_failure_code": {"type": "string", "minLength": 1},
            "expected_failure_observed": {"const": True},
            "mutation_manifest_sha256": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
            "mutation_variant_results": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "variant_id",
                        "base_input_ref",
                        "base_input_sha256",
                        "mutated_input_ref",
                        "mutated_input_sha256",
                        "mutation_receipt_ref",
                        "mutation_receipt_sha256",
                        "command_receipt_ref",
                        "command_receipt_sha256",
                        "validator_finding_ref",
                        "validator_finding_sha256",
                        "side_effect_receipt_ref",
                        "side_effect_receipt_sha256",
                        "observed_failure_code",
                        "expected_failure_observed",
                        "side_effects_started",
                        "status",
                    ],
                    "properties": {
                        "variant_id": {"type": "string", "minLength": 1},
                        "base_input_ref": {"type": "string", "minLength": 1},
                        "base_input_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                        "mutated_input_ref": {"type": "string", "minLength": 1},
                        "mutated_input_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                        "mutation_receipt_ref": {"type": "string", "minLength": 1},
                        "mutation_receipt_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                        "command_receipt_ref": {"type": "string", "minLength": 1},
                        "command_receipt_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                        "validator_finding_ref": {"type": "string", "minLength": 1},
                        "validator_finding_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                        "side_effect_receipt_ref": {"type": "string", "minLength": 1},
                        "side_effect_receipt_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                        "observed_failure_code": {"type": "string", "minLength": 1},
                        "expected_failure_observed": {"const": True},
                        "side_effects_started": {"const": False},
                        "status": {"const": "PASS"},
                    },
                },
            },
            "side_effect_receipt_ref": {"type": "string", "minLength": 1},
            "side_effect_receipt_sha256": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
            "side_effects_started": {"const": False},
            "oracle_decision": {"enum": ["PASS", "FAIL"]},
            "status": {"enum": ["PASS", "FAIL"]},
        },
        "x-ref-sha256-bindings": [
            {
                "ref_pointer": "/command_receipt_ref",
                "sha256_pointer": "/command_receipt_sha256",
                "pairing": "SINGLE",
            },
            {
                "ref_pointer": "/job_partition_results/*/lease_receipt_ref",
                "sha256_pointer": (
                    "/job_partition_results/*/lease_receipt_sha256"
                ),
                "pairing": "SAME_ARRAY_ITEM",
            },
            {
                "ref_pointer": "/job_partition_results/*/result_fragment_ref",
                "sha256_pointer": (
                    "/job_partition_results/*/result_fragment_sha256"
                ),
                "pairing": "SAME_ARRAY_ITEM",
            },
            {
                "ref_pointer": (
                    "/job_partition_results/*/fragment_artifact_manifest_ref"
                ),
                "sha256_pointer": (
                    "/job_partition_results/*/fragment_artifact_manifest_sha256"
                ),
                "pairing": "SAME_ARRAY_ITEM",
            },
            {
                "ref_pointer": "/aggregation_receipt_ref",
                "sha256_pointer": "/aggregation_receipt_sha256",
                "pairing": "SINGLE",
            },
        ],
        "x-byte-lineage-evaluator": {
            "evaluator_id": "CASE_RESULT_REF_SHA256_LINEAGE_V1",
            "implementation_entrypoint": (
                "external_lab.oracle:verify_ref_sha256_bindings_v1"
            ),
            "algorithm_version": "1.0",
            "hash_algorithm": "SHA-256",
            "byte_mode": "EXACT_REFERENCED_BYTES_NO_REENCODING",
            "unknown_or_unresolved_ref_disposition": "FAIL_CLOSED",
            "failure_code": "CASE_RESULT_BYTE_LINEAGE_MISMATCH",
        },
        "allOf": [
            {
                "if": {
                    "properties": {"status": {"const": "PASS"}},
                    "required": ["status"],
                },
                "then": {
                    "properties": {
                        "oracle_decision": {"const": "PASS"},
                        "assertion_results": {
                            "not": {
                                "contains": {
                                    "type": "object",
                                    "properties": {"passed": {"const": False}},
                                    "required": ["passed"],
                                }
                            }
                        },
                    }
                },
            },
            {
                "if": {
                    "properties": {"oracle_decision": {"const": "PASS"}},
                    "required": ["oracle_decision"],
                },
                "then": {
                    "properties": {
                        "status": {"const": "PASS"},
                        "assertion_results": {
                            "not": {
                                "contains": {
                                    "type": "object",
                                    "properties": {"passed": {"const": False}},
                                    "required": ["passed"],
                                }
                            }
                        },
                    }
                },
            },
            {
                "if": {
                    "properties": {"case_kind": {"const": "ACCEPTANCE"}},
                    "required": ["case_kind"],
                },
                "then": {
                    "required": [
                        "artifact_checks",
                        "artifact_manifest_sha256",
                        "source_job_bindings",
                        "source_job_manifest_sha256",
                    ]
                },
            },
            {
                "if": {
                    "properties": {"case_kind": {"const": "NEGATIVE"}},
                    "required": ["case_kind"],
                },
                "then": {
                    "required": [
                        "observed_failure_code",
                        "expected_failure_observed",
                        "artifact_manifest_sha256",
                        "source_job_manifest_sha256",
                        "mutation_manifest_sha256",
                        "mutation_variant_results",
                        "side_effect_receipt_ref",
                        "side_effect_receipt_sha256",
                        "side_effects_started",
                    ]
                },
            },
        ],
    }
    _write_json(staging / "validation/schemas/CASE_RESULT.schema.json", result_schema)
    schema_sha256 = _file_hash(
        staging / "validation/schemas/CASE_RESULT.schema.json"
    )

    atom_ids = [
        str(item.get("atom_id"))
        for item in ir.get("atoms", [])
        if isinstance(item, Mapping) and item.get("atom_id")
    ]
    documents = (
        (
            "validation/ACCEPTANCE_CASES.json",
            "ACCEPTANCE",
            "LAB-RUN-ACCEPTANCE-CASE",
        ),
        (
            "validation/NEGATIVE_CASES.json",
            "NEGATIVE",
            "LAB-RUN-NEGATIVE-CASE",
        ),
    )
    for relative, case_kind, command_id in documents:
        path = staging / relative
        document = json.loads(path.read_text(encoding="utf-8"))
        raw_cases = [
            dict(item)
            for item in document.get("cases", [])
            if isinstance(item, Mapping)
        ]
        if case_kind == "ACCEPTANCE":
            cases = _compile_acceptance_cases({"acceptance_cases": raw_cases})
        else:
            # Preserve the frozen target/profile context when executable case
            # fixtures are hydrated.  Reconstructing a partial Requirement IR
            # here silently selected the default distributed assurance profile
            # and reintroduced release-only HF28 cases into personal-local
            # Candidates after CASE_EXECUTION_MANIFEST had already been built.
            negative_case_ir = deepcopy(dict(ir))
            negative_case_ir["negative_cases"] = raw_cases
            cases = _mandatory_negative_cases(negative_case_ir)
        for case in cases:
            case_id = str(case["case_id"])
            fixture_relative = (
                "validation/case_fixtures/"
                f"{case_kind.lower()}-{_slug(case_id).lower()}.fixture.json"
            )
            fixture_ref = f"{LOGICAL_CANDIDATE_ROOT}/{fixture_relative}"
            result_ref = case_result_ref(case_kind, case_id)
            for assertion in case.get("assertions", []):
                if (
                    isinstance(assertion, dict)
                    and assertion.get("operator") == "VALIDATED_RECEIPT_EXISTS"
                ):
                    assertion["actual_ref"] = result_ref
            if case_kind == "ACCEPTANCE":
                fixture_input = _acceptance_fixture_input(ir, case)
                if not any(
                    isinstance(assertion, Mapping)
                    and assertion.get("operator")
                    == "ALL_ARTIFACTS_SCHEMA_HASH_AND_ORACLE_PASS"
                    for assertion in case.get("assertions", [])
                ):
                    case.setdefault("assertions", []).append(
                        {
                            "assertion_id": f"ASSERT-{case_id}-ARTIFACTS",
                            "operator": "ALL_ARTIFACTS_SCHEMA_HASH_AND_ORACLE_PASS",
                            "actual_ref": "result.artifact_checks",
                            "expected": True,
                        }
                    )
                if fixture_input["fixture_jobs"]:
                    case["assertions"].append(
                        {
                            "assertion_id": f"ASSERT-{case_id}-SOURCE-JOBS",
                            "operator": "EXACT_SOURCE_JOBS_MATCH",
                            "actual_ref": "result.source_job_bindings",
                            "expected": [
                                {
                                    "job_id": item["job_id"],
                                    "source_id": item["source_id"],
                                    "repository_url": item["repository_url"],
                                    "commit_sha": item["commit_sha"],
                                }
                                for item in fixture_input["fixture_jobs"]
                            ],
                        }
                    )
            else:
                fixture_input = deepcopy(case.get("input_fixture"))
                if isinstance(fixture_input, dict):
                    fixture_input["artifact_expectations"] = (
                        _case_artifact_expectations(
                            ir, [str(value) for value in case.get("atom_ids", [])]
                        )
                    )
                    fixture_input["artifact_dependency_mode"] = (
                        "DECLARED_PRODUCTION_ARTIFACTS"
                        if fixture_input["artifact_expectations"]
                        else "NO_DECLARED_PRODUCTION_ARTIFACTS"
                    )
                    fixture_input["fixture_jobs"] = _repository_fixture_jobs(ir)
                    _bind_negative_mutation_targets(
                        fixture_input,
                        ir,
                        case_id,
                    )
                    case["input_fixture"] = deepcopy(fixture_input)
            oracle_bindings = _case_oracle_bindings(
                fixture_input if isinstance(fixture_input, Mapping) else {},
                [
                    item
                    for item in case.get("assertions", [])
                    if isinstance(item, Mapping)
                ],
            )
            fixture = {
                "schema_version": "1.0",
                "case_id": case_id,
                "case_kind": case_kind,
                "atom_ids": list(case.get("atom_ids") or atom_ids),
                "input": fixture_input,
                "preconditions": deepcopy(case.get("preconditions")),
                "assertions": deepcopy(case.get("assertions")),
                "oracle_bindings": oracle_bindings,
                "expected_failure": case.get("expected_failure"),
                "execution_authorized": False,
            }
            _write_json(staging / fixture_relative, fixture)
            fixture_sha256 = _file_hash(staging / fixture_relative)
            result_schema_relative = (
                "validation/schemas/cases/"
                f"{case_kind.lower()}-{_slug(case_id).lower()}.result.schema.json"
            )
            result_schema_ref = (
                f"{LOGICAL_CANDIDATE_ROOT}/{result_schema_relative}"
            )
            partition_job_ids = sorted(
                {
                    str(expectation["job_id"])
                    for expectation in (
                        fixture_input.get("artifact_expectations", [])
                        if isinstance(fixture_input, Mapping)
                        else []
                    )
                    if isinstance(expectation, Mapping)
                    and expectation.get("job_id")
                }
            )
            job_read_partitions = [
                {
                    "job_id": job_id,
                    "lease_receipt_ref": (
                        f"{LOGICAL_EXECUTION_ROOT}/evidence/"
                        "job_artifact_leases/LAB-CERTIFICATION/"
                        f"LAB-RUN-CASE-PARTITION/{job_id}.lease.json"
                    ),
                    "result_fragment_ref": (
                        f"{CASE_EXECUTION_RESULT_ROOT_REF}/fragments/"
                        f"{case_kind.lower()}-{_slug(case_id).lower()}/"
                        f"{_slug(job_id).lower()}.result.json"
                    ),
                    "fragment_artifact_manifest_ref": (
                        f"{CASE_EXECUTION_RESULT_ROOT_REF}/fragments/"
                        f"{case_kind.lower()}-{_slug(case_id).lower()}/"
                        f"{_slug(job_id).lower()}.artifact-manifest.json"
                    ),
                }
                for job_id in partition_job_ids
            ]
            fragment_manifest_ref = (
                f"{CASE_EXECUTION_RESULT_ROOT_REF}/fragments/"
                f"{case_kind.lower()}-{_slug(case_id).lower()}/manifest.json"
            )
            aggregation_receipt_ref = (
                f"{CASE_EXECUTION_RESULT_ROOT_REF}/aggregation/"
                f"{case_kind.lower()}-{_slug(case_id).lower()}.receipt.json"
            )
            aggregation_schema_relative = (
                "validation/schemas/cases/"
                f"{case_kind.lower()}-{_slug(case_id).lower()}."
                "aggregation-receipt.schema.json"
            )
            aggregation_schema_ref = (
                f"{LOGICAL_CANDIDATE_ROOT}/{aggregation_schema_relative}"
            )
            aggregation_schema = _case_aggregation_receipt_schema(
                schema_id=aggregation_schema_ref,
                case_id=case_id,
                case_kind=case_kind,
                fragment_manifest_ref=fragment_manifest_ref,
                fragment_refs=[
                    item["result_fragment_ref"]
                    for item in job_read_partitions
                ],
                result_ref=result_ref,
            )
            _write_json(staging / aggregation_schema_relative, aggregation_schema)
            aggregation_schema_sha256 = _file_hash(
                staging / aggregation_schema_relative
            )
            specialized_result_schema = _specialize_case_result_schema(
                result_schema,
                schema_id=result_schema_ref,
                case_id=case_id,
                case_kind=case_kind,
                fixture_sha256=fixture_sha256,
                oracle_bindings=oracle_bindings,
                job_read_partitions=job_read_partitions,
                expected_failure=(
                    str(case.get("expected_failure") or "EXPECTED_REJECTION")
                    if case_kind == "NEGATIVE"
                    else None
                ),
            )
            specialized_result_schema["x-aggregation-receipt-schema"] = {
                "ref": aggregation_schema_ref,
                "sha256": aggregation_schema_sha256,
            }
            _write_json(
                staging / result_schema_relative,
                specialized_result_schema,
            )
            result_schema_sha256 = _file_hash(staging / result_schema_relative)
            executor_argv = [
                planned_python,
                "-m",
                "external_lab",
                (
                    "run-acceptance-case"
                    if case_kind == "ACCEPTANCE"
                    else "run-negative-case"
                ),
                "--fixture-ref",
                fixture_ref,
                "--result-ref",
                result_ref,
            ]
            partition_executor_argvs = [
                [
                    planned_python,
                    "-m",
                    "external_lab",
                    "run-case-partition",
                    "--fixture-ref",
                    fixture_ref,
                    "--job-id",
                    partition["job_id"],
                    "--lease-receipt-ref",
                    partition["lease_receipt_ref"],
                    "--result-fragment-ref",
                    partition["result_fragment_ref"],
                    "--fragment-artifact-manifest-ref",
                    partition["fragment_artifact_manifest_ref"],
                ]
                for partition in job_read_partitions
            ]
            aggregation_executor_argv = [
                planned_python,
                "-m",
                "external_lab",
                "aggregate-case-partitions",
                "--fixture-ref",
                fixture_ref,
                "--fragment-manifest-ref",
                fragment_manifest_ref,
                "--aggregation-receipt-ref",
                aggregation_receipt_ref,
                "--aggregation-receipt-schema-ref",
                aggregation_schema_ref,
                "--result-ref",
                result_ref,
            ]
            for step in case.get("steps", []):
                if isinstance(step, dict):
                    step.setdefault("command_id", command_id)
                    step.setdefault("fixture_ref", fixture_ref)
                    step.setdefault("result_ref", result_ref)
            case.update(
                {
                    "fixture_ref": fixture_ref,
                    "fixture_sha256": fixture_sha256,
                    "executor_command_manifest_ref": manifest_ref,
                    "executor_command_id": command_id,
                    "executor_argv": executor_argv,
                    "job_read_partition_policy": (
                        "EXACTLY_ONE_ACTIVE_JOB_LEASE_PER_CASE_PARTITION_"
                        "THEN_HASH_BOUND_CASE_AGGREGATION"
                    ),
                    "job_read_partitions": job_read_partitions,
                    "job_partition_manifest_sha256": _json_hash(
                        job_read_partitions
                    ),
                    "partition_executor_command_id": (
                        "LAB-RUN-CASE-PARTITION"
                    ),
                    "partition_executor_argvs": partition_executor_argvs,
                    "fragment_manifest_ref": fragment_manifest_ref,
                    "aggregation_executor_command_id": (
                        "LAB-AGGREGATE-CASE-PARTITIONS"
                    ),
                    "aggregation_executor_argv": aggregation_executor_argv,
                    "aggregation_receipt_ref": aggregation_receipt_ref,
                    "aggregation_receipt_schema_ref": aggregation_schema_ref,
                    "aggregation_receipt_schema_sha256": (
                        aggregation_schema_sha256
                    ),
                    "result_ref": result_ref,
                    "result_schema_ref": result_schema_ref,
                    "result_schema_sha256": result_schema_sha256,
                }
            )
            if case_kind == "NEGATIVE":
                case["mutation_manifest_ref"] = (
                    f"{fixture_ref}#/input/mutation_manifest"
                )
                case["mutation_manifest_sha256"] = oracle_bindings[
                    "mutation_manifest_sha256"
                ]
            oracle = dict(case["oracle_contract"])
            oracle.update(
                {
                    "executor_command_manifest_ref": manifest_ref,
                    "executor_command_id": "LAB-EVALUATE-CASE-ORACLE",
                    "executor_argv": [
                        planned_python,
                        "-m",
                        "external_lab",
                        "evaluate-case-oracle",
                        "--fixture-ref",
                        fixture_ref,
                        "--result-ref",
                        result_ref,
                    ],
                    "result_schema_ref": result_schema_ref,
                    "result_schema_sha256": result_schema_sha256,
                    "evaluator_id": "EXACT_CASE_SET_ORACLE_V1",
                    "evaluator_registry_ref": ORACLE_EVALUATOR_REGISTRY_REF,
                    "assertion_manifest_sha256": oracle_bindings[
                        "assertion_manifest_sha256"
                    ],
                    "artifact_manifest_sha256": oracle_bindings[
                        "artifact_manifest_sha256"
                    ],
                    "source_job_manifest_sha256": oracle_bindings[
                        "source_job_manifest_sha256"
                    ],
                    "mutation_manifest_sha256": oracle_bindings[
                        "mutation_manifest_sha256"
                    ],
                }
            )
            case["oracle_contract"] = oracle
        document["cases"] = cases
        _write_json(path, document)


def _materialize_workpack_files(staging: Path, ir: Mapping[str, Any], context: Mapping[str, str], docs: Mapping[str, Any]) -> None:
    workpack_id = context["first_workpack_id"]
    mission = str(ir["target"]["mission"])
    workpack = f"""# Workpack: {workpack_id}

Status: `PLANNED_NOT_ACTIVE`

## Objective

Materialize only the Main execution package envelope for {context['target_name']}: {mission}

## Boundary

- Program DAG node: `MAIN_EXECUTION_PACKAGE_MATERIALIZED`
- Project: `MAIN_HARNESS_BUILD`
- Required atoms: none; this root Workpack is structural only
- Validation scope: `{ROOT_LAYER_VALIDATION_SCOPE}`
- Behavioral Atom acceptance: `{ROOT_LAYER_BEHAVIORAL_ATOM_POLICY}`
- Read-only Start Package root: `{context['candidate_root']}`
- Planned execution workspace root: `{context['execution_root']}/project_start_packages/main_build/repository`
- Workspace status: `PLANNED_NOT_CREATED`
- Forbidden: source materials, sibling v2.8, Lab/Linkage implementation, install targets
- Execution mode: `WORKPACK_EXECUTION`
- Authorization: not granted

## Machine inputs and outputs

- Required capabilities: {', '.join(ROOT_MATERIALIZATION_REQUIRES)}
- Required inputs: Source Manifest, Atom Catalog, Coverage Matrix, Charter Lock, Profile Lock
- Command IDs in order: {', '.join(ROOT_MATERIALIZATION_COMMAND_IDS)}
- Required outputs: {', '.join(ROOT_MATERIALIZATION_PRODUCES)}
- Return path: `REOPEN_OR_SINGLE_REPAIR_OWNER_VIA_REENTRY_PLAN`

## Acceptance

- Candidate inventory, Hash bindings, command contracts, and coverage routing are structurally valid.
- Positive, negative, boundary, and runtime behavior cases remain assigned to their coverage-routed project Workpacks.
- Command evidence requires stdout, stderr, exit code, and configured runtime attestation.
- Failure returns to this Workpack or the single owner selected by `REPAIR_ROUTING_RULES.json`.

## Non-claims

This planned Workpack has not been executed and proves no Harness, install, linkage, or conformance result.
"""
    _write_text(staging / f"workpacks/{workpack_id}.md", workpack)
    command = deepcopy(docs["COMMAND_MANIFEST.json"])
    _write_json(staging / f"commands/{workpack_id}.commands.json", command)
    _write_json(staging / "COMMAND_MANIFEST.json", command)
    workpack_hash = _file_hash(staging / f"workpacks/{workpack_id}.md")
    command_hash = _file_hash(staging / f"commands/{workpack_id}.commands.json")
    capsule = deepcopy(docs["CAPSULE.json"])
    capsule.update(
        {
            "capsule_sha256": None,
            "workpack_sha256": workpack_hash,
            "command_manifest_sha256": command_hash,
            "predecessor_lock_refs": list(
                docs["WORKPACK_INDEX.json"]["workpacks"][0].get(
                    "required_predecessor_lock_refs", []
                )
            ),
            "required_file_refs": [
                "canonical_sources/SOURCE_MANIFEST.json",
                "canonical_sources/NORMATIVE_ATOM_CATALOG.json",
                "canonical_sources/ATOM_COVERAGE_MATRIX.json",
            ],
        }
    )
    _write_json(staging / f"capsules/{workpack_id}.capsule.json", capsule)
    _write_json(staging / "CAPSULE.json", capsule)
    capsule_hash = _file_hash(staging / f"capsules/{workpack_id}.capsule.json")
    result = deepcopy(docs["WORKPACK_RESULT.json"])
    result.update(
        {
            "capsule_sha256": capsule_hash,
            "command_manifest_sha256": command_hash,
            "loop_state_ref": f"loops/{workpack_id}.loop.json",
        }
    )
    _write_json(staging / f"results/{workpack_id}.result.json", result)
    _write_json(staging / "WORKPACK_RESULT.json", result)
    loop = deepcopy(docs["LOOP_STATE.json"])
    _write_json(staging / f"loops/{workpack_id}.loop.json", loop)


def _project_planned_interface_commands(
    directory: str,
    candidate: Path,
    execution: Path | None = None,
) -> list[dict[str, Any]]:
    execution_root = execution or candidate
    repository = execution_root / "project_start_packages" / directory / "repository"
    codex = execution_root / "planned_executors/bin/codex"
    coding_id = {
        "external_lab": "LAB-CODEX-CODING",
        "linkage_review": "LINK-CODEX-CODING",
        "main_build": "MB-CODEX-CODING",
    }[directory]
    commands = [
        {
            "command_id": coding_id,
            "command_kind": "PLANNED_EXECUTOR_INTERFACE",
            "executor_role": "CODEX_CODING_AGENT",
            "executable": str(codex),
            "executable_abs": str(codex),
            "executable_status": "PLANNED_NOT_INSTALLED",
            "argv": None,
            "invocation_contract_status": "REQUIRES_VERIFIED_CLI_SCHEMA_AND_PREFLIGHT",
            "task_bundle_binding_policy": "REQUIRED_PER_WORKPACK_TASK_BUNDLE",
            "task_bundle_argument_injection": "ONLY_AFTER_VERIFIED_CLI_SCHEMA",
            "unverified_cli_flags_forbidden": True,
            "cwd_absolute": str(repository),
            "authorization_ref": None,
            "preflight_gate": "PROGRAM_DRIVER_RUNTIME_VERIFIED_AND_CODEX_CLI_SCHEMA_VERIFIED",
            "allowed_modes": ["WORKPACK_EXECUTION"],
            "expected_exit_codes": [],
            "stdout_stderr_evidence_required": True,
            "allowed_write_roots": [str(repository)],
            "auto_execute": False,
            "shell": False,
        }
    ]
    if directory == "external_lab":
        from .project_verification import lab_protocol_command
        commands.append(lab_protocol_command())
        lab_python = str(
            execution_root
            / "project_start_packages/external_lab/.venv/bin/python"
        )
        commands.extend(
            _external_lab_case_command_contracts(
                executable=lab_python,
                repository_root=str(repository),
                candidate_root=str(candidate),
                execution_root=str(execution_root),
            )
        )
    if directory == "linkage_review":
        linkage_cli = (
            execution_root
            / "project_start_packages/linkage_review/.venv/bin/linkage-review"
        )
        commands.append(
            {
                "command_id": "LINK-PREFLIGHT-CHECK",
                "command_kind": "PLANNED_EXECUTOR_INTERFACE",
                "executor_role": "READ_ONLY_LINKAGE_REVIEW_TOOL",
                "executable": str(linkage_cli),
                "executable_abs": str(linkage_cli),
                "executable_status": "PLANNED_NOT_INSTALLED",
                "argv": None,
                "invocation_contract_status": "REQUIRES_GENERATED_TOOL_CLI_SCHEMA_AND_PREFLIGHT",
                "unverified_cli_flags_forbidden": True,
                "cwd_absolute": str(repository),
                "authorization_ref": None,
                "preflight_gate": "LINKAGE_TOOL_RELEASE_LOCKED_AND_CLI_SCHEMA_VERIFIED",
                "allowed_modes": ["LINKAGE_READ_ONLY"],
                "expected_exit_codes": [],
                "stdout_stderr_evidence_required": True,
                "allowed_write_roots": [
                    str(execution_root / "evidence/linkage_review")
                ],
                "auto_execute": False,
                "shell": False,
            }
        )
    if directory == "main_build":
        driver = execution_root / "control_plane/.venv/bin/program-driver"
        commands.append(
            {
                "command_id": "MB-RELEASE-CANDIDATE-PREPARE",
                "command_kind": "PLANNED_EXECUTOR_INTERFACE",
                "executor_role": "BUILD_PROGRAM_DRIVER",
                "executable": str(driver),
                "executable_abs": str(driver),
                "executable_status": "PLANNED_NOT_INSTALLED",
                "argv": None,
                "invocation_contract_status": "REQUIRES_VERIFIED_DRIVER_CLI_SCHEMA_AND_PREFLIGHT",
                "unverified_cli_flags_forbidden": True,
                "cwd_absolute": str(repository),
                "authorization_ref": None,
                "preflight_gate": "P4_INSTALLABILITY_PASS_AND_DRIVER_RUNTIME_VERIFIED",
                "allowed_modes": ["REGISTRATION_ONLY"],
                "expected_exit_codes": [],
                "stdout_stderr_evidence_required": True,
                "allowed_write_roots": [
                    str(execution_root / "evidence/release_pipeline")
                ],
                "auto_execute": False,
                "shell": False,
            }
        )
    for command in commands:
        command["command_sha256"] = _hash_without_field(
            command, "command_sha256"
        )
    return commands


def _semantic_workpack_markdown(task_bundle: Mapping[str, Any] | None) -> str:
    if not isinstance(task_bundle, Mapping):
        return "## Semantic production contract\n\nNo explicit semantic Task Bundle is routed to this Workpack."
    sections = [
        "## Frozen semantic production contract",
        "",
        f"- Task Bundle: `{task_bundle['task_bundle_id']}`",
        "- Semantic hydration: complete",
        "- Runtime binding: not complete",
        f"- Required Artifact IDs: {', '.join(task_bundle['required_artifact_ids'])}",
    ]
    lab_contract = task_bundle.get("lab_case_execution_contract")
    if isinstance(lab_contract, Mapping):
        sections.extend(
            [
                "",
                "### External Lab case execution contract",
                "",
                f"- Contract: `{lab_contract['contract_id']}`",
                "- Shared Lab interface command IDs (context; execution belongs to the native Workpack manifest): "
                + ", ".join(lab_contract["required_command_ids"]),
                "- Assertion operators: "
                + ", ".join(lab_contract["assertion_operators"]),
                "- Required interfaces:",
                *[f"  - `{item}`" for item in lab_contract["required_refs"]],
                "- Current Workpack implementation obligations (later Workpacks are not preconditions):",
                *[
                    f"  - {item}"
                    for item in lab_contract["implementation_obligations"]
                ],
            ]
        )
    for contract in task_bundle["task_contracts"]:
        sections.extend(
            [
                "",
                f"### {contract['atom_id']} / {contract['contract_id']}",
                "",
                f"Objective: {contract['task_objective']}",
                "",
                "Required inputs:",
                *[f"- {item}" for item in contract["required_inputs"]],
            ]
        )
        if contract["design_questions"]:
            sections.extend(
                [
                    "",
                    "Frozen design questions:",
                    *[f"- {item}" for item in contract["design_questions"]],
                ]
            )
        sections.extend(
            [
                "",
                "Deterministic production steps:",
                *[f"- {item}" for item in contract["deterministic_steps"]],
                "",
                "Forbidden inference:",
                *[f"- {item}" for item in contract["forbidden_inferences"]],
                "",
                "Required artifacts:",
            ]
        )
        for artifact in contract["artifact_obligations"]:
            failure_routes = artifact.get("failure_returns") or [
                artifact["failure_return"]
            ]
            sections.extend(
                [
                    f"- `{artifact['artifact_id']}` → `{artifact['artifact_ref']}`",
                    f"  - Schema required fields: {', '.join(artifact['schema']['required'])}",
                    f"  - Production rule: {artifact['production_rule']}",
                    f"  - Validation rule: {artifact['validation_rule']['decision_rule']}",
                    f"  - Oracle: {artifact['oracle']['oracle_id']} / {artifact['oracle']['independence_level']}",
                    "  - Failure returns: "
                    + ", ".join(
                        f"{route['error_code']} → {route['control_node_id']}"
                        for route in failure_routes
                    ),
                ]
            )
    return "\n".join(sections)


def _materialize_project_workpack_contracts(
    output: Path,
    *,
    project_id: str,
    directory: str,
    coverage_edges: list[Mapping[str, Any]],
    context: Mapping[str, str],
    candidate: Path,
    artifact_manifest: Mapping[str, Any] | None,
) -> None:
    execution = Path(context["execution_root"])
    index_path = output / "WORKPACK_INDEX.json"
    global_command_path = output / "COMMAND_MANIFEST.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    global_commands = json.loads(global_command_path.read_text(encoding="utf-8"))
    commands_by_id = {
        str(command["command_id"]): command
        for command in global_commands.get("commands", [])
        if isinstance(command, dict) and command.get("command_id")
    }
    global_command_sha256 = _file_hash(global_command_path)
    repository = execution / "project_start_packages" / directory / "repository"
    for workpack in index.get("workpacks", []):
        workpack_id = str(workpack["workpack_id"])
        contract = PROJECT_WORKPACK_CONTRACTS[workpack_id]
        intent_atom_ids = [
            str(edge["atom_id"])
            for edge in coverage_edges
            if workpack_id in edge.get("workpack_ids", [])
        ]
        command_ids = list(contract["command_ids"])
        missing_commands = [
            command_id for command_id in command_ids if command_id not in commands_by_id
        ]
        if missing_commands:
            raise ValueError(
                f"project Workpack {workpack_id} has missing command contracts: "
                f"{missing_commands}"
            )
        workpack_ref = f"workpacks/{workpack_id}.md"
        command_ref = f"commands/{workpack_id}.commands.json"
        capsule_ref = f"capsules/{workpack_id}.capsule.json"
        result_ref = f"results/{workpack_id}.result.json"
        loop_ref = f"loops/{workpack_id}.loop.json"
        task_bundle = task_bundle_for_workpack(
            artifact_manifest,
            workpack_id=workpack_id,
            project_id=project_id,
            program_id=str(context["program_id"]),
            target_id=str(context["target_id"]),
            structural_contract=PROJECT_WORKPACK_CONTRACTS.get(workpack_id),
        )
        required_artifact_refs = (
            list(task_bundle["required_artifact_refs"])
            if task_bundle is not None
            else []
        )
        artifact_write_roots = _artifact_write_paths(
            execution, required_artifact_refs
        )
        acceptance_write_roots = _artifact_write_paths(
            execution, _acceptance_artifact_refs(task_bundle)
        )
        auxiliary_write_roots = _workpack_auxiliary_write_roots(
            execution, workpack_id
        )
        command_write_roots = list(
            dict.fromkeys([*artifact_write_roots, *auxiliary_write_roots])
        )
        allowed_write_paths = _project_workpack_allowed_write_paths(
            execution,
            project_id=project_id,
            directory=directory,
            workpack_id=workpack_id,
            required_artifact_refs=required_artifact_refs,
        )
        task_bundle_ref = (
            f"task_bundles/{workpack_id}.task_bundle.json"
            if task_bundle is not None
            else None
        )
        if task_bundle is not None and task_bundle_ref is not None:
            _write_json(output / task_bundle_ref, task_bundle)
        required_artifact_ids = (
            list(task_bundle["required_artifact_ids"])
            if task_bundle is not None
            else []
        )
        artifact_read_roots = _artifact_dependency_read_paths(
            execution, artifact_manifest, required_artifact_ids
        )
        shared_artifact_read_roots = [
            root for root in artifact_read_roots if "/jobs/" not in root
        ]
        allowed_read_paths = list(
            dict.fromkeys([str(candidate), str(repository), *shared_artifact_read_roots])
        )
        job_artifact_read_scopes = _job_artifact_scopes(
            artifact_read_roots, roots_field="allowed_read_roots"
        )
        job_artifact_write_scopes = _job_artifact_scopes(
            artifact_write_roots, roots_field="allowed_write_roots"
        )
        job_scope_activation_policy = (
            "NO_JOB_ARTIFACT_ROOT_IS_ACTIVE_WITHOUT_EXACTLY_ONE_CURRENT_LEASE"
            if job_artifact_read_scopes or job_artifact_write_scopes
            else "NO_JOB_ARTIFACT_SCOPE"
        )
        success_rule = (
            task_bundle["completion_rule"]
            if task_bundle is not None
            else "ALL_REQUIRED_COMMANDS_AND_CAPABILITIES_VALID"
        )
        workpack.update(
            {
                "requires": list(contract["requires"]),
                "requirement_sources": dict(contract["requirement_sources"]),
                "produces": list(contract["produces"]),
                "execution_mode": contract["execution_mode"],
                "command_ids": command_ids,
                "command_execution_order": command_ids,
                "intent_atom_ids": intent_atom_ids,
                "workpack_ref": workpack_ref,
                "command_manifest_ref": command_ref,
                "capsule_ref": capsule_ref,
                "result_ref": result_ref,
                "loop_state_ref": loop_ref,
                "allowed_read_paths": allowed_read_paths,
                "job_artifact_read_scopes": job_artifact_read_scopes,
                "job_artifact_write_scopes": job_artifact_write_scopes,
                "allowed_write_paths": allowed_write_paths,
                "job_artifact_scope_activation_policy": job_scope_activation_policy,
                "active_job_artifact_lease_ref": None,
                "execution_authorization_ref": None,
                "auto_start": False,
                "success_rule": success_rule,
                "failure_return_node": workpack["program_control_node_id"],
            }
        )
        if task_bundle is not None and task_bundle_ref is not None:
            workpack.update(
                {
                    "semantic_contract_status": "FROZEN",
                    "semantic_hydration_complete": True,
                    "artifact_obligation_manifest_ref": ARTIFACT_MANIFEST_REF,
                    "artifact_obligation_manifest_sha256": artifact_manifest[
                        "manifest_sha256"
                    ],
                    "task_bundle_ref": task_bundle_ref,
                    "task_bundle_sha256": _file_hash(output / task_bundle_ref),
                    "production_contract_ids": list(
                        task_bundle["production_contract_ids"]
                    ),
                    "required_artifact_ids": required_artifact_ids,
                    "required_artifact_refs": required_artifact_refs,
                }
            )
        semantic_contract_text = _semantic_workpack_markdown(task_bundle)
        workpack_text = f"""# Project Workpack: {workpack_id}

Status: `PLANNED_NOT_ACTIVE`

## Project and control binding

- Project: `{project_id}`
- Program control surface: `{workpack['program_control_surface']}`
- Program control node: `{workpack['program_control_node_id']}`
- Execution mode: `{contract['execution_mode']}`

## Capability contract

- Requires: {', '.join(contract['requires'])}
- Produces: {', '.join(contract['produces'])}
- Requirement sources: {json.dumps(contract['requirement_sources'], sort_keys=True)}

{semantic_contract_text}

## Command and path contract

- Command IDs in order: {', '.join(command_ids)}
- Intent Atom IDs: {', '.join(intent_atom_ids) if intent_atom_ids else 'none explicitly routed'}
- Allowed read roots: {', '.join(f'`{value}`' for value in allowed_read_paths)}
- Allowed write roots: {', '.join(f'`{value}`' for value in allowed_write_paths)}
- Execution authorization: not granted

## Completion and return

{success_rule}. Failure returns to `{workpack['program_control_node_id']}` through the single-owner repair and reentry contract.

## Non-claims

This Workpack is declarative. Its semantic task contract may be frozen, but runtime binding, execution, promotion, installation, and certification have not occurred.
"""
        _write_text(output / workpack_ref, workpack_text)
        per_workpack_commands = {
            "schema_version": "2.8",
            "program_id": context["program_id"],
            "project_id": project_id,
            "workpack_id": workpack_id,
            "status": "DECLARE_ONLY",
            "execution_started": False,
            "source_project_command_manifest_ref": "COMMAND_MANIFEST.json",
            "source_project_command_manifest_sha256": global_command_sha256,
            "command_ids": command_ids,
            "intent_atom_ids": intent_atom_ids,
            "required_artifact_ids": required_artifact_ids,
            "required_artifact_refs": required_artifact_refs,
            "workpack_artifact_write_roots": artifact_write_roots,
            "workpack_acceptance_write_roots": acceptance_write_roots,
            "workpack_auxiliary_write_roots": auxiliary_write_roots,
            "workpack_artifact_read_roots": artifact_read_roots,
            "workpack_shared_artifact_read_roots": (
                shared_artifact_read_roots
            ),
            "commands": _bind_commands_to_workpack_artifact_roots(
                commands_by_id,
                command_ids,
                command_write_roots,
                artifact_read_roots,
                workpack_id=workpack_id,
                workpack_read_roots=allowed_read_paths,
                acceptance_write_roots=acceptance_write_roots,
            ),
        }
        if task_bundle is not None and task_bundle_ref is not None:
            per_workpack_commands.update(
                {
                    "semantic_task_bundle_ref": task_bundle_ref,
                    "semantic_task_bundle_sha256": _file_hash(
                        output / task_bundle_ref
                    ),
                    "artifact_obligation_manifest_ref": ARTIFACT_MANIFEST_REF,
                    "artifact_obligation_manifest_sha256": artifact_manifest[
                        "manifest_sha256"
                    ],
                }
            )
        per_workpack_commands["manifest_sha256"] = _hash_without_field(
            per_workpack_commands, "manifest_sha256"
        )
        _write_json(output / command_ref, per_workpack_commands)
        command_sha256 = _file_hash(output / command_ref)
        capsule = {
            "schema_version": "2.8",
            "program_id": context["program_id"],
            "project_id": project_id,
            "workpack_id": workpack_id,
            "status": "PLANNED_NOT_HYDRATED",
            "profile_lock_hash": index["profile_lock_hash"],
            "charter_hash": index["charter_hash"],
            "control_plane_epoch": index["control_plane_epoch"],
            "requires": list(contract["requires"]),
            "requirement_sources": dict(contract["requirement_sources"]),
            "produces": list(contract["produces"]),
            "command_ids": command_ids,
            "intent_atom_ids": intent_atom_ids,
            "command_manifest_ref": command_ref,
            "command_manifest_sha256": command_sha256,
            "allowed_read_paths": allowed_read_paths,
            "job_artifact_read_scopes": job_artifact_read_scopes,
            "job_artifact_write_scopes": job_artifact_write_scopes,
            "allowed_write_paths": allowed_write_paths,
            "job_artifact_scope_activation_policy": job_scope_activation_policy,
            "active_job_artifact_lease_ref": None,
            "case_result_write_root": (
                auxiliary_write_roots[0] if auxiliary_write_roots else None
            ),
            "repository_root_abs": str(repository),
            "repository_status": "PLANNED_NOT_CREATED",
            "execution_authorization_ref": None,
            "hydration_complete": False,
            "success_rule": success_rule,
            "return_node": workpack["program_control_node_id"],
        }
        if task_bundle is not None and task_bundle_ref is not None:
            capsule.update(
                {
                    "semantic_hydration_complete": True,
                    "task_bundle_ref": task_bundle_ref,
                    "task_bundle_sha256": _file_hash(output / task_bundle_ref),
                    "artifact_obligation_manifest_ref": ARTIFACT_MANIFEST_REF,
                    "artifact_obligation_manifest_sha256": artifact_manifest[
                        "manifest_sha256"
                    ],
                    "production_contract_ids": list(
                        task_bundle["production_contract_ids"]
                    ),
                    "required_artifact_ids": required_artifact_ids,
                    "required_artifact_refs": required_artifact_refs,
                }
            )
        _write_json(output / capsule_ref, capsule)
        capsule_sha256 = _file_hash(output / capsule_ref)
        result = {
            "schema_version": "2.8",
            "program_id": context["program_id"],
            "project_id": project_id,
            "workpack_id": workpack_id,
            "status": "NOT_RUN",
            "required_capabilities": list(contract["requires"]),
            "expected_capabilities": list(contract["produces"]),
            "intent_atom_ids": intent_atom_ids,
            "command_manifest_ref": command_ref,
            "command_manifest_sha256": command_sha256,
            "capsule_ref": capsule_ref,
            "capsule_sha256": capsule_sha256,
            "command_receipts": [],
            "evidence_refs": [],
            "promotion_eligible": False,
        }
        if task_bundle is not None and task_bundle_ref is not None:
            result.update(
                {
                    "semantic_hydration_complete": True,
                    "task_bundle_ref": task_bundle_ref,
                    "task_bundle_sha256": _file_hash(output / task_bundle_ref),
                    "artifact_obligation_manifest_ref": ARTIFACT_MANIFEST_REF,
                    "artifact_obligation_manifest_sha256": artifact_manifest[
                        "manifest_sha256"
                    ],
                    "production_contract_ids": list(
                        task_bundle["production_contract_ids"]
                    ),
                    "expected_artifact_ids": required_artifact_ids,
                    "expected_artifact_refs": required_artifact_refs,
                }
            )
        _write_json(output / result_ref, result)
        loop = {
            "schema_version": "2.8",
            "program_id": context["program_id"],
            "project_id": project_id,
            "workpack_id": workpack_id,
            "status": "NOT_STARTED",
            "current_iteration": 0,
            "max_iterations": 3,
            "authorization_ref": None,
            "last_finding_id": None,
            "promotion_eligible": False,
        }
        _write_json(output / loop_ref, loop)
        workpack.update(
            {
                "workpack_sha256": _file_hash(output / workpack_ref),
                "command_manifest_sha256": command_sha256,
                "capsule_sha256": capsule_sha256,
                "result_sha256": _file_hash(output / result_ref),
                "loop_state_sha256": _file_hash(output / loop_ref),
            }
        )
        if task_bundle is not None and task_bundle_ref is not None:
            workpack["task_bundle_sha256"] = _file_hash(output / task_bundle_ref)
    _write_json(index_path, index)


def _materialize_project_packages(
    staging: Path,
    spec: Path,
    ir: Mapping[str, Any],
    context: Mapping[str, str],
    candidate: Path,
    artifact_manifest: Mapping[str, Any] | None,
) -> None:
    execution = Path(context["execution_root"])
    template_root = spec / "templates/project_start_packages"
    role_map = {
        "external_lab": "EXTERNAL_CONFORMANCE_LAB",
        "linkage_review": "READ_ONLY_LINKAGE_REVIEW",
        "main_build": "MAIN_BUILD_PROJECT",
    }
    reverse = {directory: project_id for project_id, directory in PROJECTS}
    charter_lock = json.loads((staging / "CHARTER_LOCK.json").read_text(encoding="utf-8"))
    project_binding = {
        "program_id": context["program_id"],
        "profile_lock_hash": charter_lock["profile_lock_sha256"],
        "charter_hash": charter_lock["charter_sha256"],
        "control_plane_epoch": 0,
    }
    for directory in role_map:
        project_id = reverse[directory]
        output = staging / "project_start_packages" / directory
        project_context = {**context, "project_id": project_id, "project_directory": directory}
        for source in sorted((template_root / directory).iterdir()):
            if not source.is_file():
                continue
            destination_name = source.name.replace(".template", "")
            destination = output / destination_name
            if source.suffix == ".json":
                document = _resolve_value(json.loads(source.read_text(encoding="utf-8")), project_context, f"project/{directory}/{destination_name}")
                document.update(project_binding)
                if destination_name == "PROJECT_STATE.json":
                    document.update(
                        {
                            "project_id": project_id,
                            "program_id": context["program_id"],
                            "project_role": role_map[directory],
                            "state": "PLANNED_NOT_STARTED",
                            "current_workpack_id": None,
                            "auto_advance_enabled": False,
                            "execution_authorization_ref": None,
                            "next_eligible_transition": "HUMAN_REVIEW_AND_REGISTRATION",
                            "valid_locks": [],
                            "invalidated_locks": [],
                            "blockers": ["START_PACKAGE_HUMAN_REVIEW_REQUIRED"],
                        }
                    )
                    if directory == "main_build":
                        document["current_phase"] = None
                elif destination_name == "WORKPACK_INDEX.json":
                    document.update({"project_id": project_id, "auto_start_next_workpack": False})
                    for position, workpack in enumerate(
                        document.get("workpacks", []), 1
                    ):
                        workpack_id = str(workpack.get("workpack_id"))
                        dag_node_id = next(
                            (
                                node_id
                                for node_id, bound_id in DAG_WORKPACK_BINDINGS.items()
                                if bound_id == workpack_id
                            ),
                            None,
                        )
                        if dag_node_id is None:
                            dag_node_id = next(
                                (
                                    node_id
                                    for node_id, sequence in DAG_WORKPACK_SEQUENCE_BINDINGS.items()
                                    if workpack_id in sequence
                                ),
                                None,
                            )
                        release_step_id = next(
                            (
                                step_id
                                for step_id, bound_id in RELEASE_WORKPACK_BINDINGS.items()
                                if bound_id == workpack_id
                            ),
                            None,
                        )
                        surface = (
                            "ENGINEERING_PROJECT_DAG"
                            if dag_node_id
                            else "RELEASE_PIPELINE"
                            if release_step_id
                            else "UNBOUND"
                        )
                        control_id = dag_node_id or release_step_id
                        workpack.update(
                            {
                                "status": "PLANNED_NOT_ACTIVE",
                                "topological_order": position,
                                "program_control_surface": surface,
                                "program_control_node_id": control_id,
                                "program_control_binding_status": (
                                    "PLANNED_BOUND" if control_id else "INVALID_UNBOUND"
                                ),
                            }
                        )
                elif destination_name == "COMMAND_MANIFEST.json":
                    planned_python = execution / "project_start_packages" / directory / ".venv/bin/python"
                    document.update(
                        {
                            "project_id": project_id,
                            "default_disposition": "DECLARE_ONLY",
                            "execution_started": False,
                        }
                    )
                    for command in document.get("commands", []):
                        args = list(command.get("argv", []))
                        if not args or args[0] != str(planned_python):
                            args.insert(0, str(planned_python))
                        command.update(
                            {
                                "executable": str(planned_python),
                                "executable_abs": str(planned_python),
                                "cwd_absolute": str(
                                    execution
                                    / "project_start_packages"
                                    / directory
                                    / "repository"
                                ),
                                "authorization_ref": None,
                                "executable_status": "PLANNED_NOT_INSTALLED",
                                "preflight_gate": "VALID_EXECUTION_AUTHORIZATION",
                                "argv": args,
                                "command_kind": "LOCKED_TEMPLATE_VERIFICATION_COMMAND",
                                "invocation_contract_status": "LOCKED_V2_8_TEMPLATE_CLI_PENDING_INSTALL",
                                "unverified_cli_flags_forbidden": True,
                                "auto_execute": False,
                                "shell": False,
                            }
                        )
                        if "allowed_write_roots" in command:
                            command["allowed_write_roots"] = [
                                str(execution / "evidence" / directory)
                            ]
                    document["commands"].extend(
                        _project_planned_interface_commands(
                            directory, candidate, execution
                        )
                    )
                    for command in document["commands"]:
                        command["command_sha256"] = _hash_without_field(
                            command, "command_sha256"
                        )
                    document["manifest_sha256"] = _hash_without_field(
                        document, "manifest_sha256"
                    )
                _write_json(destination, document)
            else:
                source_text = source.read_text(encoding="utf-8")
                resolved = _resolve_value(
                    source_text,
                    {**project_context, "project_id": project_id},
                    f"project/{directory}/{destination_name}",
                )
                resolved_text = str(resolved).replace(".template.", ".").replace(
                    ".template.md", ".md"
                )
                text = (
                    f"Status: `PLANNED_NOT_STARTED`\n\n{resolved_text.rstrip()}\n\n"
                    "## Authoring boundary\n\n"
                    "This independent project Start Package is planned only. It has not "
                    "been built, installed, executed, linked, or certified. All commands "
                    "require the predecessor Gates and an explicit authorization.\n"
                )
                _write_text(destination, text)
        _materialize_project_workpack_contracts(
            output,
            project_id=project_id,
            directory=directory,
            coverage_edges=[
                item
                for item in ir.get("coverage_edges", [])
                if isinstance(item, Mapping)
            ],
            context=context,
            candidate=candidate,
            artifact_manifest=artifact_manifest,
        )


def _artifact_contract_markdown(
    artifact_manifest: Mapping[str, Any] | None,
) -> str:
    if not isinstance(artifact_manifest, Mapping):
        return """# Artifact and Interface Contracts

All future artifacts bind the frozen source, Atom, Charter, Profile, predecessor Lock, tool distribution, environment, command, evidence, and current Hash. A self-report, file presence, or exit code cannot independently promote a result.
"""
    lines = [
        "# Artifact and Interface Contracts",
        "",
        "## Plain-language meaning",
        "",
        "An Artifact Obligation is a frozen delivery promise: it names the exact output, its structure, how it must be produced, who or what judges it, and where control returns when it fails. A Task Bundle groups those promises for one Workpack so the execution agent does not invent the job from an Atom label.",
        "",
        f"- Production semantics mode: `{artifact_manifest['production_semantics_mode']}`",
        f"- Authoritative manifest: `{ARTIFACT_MANIFEST_REF}`",
        f"- Completion rule: `{artifact_manifest['completion_rule']}`",
        "",
        "## Compiled obligations",
    ]
    for contract in artifact_manifest["contracts"]:
        lines.extend(
            [
                "",
                f"### {contract['atom_id']} / {contract['contract_id']}",
            ]
        )
        for obligation in contract["workpack_obligations"]:
            lines.extend(
                [
                    "",
                    f"- Workpack: `{obligation['workpack_id']}`",
                    f"- Objective: {obligation['task_objective']}",
                    f"- Completion: {obligation['completion_rule']}",
                    "- Artifacts:",
                    *[
                        f"  - `{item['artifact_id']}` → `{item['artifact_ref']}`"
                        for item in obligation["artifact_obligations"]
                    ],
                ]
            )
    lines.extend(
        [
            "",
            "A capability label alone cannot close any obligation. Every required Artifact must satisfy its embedded Schema, validation rule, Oracle decision rule, and failure-return contract.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_markdown_documents(
    staging: Path,
    ir: Mapping[str, Any],
    context: Mapping[str, str],
    artifact_manifest: Mapping[str, Any] | None,
) -> None:
    target = ir["target"]
    epoch38_correction = target.get(
        "v2_9_charter_architecture_correction_epoch38"
    )
    local_profile_charter = bool(
        isinstance(epoch38_correction, Mapping)
        and target.get("operating_assurance_profile")
        == "SELF_USE_LOCAL_TRUSTED_OPERATOR"
    )
    if local_profile_charter:
        delivery_tiers = epoch38_correction.get("atom_delivery_tiers")
        if not isinstance(delivery_tiers, Mapping):
            raise ValueError("Epoch 38 Charter delivery tiers are missing")
        scope_lines: list[str] = []
        for item in target["scope"]:
            match = re.match(r"(P0-\d{2})\b", str(item))
            if match is None:
                scope_lines.append(f"- {item}")
                continue
            atom_id = f"ATOM-V29-{match.group(1)}"
            delivery_tier = delivery_tiers.get(atom_id)
            if delivery_tier not in {
                "CORE_IMPLEMENTATION",
                "POST_IMPLEMENTATION_VALIDATION",
                "OPTIONAL_SECURITY_HARDENING",
            }:
                raise ValueError(
                    f"Epoch 38 Charter delivery tier is missing for {atom_id}"
                )
            scope_lines.append(f"- `{delivery_tier}` {item}")
        scope = "\n".join(scope_lines)
        charter_mission = str(
            epoch38_correction.get("mission") or target["mission"]
        )
        profile_lines = (
            f"- Package shape profile: `{context['profile']}`\n"
            "- Assurance profile: `SELF_USE_LOCAL_TRUSTED_OPERATOR`"
        )
        delivery_priority = """
## Delivery priority

1. `CORE_IMPLEMENTATION` — implement owned modules and official entrypoints.
2. `POST_IMPLEMENTATION_VALIDATION` — prove implemented behavior and major failure paths.
3. `OPTIONAL_SECURITY_HARDENING` — run only when a separate profile and authority select it.

External Trust Anchor, independent certification, dual-Validator closure, and dynamic adversarial/tamper proof are optional and non-blocking for the default local profile. External certification claimed: `false`.
"""
        authority_extension = (
            "\n\nFactory SQLite, exact Freeze authority, and the append-only Event "
            "Ledger remain authoritative. Candidate self-check and receipts are "
            "diagnostic/evidence only; they cannot replace implementation or an "
            "applicable external Authority."
        )
    else:
        scope = "\n".join(f"- {item}" for item in target["scope"])
        charter_mission = str(target["mission"])
        profile_lines = f"- Profile: `{context['profile']}`"
        delivery_priority = ""
        authority_extension = ""
    non_goals = "\n".join(f"- {item}" for item in target["non_goals"]) or "- None beyond the explicit authoring boundary."
    documents = {
        "README.md": f"""# {context['target_name']} Start Package Candidate

This target-specific package is an authoring candidate governed by Harness Foundry v2.8.

Current state: `{TARGET_CANDIDATE_STATE}`
Mandatory stop: `AUTHORING_STOP`

It contains the Main, External Lab, and read-only Linkage project Start Packages plus the machine control contracts needed after separate human approval. It does not claim that any project, Driver, Workpack, Harness, install, linkage result, or certification exists.
""",
        "START_HERE.md": """# Start Here

Read `START_CONTEXT.json`, `PROGRAM_CHARTER.md`, `TARGET_PROFILE.md`, and `AUTHORING_HANDOFF.md`. The only legal next transition is human review of this candidate. Generated commands are declarative data and must not be run in this authoring boundary.
""",
        "START.md": """# Authoring Stop

```text
START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW
AUTHORING_STOP
execution_started = false
install_started = false
certification_started = false
```
""",
        "PROGRAM_CHARTER.md": f"""# Program Charter: {context['target_name']}

## Mission

{charter_mission}

## Target

- ID: `{context['target_id']}`
- Type: `{context['target_type']}`
{profile_lines}
- Primary runtime: `{target['primary_runtime']}`
{delivery_priority}

## Scope

{scope}

## Non-goals

{non_goals}

## Authority and completion

The Program Author may generate and statically validate this candidate only. Human approval, registration, engineering execution, release, certification, and real target installation are separate authorities and states. Completion of authoring proves only review readiness.{authority_extension}
""",
        "TARGET_PROFILE.md": f"""# Target Profile

- Target: `{context['target_id']}`
- Target type: `{context['target_type']}`
- Selected profile: `{context['profile']}`
- Primary runtime: `{target['primary_runtime']}`
- Profile status: `PENDING_HUMAN_APPROVAL`

The profile cannot be downgraded to make a later Gate pass.
""",
        "AUTHORITY_AND_EXECUTION_BOUNDARY.md": """# Authority and Execution Boundary

| Surface | Authoring writer | Later authority | Current state |
|---|---|---|---|
| Start Package Candidate | Program Author | Human Gate Owner | generated for review |
| Main Build | none | authorized Coding Agent | planned, not started |
| External Lab | none | independent Lab owner | planned, not started |
| Linkage Review | none | read-only Linkage owner | planned, not started |
| Real target | none | separately authorized Installer | forbidden in authoring |

The Build Program Driver and final Harness Runtime must remain distinct entrypoints. Pack is not Certificate; Linkage PASS is not Conformance PASS.
""",
        "ARTIFACT_AND_INTERFACE_CONTRACTS.md": _artifact_contract_markdown(
            artifact_manifest
        ),
        "VALIDATION_AND_REVIEW_PLAN.md": """# Validation and Review Plan

Validate structure, source and Atom coverage, Phase/DAG order, role separation, authorization defaults, negative false-success cases, repair routing, and Authoring Stop. Runtime, install, linkage, and certification checks remain planned and unexecuted.
""",
        "ROADMAP.md": """# Program Roadmap

After separate human approval and registration: verify the Driver; bootstrap and self-validate Lab; bootstrap and self-validate Linkage; materialize Main; execute G0/C0 through P4/C3 in order; build and isolate-install the artifact; run D and C4; stop again before real target installation.
""",
        "AUTHORING_HANDOFF.md": f"""# Authoring Handoff: {context['target_name']}

## Result

- Candidate state: `{TARGET_CANDIDATE_STATE}`
- Mandatory stop: `AUTHORING_STOP`
- Requirement IR Hash: `{context['ir_hash']}`
- First planned Workpack: `{context['first_workpack_id']}`
- Unique next transition: `HUMAN_REVIEW_OF_START_PACKAGE`

## Open questions and blockers

No blocking authoring questions remain. Any future scope, authority, Profile, P3 N/A, loop escalation, or real-install decision requires a new human decision bound to current Hashes.

## Non-claims

No Driver, Workpack, project bootstrap, Harness implementation, build, install, Linkage PASS, C4, Certificate, or release result was produced.
""",
    }
    for destination, text in documents.items():
        _write_text(staging / destination, text)


def _write_ledgers(staging: Path, context: Mapping[str, str]) -> None:
    ledgers = {
        "PHASE_TRANSITION_LEDGER.jsonl": {
            "event_id": "EVT-AUTHORING-INIT",
            "event_type": "AUTHORING_CANDIDATE_CREATED",
            "from_state": "UNINITIALIZED",
            "to_state": TARGET_CANDIDATE_STATE,
        },
        "PROMOTION_LEDGER.jsonl": {
            "event_id": "EVT-PROMOTION-INIT",
            "event_type": "INITIALIZATION_NO_PROMOTION",
        },
        "REVOCATION_LEDGER.jsonl": {
            "event_id": "EVT-REVOCATION-INIT",
            "event_type": "INITIALIZATION_NO_REVOCATION",
        },
    }
    for destination, fields in ledgers.items():
        event = {
            "schema_version": "2.8",
            **fields,
            "sequence": 1,
            "previous_event_hash": None,
            "program_id": context["program_id"],
            "actor_role": "PROGRAM_AUTHOR",
            "authorization_ref": "AUTHORING_SCOPE",
            "evidence_refs": ["validation/START_PACKAGE_VALIDATION_REPORT.json", "AUTHORING_HANDOFF.md"],
            "timestamp": context["created_at"],
        }
        event["event_hash"] = _json_hash(event)
        _write_text(staging / destination, json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def _write_factory_regression_execution_receipt(
    staging: Path,
    context: Mapping[str, str],
    *,
    validator_report: Mapping[str, Any],
) -> None:
    check = next(
        (
            item
            for item in validator_report.get("checks", [])
            if isinstance(item, Mapping)
            and item.get("check_id") == "FACTORY_REQUIRED_REGRESSION_EXECUTION"
        ),
        None,
    )
    evidence = (
        check.get("factory_regression_execution")
        if isinstance(check, Mapping)
        else None
    )
    if not isinstance(evidence, Mapping) or evidence.get("status") == "NOT_REQUIRED":
        return
    if check.get("status") != "PASS" or evidence.get("status") != "PASS":
        raise ValueError("Factory required regression execution did not PASS")
    receipt = {
        **deepcopy(dict(evidence)),
        "receipt_id": "FACTORY_REGRESSION_EXECUTION_RECEIPT",
        "requirement_ir_sha256": context["ir_hash"],
    }
    receipt["receipt_sha256"] = _hash_without_field(
        receipt, "receipt_sha256"
    )
    _write_json(staging / FACTORY_REGRESSION_EXECUTION_RECEIPT_REF, receipt)


def _validation_check_evidence_refs(check_id: Any) -> list[str]:
    """Return check-specific Candidate evidence instead of a generic bundle."""

    check = str(check_id or "")
    if check == "EXECUTABLE_ACCEPTANCE_AND_ORACLE_CONTRACTS":
        return [
            "validation/PUBLIC_SKILL_JOB_INTERFACE.json",
            "validation/CASE_EXECUTION_MANIFEST.json",
            "validation/ORACLE_EVALUATOR_REGISTRY.json",
            "validation/ACCEPTANCE_CASES.json",
            "validation/NEGATIVE_CASES.json",
            "validation/schemas/CASE_RESULT.schema.json",
            "validation/schemas/REGISTRY_CASE_RESULT.schema.json",
            "validation/schemas/REGISTRY_CASE_EXECUTION_RECEIPT.schema.json",
            "project_start_packages/external_lab/commands/LAB-CERTIFICATION.commands.json",
        ]
    if check == "SEMANTIC_PRODUCTION_CONTRACTS":
        return [
            "canonical_sources/FROZEN_REQUIREMENT_IR.json",
            "canonical_sources/NORMATIVE_ATOM_CATALOG.json",
            "canonical_sources/ATOM_COVERAGE_MATRIX.json",
        ]
    if check == "WORKPACK_ARTIFACT_HASH_BINDINGS":
        return [
            "PACKAGE_MANIFEST.json",
            "PHASE_DEPENDENCY_MANIFEST.json",
            "ENGINEERING_PROJECT_DAG.json",
        ]
    if check in {
        "SOURCE_ATOM_AND_COVERAGE",
        "AUTHORITATIVE_SOURCE_REGISTRY",
    }:
        return [
            "canonical_sources/SOURCE_MANIFEST.json",
            "canonical_sources/NORMATIVE_ATOM_CATALOG.json",
            "canonical_sources/ATOM_COVERAGE_MATRIX.json",
        ]
    if check in {
        "IDENTITY_REFERENCES_AND_HASHES",
        "PACKAGE_LIFECYCLE_IDENTITY",
        "LOGICAL_TARGET_ROOT_BINDING",
    }:
        return [
            "PACKAGE_MANIFEST.json",
            "START_CONTEXT.json",
            "FACTORY_PROVENANCE.json",
        ]
    if check in {
        "CANDIDATE_IMMUTABILITY_AND_EXECUTION_ROOT",
        "PHYSICAL_CANDIDATE_READ_ONLY",
    }:
        return ["START_CONTEXT.json", "CAPSULE.json"]
    if check in {
        "PHASE_P3_AND_RELEASE_ORDER",
        "THREE_PROJECT_DAG_AND_PACKAGES",
    }:
        return [
            "PHASE_DEPENDENCY_MANIFEST.json",
            "ENGINEERING_PROJECT_DAG.json",
            "RELEASE_PIPELINE_MANIFEST.json",
        ]
    if check == "VALIDATION_HANDOFF_AND_NONCLAIMS":
        return ["AUTHORING_HANDOFF.md", "START.md", "README.md"]
    return [
        "PACKAGE_MANIFEST.json",
        "canonical_sources/FROZEN_REQUIREMENT_IR.json",
        "ENGINEERING_PROJECT_DAG.json",
    ]


def _write_validation_report(
    staging: Path,
    context: Mapping[str, str],
    *,
    validator_report: Mapping[str, Any] | None = None,
    repair_attempts: int = 0,
) -> None:
    validated = validator_report is not None and validator_report.get("status") == "PASS"
    checks = []
    if validator_report:
        checks = [
            {
                "check_id": item.get("check_id"),
                "status": (
                    "DEFERRED_NOT_OBSERVED"
                    if item.get("check_id")
                    == "PHYSICAL_CANDIDATE_READ_ONLY"
                    and item.get("validation_basis")
                    == "PREPUBLICATION_STAGING_NOT_YET_SEALED"
                    else item.get("status")
                ),
                "finding_count": len(item.get("findings", [])),
                "evidence_refs": _validation_check_evidence_refs(
                    item.get("check_id")
                ),
                **(
                    {
                        "observation_status": (
                            "NOT_OBSERVED_PREPUBLICATION"
                        )
                    }
                    if item.get("check_id")
                    == "PHYSICAL_CANDIDATE_READ_ONLY"
                    and item.get("validation_basis")
                    == "PREPUBLICATION_STAGING_NOT_YET_SEALED"
                    else {}
                ),
                **(
                    {"authority_input": item.get("authority_input")}
                    if "authority_input" in item
                    else {}
                ),
                **(
                    {
                        "authority_provenance": deepcopy(
                            item.get("authority_provenance")
                        )
                    }
                    if "authority_provenance" in item
                    else {}
                ),
                **(
                    {"validation_basis": item.get("validation_basis")}
                    if "validation_basis" in item
                    else {}
                ),
                **(
                    {
                        "factory_regression_execution": deepcopy(
                            item.get("factory_regression_execution")
                        )
                    }
                    if "factory_regression_execution" in item
                    else {}
                ),
            }
            for item in validator_report.get("checks", [])
        ]
    report = {
        "schema_version": "2.8",
        "report_id": f"REPORT-{context['target_id']}-AUTHORING",
        "package_id": context["package_id"],
        "requirement_ir_sha256": context["ir_hash"],
        "status": "PASS" if validated else "PENDING_VALIDATION",
        "scope": "AUTHORING_ONLY_STATIC_VALIDATION",
        "validator_id": validator_report.get("validator_id") if validator_report else None,
        "checks": checks,
        "blocking_findings": list(validator_report.get("blocking_findings", []))
        if validator_report
        else [],
        "repair_attempts": repair_attempts,
        "permitted_terminal_state": TARGET_CANDIDATE_STATE,
        "writes_performed": False,
        "runtime_tests_executed": False,
        "factory_regression_tests_executed": bool(
            validator_report and validator_report.get("commands_executed")
        ),
        "non_claims": [
            "HARNESS_IMPLEMENTED",
            "PROGRAM_DRIVER_STARTED",
            "WORKPACK_EXECUTED",
            "THREE_PROJECTS_BUILT",
            "LINKAGE_PASS",
            "CONFORMANCE_CERTIFIED",
            "INSTALLED",
        ],
    }
    _write_json(staging / "validation/START_PACKAGE_VALIDATION_REPORT.json", report)


def _write_validation_report_receipt(
    staging: Path,
    context: Mapping[str, str],
    *,
    authority_provenance: Mapping[str, Any] | None,
    local_profile: bool = False,
) -> None:
    report_path = staging / VALIDATION_REPORT_REF
    report = json.loads(report_path.read_text(encoding="utf-8"))
    package_identity = json.loads(
        (staging / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8")
    )
    if local_profile:
        profile_ref = "EPOCH38_GENERATION_PROFILE.json"
        profile_path = staging / profile_ref
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        local_checks = sorted(
            [
                deepcopy(check)
                for check in report.get("checks", [])
                if str(check.get("check_id") or "").startswith(
                    "FACTORY_LOCAL_"
                )
            ],
            key=lambda check: str(check.get("check_id") or ""),
        )
        if (
            report.get("status") != "PASS"
            or report.get("blocking_findings") != []
            or len(local_checks) != 2
            or any(check.get("status") != "PASS" for check in local_checks)
            or any(
                str(check.get("check_id") or "").startswith(
                    "FACTORY_EXTERNAL_"
                )
                for check in report.get("checks", [])
            )
            or profile.get("assurance_profile")
            != "SELF_USE_LOCAL_TRUSTED_OPERATOR"
            or profile.get("external_certification_claimed") is not False
            or profile.get("optional_security_hardening") != "NOT_RUN"
        ):
            raise ValueError(
                "Epoch 38 local validation receipt prerequisites are incomplete"
            )
        receipt = {
            "schema_version": "2.9",
            "receipt_id": "EPOCH38_LOCAL_VALIDATION_REPORT_RECEIPT",
            "receipt_policy": "SELF_USE_LOCAL_PROFILE_VALIDATION_RECEIPT",
            "report_ref": VALIDATION_REPORT_REF,
            "report_sha256": _file_hash(report_path),
            "report_id": report.get("report_id"),
            "program_id": context["program_id"],
            "package_id": context["package_id"],
            "candidate_version": package_identity.get("candidate_version"),
            "requirement_epoch": package_identity.get("requirement_epoch"),
            "architecture_epoch": 4,
            "control_plane_epoch": 4,
            "requirement_ir_sha256": context["ir_hash"],
            "profile_ref": profile_ref,
            "profile_sha256": _file_hash(profile_path),
            "assurance_profile": "SELF_USE_LOCAL_TRUSTED_OPERATOR",
            "validator_id": report.get("validator_id"),
            "validator_status_before_publication": "PASS",
            "validation_scope": (
                "LOCAL_ENGINEERING_CORE_NOT_EXTERNAL_CERTIFICATION"
            ),
            "external_authority_provenance_required": False,
            "external_certification_claimed": False,
            "independent_certification_claimed": False,
            "optional_security_hardening": "NOT_RUN",
            "closure_claimed": False,
            "human_review_approved": False,
            "publication_precondition": "OFFICIAL_VALIDATOR_PASS",
            "binding_authority": (
                "EPOCH38_FROZEN_PROFILE_AND_PREPUBLICATION_VALIDATOR"
            ),
        }
        receipt["receipt_sha256"] = _hash_without_field(
            receipt, "receipt_sha256"
        )
        _write_json(staging / VALIDATION_REPORT_RECEIPT_REF, receipt)
        return

    external_checks = sorted(
        [
            deepcopy(check)
            for check in report.get("checks", [])
            if str(check.get("check_id") or "").startswith(
                "FACTORY_EXTERNAL_"
            )
        ],
        key=lambda check: str(check.get("check_id") or ""),
    )
    if (
        len(external_checks) != 2
        or not isinstance(authority_provenance, Mapping)
        or any(
            check.get("authority_provenance")
            != dict(authority_provenance)
            for check in external_checks
        )
    ):
        raise ValueError(
            "validation report external Authority provenance is incomplete"
        )
    receipt = {
        "schema_version": "1.0",
        "receipt_id": "START_PACKAGE_VALIDATION_REPORT_RECEIPT",
        "report_ref": VALIDATION_REPORT_REF,
        "report_sha256": _file_hash(report_path),
        "report_id": report.get("report_id"),
        "program_id": context["program_id"],
        "package_id": context["package_id"],
        "candidate_version": package_identity.get("candidate_version"),
        "requirement_epoch": package_identity.get("requirement_epoch"),
        "requirement_ir_sha256": context["ir_hash"],
        "authority_provenance": dict(authority_provenance),
        "external_authority_checks_sha256": _json_hash(external_checks),
        "binding_authority": (
            "FACTORY_EVENT_STORE_AND_RECEIVER_SIGNED_SOURCE_AUTHORITY_POLICY"
        ),
    }
    receipt["receipt_sha256"] = _hash_without_field(
        receipt, "receipt_sha256"
    )
    _write_json(staging / VALIDATION_REPORT_RECEIPT_REF, receipt)


def _recover_existing_candidate(
    candidate: Path,
    *,
    requirement_ir_sha256: str,
    spec_content_sha256: str,
    authoritative_sources: Sequence[Mapping[str, Any]] | None = None,
    authoritative_requirement_ir: Mapping[str, Any] | None = None,
    authority_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not candidate.exists():
        return None
    if not candidate.is_dir() or not any(candidate.iterdir()):
        if candidate.is_dir():
            candidate.rmdir()
            return None
        raise FileExistsError(f"candidate root is not a directory: {candidate}")
    provenance_path = candidate / "FACTORY_PROVENANCE.json"
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise FileExistsError(f"candidate root is not empty: {candidate}") from None
    if (
        provenance.get("factory_id") != FACTORY_ID
        or provenance.get("requirement_ir_sha256") != requirement_ir_sha256
        or provenance.get("spec_content_sha256") != spec_content_sha256
    ):
        raise FileExistsError(f"candidate root is not empty: {candidate}")
    from .validator import validate_candidate

    report = validate_candidate(
        candidate,
        authoritative_sources=authoritative_sources,
        authoritative_requirement_ir=authoritative_requirement_ir,
        authority_provenance=authority_provenance,
    )
    if report.get("status") != "PASS":
        raise FileExistsError(
            "matching Factory candidate exists but no longer validates; refusing overwrite"
        )
    content_hash, file_count = _tree_hash(candidate)
    return {
        "program_id": provenance.get("program_id"),
        "target_id": provenance.get("target_id"),
        "candidate_path": str(candidate),
        "manifest_path": str(candidate / "PACKAGE_MANIFEST.json"),
        "file_count": file_count,
        "content_sha256": content_hash,
        "authoring_terminal_state": TARGET_CANDIDATE_STATE,
        "execution_started": False,
        "recovered_existing_candidate": True,
    }


def _repair_structural_hashes(staging: Path) -> None:
    """Repair only derived hashes; never alter requirements or semantic contracts."""

    source_path = staging / "canonical_sources/SOURCE_MANIFEST.json"
    catalog_path = staging / "canonical_sources/NORMATIVE_ATOM_CATALOG.json"
    matrix_path = staging / "canonical_sources/ATOM_COVERAGE_MATRIX.json"
    if source_path.is_file() and catalog_path.is_file():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        catalog["source_manifest_sha256"] = _file_hash(source_path)
        _write_json(catalog_path, catalog)
    if source_path.is_file() and catalog_path.is_file() and matrix_path.is_file():
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        matrix["source_manifest_sha256"] = _file_hash(source_path)
        matrix["normative_atom_catalog_sha256"] = _file_hash(catalog_path)
        _write_json(matrix_path, matrix)
    charter_lock_path = staging / "CHARTER_LOCK.json"
    charter_path = staging / "PROGRAM_CHARTER.md"
    profile_lock_path = staging / "PROFILE_LOCK.json"
    if (
        charter_lock_path.is_file()
        and charter_path.is_file()
        and source_path.is_file()
        and catalog_path.is_file()
        and profile_lock_path.is_file()
    ):
        charter_lock = json.loads(charter_lock_path.read_text(encoding="utf-8"))
        profile_lock = json.loads(profile_lock_path.read_text(encoding="utf-8"))
        charter_lock["charter_sha256"] = _file_hash(charter_path)
        charter_lock["source_manifest_sha256"] = _file_hash(source_path)
        charter_lock["normative_atom_catalog_sha256"] = _file_hash(catalog_path)
        charter_lock["profile_lock_sha256"] = _json_hash(profile_lock)
        _write_json(charter_lock_path, charter_lock)
    index_path = staging / "WORKPACK_INDEX.json"
    if not index_path.is_file():
        return
    index = json.loads(index_path.read_text(encoding="utf-8"))
    workpacks = index.get("workpacks", [])
    if len(workpacks) != 1 or not isinstance(workpacks[0], dict):
        return
    item = workpacks[0]
    workpack_path = staging / str(item.get("workpack_ref"))
    command_path = staging / str(item.get("command_manifest_ref"))
    capsule_path = staging / str(item.get("capsule_ref"))
    result_path = staging / str(item.get("result_ref"))
    if not all(path.is_file() for path in (workpack_path, command_path, capsule_path, result_path)):
        return
    command = json.loads(command_path.read_text(encoding="utf-8"))
    for command_item in command.get("commands", []):
        if isinstance(command_item, dict):
            if command_item.get("command_kind") == "PLANNED_EXECUTOR_INTERFACE":
                command_item["command_sha256"] = _hash_without_field(
                    command_item, "command_sha256"
                )
            else:
                command_item["command_sha256"] = _stable_hash(
                    {
                        "argv": command_item.get("argv"),
                        "cwd": command_item.get("cwd_abs"),
                    }
                )
    command_without_hash = dict(command)
    command_without_hash.pop("manifest_sha256", None)
    command["manifest_sha256"] = _stable_hash(command_without_hash)
    _write_json(command_path, command)
    _write_json(staging / "COMMAND_MANIFEST.json", command)
    capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
    capsule["capsule_sha256"] = None
    capsule["workpack_sha256"] = _file_hash(workpack_path)
    capsule["command_manifest_sha256"] = _file_hash(command_path)
    _write_json(capsule_path, capsule)
    _write_json(staging / "CAPSULE.json", capsule)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["capsule_sha256"] = _file_hash(capsule_path)
    result["command_manifest_sha256"] = _file_hash(command_path)
    _write_json(result_path, result)
    _write_json(staging / "WORKPACK_RESULT.json", result)


def _resolve_value(value: Any, context: Mapping[str, str], path: str) -> Any:
    if isinstance(value, dict):
        return {key: _resolve_value(item, context, f"{path}.{key}") for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_value(item, context, f"{path}[{index}]") for index, item in enumerate(value)]
    if not isinstance(value, str):
        return value

    full_token = PLACEHOLDER_RE.fullmatch(value)
    if full_token:
        return _token_value(full_token.group(0)[1:-1], context, path)

    def replace(match: re.Match[str]) -> str:
        replacement = _token_value(match.group(0)[1:-1], context, path)
        return "PLANNED_NOT_AVAILABLE" if replacement is None else str(replacement)

    return PLACEHOLDER_RE.sub(replace, value)


def _token_value(token: str, context: Mapping[str, str], path: str) -> Any:
    upper = token.upper()
    if "AGENT|HARNESS|HYBRID" in upper:
        return context["target_type"]
    if "FULL|STANDARD|LITE" in upper:
        return context["profile"]
    if "START_PACKAGE_DRAFT_AUTHORING_CANDIDATE|START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW" in upper:
        return TARGET_CANDIDATE_STATE
    if upper == "PROGRAM-ID":
        return context["program_id"]
    if upper in {"TARGET-ID", "AGENT-OR-HARNESS-ID"}:
        return context["target_id"]
    if upper in {"TARGET-START-PACKAGE-ID", "TARGET-PACKAGE-ID"}:
        return context["package_id"]
    if upper == "TARGET-NAME" or upper == "TARGET-NAME-OR-ID":
        return context["target_name"]
    if upper == "WP-G0-ID" or upper == "WORKPACK-ID":
        return context["first_workpack_id"]
    if upper in {
        "EXTERNAL-LAB-PROJECT-ID",
        "LINKAGE-REVIEW-PROJECT-ID",
        "MAIN-BUILD-PROJECT-ID",
    }:
        return context.get("project_id", f"PROJECT-{context['target_id']}")
    if upper == "HARNESS-ID":
        return context["target_id"]
    if "RFC3339" in upper:
        return context["created_at"]
    if "SHA256" in upper or "HASH" in upper:
        return None
    if "TRUE|FALSE" in upper:
        return False
    if "|" in token:
        return None
    if "ABSOLUTE" in upper and "PATH" in upper or "ROOT" in upper:
        slug = _slug(token)
        return str(Path(context["execution_root"]) / "planned" / slug)
    if upper.endswith("-REF") or "REF-OR" in upper:
        return None
    if upper.endswith("-ID") or "-ID-" in upper:
        return f"{_slug(token)}-{context['target_id']}"
    if "MODE" in upper:
        return "WORKPACK_EXECUTION"
    if "ENV" in upper:
        return "CANDIDATE_SANDBOX_PLANNED_NOT_CREATED"
    if "OWNER" in upper or "ROLE" in upper:
        return None
    if "REASON" in upper or "SUMMARY" in upper:
        return f"Planned authoring value for {context['target_name']}"
    if "INTEGER" in upper:
        return 0
    return None


def _is_opaque_authority_history_pointer(
    relative_path: str,
    pointer: tuple[str, ...],
) -> bool:
    return any(
        pointer[: len(prefix)] == prefix
        for prefix in OPAQUE_AUTHORITY_HISTORY_SUBTREES.get(relative_path, ())
    )


def _text_contains_unresolved_template_marker(text: str) -> bool:
    return bool(
        PLACEHOLDER_RE.search(text)
        or "/absolute/path/to/" in text
        or "TBD" in text
        or "TODO" in text
    )


def _json_value_contains_unresolved_template_marker(
    value: Any,
    *,
    relative_path: str,
    pointer: tuple[str, ...] = (),
) -> bool:
    if _is_opaque_authority_history_pointer(relative_path, pointer):
        return False
    if isinstance(value, Mapping):
        return any(
            _text_contains_unresolved_template_marker(str(key))
            or _json_value_contains_unresolved_template_marker(
                item,
                relative_path=relative_path,
                pointer=(*pointer, str(key)),
            )
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(
            _json_value_contains_unresolved_template_marker(
                item,
                relative_path=relative_path,
                pointer=(*pointer, str(index)),
            )
            for index, item in enumerate(value)
        )
    return isinstance(value, str) and _text_contains_unresolved_template_marker(value)


def _file_contains_unresolved_template_marker(path: Path, relative_path: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return _text_contains_unresolved_template_marker(text)
        return _json_value_contains_unresolved_template_marker(
            value,
            relative_path=relative_path,
        )
    if path.suffix == ".jsonl":
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                return _text_contains_unresolved_template_marker(text)
            if _json_value_contains_unresolved_template_marker(
                value,
                relative_path=relative_path,
            ):
                return True
        return False
    return _text_contains_unresolved_template_marker(text)


def _scan_placeholders(root: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in {".md", ".json", ".jsonl"}:
            continue
        relative_path = path.relative_to(root).as_posix()
        if _file_contains_unresolved_template_marker(path, relative_path):
            findings.append(relative_path)
    return findings


def _write_json(path: Path, value: Any) -> None:
    _write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _hash_without_field(value: Mapping[str, Any], field: str) -> str:
    document = deepcopy(dict(value))
    document.pop(field, None)
    return _stable_hash(document)


def _json_hash(value: Any) -> str:
    return _stable_hash(value)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_hash(root: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_file_hash(path).encode("ascii"))
        digest.update(b"\n")
        count += 1
    return digest.hexdigest(), count


def _seal_candidate_tree(root: Path) -> None:
    """Physically enforce the post-publication read-only Candidate contract."""

    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink():
            raise ValueError(f"candidate publication cannot seal symlink: {path}")
        path.chmod(path.stat().st_mode & ~0o222)
    root.chmod(root.stat().st_mode & ~0o222)
    writable = [
        path.relative_to(root).as_posix() if path != root else "."
        for path in (root, *sorted(root.rglob("*")))
        if path.lstat().st_mode & 0o222
    ]
    if writable:
        raise ValueError(
            "candidate publication could not enforce physical read-only state: "
            f"{writable}"
        )


def _slug(value: str) -> str:
    result = re.sub(r"[^A-Z0-9]+", "-", value.upper()).strip("-")
    return result or "VALUE"
