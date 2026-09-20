"""Epoch 2 producer, independent-oracle, and release-closure regression tests."""

from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Mapping
import unittest
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import harness_foundry_factory.authority_adapter as authority_adapter_module

from harness_foundry_factory.closure_lanes import (
    ClosureLaneError,
    derive_anti_replay_token,
    evaluate_final_release,
    seal_receipt,
)
from harness_foundry_factory.authority_adapter import (
    AuthorityAdapterError,
    LOGICAL_DATABASE_REF,
    ReleaseArtifactBytesResolver,
    SQLiteEventStoreAuthorityAdapter,
    adapter_entrypoint_sha256,
    build_adapter_binding,
)
from harness_foundry_factory.complexity_governor import evaluate_complexity
from harness_foundry_factory.compiler import (
    _epoch35_runtime_binding_path_atomicity_remediation_is_complete,
    _release_history_semantic_entries,
    compile_candidate,
    source_authority_policy_lock,
    source_authority_registry_tip_sha256,
    source_authority_trust_anchor,
)
from harness_foundry_factory.evidence_projection import (
    ProjectionConflictError,
    rebuild_projection,
)
from harness_foundry_factory.identity_derivation import (
    IdentityDerivationError,
    build_machine_grant_binding,
    classify_identity_change,
    derive_identity_bundle,
)
from harness_foundry_factory.recovery_decision import decide_recovery
from harness_foundry_factory.service import FactoryService
from harness_foundry_factory.store import ControlEventStore, SQLiteEventStore
from harness_foundry_factory.validator import (
    _epoch35_runtime_binding_path_atomicity_is_complete,
    _factory_required_regression_execution,
    validate_candidate,
)
from tests.permissions import make_path_writable


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SPEC_ROOT = REPOSITORY_ROOT.parent / "Harness_Foundry_v2_8_Start_Package"
FIXTURE_PATH = REPOSITORY_ROOT / "tests/fixtures/harness_requirement_ir.json"
EPOCH2_IDS = [f"CORR-29-{index:03d}" for index in range(9, 14)]
EPOCH2_ARTIFACTS = [
    "V2_9_RELEASE_CLOSURE_CONTROL_PLANE_MANIFEST.json",
    "SEMANTIC_IMPLEMENTATION_AUTHORIZATION_IDENTITY_CONTRACT.json",
    "GENERIC_RECOVERY_DECISION_PROTOCOL.json",
    "COMPLEXITY_GOVERNOR.json",
    "PRODUCT_SAFETY_RELEASE_CLOSURE_GRAPH.json",
    "EVIDENCE_LIFECYCLE_AND_PROJECTION_CONTRACT.json",
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
    "tools/harness_foundry_runtime/identity_derivation.py",
    "tools/harness_foundry_runtime/recovery_decision.py",
    "tools/harness_foundry_runtime/complexity_governor.py",
    "tools/harness_foundry_runtime/closure_lanes.py",
    "tools/harness_foundry_runtime/evidence_projection.py",
    "EVENT_STORE_AUTHORITY_ADAPTER_CONTRACT.json",
    "contracts/v2_9_release_closure/EVENT_STORE_AUTHORITY_ADAPTER_BINDING.schema.json",
    "tools/harness_foundry_runtime/authority_adapter.py",
    "contracts/v2_9_release_closure/SOURCE_AUTHORITY_POLICY_LOCK.schema.json",
    "tools/harness_foundry_runtime/store.py",
    "tools/harness_foundry_runtime/models.py",
    "tools/harness_foundry_runtime/constants.py",
]


def epoch32_runtime_binding_remediation() -> dict:
    return {
        "active_epochs": {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 32,
        },
        "status": "REQUIRED_IN_REPLACEMENT_CANDIDATE",
        "closure_receipt_required": True,
        "closure_receipt_status": (
            "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT"
        ),
        "candidate_resource_uri_closure_contract": {
            "scan_all_portable_text_resources": True,
            "candidate_root_uri_may_resolve_to_root_directory": True,
            "non_root_candidate_uri_must_resolve_to_physical_file": True,
            "target_must_be_in_portable_manifest_files_or_declared_exclusions": True,
            "missing_or_uninventoried_behavior": (
                "FAIL_CLOSED_BEFORE_PUBLICATION_OR_BINDING"
            ),
        },
        "runtime_dependency_closure_contract": {
            "retained_store_contract": True,
            "relative_import_dependency_scan_required": True,
            "required_runtime_module_refs": [
                "tools/harness_foundry_runtime/store.py",
                "tools/harness_foundry_runtime/models.py",
                "tools/harness_foundry_runtime/constants.py",
            ],
            "missing_dependency_behavior": "FAIL_CLOSED",
        },
        "runtime_binder_atomicity_contract": {
            "validate_complete_uri_and_inventory_before_first_execution_root_write": True,
            "fresh_root_same_parent_staging_required": True,
            "fresh_root_atomic_publish_required": True,
            "failure_cleanup_keeps_fresh_root_absent": True,
            "candidate_write_allowed": False,
            "human_gate_consumption_before_binding_success_allowed": False,
        },
        "independent_oracle_contract": {
            "factory_validator_full_uri_closure_required": True,
            "standalone_full_uri_closure_required": True,
            "factory_validator_calls_standalone": False,
            "standalone_calls_factory_validator": False,
        },
        "required_adversarial_cases": [
            "DANGLING_CANDIDATE_RESOURCE_URI",
            "CANDIDATE_RESOURCE_URI_OUTSIDE_PORTABLE_INVENTORY",
            "MISSING_PACKAGED_RUNTIME_RELATIVE_IMPORT",
            "BINDER_FAILURE_LEAVES_FRESH_EXECUTION_ROOT_ABSENT",
        ],
    }


def epoch33_runtime_binding_review_remediation() -> dict:
    return {
        "active_epochs": {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 33,
        },
        "status": "REQUIRED_IN_REPLACEMENT_CANDIDATE",
        "closure_receipt_required": True,
        "closure_receipt_status": (
            "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT"
        ),
        "finding_ids": [
            "HR-V032-001-BINDER-PREFLIGHT-INCOMPLETE",
            "HR-V032-002-ADVERSARIAL-DOMAIN-MISROUTED",
            "HR-V032-003-BINDER-HASH-ATOMICITY-UNBOUND",
            "HR-V032-004-STANDALONE-CASCADE-FALSE-FINDING",
        ],
        "review_report_source_id": "SRC-V29-V032-HUMAN-REVIEW-E33",
        "review_report_sha256": "3" * 64,
        "runtime_binder_preflight_contract": {
            "portable_manifest_before_first_execution_root_write": True,
            "all_candidate_uri_closure_before_first_execution_root_write": True,
            "runtime_dependency_closure_before_first_execution_root_write": True,
            "necessary_receiver_authority_before_first_execution_root_write": True,
        },
        "adversarial_domain_contract": {
            "epoch32_uri_binder_cases_owner": "RUNTIME_BINDER",
            "source_authority_domain_excludes_runtime_binder_cases": True,
            "runtime_binder_required_adversarial_cases": [
                "DANGLING_CANDIDATE_RESOURCE_URI",
                "CANDIDATE_RESOURCE_URI_OUTSIDE_PORTABLE_INVENTORY",
                "MISSING_PACKAGED_RUNTIME_RELATIVE_IMPORT",
                "BINDER_FAILURE_LEAVES_FRESH_EXECUTION_ROOT_ABSENT",
            ],
        },
        "setup_runtime_binding_contract": {
            "runtime_binding_contract_binds_setup_runtime_sha256": True,
            "closure_receipt_binds_setup_runtime_sha256": True,
            "validation_before_first_execution_root_write": True,
            "fresh_root_same_parent_staging_required": True,
            "fresh_root_atomic_publish_required": True,
            "failure_cleanup_keeps_fresh_root_absent": True,
        },
        "standalone_missing_authority_contract": {
            "missing_external_authority_root_finding_preserved": True,
            "dependent_adversarial_false_findings_suppressed": True,
        },
        "required_closures": [
            "Official Runtime Binder completes all preflight checks before the first Execution Root write",
            "Epoch 32 URI and Binder adversarial cases belong only to the Runtime Binder domain",
            "Runtime Binding Contract and Closure Receipt bind setup_runtime.py Hash and atomicity fields",
            "Missing receiver authority reports the root cause without dependent false findings",
        ],
    }


def epoch34_runtime_binding_review_remediation() -> dict:
    required_tests = [
        "test_epoch33_review_remediation_routes_to_producer_and_both_oracles",
        "test_runtime_binder_rejects_missing_dependency_before_root_write",
        "test_runtime_binder_rejects_dangling_uri_without_creating_root",
        "test_runtime_binder_rejects_portable_inventory_gap_without_creating_root",
        "test_runtime_binder_rejects_existing_root_by_default_and_allows_exact_reentry",
        "test_standalone_requires_receiver_side_source_authority_policy",
    ]
    return {
        "active_epochs": {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 34,
        },
        "status": "REQUIRED_IN_REPLACEMENT_CANDIDATE",
        "closure_receipt_required": True,
        "closure_receipt_status": (
            "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT"
        ),
        "closure_requirement_kind": (
            "RUNTIME_BINDER_AND_FACTORY_REGRESSION_HUMAN_REVIEW_REMEDIATION"
        ),
        "finding_ids": [
            "HR-V033-001-EXISTING-EXECUTION-ROOT-OVERWRITE",
            "HR-V033-002-REQUIRED-BINDER-REGRESSION-NOT-EXECUTED",
        ],
        "existing_execution_root_contract": {
            "fail_closed_by_default": True,
            "explicit_idempotent_reentry_allowed": True,
            "exact_existing_receipt_required": True,
            "receipt_overwrite_allowed": False,
        },
        "required_regression_execution_contract": {
            "factory_validator_executes_exact_hash_bound_tests": True,
            "candidate_publication_blocked_on_missing_test": True,
            "candidate_publication_blocked_on_failed_test": True,
            "closure_pass_requires_execution_receipt": True,
        },
        "implementation_evidence": {
            "regression_test_ref": "tests/test_release_closure_candidate.py",
            "regression_test_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
        },
        "required_regression_tests": required_tests,
        "required_closures": [
            "Existing Execution Root fails closed unless exact idempotent re-entry is explicitly requested",
            "Exact idempotent re-entry performs no receipt overwrite",
            "Factory Validator verifies required test definitions in the Hash-bound source",
            "Factory Validator executes every exact required regression selector and blocks publication on failure",
            "Closure PASS binds the Factory regression execution receipt",
        ],
    }


def epoch35_runtime_binding_path_atomicity_remediation() -> dict:
    required_tests = [
        *epoch34_runtime_binding_review_remediation()["required_regression_tests"],
        "test_epoch35_remediation_contract_is_accepted_by_both_oracles",
        "test_runtime_binder_rejects_dangling_execution_root_symlink",
        "test_runtime_binder_rejects_execution_root_symlink_to_existing_directory",
        "test_runtime_binder_atomic_noreplace_rejects_appeared_empty_root",
        "test_runtime_binder_rejects_parent_identity_swap",
        "test_runtime_binder_atomic_noreplace_rejects_target_symlink_swap",
    ]
    return {
        "active_epochs": {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 35,
        },
        "status": "REQUIRED_IN_REPLACEMENT_CANDIDATE",
        "closure_receipt_required": True,
        "closure_receipt_status": (
            "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT"
        ),
        "closure_requirement_kind": (
            "RUNTIME_BINDER_PATH_IDENTITY_AND_ATOMIC_NOREPLACE_REMEDIATION"
        ),
        "finding_ids": [
            "HR-V034-001-RUNTIME-BINDER-EXECUTION-ROOT-SYMLINK-BYPASS",
            "HR-V034-002-RUNTIME-BINDER-ATOMIC-PUBLISH-TOCTOU",
            "HR-V034-003-RUNTIME-BINDER-CLOSURE-OVERCLAIM",
        ],
        "receiver_raw_path_identity_contract": {
            "receiver_argument_preserved_before_resolution": True,
            "final_component_lstat_nofollow_required": True,
            "dangling_symlink_rejected": True,
            "existing_target_symlink_rejected": True,
        },
        "parent_directory_identity_contract": {
            "opened_parent_directory_identity_pinned": True,
            "parent_identity_revalidated_before_publish": True,
            "publication_uses_pinned_parent_descriptor": True,
        },
        "atomic_noreplace_publication_contract": {
            "destination_noreplace_required": True,
            "macos_renameatx_np_rename_excl": True,
            "linux_renameat2_rename_noreplace": True,
            "unsafe_replace_fallback_allowed": False,
            "unsupported_platform_behavior": "FAIL_CLOSED",
        },
        "idempotent_reentry_nofollow_contract": {
            "execution_root_identity_stable_for_reentry": True,
            "receipt_directory_nofollow": True,
            "receipt_file_nofollow": True,
            "receipt_overwrite_allowed": False,
        },
        "required_regression_execution_contract": {
            "factory_validator_executes_exact_hash_bound_tests": True,
            "candidate_publication_blocked_on_missing_test": True,
            "candidate_publication_blocked_on_failed_test": True,
            "closure_pass_requires_execution_receipt": True,
        },
        "required_adversarial_cases": [
            "DANGLING_EXECUTION_ROOT_SYMLINK",
            "EXISTING_TARGET_EXECUTION_ROOT_SYMLINK",
            "EXECUTION_ROOT_APPEARS_AFTER_PREFLIGHT",
            "EXECUTION_ROOT_PARENT_IDENTITY_SWAP",
            "EXECUTION_ROOT_TARGET_SYMLINK_SWAP",
        ],
        "implementation_evidence": {
            "compiler_ref": "src/harness_foundry_factory/compiler.py",
            "compiler_sha256": hashlib.sha256(
                (REPOSITORY_ROOT / "src/harness_foundry_factory/compiler.py").read_bytes()
            ).hexdigest(),
            "factory_validator_ref": "src/harness_foundry_factory/validator.py",
            "factory_validator_sha256": hashlib.sha256(
                (REPOSITORY_ROOT / "src/harness_foundry_factory/validator.py").read_bytes()
            ).hexdigest(),
            "regression_test_ref": "tests/test_release_closure_candidate.py",
            "regression_test_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "required_regression_tests": required_tests,
        "required_closures": [
            "Receiver raw Execution Root identity is checked before final-component resolution",
            "Dangling and existing-target Execution Root symlinks fail closed",
            "Parent directory identity remains pinned through publication",
            "Fresh Root publication uses an atomic no-replace primitive",
            "Unsupported no-replace platforms fail closed without unsafe fallback",
            "Exact idempotent re-entry reads Root and receipt paths with no-follow semantics",
            "Factory Validator executes and binds every exact Epoch 35 regression",
            "v0_34 Candidate and Human Review evidence remain preserved without runtime side effects",
        ],
    }


def json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def without_hash(value: dict, field: str) -> dict:
    projected = dict(value)
    projected.pop(field, None)
    return projected


EPOCH18_CASES = [
    "FULLY_FORGED_CONTEXT_AND_ALL_RECEIPTS_WITH_RECOMPUTED_HASHES",
    "RECOMPUTED_STALE_BUNDLE_PLUS_MATCHING_STALE_STATE",
    "FAKE_ADAPTER_OBJECT",
    "WRONG_ADAPTER_IMPLEMENTATION_SHA256",
    "FORGED_EVENT_STORE_WITH_WRONG_AUTHORIZED_DATABASE_IDENTITY",
    "EVENT_STORE_TIP_CHANGED_AFTER_EVALUATION_BEFORE_ATOMIC_COMMIT",
    "RECEIPT_CONSUMED_AFTER_EVALUATION_BEFORE_ATOMIC_COMMIT",
    "UNSIGNED_MATCHING_EVENT_STORE_BINDING",
    "FORGED_EVENT_STORE_AND_MATCHING_BINDING_WITH_ATTACKER_SIGNATURE",
    "WRONG_ACTUAL_ADAPTER_CONTRACT_HASH",
    "SELF_ASSERTED_RELEASE_COMMIT_AUTHORIZATION",
    "REPLAYED_SIGNED_RELEASE_COMMIT_AUTHORIZATION",
]
EPOCH22_CASES = [
    "VALID_SIGNATURE_WRONG_CANDIDATE_CONTENT_SHA256",
    "VALID_SIGNATURE_WRONG_REQUIREMENT_IR_SHA256",
    "VALID_SIGNATURE_WRONG_EXECUTOR_RELEASE_SHA256",
    "VALID_SIGNATURE_WRONG_HUMAN_GATE_RECEIPT_SHA256",
]
EPOCH24_CASES = [
    "EPOCH23_PRODUCER_VALIDATOR_ROUTE_OMITTED",
    "SYNCHRONIZED_WRONG_ARTIFACT_HASHES_WITH_VALID_SIGNATURE",
    "CANDIDATE_LOCAL_TRUST_ANCHOR_SUBSTITUTION",
    "FAKE_ARTIFACT_BYTES_RESOLVER",
    "SYNCHRONIZED_AUTHORITY_NORMALIZATION_RECOMPUTATION",
    "MISSING_RECEIVER_SOURCE_AUTHORITY_POLICY_LOCK",
]
EPOCH26_CASES = [
    "PORTABLE_SOURCE_INDEX_SYNCHRONIZED_REHASH_TAMPER",
    "UNSIGNED_OR_MODIFIED_SOURCE_AUTHORITY_POLICY",
    "CANDIDATE_SELECTED_TRUST_ANCHOR",
    "STALE_ISSUER_EVENT_OR_SOURCE_REGISTRY_REVISION",
]


def receiver_source_authority_bundle(
    sources: list[dict],
    *,
    requirement_ir: Mapping[str, object] | None = None,
    candidate_root: Path | None = None,
    release_history_override: list[dict] | None = None,
    private_key: Ed25519PrivateKey | None = None,
    trust_anchor: dict | None = None,
) -> tuple[dict, dict]:
    key = private_key or Ed25519PrivateKey.generate()
    release_history = (
        deepcopy(release_history_override)
        if release_history_override is not None
        else (
            _release_history_semantic_entries(requirement_ir)
            if requirement_ir is not None else []
        )
    )
    release_history_tip = json_hash(release_history)
    target = (
        requirement_ir.get("target")
        if isinstance(requirement_ir, Mapping) else None
    )
    epochs = [
        value["active_epochs"]["requirement_epoch"]
        for value in target.values()
        if isinstance(target, Mapping)
        and isinstance(value, Mapping)
        and isinstance(value.get("active_epochs"), Mapping)
        and isinstance(value["active_epochs"].get("requirement_epoch"), int)
    ] if isinstance(target, Mapping) else []
    requirement_epoch = max(epochs, default=26)
    program_id = (
        str(requirement_ir.get("program_id"))
        if isinstance(requirement_ir, Mapping)
        else "PROGRAM-REFERENCE-HARNESS"
    )
    issuance_revision = requirement_epoch * 10
    source_registry_revision = issuance_revision - 1
    issuance_event_id = f"SOURCE-POLICY-ISSUED-EPOCH-{requirement_epoch}"
    if trust_anchor is None:
        public_key = key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        source_registry_tip = source_authority_registry_tip_sha256(sources)
        issuance_event = {
            "event_id": issuance_event_id,
            "event_revision": issuance_revision,
            "event_type": "SOURCE_AUTHORITY_POLICY_ISSUED",
            "program_id": program_id,
            "requirement_epoch": requirement_epoch,
            "source_registry_revision": source_registry_revision,
            "source_registry_tip_sha256": source_registry_tip,
            "release_history_tip_sha256": release_history_tip,
        }
        trust_anchor = source_authority_trust_anchor(
            public_key,
            program_id=program_id,
            requirement_epoch=requirement_epoch,
            issuer_id="RECEIVER-SOURCE-AUTHORITY",
            key_id="SOURCE-AUTHORITY-KEY-1",
            issuance_event_id=issuance_event_id,
            issuance_event_revision=issuance_revision,
            issuance_event_sha256=json_hash(issuance_event),
            source_registry_revision=source_registry_revision,
            source_registry_tip_sha256=source_registry_tip,
            release_history_tip_sha256=release_history_tip,
        )
    validation_report_binding = {
        "report_ref": "validation/START_PACKAGE_VALIDATION_REPORT.json",
        "report_sha256": "0" * 64,
        "receipt_ref": (
            "validation/START_PACKAGE_VALIDATION_REPORT_RECEIPT.json"
        ),
        "receipt_sha256": "0" * 64,
    }
    if candidate_root is not None and requirement_epoch >= 30:
        report_path = (
            candidate_root / "validation/START_PACKAGE_VALIDATION_REPORT.json"
        )
        receipt_path = (
            candidate_root
            / "validation/START_PACKAGE_VALIDATION_REPORT_RECEIPT.json"
        )
        validation_report_binding.update(
            {
                "report_sha256": hashlib.sha256(
                    report_path.read_bytes()
                ).hexdigest(),
                "receipt_sha256": hashlib.sha256(
                    receipt_path.read_bytes()
                ).hexdigest(),
            }
        )
    policy = source_authority_policy_lock(
        sources,
        release_history=release_history,
        signer_private_key=key,
        trust_anchor=trust_anchor,
        validation_report_binding=validation_report_binding,
    )
    return policy, trust_anchor


def epoch18_remediation() -> dict:
    return {
        "active_epochs": {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 18,
        },
        "status": "REQUIRED_IN_REPLACEMENT_CANDIDATE",
        "event_store_authority_adapter_contract": {
            "adapter_id": "V29_SQLITE_EVENT_STORE_AUTHORITY_ADAPTER_V1",
            "adapter_implementation_required": True,
            "adapter_implementation_sha256_bound": True,
            "adapter_entrypoint_sha256_bound": True,
            "adapter_contract_sha256_bound": True,
            "adapter_exact_runtime_type_required": True,
            "fake_substitute_or_wrong_hash_behavior": "FAIL_CLOSED_BEFORE_AUTHORITY_READ",
            "database_identity_source": "AUTHORIZED_LOCAL_RUNTIME_BINDING_ONLY",
            "shareable_absolute_database_path_allowed": False,
            "logical_database_ref": LOGICAL_DATABASE_REF,
            "existing_native_event_store_required": True,
            "event_store_creation_by_reader_allowed": False,
            "exact_schema_and_append_only_trigger_verification_required": True,
            "complete_event_hash_chain_verification_required": True,
            "read_transaction_required": True,
            "caller_supplied_release_context_allowed": False,
            "caller_supplied_authoritative_current_state_allowed": False,
            "public_self_hash_or_sealer_establishes_authority": False,
        },
        "verified_release_context_read_contract": {
            "adapter_reads_directly": [
                "authority_scope", "instance_id", "requirement_epoch",
                "semantic_contract_identity_sha256",
                "authorization_risk_identity_sha256", "state_revision",
                "current_state_sha256", "event_store_tip_sha256",
                "authorized_issuer_events", "consumed_receipt_ids",
            ],
            "latest_matching_authoritative_events_required": True,
            "issuer_event_id_revision_hash_verified_against_event_chain": True,
            "release_context_constructed_only_by_bound_adapter": True,
            "release_context_value_type_constructed_only_by_adapter": True,
            "receipt_peer_agreement_is_authority": False,
            "missing_ambiguous_forged_or_stale_event_behavior": "FAIL_CLOSED",
        },
        "verified_current_state_read_contract": {
            "machine_binding_calls_bound_adapter_internally": True,
            "machine_binding_accepts_current_state_mapping_argument": False,
            "machine_binding_accepts_caller_asserted_adapter_checked_flag": False,
            "exact_live_match_fields": [
                "authority_scope", "instance_id", "state_revision",
                "current_state_sha256", "event_store_tip_sha256",
            ],
            "bundle_and_matching_stale_mapping_recomputation_behavior": "FAIL_CLOSED",
            "adapter_read_after_bundle_validation_required": True,
        },
        "atomic_release_commit_contract": {
            "pure_evaluator_output": "RELEASE_ELIGIBILITY_PROPOSAL_NOT_AUTHORITY",
            "release_ready_requires_atomic_event_store_commit": True,
            "begin_immediate_or_equivalent_write_lock_required": True,
            "expected_event_store_tip_compare_and_swap_required": True,
            "exact_receipt_set_unconsumed_recheck_required": True,
            "receipt_consumption_and_release_ready_event_same_transaction": True,
            "tip_change_or_receipt_replay_behavior": "ROLLBACK_AND_FAIL_CLOSED",
            "candidate_generation_invokes_commit": False,
            "runtime_authorization_required_before_commit": True,
        },
        "independent_oracle_contract": {
            "standalone_executes_candidate_production_against_temporary_native_event_store": True,
            "factory_oracle_imports_candidate_production_module": False,
            "factory_oracle_uses_independent_event_chain_and_schema_logic": True,
            "source_equality_only_role": "INTEGRITY_BINDING_NOT_SEMANTIC_PROOF",
            "both_oracles_must_reject_every_epoch18_adversarial_case": True,
        },
        "required_adversarial_cases": EPOCH18_CASES,
        "implementation_budget": {
            "reuse_existing_sqlite_event_store_patterns": True,
            "new_runtime_modules_max": 1,
            "new_aggregate_schemas_max": 2,
            "new_human_gates": 0,
            "new_node_specific_authorized_paths": 0,
            "active_bespoke_path_delta_max": 0,
        },
    }


def epoch20_remediation() -> dict:
    return {
        "active_epochs": {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 20,
        },
        "status": "REQUIRED_IN_REPLACEMENT_CANDIDATE",
        "trust_root_contract": {
            "external_signature_root_required": True,
            "signature_algorithm": "ED25519",
            "private_key_in_candidate_allowed": False,
            "caller_self_hash_establishes_authority": False,
            "binding_receipt_signature_required": True,
            "actual_adapter_contract_hash_recomputed_internally": True,
        },
        "release_commit_authorization_contract": {
            "signed_authorization_required": True,
            "self_asserted_event_is_authority": False,
            "issuer_role_required": "CONTROL_PLANE_AUTHORITY",
            "validity_window_required": True,
            "revocation_check_required": True,
            "one_shot_required": True,
            "candidate_ir_executor_human_gate_hashes_required": True,
            "proposal_state_and_prior_tip_binding_required": True,
            "lease_fencing_and_idempotency_required": True,
            "authorization_consumption_same_transaction_required": True,
        },
        "independent_oracle_contract": {
            "standalone_uses_exact_candidate_production_adapter": True,
            "factory_imports_candidate_production_adapter": False,
            "forged_store_and_matching_binding_required": True,
            "attacker_signature_required": True,
            "self_asserted_commit_and_replay_required": True,
        },
        "required_adversarial_cases": EPOCH18_CASES,
        "authoring_boundary": {
            "execution_root_creation_allowed": False,
            "human_gate_consumption_allowed": False,
            "runtime_authorization_allowed": False,
            "driver_or_workpack_start_allowed": False,
        },
    }


def epoch22_remediation() -> dict:
    return {
        "active_epochs": {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 22,
        },
        "status": "REQUIRED_IN_REPLACEMENT_CANDIDATE",
        "release_commit_actual_hash_contract": {
            "compare_inside_begin_immediate": True,
            "release_artifact_hash_authority_event": "CURRENT_STATE_COMMITTED",
            "release_artifact_hash_fields": [
                "candidate_content_sha256",
                "requirement_ir_sha256",
                "executor_release_sha256",
                "human_gate_receipt_sha256",
            ],
            "release_artifact_hashes_read_and_compared_inside_begin_immediate": True,
            "valid_signature_with_wrong_release_artifact_hash_behavior": "FAIL_CLOSED",
        },
        "required_adversarial_cases": EPOCH22_CASES,
    }


def epoch24_remediation() -> dict:
    return {
        "active_epochs": {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 24,
        },
        "status": "REQUIRED_IN_REPLACEMENT_CANDIDATE",
        "producer_validator_route_contract": {
            "epoch23_requirements_consumed_by_producer": True,
            "epoch23_requirements_consumed_by_standalone": True,
            "epoch23_requirements_consumed_by_factory_validator": True,
            "manifest_requirement_epoch": 24,
            "unknown_or_omitted_route_behavior": "FAIL_CLOSED",
        },
        "artifact_bytes_resolver_contract": {
            "four_actual_artifact_byte_hashes_required": True,
            "receiver_side_runtime_paths_only": True,
            "candidate_persisted_absolute_paths_allowed": False,
            "exact_production_resolver_type_required": True,
            "resolve_inside_begin_immediate": True,
            "event_store_and_signed_authorization_must_match_actual_bytes": True,
            "symlink_or_read_mutation_behavior": "FAIL_CLOSED",
        },
        "receiver_trust_anchor_contract": {
            "receiver_supplied_external_anchor_required": True,
            "candidate_local_anchor_establishes_authority": False,
            "binding_and_commit_signature_use_same_receiver_anchor": True,
        },
        "authority_normalization_oracle_contract": {
            "factory_uses_event_store_source_registry": True,
            "standalone_requires_external_receiver_policy_lock": True,
            "candidate_frozen_ir_is_authority": False,
            "candidate_source_manifest_is_authority": False,
            "oracles_share_candidate_authority_input": False,
        },
        "required_adversarial_cases": EPOCH24_CASES,
        "required_runtime_adversarial_cases": [
            "SYNCHRONIZED_WRONG_ARTIFACT_HASHES_WITH_VALID_SIGNATURE",
            "CANDIDATE_LOCAL_TRUST_ANCHOR_SUBSTITUTION",
            "FAKE_ARTIFACT_BYTES_RESOLVER",
        ],
        "required_gate_adversarial_cases": [
            "EPOCH23_PRODUCER_VALIDATOR_ROUTE_OMITTED",
            "SYNCHRONIZED_AUTHORITY_NORMALIZATION_RECOMPUTATION",
            "MISSING_RECEIVER_SOURCE_AUTHORITY_POLICY_LOCK",
        ],
        "authoring_boundary": {
            "candidate_generation_allowed_in_this_turn": False,
            "execution_root_creation_allowed": False,
            "human_gate_consumption_allowed": False,
            "runtime_authorization_allowed": False,
            "driver_or_workpack_start_allowed": False,
        },
    }


def epoch25_remediation() -> dict:
    return {
        "active_epochs": {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 25,
        },
        "status": "REQUIRED_IN_REPLACEMENT_CANDIDATE",
        "closure_receipt_required": True,
        "closure_receipt_status": (
            "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT"
        ),
        "closure_requirement_kind": "GENERATION_FAILURE_REMEDIATION",
        "finding_ids": [
            "V025-GENERATION-SOURCE-AUTHORITY-PROJECTION-MISMATCH"
        ],
        "superseded_candidate": "candidate-v0_25",
        "replacement_candidate": "candidate-v0_26",
        "replacement_identity_cross_check_required": True,
        "successor_binding": {
            "candidate_version": "v0_26",
            "superseded_candidate_version": "v0_25",
        },
        "required_closures": [
            "Receiver-local locators are excluded from semantic authority comparison",
            "Candidate portable source URIs are independently validated",
        ],
        "required_evidence_refs": [
            "canonical_sources/SOURCE_MANIFEST.json",
            "canonical_sources/PORTABLE_SOURCE_INDEX.json",
            "contracts/v2_9_release_closure/SOURCE_AUTHORITY_POLICY_LOCK.schema.json",
            "tools/self_check.py",
            "validation/START_PACKAGE_VALIDATION_REPORT.json",
        ],
        "producer_validator_route_contract": {
            "semantic_policy_projection_consumed_by_producer": True,
            "semantic_policy_projection_consumed_by_standalone": True,
            "portable_uri_projection_consumed_by_factory_validator": True,
            "manifest_requirement_epoch": 25,
            "unknown_or_omitted_route_behavior": "FAIL_CLOSED",
        },
        "source_authority_semantic_projection_contract": {
            "compared_fields": [
                "source_id",
                "content_sha256",
                "copy_policy",
                "loaded_completely",
                "declared_authority_level",
                "canonical_authority_level",
            ],
            "receiver_local_locator_fields_compared": False,
        },
        "portable_uri_projection_contract": {
            "independent_mapping_validation_required": True,
            "candidate_resource_uri_required": True,
            "receiver_local_absolute_path_allowed": False,
        },
    }


def epoch26_remediation() -> dict:
    return {
        "active_epochs": {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 26,
        },
        "status": "REQUIRED_IN_REPLACEMENT_CANDIDATE",
        "closure_receipt_required": True,
        "closure_receipt_status": (
            "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT"
        ),
        "closure_requirement_kind": "HUMAN_REVIEW_REMEDIATION",
        "finding_ids": [
            "HR-V026-001-PORTABLE-SOURCE-INDEX-STANDALONE-BLIND-SPOT",
            "HR-V026-002-SOURCE-AUTHORITY-POLICY-NOT-EXTERNALLY-AUTHENTIC",
            "HR-V026-003-V025-CLOSURE-REPLACEMENT-IDENTITY-DRIFT",
        ],
        "superseded_candidate": "candidate-v0_26",
        "replacement_candidate": "candidate-v0_27",
        "replacement_identity_cross_check_required": True,
        "successor_binding": {
            "candidate_version": "v0_27",
            "superseded_candidate_version": "v0_26",
        },
        "portable_source_index_contract": {
            "standalone_independent_semantic_validation_required": True,
            "factory_independent_semantic_validation_required": True,
            "synchronized_downstream_rehash_behavior": "FAIL_CLOSED",
        },
        "source_authority_policy_lock_contract": {
            "receiver_pinned_ed25519_signature_required": True,
            "receiver_trust_anchor_external_to_candidate_required": True,
            "receiver_anchor_file_sha256_pinned_outside_candidate_required": True,
            "issuer_event_id_revision_hash_binding_required": True,
            "source_registry_revision_tip_binding_required": True,
            "candidate_selected_anchor_establishes_authority": False,
        },
        "closure_identity_contract": {
            "successor_package_epoch_cross_check_required": True,
            "replacement_candidate_exact_version_required": True,
            "current_package_identity_receipt_binding_required": True,
        },
        "required_standalone_adversarial_cases": [
            "PORTABLE_SOURCE_INDEX_SYNCHRONIZED_REHASH_TAMPER"
        ],
        "required_adversarial_cases": EPOCH26_CASES,
        "required_closures": [
            "Standalone independently validates Portable Source Index semantics",
            "Receiver-pinned signature authenticates source authority policy",
            "Closure replacement identity matches successor and package epochs",
        ],
    }


def epoch28_remediation() -> dict:
    return {
        "active_epochs": {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 28,
        },
        "status": "REQUIRED_IN_REPLACEMENT_CANDIDATE",
        "closure_receipt_required": True,
        "closure_receipt_status": (
            "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT"
        ),
        "closure_requirement_kind": "HUMAN_REVIEW_REMEDIATION",
        "finding_ids": [
            "HR-V027-001-HISTORICAL-SUCCESSOR-AUTHORITY-MISSING"
        ],
        "superseded_candidate": "candidate-v0_27",
        "replacement_candidate": "candidate-v0_28",
        "replacement_identity_cross_check_required": True,
        "successor_binding": {
            "candidate_version": "v0_28",
            "superseded_candidate_version": "v0_27",
        },
        "receiver_release_history_authority_contract": {
            "receiver_pinned_ed25519_signature_required": True,
        },
        "producer_history_authority_contract": {
            "source_authority_policy_version": (
                "V29_SOURCE_AUTHORITY_POLICY_LOCK_V4"
            ),
        },
        "dual_oracle_history_contract": {
            "factory_authority_input": "FACTORY_EVENT_STORE_REQUIREMENT_IR",
            "standalone_authority_input": (
                "RECEIVER_PINNED_SIGNED_RELEASE_HISTORY_POLICY"
            ),
        },
        "required_adversarial_cases": [
            "HISTORICAL_SUCCESSOR_SYNCHRONIZED_REHASH_TAMPER",
            "MISSING_RELEASE_HISTORY_AUTHORITY",
            "UNSIGNED_OR_MODIFIED_RELEASE_HISTORY_POLICY",
            "STALE_RELEASE_HISTORY_ISSUER_EVENT_OR_TIP",
            "CANDIDATE_SELECTED_RELEASE_HISTORY_TRUST_ANCHOR",
            "DUPLICATE_OR_CONFLICTING_RELEASE_HISTORY_ENTRY",
        ],
        "required_closures": [
            "External signed history binds the exact Candidate successor",
            "Factory and standalone consume independent external authority",
        ],
    }


def epoch29_remediation() -> dict:
    return {
        "active_epochs": {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 29,
        },
        "status": "REQUIRED_IN_REPLACEMENT_CANDIDATE",
        "closure_receipt_required": True,
        "closure_receipt_status": (
            "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT"
        ),
        "closure_requirement_kind": "HUMAN_REVIEW_REMEDIATION",
        "finding_ids": [
            "HR-V028-001-EXTERNAL-ORACLE-PASS-WITHOUT-AUTHORITY-INPUT",
            "HR-V028-002-VALIDATION-REPORT-OMITS-AUTHORITY-PROVENANCE",
        ],
        "superseded_candidate": "candidate-v0_28",
        "replacement_candidate": "candidate-v0_29",
        "replacement_identity_cross_check_required": True,
        "successor_binding": {
            "candidate_version": "v0_29",
            "superseded_candidate_version": "v0_28",
        },
        "external_authority_fail_closed_contract": {
            "missing_authoritative_sources_overall_status": "FAIL",
            "missing_authoritative_requirement_ir_overall_status": "FAIL",
        },
        "validation_report_authority_provenance_contract": {
            "authority_input_preserved": True,
            "event_store_revision_tip_and_content_hashes_required": True,
        },
        "required_adversarial_cases": [
            "MISSING_FACTORY_EVENT_STORE_SOURCE_REGISTRY",
            "MISSING_FACTORY_EVENT_STORE_REQUIREMENT_IR",
            "OMITTED_VALIDATION_REPORT_AUTHORITY_PROVENANCE",
        ],
        "required_regression_tests": [
            "test_epoch28_factory_validator_requires_both_external_authority_inputs",
            "test_epoch28_candidate_report_preserves_external_authority_provenance",
            "test_epoch29_candidate_routes_fail_closed_external_authority_contract",
        ],
        "required_closures": [
            "Active external Oracles cannot pass without both Factory authority inputs",
            "Candidate validation report preserves authority input and Event Store revision tip and content Hash provenance",
        ],
    }


def epoch30_remediation() -> dict:
    return {
        "active_epochs": {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 30,
        },
        "status": "REQUIRED_IN_REPLACEMENT_CANDIDATE",
        "closure_receipt_required": True,
        "closure_receipt_status": (
            "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT"
        ),
        "closure_requirement_kind": "HUMAN_REVIEW_REMEDIATION",
        "finding_ids": [
            "HR-V029-001-VALIDATION-REPORT-PROVENANCE-NOT-INTEGRITY-BOUND",
        ],
        "superseded_candidate": "candidate-v0_29",
        "replacement_candidate": "candidate-v0_30",
        "replacement_identity_cross_check_required": True,
        "successor_binding": {
            "candidate_version": "v0_30",
            "superseded_candidate_version": "v0_29",
        },
        "validation_report_integrity_contract": {
            "factory_compares_embedded_external_checks_to_recomputed_checks": True,
            "detached_report_receipt_required": True,
            "receiver_signed_policy_binds_report_and_receipt_hashes": True,
            "standalone_verifies_signed_report_binding": True,
        },
        "required_adversarial_cases": [
            "DELETED_VALIDATION_REPORT_AUTHORITY_PROVENANCE",
            "REPLACED_VALIDATION_REPORT_PROVENANCE_HASH",
            "SWAPPED_ORACLE_AUTHORITY_PROVENANCE",
            "SYNCHRONIZED_VALIDATION_REPORT_AND_RECEIPT_REHASH_TAMPER",
        ],
        "required_regression_tests": [
            "test_epoch30_validation_report_receipt_is_hash_bound",
            "test_epoch30_validation_report_tamper_is_rejected_by_both_oracles",
        ],
        "required_closures": [
            "Factory compares the embedded external Oracle entries with its freshly recomputed checks",
            "A detached receipt binds the exact Validation Report bytes and external-check projection",
            "The receiver-pinned signed Source Authority Policy binds both report and receipt hashes",
            "Synchronized Candidate-local rehashing cannot make either Oracle accept tampered report provenance",
        ],
    }


def epoch31_remediation() -> dict:
    return {
        "active_epochs": {
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "requirement_epoch": 31,
        },
        "status": "REQUIRED_IN_REPLACEMENT_CANDIDATE",
        "closure_receipt_required": True,
        "closure_receipt_status": (
            "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT"
        ),
        "closure_requirement_kind": "POST_PUBLISH_VALIDATION_REMEDIATION",
        "finding_ids": [
            "HR-V030-001-PRECOMMIT-BASIS-COMPARED-AS-CURRENT-HEAD",
        ],
        "superseded_candidate": "candidate-v0_30",
        "replacement_candidate": "candidate-v0_31",
        "replacement_identity_cross_check_required": True,
        "successor_binding": {
            "candidate_version": "v0_31",
            "superseded_candidate_version": "v0_30",
        },
        "validation_basis_current_head_contract": {
            "immutable_basis_must_be_verified_ancestor": True,
            "current_head_may_advance_after_candidate_commit": True,
            "basis_equals_mutable_head_required": False,
            "forked_or_unrelated_basis_behavior": "FAIL_CLOSED",
        },
        "candidate_generation_commit_contract": {
            "authority_source": "FACTORY_APPEND_ONLY_EVENT_STORE",
            "event_type": "START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW",
            "unique_matching_commit_required": True,
            "commit_directly_descends_from_validation_basis": True,
            "commit_binds_candidate_content_sha256": True,
            "commit_binds_validation_report_sha256": True,
            "commit_binds_validation_report_receipt_sha256": True,
            "commit_binds_requirement_ir_sha256": True,
            "commit_binds_validation_basis_revision_and_tip": True,
            "replay_or_duplicate_commit_behavior": "FAIL_CLOSED",
        },
        "required_adversarial_cases": [
            "POST_PUBLISH_IMMEDIATE_REVALIDATION",
            "LATER_LEGITIMATE_DESCENDANT_EVENT",
            "FORGED_VALIDATION_BASIS_ANCESTOR",
            "FORKED_CURRENT_EVENT_STORE_TIP",
            "REPLAYED_CANDIDATE_GENERATION_COMMIT",
            "SYNCHRONIZED_CANDIDATE_REHASH_WITHOUT_AUTHORITY_COMMIT",
        ],
        "required_regression_tests": [
            "test_epoch31_post_publish_and_descendant_validation_pass",
            "test_epoch31_generation_commit_adversarial_cases_fail",
        ],
        "required_closures": [
            "The immutable validation basis is verified as the direct parent of the authoritative Candidate generation commit",
            "The current Event Store head may advance only through a valid descendant hash chain",
            "Exactly one authoritative generation commit binds Candidate, report, receipt, Requirement IR and validation basis identities",
            "Fork, replay and Candidate-local synchronized rehashing fail closed",
        ],
    }


def write_json(path: Path, value: object) -> None:
    make_path_writable(path)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def epoch2_requirement(candidate: Path, execution: Path) -> dict:
    ir = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    corrections = [
        {
            "correction_id": correction_id,
            "maps_to": ["ATOM-001" if index % 2 else "ATOM-002"],
            "requirement": f"Epoch 2 production correction {correction_id}",
        }
        for index, correction_id in enumerate(EPOCH2_IDS, 1)
    ]
    ir["target"].update(
        {
            "output_root": str(candidate),
            "execution_root": str(execution),
            "candidate_version": "v0_27",
            "portability_mode": "LOGICAL_RESOURCE_URI",
            "architecture_epoch": 2,
            "control_plane_epoch": 2,
            "release_closure_control_plane_remediation": {
                "architecture_epoch": 2,
                "control_plane_epoch": 2,
                "identity_contract": {
                    "human_authorization_binds": ["SEMANTIC", "RISK"],
                    "implementation_only_change_requires_human_gate": False,
                    "machine_grant_binds": ["RISK", "EXECUTOR_SHA256"],
                    "manual_hash_input_required": False,
                    "semantic_or_risk_change_requires_human_gate": True,
                },
                "generic_recovery_protocol": {
                    "decision_modes": [
                        "RESULT_VALIDATION_ONLY",
                        "FINALIZATION_ONLY",
                        "RETRY_EXECUTOR",
                        "HUMAN_RISK_REVIEW",
                    ],
                    "node_specific_authoritative_recovery_allowed": False,
                    "unknown_side_effect_behavior": "HUMAN_RISK_REVIEW",
                },
                "complexity_governor": {
                    "active_bespoke_path_delta_must_be_negative": True,
                    "generic_path_minimum_authoritative_retirements": 1,
                    "human_gate_requires_real_risk_delta_or_external_authority_boundary": True,
                    "new_fixed_attempt_or_receipt_ids_in_core_max": 0,
                    "new_node_specific_authorized_paths_max": 0,
                    "same_control_fault_second_occurrence": "ARCHITECTURE_REVIEW_REQUIRED",
                    "validator_only_closure_allowed": False,
                },
                "closure_lanes": {
                    "cross_lane_status_overwrite_allowed": False,
                    "final_release_rule": "ALL_THREE_VALID_CLOSURE_RECEIPTS_AND_COMPATIBILITY_LINKAGE_PASS",
                    "independent_state_and_receipt_required": True,
                    "lane_ids": ["PRODUCT", "SAFETY", "RELEASE"],
                    "three_physical_clis_projects_or_chats_required": False,
                    "v2_8_fixed_release_pipeline_role": "COMPATIBILITY_ADAPTER_ONLY",
                },
                "evidence_and_projection": {
                    "evidence_index_creates_authority": False,
                    "file_receipt_hash_or_directory_count_is_completion_evidence": False,
                    "persistent_fact_authority": "SINGLE_APPEND_ONLY_EVENT_STORE",
                    "projection_conflict_behavior": "FAIL_CLOSED_WITH_PROJECTION_CONFLICT",
                    "projection_rebuild_required": True,
                    "retention_classes": [
                        "ACTIVE_BASELINE",
                        "HISTORICAL_REGRESSION",
                        "SUPERSEDED",
                        "ARCHIVED",
                    ],
                },
                "correction_requirements": corrections,
            },
            "v0_15_epoch2_producer_validator_alignment_correction": {
                "active_epoch_dispatch": {
                    "epoch_1_mode": "EPOCH1_GENERIC_CONTROL_KERNEL_COMPATIBILITY_BASELINE",
                    "epoch_2_mode": "EPOCH2_RELEASE_CLOSURE_CONTROL_PLANE",
                    "selection_inputs": [
                        "target.architecture_epoch",
                        "target.control_plane_epoch",
                    ],
                    "unknown_or_mixed_epoch_behavior": "FAIL_CLOSED_BEFORE_CANDIDATE_PUBLICATION",
                },
                "active_epochs": {
                    "architecture_epoch": 2,
                    "control_plane_epoch": 2,
                },
                "atomic_publication_requires": [
                    "FACTORY_VALIDATOR_PASS",
                    "STANDALONE_SELF_CHECK_PASS",
                ],
                "correction_ids": EPOCH2_IDS,
                "factory_validator": {
                    "active_epoch_check_must_not_be_vacuous": True,
                    "calls_standalone_self_check_as_verdict_source": False,
                    "independent_implementation_required": True,
                },
                "producer_first": True,
                "required_epoch2_artifacts": EPOCH2_ARTIFACTS,
                "standalone_self_check": {
                    "calls_factory_validator_as_verdict_source": False,
                    "historical_traceability_alone_selects_epoch1": False,
                    "independent_implementation_required": True,
                },
                "status": "REQUIRED_IN_REPLACEMENT_CANDIDATE",
            },
            "v0_16_human_review_remediation": {
                "active_epochs": {
                    "architecture_epoch": 2,
                    "control_plane_epoch": 2,
                    "requirement_epoch": 16,
                },
                "authoring_boundary": {
                    "candidate_generation_before_new_freeze_allowed": False,
                    "execution_root_creation_allowed": False,
                    "human_gate_consumption_allowed": False,
                    "runtime_authorization_allowed": False,
                },
                "closure_lane_contract": {
                    "canonical_receipt_body_hash_required": True,
                    "compatibility_linkage_receipt_required": True,
                    "exact_schema_validation_required": True,
                    "same_authority_scope_required": True,
                    "same_authorization_risk_identity_required": True,
                    "same_instance_id_required": True,
                    "same_requirement_epoch_required": True,
                    "same_semantic_contract_identity_required": True,
                },
                "complexity_output_contract": {
                    "aggregate_output_id": "COMPLEXITY_ASSESSMENT",
                    "aggregate_schema_required": True,
                    "canonical_assessment_hash_required": True,
                    "required_machine_outputs": [
                        "COMPLEXITY_BASELINE",
                        "COMPLEXITY_DELTA",
                        "RETIREMENT_MANIFEST",
                        "HUMAN_COST_RESULT",
                        "CIRCUIT_BREAKER_DECISION_RECEIPT",
                    ],
                },
                "identity_implementation_contract": {
                    "change_classes": [
                        "NO_REBIND_REQUIRED",
                        "MACHINE_GRANT_REBIND_REQUIRED",
                        "HUMAN_REAUTHORIZATION_REQUIRED",
                    ],
                    "executable_module_required": True,
                    "identity_ids": [
                        "SEMANTIC_CONTRACT_IDENTITY",
                        "IMPLEMENTATION_RELEASE_IDENTITY",
                        "AUTHORIZATION_RISK_IDENTITY",
                    ],
                    "machine_grant_binding_creates_authority": False,
                    "machine_grant_binding_required": True,
                    "output_schemas_required": True,
                },
                "independent_oracles": {
                    "factory_validator_calls_standalone": False,
                    "factory_validator_required": True,
                    "standalone_calls_factory_validator": False,
                    "standalone_self_check_required": True,
                },
                "required_epoch2_artifacts": EPOCH2_ARTIFACTS,
                "review_finding_ids": [
                    "HR-V016-001-CLOSURE-LANE-UNTRUSTED-RECEIPT",
                    "HR-V016-002-CORR-29-009-DECLARATIVE-ONLY",
                    "HR-V016-003-COMPLEXITY-OUTPUT-CONTRACT-MISSING",
                ],
                "review_report_sha256": "1" * 64,
                "review_report_source_id": "SRC-V29-V016-HUMAN-REVIEW-E16",
                "status": "REQUIRED_IN_REPLACEMENT_CANDIDATE",
            },
            "v0_17_human_review_remediation": {
                "active_epochs": {
                    "architecture_epoch": 2,
                    "control_plane_epoch": 2,
                    "requirement_epoch": 17,
                },
                "authoring_boundary": {
                    "candidate_generation_before_new_freeze_allowed": False,
                    "execution_root_creation_allowed": False,
                    "human_gate_consumption_allowed": False,
                    "runtime_authorization_allowed": False,
                },
                "closure_receipt_authority_contract": {
                    "atomic_receipt_set_consumption_required": True,
                    "authoritative_release_state": "RELEASE_READY_ONLY_AFTER_EVENT_STORE_COMMIT",
                    "authority_proof_fields": [
                        "receipt_id",
                        "issuer_control_domain_id",
                        "issuance_event_id",
                        "issuance_event_revision",
                        "issuance_event_sha256",
                        "release_context_sha256",
                        "anti_replay_token",
                    ],
                    "duplicate_or_consumed_receipt_behavior": "FAIL_CLOSED",
                    "evaluator_output": "RELEASE_ELIGIBILITY_PROPOSAL_NOT_AUTHORITY",
                    "receipt_self_hash_creates_authority": False,
                    "trusted_issuer_map_required": True,
                    "uniformly_forged_or_stale_behavior": "FAIL_CLOSED",
                },
                "complexity_budget": {
                    "active_bespoke_path_delta_max": 0,
                    "human_gate_added": False,
                    "new_aggregate_schemas_max": 3,
                    "new_node_specific_authorized_paths_max": 0,
                    "prefer_existing_runtime_modules": True,
                },
                "current_state_freshness_contract": {
                    "authoritative_adapter_required": True,
                    "caller_selected_state_is_authority": False,
                    "machine_binding_requires_exact_live_state_match": True,
                    "mismatch_behavior": "FAIL_CLOSED_BEFORE_BINDING",
                    "recomputed_stale_bundle_behavior": "FAIL_CLOSED",
                },
                "identity_input_contract": {
                    "additional_properties_allowed": False,
                    "aggregate_input_schema_id": "IDENTITY_DERIVATION_INPUT",
                    "authorization_risk_required_fields": [
                        "risk_profile_id", "scope_sha256", "permissions_sha256",
                        "write_roots_sha256", "network_policy_sha256",
                        "secret_access_policy_sha256", "external_effect_class",
                        "budget_sha256", "stop_gates_sha256",
                    ],
                    "current_state_required_fields": [
                        "authority_scope", "instance_id", "state_revision",
                        "current_state_sha256", "event_store_tip_sha256",
                    ],
                    "implementation_release_required_fields": [
                        "release_id", "exact_executor_bytes_sha256",
                        "artifact_bytes_sha256", "sbom_sha256",
                        "provenance_sha256", "toolchain_sha256",
                    ],
                    "semantic_contract_required_fields": [
                        "contract_id", "contract_version",
                        "normative_behavior_sha256", "input_schema_sha256",
                        "output_schema_sha256", "invariants_sha256",
                    ],
                },
                "independent_oracles": {
                    "factory_oracle_imports_candidate_production_module": False,
                    "factory_validator_calls_standalone": False,
                    "factory_validator_required": True,
                    "shared_source_equality_is_semantic_proof": False,
                    "standalone_calls_factory_validator": False,
                    "standalone_oracle_imports_factory_reference_oracle": False,
                    "standalone_self_check_required": True,
                },
                "required_adversarial_cases": [
                    "UNIFORMLY_STALE_ALL_RECEIPTS",
                    "UNIFORMLY_FORGED_ALL_RECEIPTS",
                    "WRONG_AUTHORIZED_ISSUER",
                    "RECOMPUTED_STALE_CURRENT_STATE_BUNDLE",
                    "DUPLICATE_RECEIPT_ID",
                    "ALREADY_CONSUMED_RECEIPT_REPLAY",
                    "EVENT_STORE_TIP_CHANGED_BEFORE_ATOMIC_COMMIT",
                ],
                "review_finding_ids": [
                    "HR-V017-001-TRUSTED-RELEASE-CONTEXT-MISSING",
                    "HR-V017-002-IDENTITY-INPUT-AND-STATE-FRESHNESS",
                    "HR-V017-003-COMMON-MODE-ORACLE-BLIND-SPOT",
                ],
                "status": "REQUIRED_IN_REPLACEMENT_CANDIDATE",
                "trusted_release_context_contract": {
                    "context_authority": "SINGLE_APPEND_ONLY_EVENT_STORE_AUTHORITY_ADAPTER",
                    "context_fields": [
                        "authority_scope", "instance_id", "requirement_epoch",
                        "semantic_contract_identity_sha256",
                        "authorization_risk_identity_sha256", "state_revision",
                        "current_state_sha256", "event_store_tip_sha256",
                        "authorized_issuers", "consumed_receipt_ids",
                    ],
                    "evaluator_derives_expected_context_from_receipts": False,
                    "exact_schema_required": True,
                    "required": True,
                },
            },
            "v0_18_human_review_remediation": epoch18_remediation(),
            "v0_20_human_review_remediation": epoch20_remediation(),
            "v0_22_human_review_remediation": epoch22_remediation(),
            "v0_24_human_review_remediation": epoch24_remediation(),
            "v0_25_generation_failure_remediation": epoch25_remediation(),
            "v0_26_human_review_remediation": epoch26_remediation(),
            "human_review_v0_15_closure": {
                "finding_ids": [
                    "FINDING-V0-15-EPOCH2-PRODUCER-ORACLE-DIVERGENCE-001"
                ],
                "replacement_candidate": "candidate-v0_16",
                "required_closures": [
                    "Producer, standalone and Factory Validator agree on Epoch 2"
                ],
                "status": "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT",
                "superseded_candidate": "candidate-v0_15",
            },
            "human_review_v0_16_closure": {
                "finding_ids": [
                    "HR-V016-001-CLOSURE-LANE-UNTRUSTED-RECEIPT",
                    "HR-V016-002-CORR-29-009-DECLARATIVE-ONLY",
                    "HR-V016-003-COMPLEXITY-OUTPUT-CONTRACT-MISSING",
                ],
                "replacement_candidate": "candidate-v0_17",
                "required_closures": [
                    "Production and both independent oracles fail closed"
                ],
                "status": "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT",
                "superseded_candidate": "candidate-v0_16",
            },
            "human_review_v0_17_closure": {
                "finding_ids": [
                    "HR-V017-001-TRUSTED-RELEASE-CONTEXT-MISSING",
                    "HR-V017-002-IDENTITY-INPUT-AND-STATE-FRESHNESS",
                    "HR-V017-003-COMMON-MODE-ORACLE-BLIND-SPOT",
                ],
                "replacement_candidate": "candidate-v0_18",
                "required_closures": [
                    "Trusted Release Context and independent adversarial oracles"
                ],
                "status": "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT",
                "superseded_candidate": "candidate-v0_17",
            },
            "human_review_v0_18_closure": {
                "finding_ids": [
                    "HR-V018-001-CALLER-SEALED-RELEASE-CONTEXT",
                    "HR-V018-002-CALLER-SUPPLIED-AUTHORITATIVE-STATE",
                    "HR-V018-003-ORACLE-TRUST-BOUNDARY-NOT-EXERCISED",
                ],
                "replacement_candidate": "candidate-v0_19",
                "required_closures": [
                    "Exact Hash-bound adapter owns Context and Current State reads",
                    "Production and independent oracles reject Epoch 18 attacks",
                ],
                "status": "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT",
                "superseded_candidate": "candidate-v0_18",
            },
            "human_review_v0_20_closure": {
                "finding_ids": [
                    "HR-V020-001-AUTHORITY-BINDING-NO-EXTERNAL-ROOT",
                    "HR-V020-002-SELF-ASSERTED-RELEASE-COMMIT-AUTHORIZATION",
                    "HR-V020-003-COMMON-MODE-ORACLE-BLIND-SPOT",
                ],
                "replacement_candidate": "candidate-v0_21",
                "required_closures": [
                    "Pinned external signature root and actual Adapter Contract Hash",
                    "Signed one-shot Release Commit authorization with atomic consumption",
                    "Exact production and independent Oracle reject forged matching store and binding",
                ],
                "status": "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT",
                "superseded_candidate": "candidate-v0_20",
            },
            "human_review_v0_22_closure": {
                "finding_ids": [
                    "HR-V022-001-AUTHORITY-NORMALIZATION-DUAL-ORACLE-GAP",
                    "HR-V022-002-GENERATION-REMEDIATION-CLOSURE-OMITTED",
                    "HR-V022-003-RELEASE-AUTHORIZATION-ACTUAL-HASH-UNBOUND",
                ],
                "replacement_candidate": "candidate-v0_23",
                "required_closures": [
                    "Dual Oracle authority normalization is semantic",
                    "v0.21 generation remediation is closure-bound",
                    "Signed authorization Hashes equal live authority Hashes inside transaction",
                ],
                "status": "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT",
                "superseded_candidate": "candidate-v0_22",
            },
            "human_review_v0_24_closure": {
                "finding_ids": [
                    "HR-V024-001-EPOCH23-PRODUCER-VALIDATOR-ROUTE-OMITTED",
                    "HR-V024-002-ACTUAL-ARTIFACT-BYTES-UNRESOLVED",
                    "HR-V024-003-CANDIDATE-LOCAL-TRUST-ANCHOR",
                    "HR-V024-004-AUTHORITY-NORMALIZATION-COMMON-INPUT",
                ],
                "replacement_candidate": "UNASSIGNED_UNTIL_NEXT_FREEZE",
                "required_closures": [
                    "Epoch 23 remediation is routed through Producer and both Validators",
                    "Release commit compares receiver-resolved bytes inside the transaction",
                    "Receiver trust anchor and independent normalization authority are external",
                ],
                "status": "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT",
                "superseded_candidate": "candidate-v0_24",
            },
        }
    )
    return ir


class Epoch2CandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.candidate = self.root / "candidate"
        self.ir = epoch2_requirement(
            self.candidate, self.root / "execution-not-created"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def authority_provenance(self) -> dict:
        target = self.ir["target"]
        epochs = [
            value["active_epochs"]["requirement_epoch"]
            for value in target.values()
            if isinstance(value, Mapping)
            and isinstance(value.get("active_epochs"), Mapping)
            and isinstance(value["active_epochs"].get("requirement_epoch"), int)
        ]
        requirement_epoch = max(epochs, default=0)
        return {
            "event_store_revision": requirement_epoch * 10,
            "event_store_tip_sha256": json_hash(
                {
                    "authority": "FACTORY_EVENT_STORE_TEST_FIXTURE",
                    "requirement_epoch": requirement_epoch,
                }
            ),
            "requirement_epoch": requirement_epoch,
            "source_registry_sha256": json_hash(self.ir["sources"]),
            "requirement_ir_sha256": json_hash(self.ir),
        }

    def compile(self) -> None:
        compile_candidate(
            deepcopy(self.ir),
            SPEC_ROOT,
            self.root / "staging",
            self.candidate,
            "2026-08-05T00:00:00Z",
            authority_provenance=self.authority_provenance(),
        )

    def receiver_authority_environment(
        self,
        policy: dict | None = None,
        trust_anchor: dict | None = None,
    ) -> dict[str, str]:
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        policy_path = self.root / "receiver-source-authority-policy-lock.json"
        anchor_path = self.root / "receiver-source-authority-trust-anchor.json"
        if policy is None or trust_anchor is None:
            policy, trust_anchor = receiver_source_authority_bundle(
                self.ir["sources"],
                requirement_ir=self.ir,
                candidate_root=self.candidate,
            )
        write_json(policy_path, policy)
        write_json(anchor_path, trust_anchor)
        environment["HF_SOURCE_AUTHORITY_POLICY_LOCK"] = str(policy_path)
        environment["HF_SOURCE_AUTHORITY_TRUST_ANCHOR"] = str(anchor_path)
        environment["HF_SOURCE_AUTHORITY_TRUST_ANCHOR_SHA256"] = hashlib.sha256(
            anchor_path.read_bytes()
        ).hexdigest()
        return environment

    def run_self_check(
        self,
        policy: dict | None = None,
        trust_anchor: dict | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "tools/self_check.py"],
            cwd=self.candidate,
            env=self.receiver_authority_environment(policy, trust_anchor),
            check=False,
            capture_output=True,
            text=True,
        )

    def codes(self) -> set[str]:
        return {
            finding["code"]
            for check in validate_candidate(
                self.candidate,
                authoritative_sources=self.ir["sources"],
                authoritative_requirement_ir=self.ir,
                authority_provenance=self.authority_provenance(),
            )["checks"]
            for finding in check["findings"]
        }

    def refresh_closure_and_portable_hashes(self) -> None:
        receipt_path = (
            self.candidate / "validation/HUMAN_REVIEW_CLOSURE_RECEIPT.json"
        )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        for closure in receipt["closures"]:
            closure["evidence_sha256"] = {
                relative: hashlib.sha256(
                    (self.candidate / relative).read_bytes()
                ).hexdigest()
                for relative in closure["evidence_refs"]
                if (self.candidate / relative).is_file()
            }
        write_json(receipt_path, receipt)
        portable_path = self.candidate / "validation/PORTABLE_FILE_MANIFEST.json"
        portable = json.loads(portable_path.read_text(encoding="utf-8"))
        excluded = set(portable["excluded_files"])
        files = {
            path.relative_to(self.candidate).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(self.candidate.rglob("*"))
            if path.is_file()
            and path.relative_to(self.candidate).as_posix() not in excluded
        }
        portable["file_count"] = len(files)
        portable["files"] = files
        write_json(portable_path, portable)

    def activate_epoch30(self) -> None:
        self.ir["target"]["candidate_version"] = "v0_30"
        self.ir["target"]["v0_27_human_review_remediation"] = (
            epoch28_remediation()
        )
        self.ir["target"]["v0_28_human_review_remediation"] = (
            epoch29_remediation()
        )
        self.ir["target"]["v0_29_human_review_remediation"] = (
            epoch30_remediation()
        )

    def activate_epoch31(self) -> None:
        self.activate_epoch30()
        self.ir["target"]["candidate_version"] = "v0_31"
        self.ir["target"]["v0_30_human_review_remediation"] = (
            epoch31_remediation()
        )

    def activate_epoch33(self) -> None:
        self.ir["target"][
            "v0_31_runtime_binding_failure_remediation"
        ] = epoch32_runtime_binding_remediation()
        self.ir["target"][
            "v0_32_human_review_remediation"
        ] = epoch33_runtime_binding_review_remediation()
        self.ir["target"]["candidate_version"] = "v0_33"

    def activate_epoch34(self) -> None:
        self.activate_epoch33()
        self.ir["target"][
            "v0_33_human_review_remediation"
        ] = epoch34_runtime_binding_review_remediation()
        self.ir["target"]["candidate_version"] = "v0_34"

    def activate_epoch35(self) -> None:
        self.activate_epoch34()
        self.ir["target"][
            "v0_34_human_review_remediation"
        ] = epoch35_runtime_binding_path_atomicity_remediation()
        self.ir["target"]["candidate_version"] = "v0_35"

    def setup_runtime_module(self):
        module_path = self.candidate / "tools/setup_runtime.py"
        spec = importlib.util.spec_from_file_location(
            f"setup_runtime_{id(self)}", module_path
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def candidate_tree_hash(self) -> tuple[str, int]:
        digest = hashlib.sha256()
        count = 0
        for path in sorted(self.candidate.rglob("*"), key=lambda item: item.as_posix()):
            if not path.is_file():
                continue
            relative = path.relative_to(self.candidate).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
            digest.update(b"\n")
            count += 1
        return digest.hexdigest(), count

    def generation_commit_binding(self, basis: dict) -> dict:
        report_path = (
            self.candidate / "validation/START_PACKAGE_VALIDATION_REPORT.json"
        )
        receipt_path = (
            self.candidate
            / "validation/START_PACKAGE_VALIDATION_REPORT_RECEIPT.json"
        )
        candidate_hash, file_count = self.candidate_tree_hash()
        binding = {
            "schema_version": "1.0",
            "binding_kind": "FACTORY_CANDIDATE_GENERATION_COMMIT",
            "program_id": self.ir["program_id"],
            "candidate_version": self.ir["target"].get("candidate_version"),
            "candidate_content_sha256": candidate_hash,
            "candidate_file_count": file_count,
            "validation_report_ref": (
                "validation/START_PACKAGE_VALIDATION_REPORT.json"
            ),
            "validation_report_sha256": hashlib.sha256(
                report_path.read_bytes()
            ).hexdigest(),
            "validation_report_receipt_ref": (
                "validation/START_PACKAGE_VALIDATION_REPORT_RECEIPT.json"
            ),
            "validation_report_receipt_sha256": hashlib.sha256(
                receipt_path.read_bytes()
            ).hexdigest(),
            "requirement_epoch": basis["requirement_epoch"],
            "requirement_ir_sha256": json_hash(self.ir),
            "validation_basis": deepcopy(basis),
            "generation_request_id": "REQ-GENERATE-EPOCH31",
            "generation_idempotency_key": "IDEM-GENERATE-EPOCH31",
        }
        binding["binding_sha256"] = json_hash(binding)
        return binding

    def authority_event_chain(
        self,
        *,
        include_descendant: bool = False,
        replay_commit: bool = False,
    ) -> tuple[list[dict], dict]:
        basis = self.authority_provenance()
        events: list[dict] = []
        previous_state: str | None = None
        previous_event: str | None = None

        def append_event(
            event_type: str,
            new_state: str,
            resulting_snapshot: dict,
            *,
            request_id: str,
            idempotency_key: str,
        ) -> None:
            nonlocal previous_event, previous_state
            revision = len(events) + 1
            event = {
                "schema_version": "1.0",
                "event_id": f"EVT-E31-{revision:04d}",
                "program_id": self.ir["program_id"],
                "revision": revision,
                "event_type": event_type,
                "request_id": request_id,
                "idempotency_key": idempotency_key,
                "actor": {
                    "type": "HUMAN_VIA_CODEX_CHAT",
                    "chat_thread_id": "TEST-EPOCH31",
                    "turn_id": f"TURN-{revision}",
                },
                "payload": {},
                "resulting_snapshot": resulting_snapshot,
                "previous_state_hash": previous_state,
                "new_state_hash": new_state,
                "previous_event_hash": previous_event,
                "created_at": "2026-08-10T00:00:00Z",
            }
            event["event_hash"] = json_hash(event)
            events.append(event)
            previous_state = new_state
            previous_event = event["event_hash"]

        for revision in range(1, basis["event_store_revision"] + 1):
            state = (
                basis["event_store_tip_sha256"]
                if revision == basis["event_store_revision"]
                else json_hash({"state_revision": revision})
            )
            append_event(
                "TEST_AUTHORITY_EVENT",
                state,
                {"state_revision": revision},
                request_id=f"REQ-E31-{revision:04d}",
                idempotency_key=f"IDEM-E31-{revision:04d}",
            )

        binding = self.generation_commit_binding(basis)
        generated_state = json_hash(
            {"candidate_generation_commit": binding["binding_sha256"]}
        )
        append_event(
            "START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW",
            generated_state,
            {"candidate": {"generation_commit_binding": binding}},
            request_id=binding["generation_request_id"],
            idempotency_key=binding["generation_idempotency_key"],
        )
        if replay_commit:
            replay_state = json_hash(
                {"replayed_candidate_generation_commit": binding["binding_sha256"]}
            )
            append_event(
                "START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW",
                replay_state,
                {"candidate": {"generation_commit_binding": deepcopy(binding)}},
                request_id="REQ-GENERATE-EPOCH31-REPLAY",
                idempotency_key="IDEM-GENERATE-EPOCH31-REPLAY",
            )
        if include_descendant:
            descendant_state = json_hash(
                {"audit_descendant_of": previous_state}
            )
            append_event(
                "AUTHORING_AUDIT_EVIDENCE_RECORDED",
                descendant_state,
                {"candidate": {"generation_commit_binding": binding}},
                request_id="REQ-E31-AUDIT-DESCENDANT",
                idempotency_key="IDEM-E31-AUDIT-DESCENDANT",
            )
        current = {
            **basis,
            "event_store_revision": len(events),
            "event_store_tip_sha256": events[-1]["new_state_hash"],
        }
        return events, current

    def epoch31_validation(
        self,
        events: list[dict],
        current: dict,
    ) -> dict:
        return validate_candidate(
            self.candidate,
            authoritative_sources=self.ir["sources"],
            authoritative_requirement_ir=self.ir,
            authority_provenance=current,
            authority_events=events,
        )

    def refresh_validation_report_receipt(self) -> None:
        report_path = (
            self.candidate / "validation/START_PACKAGE_VALIDATION_REPORT.json"
        )
        receipt_path = (
            self.candidate
            / "validation/START_PACKAGE_VALIDATION_REPORT_RECEIPT.json"
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertTrue(
            (
                self.candidate
                / "contracts/v2_9_release_closure/VALIDATION_REPORT_RECEIPT.schema.json"
            ).is_file()
        )
        external_checks = sorted(
            [
                check
                for check in report["checks"]
                if check["check_id"].startswith("FACTORY_EXTERNAL_")
            ],
            key=lambda check: check["check_id"],
        )
        receipt["report_sha256"] = hashlib.sha256(
            report_path.read_bytes()
        ).hexdigest()
        receipt["external_authority_checks_sha256"] = json_hash(
            external_checks
        )
        receipt["receipt_sha256"] = json_hash(
            without_hash(receipt, "receipt_sha256")
        )
        write_json(receipt_path, receipt)
        self.refresh_closure_and_portable_hashes()

    def rebind_epoch2_manifest(self) -> None:
        manifest_path = self.candidate / EPOCH2_ARTIFACTS[0]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for relative in list(manifest["runtime_module_sha256"]):
            manifest["runtime_module_sha256"][relative] = hashlib.sha256(
                (self.candidate / relative).read_bytes()
            ).hexdigest()
        for relative in list(manifest["schema_sha256"]):
            manifest["schema_sha256"][relative] = hashlib.sha256(
                (self.candidate / relative).read_bytes()
            ).hexdigest()
        for relative in list(manifest["contract_sha256"]):
            manifest["contract_sha256"][relative] = hashlib.sha256(
                (self.candidate / relative).read_bytes()
            ).hexdigest()
        manifest["manifest_sha256"] = json_hash(
            without_hash(manifest, "manifest_sha256")
        )
        write_json(manifest_path, manifest)

    def rewrite_v025_successor_inside_candidate(self) -> None:
        frozen_path = self.candidate / "canonical_sources/FROZEN_REQUIREMENT_IR.json"
        receipt_path = (
            self.candidate / "validation/HUMAN_REVIEW_CLOSURE_RECEIPT.json"
        )
        frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
        closure = frozen["target"]["v0_25_generation_failure_remediation"]
        closure["replacement_candidate"] = "candidate-v0_27"
        closure["successor_binding"]["candidate_version"] = "v0_27"
        write_json(frozen_path, frozen)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        entry = next(
            item
            for item in receipt["closures"]
            if item["requirement_key"]
            == "v0_25_generation_failure_remediation"
        )
        entry["replacement_candidate"] = "candidate-v0_27"
        entry["replacement_candidate_version"] = "v0_27"
        entry["requirement_sha256"] = json_hash(closure)
        receipt["portable_requirement_ir_sha256"] = json_hash(frozen)
        write_json(receipt_path, receipt)
        self.refresh_closure_and_portable_hashes()

    def test_epoch2_producer_and_both_oracles_pass(self) -> None:
        self.compile()
        self.assertEqual(
            validate_candidate(
                self.candidate,
                authoritative_sources=self.ir["sources"],
            )["status"],
            "PASS",
        )
        self.assertEqual(self.run_self_check().returncode, 0)
        self.assertTrue(all((self.candidate / path).is_file() for path in EPOCH2_ARTIFACTS))
        self.assertFalse((self.root / "execution-not-created").exists())
        manifest = json.loads(
            (self.candidate / EPOCH2_ARTIFACTS[0]).read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["architecture_epoch"], 2)
        self.assertEqual(manifest["requirement_epoch"], 26)
        portable = json.loads((self.candidate / "validation/PORTABLE_FILE_MANIFEST.json").read_text())
        for filename in ("lab_protocol.py", "lab_protocol_checks.py", "lab_protocol_contract_checks.py"):
            ref = "tools/harness_foundry_runtime/" + filename
            self.assertTrue((self.candidate / ref).is_file())
            self.assertIn(ref, portable["files"])
            self.assertNotIn(ref, manifest["runtime_module_sha256"])
        self.assertTrue(set(EPOCH24_CASES).issubset(manifest["required_adversarial_cases"]))
        self.assertEqual(
            manifest["source_authority_required_adversarial_cases"],
            sorted(EPOCH26_CASES),
        )
        self.assertEqual(manifest["human_authorization_status"], "NOT_GRANTED")
        self.assertFalse(manifest["execution_started"])

    def test_retained_store_contract_packages_complete_dependency_closure(
        self,
    ) -> None:
        self.compile()
        runtime_modules = {
            "tools/harness_foundry_runtime/store.py",
            "tools/harness_foundry_runtime/models.py",
            "tools/harness_foundry_runtime/constants.py",
        }
        self.assertTrue(
            all((self.candidate / relative).is_file() for relative in runtime_modules)
        )
        manifest = json.loads(
            (
                self.candidate
                / "V2_9_RELEASE_CLOSURE_CONTROL_PLANE_MANIFEST.json"
            ).read_text(encoding="utf-8")
        )
        self.assertTrue(
            runtime_modules.issubset(set(manifest["runtime_module_sha256"]))
        )
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONPATH"] = str(self.candidate / "tools")
        imported = subprocess.run(
            [
                sys.executable,
                "-c",
                "from harness_foundry_runtime.store import ControlEventStore",
            ],
            cwd=self.candidate,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(imported.returncode, 0, imported.stderr)

        missing = self.candidate / "tools/harness_foundry_runtime/models.py"
        make_path_writable(missing)
        missing.unlink()
        self.assertIn("PORTABLE_RUNTIME_DEPENDENCY_MISSING", self.codes())
        standalone = json.loads(self.run_self_check().stdout)
        self.assertIn(
            "PORTABLE_RUNTIME_DEPENDENCY_MISSING",
            {finding["code"] for finding in standalone["findings"]},
        )

    def test_epoch32_requirement_routes_to_producer_both_oracles_and_binder(
        self,
    ) -> None:
        self.ir["target"][
            "v0_31_runtime_binding_failure_remediation"
        ] = epoch32_runtime_binding_remediation()
        self.ir["target"]["candidate_version"] = "v0_32"
        self.compile()

        manifest = json.loads(
            (
                self.candidate
                / "V2_9_RELEASE_CLOSURE_CONTROL_PLANE_MANIFEST.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["requirement_epoch"], 32)
        self.assertEqual(
            set(manifest["runtime_binder_required_adversarial_cases"]),
            set(epoch32_runtime_binding_remediation()["required_adversarial_cases"]),
        )
        self.assertTrue(
            set(epoch32_runtime_binding_remediation()["required_adversarial_cases"])
            .isdisjoint(manifest["source_authority_required_adversarial_cases"])
        )
        events, current = self.authority_event_chain()
        report = self.epoch31_validation(events, current)
        self.assertEqual(report["status"], "PASS", report["blocking_findings"])
        self.assertEqual(self.run_self_check().returncode, 0)

        execution = self.root / "epoch32-official-binder-execution"
        binding = subprocess.run(
            [
                sys.executable,
                "tools/setup_runtime.py",
                "--execution-root",
                str(execution),
            ],
            cwd=self.candidate,
            env=self.receiver_authority_environment(),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(binding.returncode, 0, binding.stderr or binding.stdout)
        self.assertEqual(json.loads(binding.stdout)["status"], "PASS")
        self.assertTrue(
            (execution / ".harness-foundry/runtime_binding.json").is_file()
        )

        contract = json.loads(
            (
                self.candidate / "validation/RUNTIME_BINDING_CONTRACT.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            contract["setup_sha256"],
            hashlib.sha256(
                (self.candidate / "tools/setup_runtime.py").read_bytes()
            ).hexdigest(),
        )
        self.assertTrue(contract["validation_before_first_execution_root_write"])
        closure = json.loads(
            (
                self.candidate / "validation/HUMAN_REVIEW_CLOSURE_RECEIPT.json"
            ).read_text(encoding="utf-8")
        )
        epoch32_entry = next(
            item
            for item in closure["closures"]
            if item["requirement_key"]
            == "v0_31_runtime_binding_failure_remediation"
        )
        self.assertEqual(
            epoch32_entry["evidence_sha256"]["tools/setup_runtime.py"],
            contract["setup_sha256"],
        )

    def test_runtime_binder_rejects_missing_dependency_before_root_write(
        self,
    ) -> None:
        self.ir["target"][
            "v0_31_runtime_binding_failure_remediation"
        ] = epoch32_runtime_binding_remediation()
        self.ir["target"]["candidate_version"] = "v0_32"
        self.compile()
        probe = self.candidate / "tools/harness_foundry_runtime/binder_probe.py"
        make_path_writable(probe)
        probe.write_text(
            "from .missing_for_binder_test import value\n",
            encoding="utf-8",
        )
        portable_path = self.candidate / "validation/PORTABLE_FILE_MANIFEST.json"
        portable = json.loads(portable_path.read_text(encoding="utf-8"))
        portable["files"][probe.relative_to(self.candidate).as_posix()] = (
            hashlib.sha256(probe.read_bytes()).hexdigest()
        )
        write_json(portable_path, portable)

        execution = self.root / "missing-dependency-execution"
        binding = subprocess.run(
            [
                sys.executable,
                "tools/setup_runtime.py",
                "--execution-root",
                str(execution),
            ],
            cwd=self.candidate,
            env=self.receiver_authority_environment(),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(binding.returncode, 0)
        self.assertIn("portable runtime dependency is missing", binding.stdout)
        self.assertFalse(execution.exists())

    def test_runtime_binder_rejects_dangling_uri_without_creating_root(
        self,
    ) -> None:
        self.activate_epoch33()
        self.compile()
        readme_path = self.candidate / "README.md"
        make_path_writable(readme_path)
        readme_path.write_text(
            readme_path.read_text(encoding="utf-8")
            + "\nAttack probe: harness-resource://candidate/missing/dangling.json\n",
            encoding="utf-8",
        )
        portable_path = self.candidate / "validation/PORTABLE_FILE_MANIFEST.json"
        portable = json.loads(portable_path.read_text(encoding="utf-8"))
        portable["files"]["README.md"] = hashlib.sha256(
            readme_path.read_bytes()
        ).hexdigest()
        write_json(portable_path, portable)
        execution = self.root / "dangling-uri-execution"
        binding = subprocess.run(
            [
                sys.executable,
                "tools/setup_runtime.py",
                "--execution-root",
                str(execution),
            ],
            cwd=self.candidate,
            env=self.receiver_authority_environment(),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(binding.returncode, 0)
        self.assertIn("Candidate Resource URI is dangling", binding.stdout)
        self.assertFalse(execution.exists())

    def test_runtime_binder_rejects_portable_inventory_gap_without_creating_root(
        self,
    ) -> None:
        self.activate_epoch33()
        self.compile()
        portable_path = self.candidate / "validation/PORTABLE_FILE_MANIFEST.json"
        portable = json.loads(portable_path.read_text(encoding="utf-8"))
        portable["files"].pop("README.md")
        write_json(portable_path, portable)
        execution = self.root / "portable-inventory-gap-execution"
        binding = subprocess.run(
            [
                sys.executable,
                "tools/setup_runtime.py",
                "--execution-root",
                str(execution),
            ],
            cwd=self.candidate,
            env=self.receiver_authority_environment(),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(binding.returncode, 0)
        self.assertIn(
            "portable file manifest does not cover Candidate bytes",
            binding.stdout,
        )
        self.assertFalse(execution.exists())

    def test_runtime_binder_rejects_existing_root_by_default_and_allows_exact_reentry(
        self,
    ) -> None:
        self.activate_epoch33()
        self.compile()
        execution = self.root / "existing-root-boundary-execution"
        environment = self.receiver_authority_environment()
        command = [
            sys.executable,
            "tools/setup_runtime.py",
            "--execution-root",
            str(execution),
        ]
        first = subprocess.run(
            command,
            cwd=self.candidate,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(first.returncode, 0, first.stdout)
        receipt_path = execution / ".harness-foundry/runtime_binding.json"
        original_receipt = receipt_path.read_bytes()

        default_reentry = subprocess.run(
            command,
            cwd=self.candidate,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(default_reentry.returncode, 0)
        self.assertIn("execution root already exists", default_reentry.stdout)
        self.assertEqual(receipt_path.read_bytes(), original_receipt)

        exact_reentry = subprocess.run(
            [*command, "--allow-idempotent-reentry"],
            cwd=self.candidate,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(exact_reentry.returncode, 0, exact_reentry.stdout)
        self.assertTrue(json.loads(exact_reentry.stdout)["reused_existing_binding"])
        self.assertEqual(receipt_path.read_bytes(), original_receipt)

        tampered = json.loads(receipt_path.read_text(encoding="utf-8"))
        tampered["candidate_manifest_sha256"] = "f" * 64
        write_json(receipt_path, tampered)
        tampered_receipt = receipt_path.read_bytes()
        mismatched_reentry = subprocess.run(
            [*command, "--allow-idempotent-reentry"],
            cwd=self.candidate,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(mismatched_reentry.returncode, 0)
        self.assertIn("does not exactly match", mismatched_reentry.stdout)
        self.assertEqual(receipt_path.read_bytes(), tampered_receipt)

    def test_epoch35_remediation_contract_is_accepted_by_both_oracles(
        self,
    ) -> None:
        remediation = epoch35_runtime_binding_path_atomicity_remediation()
        self.assertTrue(
            _epoch35_runtime_binding_path_atomicity_remediation_is_complete(
                remediation
            )
        )
        self.assertTrue(
            _epoch35_runtime_binding_path_atomicity_is_complete(remediation)
        )

    def test_runtime_binder_rejects_dangling_execution_root_symlink(
        self,
    ) -> None:
        self.activate_epoch33()
        self.compile()
        execution = self.root / "dangling-execution-root-link"
        outside_target = self.root / "outside-target-not-created"
        execution.symlink_to(outside_target, target_is_directory=True)
        binding = subprocess.run(
            [
                sys.executable,
                "tools/setup_runtime.py",
                "--execution-root",
                str(execution),
            ],
            cwd=self.candidate,
            env=self.receiver_authority_environment(),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(binding.returncode, 0)
        self.assertIn("execution root must not be a symlink", binding.stdout)
        self.assertTrue(execution.is_symlink())
        self.assertFalse(outside_target.exists())

    def test_runtime_binder_rejects_execution_root_symlink_to_existing_directory(
        self,
    ) -> None:
        self.activate_epoch33()
        self.compile()
        outside_target = self.root / "existing-outside-target"
        outside_target.mkdir()
        marker = outside_target / "preserved.txt"
        marker.write_text("preserved", encoding="utf-8")
        execution = self.root / "existing-target-execution-root-link"
        execution.symlink_to(outside_target, target_is_directory=True)
        binding = subprocess.run(
            [
                sys.executable,
                "tools/setup_runtime.py",
                "--execution-root",
                str(execution),
            ],
            cwd=self.candidate,
            env=self.receiver_authority_environment(),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(binding.returncode, 0)
        self.assertIn("execution root must not be a symlink", binding.stdout)
        self.assertTrue(execution.is_symlink())
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserved")

    def test_runtime_binder_atomic_noreplace_rejects_appeared_empty_root(
        self,
    ) -> None:
        self.activate_epoch33()
        self.compile()
        module = self.setup_runtime_module()
        parent = self.root / "appeared-root-parent"
        parent.mkdir()
        execution = parent / "execution"
        resolved, descriptor, parent_identity = module.pin_parent(parent)
        staging = Path(
            tempfile.mkdtemp(prefix=".execution.runtime-binding-", dir=parent)
        )
        try:
            self.assertFalse(execution.exists())
            execution.mkdir()
            with self.assertRaisesRegex(
                ValueError, "execution root appeared during atomic binding"
            ):
                module.atomic_publish_noreplace(
                    staging,
                    execution,
                    descriptor,
                    parent,
                    resolved,
                    parent_identity,
                )
            self.assertTrue(execution.is_dir())
            self.assertTrue(staging.is_dir())
        finally:
            os.close(descriptor)

    def test_runtime_binder_rejects_parent_identity_swap(self) -> None:
        self.activate_epoch33()
        self.compile()
        module = self.setup_runtime_module()
        container = self.root / "parent-swap-container"
        container.mkdir()
        parent = container / "approved-parent"
        parent.mkdir()
        resolved, descriptor, parent_identity = module.pin_parent(parent)
        moved_parent = container / "moved-approved-parent"
        parent.rename(moved_parent)
        parent.mkdir()
        staging = Path(
            tempfile.mkdtemp(prefix=".execution.runtime-binding-", dir=moved_parent)
        )
        try:
            with self.assertRaisesRegex(
                ValueError, "execution root parent identity changed during binding"
            ):
                module.atomic_publish_noreplace(
                    staging,
                    resolved / "execution",
                    descriptor,
                    parent,
                    resolved,
                    parent_identity,
                )
            self.assertTrue(staging.is_dir())
            self.assertFalse((parent / "execution").exists())
        finally:
            os.close(descriptor)

    def test_runtime_binder_atomic_noreplace_rejects_target_symlink_swap(
        self,
    ) -> None:
        self.activate_epoch33()
        self.compile()
        module = self.setup_runtime_module()
        parent = self.root / "target-symlink-swap-parent"
        parent.mkdir()
        execution = parent / "execution"
        outside_target = self.root / "target-symlink-outside"
        resolved, descriptor, parent_identity = module.pin_parent(parent)
        staging = Path(
            tempfile.mkdtemp(prefix=".execution.runtime-binding-", dir=parent)
        )
        execution.symlink_to(outside_target, target_is_directory=True)
        try:
            with self.assertRaisesRegex(
                ValueError, "execution root appeared during atomic binding"
            ):
                module.atomic_publish_noreplace(
                    staging,
                    execution,
                    descriptor,
                    parent,
                    resolved,
                    parent_identity,
                )
            self.assertTrue(execution.is_symlink())
            self.assertFalse(outside_target.exists())
            self.assertTrue(staging.is_dir())
        finally:
            os.close(descriptor)

    def test_epoch35_factory_executes_path_identity_and_noreplace_regressions(
        self,
    ) -> None:
        self.activate_epoch35()
        self.compile()
        remediation = epoch35_runtime_binding_path_atomicity_remediation()
        required = remediation["required_regression_tests"]
        receipt = json.loads(
            (
                self.candidate
                / "validation/FACTORY_REGRESSION_EXECUTION_RECEIPT.json"
            ).read_text(encoding="utf-8")
        )
        manifest = json.loads(
            (
                self.candidate
                / "V2_9_RELEASE_CLOSURE_CONTROL_PLANE_MANIFEST.json"
            ).read_text(encoding="utf-8")
        )
        contract = json.loads(
            (
                self.candidate / "validation/RUNTIME_BINDING_CONTRACT.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["required_tests"], required)
        self.assertEqual(receipt["executed_tests"], required)
        self.assertEqual(manifest["requirement_epoch"], 35)
        self.assertEqual(manifest["factory_required_regression_tests"], required)
        self.assertTrue(contract["fresh_root_atomic_noreplace_required"])
        self.assertEqual(
            contract["unsupported_noreplace_platform_behavior"], "FAIL_CLOSED"
        )
        self.assertEqual(self.run_self_check().returncode, 0)

    def test_epoch33_review_remediation_routes_to_producer_and_both_oracles(
        self,
    ) -> None:
        self.ir["target"][
            "v0_31_runtime_binding_failure_remediation"
        ] = epoch32_runtime_binding_remediation()
        self.ir["target"][
            "v0_32_human_review_remediation"
        ] = epoch33_runtime_binding_review_remediation()
        self.ir["target"]["candidate_version"] = "v0_33"
        self.compile()
        manifest = json.loads(
            (
                self.candidate
                / "V2_9_RELEASE_CLOSURE_CONTROL_PLANE_MANIFEST.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["requirement_epoch"], 33)
        self.assertEqual(
            set(manifest["runtime_binder_required_adversarial_cases"]),
            set(epoch32_runtime_binding_remediation()["required_adversarial_cases"]),
        )
        self.assertTrue(
            set(manifest["runtime_binder_required_adversarial_cases"]).isdisjoint(
                manifest["source_authority_required_adversarial_cases"]
            )
        )
        events, current = self.authority_event_chain()
        report = self.epoch31_validation(events, current)
        self.assertEqual(report["status"], "PASS", report["blocking_findings"])
        self.assertEqual(self.run_self_check().returncode, 0)

    def test_epoch34_factory_validator_executes_hash_bound_required_regressions(
        self,
    ) -> None:
        self.activate_epoch34()
        self.compile()
        receipt = json.loads(
            (
                self.candidate
                / "validation/FACTORY_REGRESSION_EXECUTION_RECEIPT.json"
            ).read_text(encoding="utf-8")
        )
        required = epoch34_runtime_binding_review_remediation()[
            "required_regression_tests"
        ]
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["required_tests"], required)
        self.assertEqual(receipt["executed_tests"], required)
        self.assertEqual(receipt["returncode"], 0)
        self.assertFalse(receipt["runtime_claims_verified"])
        self.assertFalse(receipt["workpack_execution_authorized"])
        self.assertEqual(
            receipt["receipt_sha256"],
            json_hash(without_hash(receipt, "receipt_sha256")),
        )
        report = json.loads(
            (
                self.candidate / "validation/START_PACKAGE_VALIDATION_REPORT.json"
            ).read_text(encoding="utf-8")
        )
        regression = next(
            item
            for item in report["checks"]
            if item["check_id"] == "FACTORY_REQUIRED_REGRESSION_EXECUTION"
        )
        self.assertEqual(regression["status"], "PASS")
        self.assertEqual(
            regression["factory_regression_execution"]["executed_tests"],
            required,
        )

    def test_epoch34_factory_validator_rejects_missing_required_test_definition(
        self,
    ) -> None:
        self.activate_epoch34()
        remediation = self.ir["target"]["v0_33_human_review_remediation"]
        remediation["required_regression_tests"][-1] = (
            "test_required_but_not_defined"
        )
        remediation["implementation_evidence"]["regression_test_sha256"] = (
            hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        )
        findings, evidence, executed = _factory_required_regression_execution(
            self.candidate,
            self.ir,
            require_receipt=False,
        )
        self.assertFalse(executed)
        self.assertEqual(evidence["status"], "FAIL")
        self.assertIn(
            "FACTORY_REQUIRED_REGRESSION_DEFINITION_MISSING",
            {item["code"] for item in findings},
        )

    def test_missing_retained_store_uri_is_rejected_by_both_oracles(self) -> None:
        self.compile()
        report_path = self.candidate / "validation/START_PACKAGE_VALIDATION_REPORT.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["retained_store_ref"] = (
            "harness-resource://candidate/tools/harness_foundry_runtime/store.py"
        )
        write_json(report_path, report)
        missing = self.candidate / "tools/harness_foundry_runtime/store.py"
        make_path_writable(missing)
        missing.unlink()

        self.assertIn("CANDIDATE_RESOURCE_URI_DANGLING", self.codes())
        standalone = json.loads(self.run_self_check().stdout)
        self.assertIn(
            "CANDIDATE_RESOURCE_URI_DANGLING",
            {finding["code"] for finding in standalone["findings"]},
        )

    def test_factory_external_oracle_rejects_synchronized_authority_rewrite(self) -> None:
        self.compile()
        frozen_path = self.candidate / "canonical_sources/FROZEN_REQUIREMENT_IR.json"
        manifest_path = self.candidate / "canonical_sources/SOURCE_MANIFEST.json"
        frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        frozen["sources"][0]["authority_level"] = "HUMAN_PROVIDED"
        manifest["sources"][0]["authority_level"] = "HUMAN_PROVIDED"
        manifest["sources"][0]["declared_authority_level"] = None
        write_json(frozen_path, frozen)
        write_json(manifest_path, manifest)
        report = validate_candidate(
            self.candidate,
            authoritative_sources=self.ir["sources"],
        )
        factory_oracle = next(
            check
            for check in report["checks"]
            if check["check_id"] == "FACTORY_LOCAL_SOURCE_CONSISTENCY"
        )
        self.assertEqual(factory_oracle["status"], "FAIL")
        self.assertEqual(
            {finding["code"] for finding in factory_oracle["findings"]},
            {"SOURCE_AUTHORITY_NORMALIZATION_CONTRACT_INVALID"},
        )
        standalone = json.loads(self.run_self_check().stdout)
        self.assertIn(
            "SOURCE_AUTHORITY_NORMALIZATION_CONTRACT_INVALID",
            {finding["code"] for finding in standalone["findings"]},
        )

    def test_receiver_policy_contains_only_semantic_source_fields(self) -> None:
        sources = deepcopy(self.ir["sources"])
        sources[0].update(
            {
                "path_or_uri": "/Users/receiver-a/source.md",
                "snapshot_path": "/private/tmp/receiver-a-snapshot.md",
                "registered_at": "2026-08-10T00:00:00Z",
            }
        )
        key = Ed25519PrivateKey.generate()
        first, trust_anchor = receiver_source_authority_bundle(
            sources, requirement_ir=self.ir, private_key=key
        )
        sources[0].update(
            {
                "path_or_uri": "/home/receiver-b/source.md",
                "snapshot_path": "/tmp/receiver-b-snapshot.md",
                "registered_at": "2030-01-01T00:00:00Z",
            }
        )
        second = source_authority_policy_lock(
            sources,
            release_history=first["release_history"],
            signer_private_key=key,
            trust_anchor=trust_anchor,
            validation_report_binding=first.get("validation_report_binding"),
        )
        self.assertEqual(first, second)
        self.assertEqual(
            set(first["sources"][0]),
            {
                "source_id",
                "content_sha256",
                "copy_policy",
                "loaded_completely",
                "declared_authority_level",
                "canonical_authority_level",
            },
        )

    def test_policy_local_locator_injection_is_rejected(self) -> None:
        self.compile()
        policy, trust_anchor = receiver_source_authority_bundle(
            self.ir["sources"], requirement_ir=self.ir
        )
        policy["sources"][0]["path_or_uri"] = "/Users/attacker/source.md"
        policy["lock_sha256"] = json_hash(
            without_hash(policy, "lock_sha256")
        )
        result = self.run_self_check(policy, trust_anchor)
        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertIn(
            "SOURCE_AUTHORITY_POLICY_LOCK_INVALID",
            {finding["code"] for finding in report["findings"]},
        )

    def test_portable_source_uri_relabel_is_rejected_by_both_oracles(self) -> None:
        self.compile()
        manifest_path = self.candidate / "canonical_sources/SOURCE_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["sources"][0]["path_or_uri"] = (
            "harness-resource://candidate/canonical_sources/evidence/"
            "ATTACKER.source_receipt.json"
        )
        write_json(manifest_path, manifest)
        self.refresh_closure_and_portable_hashes()
        self.assertIn("PORTABLE_SOURCE_RECEIPT_INVALID", self.codes())
        report = json.loads(self.run_self_check().stdout)
        self.assertIn(
            "SOURCE_PORTABLE_URI_PROJECTION_INVALID",
            {finding["code"] for finding in report["findings"]},
        )

    def test_portable_source_index_synchronized_rehash_is_rejected_by_both_oracles(
        self,
    ) -> None:
        self.compile()
        index_path = (
            self.candidate / "canonical_sources/PORTABLE_SOURCE_INDEX.json"
        )
        index = json.loads(index_path.read_text(encoding="utf-8"))
        entry = index["sources"][0]
        if entry["payload_embedded"]:
            entry["payload_ref"] = (
                "harness-resource://candidate/canonical_sources/evidence/"
                "ATTACKER.payload.b64"
            )
        else:
            entry["receipt_ref"] = (
                "harness-resource://candidate/canonical_sources/evidence/"
                "ATTACKER.source_receipt.json"
            )
        write_json(index_path, index)
        self.refresh_closure_and_portable_hashes()
        self.assertTrue(
            {
                "PORTABLE_SOURCE_INDEX_INVALID",
                "PORTABLE_SOURCE_RECEIPT_INVALID",
                "PORTABLE_SOURCE_PAYLOAD_INVALID",
            }
            & self.codes()
        )
        standalone = json.loads(self.run_self_check().stdout)
        self.assertIn(
            "PORTABLE_SOURCE_INDEX_SEMANTICS_INVALID",
            {finding["code"] for finding in standalone["findings"]},
        )

    def test_modified_signed_policy_payload_is_rejected(self) -> None:
        self.compile()
        policy, trust_anchor = receiver_source_authority_bundle(
            self.ir["sources"], requirement_ir=self.ir
        )
        policy["sources"][0]["content_sha256"] = "f" * 64
        signed_body = {
            key: value
            for key, value in policy.items()
            if key not in {
                "policy_payload_sha256",
                "signature_algorithm",
                "signature_base64",
                "lock_sha256",
            }
        }
        policy["policy_payload_sha256"] = json_hash(signed_body)
        policy["lock_sha256"] = json_hash(
            without_hash(policy, "lock_sha256")
        )
        result = self.run_self_check(policy, trust_anchor)
        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertTrue(
            {
                "SOURCE_AUTHORITY_POLICY_LOCK_INVALID",
                "SOURCE_AUTHORITY_POLICY_SIGNATURE_INVALID",
            }
            & {finding["code"] for finding in report["findings"]},
        )

    def test_valid_signature_with_stale_issuer_epoch_is_rejected(self) -> None:
        self.compile()
        key = Ed25519PrivateKey.generate()
        policy, trust_anchor = receiver_source_authority_bundle(
            self.ir["sources"], requirement_ir=self.ir, private_key=key
        )
        policy["issuer_binding"]["requirement_epoch"] = 25
        signed_body = {
            field: value
            for field, value in policy.items()
            if field not in {
                "policy_payload_sha256",
                "signature_algorithm",
                "signature_base64",
                "lock_sha256",
            }
        }
        payload = json.dumps(
            signed_body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        policy["policy_payload_sha256"] = hashlib.sha256(payload).hexdigest()
        policy["signature_base64"] = base64.b64encode(
            key.sign(payload)
        ).decode("ascii")
        policy["lock_sha256"] = json_hash(
            without_hash(policy, "lock_sha256")
        )
        result = self.run_self_check(policy, trust_anchor)
        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertIn(
            "SOURCE_AUTHORITY_POLICY_LOCK_INVALID",
            {finding["code"] for finding in report["findings"]},
        )

    def test_candidate_local_source_authority_anchor_is_rejected(self) -> None:
        self.compile()
        policy, trust_anchor = receiver_source_authority_bundle(
            self.ir["sources"], requirement_ir=self.ir
        )
        policy_path = self.candidate / "ATTACKER_SOURCE_POLICY.json"
        anchor_path = self.candidate / "ATTACKER_SOURCE_ANCHOR.json"
        write_json(policy_path, policy)
        write_json(anchor_path, trust_anchor)
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["HF_SOURCE_AUTHORITY_POLICY_LOCK"] = str(policy_path)
        environment["HF_SOURCE_AUTHORITY_TRUST_ANCHOR"] = str(anchor_path)
        environment["HF_SOURCE_AUTHORITY_TRUST_ANCHOR_SHA256"] = hashlib.sha256(
            anchor_path.read_bytes()
        ).hexdigest()
        result = subprocess.run(
            [sys.executable, "tools/self_check.py"],
            cwd=self.candidate,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertIn(
            "SOURCE_AUTHORITY_POLICY_LOCK_INVALID",
            {finding["code"] for finding in report["findings"]},
        )

    def test_v025_closure_fully_synchronized_wrong_successor_is_rejected_by_both_external_oracles(
        self,
    ) -> None:
        self.compile()
        self.rewrite_v025_successor_inside_candidate()
        self.assertIn("RELEASE_HISTORY_AUTHORITY_MISMATCH", self.codes())
        standalone = json.loads(self.run_self_check().stdout)
        self.assertIn(
            "RELEASE_HISTORY_AUTHORITY_MISMATCH",
            {finding["code"] for finding in standalone["findings"]},
        )

    def test_standalone_requires_signed_release_history_authority(self) -> None:
        self.compile()
        policy, trust_anchor = receiver_source_authority_bundle(
            self.ir["sources"],
            requirement_ir=self.ir,
            release_history_override=[],
        )
        result = self.run_self_check(policy, trust_anchor)
        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertIn(
            "SOURCE_AUTHORITY_POLICY_LOCK_INVALID",
            {finding["code"] for finding in report["findings"]},
        )

    def test_factory_history_oracle_rejects_candidate_internal_synchronized_rewrite(
        self,
    ) -> None:
        self.compile()
        self.rewrite_v025_successor_inside_candidate()
        report = validate_candidate(
            self.candidate,
            authoritative_requirement_ir=self.ir,
        )
        oracle = next(
            check
            for check in report["checks"]
            if check["check_id"] == "FACTORY_LOCAL_REQUIREMENT_IR_CONSISTENCY"
        )
        self.assertEqual(oracle["status"], "FAIL")
        self.assertIn(
            "RELEASE_HISTORY_AUTHORITY_MISMATCH",
            {finding["code"] for finding in oracle["findings"]},
        )

    def test_release_history_policy_rejects_duplicate_conflicting_or_stale_entries(
        self,
    ) -> None:
        self.compile()
        canonical = _release_history_semantic_entries(self.ir)
        duplicate = [*canonical, deepcopy(canonical[0])]
        conflicting_entry = deepcopy(canonical[0])
        conflicting_entry["replacement_candidate"] = "candidate-v0_99"
        conflicting_entry["successor_candidate_version"] = "v0_99"
        conflicting = [*canonical, conflicting_entry]
        stale = canonical[:-1]
        self.assertTrue(stale)
        for name, history, expected_code in (
            ("duplicate", duplicate, "SOURCE_AUTHORITY_POLICY_LOCK_INVALID"),
            ("conflicting", conflicting, "SOURCE_AUTHORITY_POLICY_LOCK_INVALID"),
            ("stale", stale, "RELEASE_HISTORY_AUTHORITY_MISMATCH"),
        ):
            with self.subTest(name=name):
                policy, trust_anchor = receiver_source_authority_bundle(
                    self.ir["sources"],
                    requirement_ir=self.ir,
                    release_history_override=history,
                )
                result = self.run_self_check(policy, trust_anchor)
                self.assertNotEqual(result.returncode, 0)
                report = json.loads(result.stdout)
                self.assertIn(
                    expected_code,
                    {finding["code"] for finding in report["findings"]},
                )

    def test_epoch28_signed_release_history_authority_is_producer_routed(
        self,
    ) -> None:
        self.ir["target"]["candidate_version"] = "v0_28"
        self.ir["target"]["v0_27_human_review_remediation"] = (
            epoch28_remediation()
        )
        self.compile()
        manifest = json.loads(
            (
                self.candidate
                / "V2_9_RELEASE_CLOSURE_CONTROL_PLANE_MANIFEST.json"
            ).read_text(encoding="utf-8")
        )
        schema = json.loads(
            (
                self.candidate
                / "contracts/v2_9_release_closure/"
                "SOURCE_AUTHORITY_POLICY_LOCK.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["requirement_epoch"], 28)
        self.assertTrue(
            set(epoch28_remediation()["required_adversarial_cases"])
            <= set(manifest["source_authority_required_adversarial_cases"])
        )
        self.assertEqual(
            schema["properties"]["lock_id"]["const"],
            "V29_SOURCE_AUTHORITY_POLICY_LOCK_V4",
        )
        standalone = self.run_self_check()
        self.assertEqual(standalone.returncode, 0, standalone.stdout)

    def test_epoch28_factory_validator_requires_both_external_authority_inputs(
        self,
    ) -> None:
        self.ir["target"]["candidate_version"] = "v0_28"
        self.ir["target"]["v0_27_human_review_remediation"] = (
            epoch28_remediation()
        )
        self.compile()

        report = validate_candidate(self.candidate)

        self.assertEqual(report["status"], "FAIL")
        external_checks = {
            check["check_id"]: check
            for check in report["checks"]
            if check["check_id"].startswith("FACTORY_EXTERNAL_")
        }
        self.assertEqual(
            set(external_checks),
            {
                "FACTORY_EXTERNAL_SOURCE_AUTHORITY_ORACLE",
                "FACTORY_EXTERNAL_RELEASE_HISTORY_ORACLE",
            },
        )
        for check in external_checks.values():
            self.assertEqual(check["status"], "FAIL")
            self.assertEqual(
                check["authority_input"],
                "NOT_SUPPLIED_EXTERNAL_AUTHORITY_REQUIRED",
            )
            self.assertIn(
                "EXTERNAL_AUTHORITY_INPUT_REQUIRED",
                {finding["code"] for finding in check["findings"]},
            )

    def test_epoch28_candidate_report_preserves_external_authority_provenance(
        self,
    ) -> None:
        self.ir["target"]["candidate_version"] = "v0_28"
        self.ir["target"]["v0_27_human_review_remediation"] = (
            epoch28_remediation()
        )
        expected = self.authority_provenance()
        self.compile()

        report = json.loads(
            (
                self.candidate
                / "validation/START_PACKAGE_VALIDATION_REPORT.json"
            ).read_text(encoding="utf-8")
        )
        external_checks = {
            check["check_id"]: check
            for check in report["checks"]
            if check["check_id"].startswith("FACTORY_EXTERNAL_")
        }
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(
            external_checks["FACTORY_EXTERNAL_SOURCE_AUTHORITY_ORACLE"][
                "authority_input"
            ],
            "FACTORY_EVENT_STORE_SOURCE_REGISTRY",
        )
        self.assertEqual(
            external_checks["FACTORY_EXTERNAL_RELEASE_HISTORY_ORACLE"][
                "authority_input"
            ],
            "FACTORY_EVENT_STORE_REQUIREMENT_IR",
        )
        for check in external_checks.values():
            self.assertEqual(check["authority_provenance"], expected)

    def test_epoch29_candidate_routes_fail_closed_external_authority_contract(
        self,
    ) -> None:
        self.ir["target"]["candidate_version"] = "v0_29"
        self.ir["target"]["v0_27_human_review_remediation"] = (
            epoch28_remediation()
        )
        self.ir["target"]["v0_28_human_review_remediation"] = (
            epoch29_remediation()
        )
        expected = self.authority_provenance()
        self.compile()

        manifest = json.loads(
            (
                self.candidate
                / "V2_9_RELEASE_CLOSURE_CONTROL_PLANE_MANIFEST.json"
            ).read_text(encoding="utf-8")
        )
        embedded_report = json.loads(
            (
                self.candidate
                / "validation/START_PACKAGE_VALIDATION_REPORT.json"
            ).read_text(encoding="utf-8")
        )
        direct_report = validate_candidate(self.candidate)

        self.assertEqual(manifest["requirement_epoch"], 29)
        self.assertTrue(
            set(epoch29_remediation()["required_adversarial_cases"])
            <= set(manifest["source_authority_required_adversarial_cases"])
        )
        self.assertEqual(direct_report["status"], "FAIL")
        for check in embedded_report["checks"]:
            if check["check_id"].startswith("FACTORY_EXTERNAL_"):
                self.assertEqual(check["status"], "PASS")
                self.assertEqual(check["authority_provenance"], expected)

    def test_epoch30_validation_report_receipt_is_hash_bound(self) -> None:
        self.activate_epoch30()
        self.compile()

        report_path = (
            self.candidate / "validation/START_PACKAGE_VALIDATION_REPORT.json"
        )
        receipt_path = (
            self.candidate
            / "validation/START_PACKAGE_VALIDATION_REPORT_RECEIPT.json"
        )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(
            receipt["report_sha256"],
            hashlib.sha256(report_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            receipt["receipt_sha256"],
            json_hash(without_hash(receipt, "receipt_sha256")),
        )
        closure = json.loads(
            (
                self.candidate
                / "validation/HUMAN_REVIEW_CLOSURE_RECEIPT.json"
            ).read_text(encoding="utf-8")
        )
        epoch30 = next(
            item
            for item in closure["closures"]
            if item["requirement_key"] == "v0_29_human_review_remediation"
        )
        receipt_ref = (
            "validation/START_PACKAGE_VALIDATION_REPORT_RECEIPT.json"
        )
        self.assertIn(receipt_ref, epoch30["evidence_refs"])
        self.assertEqual(
            epoch30["evidence_sha256"][receipt_ref],
            hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        )
        portable = json.loads(
            (
                self.candidate / "validation/PORTABLE_FILE_MANIFEST.json"
            ).read_text(encoding="utf-8")
        )
        self.assertIn(receipt_ref, portable["files"])
        standalone = self.run_self_check()
        self.assertEqual(standalone.returncode, 0, standalone.stdout)

        policy, trust_anchor = receiver_source_authority_bundle(
            self.ir["sources"],
            requirement_ir=self.ir,
            candidate_root=self.candidate,
        )
        report_bytes = report_path.read_bytes()
        receipt_bytes = receipt_path.read_bytes()
        make_path_writable(receipt_path)
        make_path_writable(report_path)
        receipt_path.unlink()
        self.assertIn("VALIDATION_REPORT_RECEIPT_MISSING", self.codes())
        missing_receipt = json.loads(
            self.run_self_check(policy, trust_anchor).stdout
        )
        self.assertIn(
            "VALIDATION_REPORT_RECEIPT_MISSING",
            {finding["code"] for finding in missing_receipt["findings"]},
        )
        receipt_path.write_bytes(receipt_bytes)
        report_path.unlink()
        self.assertIn("VALIDATION_REPORT_RECEIPT_MISSING", self.codes())
        missing_report = json.loads(
            self.run_self_check(policy, trust_anchor).stdout
        )
        self.assertIn(
            "VALIDATION_REPORT_RECEIPT_MISSING",
            {finding["code"] for finding in missing_report["findings"]},
        )
        report_path.write_bytes(report_bytes)

    def test_epoch30_validation_report_tamper_is_rejected_by_both_oracles(
        self,
    ) -> None:
        self.activate_epoch30()
        self.compile()
        policy, trust_anchor = receiver_source_authority_bundle(
            self.ir["sources"],
            requirement_ir=self.ir,
            candidate_root=self.candidate,
        )
        report_path = (
            self.candidate / "validation/START_PACKAGE_VALIDATION_REPORT.json"
        )
        protected_paths = [
            report_path,
            self.candidate
            / "validation/START_PACKAGE_VALIDATION_REPORT_RECEIPT.json",
            self.candidate / "validation/HUMAN_REVIEW_CLOSURE_RECEIPT.json",
            self.candidate / "validation/PORTABLE_FILE_MANIFEST.json",
        ]
        originals = {path: path.read_bytes() for path in protected_paths}

        def external_checks(report: dict) -> dict[str, dict]:
            return {
                check["check_id"]: check
                for check in report["checks"]
                if check["check_id"].startswith("FACTORY_EXTERNAL_")
            }

        def delete_provenance(report: dict) -> None:
            for check in external_checks(report).values():
                check.pop("authority_input", None)
                check.pop("authority_provenance", None)

        def stale_tip(report: dict) -> None:
            first = next(iter(external_checks(report).values()))
            first["authority_provenance"]["event_store_tip_sha256"] = "f" * 64

        def extra_field(report: dict) -> None:
            first = next(iter(external_checks(report).values()))
            first["authority_provenance"]["unexpected"] = True

        def swap_oracle_provenance(report: dict) -> None:
            checks = external_checks(report)
            source = checks["FACTORY_EXTERNAL_SOURCE_AUTHORITY_ORACLE"]
            history = checks["FACTORY_EXTERNAL_RELEASE_HISTORY_ORACLE"]
            source["authority_input"], history["authority_input"] = (
                history["authority_input"],
                source["authority_input"],
            )
            source["authority_provenance"], history["authority_provenance"] = (
                history["authority_provenance"],
                source["authority_provenance"],
            )

        for name, mutate in (
            ("deleted", delete_provenance),
            ("stale-tip", stale_tip),
            ("extra-field", extra_field),
            ("swapped-oracle-provenance", swap_oracle_provenance),
        ):
            with self.subTest(name=name):
                for path, payload in originals.items():
                    make_path_writable(path)
                    path.write_bytes(payload)
                report = json.loads(report_path.read_text(encoding="utf-8"))
                mutate(report)
                write_json(report_path, report)
                self.refresh_validation_report_receipt()

                self.assertIn(
                    "VALIDATION_REPORT_AUTHORITY_BINDING_INVALID",
                    self.codes(),
                )
                standalone = json.loads(
                    self.run_self_check(policy, trust_anchor).stdout
                )
                self.assertIn(
                    "VALIDATION_REPORT_EXTERNAL_AUTHORITY_MISMATCH",
                    {
                        finding["code"]
                        for finding in standalone["findings"]
                    },
                )

    def test_epoch31_post_publish_and_descendant_validation_pass(self) -> None:
        self.activate_epoch31()
        self.compile()

        without_commit = validate_candidate(
            self.candidate,
            authoritative_sources=self.ir["sources"],
            authoritative_requirement_ir=self.ir,
            authority_provenance=self.authority_provenance(),
        )
        self.assertEqual(without_commit["status"], "FAIL")
        self.assertIn(
            "CANDIDATE_GENERATION_COMMIT_REQUIRED",
            {
                finding["code"]
                for check in without_commit["checks"]
                for finding in check["findings"]
            },
        )

        events, current = self.authority_event_chain()
        immediate = self.epoch31_validation(events, current)
        self.assertEqual(immediate["status"], "PASS", immediate)
        commit_check = next(
            check
            for check in immediate["checks"]
            if check["check_id"] == "CANDIDATE_GENERATION_COMMIT_AUTHORITY"
        )
        self.assertEqual(commit_check["status"], "PASS")

        descendant_events, descendant_current = self.authority_event_chain(
            include_descendant=True
        )
        descendant = self.epoch31_validation(
            descendant_events, descendant_current
        )
        self.assertEqual(descendant["status"], "PASS", descendant)

    def test_epoch31_factory_generation_is_immediately_revalidatable(self) -> None:
        from tests.build_review_fixture import reviewed_document

        self.activate_epoch31()
        runs_root = self.root / "factory-runs"
        store = SQLiteEventStore(
            runs_root / self.ir["program_id"] / "factory.sqlite3"
        )
        service = FactoryService(
            store,
            spec_root=SPEC_ROOT,
            runs_root=runs_root,
        )
        request_number = 0

        def apply(intent: str, state_hash: str | None, payload: dict | None = None) -> dict:
            nonlocal request_number
            request_number += 1
            payload = dict(payload or {})
            if intent == "CREATE":
                payload["build_document_review"] = reviewed_document(self.root)
            return service.handle_chat_turn({
                "request_id": f"REQ-E31-E2E-{request_number:02d}",
                "idempotency_key": f"IDEM-E31-E2E-{request_number:02d}",
                "program_id": self.ir["program_id"],
                "expected_state_hash": state_hash,
                "actor": {
                    "type": "HUMAN_VIA_CODEX_CHAT",
                    "chat_thread_id": "THREAD-E31-E2E",
                    "turn_id": f"TURN-E31-E2E-{request_number:02d}",
                },
                "intent": intent,
                "payload": payload,
            })

        created = apply("CREATE", None, {"requirement_ir": self.ir})
        current = created
        for epoch in range(1, 32):
            readback = apply("PREPARE_READBACK", current["new_state_hash"])
            challenge = apply("REQUEST_FREEZE", readback["new_state_hash"])
            current = apply(
                "REOPEN",
                challenge["new_state_hash"],
                {"reason": f"prepare deterministic requirement epoch {epoch}"},
            )

        readback = apply("PREPARE_READBACK", current["new_state_hash"])
        challenge = apply("REQUEST_FREEZE", readback["new_state_hash"])
        frozen = apply(
            "CONFIRM_FREEZE",
            challenge["new_state_hash"],
            {
                "challenge_id": challenge["approval_challenge"]["challenge_id"],
                "requirement_ir_sha256": challenge["approval_challenge"][
                    "requirement_ir_sha256"
                ],
                "decision": "APPROVE",
                "confirmation_text": challenge["approval_challenge"][
                    "confirmation_token"
                ],
            },
        )
        generated = apply("GENERATE", frozen["new_state_hash"])

        self.assertEqual(
            generated["factory_state"],
            "CANDIDATE_READY_FOR_HUMAN_REVIEW",
        )
        binding = generated["candidate"].get("generation_commit_binding")
        self.assertIsInstance(binding, dict)
        generation_event = store.list_events(self.ir["program_id"])[-1]
        self.assertEqual(
            generation_event["revision"],
            binding["validation_basis"]["event_store_revision"] + 1,
        )
        validation = service.validate_program_candidate(self.ir["program_id"])
        self.assertEqual(validation["status"], "PASS", validation)
        self.assertEqual(service.verify_run(self.ir["program_id"])["status"], "PASS")

    def test_epoch31_generation_commit_adversarial_cases_fail(self) -> None:
        self.activate_epoch31()
        self.compile()
        original_files = {
            path: path.read_bytes()
            for path in (
                self.candidate
                / "validation/START_PACKAGE_VALIDATION_REPORT.json",
                self.candidate
                / "validation/START_PACKAGE_VALIDATION_REPORT_RECEIPT.json",
                self.candidate
                / "validation/HUMAN_REVIEW_CLOSURE_RECEIPT.json",
                self.candidate
                / "validation/PORTABLE_FILE_MANIFEST.json",
            )
        }

        def finding_codes(report: dict) -> set[str]:
            return {
                finding["code"]
                for check in report["checks"]
                for finding in check["findings"]
            }

        events, current = self.authority_event_chain()
        forged_ancestor = deepcopy(events)
        basis_index = self.authority_provenance()["event_store_revision"] - 1
        forged_ancestor[basis_index]["new_state_hash"] = "f" * 64
        for index in range(basis_index, len(forged_ancestor)):
            event = forged_ancestor[index]
            if index == basis_index + 1:
                event["previous_state_hash"] = "f" * 64
            if index > basis_index:
                event["previous_event_hash"] = forged_ancestor[index - 1][
                    "event_hash"
                ]
            event["event_hash"] = json_hash(
                {key: value for key, value in event.items() if key != "event_hash"}
            )
        report = self.epoch31_validation(forged_ancestor, current)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("VALIDATION_BASIS_ANCESTRY_INVALID", finding_codes(report))

        forked_current = {**current, "event_store_tip_sha256": "e" * 64}
        report = self.epoch31_validation(events, forked_current)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("FACTORY_EVENT_CHAIN_INVALID", finding_codes(report))

        replay_events, replay_current = self.authority_event_chain(
            replay_commit=True
        )
        report = self.epoch31_validation(replay_events, replay_current)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("CANDIDATE_GENERATION_COMMIT_REPLAYED", finding_codes(report))

        for path, payload in original_files.items():
            make_path_writable(path)
            path.write_bytes(payload)
        report_path = (
            self.candidate / "validation/START_PACKAGE_VALIDATION_REPORT.json"
        )
        embedded = json.loads(report_path.read_text(encoding="utf-8"))
        external = next(
            check
            for check in embedded["checks"]
            if check["check_id"] == "FACTORY_EXTERNAL_SOURCE_AUTHORITY_ORACLE"
        )
        external["authority_provenance"]["event_store_tip_sha256"] = "d" * 64
        write_json(report_path, embedded)
        self.refresh_validation_report_receipt()
        self.refresh_closure_and_portable_hashes()
        report = self.epoch31_validation(events, current)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("CANDIDATE_GENERATION_COMMIT_INVALID", finding_codes(report))

    def test_unknown_or_mixed_epoch_fails_before_publication(self) -> None:
        self.ir["target"]["control_plane_epoch"] = 1
        with self.assertRaisesRegex(ValueError, "unsupported or mixed"):
            self.compile()
        self.assertFalse(self.candidate.exists())

    def test_epoch24_route_omission_fails_before_publication(self) -> None:
        route = self.ir["target"]["v0_24_human_review_remediation"][
            "producer_validator_route_contract"
        ]
        route.pop("epoch23_requirements_consumed_by_producer")
        with self.assertRaisesRegex(ValueError, "Epoch 24/25/26/28/29 remediation"):
            self.compile()
        self.assertFalse(self.candidate.exists())

    def test_standalone_requires_receiver_side_source_authority_policy(self) -> None:
        self.compile()
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment.pop("HF_SOURCE_AUTHORITY_POLICY_LOCK", None)
        environment.pop("HF_SOURCE_AUTHORITY_TRUST_ANCHOR", None)
        environment.pop("HF_SOURCE_AUTHORITY_TRUST_ANCHOR_SHA256", None)
        result = subprocess.run(
            [sys.executable, "tools/self_check.py"],
            cwd=self.candidate,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertIn(
            "SOURCE_AUTHORITY_POLICY_LOCK_REQUIRED",
            {finding["code"] for finding in report["findings"]},
        )
        self.assertNotIn(
            "V2_9_EPOCH24_GATE_ADVERSARIAL_CASES_INVALID",
            {finding["code"] for finding in report["findings"]},
        )

    def test_missing_epoch2_module_is_rejected_by_both_oracles(self) -> None:
        self.compile()
        missing = self.candidate / EPOCH2_ARTIFACTS[17]
        make_path_writable(missing)
        missing.unlink()
        self.refresh_closure_and_portable_hashes()
        self.assertIn("V2_9_EPOCH2_ARTIFACT_MISSING", self.codes())
        report = json.loads(self.run_self_check().stdout)
        self.assertIn(
            "V2_9_EPOCH2_ARTIFACT_MISSING",
            {item["code"] for item in report["findings"]},
        )

    def test_hash_consistent_correction_mapping_tamper_is_rejected(self) -> None:
        self.compile()
        matrix_path = self.candidate / EPOCH2_ARTIFACTS[6]
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        row = matrix["rows"][0]
        row["maps_to"] = ["ATOM-002"]
        coverage = json.loads(
            (
                self.candidate / "canonical_sources/ATOM_COVERAGE_MATRIX.json"
            ).read_text(encoding="utf-8")
        )
        edge = next(item for item in coverage["coverage"] if item["atom_id"] == "ATOM-002")
        row["mapped_atom_coverage"] = [
            {
                "atom_id": "ATOM-002",
                "workpack_ids": list(edge.get("workpack_ids") or []),
                "stage_ids": list(edge.get("stage_ids") or []),
                "release_step_ids": list(edge.get("release_step_ids") or []),
                "owner_project_ids": list(edge.get("owner_project_ids") or []),
                "coverage_status": edge.get("status"),
            }
        ]
        row["row_sha256"] = json_hash(without_hash(row, "row_sha256"))
        matrix["matrix_sha256"] = json_hash(without_hash(matrix, "matrix_sha256"))
        write_json(matrix_path, matrix)
        manifest_path = self.candidate / EPOCH2_ARTIFACTS[0]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["correction_coverage_sha256"] = hashlib.sha256(
            matrix_path.read_bytes()
        ).hexdigest()
        manifest["manifest_sha256"] = json_hash(
            without_hash(manifest, "manifest_sha256")
        )
        write_json(manifest_path, manifest)
        self.refresh_closure_and_portable_hashes()
        self.assertIn("V2_9_EPOCH2_CORRECTION_COVERAGE_INVALID", self.codes())
        report = json.loads(self.run_self_check().stdout)
        self.assertIn(
            "V2_9_EPOCH2_CORRECTION_COVERAGE_INVALID",
            {item["code"] for item in report["findings"]},
        )

    def test_epoch1_compatibility_cannot_regain_active_authority(self) -> None:
        self.compile()
        for relative in (
            "ENGINEERING_PROJECT_DAG.json",
            "THREE_PROJECT_PROGRAM_MANIFEST.json",
        ):
            path = self.candidate / relative
            document = json.loads(path.read_text(encoding="utf-8"))
            document["authority_role"] = "ACTIVE_AUTHORITY"
            write_json(path, document)
        self.refresh_closure_and_portable_hashes()
        self.assertIn("V2_9_EPOCH1_AUTHORITY_REACTIVATED", self.codes())
        report = json.loads(self.run_self_check().stdout)
        self.assertIn(
            "V2_9_EPOCH1_AUTHORITY_REACTIVATED",
            {item["code"] for item in report["findings"]},
        )

    def test_hash_consistent_closure_runtime_weakening_is_rejected(self) -> None:
        self.compile()
        runtime_path = self.candidate / EPOCH2_ARTIFACTS[20]
        source = runtime_path.read_text(encoding="utf-8")
        source = source.replace(
            "if type(authority_adapter) is not SQLiteEventStoreAuthorityAdapter:",
            "if False:",
        )
        make_path_writable(runtime_path)
        runtime_path.write_text(source, encoding="utf-8")
        closure_path = self.candidate / EPOCH2_ARTIFACTS[4]
        closure = json.loads(closure_path.read_text(encoding="utf-8"))
        closure["implementation_sha256"] = hashlib.sha256(
            runtime_path.read_bytes()
        ).hexdigest()
        closure["graph_sha256"] = json_hash(without_hash(closure, "graph_sha256"))
        write_json(closure_path, closure)
        self.rebind_epoch2_manifest()
        self.refresh_closure_and_portable_hashes()
        self.assertIn("V2_9_EPOCH2_SOURCE_INVALID", self.codes())
        report = json.loads(self.run_self_check().stdout)
        self.assertIn(
            "V2_9_EPOCH2_RUNTIME_FIXTURE_INVALID",
            {item["code"] for item in report["findings"]},
        )

    def test_hash_consistent_authority_adapter_weakening_is_rejected(self) -> None:
        self.compile()
        adapter_path = self.candidate / EPOCH2_ARTIFACTS[24]
        source = adapter_path.read_text(encoding="utf-8")
        weakened = source.replace(
            """Ed25519PublicKey.from_public_bytes(public_bytes).verify(
            signature_bytes,
            _canonical_json(signed).encode("utf-8"),
        )""",
            """# adversarial weakening: accept any attacker signature
        None""",
        )
        self.assertNotEqual(source, weakened)
        make_path_writable(adapter_path)
        adapter_path.write_text(weakened, encoding="utf-8")
        adapter_sha = hashlib.sha256(adapter_path.read_bytes()).hexdigest()

        adapter_contract_path = self.candidate / EPOCH2_ARTIFACTS[22]
        adapter_contract = json.loads(
            adapter_contract_path.read_text(encoding="utf-8")
        )
        adapter_contract["implementation_sha256"] = adapter_sha
        adapter_contract["contract_sha256"] = json_hash(
            without_hash(adapter_contract, "contract_sha256")
        )
        write_json(adapter_contract_path, adapter_contract)

        for index, hash_field in ((1, "contract_sha256"), (4, "graph_sha256")):
            path = self.candidate / EPOCH2_ARTIFACTS[index]
            document = json.loads(path.read_text(encoding="utf-8"))
            document["authority_adapter_implementation_sha256"] = adapter_sha
            document["authority_adapter_contract_sha256"] = adapter_contract[
                "contract_sha256"
            ]
            document[hash_field] = json_hash(without_hash(document, hash_field))
            write_json(path, document)

        self.rebind_epoch2_manifest()
        self.refresh_closure_and_portable_hashes()
        self.assertIn("V2_9_EPOCH2_SOURCE_INVALID", self.codes())
        report = json.loads(self.run_self_check().stdout)
        self.assertIn(
            "V2_9_EPOCH18_PRODUCTION_ADVERSARIAL_CASES_INVALID",
            {item["code"] for item in report["findings"]},
        )

    def test_hash_consistent_output_schema_weakening_is_rejected(self) -> None:
        self.compile()
        schema_path = self.candidate / EPOCH2_ARTIFACTS[12]
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema["additionalProperties"] = True
        write_json(schema_path, schema)
        closure_path = self.candidate / EPOCH2_ARTIFACTS[4]
        closure = json.loads(closure_path.read_text(encoding="utf-8"))
        closure["closure_receipt_schema_sha256"] = hashlib.sha256(
            schema_path.read_bytes()
        ).hexdigest()
        closure["graph_sha256"] = json_hash(without_hash(closure, "graph_sha256"))
        write_json(closure_path, closure)
        self.rebind_epoch2_manifest()
        self.refresh_closure_and_portable_hashes()
        self.assertIn("V2_9_EPOCH2_OUTPUT_SCHEMA_INVALID", self.codes())
        report = json.loads(self.run_self_check().stdout)
        self.assertIn(
            "V2_9_EPOCH2_OUTPUT_SCHEMA_INVALID",
            {item["code"] for item in report["findings"]},
        )


class Epoch2RuntimePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.candidate_root = Path(self.temporary.name) / "candidate"
        self.candidate_root.mkdir()
        self.authority_private_key = Ed25519PrivateKey.generate()
        public_bytes = self.authority_private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        trust_root = {
            "schema_version": "2.9",
            "trust_root_id": "TEST-TRUST-ROOT",
            "algorithm": "ED25519",
            "public_key_base64": base64.b64encode(public_bytes).decode("ascii"),
            "public_key_sha256": hashlib.sha256(public_bytes).hexdigest(),
            "purpose": "VERIFY_EVENT_STORE_BINDING_AND_RELEASE_COMMIT_AUTHORIZATION",
            "private_key_packaged": False,
            "creates_authority": False,
            "status": "PINNED_VERIFICATION_ROOT_NOT_AUTHORIZATION",
        }
        trust_root["trust_root_sha256"] = json_hash(trust_root)
        self.receiver_trust_anchor = trust_root
        self.trust_root = trust_root
        contract = {
            "schema_version": "2.9",
            "contract_id": "TEST-AUTHORITY-ADAPTER-CONTRACT",
        }
        contract["contract_sha256"] = json_hash(contract)
        write_json(
            self.candidate_root / "EVENT_STORE_AUTHORITY_ADAPTER_CONTRACT.json",
            contract,
        )
        self.adapter_contract_sha256 = contract["contract_sha256"]
        self.root_patch = mock.patch.object(
            authority_adapter_module,
            "_candidate_root",
            return_value=self.candidate_root,
        )
        self.root_patch.start()
        self.database = Path(self.temporary.name) / "control-events.sqlite3"
        self.program_id = "PROGRAM-EPOCH18-TEST"
        self.database_identity = "9" * 64
        self.semantic_contract = self.semantic("A")
        self.risk_contract = self.risk("LOW")
        self.semantic_identity = json_hash({
            "identity_id": "SEMANTIC_CONTRACT_IDENTITY",
            "normative_fields": self.semantic_contract,
        })
        self.risk_identity = json_hash({
            "identity_id": "AUTHORIZATION_RISK_IDENTITY",
            "normative_fields": self.risk_contract,
        })
        self.binding = {
            "authority_scope": "PROGRAM",
            "instance_id": "INSTANCE-1",
            "requirement_epoch": 18,
            "semantic_contract_identity_sha256": self.semantic_identity,
            "authorization_risk_identity_sha256": self.risk_identity,
        }
        artifact_root = Path(self.temporary.name).resolve() / "receiver-artifacts"
        artifact_root.mkdir()
        self.artifact_paths = {
            "candidate_content_sha256": artifact_root / "candidate.bundle",
            "requirement_ir_sha256": artifact_root / "requirement-ir.json",
            "executor_release_sha256": artifact_root / "executor.bin",
            "human_gate_receipt_sha256": artifact_root / "human-gate.json",
        }
        for index, path in enumerate(self.artifact_paths.values(), 1):
            path.write_bytes(f"receiver-artifact-{index}".encode("utf-8"))
        self.artifact_resolver = ReleaseArtifactBytesResolver(self.artifact_paths)
        self.release_artifacts = self.artifact_resolver.resolve_hashes()
        self.store = ControlEventStore(self.database)
        entries = [
            {
                "event_type": "CONTROL_EVENT_STORE_ACTIVATED",
                "payload": {
                    "database_identity_sha256": self.database_identity,
                    "logical_database_ref": LOGICAL_DATABASE_REF,
                },
            },
            {
                "event_type": "CURRENT_STATE_COMMITTED",
                "payload": {
                    **self.binding,
                    "current_state_sha256": "c" * 64,
                    **self.release_artifacts,
                },
            },
            *[
                {
                    "event_type": "CLOSURE_RECEIPT_ISSUED",
                    "payload": {
                        "receipt_kind": kind,
                        "receipt_id": (
                            f"RECEIPT-{kind}"
                            if kind != "COMPATIBILITY_LINKAGE"
                            else "RECEIPT-LINKAGE"
                        ),
                        "issuer_control_domain_id": f"DOMAIN-{kind}",
                        **self.binding,
                    },
                }
                for kind in (
                    "PRODUCT", "SAFETY", "RELEASE", "COMPATIBILITY_LINKAGE"
                )
            ],
        ]
        self.store.append_batch(
            self.program_id,
            entries,
            idempotency_key="BOOTSTRAP-EPOCH18",
            created_at="2026-08-06T00:00:00Z",
            expected_previous_event_hash=None,
        )
        self.adapter = self.make_adapter()
        self.context = self.adapter.read_release_context()

    def tearDown(self) -> None:
        self.root_patch.stop()
        self.temporary.cleanup()

    @staticmethod
    def semantic(contract_id: str) -> dict:
        return {
            "contract_id": contract_id,
            "contract_version": "1",
            "normative_behavior_sha256": "1" * 64,
            "input_schema_sha256": "2" * 64,
            "output_schema_sha256": "3" * 64,
            "invariants_sha256": "4" * 64,
        }

    @staticmethod
    def implementation(release_id: str) -> dict:
        return {
            "release_id": release_id,
            "exact_executor_bytes_sha256": (
                "5" if release_id == "1" else "6"
            ) * 64,
            "artifact_bytes_sha256": "7" * 64,
            "sbom_sha256": "8" * 64,
            "provenance_sha256": "9" * 64,
            "toolchain_sha256": "a" * 64,
        }

    @staticmethod
    def risk(profile: str) -> dict:
        return {
            "risk_profile_id": profile,
            "scope_sha256": "b" * 64,
            "permissions_sha256": "c" * 64,
            "write_roots_sha256": "d" * 64,
            "network_policy_sha256": "e" * 64,
            "secret_access_policy_sha256": "f" * 64,
            "external_effect_class": "READ_ONLY",
            "budget_sha256": "0" * 64,
            "stop_gates_sha256": "1" * 64,
        }

    def make_adapter(self, **updates: object) -> SQLiteEventStoreAuthorityAdapter:
        body = {
            "schema_version": "2.9",
            "adapter_id": "V29_SQLITE_EVENT_STORE_AUTHORITY_ADAPTER_V1",
            "program_id": self.program_id,
            "authority_scope": "PROGRAM",
            "instance_id": "INSTANCE-1",
            "requirement_epoch": 18,
            "database_identity_sha256": self.database_identity,
            "logical_database_ref": LOGICAL_DATABASE_REF,
            "adapter_implementation_sha256": hashlib.sha256(
                Path(authority_adapter_module.__file__).read_bytes()
            ).hexdigest(),
            "adapter_entrypoint_sha256": adapter_entrypoint_sha256(),
            "adapter_contract_sha256": self.adapter_contract_sha256,
        }
        body.update(updates)
        authorization = {
            "schema_version": "2.9",
            "receipt_kind": "AUTHORITY_BINDING_RECEIPT",
            "receipt_id": "TEST-BINDING-AUTHORITY",
            "issuer_role": "CONTROL_PLANE_AUTHORITY",
            "trust_root_id": self.trust_root["trust_root_id"],
            "issued_at": "2026-08-01T00:00:00Z",
            "not_before": "2026-08-01T00:00:00Z",
            "expires_at": "2099-08-01T00:00:00Z",
            "revoked": False,
            "one_shot": False,
            "authorization_purpose": "EVENT_STORE_ADAPTER_BINDING",
            **body,
        }
        authorization.pop("schema_version")
        authorization["schema_version"] = "2.9"
        authorization.pop("adapter_id")
        authorization["signature_base64"] = base64.b64encode(
            self.authority_private_key.sign(
                json.dumps(
                    authorization,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            )
        ).decode("ascii")
        body["authority_binding_receipt"] = authorization
        return SQLiteEventStoreAuthorityAdapter(
            self.database,
            build_adapter_binding(
                body,
                receiver_trust_anchor=self.receiver_trust_anchor,
            ),
            receiver_trust_anchor=self.receiver_trust_anchor,
            artifact_resolver=self.artifact_resolver,
        )

    def append(self, event_type: str, payload: dict, key: str) -> None:
        tip = self.store.verify_stream(self.program_id)["last_event_hash"]
        self.store.append_batch(
            self.program_id,
            [{"event_type": event_type, "payload": payload}],
            idempotency_key=key,
            created_at="2026-08-06T00:01:00Z",
            expected_previous_event_hash=tip,
        )

    def sign_authority(self, body: dict) -> dict:
        signed = deepcopy(body)
        signed["signature_base64"] = base64.b64encode(
            self.authority_private_key.sign(
                json.dumps(
                    body,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            )
        ).decode("ascii")
        return signed

    def release_commit_authorization(
        self,
        proposal: dict,
        *,
        context: Mapping[str, object] | None = None,
    ) -> dict:
        authoritative = context or self.context
        return self.sign_authority({
            "schema_version": "2.9",
            "authorization_id": "AUTH-RELEASE-1",
            "authorization_purpose": "RUNTIME_RELEASE_COMMIT",
            "issuer_role": "CONTROL_PLANE_AUTHORITY",
            "trust_root_id": self.trust_root["trust_root_id"],
            "issued_at": "2026-08-01T00:00:00Z",
            "not_before": "2026-08-01T00:00:00Z",
            "expires_at": "2099-08-01T00:00:00Z",
            "revoked": False,
            "one_shot": True,
            "program_id": self.program_id,
            **self.binding,
            **{
                field: authoritative[field]
                for field in self.release_artifacts
            },
            "expected_control_state_sha256": authoritative["current_state_sha256"],
            "authorized_event_store_tip_sha256": proposal[
                "expected_event_store_tip_sha256"
            ],
            "proposal_decision_sha256": proposal["decision_sha256"],
            "lease_id": "LEASE-RELEASE-1",
            "lease_expires_at": "2099-08-01T00:00:00Z",
            "fencing_token": 1,
            "idempotency_key": "IDEM-RELEASE-1",
            "status": "AUTHORIZED",
        })

    def receipt(
        self,
        kind: str,
        receipt_id: str,
        *,
        context: dict | None = None,
        **updates: object,
    ) -> dict:
        trusted = context or self.context
        body = {
            "schema_version": "2.9",
            **({"lane_id": kind} if kind != "COMPATIBILITY_LINKAGE" else {}),
            "status": "CLOSED" if kind != "COMPATIBILITY_LINKAGE" else "PASS",
            **{field: trusted[field] for field in self.binding},
            "receipt_id": receipt_id,
            **trusted["authorized_issuers"][kind],
            "release_context_sha256": trusted["release_context_sha256"],
            "creates_authority": False,
        }
        body.update(updates)
        body["anti_replay_token"] = derive_anti_replay_token(body)
        return seal_receipt(body)

    def lane_receipts(self) -> list[dict]:
        return [
            self.receipt(lane, f"RECEIPT-{lane}")
            for lane in ("PRODUCT", "SAFETY", "RELEASE")
        ]

    def linkage_receipt(self, **updates: object) -> dict:
        return self.receipt("COMPATIBILITY_LINKAGE", "RECEIPT-LINKAGE", **updates)

    def test_recovery_complexity_closure_and_projection_semantics(self) -> None:
        recovery = {
            "command_receipt_status": "VALID",
            "effect_certainty": "NO_EFFECT",
            "result_receipt_status": "MISSING",
            "event_commit_state": "NOT_COMMITTED",
            "grant_state": "ACTIVE",
            "checkpoint_status": "VALID",
            "retry_budget_remaining": 1,
        }
        self.assertEqual(decide_recovery(recovery)["decision"], "RETRY_EXECUTOR")
        complexity = {
            "active_bespoke_paths_before": 2,
            "active_bespoke_paths_after": 1,
            "new_node_specific_authorized_paths": 0,
            "new_fixed_attempt_or_receipt_ids_in_core": 0,
            "generic_path_added": True,
            "retired_authoritative_paths": 1,
            "human_gate_added": False,
            "human_gate_has_risk_delta_or_external_boundary": False,
            "control_fault_fingerprint_occurrences": 2,
        }
        assessment = evaluate_complexity(complexity)
        self.assertEqual(assessment["decision"], "ARCHITECTURE_REVIEW_REQUIRED")
        self.assertEqual(
            set(assessment["outputs"]),
            {
                "complexity_baseline",
                "complexity_delta",
                "retirement_manifest",
                "human_cost_result",
                "circuit_breaker_decision_receipt",
            },
        )
        self.assertRegex(assessment["assessment_sha256"], r"^[0-9a-f]{64}$")
        lanes = self.lane_receipts()
        self.assertEqual(
            evaluate_final_release(
                lanes,
                compatibility_linkage_receipt=self.linkage_receipt(),
                authority_adapter=self.adapter,
            )["decision"],
            "RELEASE_ELIGIBILITY_PROPOSAL_NOT_AUTHORITY",
        )
        event = {
            "authority_scope": "PROGRAM",
            "instance_id": "P-1",
            "fact_key": "status",
            "fact_value": "READY",
            "revision": 1,
            "event_sha256": "a" * 64,
            "retention_class": "ACTIVE_BASELINE",
        }
        with self.assertRaises(ProjectionConflictError):
            rebuild_projection(
                [event, {**event, "fact_value": "BLOCKED", "event_sha256": "b" * 64}]
            )

    def test_closure_lane_counterexamples_fail_closed(self) -> None:
        lanes = self.lane_receipts()
        linkage = self.linkage_receipt()
        counterexamples: list[list[dict]] = [lanes[:-1]]

        malformed = deepcopy(lanes)
        malformed[0]["receipt_sha256"] = "not-a-hash"
        counterexamples.append(malformed)

        hash_mismatch = deepcopy(lanes)
        hash_mismatch[0]["instance_id"] = "TAMPERED"
        counterexamples.append(hash_mismatch)

        extra_field = deepcopy(lanes)
        extra_field[0]["unexpected"] = True
        counterexamples.append(extra_field)

        for field, value in (
            ("authority_scope", "OTHER"),
            ("instance_id", "INSTANCE-2"),
            ("requirement_epoch", 15),
            ("semantic_contract_identity_sha256", "c" * 64),
            ("authorization_risk_identity_sha256", "d" * 64),
        ):
            mixed = deepcopy(lanes)
            body = without_hash(mixed[1], "receipt_sha256")
            body[field] = value
            mixed[1] = seal_receipt(body)
            counterexamples.append(mixed)

        duplicate = deepcopy(lanes)
        duplicate[2] = deepcopy(duplicate[1])
        counterexamples.append(duplicate)

        for counterexample in counterexamples:
            with self.assertRaises(ClosureLaneError):
                evaluate_final_release(
                    counterexample,
                    compatibility_linkage_receipt=linkage,
                    authority_adapter=self.adapter,
                )

        for updates in (
            {"instance_id": "INSTANCE-2"},
            {"requirement_epoch": 15},
            {"semantic_contract_identity_sha256": "c" * 64},
            {"authorization_risk_identity_sha256": "d" * 64},
        ):
            with self.assertRaises(ClosureLaneError):
                evaluate_final_release(
                    lanes,
                    compatibility_linkage_receipt=self.linkage_receipt(**updates),
                    authority_adapter=self.adapter,
                )

    def test_epoch18_context_adapter_and_precommit_cases_fail_closed(self) -> None:
        lanes = self.lane_receipts()
        linkage = self.linkage_receipt()
        proposal = evaluate_final_release(
            lanes,
            compatibility_linkage_receipt=linkage,
            authority_adapter=self.adapter,
        )

        class FakeAdapter:
            def read_release_context(self) -> dict:
                forged = deepcopy(self.context)
                forged["current_state_sha256"] = "0" * 64
                forged["release_context_sha256"] = json_hash(
                    without_hash(forged, "release_context_sha256")
                )
                return forged

        fake = FakeAdapter()
        fake.context = self.context
        with self.assertRaises(ClosureLaneError):
            evaluate_final_release(
                lanes,
                compatibility_linkage_receipt=linkage,
                authority_adapter=fake,  # type: ignore[arg-type]
            )
        with self.assertRaises(AuthorityAdapterError):
            self.make_adapter(adapter_implementation_sha256="0" * 64)
        with self.assertRaises(AuthorityAdapterError):
            self.make_adapter(database_identity_sha256="0" * 64)

        forged_body = dict(self.adapter._binding)
        forged_body.pop("binding_sha256")
        forged_receipt = dict(forged_body["authority_binding_receipt"])
        forged_receipt.pop("signature_base64")
        attacker = Ed25519PrivateKey.generate()
        forged_receipt["signature_base64"] = base64.b64encode(
            attacker.sign(
                json.dumps(
                    forged_receipt,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            )
        ).decode("ascii")
        forged_body["authority_binding_receipt"] = forged_receipt
        with self.assertRaises(AuthorityAdapterError):
            build_adapter_binding(
                forged_body,
                receiver_trust_anchor=self.receiver_trust_anchor,
            )

        attacker_public = attacker.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        candidate_local_anchor = {
            **self.receiver_trust_anchor,
            "trust_root_id": "ATTACKER-CANDIDATE-LOCAL-ROOT",
            "public_key_base64": base64.b64encode(attacker_public).decode("ascii"),
            "public_key_sha256": hashlib.sha256(attacker_public).hexdigest(),
        }
        candidate_local_anchor["trust_root_sha256"] = json_hash(
            without_hash(candidate_local_anchor, "trust_root_sha256")
        )
        write_json(
            self.candidate_root / "AUTHORITY_TRUST_ROOT.json",
            candidate_local_anchor,
        )
        with self.assertRaises(AuthorityAdapterError):
            build_adapter_binding(
                forged_body,
                receiver_trust_anchor=self.receiver_trust_anchor,
            )

        class FakeResolver(ReleaseArtifactBytesResolver):
            def resolve_hashes(self) -> dict[str, str]:
                return dict(self.release_artifacts)

        fake_resolver = object.__new__(FakeResolver)
        fake_resolver.release_artifacts = self.release_artifacts
        body = dict(self.adapter._binding)
        body.pop("binding_sha256")
        with self.assertRaises(AuthorityAdapterError):
            SQLiteEventStoreAuthorityAdapter(
                self.database,
                self.adapter._binding,
                receiver_trust_anchor=self.receiver_trust_anchor,
                artifact_resolver=fake_resolver,
            )

        self.append("AUDIT_EVENT", {"status": "NO_AUTHORITY"}, "TIP-CHANGED")
        with self.assertRaises(AuthorityAdapterError):
            self.adapter.validate_precommit(proposal)

    def test_signed_release_authorization_is_consumed_atomically_and_not_replayed(self) -> None:
        proposal = evaluate_final_release(
            self.lane_receipts(),
            compatibility_linkage_receipt=self.linkage_receipt(),
            authority_adapter=self.adapter,
        )
        self.append(
            "RELEASE_COMMIT_AUTHORIZED",
            self.release_commit_authorization(proposal),
            "SIGNED-RELEASE-AUTHORIZATION",
        )
        appended = self.adapter.atomic_commit_release_ready(
            proposal,
            created_at="2026-08-06T00:02:00Z",
        )
        self.assertEqual(
            [event["event_type"] for event in appended],
            [
                "RELEASE_COMMIT_AUTHORIZATION_CONSUMED",
                "CLOSURE_RECEIPT_SET_CONSUMED",
                "RELEASE_READY_COMMITTED",
            ],
        )
        with self.assertRaises(AuthorityAdapterError):
            self.adapter.atomic_commit_release_ready(
                proposal,
                created_at="2026-08-06T00:03:00Z",
            )

    def test_signed_synchronized_wrong_artifact_hashes_are_rejected_by_bytes(self) -> None:
        wrong_hashes = {
            field: "f" * 64 for field in self.release_artifacts
        }
        self.append(
            "CURRENT_STATE_COMMITTED",
            {
                **self.binding,
                "current_state_sha256": "d" * 64,
                **wrong_hashes,
            },
            "SYNCHRONIZED-WRONG-ARTIFACT-STATE",
        )
        context = self.adapter.read_release_context()
        lanes = [
            self.receipt(lane, f"RECEIPT-{lane}", context=context)
            for lane in ("PRODUCT", "SAFETY", "RELEASE")
        ]
        proposal = evaluate_final_release(
            lanes,
            compatibility_linkage_receipt=self.receipt(
                "COMPATIBILITY_LINKAGE", "RECEIPT-LINKAGE", context=context
            ),
            authority_adapter=self.adapter,
        )
        authorization = self.release_commit_authorization(
            proposal,
            context=context,
        )
        self.append(
            "RELEASE_COMMIT_AUTHORIZED",
            authorization,
            "SIGNED-SYNCHRONIZED-WRONG-ARTIFACT-AUTHORIZATION",
        )
        with self.assertRaisesRegex(
            AuthorityAdapterError,
            "actual release artifact bytes",
        ):
            self.adapter.atomic_commit_release_ready(
                proposal,
                created_at="2026-08-06T00:02:00Z",
            )

    def test_artifact_resolver_rejects_receiver_path_symlink(self) -> None:
        link = Path(self.temporary.name).resolve() / "candidate-link"
        link.symlink_to(self.artifact_paths["candidate_content_sha256"])
        paths = dict(self.artifact_paths)
        paths["candidate_content_sha256"] = link
        with self.assertRaisesRegex(AuthorityAdapterError, "symlink"):
            ReleaseArtifactBytesResolver(paths)

    def test_self_asserted_or_attacker_signed_release_authorization_is_rejected(self) -> None:
        proposal = evaluate_final_release(
            self.lane_receipts(),
            compatibility_linkage_receipt=self.linkage_receipt(),
            authority_adapter=self.adapter,
        )
        forged = self.release_commit_authorization(proposal)
        forged.pop("signature_base64")
        attacker = Ed25519PrivateKey.generate()
        forged["signature_base64"] = base64.b64encode(
            attacker.sign(
                json.dumps(
                    forged,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            )
        ).decode("ascii")
        self.append(
            "RELEASE_COMMIT_AUTHORIZED",
            forged,
            "FORGED-RELEASE-AUTHORIZATION",
        )
        with self.assertRaises(AuthorityAdapterError):
            self.adapter.atomic_commit_release_ready(
                proposal,
                created_at="2026-08-06T00:02:00Z",
            )

    def test_valid_signature_with_wrong_authoritative_artifact_hash_is_rejected(self) -> None:
        for index, field in enumerate(self.release_artifacts, 1):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                database = Path(temporary) / "control-events.sqlite3"
                store = ControlEventStore(database)
                entries = [
                    {
                        "event_type": "CONTROL_EVENT_STORE_ACTIVATED",
                        "payload": {
                            "database_identity_sha256": self.database_identity,
                            "logical_database_ref": LOGICAL_DATABASE_REF,
                        },
                    },
                    {
                        "event_type": "CURRENT_STATE_COMMITTED",
                        "payload": {
                            **self.binding,
                            "current_state_sha256": "c" * 64,
                            **self.release_artifacts,
                        },
                    },
                    *[
                        {
                            "event_type": "CLOSURE_RECEIPT_ISSUED",
                            "payload": {
                                "receipt_kind": kind,
                                "receipt_id": (
                                    f"RECEIPT-{kind}"
                                    if kind != "COMPATIBILITY_LINKAGE"
                                    else "RECEIPT-LINKAGE"
                                ),
                                "issuer_control_domain_id": f"DOMAIN-{kind}",
                                **self.binding,
                            },
                        }
                        for kind in (
                            "PRODUCT", "SAFETY", "RELEASE", "COMPATIBILITY_LINKAGE"
                        )
                    ],
                ]
                store.append_batch(
                    self.program_id,
                    entries,
                    idempotency_key=f"BOOTSTRAP-WRONG-HASH-{index}",
                    created_at="2026-08-06T00:00:00Z",
                    expected_previous_event_hash=None,
                )
                original_database = self.database
                self.database = database
                try:
                    adapter = self.make_adapter()
                finally:
                    self.database = original_database
                context = adapter.read_release_context()
                lanes = [
                    self.receipt(lane, f"RECEIPT-{lane}", context=context)
                    for lane in ("PRODUCT", "SAFETY", "RELEASE")
                ]
                linkage = self.receipt(
                    "COMPATIBILITY_LINKAGE",
                    "RECEIPT-LINKAGE",
                    context=context,
                )
                proposal = evaluate_final_release(
                    lanes,
                    compatibility_linkage_receipt=linkage,
                    authority_adapter=adapter,
                )
                authorization = self.release_commit_authorization(proposal)
                authorization.pop("signature_base64")
                authorization[field] = "f" * 64
                authorization = self.sign_authority(authorization)
                tip = store.verify_stream(self.program_id)["last_event_hash"]
                store.append_batch(
                    self.program_id,
                    [{
                        "event_type": "RELEASE_COMMIT_AUTHORIZED",
                        "payload": authorization,
                    }],
                    idempotency_key=f"WRONG-HASH-{index}",
                    created_at="2026-08-06T00:01:00Z",
                    expected_previous_event_hash=tip,
                )
                with self.assertRaises(AuthorityAdapterError):
                    adapter.atomic_commit_release_ready(
                        proposal,
                        created_at="2026-08-06T00:02:00Z",
                    )

    def test_receipt_consumption_after_evaluation_fails_closed(self) -> None:
        proposal = evaluate_final_release(
            self.lane_receipts(),
            compatibility_linkage_receipt=self.linkage_receipt(),
            authority_adapter=self.adapter,
        )
        self.append(
            "CLOSURE_RECEIPT_SET_CONSUMED",
            {
                "receipt_ids": ["RECEIPT-PRODUCT"],
                "decision_sha256": proposal["decision_sha256"],
            },
            "CONSUMED-AFTER-EVALUATION",
        )
        with self.assertRaises(AuthorityAdapterError):
            self.adapter.validate_precommit(proposal)

    def test_identity_derivation_and_rebinding_policy(self) -> None:
        base = derive_identity_bundle(
            semantic_contract=self.semantic_contract,
            implementation_release=self.implementation("1"),
            authorization_risk=self.risk_contract,
            authority_adapter=self.adapter,
        )
        implementation_change = derive_identity_bundle(
            semantic_contract=self.semantic_contract,
            implementation_release=self.implementation("2"),
            authorization_risk=self.risk_contract,
            authority_adapter=self.adapter,
        )
        semantic_change = dict(implementation_change)
        semantic_change["semantic_contract_identity_sha256"] = "e" * 64
        semantic_change["identity_bundle_sha256"] = json_hash(
            without_hash(semantic_change, "identity_bundle_sha256")
        )
        risk_change = dict(implementation_change)
        risk_change["authorization_risk_identity_sha256"] = "d" * 64
        risk_change["identity_bundle_sha256"] = json_hash(
            without_hash(risk_change, "identity_bundle_sha256")
        )
        self.assertEqual(
            classify_identity_change(base, implementation_change)["change_class"],
            "MACHINE_GRANT_REBIND_REQUIRED",
        )
        self.assertEqual(
            classify_identity_change(implementation_change, semantic_change)[
                "change_class"
            ],
            "HUMAN_REAUTHORIZATION_REQUIRED",
        )
        self.assertEqual(
            classify_identity_change(implementation_change, risk_change)[
                "change_class"
            ],
            "HUMAN_REAUTHORIZATION_REQUIRED",
        )
        binding = build_machine_grant_binding(
            implementation_change,
            authority_adapter=self.adapter,
            exact_executor_release_sha256="2" * 64,
            exact_artifact_release_sha256="3" * 64,
        )
        self.assertFalse(binding["machine_grant_issued"])
        self.assertFalse(binding["creates_authority"])
        with self.assertRaises(IdentityDerivationError):
            derive_identity_bundle(
                semantic_contract=self.semantic("A"),
                implementation_release={},
                authorization_risk=self.risk_contract,
                authority_adapter=self.adapter,
            )
        self.append(
            "CURRENT_STATE_COMMITTED",
            {
                **self.binding,
                "current_state_sha256": "4" * 64,
                **self.release_artifacts,
            },
            "ADVANCE-CURRENT-STATE",
        )
        with self.assertRaises(IdentityDerivationError):
            build_machine_grant_binding(
                implementation_change,
                authority_adapter=self.adapter,
                exact_executor_release_sha256="2" * 64,
                exact_artifact_release_sha256="3" * 64,
            )
        with self.assertRaises(TypeError):
            build_machine_grant_binding(
                implementation_change,
                authoritative_current_state=self.context,  # type: ignore[call-arg]
                exact_executor_release_sha256="2" * 64,
                exact_artifact_release_sha256="3" * 64,
            )


if __name__ == "__main__":
    unittest.main()
