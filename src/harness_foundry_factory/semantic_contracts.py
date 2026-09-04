"""Explicit Requirement Atom production contracts for v2.9 candidates."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Mapping

from .constants import (
    DAG_WORKPACK_BINDINGS,
    DAG_WORKPACK_SEQUENCE_BINDINGS,
    PROJECT_WORKPACK_CONTRACTS,
    RELEASE_STEP_ORDER,
    RELEASE_WORKPACK_BINDINGS,
)


EXPLICIT_PRODUCTION_MODE = "EXPLICIT_ARTIFACT_OBLIGATIONS"
DETERMINISTIC_DERIVATION_POLICY = (
    "DETERMINISTIC_FROM_FROZEN_ATOMS_COVERAGE_AND_SCHEMA_CATALOG"
)
ARTIFACT_MANIFEST_REF = (
    "harness-resource://candidate/canonical_sources/"
    "ARTIFACT_OBLIGATION_MANIFEST.json"
)
ORACLE_EVALUATOR_REGISTRY_REF = (
    "harness-resource://candidate/validation/ORACLE_EVALUATOR_REGISTRY.json"
)
PUBLIC_SKILL_JOB_INTERFACE_REF = (
    "harness-resource://candidate/validation/PUBLIC_SKILL_JOB_INTERFACE.json"
)
CASE_EXECUTION_RESULT_ROOT_REF = (
    "harness-resource://execution/evidence/cases"
)
CASE_EVIDENCE_WRITER_WORKPACK_ID = "LAB-CERTIFICATION"
TERMINAL_TIMING_EVIDENCE_TYPES = frozenset(
    {"LOCAL_AUDIO_ALIGNMENT_MOTION_SYNC_RECEIPTS"}
)
JOB_SCOPED_ARTIFACT_KINDS = frozenset(
    {
        "SOURCE_FREEZE_RECEIPT",
        "FUNCTION_SCENARIO_EFFECT_MATRIX",
        "NARRATION_SCRIPT",
        "LOCAL_TTS_RECEIPT",
        "AUDIO_ALIGNMENT_RECEIPT",
        "OBJECT_MOTION_IR",
        "ASSET_PLAN",
        "ASSET_BINDING_RECEIPT",
        "BEFORE_AFTER_DEMO_CONTRACT",
        "TARGET_SKILL_EXECUTION_GATE_RECEIPT",
        "LOCAL_RENDER_RECEIPT",
        "MEDIA_ACCEPTANCE_RECEIPT",
        "RESUMABLE_STAGE_RECEIPT",
    }
)

RESUMABLE_STAGE_ORDER = (
    "SOURCE",
    "REASONING",
    "NARRATION",
    "TTS",
    "ALIGNMENT",
    "ASSETS",
    "MOTION_IR",
    "RENDER",
    "SYNCHRONIZATION",
    "TECHNICAL_QA",
    "CONTENT_QA",
    "PACKAGING",
)


_ARTIFACT_KIND_FAILURE_RETURN_CODES: dict[str, tuple[str, ...]] = {
    "SOURCE_FREEZE_RECEIPT": ("INSUFFICIENT_SOURCE_EVIDENCE",),
    "FUNCTION_SCENARIO_EFFECT_MATRIX": (
        "FUNCTION_EFFECT_UNSUPPORTED",
        "CONTENT_EVIDENCE_MISMATCH",
    ),
    "NARRATION_SCRIPT": ("NARRATION_BUDGET_UNSATISFIED",),
    "LOCAL_TTS_RECEIPT": (
        "LOCAL_TTS_UNAVAILABLE",
        "TTS_DURATION_DRIFT",
    ),
    "AUDIO_ALIGNMENT_RECEIPT": (
        "FORCED_ALIGNMENT_FAILED",
        "MOTION_SYNC_TOLERANCE_EXCEEDED",
    ),
    "ASSET_PLAN": (
        "ASSET_ROUTE_UNRESOLVED",
        "CODEX_IMAGE_GENERATION_AUTHORIZATION_REQUIRED",
    ),
    "TARGET_SKILL_EXECUTION_GATE_RECEIPT": (
        "TARGET_SKILL_EXECUTION_DISABLED",
        "TARGET_SKILL_EXECUTION_AUTHORIZATION_REQUIRED",
    ),
    "OBJECT_MOTION_IR": (
        "MOTION_OBJECT_CONTRACT_INCOMPLETE",
        "MOTION_SYNC_TOLERANCE_EXCEEDED",
        "DISPLAY_COPY_REWRITE_REQUIRED",
    ),
    "LOCAL_RENDER_RECEIPT": (
        "RENDER_FAILED",
        "TECHNICAL_ACCEPTANCE_FAILED",
    ),
    "BEFORE_AFTER_DEMO_CONTRACT": ("CONTENT_EVIDENCE_MISMATCH",),
    "MEDIA_ACCEPTANCE_RECEIPT": (
        "TTS_DURATION_DRIFT",
        "AUDIO_VIDEO_DRIFT",
        "CONTENT_EVIDENCE_MISMATCH",
        "TECHNICAL_ACCEPTANCE_FAILED",
    ),
}

RELEASE_STEP_OUTPUT_CAPABILITIES = {
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
    "LAB_INSTALLED_POSITIVE_NEGATIVE_TAMPER_TESTS": (
        "LAB_INSTALLED_TEST_MATRIX_PASS"
    ),
    "C4_REPORT": "C4_CHECKPOINT_PASS",
    "CONFORMANCE_CERTIFICATE": "CONFORMANCE_CERTIFICATE_READY",
    "P4_CERTIFIED_RELEASE_LOCK": "P4_CERTIFIED_RELEASE_LOCK_VALID",
    "WAIT_REAL_TARGET_INSTALL_AUTHORIZATION": (
        "REAL_TARGET_INSTALL_AUTHORIZATION_GRANTED"
    ),
    "REAL_TARGET_INSTALL": "REAL_TARGET_INSTALL_COMPLETED",
    "REAL_TARGET_INSTALLATION_RECEIPT": "REAL_TARGET_INSTALL_RECEIPT_VERIFIED",
    "ACTIVE_INSTANCE_MANIFEST": "REAL_TARGET_ACTIVE",
}

HF28_MANDATORY_NEGATIVE_CASE_SPECS = (
    ("NEG-HF28-CODEX-SELF-REPORT", "Python or Harness self-reported Codex receipt must not prove invocation.", "INVOCATION_UNVERIFIED"),
    ("NEG-HF28-ATTESTATION-REPLAY", "Replayed runtime attestation challenge or receipt must fail.", "ATTESTATION_REPLAY_REJECTED"),
    ("NEG-HF28-OUTPUT-SUBSTITUTION", "Output substituted after runtime invocation must fail Hash binding.", "OUTPUT_SUBSTITUTION_DETECTED"),
    ("NEG-HF28-STUB-EXECUTOR", "Stub or fake executor identity must not satisfy runtime provenance.", "EXECUTOR_IDENTITY_UNTRUSTED"),
    ("NEG-HF28-P3-SKIP", "P1 P2 P4 progression without P3 lock and C3 must fail.", "ILLEGAL_PHASE_TRANSITION"),
    ("NEG-HF28-STALE-HASH", "Stale or forged predecessor Lock Hash must fail.", "STALE_PREDECESSOR_HASH"),
    ("NEG-HF28-MISSING-STAGE-RECEIPT", "Final artifact without every required intermediate Stage receipt must fail.", "STAGE_RECEIPT_MISSING"),
    ("NEG-HF28-SOURCE-DRIVER-FALLBACK", "Launching final runtime from source tree or Build Program Driver must fail.", "RUNTIME_ENTRYPOINT_FALLBACK_REJECTED"),
    ("NEG-HF28-CERTIFICATE-REUSE", "Certificate reuse after checker or scenario Hash changes must fail.", "CERTIFICATE_INVALIDATED"),
    ("NEG-HF28-AUTH-SCOPE", "Missing expired or scope-mismatched authorization must fail.", "AUTHORIZATION_INVALID"),
    ("NEG-HF28-MULTIPLE-NEXT-LEASE", "Multiple next actions active Workpacks or lease conflict must block.", "STATE_CONFLICT"),
    ("NEG-HF28-RELEASE-SKIP", "Skipping A B0 C B1 or D and jumping to C4 must fail.", "RELEASE_PREDECESSOR_MISSING"),
    ("NEG-HF28-LOOP-OSCILLATION", "Repeated Finding no-progress or A-B oscillation must stop and escalate.", "LOOP_ESCALATION_REQUIRED"),
    ("NEG-HF28-CRASH-DUPLICATE", "Crash after side effect before state commit must not repeat the command.", "DUPLICATE_SIDE_EFFECT_REJECTED"),
    ("NEG-HF28-UPSTREAM-INVALIDATION", "Upstream Hash change must invalidate affected project and release states.", "DEPENDENT_STATE_INVALIDATED"),
    ("NEG-HF28-AUTO-REAL-INSTALL", "Any automatic REAL_TARGET_INSTALL attempt must be rejected.", "REAL_TARGET_INSTALL_AUTHORIZATION_REQUIRED"),
    ("NEG-HF28-THREE-PROJECT-ORDER", "Lab must release before Linkage and Linkage must release before Main registration.", "ENGINEERING_PREDECESSOR_MISSING"),
    ("NEG-HF28-DUAL-ACTIVE-WORKPACK", "Two active Workpacks across the three projects must hard-stop.", "STATE_CONFLICT_HARD_STOP"),
    ("NEG-HF28-CANDIDATE-ENV-MISMATCH", "P4 installability certification and Lab using different Candidate Hashes must fail.", "CANDIDATE_HASH_MISMATCH"),
    ("NEG-HF28-TOOL-DISTRIBUTION-DRIFT", "Changing Lab or Linkage tool distribution mid-attempt must invalidate results.", "TOOL_DISTRIBUTION_HASH_CHANGED"),
    ("NEG-HF28-B0-B1-ORDER", "B0 cannot prefill Artifact Hash and B1 cannot precede immutable Artifact build.", "RELEASE_PREDECESSOR_MISSING"),
    ("NEG-HF28-LINKAGE-AUTHORITY", "Linkage must not modify reviewed assets or issue a Certificate.", "AUTHORITY_MISMATCH"),
)


def negative_case_specs_with_mandatory_controls(
    requirement_ir: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return the frozen negative cases plus the non-optional HF28 controls."""

    cases = [
        deepcopy(dict(item))
        for item in requirement_ir.get("negative_cases", [])
        if isinstance(item, Mapping)
    ]
    for case in cases:
        case.setdefault("expected_failure", "EXPECTED_REJECTION")
        case.setdefault("origin", "FROZEN_REQUIREMENT_IR")
    existing = {str(item.get("case_id")) for item in cases}
    atom_ids = [
        str(item.get("atom_id"))
        for item in requirement_ir.get("atoms", [])
        if isinstance(item, Mapping) and item.get("atom_id")
    ]
    for case_id, description, expected_failure in HF28_MANDATORY_NEGATIVE_CASE_SPECS:
        if case_id in existing:
            continue
        cases.append(
            {
                "case_id": case_id,
                "atom_ids": atom_ids,
                "description": description,
                "expected_failure": expected_failure,
                "origin": "HF28_LOCKED_CONTROL_CONTRACT",
            }
        )
    return cases


_INVARIANT_MUTATION_TARGETS = {
    "FROZEN_FILE_REFS_AND_HASHES_HAVE_EQUAL_CARDINALITY": "/frozen_file_sha256s",
    "EVERY_FROZEN_FILE_HASH_MATCHES_REFERENCED_BYTES": "/frozen_file_sha256s/0",
    "EVERY_CLAIM_BINDING_RESOLVES_TO_FROZEN_FILE_AND_MATCHES_HASH": "/claim_bindings/0/source_ref",
    "LICENSE_SPDX_MATCHES_HASHED_LICENSE_EVIDENCE": "/license_spdx",
    "SOURCE_MANIFEST_ENTRY_MATCHES_REPOSITORY_COMMIT_AND_TREE": "/source_manifest_sha256",
    "EVERY_CLAIM_HAS_FUNCTION_SCENARIO_EFFECT_AND_SOURCE_EVIDENCE": "/claims/0/source_refs",
    "CLAIM_IDS_ARE_UNIQUE": "/claims/0/claim_id",
    "CLAIM_MANIFEST_SHA256_MATCHES_CANONICAL_CLAIM_ARRAY": "/claim_manifest_sha256",
    "EVERY_VERIFIED_CLAIM_IS_COVERED_BY_AT_LEAST_ONE_SENTENCE": "/sentences/0/claim_ids",
    "EVERY_SENTENCE_HAS_A_VISUAL_INTENT": "/sentences/0/visual_intent",
    "NARRATION_VISUAL_INTENT_IDS_ARE_UNIQUE": "/sentences/0/visual_intent_id",
    "SCRIPT_SHA256_MATCHES_CANONICAL_SENTENCE_ARRAY": "/script_sha256",
    "NARRATION_BUDGET_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES": "/narration_budget_receipt_sha256",
    "NARRATION_BUDGET_ESTIMATE_MATCHES_CANONICAL_SENTENCE_ARRAY_AND_METHOD": "/narration_budget_estimated_seconds",
    "NARRATION_SCRIPT_SHA256_MATCHES_REFERENCED_SCRIPT": "/narration_script_sha256",
    "TRANSCRIPT_SHA256_MATCHES_SYNTHESIZED_AUDIO_TRANSCRIPT": "/transcript_sha256",
    "CLAIM_COVERAGE_SHA256_MATCHES_NARRATION_SCRIPT": "/claim_coverage_sha256",
    "TTS_MODEL_SHA256_MATCHES_REFERENCED_LOCAL_MODEL_ARTIFACT": "/model_sha256",
    "TTS_PROVIDER_IMPLEMENTATION_SHA256_MATCHES_REFERENCED_LOCAL_BYTES": "/provider_implementation_sha256",
    "PROVIDER_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES": "/provider_receipt_sha256",
    "TTS_RUNTIME_ENVIRONMENT_SHA256_MATCHES_REFERENCED_BYTES": "/runtime_environment_sha256",
    "LICENSE_SPDX_MATCHES_TTS_MODEL_LICENSE_EVIDENCE": "/license_evidence_sha256",
    "TTS_EXECUTION_MODE_IS_LOCAL_OFFLINE": "/execution_mode",
    "TTS_NETWORK_ACCESS_WAS_NOT_USED": "/network_accessed",
    "TTS_VOICE_IS_NOT_CLONED": "/voice_cloned",
    "AUDIO_SHA256_MATCHES_REFERENCED_AUDIO_BYTES": "/audio_sha256",
    "TTS_RECEIPT_AUDIO_SHA256_EQUALS_AUDIO_SHA256": "/audio_sha256",
    "TTS_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES": "/tts_receipt_sha256",
    "EVERY_WORD_ANCHOR_AUDIO_SHA256_EQUALS_TOP_LEVEL_AUDIO_SHA256": "/word_anchors/0/audio_sha256",
    "EVERY_WORD_ANCHOR_START_SECONDS_IS_LESS_THAN_END_SECONDS": "/word_anchors/0/end_seconds",
    "WORD_ANCHORS_ARE_MONOTONIC_AND_NON_OVERLAPPING": "/word_anchors/0/start_seconds",
    "SENTENCE_IDS_EQUAL_NARRATION_SCRIPT_SENTENCE_IDS": "/sentence_ids",
    # Retained so older immutable Candidates remain diagnosable by the
    # repaired Validator even though new Producers no longer emit it.
    "ABSOLUTE_FINAL_AV_DRIFT_EQUALS_ABS_FINAL_AV_DRIFT": "/absolute_final_av_drift_frames",
    "ALIGNMENT_RECEIPT_AUDIO_SHA256_EQUALS_AUDIO_SHA256": "/audio_sha256",
    "ALIGNMENT_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES": "/alignment_receipt_sha256",
    "CLAIM_MATRIX_SHA256_MATCHES_REFERENCED_BYTES": "/claim_matrix_sha256",
    "AUDIO_ANCHOR_IDS_EQUAL_REFERENCED_ALIGNMENT_ANCHOR_IDS": "/audio_anchor_ids",
    "FULL_TIMELINE_CONTIGUOUS_NO_GAPS_OR_OVERLAPS": "/shots/1/start_seconds",
    "FIRST_SHOT_STARTS_AT_ZERO": "/shots/0/start_seconds",
    "FINAL_SHOT_END_EQUALS_DURATION_SECONDS": "/duration_seconds",
    "SHOT_SENTENCE_ID_UNION_EQUALS_TOP_LEVEL_SENTENCE_IDS": "/shots/0/sentence_ids",
    "SHOT_AUDIO_ANCHOR_ID_UNION_EQUALS_TOP_LEVEL_AUDIO_ANCHOR_IDS": "/shots/0/audio_anchor_ids",
    "EVERY_OBJECT_AUDIO_ANCHOR_ID_EXISTS_IN_AUDIO_ANCHOR_IDS": "/shots/0/objects/0/audio_anchor_id",
    "EVERY_MOTION_OBJECT_BINDS_SENTENCES_CLAIMS_VISUAL_INTENT_ASSET_AND_AUDIO_ANCHOR": "/shots/0/objects/0/claim_ids",
    "MOTION_OBJECT_BINDINGS_RESOLVE_TO_NARRATION_ASSET_AND_ALIGNMENT": "/shots/0/objects/0/visual_intent_id",
    "EVERY_SPOKEN_SENTENCE_HAS_VISIBLE_OBJECT_DURING_BOUND_AUDIO_ANCHOR": "/shots/0/objects/0/sentence_ids",
    "EVERY_OBJECT_WORD_TO_MOTION_ERROR_DOES_NOT_EXCEED_0_1_SECONDS": "/shots/0/objects/0/enter_time",
    "SCENE_TRANSITION_COUNT_EQUALS_NON_INITIAL_TRANSITIONS": "/scene_transition_count",
    "ENTER_TIME_LESS_THAN_OR_EQUAL_TO_HOLD_START": "/shots/0/objects/0/enter_time",
    "HOLD_START_LESS_THAN_HOLD_END": "/shots/0/objects/0/hold_interval/end_seconds",
    "HOLD_END_LESS_THAN_OR_EQUAL_TO_EXIT_TIME": "/shots/0/objects/0/exit_time",
    "MOTION_CURVE_IDS_EQUAL_OBJECT_MOTION_SEGMENT_CURVE_IDS": "/motion_curve_ids",
    "MOTION_SEGMENT_IDS_ARE_UNIQUE": "/shots/0/objects/0/motion_segments/1/segment_id",
    "ENTER_HOLD_EXIT_SEGMENTS_ARE_CONTIGUOUS_AND_MATCH_DECLARED_INTERVALS": "/shots/0/objects/0/motion_segments/1/phase",
    "EVERY_MOTION_SEGMENT_HAS_DISTINCT_FROM_AND_TO_STATE": "/shots/0/objects/0/motion_segments/0/to_state",
    "MOTION_OBJECT_IDS_EQUAL_ASSET_OBJECT_IDS": "/motion_object_ids",
    "EVERY_ASSET_BINDS_SENTENCES_CLAIMS_AND_VISUAL_INTENT": "/assets/0/claim_ids",
    "ASSET_SEMANTIC_BINDINGS_RESOLVE_TO_NARRATION_AND_CLAIM_MATRIX": "/resolved_asset_visual_intent_ids",
    "ASSET_MANIFEST_SHA256_MATCHES_CANONICAL_ASSET_ARRAY": "/asset_manifest_sha256",
    "EVERY_MATERIALIZED_ASSET_REF_HASH_MATCHES_ASSET_SHA256": "/assets/0/asset_sha256",
    "ASSET_PROVENANCE_REFS_AND_HASHES_HAVE_EQUAL_CARDINALITY": "/assets/0/provenance_sha256s",
    "EVERY_ASSET_PROVENANCE_HASH_MATCHES_REFERENCED_BYTES": "/assets/0/provenance_sha256s/0",
    "LOCAL_DETERMINISTIC_ASSET_RECIPE_AND_OUTPUT_ARE_HASH_BOUND": "/assets/0/local_build_recipe/implementation_sha256",
    "CODEX_IMAGEGEN_MATERIALIZATION_REQUIRES_SEPARATE_CURRENT_AUTHORIZATION": "/assets/0/generation_authorization_ref",
    "IMAGEGEN_RECEIPT_HASH_MATCHES_REFERENCED_BYTES_WHEN_MATERIALIZED": "/assets/0/generation_receipt_sha256",
    "DEMO_CLAIM_IDS_RESOLVE_TO_SAME_JOB_CLAIM_MATRIX": "/claim_ids",
    "DEMO_EFFECT_CLAIM_RESOLVES_TO_SAME_JOB_CLAIM_MATRIX": "/effect_claim_id",
    "BEFORE_AND_AFTER_HASHES_MATCH_REFERENCED_BYTES": "/output_after_sha256",
    "DEMO_INPUT_AND_OUTPUT_BYTES_ARE_DISTINCT": "/output_after_sha256",
    "DEMO_EFFECT_DELTA_CONTAINS_OBSERVED_STATE_CHANGE": "/effect_delta/0/after_value",
    "DEMO_EFFECT_DELTA_PROPERTY_PATHS_RESOLVE_IN_BOTH_STATES": "/effect_delta/0/property_path",
    "DEMO_EFFECT_DELTA_VALUES_EQUAL_RESOLVED_STATE_VALUES": "/effect_delta/0/after_value",
    "DEMO_EFFECT_DELTA_BEFORE_AND_AFTER_VALUES_ARE_DISTINCT": "/effect_delta/0/after_value",
    "DEMO_EFFECT_DELTA_EVIDENCE_SHA256_MATCHES_REFERENCED_BYTES": "/effect_delta/0/evidence_sha256",
    "DEMO_EFFECT_DELTA_EVIDENCE_BINDS_BEFORE_AND_AFTER_BYTES": "/effect_delta/0/evidence_output_sha256",
    "DEMO_PROCESSING_ACTION_MATCHES_EFFECT_CLAIM": "/processing_action",
    "SOURCE_EVIDENCE_REFS_AND_HASHES_HAVE_EQUAL_CARDINALITY": "/source_evidence_sha256s",
    "OBSERVED_REPO_FIXTURE_REQUIRES_PINNED_SOURCE_EVIDENCE": "/source_evidence_refs",
    "AUTHORIZED_TARGET_SKILL_RUN_REQUIRES_CURRENT_EXACT_AUTHORIZATION_AND_RECEIPT": "/target_skill_execution_receipt_ref",
    "ILLUSTRATION_IS_EXPLICITLY_LABELED_AND_NOT_ACTUAL_SKILL_OUTPUT": "/illustration_label",
    "AUTHORIZED_TARGET_EXECUTION_BINDS_EXACT_JOB_COMMIT_INPUT_ENVIRONMENT_AND_OUTPUT": "/authorized_job_id",
    "TARGET_EXECUTION_ENVIRONMENT_RECEIPT_HASH_MATCHES_REFERENCED_BYTES": "/authorized_environment_manifest_ref",
    "TARGET_EXECUTION_OUTPUT_RECEIPT_HASH_MATCHES_REFERENCED_BYTES": "/output_receipt_sha256",
    "AUTHORIZED_ENVIRONMENT_MANIFEST_SHA256_EQUALS_CURRENT_ENVIRONMENT_MANIFEST_SHA256": "/current_environment_manifest_sha256",
    "AUTHORIZED_OUTPUT_MANIFEST_SHA256_EQUALS_CURRENT_OUTPUT_MANIFEST_SHA256": "/current_output_manifest_sha256",
    "TARGET_EXECUTION_AUTHORIZATION_IS_CURRENT_SINGLE_USE_AND_NOT_PROGRAM_WIDE": "/authorization_freshness",
    "TARGET_EXECUTION_RECEIPT_HASH_MATCHES_REFERENCED_BYTES": "/execution_receipt_sha256",
    "DENIED_TARGET_SKILL_GATE_HAS_NO_AUTHORIZATION_OR_SIDE_EFFECT_ATTEMPT": "/attempted_side_effect_ids",
    "TTS_ALIGNMENT_MOTION_AND_RENDER_AUDIO_SHA256_ARE_EQUAL": "/audio_sha256",
    "LOCAL_RENDER_TTS_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES": "/tts_receipt_sha256",
    "LOCAL_RENDER_ALIGNMENT_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES": "/alignment_receipt_sha256",
    "DEPENDENCY_MANIFEST_SHA256_MATCHES_REFERENCED_BYTES": "/dependency_manifest_sha256",
    "DEPENDENCY_MANIFEST_BINDS_EXACT_DECLARED_ARTIFACT_DEPENDENCIES": "/dependency_manifest_sha256",
    "MOTION_IR_SHA256_MATCHES_REFERENCED_MOTION_IR": "/motion_ir_sha256",
    "ASSET_PLAN_SHA256_MATCHES_REFERENCED_ASSET_PLAN": "/asset_plan_sha256",
    "RENDER_INPUT_MANIFEST_SHA256_MATCHES_REFERENCED_BYTES": "/render_input_manifest_sha256",
    "RENDER_INPUT_MANIFEST_BINDS_EXACT_ASSET_REFS_AND_SHA256S": "/render_input_manifest_sha256",
    "RENDER_COMPOSITION_SHA256_MATCHES_REFERENCED_BYTES": "/composition_sha256",
    "RENDER_COMMAND_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES": "/render_command_receipt_sha256",
    "VIDEO_BYTES_INCLUDE_THE_REFERENCED_AUDIO_STREAM": "/audio_stream_present",
    "RENDER_TRACE_SHA256_MATCHES_REFERENCED_TRACE": "/render_trace_sha256",
    "RENDERED_SHOT_IDS_EQUAL_MOTION_IR_SHOT_IDS": "/rendered_shot_ids",
    "RENDERED_OBJECT_IDS_EQUAL_MOTION_IR_OBJECT_IDS": "/rendered_object_ids",
    "RENDERED_MOTION_CURVE_IDS_EQUAL_MOTION_IR_CURVE_IDS": "/rendered_motion_curve_ids",
    "RENDERED_SEMANTIC_BINDINGS_EQUAL_MOTION_IR_OBJECT_BINDINGS": "/rendered_semantic_bindings/0/visual_intent_id",
    "RENDER_TRACE_SAMPLES_MATCH_DECLARED_OBJECT_CURVES": "/render_trace_sample_count",
    "FFPROBE_INPUT_SHA256_EQUALS_VIDEO_SHA256": "/video_sha256",
    "RENDER_RECEIPT_VIDEO_SHA256_EQUALS_VIDEO_SHA256": "/render_receipt_ref",
    "FFPROBE_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES": "/ffprobe_receipt_sha256",
    "MEDIA_RENDER_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES": "/render_receipt_sha256",
    "MEDIA_TTS_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES": "/tts_receipt_sha256",
    "MEDIA_ALIGNMENT_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES": "/alignment_receipt_sha256",
    "RENDER_TTS_ALIGNMENT_AND_MEDIA_AUDIO_SHA256_ARE_EQUAL": "/audio_sha256",
    "RECOMPUTED_ANCHOR_ERROR_DOES_NOT_EXCEED_0_1_SECONDS": "/max_anchor_error_seconds",
    "ABSOLUTE_FINAL_AV_DRIFT_DOES_NOT_EXCEED_ONE_FRAME": "/final_av_drift_frames",
    "MOTION_PROBE_SHA256_MATCHES_REFERENCED_PROBE": "/motion_probe_sha256",
    "OBSERVED_DYNAMIC_FRAME_COUNT_IS_NONZERO": "/observed_dynamic_frame_count",
    "OBSERVED_SCENE_TRANSITION_COUNT_EQUALS_EXPECTED_SCENE_TRANSITION_COUNT": "/observed_scene_transition_count",
    "MOTION_PROBE_BINDS_FINAL_VIDEO_SHA256_AND_MOTION_IR_SHA256": "/motion_probe_ref",
    "OBSERVED_MOTION_OBJECT_IDS_EQUAL_MOTION_IR_OBJECT_IDS": "/observed_motion_objects/0/object_id",
    "OBSERVED_MOTION_CURVE_IDS_EQUAL_MOTION_IR_CURVE_IDS": "/observed_motion_objects/0/motion_curve_ids/0",
    "OBSERVED_MOTION_SEMANTIC_BINDINGS_EQUAL_RENDERED_AND_MOTION_BINDINGS": "/observed_motion_objects/0/visual_intent_id",
    "EACH_DECLARED_OBJECT_HAS_NONZERO_PROBED_MOTION": "/observed_motion_objects/0/changed_frame_count",
    "EVERY_OBJECT_MOTION_PROBE_HASH_MATCHES_REFERENCED_PROBE": "/observed_motion_objects/0/probe_sha256",
    "FIXTURE_RESULT_JOB_IDS_EQUAL_FROZEN_REPOSITORY_JOB_IDS": "/fixture_results/0/job_id",
    "FIXTURE_RESULT_SOURCE_IDS_EQUAL_FROZEN_REPOSITORY_SOURCE_IDS": "/fixture_results/0/source_id",
    "EXPECTED_FUNCTION_SCENARIO_EFFECT_RESOLVE_TO_JOB_CLAIM_MATRIX": "/fixture_results/0/expected_function",
    "DEMO_CONTRACT_REF_RESOLVES_TO_SAME_JOB_BEFORE_AFTER_CONTRACT": "/fixture_results/0/demo_contract_ref",
    "ACCEPTANCE_CASE_RESULT_IDS_EQUAL_FROZEN_ACCEPTANCE_CASE_IDS": "/acceptance_case_results/0/case_id",
    "ACCEPTANCE_CASE_RESULT_REFS_EQUAL_FROZEN_CASE_RESULT_REFS": "/acceptance_case_results/0/result_ref",
    "EVERY_ACCEPTANCE_CASE_RESULT_SHA256_MATCHES_REFERENCED_BYTES": "/acceptance_case_results/0/result_sha256",
    "NEGATIVE_CASE_RESULT_IDS_EQUAL_COMPLETE_NEGATIVE_CASE_IDS": "/negative_case_results/0/case_id",
    "NEGATIVE_CASE_RESULT_REFS_EQUAL_FROZEN_CASE_RESULT_REFS": "/negative_case_results/0/result_ref",
    "EVERY_NEGATIVE_CASE_RESULT_SHA256_MATCHES_REFERENCED_BYTES": "/negative_case_results/0/result_sha256",
    "EVERY_FIXTURE_CASE_RESULT_SHA256_MATCHES_REFERENCED_BYTES": "/fixture_results/0/case_result_sha256",
    "EVERY_FIXTURE_VIDEO_SHA256_MATCHES_REFERENCED_BYTES": "/fixture_results/0/video_sha256",
    "EVERY_NEGATIVE_RESULT_OBSERVES_EXPECTED_FAILURE_WITHOUT_SIDE_EFFECTS": "/negative_case_results/0/observed_failure_code",
    "NEGATIVE_MUTATION_MANIFEST_HASH_MATCHES_REFERENCED_VARIANTS": "/negative_case_results/0/mutation_manifest_sha256",
    "NEGATIVE_MUTATION_VARIANT_RESULT_IDS_EQUAL_DECLARED_VARIANT_IDS": "/negative_case_results/0/mutation_variant_results/0/variant_id",
    "EVERY_NEGATIVE_MUTATION_VARIANT_HAS_HASH_BOUND_EXECUTION_EVIDENCE": "/negative_case_results/0/mutation_variant_results/0/mutation_receipt_sha256",
    "CASE_MANIFEST_HASHES_MATCH_REFERENCED_CANDIDATE_CASE_DOCUMENTS": "/acceptance_case_manifest_sha256",
    "ORACLE_EVALUATOR_REGISTRY_HASH_MATCHES_REFERENCED_BYTES": "/oracle_evaluator_registry_sha256",
    "INVARIANT_NEGATIVE_CASE_RESULT_IDS_EQUAL_REGISTRY_CASE_IDS": "/invariant_negative_case_results/0/case_id",
    "INVARIANT_NEGATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS": "/invariant_negative_case_results/0/schema_instance_results/0/result_ref",
    "EVERY_INVARIANT_NEGATIVE_RESULT_SHA256_MATCHES_REFERENCED_BYTES": "/invariant_negative_case_results/0/schema_instance_results/0/result_sha256",
    "EVERY_INVARIANT_RESULT_COVERS_EXACT_APPLICABLE_SCHEMA_SHA256S": "/invariant_negative_case_results/0/schema_instance_results/0/schema_sha256",
    "EVERY_INVARIANT_MUTATION_PRESERVES_JSON_SCHEMA_AND_FAILS_DECLARED_INVARIANT": "/invariant_negative_case_results/0/schema_instance_results/0/mutated_schema_pass",
    "SCHEMA_NATIVE_NEGATIVE_CASE_RESULT_IDS_EQUAL_REGISTRY_CASE_IDS": "/schema_native_negative_case_results/0/case_id",
    "SCHEMA_NATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS": "/schema_native_negative_case_results/0/schema_instance_results/0/result_ref",
    "EVERY_SCHEMA_NATIVE_RESULT_SHA256_MATCHES_REFERENCED_BYTES": "/schema_native_negative_case_results/0/schema_instance_results/0/result_sha256",
    "EVERY_SCHEMA_NATIVE_MUTATION_FAILS_SCHEMA_WITHOUT_ORACLE_OR_SIDE_EFFECTS": "/schema_native_negative_case_results/0/schema_instance_results/0/mutated_schema_pass",
    "INPUT_MANIFEST_SHA256_MATCHES_CANONICAL_INPUT_HASHES": "/input_manifest_sha256",
    "OUTPUT_MANIFEST_SHA256_MATCHES_CANONICAL_OUTPUT_HASHES": "/output_manifest_sha256",
    "EVENT_PAYLOAD_SHA256_MATCHES_CANONICAL_STAGE_EVENT": "/event_payload_sha256",
    "EVENT_HASH_RECOMPUTES_FROM_PREVIOUS_HASH_AND_CANONICAL_EVENT_PAYLOAD": "/event_hash",
    "REUSE_VALID_RECEIPT_REQUIRES_EXACT_CURRENT_INPUT_HASHES": "/current_input_hashes_sha256",
    "RERUN_INVALIDATED_STAGE_REQUIRES_CHANGED_OR_INVALIDATED_INPUT": "/current_input_hashes_sha256",
    "STOP_FOR_AUTHORITY_HAS_NO_SIDE_EFFECT_ATTEMPT": "/attempted_side_effect_ids",
    "COMPLETED_SIDE_EFFECTS_AND_IDEMPOTENCY_KEYS_ARE_NOT_REPLAYED": "/attempted_idempotency_keys",
    "STAGE_ID_AND_INDEX_MATCH_FROZEN_STAGE_EXPECTATION": "/stage_id",
    "PREVIOUS_STAGE_ID_MATCHES_FROZEN_STAGE_ORDER": "/previous_stage_id",
    "AUTHORING_FIELDS_DESCRIBE_THE_IMMUTABLE_CANDIDATE_HANDOFF_NOT_CURRENT_RUNTIME_STATE": "/authoring_execution_mode",
    "HUMAN_REVIEW_CLOSURE_HASH_MATCHES_REFERENCED_CLOSURE_RECEIPT": "/candidate_human_review_closure_sha256",
}


_SCHEMA_NATIVE_INVARIANT_CASES: dict[str, dict[str, Any]] = {
    "EVERY_SENTENCE_HAS_A_VISUAL_INTENT": {
        "artifact_kind": "NARRATION_SCRIPT",
        "operation": "REMOVE_REQUIRED_FIELD",
        "target_ref": "/sentences/0/visual_intent",
    },
    "EVERY_ASSET_BINDS_SENTENCES_CLAIMS_AND_VISUAL_INTENT": {
        "artifact_kind": "ASSET_PLAN",
        "operation": "REMOVE_REQUIRED_FIELD",
        "target_ref": "/assets/0/claim_ids",
    },
    "EVERY_ASSET_HAS_EXACTLY_ONE_ROUTE": {
        "artifact_kind": "ASSET_PLAN",
        "operation": "REMOVE_REQUIRED_FIELD",
        "target_ref": "/assets/0/route",
    },
}


_INVARIANT_MUTATION_RECIPES: dict[str, dict[str, Any]] = {
    "FROZEN_FILE_REFS_AND_HASHES_HAVE_EQUAL_CARDINALITY": {
        "strategy": "CHANGE_ARRAY_CARDINALITY_RELATIVE_TO_PARALLEL_ARRAY_WITHIN_SCHEMA",
        "comparison_ref": "/frozen_file_refs",
    },
    "FINAL_SHOT_END_EQUALS_DURATION_SECONDS": {
        "strategy": "SELECT_SCHEMA_VALID_VALUE_NOT_EQUAL_TO_REFERENCED_BASE_VALUE",
        "comparison_ref": "/shots/-1/end_seconds",
        "array_selector_semantics": "-1_MEANS_LAST_EXISTING_ARRAY_ITEM",
    },
    "FULL_TIMELINE_CONTIGUOUS_NO_GAPS_OR_OVERLAPS": {
        "strategy": "OFFSET_FROM_PREVIOUS_SHOT_END_WITHIN_TARGET_SCHEMA",
        "comparison_ref": "/shots/0/end_seconds",
    },
    "EVERY_MOTION_SEGMENT_HAS_DISTINCT_FROM_AND_TO_STATE": {
        "strategy": "COPY_VALUE_FROM_JSON_POINTER",
        "source_ref": "/shots/0/objects/0/motion_segments/0/from_state",
    },
    "EVERY_OBJECT_WORD_TO_MOTION_ERROR_DOES_NOT_EXCEED_0_1_SECONDS": {
        "strategy": (
            "SET_OBJECT_ENTER_TIME_TO_BOUND_AUDIO_ANCHOR_START_PLUS_"
            "TOLERANCE_PLUS_EPSILON_WITHIN_SHOT"
        ),
        "audio_anchor_id_ref": "/shots/0/objects/0/audio_anchor_id",
        "audio_anchor_collection_ref": (
            "dependency://AUDIO_ALIGNMENT_RECEIPT/word_anchors"
        ),
        "tolerance_ref": "/word_to_motion_tolerance_seconds",
        "epsilon_seconds": 0.001,
    },
    "DEMO_EFFECT_DELTA_PROPERTY_PATHS_RESOLVE_IN_BOTH_STATES": {
        "strategy": "SELECT_SCHEMA_VALID_JSON_POINTER_OUTSIDE_BOTH_STATE_OBJECTS",
        "comparison_refs": ["/input_state", "/output_state"],
    },
    "DEMO_EFFECT_DELTA_VALUES_EQUAL_RESOLVED_STATE_VALUES": {
        "strategy": "SELECT_VALUE_DIFFERENT_FROM_JSON_POINTER_RESOLUTION",
        "property_path_ref": "/effect_delta/0/property_path",
        "state_refs": ["/input_state", "/output_state"],
    },
    "DEMO_EFFECT_DELTA_BEFORE_AND_AFTER_VALUES_ARE_DISTINCT": {
        "strategy": "COPY_VALUE_FROM_JSON_POINTER",
        "source_ref": "/effect_delta/0/before_value",
    },
    "DEMO_EFFECT_DELTA_EVIDENCE_BINDS_BEFORE_AND_AFTER_BYTES": {
        "strategy": "DERIVE_SCHEMA_VALID_HASH_DIFFERENT_FROM_REFERENCED_VALUE",
        "comparison_refs": ["/input_before_sha256", "/output_after_sha256"],
    },
    "MOTION_SEGMENT_IDS_ARE_UNIQUE": {
        "strategy": "COPY_VALUE_FROM_JSON_POINTER",
        "source_ref": "/shots/0/objects/0/motion_segments/0/segment_id",
    },
    "REUSE_VALID_RECEIPT_REQUIRES_EXACT_CURRENT_INPUT_HASHES": {
        "strategy": "SELECT_SCHEMA_VALID_HASH_DIFFERENT_FROM_RECEIPT_INPUT_HASHES",
        "comparison_ref": "/receipt_input_hashes_sha256",
        "required_base_branch": "REUSED_VALID_RECEIPT",
    },
    "RERUN_INVALIDATED_STAGE_REQUIRES_CHANGED_OR_INVALIDATED_INPUT": {
        "strategy": "COPY_VALUE_FROM_JSON_POINTER",
        "source_ref": "/receipt_input_hashes_sha256",
        "required_base_branch": "RERUN_REQUIRED_INPUT_CHANGED_OR_INVALID",
    },
    "STAGE_ID_AND_INDEX_MATCH_FROZEN_STAGE_EXPECTATION": {
        "strategy": "SELECT_DIFFERENT_MEMBER_OF_FROZEN_STAGE_ENUM",
    },
    "PREVIOUS_STAGE_ID_MATCHES_FROZEN_STAGE_ORDER": {
        "strategy": "SELECT_SCHEMA_VALID_VALUE_DIFFERENT_FROM_FROZEN_PREDECESSOR",
    },
    "NARRATION_BUDGET_ESTIMATE_MATCHES_CANONICAL_SENTENCE_ARRAY_AND_METHOD": {
        "strategy": "DERIVE_SCHEMA_VALID_ESTIMATE_DIFFERENT_FROM_CANONICAL_BUDGET_RECOMPUTATION",
        "comparison_refs": [
            "/sentences",
            "/narration_budget_method",
        ],
    },
}


def _invariant_mutation_recipe(invariant_id: str) -> dict[str, Any]:
    """Return an executable obligation without fabricating a passing witness."""

    recipe = deepcopy(_INVARIANT_MUTATION_RECIPES.get(invariant_id, {}))
    if not recipe:
        if "ARE_UNIQUE" in invariant_id:
            strategy = "COPY_EXISTING_SIBLING_ID_TO_DISTINCT_ARRAY_MEMBER"
        elif "RESOLVE" in invariant_id or "EXISTS_IN" in invariant_id:
            strategy = "SELECT_SCHEMA_VALID_IDENTIFIER_OUTSIDE_REFERENCE_SET"
        elif "NO_SIDE_EFFECT" in invariant_id or "NOT_REPLAYED" in invariant_id:
            strategy = "INTRODUCE_FORBIDDEN_SIDE_EFFECT_OR_REPLAY_SET_INTERSECTION"
        elif any(
            token in invariant_id
            for token in ("SHA256", "HASH", "EQUAL", "MATCHES")
        ):
            strategy = "DERIVE_SCHEMA_VALID_VALUE_DIFFERENT_FROM_REFERENCED_VALUE"
        else:
            strategy = (
                "DETERMINISTIC_BOUNDED_EXACT_COUNTEREXAMPLE_ENUMERATION"
            )
            recipe.update(
                {
                    "maximum_candidates": 4096,
                    "candidate_generation_order": [
                        "COPY_REFERENCED_VALUE",
                        "SCHEMA_BOUNDARY_NEIGHBORS",
                        "BOOLEAN_TOGGLE",
                        "ENUM_ALTERNATIVES_IN_DECLARED_ORDER",
                        "ARRAY_SINGLE_MEMBER_EDIT",
                        "OBJECT_SINGLE_FIELD_EDIT",
                    ],
                    "candidate_sort": (
                        "CANONICAL_JSON_UTF8_LEXICOGRAPHIC"
                    ),
                }
            )
        recipe["strategy"] = strategy
    recipe.update(
        {
            "recipe_id": f"MUTATION-{_safe_id(invariant_id)}-V1",
            "base_selection": "FULL_ARTIFACT_SCHEMA_AND_ALL_ORACLES_PASS",
            "acceptance_predicate": {
                "full_artifact_json_schema": "PASS",
                "failed_invariant_ids": [invariant_id],
                "all_other_invariant_ids": "PASS",
            },
            "failure_if_unsatisfied": "EXACT_COUNTEREXAMPLE_NOT_FOUND",
        }
    )
    return recipe


INVARIANT_CONTRACT_REQUIRED_FIELDS = frozenset(
    {
        "algorithm_id",
        "algorithm_version",
        "algorithm",
        "input_refs",
        "target_ref",
        "canonicalization",
        "ordering",
        "numeric_tolerance",
        "branch_precondition",
        "decision_rule",
        "failure_code",
    }
)


def _invariant_algorithm_family(invariant_id: str) -> str:
    if "SHA256" in invariant_id or "HASH" in invariant_id:
        return "HASH_AND_BYTE_LINEAGE_V1"
    if "ARE_UNIQUE" in invariant_id:
        return "CANONICAL_MEMBER_UNIQUENESS_V1"
    if "CARDINALITY" in invariant_id:
        return "EXACT_ARRAY_CARDINALITY_COMPARISON_V1"
    if any(
        token in invariant_id
        for token in ("RESOLVE", "EXISTS_IN", "BINDS", "REQUIRES")
    ):
        return "DECLARED_REFERENCE_RESOLUTION_V1"
    if any(
        token in invariant_id
        for token in (
            "LESS_THAN",
            "DOES_NOT_EXCEED",
            "NONZERO",
            "MONOTONIC",
            "CONTIGUOUS",
        )
    ):
        return "ORDERED_NUMERIC_PREDICATE_V1"
    if "EQUAL" in invariant_id or "MATCHES" in invariant_id:
        return "CANONICAL_VALUE_OR_SET_EQUALITY_V1"
    if any(
        token in invariant_id
        for token in ("NO_SIDE_EFFECT", "NOT_REPLAYED", "IS_NOT", "WAS_NOT")
    ):
        return "POLICY_STATE_PREDICATE_V1"
    return "EXACT_NAMED_PREDICATE_V1"


def _invariant_evaluation_contract(invariant_id: str) -> dict[str, Any]:
    """Return the deterministic Lab evaluator contract for one invariant."""

    target_ref = _INVARIANT_MUTATION_TARGETS.get(invariant_id)
    if target_ref is None:
        raise ValueError(f"invariant evaluation target is missing: {invariant_id}")
    recipe = _invariant_mutation_recipe(invariant_id)
    input_refs = [
        target_ref,
        "artifact://self",
        "manifest://declared-artifact-dependencies",
        "evidence://declared-reference-bytes",
    ]
    for field in (
        "comparison_ref",
        "source_ref",
        "audio_anchor_id_ref",
        "audio_anchor_collection_ref",
        "tolerance_ref",
        "property_path_ref",
    ):
        value = recipe.get(field)
        if isinstance(value, str) and value and value not in input_refs:
            input_refs.append(value)
    for field in ("comparison_refs", "state_refs"):
        for value in recipe.get(field, []):
            if isinstance(value, str) and value and value not in input_refs:
                input_refs.append(value)
    family = _invariant_algorithm_family(invariant_id)
    decision_rules = {
        "HASH_AND_BYTE_LINEAGE_V1": (
            "Resolve the reference paired by the artifact schema or declared "
            "dependency manifest, hash its exact bytes with SHA-256, and require "
            "the lowercase digest to equal the declared digest; manifest hashes "
            "use canonical UTF-8 JSON bytes."
        ),
        "CANONICAL_MEMBER_UNIQUENESS_V1": (
            "Canonicalize each member independently and require member count to "
            "equal distinct canonical-member count."
        ),
        "EXACT_ARRAY_CARDINALITY_COMPARISON_V1": (
            "Resolve the two arrays named by the invariant and require their "
            "integer lengths to be exactly equal."
        ),
        "DECLARED_REFERENCE_RESOLUTION_V1": (
            "Resolve every identifier or resource reference at the target against "
            "the exact declared dependency indexes and require exactly one "
            "same-Job match with every declared byte hash verified."
        ),
        "ORDERED_NUMERIC_PREDICATE_V1": (
            "Read JSON numbers as exact decimal values, evaluate subjects in "
            "declared array order, and require the ordering or bound stated by "
            "the invariant for every subject."
        ),
        "CANONICAL_VALUE_OR_SET_EQUALITY_V1": (
            "Resolve the values named by the invariant; compare scalars exactly "
            "and compare ID collections as sorted unique UTF-8 strings."
        ),
        "POLICY_STATE_PREDICATE_V1": (
            "Select the active JSON-Schema branch and require every forbidden "
            "side-effect, replay, network, clone, or authority field named by "
            "the invariant to remain absent, false, or disjoint as declared."
        ),
        "EXACT_NAMED_PREDICATE_V1": (
            "Dispatch only this exact invariant_id, resolve all artifact, "
            "dependency, and evidence inputs, and require every quantified "
            "subject named by the invariant to satisfy the stated predicate."
        ),
    }
    contract: dict[str, Any] = {
        "algorithm_id": f"INVARIANT-{_safe_id(invariant_id)}-V1",
        "algorithm_version": "1.0",
        "algorithm": family,
        "input_refs": input_refs,
        "target_ref": target_ref,
        "canonicalization": (
            "UTF8_JSON_SORT_KEYS_COMPACT_SEPARATORS_PRESERVE_ARRAY_ORDER_V1"
        ),
        "ordering": (
            "DECLARED_ARRAY_ORDER_EXCEPT_SET_COMPARISONS_USE_SORTED_UNIQUE_UTF8"
        ),
        "numeric_tolerance": {"mode": "EXACT_DECIMAL_FROM_JSON"},
        "branch_precondition": recipe.get(
            "required_base_branch", "ANY_JSON_SCHEMA_VALID_BRANCH"
        ),
        "decision_rule": decision_rules[family],
        "failure_code": f"INVARIANT_{_safe_id(invariant_id).replace('-', '_')}_FAILED",
        "parameters": {},
    }
    explicit_specs: dict[str, dict[str, Any]] = {
        "AUTHORING_FIELDS_DESCRIBE_THE_IMMUTABLE_CANDIDATE_HANDOFF_NOT_CURRENT_RUNTIME_STATE": {
            "algorithm": "AUTHORING_HANDOFF_STATE_V1",
            "input_refs": [
                target_ref,
                "/authoring_state",
                "/authoring_workpack_started",
                "/authoring_driver_started",
                "/authoring_harness_started",
                "/authoring_model_downloaded",
                "/authoring_media_rendered",
            ],
            "decision_rule": (
                "Require authoring_state to name the immutable Candidate handoff, "
                "authoring_execution_mode to equal AUTHORING_ONLY, and every "
                "authoring execution flag to be false."
            ),
        },
        "DEMO_INPUT_AND_OUTPUT_BYTES_ARE_DISTINCT": {
            "algorithm": "CANONICAL_VALUE_INEQUALITY_V1",
            "input_refs": [target_ref, "/input_before_sha256"],
            "decision_rule": (
                "Require input_before_sha256 and output_after_sha256 to be "
                "different lowercase SHA-256 digests after both referenced byte "
                "hashes have independently verified."
            ),
        },
        "DEMO_EFFECT_DELTA_CONTAINS_OBSERVED_STATE_CHANGE": {
            "algorithm": "DEMO_OBSERVED_DELTA_V1",
            "input_refs": [target_ref, "/effect_delta"],
            "decision_rule": (
                "Require at least one effect_delta member with observed_change "
                "true and canonically unequal before_value and after_value."
            ),
        },
        "DENIED_TARGET_SKILL_GATE_HAS_NO_AUTHORIZATION_OR_SIDE_EFFECT_ATTEMPT": {
            "algorithm": "DENIED_GATE_ZERO_SIDE_EFFECT_V1",
            "input_refs": [
                target_ref,
                "/status",
                "/authorization_ref",
                "/execution_receipt_ref",
                "/side_effects_started",
            ],
            "branch_precondition": "DENIED_NO_SIDE_EFFECT",
            "decision_rule": (
                "On the DENIED_NO_SIDE_EFFECT branch require empty attempted "
                "side-effect IDs, false side_effects_started, and null "
                "authorization and execution receipt references."
            ),
        },
        "EVERY_CLAIM_HAS_FUNCTION_SCENARIO_EFFECT_AND_SOURCE_EVIDENCE": {
            "algorithm": "CLAIM_SEMANTIC_COMPLETENESS_V1",
            "input_refs": [target_ref, "/claims"],
            "decision_rule": (
                "For every claim require non-empty function, trigger_scenario, "
                "effect, inputs, outputs, and source_refs, then resolve every "
                "source_ref to exactly one hash-verified Source Freeze member."
            ),
        },
        "EVERY_INVARIANT_MUTATION_PRESERVES_JSON_SCHEMA_AND_FAILS_DECLARED_INVARIANT": {
            "algorithm": "INVARIANT_COUNTEREXAMPLE_REPLAY_V1",
            "input_refs": [
                target_ref,
                "/invariant_negative_case_results",
                "candidate://validation/ORACLE_EVALUATOR_REGISTRY.json",
            ],
            "decision_rule": (
                "For every registry invariant and applicable schema Hash require "
                "a passing base instance; apply the bound mutation; require JSON "
                "Schema PASS, exactly the declared invariant FAIL, all other "
                "invariants PASS, and zero side effects."
            ),
        },
        "EVERY_MOTION_SEGMENT_HAS_DISTINCT_FROM_AND_TO_STATE": {
            "algorithm": "MOTION_STATE_VECTOR_INEQUALITY_V1",
            "input_refs": [
                target_ref,
                "/shots/*/objects/*/motion_segments/*/from_state",
                "/shots/*/objects/*/motion_segments/*/to_state",
            ],
            "decision_rule": (
                "For every motion segment compare canonical vectors "
                "[x,y,scale,rotation_degrees,opacity] and require at least one "
                "component to differ exactly."
            ),
        },
        "EVERY_NEGATIVE_RESULT_OBSERVES_EXPECTED_FAILURE_WITHOUT_SIDE_EFFECTS": {
            "algorithm": "NEGATIVE_RESULT_EXACT_FAILURE_V1",
            "input_refs": [
                target_ref,
                "/negative_case_results",
                "candidate://validation/NEGATIVE_CASES.json",
            ],
            "decision_rule": (
                "Join results to Cases by case_id; require observed failure code "
                "equal expected_failure, expected_failure_observed true, every "
                "variant PASS, and all side_effects_started values false."
            ),
        },
        "EVERY_SCHEMA_NATIVE_MUTATION_FAILS_SCHEMA_WITHOUT_ORACLE_OR_SIDE_EFFECTS": {
            "algorithm": "SCHEMA_NATIVE_REJECTION_REPLAY_V1",
            "input_refs": [
                target_ref,
                "/schema_native_negative_case_results",
                "candidate://validation/ORACLE_EVALUATOR_REGISTRY.json",
            ],
            "decision_rule": (
                "For every schema-native Case and applicable schema Hash require "
                "the mutation to produce JSON Schema FAIL, oracle NOT_RUN_SCHEMA_"
                "REJECTED, expected failure ARTIFACT_SCHEMA_REJECTED, and zero "
                "side effects."
            ),
        },
        "EVERY_SPOKEN_SENTENCE_HAS_VISIBLE_OBJECT_DURING_BOUND_AUDIO_ANCHOR": {
            "algorithm": "SENTENCE_OBJECT_VISIBILITY_INTERVAL_V1",
            "input_refs": [
                target_ref,
                "/shots/*/objects",
                "dependency://AUDIO_ALIGNMENT_RECEIPT/word_anchors",
            ],
            "numeric_tolerance": {
                "mode": "ABSOLUTE",
                "absolute_seconds": 0.001,
            },
            "decision_rule": (
                "For each narration sentence resolve its word-anchor interval and "
                "require at least one object bound to that sentence and anchor "
                "whose [enter_time,exit_time] intersection with the anchor "
                "interval is greater than 0.001 seconds and whose opacity is "
                "positive in the intersecting segment."
            ),
        },
        "EVERY_VERIFIED_CLAIM_IS_COVERED_BY_AT_LEAST_ONE_SENTENCE": {
            "algorithm": "VERIFIED_CLAIM_SENTENCE_COVERAGE_V1",
            "input_refs": [
                target_ref,
                "/sentences/*/claim_ids",
                "dependency://FUNCTION_SCENARIO_EFFECT_MATRIX/claims/*/claim_id",
            ],
            "decision_rule": (
                "Require the exact set of verified claim IDs from the same-Job "
                "claim matrix to be a subset of the union of sentence claim_ids."
            ),
        },
        "FIRST_SHOT_STARTS_AT_ZERO": {
            "algorithm": "EXACT_DECIMAL_EQUALITY_V1",
            "input_refs": [target_ref],
            "decision_rule": "Require shots[0].start_seconds to equal decimal 0 exactly.",
        },
        "ILLUSTRATION_IS_EXPLICITLY_LABELED_AND_NOT_ACTUAL_SKILL_OUTPUT": {
            "algorithm": "ILLUSTRATION_PROVENANCE_BRANCH_V1",
            "input_refs": [
                target_ref,
                "/provenance_state",
                "/actual_skill_output",
                "/target_skill_execution_receipt_ref",
            ],
            "branch_precondition": "CLEARLY_LABELED_ILLUSTRATION",
            "decision_rule": (
                "On the illustration branch require a non-empty illustration "
                "label, actual_skill_output false, and null target execution "
                "receipt and authorization references."
            ),
        },
        "STAGE_ID_AND_INDEX_MATCH_FROZEN_STAGE_EXPECTATION": {
            "algorithm": "FROZEN_STAGE_POSITION_V1",
            "input_refs": [target_ref, "/stage_index"],
            "decision_rule": (
                "Resolve the artifact expected_stage_id and expected_stage_index; "
                "require exact equality to stage_id and stage_index and require "
                "the same position in the frozen 12-stage order."
            ),
            "parameters": {"stage_order": list(RESUMABLE_STAGE_ORDER)},
        },
        "TARGET_EXECUTION_AUTHORIZATION_IS_CURRENT_SINGLE_USE_AND_NOT_PROGRAM_WIDE": {
            "algorithm": "TARGET_AUTHORIZATION_SCOPE_V1",
            "input_refs": [
                target_ref,
                "/authorization_scope",
                "/authorization_consumed",
                "/authorized_job_id",
                "/current_input_manifest_sha256",
            ],
            "branch_precondition": "AUTHORIZED_EXECUTION_RECEIPT_VALID",
            "decision_rule": (
                "Require CURRENT freshness, unconsumed single-use authorization, "
                "scope EXACT_JOB_COMMIT_AND_INPUT_MANIFEST, and exact Job, commit, "
                "input, environment, and output bindings; reject PROGRAM_WIDE."
            ),
        },
        "TTS_EXECUTION_MODE_IS_LOCAL_OFFLINE": {
            "algorithm": "EXACT_SCALAR_CONST_V1",
            "input_refs": [target_ref],
            "decision_rule": "Require execution_mode to equal LOCAL_OFFLINE exactly.",
            "parameters": {"expected": "LOCAL_OFFLINE"},
        },
        "VIDEO_BYTES_INCLUDE_THE_REFERENCED_AUDIO_STREAM": {
            "algorithm": "VIDEO_AUDIO_STREAM_BYTE_BINDING_V1",
            "input_refs": [
                target_ref,
                "/video_ref",
                "/video_sha256",
                "/audio_sha256",
                "/render_command_receipt_ref",
            ],
            "decision_rule": (
                "Probe the hash-verified final video bytes, require at least one "
                "audio stream, demux the selected stream without transcoding, and "
                "require its canonical packet-payload SHA-256 to equal the "
                "referenced audio stream digest; the boolean field alone is not evidence."
            ),
            "parameters": {
                "probe": "FFPROBE_JSON",
                "demux": "FFMPEG_COPY_NO_TRANSCODE",
                "stream_selection": "FIRST_DEFAULT_AUDIO_ELSE_LOWEST_AUDIO_INDEX",
            },
        },
    }
    if invariant_id in explicit_specs:
        contract.update(deepcopy(explicit_specs[invariant_id]))
    if invariant_id == (
        "NARRATION_BUDGET_ESTIMATE_MATCHES_CANONICAL_SENTENCE_ARRAY_AND_METHOD"
    ):
        contract.update(
            {
                "algorithm": "MANDARIN_CHARACTER_RATE_V1",
                "input_refs": [
                    target_ref,
                    "/sentences/*/text",
                    "/narration_budget_method",
                ],
                "numeric_tolerance": {
                    "mode": "ABSOLUTE",
                    "absolute_seconds": 0.001,
                },
                "decision_rule": (
                    "NFKC-normalize sentence text in declared order; count each "
                    "Unicode letter or number as one spoken unit; add the fixed "
                    "pause for each punctuation code point; compute units/4.2 + "
                    "pause_seconds and round half-up to 3 decimals; require exact "
                    "agreement within 0.001 seconds."
                ),
                "parameters": {
                    "unicode_normalization": "NFKC",
                    "spoken_unit_categories": ["L*", "N*"],
                    "spoken_units_per_second": 4.2,
                    "punctuation_pause_seconds": {
                        "，": 0.18,
                        "、": 0.18,
                        "：": 0.18,
                        "；": 0.18,
                        "。": 0.35,
                        "！": 0.35,
                        "？": 0.35,
                        "\n": 0.25,
                    },
                    "rounding": "ROUND_HALF_UP_3_DECIMALS",
                },
            }
        )
    elif invariant_id == "RENDER_TRACE_SAMPLES_MATCH_DECLARED_OBJECT_CURVES":
        contract.update(
            {
                "algorithm": "OBJECT_CURVE_FRAME_SAMPLING_V1",
                "input_refs": [
                    target_ref,
                    "/render_trace_ref",
                    "dependency://OBJECT_MOTION_IR/shots/*/objects/*/motion_segments",
                ],
                "numeric_tolerance": {
                    "mode": "ABSOLUTE_PER_COMPONENT",
                    "position_pixels": 0.01,
                    "scale": 0.0001,
                    "rotation_degrees": 0.01,
                    "opacity": 0.0001,
                },
                "decision_rule": (
                    "At every integer 30-fps frame whose timestamp intersects a "
                    "motion segment, compute normalized segment progress, apply "
                    "the declared easing and loop_count, interpolate every motion "
                    "state component, and compare it with the trace sample using "
                    "the declared per-component absolute tolerances; require exact "
                    "object_id, segment_id, curve_id, frame, and sample coverage."
                ),
                "parameters": {
                    "sample_rate_fps": 30,
                    "timestamp_rule": "FRAME_INDEX_DIVIDED_BY_30",
                    "segment_inclusion": "START_INCLUSIVE_END_INCLUSIVE",
                    "loop_progress": (
                        "MIN_1_OF_FRACTIONAL_PART_PROGRESS_TIMES_LOOP_COUNT_"
                        "WITH_SEGMENT_END_FORCED_TO_1"
                    ),
                    "state_components": [
                        "x",
                        "y",
                        "scale",
                        "rotation_degrees",
                        "opacity",
                    ],
                    "easing_functions": {
                        "LINEAR": "u",
                        "EASE_IN": "u^2",
                        "EASE_OUT": "1-(1-u)^2",
                        "EASE_IN_OUT": (
                            "u<0.5 ? 2*u^2 : 1-2*(1-u)^2"
                        ),
                        "SPRING": (
                            "(1-exp(-6*u)*cos(8*pi*u))/(1-exp(-6)*cos(8*pi))"
                        ),
                    },
                    "interpolation": "FROM_PLUS_EASED_U_TIMES_TO_MINUS_FROM",
                },
            }
        )
    return contract


def _bind_invariant_evaluation_contracts(schema: dict[str, Any]) -> None:
    invariants = [
        str(value)
        for value in schema.get("x-invariants", [])
        if isinstance(value, str) and value
    ]
    declared = schema.get("x-invariant-contracts")
    declared = declared if isinstance(declared, Mapping) else {}
    contracts: dict[str, Any] = {}
    for invariant_id in invariants:
        contract = _invariant_evaluation_contract(invariant_id)
        existing = declared.get(invariant_id)
        if isinstance(existing, Mapping):
            contract.update(deepcopy(dict(existing)))
        contracts[invariant_id] = contract
    schema["x-invariant-contracts"] = contracts


def schema_invariant_contracts_are_complete(schema: Any) -> bool:
    """Return whether every x-invariant has one executable exact contract."""

    if not isinstance(schema, Mapping):
        return False
    invariants = {
        str(value)
        for value in schema.get("x-invariants", [])
        if isinstance(value, str) and value
    }
    contracts = schema.get("x-invariant-contracts")
    if not isinstance(contracts, Mapping) or set(contracts) != invariants:
        return False
    for invariant_id, contract in contracts.items():
        if (
            not isinstance(contract, Mapping)
            or not INVARIANT_CONTRACT_REQUIRED_FIELDS.issubset(contract)
            or contract.get("target_ref")
            != _INVARIANT_MUTATION_TARGETS.get(str(invariant_id))
            or not isinstance(contract.get("input_refs"), list)
            or not contract["input_refs"]
            or contract["input_refs"][0] != contract.get("target_ref")
            or not all(
                isinstance(contract.get(field), str) and contract.get(field)
                for field in (
                    "algorithm_id",
                    "algorithm_version",
                    "algorithm",
                    "canonicalization",
                    "ordering",
                    "branch_precondition",
                    "decision_rule",
                    "failure_code",
                )
            )
            or not isinstance(contract.get("numeric_tolerance"), Mapping)
        ):
            return False
    return True


def _safe_id(value: str) -> str:
    return "".join(
        character if character.isalnum() else "-"
        for character in value.upper()
    ).strip("-")


def case_result_ref(case_kind: str, case_id: str) -> str:
    """Return the single owned aggregate result ref for a frozen Case."""

    return (
        f"{CASE_EXECUTION_RESULT_ROOT_REF}/"
        f"{case_kind.lower()}-{_safe_id(case_id).lower()}.result.json"
    )


def registry_case_result_ref(
    case_kind: str, case_id: str, schema_sha256: str
) -> str:
    """Return one deterministic registry-mutation result per schema instance."""

    return (
        f"{CASE_EXECUTION_RESULT_ROOT_REF}/registry/"
        f"{case_kind.lower()}-{_safe_id(case_id).lower()}/"
        f"{schema_sha256}.result.json"
    )


def registry_case_result_refs(registry: Mapping[str, Any]) -> list[str]:
    """Project every invariant/schema-native replay into an exact result ref."""

    refs: list[str] = []
    for matrix_field, case_kind in (
        ("invariant_negative_case_matrix", "INVARIANT"),
        ("schema_native_negative_case_matrix", "SCHEMA_NATIVE"),
    ):
        for case in registry.get(matrix_field, []):
            if not isinstance(case, Mapping) or not case.get("case_id"):
                continue
            for schema_sha256 in case.get("applicable_schema_sha256s", []):
                if not isinstance(schema_sha256, str) or not schema_sha256:
                    continue
                refs.append(
                    registry_case_result_ref(
                        case_kind,
                        str(case["case_id"]),
                        schema_sha256,
                    )
                )
    return sorted(dict.fromkeys(refs))


def required_artifact_kinds_for_case(case: Mapping[str, Any]) -> list[str]:
    """Return explicit terminal evidence closure for a frozen acceptance Case."""

    kinds = [
        str(value)
        for value in case.get("required_artifact_kinds", [])
        if isinstance(value, str) and value
    ]
    if str(case.get("evidence_type") or "") in TERMINAL_TIMING_EVIDENCE_TYPES:
        for kind in (
            "LOCAL_TTS_RECEIPT",
            "AUDIO_ALIGNMENT_RECEIPT",
            "OBJECT_MOTION_IR",
            "MEDIA_ACCEPTANCE_RECEIPT",
        ):
            if kind not in kinds:
                kinds.append(kind)
    return kinds


def repository_job_bindings(
    requirement_ir: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Derive the fixed one-repository/one-job identities used by all producers."""

    jobs: list[dict[str, str]] = []
    for source in requirement_ir.get("sources", []):
        if not isinstance(source, Mapping) or not source.get("repository_url"):
            continue
        source_id = str(source.get("source_id") or "")
        jobs.append(
            {
                "job_id": f"FIXTURE-JOB-{_safe_id(source_id)}",
                "source_id": source_id,
                "repository_url": str(source["repository_url"]),
                "revision": str(source.get("revision") or ""),
                "commit_sha": str(source.get("commit_sha") or ""),
                "git_tree_oid": str(source.get("git_tree_oid") or ""),
                "tree_sha256": str(
                    source.get("tree_sha256") or source.get("sha256") or ""
                ),
                "license_spdx": str(source.get("license_spdx") or ""),
            }
        )
    return jobs


def public_skill_job_interface(
    requirement_ir: Mapping[str, Any],
) -> dict[str, Any]:
    """Declare a reusable one-public-Skill-URL/one-video Job interface."""

    frozen_fixtures = repository_job_bindings(requirement_ir)
    frozen_urls = {item["repository_url"] for item in frozen_fixtures}
    sample_url = "https://github.com/harness-foundry/nonfixture-skill"
    suffix = 1
    while sample_url in frozen_urls:
        suffix += 1
        sample_url = (
            "https://github.com/harness-foundry/"
            f"nonfixture-skill-{suffix}"
        )
    sample_request = {
        "request_id": "METAMORPHIC-PUBLIC-SKILL-URL-001",
        "skill_url": sample_url,
        "requested_revision": "main",
        "language": "zh-CN",
        "duration_target_seconds": 180,
        "output_video_count": 1,
        "target_skill_execution_enabled": False,
    }
    identity_payload = {
        "skill_url": sample_request["skill_url"],
        "requested_revision": sample_request["requested_revision"],
    }
    identity_sha256 = hashlib.sha256(
        json.dumps(
            identity_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    target = requirement_ir.get("target")
    catalog = (
        target.get("artifact_schema_catalog", {})
        if isinstance(target, Mapping)
        else {}
    )
    template_bindings = sorted(
        [
            {
                "atom_id": str(atom_id),
                "artifact_kind": str(profile.get("artifact_kind") or ""),
                "schema_sha256": hashlib.sha256(
                    json.dumps(
                        profile.get("schema"),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
            }
            for atom_id, profile in (
                catalog.items() if isinstance(catalog, Mapping) else []
            )
            if isinstance(profile, Mapping)
            and isinstance(profile.get("schema"), Mapping)
        ],
        key=lambda item: (item["atom_id"], item["artifact_kind"]),
    )
    interface = {
        "schema_version": "1.0",
        "interface_id": "PUBLIC-SKILL-URL-TO-VIDEO-JOB-V1",
        "status": "DECLARE_ONLY_NOT_RUN",
        "execution_started": False,
        "job_request_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"{PUBLIC_SKILL_JOB_INTERFACE_REF}#/job_request_schema",
            "type": "object",
            "additionalProperties": False,
            "required": list(sample_request),
            "properties": {
                "request_id": {"type": "string", "minLength": 1},
                "skill_url": {
                    "type": "string",
                    "pattern": (
                        "^https://github\\.com/[A-Za-z0-9_.-]+/"
                        "[A-Za-z0-9_.-]+(?:\\.git)?/?$"
                    ),
                },
                "requested_revision": {
                    "type": "string",
                    "minLength": 1,
                },
                "language": {"const": "zh-CN"},
                "duration_target_seconds": {
                    "type": "number",
                    "minimum": 175,
                    "maximum": 185,
                },
                "output_video_count": {"const": 1},
                "target_skill_execution_enabled": {"const": False},
            },
        },
        "dynamic_specialization_contract": {
            "algorithm_id": "PUBLIC-SKILL-JOB-SPECIALIZATION-V1",
            "job_id_derivation": "SHA256_CANONICAL_JOB_REQUEST_PREFIX_16",
            "job_identity_fields": ["skill_url", "requested_revision"],
            "url_normalization": (
                "HTTPS_GITHUB_HOST_LOWERCASE_STRIP_TRAILING_SLASH_AND_DOT_GIT_"
                "PRESERVE_OWNER_REPOSITORY_CASE"
            ),
            "source_freeze_required_before_content_analysis": True,
            "source_commit_resolution": (
                "RESOLVE_REQUESTED_REVISION_THEN_BIND_EXACT_COMMIT_TREE_AND_"
                "CONTENT_SHA256"
            ),
            "schema_template_bindings": template_bindings,
            "schema_binding_rule": (
                "DEEP_COPY_GENERIC_TEMPLATE_THEN_BIND_ONLY_JOB_SOURCE_PIN_AND_"
                "PINNED_RENDERER_FIELDS"
            ),
            "one_input_skill_per_job": True,
            "one_independent_video_output_per_job": True,
            "frozen_fixture_urls_must_not_be_schema_const_or_enum": True,
        },
        "frozen_certification_fixtures": frozen_fixtures,
        "metamorphic_acceptance_vector": {
            "case_id": "AC-PUBLIC-SKILL-URL-NOT-IN-FROZEN-FIXTURES",
            "input": sample_request,
            "preconditions": [
                "SKILL_URL_NOT_IN_FROZEN_CERTIFICATION_FIXTURES",
                "PUBLIC_GITHUB_REPOSITORY_IS_READABLE_AT_EXECUTION_TIME",
            ],
            "steps": [
                "VALIDATE_JOB_REQUEST_SCHEMA",
                "NORMALIZE_URL_AND_RESOLVE_REQUESTED_REVISION",
                "DERIVE_ONE_JOB_ID_AND_BIND_GENERIC_ARTIFACT_SCHEMAS",
                "REQUIRE_ONE_INDEPENDENT_VIDEO_OUTPUT_CONTRACT",
            ],
            "expected": {
                "input_skill_count": 1,
                "output_video_count": 1,
                "job_id_derivation": (
                    "SHA256_CANONICAL_JOB_REQUEST_PREFIX_16"
                ),
                "expected_job_id": f"JOB-{identity_sha256[:16].upper()}",
                "source_is_frozen_before_analysis": True,
                "target_skill_execution_enabled": False,
            },
            "oracle": {
                "algorithm_id": "PUBLIC-SKILL-JOB-METAMORPHIC-ORACLE-V1",
                "decision_rule": (
                    "PASS_ONLY_IF_THE_UNLISTED_SCHEMA_VALID_URL_PRODUCES_EXACTLY_"
                    "ONE_DISTINCT_JOB_ID_ONE_DYNAMIC_SCHEMA_BINDING_SET_AND_ONE_"
                    "VIDEO_OUTPUT_WITHOUT_MATCHING_ANY_FROZEN_FIXTURE_URL"
                ),
                "side_effects_allowed_during_authoring": False,
            },
            "status": "PLANNED_NOT_RUN",
        },
    }
    interface["interface_sha256"] = hashlib.sha256(
        json.dumps(
            interface,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return interface


def _artifact_evaluator_id(artifact_kind: str) -> str:
    return f"{_safe_id(artifact_kind)}_ORACLE_V1"


def _schema_declares_json_pointer(
    schema: Mapping[str, Any], pointer: str
) -> bool:
    return _schema_at_json_pointer(schema, pointer) is not None


def _schema_at_json_pointer(
    schema: Mapping[str, Any], pointer: str
) -> Mapping[str, Any] | None:
    current: Any = schema
    for token in pointer.removeprefix("/").split("/"):
        if not isinstance(current, Mapping):
            return None
        if token.isdigit():
            current = current.get("items")
            continue
        properties = current.get("properties")
        if not isinstance(properties, Mapping) or token not in properties:
            return None
        current = properties[token]
    return current if isinstance(current, Mapping) else None


def oracle_evaluator_registry(
    additional_artifact_kinds: set[str] | None = None,
    artifact_contracts: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the exact evaluator interfaces the external Lab must implement."""

    schemas_by_kind: dict[str, dict[str, Mapping[str, Any]]] = {}
    for artifact in artifact_contracts or []:
        if not isinstance(artifact, Mapping):
            continue
        kind = str(artifact.get("artifact_kind") or "")
        schema = artifact.get("schema")
        if not kind or not isinstance(schema, Mapping):
            continue
        schema_sha256 = hashlib.sha256(
            json.dumps(
                schema,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        schemas_by_kind.setdefault(kind, {})[schema_sha256] = schema
    kinds = sorted(
        JOB_SCOPED_ARTIFACT_KINDS
        | {"FIXTURE_ACCEPTANCE_RECEIPT"}
        | set(additional_artifact_kinds or set())
    )
    evaluators: dict[str, Any] = {}
    invariant_negative_case_matrix: list[dict[str, Any]] = []
    schema_native_negative_case_matrix: list[dict[str, Any]] = []
    for invariant_id, case in sorted(_SCHEMA_NATIVE_INVARIANT_CASES.items()):
        kind = str(case["artifact_kind"])
        applicable = sorted(schemas_by_kind.get(kind, {}))
        if not applicable:
            continue
        schema_native_negative_case_matrix.append(
            {
                "case_id": f"NEG-SCHEMA-{_safe_id(kind)}-{_safe_id(invariant_id)}",
                "artifact_kind": kind,
                "constraint_id": invariant_id,
                "applicable_schema_sha256s": applicable,
                "mutation": {
                    "operation": case["operation"],
                    "target_ref": case["target_ref"],
                    "post_mutation_json_schema_expected": "FAIL",
                    "post_mutation_oracle_expected": "NOT_RUN_SCHEMA_REJECTED",
                },
                "expected_failure": "ARTIFACT_SCHEMA_REJECTED",
                "side_effects_allowed": False,
            }
        )
    for kind in kinds:
        invariant_ids = sorted(
            {
                str(invariant)
                for schema in schemas_by_kind.get(kind, {}).values()
                for invariant in schema.get("x-invariants", [])
                if isinstance(invariant, str) and invariant
            }
        )
        negative_case_ids = []
        evaluator_invariant_contracts: dict[str, Any] = {}
        for invariant_id in invariant_ids:
            target_ref = _INVARIANT_MUTATION_TARGETS.get(invariant_id)
            if target_ref is None:
                raise ValueError(
                    "machine-applicable invariant mutation is missing for "
                    f"{kind}:{invariant_id}"
                )
            contract_variants: dict[str, Mapping[str, Any]] = {}
            for current_schema in schemas_by_kind.get(kind, {}).values():
                if not schema_invariant_contracts_are_complete(current_schema):
                    raise ValueError(
                        "executable invariant contract set is incomplete for "
                        f"{kind}:{invariant_id}"
                    )
                contract = current_schema["x-invariant-contracts"].get(
                    invariant_id
                )
                if not isinstance(contract, Mapping):
                    raise ValueError(
                        "executable invariant contract is missing for "
                        f"{kind}:{invariant_id}"
                    )
                contract_sha256 = hashlib.sha256(
                    json.dumps(
                        contract,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                contract_variants[contract_sha256] = contract
            if len(contract_variants) != 1:
                raise ValueError(
                    "invariant contract differs across schema instances for "
                    f"{kind}:{invariant_id}"
                )
            invariant_contract_sha256, invariant_contract = next(
                iter(contract_variants.items())
            )
            evaluator_invariant_contracts[invariant_id] = deepcopy(
                dict(invariant_contract)
            )
            missing_target_schemas = [
                schema_sha256
                for schema_sha256, schema in schemas_by_kind.get(kind, {}).items()
                if not _schema_declares_json_pointer(schema, target_ref)
            ]
            if missing_target_schemas:
                raise ValueError(
                    "invariant mutation target is not declared by every schema "
                    f"instance for {kind}:{invariant_id}:{missing_target_schemas}"
                )
            case_id = f"NEG-INV-{_safe_id(kind)}-{_safe_id(invariant_id)}"
            negative_case_ids.append(case_id)
            mutation_recipe = _invariant_mutation_recipe(invariant_id)
            schema_instances = []
            for schema_sha256, current_schema in sorted(
                schemas_by_kind.get(kind, {}).items()
            ):
                target_schema = _schema_at_json_pointer(
                    current_schema, target_ref
                )
                if target_schema is None:
                    raise ValueError(
                        f"missing target schema for {kind}:{invariant_id}"
                    )
                if "const" in target_schema:
                    raise ValueError(
                        "invariant mutation target is fixed by JSON Schema and "
                        "cannot prove the x-invariant independently for "
                        f"{kind}:{invariant_id}:{schema_sha256}"
                    )
                schema_instances.append(
                    {
                        "schema_sha256": schema_sha256,
                        "target_schema_sha256": hashlib.sha256(
                            json.dumps(
                                target_schema,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        ).hexdigest(),
                        "counterexample_replay_required": True,
                        "counterexample_proof_status": (
                            "NOT_CLAIMED_UNTIL_EXTERNAL_LAB_REPLAY"
                        ),
                    }
                )
            invariant_negative_case_matrix.append(
                {
                    "case_id": case_id,
                    "artifact_kind": kind,
                    "evaluator_id": _artifact_evaluator_id(kind),
                    "invariant_id": invariant_id,
                    "invariant_contract": deepcopy(dict(invariant_contract)),
                    "invariant_contract_sha256": invariant_contract_sha256,
                    "applicable_schema_sha256s": sorted(
                        schemas_by_kind.get(kind, {})
                    ),
                    "apply_to_every_schema_instance": True,
                    "base_precondition": {
                        "artifact_schema": "PASS",
                        "artifact_oracle": "PASS",
                        "required_branch": mutation_recipe.get(
                            "required_base_branch", "ANY_PASSING_BRANCH"
                        ),
                    },
                    "mutation": {
                        "operation": "DERIVE_VALUE_FROM_PASSING_BASE",
                        "target_ref": target_ref,
                        "derivation_recipe": mutation_recipe,
                        "schema_instances": schema_instances,
                        "post_mutation_json_schema_expected": "PASS",
                        "post_mutation_oracle_expected": "FAIL",
                        "post_mutation_failed_invariant_ids": [invariant_id],
                        "all_other_invariant_ids_expected": "PASS",
                        "proof_status": "REQUIRES_EXTERNAL_LAB_REPLAY",
                        "failure_if_counterexample_not_found": (
                            "EXACT_COUNTEREXAMPLE_NOT_FOUND"
                        ),
                        "violated_constraint": {"x-invariant": invariant_id},
                    },
                    "expected_failure": "ARTIFACT_INVARIANT_REJECTED",
                    "side_effects_allowed": False,
                }
            )
        evaluators[_artifact_evaluator_id(kind)] = {
            "artifact_kind": kind,
            "implementation_entrypoint": (
                "external_lab.evaluators:evaluate_" + kind.lower()
            ),
            "decision_rule": (
                "LOAD_REFERENCED_BYTES_VALIDATE_JSON_SCHEMA_RECOMPUTE_X_INVARIANTS_"
                "AND_REJECT_ON_MISSING_EVIDENCE"
            ),
            "required_inputs": [
                "ARTIFACT_BYTES",
                "FROZEN_ARTIFACT_SCHEMA",
                "ARTIFACT_OBLIGATION_MANIFEST_BYTES",
                "DEPENDENCY_BYTES",
                "EVIDENCE_BYTES",
            ],
            "invariant_source": "ARTIFACT_SCHEMA_X_INVARIANTS",
            "invariant_contracts": evaluator_invariant_contracts,
            "invariant_contracts_sha256": hashlib.sha256(
                json.dumps(
                    evaluator_invariant_contracts,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            "declared_invariant_count": len(invariant_ids),
            "invariant_negative_case_ids": negative_case_ids,
            "negative_fixture_contract": (
                "EACH_DECLARED_INVARIANT_HAS_A_MACHINE_APPLICABLE_FAILING_MUTATION"
            ),
        }
    evaluators["EXACT_CASE_SET_ORACLE_V1"] = {
        "artifact_kind": "CASE_RESULT",
        "implementation_entrypoint": "external_lab.oracle:evaluate_case_oracle",
        "decision_rule": (
            "RECOMPUTE_FIXTURE_HASH_AND_REQUIRE_EXACT_ASSERTION_ARTIFACT_AND_"
            "SOURCE_JOB_SETS_BEFORE_PASS"
        ),
        "required_inputs": [
            "CASE_FIXTURE_BYTES",
            "CASE_RESULT_BYTES",
            "CASE_RESULT_SCHEMA_BYTES",
            "REFERENCED_EVIDENCE_BYTES",
        ],
        "negative_fixture_contract": (
            "DUPLICATE_OMITTED_OR_SUBSTITUTED_SET_MEMBER_MUST_FAIL"
        ),
    }
    registry = {
        "schema_version": "1.0",
        "registry_id": "ORACLE-EVALUATOR-REGISTRY-V1",
        "status": "DECLARE_ONLY_NOT_IMPLEMENTED_NOT_RUN",
        "execution_started": False,
        "evaluators": evaluators,
        "invariant_negative_case_matrix": invariant_negative_case_matrix,
        "schema_native_negative_case_matrix": (
            schema_native_negative_case_matrix
        ),
    }
    registry["registry_sha256"] = hashlib.sha256(
        json.dumps(
            registry,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return registry


def _bind_schema_to_job(
    schema: Mapping[str, Any],
    job: Mapping[str, str],
    artifact_kind: str,
    repository_jobs: list[Mapping[str, str]],
) -> dict[str, Any]:
    bound = deepcopy(dict(schema))
    properties = bound.setdefault("properties", {})
    _require_schema_fields(bound, ["job_id", "source_id"])
    properties["job_id"] = {"const": job["job_id"]}
    properties["source_id"] = {"const": job["source_id"]}
    if artifact_kind == "LOCAL_RENDER_RECEIPT":
        declared_repository = properties.get("repository_url")
        renderer_repository_url = (
            declared_repository.get("const")
            if isinstance(declared_repository, Mapping)
            else None
        )
        renderer = next(
            (
                item
                for item in repository_jobs
                if item.get("repository_url") == renderer_repository_url
            ),
            None,
        )
        if renderer is not None:
            renderer_fields = {
                "renderer_source_id": renderer.get("source_id"),
                "renderer_repository_url": renderer.get("repository_url"),
                "renderer_commit_sha": renderer.get("commit_sha"),
                "renderer_tree_sha256": renderer.get("tree_sha256"),
                "renderer_license_spdx": renderer.get("license_spdx"),
                # Preserve the original renderer fields for compatibility.
                "repository_url": renderer.get("repository_url"),
                "commit_sha": renderer.get("commit_sha"),
                "tree_sha256": renderer.get("tree_sha256"),
                "license_spdx": renderer.get("license_spdx"),
            }
            _require_schema_fields(bound, list(renderer_fields))
            for field, value in renderer_fields.items():
                if value:
                    properties[field] = {"const": value}
        content_fields = {
            "content_repository_url": job.get("repository_url"),
            "content_commit_sha": job.get("commit_sha"),
            "content_tree_sha256": job.get("tree_sha256"),
        }
        _require_schema_fields(bound, list(content_fields))
        for field, value in content_fields.items():
            if value:
                properties[field] = {"const": value}
    else:
        for field in (
            "repository_url",
            "commit_sha",
            "git_tree_oid",
            "tree_sha256",
        ):
            if field in properties and job.get(field):
                properties[field] = {"const": job[field]}
    if "exact_commit_sha" in properties and job.get("commit_sha"):
        properties["exact_commit_sha"] = {"const": job["commit_sha"]}
    if artifact_kind == "TARGET_SKILL_EXECUTION_GATE_RECEIPT":
        properties["target_skill_id"] = {"const": job["source_id"]}
    return bound


def _require_schema_fields(schema: dict[str, Any], fields: list[str]) -> None:
    required = schema.setdefault("required", [])
    if not isinstance(required, list):
        required = []
        schema["required"] = required
    for field in fields:
        if field not in required:
            required.append(field)


def _strengthen_artifact_schema(
    artifact_kind: str,
    declared_schema: Mapping[str, Any],
    repository_jobs: list[Mapping[str, str]] | None = None,
    acceptance_cases: list[Mapping[str, Any]] | None = None,
    negative_cases: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Add domain invariants that a field-name-only schema cannot enforce."""

    schema = deepcopy(dict(declared_schema))
    properties = schema.setdefault("properties", {})
    if not isinstance(properties, dict):
        return schema

    if artifact_kind == "SOURCE_FREEZE_RECEIPT":
        hash_schema = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
        _require_schema_fields(
            schema,
            [
                "repository_url",
                "commit_sha",
                "git_tree_oid",
                "tree_sha256",
                "license_spdx",
                "skill_entrypoint_ref",
                "frozen_file_refs",
                "frozen_file_sha256s",
                "claim_ids",
                "claim_bindings",
                "source_manifest_ref",
                "source_manifest_sha256",
                "license_evidence_ref",
                "license_evidence_sha256",
                "status",
            ],
        )
        for field in (
            "repository_url",
            "license_spdx",
            "skill_entrypoint_ref",
            "source_manifest_ref",
            "license_evidence_ref",
        ):
            properties.setdefault(field, {"type": "string", "minLength": 1})
        for field in ("commit_sha", "git_tree_oid"):
            properties[field] = {
                "type": "string",
                "pattern": "^[0-9a-f]{40}$",
            }
        properties["tree_sha256"] = deepcopy(hash_schema)
        for field in (
            "source_manifest_sha256",
            "license_evidence_sha256",
        ):
            properties[field] = deepcopy(hash_schema)
        properties["frozen_file_refs"] = {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
        }
        properties["frozen_file_sha256s"] = {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": deepcopy(hash_schema),
        }
        properties["claim_ids"] = {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
        }
        properties["claim_bindings"] = {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "claim_id",
                    "source_ref",
                    "source_sha256",
                    "source_locator",
                ],
                "properties": {
                    "claim_id": {"type": "string", "minLength": 1},
                    "source_ref": {"type": "string", "minLength": 1},
                    "source_sha256": deepcopy(hash_schema),
                    "source_locator": {"type": "string", "minLength": 1},
                },
            },
        }
        schema["additionalProperties"] = False
        schema["x-invariants"] = [
            "FROZEN_FILE_REFS_AND_HASHES_HAVE_EQUAL_CARDINALITY",
            "EVERY_FROZEN_FILE_HASH_MATCHES_REFERENCED_BYTES",
            "EVERY_CLAIM_BINDING_RESOLVES_TO_FROZEN_FILE_AND_MATCHES_HASH",
            "LICENSE_SPDX_MATCHES_HASHED_LICENSE_EVIDENCE",
            "SOURCE_MANIFEST_ENTRY_MATCHES_REPOSITORY_COMMIT_AND_TREE",
        ]

    elif artifact_kind == "FUNCTION_SCENARIO_EFFECT_MATRIX":
        if "claims" not in properties:
            claim_properties = deepcopy(properties)
            claim_required = [
                str(value)
                for value in schema.get("required", [])
                if value not in {"job_id", "source_id", "status"}
            ]
            semantic_claim_fields = {
                "claim_id": {"type": "string", "minLength": 1},
                "function": {"type": "string", "minLength": 1},
                "user_role": {"type": "string", "minLength": 1},
                "trigger_scenario": {"type": "string", "minLength": 1},
                "inputs": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
                "outputs": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
                "effect": {"type": "string", "minLength": 1},
                "limitations": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
                "source_refs": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
                "narration_refs": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
                "visual_refs": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
            }
            for field, field_schema in semantic_claim_fields.items():
                claim_properties.setdefault(field, field_schema)
                if field not in claim_required:
                    claim_required.append(field)
            schema = {
                "type": "object",
                "additionalProperties": False,
                "required": ["claims", "claim_manifest_sha256", "status"],
                "properties": {
                    "claims": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": claim_required,
                            "properties": claim_properties,
                        },
                    },
                    "claim_manifest_sha256": {
                        "type": "string",
                        "pattern": "^[0-9a-f]{64}$",
                    },
                    "status": {"const": "PASS"},
                },
                "x-invariants": [
                    "EVERY_CLAIM_HAS_FUNCTION_SCENARIO_EFFECT_AND_SOURCE_EVIDENCE",
                    "CLAIM_IDS_ARE_UNIQUE",
                    "CLAIM_MANIFEST_SHA256_MATCHES_CANONICAL_CLAIM_ARRAY",
                ],
            }
            properties = schema["properties"]

    elif artifact_kind == "NARRATION_SCRIPT":
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "script_id",
                "language",
                "duration_target_seconds",
                "narration_budget_verified",
                "narration_budget_estimated_seconds",
                "narration_budget_method",
                "narration_budget_receipt_ref",
                "narration_budget_receipt_sha256",
                "duration_repair_count",
                "playback_speed",
                "truncation_applied",
                "sentences",
                "claim_manifest_sha256",
                "script_sha256",
                "status",
            ],
            "properties": {
                "script_id": {"type": "string", "minLength": 1},
                "language": {"const": "zh-CN"},
                "duration_target_seconds": {
                    "type": "number",
                    "minimum": 175,
                    "maximum": 185,
                },
                "narration_budget_verified": {"const": True},
                "narration_budget_estimated_seconds": {
                    "type": "number",
                    "minimum": 175,
                    "maximum": 185,
                },
                "narration_budget_method": {
                    "const": "MANDARIN_CHARACTER_RATE_V1"
                },
                "narration_budget_receipt_ref": {
                    "type": "string",
                    "minLength": 1,
                },
                "narration_budget_receipt_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "duration_repair_count": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 2,
                },
                "playback_speed": {"const": 1.0},
                "truncation_applied": {"const": False},
                "sentences": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "sentence_id",
                            "text",
                            "claim_ids",
                            "visual_intent_id",
                            "visual_intent",
                        ],
                        "properties": {
                            "sentence_id": {"type": "string", "minLength": 1},
                            "text": {"type": "string", "minLength": 1},
                            "claim_ids": {
                                "type": "array",
                                "minItems": 1,
                                "uniqueItems": True,
                                "items": {"type": "string", "minLength": 1},
                            },
                            "visual_intent_id": {
                                "type": "string",
                                "minLength": 1,
                            },
                            "visual_intent": {"type": "string", "minLength": 1},
                        },
                    },
                },
                "claim_manifest_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "script_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "status": {"const": "PASS"},
            },
            "x-invariants": [
                "EVERY_VERIFIED_CLAIM_IS_COVERED_BY_AT_LEAST_ONE_SENTENCE",
                "NARRATION_VISUAL_INTENT_IDS_ARE_UNIQUE",
                "SCRIPT_SHA256_MATCHES_CANONICAL_SENTENCE_ARRAY",
                "NARRATION_BUDGET_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES",
                "NARRATION_BUDGET_ESTIMATE_MATCHES_CANONICAL_SENTENCE_ARRAY_AND_METHOD",
            ],
        }
        properties = schema["properties"]

    elif artifact_kind == "LOCAL_TTS_RECEIPT":
        _require_schema_fields(
            schema,
            [
                "provider",
                "model_id",
                "model_artifact_ref",
                "model_sha256",
                "license_spdx",
                "provider_implementation_ref",
                "provider_implementation_sha256",
                "audio_ref",
                "audio_sha256",
                "provider_receipt_ref",
                "provider_receipt_sha256",
                "runtime_environment_ref",
                "runtime_environment_sha256",
                "license_evidence_ref",
                "license_evidence_sha256",
                "execution_mode",
                "network_accessed",
                "voice_cloned",
                "narration_script_ref",
                "narration_script_sha256",
                "transcript_ref",
                "transcript_sha256",
                "claim_coverage_sha256",
            ],
        )
        properties["provider"] = {"type": "string", "minLength": 1}
        properties["model_id"] = {"type": "string", "minLength": 1}
        properties["model_artifact_ref"] = {
            "type": "string",
            "minLength": 1,
        }
        properties["model_sha256"] = {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        }
        properties["license_spdx"] = {"type": "string", "minLength": 1}
        properties["provider_implementation_ref"] = {
            "type": "string",
            "minLength": 1,
        }
        properties["provider_implementation_sha256"] = {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        }
        properties["audio_ref"] = {"type": "string", "minLength": 1}
        properties["audio_sha256"] = {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        }
        properties["provider_receipt_ref"] = {
            "type": "string",
            "minLength": 1,
        }
        for field in (
            "runtime_environment_ref",
            "license_evidence_ref",
            "narration_script_ref",
            "transcript_ref",
        ):
            properties[field] = {"type": "string", "minLength": 1}
        for field in (
            "provider_receipt_sha256",
            "runtime_environment_sha256",
            "license_evidence_sha256",
            "narration_script_sha256",
            "transcript_sha256",
            "claim_coverage_sha256",
        ):
            properties[field] = {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            }
        properties["execution_mode"] = {
            "enum": ["LOCAL_OFFLINE", "REMOTE_API"]
        }
        properties["network_accessed"] = {"type": "boolean"}
        properties["voice_cloned"] = {"type": "boolean"}
        schema["x-invariants"] = [
            "AUDIO_SHA256_MATCHES_REFERENCED_AUDIO_BYTES",
            "NARRATION_SCRIPT_SHA256_MATCHES_REFERENCED_SCRIPT",
            "TRANSCRIPT_SHA256_MATCHES_SYNTHESIZED_AUDIO_TRANSCRIPT",
            "CLAIM_COVERAGE_SHA256_MATCHES_NARRATION_SCRIPT",
            "TTS_MODEL_SHA256_MATCHES_REFERENCED_LOCAL_MODEL_ARTIFACT",
            "TTS_PROVIDER_IMPLEMENTATION_SHA256_MATCHES_REFERENCED_LOCAL_BYTES",
            "PROVIDER_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES",
            "TTS_RUNTIME_ENVIRONMENT_SHA256_MATCHES_REFERENCED_BYTES",
            "LICENSE_SPDX_MATCHES_TTS_MODEL_LICENSE_EVIDENCE",
            "TTS_EXECUTION_MODE_IS_LOCAL_OFFLINE",
            "TTS_NETWORK_ACCESS_WAS_NOT_USED",
            "TTS_VOICE_IS_NOT_CLONED",
        ]

    elif artifact_kind == "AUDIO_ALIGNMENT_RECEIPT":
        for field in (
            "final_av_drift_frames",
            "absolute_final_av_drift_frames",
        ):
            properties.pop(field, None)
        if isinstance(schema.get("required"), list):
            schema["required"] = [
                field
                for field in schema["required"]
                if field
                not in {
                    "final_av_drift_frames",
                    "absolute_final_av_drift_frames",
                }
            ]
        _require_schema_fields(
            schema,
            [
                "tts_receipt_ref",
                "tts_receipt_sha256",
                "audio_sha256",
                "narration_script_ref",
                "narration_script_sha256",
                "max_anchor_error_seconds",
                "opening_dead_air_seconds",
                "minimum_shot_tail_seconds",
            ],
        )
        properties["tts_receipt_ref"] = {
            "type": "string",
            "minLength": 1,
        }
        properties["narration_script_ref"] = {
            "type": "string",
            "minLength": 1,
        }
        for field in (
            "tts_receipt_sha256",
            "audio_sha256",
            "narration_script_sha256",
        ):
            properties[field] = {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            }
        properties["max_anchor_error_seconds"] = {
            "type": "number",
            "minimum": 0,
            "maximum": 0.1,
        }
        properties["opening_dead_air_seconds"] = {
            "type": "number",
            "minimum": 0,
            "maximum": 1.5,
        }
        properties["minimum_shot_tail_seconds"] = {
            "type": "number",
            "minimum": 0.5,
        }
        sentence_ids = properties.setdefault("sentence_ids", {"type": "array"})
        sentence_ids.update(
            {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            }
        )
        word_anchors = properties.setdefault("word_anchors", {"type": "array"})
        word_anchors.update(
            {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "anchor_id",
                        "sentence_id",
                        "token",
                        "start_seconds",
                        "end_seconds",
                        "audio_sha256",
                    ],
                    "properties": {
                        "anchor_id": {"type": "string", "minLength": 1},
                        "sentence_id": {"type": "string", "minLength": 1},
                        "token": {"type": "string", "minLength": 1},
                        "start_seconds": {"type": "number", "minimum": 0},
                        "end_seconds": {"type": "number", "exclusiveMinimum": 0},
                        "audio_sha256": {
                            "type": "string",
                            "pattern": "^[0-9a-f]{64}$",
                        },
                    },
                },
            }
        )
        schema["x-invariants"] = [
            "TTS_RECEIPT_AUDIO_SHA256_EQUALS_AUDIO_SHA256",
            "TTS_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES",
            "NARRATION_SCRIPT_SHA256_MATCHES_REFERENCED_SCRIPT",
            "EVERY_WORD_ANCHOR_AUDIO_SHA256_EQUALS_TOP_LEVEL_AUDIO_SHA256",
            "EVERY_WORD_ANCHOR_START_SECONDS_IS_LESS_THAN_END_SECONDS",
            "WORD_ANCHORS_ARE_MONOTONIC_AND_NON_OVERLAPPING",
            "SENTENCE_IDS_EQUAL_NARRATION_SCRIPT_SENTENCE_IDS",
        ]

    elif artifact_kind == "OBJECT_MOTION_IR":
        motion_state_schema = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "x",
                "y",
                "scale",
                "rotation_degrees",
                "opacity",
            ],
            "properties": {
                "x": {"type": "number"},
                "y": {"type": "number"},
                "scale": {"type": "number", "exclusiveMinimum": 0},
                "rotation_degrees": {"type": "number"},
                "opacity": {"type": "number", "minimum": 0, "maximum": 1},
            },
        }
        motion_segment_schema = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "segment_id",
                "curve_id",
                "phase",
                "start_seconds",
                "end_seconds",
                "kind",
                "easing",
                "loop_count",
                "from_state",
                "to_state",
            ],
            "properties": {
                "segment_id": {"type": "string", "minLength": 1},
                "curve_id": {"type": "string", "minLength": 1},
                "phase": {"enum": ["ENTER", "HOLD", "EXIT"]},
                "start_seconds": {"type": "number", "minimum": 0},
                "end_seconds": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "maximum": 185,
                },
                "kind": {
                    "enum": [
                        "TRANSLATE",
                        "SCALE",
                        "ROTATE",
                        "OPACITY",
                        "COMPOSITE",
                    ]
                },
                "easing": {
                    "enum": [
                        "LINEAR",
                        "EASE_IN",
                        "EASE_OUT",
                        "EASE_IN_OUT",
                        "SPRING",
                    ]
                },
                "loop_count": {"type": "integer", "minimum": 1},
                "from_state": deepcopy(motion_state_schema),
                "to_state": deepcopy(motion_state_schema),
            },
        }
        object_schema = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "object_id",
                "asset_id",
                "sentence_ids",
                "claim_ids",
                "visual_intent_id",
                "semantic_role",
                "source_type",
                "geometry",
                "z_order",
                "enter_time",
                "hold_interval",
                "exit_time",
                "motion_segments",
                "audio_anchor_id",
                "invariants",
                "prohibited_changes",
            ],
            "properties": {
                "object_id": {"type": "string", "minLength": 1},
                "asset_id": {"type": "string", "minLength": 1},
                "sentence_ids": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1},
                },
                "claim_ids": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1},
                },
                "visual_intent_id": {"type": "string", "minLength": 1},
                "semantic_role": {"type": "string", "minLength": 1},
                "source_type": {"type": "string", "minLength": 1},
                "geometry": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["x", "y", "width", "height", "unit"],
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "width": {"type": "number", "exclusiveMinimum": 0},
                        "height": {"type": "number", "exclusiveMinimum": 0},
                        "unit": {"enum": ["PIXEL", "NORMALIZED"]},
                    },
                },
                "z_order": {"type": "integer"},
                "enter_time": {"type": "number", "minimum": 0},
                "hold_interval": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["start_seconds", "end_seconds"],
                    "properties": {
                        "start_seconds": {"type": "number", "minimum": 0},
                        "end_seconds": {"type": "number", "exclusiveMinimum": 0},
                    },
                },
                "exit_time": {"type": "number", "exclusiveMinimum": 0},
                "motion_segments": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 3,
                    "uniqueItems": True,
                    "items": motion_segment_schema,
                },
                "audio_anchor_id": {"type": "string", "minLength": 1},
                "invariants": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
                "prohibited_changes": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
            },
        }
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "alignment_receipt_ref",
                "alignment_receipt_sha256",
                "audio_sha256",
                "narration_script_ref",
                "narration_script_sha256",
                "asset_plan_ref",
                "asset_plan_sha256",
                "claim_matrix_ref",
                "claim_matrix_sha256",
                "duration_seconds",
                "sentence_ids",
                "audio_anchor_ids",
                "motion_curve_ids",
                "word_to_motion_tolerance_seconds",
                "scene_transition_count",
                "shots",
                "seek_safe",
                "random_seed_policy",
                "status",
            ],
            "properties": {
                "alignment_receipt_ref": {"type": "string", "minLength": 1},
                "alignment_receipt_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "audio_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "narration_script_ref": {"type": "string", "minLength": 1},
                "narration_script_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "asset_plan_ref": {"type": "string", "minLength": 1},
                "asset_plan_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "claim_matrix_ref": {"type": "string", "minLength": 1},
                "claim_matrix_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "duration_seconds": {
                    "type": "number",
                    "minimum": 175,
                    "maximum": 185,
                },
                "sentence_ids": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1},
                },
                "audio_anchor_ids": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1},
                },
                "motion_curve_ids": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1},
                },
                "word_to_motion_tolerance_seconds": {"const": 0.1},
                "scene_transition_count": {
                    "type": "integer",
                    "minimum": 9,
                    "maximum": 13,
                },
                "shots": {
                    "type": "array",
                    "minItems": 10,
                    "maxItems": 14,
                    "uniqueItems": True,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "shot_id",
                            "start_seconds",
                            "end_seconds",
                            "scene_transition",
                            "sentence_ids",
                            "audio_anchor_ids",
                            "objects",
                        ],
                        "properties": {
                            "shot_id": {"type": "string", "minLength": 1},
                            "start_seconds": {"type": "number", "minimum": 0},
                            "end_seconds": {"type": "number", "exclusiveMinimum": 0},
                            "scene_transition": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["kind", "duration_seconds", "easing"],
                                "properties": {
                                    "kind": {"type": "string", "minLength": 1},
                                    "duration_seconds": {
                                        "type": "number",
                                        "minimum": 0,
                                    },
                                    "easing": {"type": "string", "minLength": 1},
                                },
                            },
                            "sentence_ids": {
                                "type": "array",
                                "minItems": 1,
                                "uniqueItems": True,
                                "items": {"type": "string", "minLength": 1},
                            },
                            "audio_anchor_ids": {
                                "type": "array",
                                "minItems": 1,
                                "uniqueItems": True,
                                "items": {"type": "string", "minLength": 1},
                            },
                            "objects": {
                                "type": "array",
                                "minItems": 1,
                                "uniqueItems": True,
                                "items": object_schema,
                            },
                        },
                    },
                },
                "seek_safe": {"const": True},
                "random_seed_policy": {"const": "NO_UNSEEDED_RANDOMNESS"},
                "status": {"const": "PASS"},
            },
        }
        properties = schema["properties"]
        schema["x-invariants"] = [
            "ALIGNMENT_RECEIPT_AUDIO_SHA256_EQUALS_AUDIO_SHA256",
            "ALIGNMENT_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES",
            "AUDIO_ANCHOR_IDS_EQUAL_REFERENCED_ALIGNMENT_ANCHOR_IDS",
            "NARRATION_SCRIPT_SHA256_MATCHES_REFERENCED_SCRIPT",
            "ASSET_PLAN_SHA256_MATCHES_REFERENCED_ASSET_PLAN",
            "CLAIM_MATRIX_SHA256_MATCHES_REFERENCED_BYTES",
            "SENTENCE_IDS_EQUAL_NARRATION_SCRIPT_SENTENCE_IDS",
            "FULL_TIMELINE_CONTIGUOUS_NO_GAPS_OR_OVERLAPS",
            "FIRST_SHOT_STARTS_AT_ZERO",
            "FINAL_SHOT_END_EQUALS_DURATION_SECONDS",
            "SHOT_SENTENCE_ID_UNION_EQUALS_TOP_LEVEL_SENTENCE_IDS",
            "SHOT_AUDIO_ANCHOR_ID_UNION_EQUALS_TOP_LEVEL_AUDIO_ANCHOR_IDS",
            "EVERY_OBJECT_AUDIO_ANCHOR_ID_EXISTS_IN_AUDIO_ANCHOR_IDS",
            "EVERY_MOTION_OBJECT_BINDS_SENTENCES_CLAIMS_VISUAL_INTENT_ASSET_AND_AUDIO_ANCHOR",
            "MOTION_OBJECT_BINDINGS_RESOLVE_TO_NARRATION_ASSET_AND_ALIGNMENT",
            "EVERY_SPOKEN_SENTENCE_HAS_VISIBLE_OBJECT_DURING_BOUND_AUDIO_ANCHOR",
            "EVERY_OBJECT_WORD_TO_MOTION_ERROR_DOES_NOT_EXCEED_0_1_SECONDS",
            "SCENE_TRANSITION_COUNT_EQUALS_NON_INITIAL_TRANSITIONS",
            "ENTER_TIME_LESS_THAN_OR_EQUAL_TO_HOLD_START",
            "HOLD_START_LESS_THAN_HOLD_END",
            "HOLD_END_LESS_THAN_OR_EQUAL_TO_EXIT_TIME",
            "MOTION_CURVE_IDS_EQUAL_OBJECT_MOTION_SEGMENT_CURVE_IDS",
            "MOTION_SEGMENT_IDS_ARE_UNIQUE",
            "ENTER_HOLD_EXIT_SEGMENTS_ARE_CONTIGUOUS_AND_MATCH_DECLARED_INTERVALS",
            "EVERY_MOTION_SEGMENT_HAS_DISTINCT_FROM_AND_TO_STATE",
        ]
        schema["x-invariant-contracts"] = {
            "EVERY_OBJECT_WORD_TO_MOTION_ERROR_DOES_NOT_EXCEED_0_1_SECONDS": {
                "algorithm": (
                    "FOR_EACH_OBJECT_RESOLVE_AUDIO_ANCHOR_START_SECONDS_AND_"
                    "REQUIRE_ABS_OBJECT_ENTER_TIME_MINUS_ANCHOR_START_SECONDS_"
                    "LTE_WORD_TO_MOTION_TOLERANCE_SECONDS"
                ),
                "failure_code": "MOTION_SYNC_TOLERANCE_EXCEEDED",
            }
        }

    elif artifact_kind == "ASSET_PLAN":
        if (
            {
                "assets",
                "asset_object_ids",
                "motion_object_ids",
                "asset_manifest_sha256",
                "status",
            }.issubset(properties)
            and "ASSET_MANIFEST_SHA256_MATCHES_CANONICAL_ASSET_ARRAY"
            in schema.get("x-invariants", [])
        ):
            return schema
        item_properties = deepcopy(properties)
        item_required = [
            str(value)
            for value in schema.get("required", [])
            if value not in {"job_id", "source_id", "status"}
        ]
        for field in (
            "asset_id",
            "object_id",
            "sentence_ids",
            "claim_ids",
            "visual_intent_id",
            "route",
            "materialization_state",
            "asset_ref",
            "asset_sha256",
            "provenance_refs",
            "provenance_sha256s",
            "local_build_recipe",
            "generation_authorization_ref",
            "generation_receipt_ref",
            "generation_receipt_sha256",
        ):
            if field not in item_required:
                item_required.append(field)
        item_properties["asset_id"] = {"type": "string", "minLength": 1}
        item_properties["object_id"] = {"type": "string", "minLength": 1}
        for field in ("sentence_ids", "claim_ids"):
            item_properties[field] = {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            }
        item_properties["visual_intent_id"] = {
            "type": "string",
            "minLength": 1,
        }
        item_properties["route"] = {
            "enum": [
                "SOURCE_EVIDENCE",
                "CODEX_IMAGEGEN",
                "LOCAL_PY_DETERMINISTIC",
            ]
        }
        item_properties["asset_ref"] = {
            "type": ["string", "null"],
            "minLength": 1,
        }
        item_properties["asset_sha256"] = {
            "type": ["string", "null"],
            "pattern": "^[0-9a-f]{64}$",
        }
        item_properties["provenance_refs"] = {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
        }
        item_properties["provenance_sha256s"] = {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
        }
        item_properties["local_build_recipe"] = {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": [
                "implementation_ref",
                "implementation_sha256",
                "input_manifest_ref",
                "input_manifest_sha256",
                "command_receipt_ref",
                "command_receipt_sha256",
                "output_ref",
                "output_sha256",
                "deterministic_seed",
                "network_accessed",
                "status",
            ],
            "properties": {
                "implementation_ref": {"type": "string", "minLength": 1},
                "implementation_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "input_manifest_ref": {"type": "string", "minLength": 1},
                "input_manifest_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "command_receipt_ref": {"type": "string", "minLength": 1},
                "command_receipt_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "output_ref": {"type": "string", "minLength": 1},
                "output_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "deterministic_seed": {"type": "integer", "minimum": 0},
                "network_accessed": {"const": False},
                "status": {"const": "PASS"},
            },
        }
        item_properties["generation_authorization_ref"] = {
            "type": ["string", "null"],
            "minLength": 1,
        }
        item_properties["generation_receipt_ref"] = {
            "type": ["string", "null"],
            "minLength": 1,
        }
        item_properties["generation_receipt_sha256"] = {
            "type": ["string", "null"],
            "pattern": "^[0-9a-f]{64}$",
        }
        item_properties["materialization_state"] = {
            "enum": [
                "SOURCE_VERIFIED",
                "LOCAL_DETERMINISTIC_VERIFIED",
                "CODEX_IMAGEGEN_PLANNED_NOT_AUTHORIZED",
                "CODEX_IMAGEGEN_AUTHORIZED_MATERIALIZED",
            ]
        }
        route_contract = [
            {
                "properties": {
                    "route": {"const": "SOURCE_EVIDENCE"},
                    "materialization_state": {"const": "SOURCE_VERIFIED"},
                    "asset_ref": {"type": "string"},
                    "asset_sha256": {"type": "string"},
                    "local_build_recipe": {"type": "null"},
                    "generation_authorization_ref": {"type": "null"},
                    "generation_receipt_ref": {"type": "null"},
                    "generation_receipt_sha256": {"type": "null"},
                }
            },
            {
                "properties": {
                    "route": {"const": "LOCAL_PY_DETERMINISTIC"},
                    "materialization_state": {
                        "const": "LOCAL_DETERMINISTIC_VERIFIED"
                    },
                    "asset_ref": {"type": "string"},
                    "asset_sha256": {"type": "string"},
                    "local_build_recipe": {"type": "object"},
                    "generation_authorization_ref": {"type": "null"},
                    "generation_receipt_ref": {"type": "null"},
                    "generation_receipt_sha256": {"type": "null"},
                }
            },
            {
                "properties": {
                    "route": {"const": "CODEX_IMAGEGEN"},
                    "materialization_state": {
                        "const": "CODEX_IMAGEGEN_PLANNED_NOT_AUTHORIZED"
                    },
                    "asset_ref": {"type": "null"},
                    "asset_sha256": {"type": "null"},
                    "local_build_recipe": {"type": "null"},
                    "generation_authorization_ref": {"type": "null"},
                    "generation_receipt_ref": {"type": "null"},
                    "generation_receipt_sha256": {"type": "null"},
                }
            },
            {
                "properties": {
                    "route": {"const": "CODEX_IMAGEGEN"},
                    "materialization_state": {
                        "const": "CODEX_IMAGEGEN_AUTHORIZED_MATERIALIZED"
                    },
                    "asset_ref": {"type": "string"},
                    "asset_sha256": {"type": "string"},
                    "local_build_recipe": {"type": "null"},
                    "generation_authorization_ref": {"type": "string"},
                    "generation_receipt_ref": {"type": "string"},
                    "generation_receipt_sha256": {"type": "string"},
                }
            },
        ]
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "assets",
                "asset_object_ids",
                "motion_object_ids",
                "asset_manifest_sha256",
                "status",
            ],
            "properties": {
                "assets": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": item_required,
                        "properties": item_properties,
                        "oneOf": route_contract,
                    },
                },
                "asset_object_ids": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1},
                },
                "motion_object_ids": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1},
                },
                "asset_manifest_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "status": {"const": "PASS"},
            },
            "x-invariants": [
                "ASSET_MANIFEST_SHA256_MATCHES_CANONICAL_ASSET_ARRAY",
                "EVERY_MATERIALIZED_ASSET_REF_HASH_MATCHES_ASSET_SHA256",
                "ASSET_PROVENANCE_REFS_AND_HASHES_HAVE_EQUAL_CARDINALITY",
                "EVERY_ASSET_PROVENANCE_HASH_MATCHES_REFERENCED_BYTES",
                "LOCAL_DETERMINISTIC_ASSET_RECIPE_AND_OUTPUT_ARE_HASH_BOUND",
                "CODEX_IMAGEGEN_MATERIALIZATION_REQUIRES_SEPARATE_CURRENT_AUTHORIZATION",
                "IMAGEGEN_RECEIPT_HASH_MATCHES_REFERENCED_BYTES_WHEN_MATERIALIZED",
            ],
        }
        properties = schema["properties"]

    elif artifact_kind == "ASSET_BINDING_RECEIPT":
        id_array = {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
        }
        hash_field = {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        }
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "asset_plan_ref",
                "asset_plan_sha256",
                "narration_script_ref",
                "narration_script_sha256",
                "claim_matrix_ref",
                "claim_matrix_sha256",
                "motion_ir_ref",
                "motion_ir_sha256",
                "asset_object_ids",
                "motion_object_ids",
                "asset_sentence_ids",
                "narration_sentence_ids",
                "asset_claim_ids",
                "claim_matrix_claim_ids",
                "asset_visual_intent_ids",
                "resolved_asset_visual_intent_ids",
                "status",
            ],
            "properties": {
                "asset_plan_ref": {"type": "string", "minLength": 1},
                "asset_plan_sha256": deepcopy(hash_field),
                "narration_script_ref": {"type": "string", "minLength": 1},
                "narration_script_sha256": deepcopy(hash_field),
                "claim_matrix_ref": {"type": "string", "minLength": 1},
                "claim_matrix_sha256": deepcopy(hash_field),
                "motion_ir_ref": {"type": "string", "minLength": 1},
                "motion_ir_sha256": deepcopy(hash_field),
                "asset_object_ids": deepcopy(id_array),
                "motion_object_ids": deepcopy(id_array),
                "asset_sentence_ids": deepcopy(id_array),
                "narration_sentence_ids": deepcopy(id_array),
                "asset_claim_ids": deepcopy(id_array),
                "claim_matrix_claim_ids": deepcopy(id_array),
                "asset_visual_intent_ids": deepcopy(id_array),
                "resolved_asset_visual_intent_ids": deepcopy(id_array),
                "status": {"const": "PASS"},
            },
            "x-invariants": [
                "MOTION_OBJECT_IDS_EQUAL_ASSET_OBJECT_IDS",
                "ASSET_SEMANTIC_BINDINGS_RESOLVE_TO_NARRATION_AND_CLAIM_MATRIX",
            ],
        }
        properties = schema["properties"]

    elif artifact_kind == "BEFORE_AFTER_DEMO_CONTRACT":
        nullable_ref = {"type": ["string", "null"], "minLength": 1}
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "demo_id",
                "input_before_ref",
                "input_before_sha256",
                "processing_action",
                "effect_claim_id",
                "effect_delta",
                "output_after_ref",
                "output_after_sha256",
                "input_state",
                "output_state",
                "claim_ids",
                "provenance_state",
                "source_evidence_refs",
                "source_evidence_sha256s",
                "target_skill_authorization_ref",
                "target_skill_execution_receipt_ref",
                "target_skill_execution_receipt_sha256",
                "actual_skill_output",
                "illustration_label",
                "status",
            ],
            "properties": {
                "demo_id": {"type": "string", "minLength": 1},
                "input_before_ref": {"type": "string", "minLength": 1},
                "input_before_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "processing_action": {"type": "string", "minLength": 1},
                "effect_claim_id": {"type": "string", "minLength": 1},
                "effect_delta": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "property_path",
                            "before_value",
                            "after_value",
                            "evidence_ref",
                            "evidence_sha256",
                            "evidence_input_sha256",
                            "evidence_output_sha256",
                            "observed_change",
                        ],
                        "properties": {
                            "property_path": {
                                "type": "string",
                                "pattern": "^(?:/(?:[^~/]|~0|~1)*)+$",
                            },
                            "before_value": {},
                            "after_value": {},
                            "evidence_ref": {"type": "string", "minLength": 1},
                            "evidence_sha256": {
                                "type": "string",
                                "pattern": "^[0-9a-f]{64}$",
                            },
                            "evidence_input_sha256": {
                                "type": "string",
                                "pattern": "^[0-9a-f]{64}$",
                            },
                            "evidence_output_sha256": {
                                "type": "string",
                                "pattern": "^[0-9a-f]{64}$",
                            },
                            "observed_change": {"const": True},
                        },
                    },
                },
                "output_after_ref": {"type": "string", "minLength": 1},
                "output_after_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "input_state": {
                    "type": "object",
                    "minProperties": 1,
                },
                "output_state": {
                    "type": "object",
                    "minProperties": 1,
                },
                "claim_ids": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1},
                },
                "provenance_state": {
                    "enum": [
                        "OBSERVED_REPO_FIXTURE",
                        "AUTHORIZED_TARGET_SKILL_RUN",
                        "CLEARLY_LABELED_ILLUSTRATION",
                    ]
                },
                "source_evidence_refs": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1},
                },
                "source_evidence_sha256s": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "pattern": "^[0-9a-f]{64}$",
                    },
                },
                "target_skill_authorization_ref": deepcopy(nullable_ref),
                "target_skill_execution_receipt_ref": deepcopy(nullable_ref),
                "target_skill_execution_receipt_sha256": {
                    "type": ["string", "null"],
                    "pattern": "^[0-9a-f]{64}$",
                },
                "actual_skill_output": {"type": "boolean"},
                "illustration_label": deepcopy(nullable_ref),
                "status": {"const": "PASS"},
            },
            "oneOf": [
                {
                    "properties": {
                        "provenance_state": {
                            "const": "OBSERVED_REPO_FIXTURE"
                        },
                        "target_skill_authorization_ref": {"type": "null"},
                        "target_skill_execution_receipt_ref": {"type": "null"},
                        "target_skill_execution_receipt_sha256": {
                            "type": "null"
                        },
                        "actual_skill_output": {"const": True},
                        "illustration_label": {"type": "null"},
                    }
                },
                {
                    "properties": {
                        "provenance_state": {
                            "const": "AUTHORIZED_TARGET_SKILL_RUN"
                        },
                        "target_skill_authorization_ref": {"type": "string"},
                        "target_skill_execution_receipt_ref": {
                            "type": "string"
                        },
                        "target_skill_execution_receipt_sha256": {
                            "type": "string"
                        },
                        "actual_skill_output": {"const": True},
                        "illustration_label": {"type": "null"},
                    }
                },
                {
                    "properties": {
                        "provenance_state": {
                            "const": "CLEARLY_LABELED_ILLUSTRATION"
                        },
                        "target_skill_authorization_ref": {"type": "null"},
                        "target_skill_execution_receipt_ref": {"type": "null"},
                        "target_skill_execution_receipt_sha256": {
                            "type": "null"
                        },
                        "actual_skill_output": {"const": False},
                        "illustration_label": {
                            "type": "string",
                            "minLength": 1,
                        },
                    }
                },
            ],
            "x-invariants": [
                "DEMO_CLAIM_IDS_RESOLVE_TO_SAME_JOB_CLAIM_MATRIX",
                "DEMO_EFFECT_CLAIM_RESOLVES_TO_SAME_JOB_CLAIM_MATRIX",
                "BEFORE_AND_AFTER_HASHES_MATCH_REFERENCED_BYTES",
                "DEMO_INPUT_AND_OUTPUT_BYTES_ARE_DISTINCT",
                "DEMO_EFFECT_DELTA_CONTAINS_OBSERVED_STATE_CHANGE",
                "DEMO_EFFECT_DELTA_PROPERTY_PATHS_RESOLVE_IN_BOTH_STATES",
                "DEMO_EFFECT_DELTA_VALUES_EQUAL_RESOLVED_STATE_VALUES",
                "DEMO_EFFECT_DELTA_BEFORE_AND_AFTER_VALUES_ARE_DISTINCT",
                "DEMO_EFFECT_DELTA_EVIDENCE_SHA256_MATCHES_REFERENCED_BYTES",
                "DEMO_EFFECT_DELTA_EVIDENCE_BINDS_BEFORE_AND_AFTER_BYTES",
                "DEMO_PROCESSING_ACTION_MATCHES_EFFECT_CLAIM",
                "SOURCE_EVIDENCE_REFS_AND_HASHES_HAVE_EQUAL_CARDINALITY",
                "OBSERVED_REPO_FIXTURE_REQUIRES_PINNED_SOURCE_EVIDENCE",
                "AUTHORIZED_TARGET_SKILL_RUN_REQUIRES_CURRENT_EXACT_AUTHORIZATION_AND_RECEIPT",
                "ILLUSTRATION_IS_EXPLICITLY_LABELED_AND_NOT_ACTUAL_SKILL_OUTPUT",
            ],
            "x-invariant-contracts": {
                "DEMO_EFFECT_DELTA_PROPERTY_PATHS_RESOLVE_IN_BOTH_STATES": {
                    "algorithm": "RFC6901_RESOLVE_EACH_PROPERTY_PATH_IN_INPUT_STATE_AND_OUTPUT_STATE",
                    "failure_code": "DEMO_EFFECT_DELTA_PROPERTY_PATH_UNRESOLVED",
                },
                "DEMO_EFFECT_DELTA_VALUES_EQUAL_RESOLVED_STATE_VALUES": {
                    "algorithm": "DEEP_EQUAL_BEFORE_VALUE_TO_INPUT_STATE_POINTER_AND_AFTER_VALUE_TO_OUTPUT_STATE_POINTER",
                    "failure_code": "DEMO_EFFECT_DELTA_VALUE_MISMATCH",
                },
                "DEMO_EFFECT_DELTA_BEFORE_AND_AFTER_VALUES_ARE_DISTINCT": {
                    "algorithm": "REQUIRE_CANONICAL_JSON_BYTES_OF_BEFORE_VALUE_AND_AFTER_VALUE_TO_DIFFER",
                    "failure_code": "DEMO_EFFECT_DELTA_NOT_OBSERVED",
                },
                "DEMO_EFFECT_DELTA_EVIDENCE_SHA256_MATCHES_REFERENCED_BYTES": {
                    "algorithm": "SHA256_EVIDENCE_REF_BYTES_EQUALS_EVIDENCE_SHA256",
                    "failure_code": "DEMO_EFFECT_DELTA_EVIDENCE_HASH_MISMATCH",
                },
                "DEMO_EFFECT_DELTA_EVIDENCE_BINDS_BEFORE_AND_AFTER_BYTES": {
                    "algorithm": "EVIDENCE_BYTES_DECLARE_INPUT_AND_OUTPUT_SHA256_EQUAL_TO_TOP_LEVEL_BEFORE_AND_AFTER_SHA256",
                    "failure_code": "DEMO_EFFECT_DELTA_EVIDENCE_LINEAGE_MISMATCH",
                },
            },
        }
        properties = schema["properties"]

    elif artifact_kind == "TARGET_SKILL_EXECUTION_GATE_RECEIPT":
        nullable_ref = {"type": ["string", "null"], "minLength": 1}
        nullable_sha256 = {
            "type": ["string", "null"],
            "pattern": "^[0-9a-f]{64}$",
        }
        nullable_commit = {
            "type": ["string", "null"],
            "pattern": "^[0-9a-f]{40}$",
        }
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "target_skill_id",
                "default_enabled",
                "authorization_class",
                "authorization_scope",
                "authorization_ref",
                "authorization_receipt_sha256",
                "authorization_freshness",
                "authorization_consumed",
                "exact_commit_sha",
                "authorized_job_id",
                "authorized_commit_sha",
                "authorized_input_manifest_sha256",
                "current_input_manifest_sha256",
                "authorized_environment_id",
                "authorized_environment_manifest_ref",
                "authorized_environment_manifest_sha256",
                "current_environment_manifest_sha256",
                "authorized_output_root_ref",
                "authorized_output_manifest_sha256",
                "current_output_manifest_sha256",
                "output_receipt_ref",
                "output_receipt_sha256",
                "input_hashes",
                "attempted_side_effect_ids",
                "side_effects_started",
                "execution_receipt_ref",
                "execution_receipt_sha256",
                "status",
            ],
            "properties": {
                "target_skill_id": {"type": "string", "minLength": 1},
                "default_enabled": {"const": False},
                "authorization_class": {
                    "const": "TARGET_SKILL_EXECUTION_AUTHORIZATION"
                },
                "authorization_scope": {
                    "enum": [
                        "EXACT_JOB_COMMIT_INPUT_ENVIRONMENT_AND_OUTPUT",
                        "PROGRAM_WIDE",
                    ]
                },
                "authorization_ref": deepcopy(nullable_ref),
                "authorization_receipt_sha256": deepcopy(nullable_sha256),
                "authorization_freshness": {
                    "enum": ["NOT_AUTHORIZED", "CURRENT", "STALE"]
                },
                "authorization_consumed": {"type": "boolean"},
                "exact_commit_sha": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{40}$",
                },
                "authorized_job_id": deepcopy(nullable_ref),
                "authorized_commit_sha": deepcopy(nullable_commit),
                "authorized_input_manifest_sha256": deepcopy(nullable_sha256),
                "current_input_manifest_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "authorized_environment_id": deepcopy(nullable_ref),
                "authorized_environment_manifest_ref": deepcopy(nullable_ref),
                "authorized_environment_manifest_sha256": deepcopy(
                    nullable_sha256
                ),
                "current_environment_manifest_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "authorized_output_root_ref": deepcopy(nullable_ref),
                "authorized_output_manifest_sha256": deepcopy(nullable_sha256),
                "current_output_manifest_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "output_receipt_ref": deepcopy(nullable_ref),
                "output_receipt_sha256": deepcopy(nullable_sha256),
                "input_hashes": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "pattern": "^[0-9a-f]{64}$",
                    },
                },
                "attempted_side_effect_ids": {
                    "type": "array",
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1},
                },
                "side_effects_started": {"type": "boolean"},
                "execution_receipt_ref": deepcopy(nullable_ref),
                "execution_receipt_sha256": deepcopy(nullable_sha256),
                "status": {
                    "enum": [
                        "DENIED_NO_SIDE_EFFECT",
                        "AUTHORIZED_EXECUTION_RECEIPT_VALID",
                    ]
                },
            },
        }
        properties = schema["properties"]
        schema["oneOf"] = [
            {
                "properties": {
                    "status": {"const": "DENIED_NO_SIDE_EFFECT"},
                    "authorization_ref": {"type": "null"},
                    "authorized_environment_id": {"type": "null"},
                    "authorized_environment_manifest_ref": {"type": "null"},
                    "authorized_environment_manifest_sha256": {"type": "null"},
                    "authorized_output_root_ref": {"type": "null"},
                    "authorized_output_manifest_sha256": {"type": "null"},
                    "output_receipt_ref": {"type": "null"},
                    "output_receipt_sha256": {"type": "null"},
                    "execution_receipt_ref": {"type": "null"},
                    "execution_receipt_sha256": {"type": "null"},
                    "side_effects_started": {"const": False},
                }
            },
            {
                "properties": {
                    "status": {
                        "const": "AUTHORIZED_EXECUTION_RECEIPT_VALID"
                    },
                    "authorization_ref": {"type": "string"},
                    "authorized_environment_id": {"type": "string"},
                    "authorized_environment_manifest_ref": {"type": "string"},
                    "authorized_environment_manifest_sha256": {"type": "string"},
                    "authorized_output_root_ref": {"type": "string"},
                    "authorized_output_manifest_sha256": {"type": "string"},
                    "output_receipt_ref": {"type": "string"},
                    "output_receipt_sha256": {"type": "string"},
                    "execution_receipt_ref": {"type": "string"},
                    "execution_receipt_sha256": {"type": "string"},
                    "side_effects_started": {"const": True},
                }
            },
        ]
        schema["x-invariants"] = [
            "AUTHORIZED_TARGET_EXECUTION_BINDS_EXACT_JOB_COMMIT_INPUT_ENVIRONMENT_AND_OUTPUT",
            "TARGET_EXECUTION_ENVIRONMENT_RECEIPT_HASH_MATCHES_REFERENCED_BYTES",
            "TARGET_EXECUTION_OUTPUT_RECEIPT_HASH_MATCHES_REFERENCED_BYTES",
            "AUTHORIZED_ENVIRONMENT_MANIFEST_SHA256_EQUALS_CURRENT_ENVIRONMENT_MANIFEST_SHA256",
            "AUTHORIZED_OUTPUT_MANIFEST_SHA256_EQUALS_CURRENT_OUTPUT_MANIFEST_SHA256",
            "TARGET_EXECUTION_AUTHORIZATION_IS_CURRENT_SINGLE_USE_AND_NOT_PROGRAM_WIDE",
            "TARGET_EXECUTION_RECEIPT_HASH_MATCHES_REFERENCED_BYTES",
            "DENIED_TARGET_SKILL_GATE_HAS_NO_AUTHORIZATION_OR_SIDE_EFFECT_ATTEMPT",
        ]

    elif artifact_kind == "LOCAL_RENDER_RECEIPT":
        _require_schema_fields(
            schema,
            [
                "video_ref",
                "video_sha256",
                "audio_sha256",
                "tts_receipt_ref",
                "tts_receipt_sha256",
                "alignment_receipt_ref",
                "alignment_receipt_sha256",
                "motion_ir_ref",
                "motion_ir_sha256",
                "asset_plan_ref",
                "asset_plan_sha256",
                "dependency_manifest_ref",
                "dependency_manifest_sha256",
                "render_input_manifest_ref",
                "render_input_manifest_sha256",
                "composition_ref",
                "composition_sha256",
                "render_command_receipt_ref",
                "render_command_receipt_sha256",
                "audio_stream_present",
                "render_trace_ref",
                "render_trace_sha256",
                "rendered_shot_ids",
                "rendered_object_ids",
                "rendered_motion_curve_ids",
                "rendered_semantic_bindings",
                "render_trace_sample_count",
            ],
        )
        properties["video_ref"] = {"type": "string", "minLength": 1}
        for field in (
            "video_sha256",
            "audio_sha256",
            "motion_ir_sha256",
            "asset_plan_sha256",
            "tts_receipt_sha256",
            "alignment_receipt_sha256",
            "dependency_manifest_sha256",
            "render_input_manifest_sha256",
            "composition_sha256",
            "render_command_receipt_sha256",
            "render_trace_sha256",
        ):
            properties[field] = {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            }
        for field in (
            "tts_receipt_ref",
            "alignment_receipt_ref",
            "motion_ir_ref",
            "asset_plan_ref",
            "dependency_manifest_ref",
            "render_input_manifest_ref",
            "composition_ref",
            "render_command_receipt_ref",
            "render_trace_ref",
        ):
            properties[field] = {"type": "string", "minLength": 1}
        for field in (
            "rendered_shot_ids",
            "rendered_object_ids",
            "rendered_motion_curve_ids",
        ):
            properties[field] = {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            }
        properties["rendered_semantic_bindings"] = {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "object_id",
                    "asset_id",
                    "sentence_ids",
                    "claim_ids",
                    "visual_intent_id",
                    "audio_anchor_id",
                    "motion_segment_ids",
                    "motion_curve_ids",
                ],
                "properties": {
                    "object_id": {"type": "string", "minLength": 1},
                    "asset_id": {"type": "string", "minLength": 1},
                    "sentence_ids": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "claim_ids": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "visual_intent_id": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "audio_anchor_id": {"type": "string", "minLength": 1},
                    "motion_segment_ids": {
                        "type": "array",
                        "minItems": 3,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "motion_curve_ids": {
                        "type": "array",
                        "minItems": 3,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1},
                    },
                },
            },
        }
        properties["audio_stream_present"] = {"type": "boolean"}
        properties["render_trace_sample_count"] = {
            "type": "integer",
            "minimum": 1,
        }
        schema["x-invariants"] = [
            "TTS_ALIGNMENT_MOTION_AND_RENDER_AUDIO_SHA256_ARE_EQUAL",
            "LOCAL_RENDER_TTS_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES",
            "LOCAL_RENDER_ALIGNMENT_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES",
            "MOTION_IR_SHA256_MATCHES_REFERENCED_MOTION_IR",
            "ASSET_PLAN_SHA256_MATCHES_REFERENCED_ASSET_PLAN",
            "DEPENDENCY_MANIFEST_SHA256_MATCHES_REFERENCED_BYTES",
            "DEPENDENCY_MANIFEST_BINDS_EXACT_DECLARED_ARTIFACT_DEPENDENCIES",
            "RENDER_INPUT_MANIFEST_SHA256_MATCHES_REFERENCED_BYTES",
            "RENDER_INPUT_MANIFEST_BINDS_EXACT_ASSET_REFS_AND_SHA256S",
            "RENDER_COMPOSITION_SHA256_MATCHES_REFERENCED_BYTES",
            "RENDER_COMMAND_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES",
            "VIDEO_BYTES_INCLUDE_THE_REFERENCED_AUDIO_STREAM",
            "RENDER_TRACE_SHA256_MATCHES_REFERENCED_TRACE",
            "RENDERED_SHOT_IDS_EQUAL_MOTION_IR_SHOT_IDS",
            "RENDERED_OBJECT_IDS_EQUAL_MOTION_IR_OBJECT_IDS",
            "RENDERED_MOTION_CURVE_IDS_EQUAL_MOTION_IR_CURVE_IDS",
            "RENDERED_SEMANTIC_BINDINGS_EQUAL_MOTION_IR_OBJECT_BINDINGS",
            "RENDER_TRACE_SAMPLES_MATCH_DECLARED_OBJECT_CURVES",
        ]

    elif artifact_kind == "MEDIA_ACCEPTANCE_RECEIPT":
        _require_schema_fields(
            schema,
            [
                "video_ref",
                "video_sha256",
                "audio_sha256",
                "ffprobe_receipt_ref",
                "ffprobe_receipt_sha256",
                "render_receipt_ref",
                "render_receipt_sha256",
                "tts_receipt_ref",
                "tts_receipt_sha256",
                "alignment_receipt_ref",
                "alignment_receipt_sha256",
                "dependency_manifest_ref",
                "dependency_manifest_sha256",
                "duration_seconds",
                "width",
                "height",
                "fps",
                "audio_stream_count",
                "max_anchor_error_seconds",
                "final_av_drift_frames",
                "motion_probe_ref",
                "motion_probe_sha256",
                "observed_dynamic_frame_count",
                "observed_scene_transition_count",
                "expected_scene_transition_count",
                "observed_motion_objects",
            ],
        )
        for field in (
            "video_sha256",
            "audio_sha256",
            "ffprobe_receipt_sha256",
            "render_receipt_sha256",
            "tts_receipt_sha256",
            "alignment_receipt_sha256",
            "dependency_manifest_sha256",
            "motion_probe_sha256",
        ):
            properties[field] = {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            }
        for field in (
            "video_ref",
            "ffprobe_receipt_ref",
            "render_receipt_ref",
            "tts_receipt_ref",
            "alignment_receipt_ref",
            "dependency_manifest_ref",
            "motion_probe_ref",
        ):
            properties[field] = {"type": "string", "minLength": 1}
        properties["audio_stream_count"] = {
            "type": "integer",
            "minimum": 1,
        }
        properties["duration_seconds"] = {
            "type": "number",
            "minimum": 175,
            "maximum": 185,
        }
        properties["width"] = {"const": 1920}
        properties["height"] = {"const": 1080}
        properties["fps"] = {"const": 30}
        properties["max_anchor_error_seconds"] = {
            "type": "number",
            "minimum": 0,
        }
        properties["final_av_drift_frames"] = {
            "type": "number",
        }
        properties["observed_dynamic_frame_count"] = {
            "type": "integer",
            "minimum": 0,
        }
        properties["observed_scene_transition_count"] = {
            "type": "integer",
            "minimum": 1,
        }
        properties["expected_scene_transition_count"] = {
            "type": "integer",
            "minimum": 1,
        }
        properties["observed_motion_objects"] = {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "object_id",
                    "asset_id",
                    "sentence_ids",
                    "claim_ids",
                    "visual_intent_id",
                    "audio_anchor_id",
                    "motion_segment_ids",
                    "motion_curve_ids",
                    "first_dynamic_frame",
                    "last_dynamic_frame",
                    "changed_frame_count",
                    "max_visual_delta",
                    "probe_ref",
                    "probe_sha256",
                ],
                "properties": {
                    "object_id": {"type": "string", "minLength": 1},
                    "asset_id": {"type": "string", "minLength": 1},
                    "sentence_ids": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "claim_ids": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "visual_intent_id": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "audio_anchor_id": {"type": "string", "minLength": 1},
                    "motion_segment_ids": {
                        "type": "array",
                        "minItems": 3,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "motion_curve_ids": {
                        "type": "array",
                        "minItems": 3,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "first_dynamic_frame": {"type": "integer", "minimum": 0},
                    "last_dynamic_frame": {"type": "integer", "minimum": 1},
                    "changed_frame_count": {"type": "integer", "minimum": 0},
                    "max_visual_delta": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                    },
                    "probe_ref": {"type": "string", "minLength": 1},
                    "probe_sha256": {
                        "type": "string",
                        "pattern": "^[0-9a-f]{64}$",
                    },
                },
            },
        }
        schema["x-invariants"] = [
            "FFPROBE_INPUT_SHA256_EQUALS_VIDEO_SHA256",
            "FFPROBE_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES",
            "RENDER_RECEIPT_VIDEO_SHA256_EQUALS_VIDEO_SHA256",
            "MEDIA_RENDER_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES",
            "MEDIA_TTS_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES",
            "MEDIA_ALIGNMENT_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES",
            "DEPENDENCY_MANIFEST_SHA256_MATCHES_REFERENCED_BYTES",
            "DEPENDENCY_MANIFEST_BINDS_EXACT_DECLARED_ARTIFACT_DEPENDENCIES",
            "RENDER_TTS_ALIGNMENT_AND_MEDIA_AUDIO_SHA256_ARE_EQUAL",
            "RECOMPUTED_ANCHOR_ERROR_DOES_NOT_EXCEED_0_1_SECONDS",
            "ABSOLUTE_FINAL_AV_DRIFT_DOES_NOT_EXCEED_ONE_FRAME",
            "MOTION_PROBE_SHA256_MATCHES_REFERENCED_PROBE",
            "OBSERVED_DYNAMIC_FRAME_COUNT_IS_NONZERO",
            "OBSERVED_SCENE_TRANSITION_COUNT_EQUALS_EXPECTED_SCENE_TRANSITION_COUNT",
            "MOTION_PROBE_BINDS_FINAL_VIDEO_SHA256_AND_MOTION_IR_SHA256",
            "OBSERVED_MOTION_OBJECT_IDS_EQUAL_MOTION_IR_OBJECT_IDS",
            "OBSERVED_MOTION_CURVE_IDS_EQUAL_MOTION_IR_CURVE_IDS",
            "OBSERVED_MOTION_SEMANTIC_BINDINGS_EQUAL_RENDERED_AND_MOTION_BINDINGS",
            "EACH_DECLARED_OBJECT_HAS_NONZERO_PROBED_MOTION",
            "EVERY_OBJECT_MOTION_PROBE_HASH_MATCHES_REFERENCED_PROBE",
        ]

    elif artifact_kind == "RESUMABLE_STAGE_RECEIPT":
        hash_schema = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
        hash_map_schema = {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": deepcopy(hash_schema),
        }
        id_array_schema = {
            "type": "array",
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
        }
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "stage_id",
                "stage_index",
                "previous_stage_id",
                "required_stage_ids",
                "stage_receipt_set_id",
                "input_hashes",
                "input_manifest_sha256",
                "output_hashes",
                "output_manifest_sha256",
                "previous_event_hash",
                "event_payload_sha256",
                "event_hash",
                "receipt_input_hashes_sha256",
                "current_input_hashes_sha256",
                "receipt_invalidated",
                "completed_side_effect_ids",
                "attempted_side_effect_ids",
                "completed_idempotency_keys",
                "attempted_idempotency_keys",
                "authority_ref",
                "side_effects_started",
                "evidence_state",
                "generation_state",
                "execution_state",
                "resume_decision",
                "status",
            ],
            "properties": {
                "stage_id": {"enum": list(RESUMABLE_STAGE_ORDER)},
                "stage_index": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": len(RESUMABLE_STAGE_ORDER) - 1,
                },
                "previous_stage_id": {
                    "type": ["string", "null"],
                    "enum": [None, *RESUMABLE_STAGE_ORDER],
                },
                "required_stage_ids": {"const": list(RESUMABLE_STAGE_ORDER)},
                "stage_receipt_set_id": {"type": "string", "minLength": 1},
                "input_hashes": deepcopy(hash_map_schema),
                "input_manifest_sha256": deepcopy(hash_schema),
                "output_hashes": deepcopy(hash_map_schema),
                "output_manifest_sha256": deepcopy(hash_schema),
                "previous_event_hash": {
                    "type": ["string", "null"],
                    "pattern": "^[0-9a-f]{64}$",
                },
                "event_payload_sha256": deepcopy(hash_schema),
                "event_hash": deepcopy(hash_schema),
                "receipt_input_hashes_sha256": deepcopy(hash_schema),
                "current_input_hashes_sha256": deepcopy(hash_schema),
                "receipt_invalidated": {"type": "boolean"},
                "completed_side_effect_ids": deepcopy(id_array_schema),
                "attempted_side_effect_ids": deepcopy(id_array_schema),
                "completed_idempotency_keys": deepcopy(id_array_schema),
                "attempted_idempotency_keys": deepcopy(id_array_schema),
                "authority_ref": {
                    "type": ["string", "null"],
                    "minLength": 1,
                },
                "side_effects_started": {"type": "boolean"},
                "evidence_state": {
                    "enum": [
                        "EVIDENCE_NOT_STARTED",
                        "EVIDENCE_VERIFIED",
                        "EVIDENCE_INVALIDATED",
                    ]
                },
                "generation_state": {
                    "enum": [
                        "GENERATION_NOT_STARTED",
                        "GENERATION_PLANNED",
                        "GENERATION_COMPLETED",
                        "GENERATION_INVALIDATED",
                    ]
                },
                "execution_state": {
                    "enum": [
                        "EXECUTION_NOT_STARTED",
                        "EXECUTION_BLOCKED_AUTHORITY",
                        "EXECUTION_COMPLETED",
                        "EXECUTION_INVALIDATED",
                    ]
                },
                "resume_decision": {
                    "enum": [
                        "REUSE_VALID_RECEIPT",
                        "RERUN_INVALIDATED_STAGE",
                        "STOP_FOR_AUTHORITY",
                    ]
                },
                "status": {
                    "enum": [
                        "REUSED_VALID_RECEIPT",
                        "RERUN_REQUIRED_INPUT_CHANGED_OR_INVALID",
                        "STOPPED_FOR_AUTHORITY",
                    ]
                },
            },
            "oneOf": [
                {
                    "properties": {
                        "resume_decision": {"const": "REUSE_VALID_RECEIPT"},
                        "status": {"const": "REUSED_VALID_RECEIPT"},
                    }
                },
                {
                    "properties": {
                        "resume_decision": {
                            "const": "RERUN_INVALIDATED_STAGE"
                        },
                        "status": {
                            "const": "RERUN_REQUIRED_INPUT_CHANGED_OR_INVALID"
                        },
                    }
                },
                {
                    "properties": {
                        "resume_decision": {"const": "STOP_FOR_AUTHORITY"},
                        "status": {"const": "STOPPED_FOR_AUTHORITY"},
                    }
                },
            ],
            "x-invariants": [
                "INPUT_MANIFEST_SHA256_MATCHES_CANONICAL_INPUT_HASHES",
                "OUTPUT_MANIFEST_SHA256_MATCHES_CANONICAL_OUTPUT_HASHES",
                "EVENT_PAYLOAD_SHA256_MATCHES_CANONICAL_STAGE_EVENT",
                "EVENT_HASH_RECOMPUTES_FROM_PREVIOUS_HASH_AND_CANONICAL_EVENT_PAYLOAD",
                "REUSE_VALID_RECEIPT_REQUIRES_EXACT_CURRENT_INPUT_HASHES",
                "RERUN_INVALIDATED_STAGE_REQUIRES_CHANGED_OR_INVALIDATED_INPUT",
                "STOP_FOR_AUTHORITY_HAS_NO_SIDE_EFFECT_ATTEMPT",
                "COMPLETED_SIDE_EFFECTS_AND_IDEMPOTENCY_KEYS_ARE_NOT_REPLAYED",
                "STAGE_ID_AND_INDEX_MATCH_FROZEN_STAGE_EXPECTATION",
                "PREVIOUS_STAGE_ID_MATCHES_FROZEN_STAGE_ORDER",
            ],
        }
        properties = schema["properties"]

    elif artifact_kind == "FIXTURE_ACCEPTANCE_RECEIPT":
        hash_field = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "acceptance_case_manifest_ref",
                "acceptance_case_manifest_sha256",
                "negative_case_manifest_ref",
                "negative_case_manifest_sha256",
                "acceptance_case_results",
                "fixture_results",
                "negative_case_results",
                "oracle_evaluator_registry_ref",
                "oracle_evaluator_registry_sha256",
                "invariant_negative_case_results",
                "schema_native_negative_case_results",
                "isolation_policy",
                "execution_started",
                "status",
            ],
            "properties": {
                "acceptance_case_manifest_ref": {
                    "const": (
                        "harness-resource://candidate/validation/"
                        "ACCEPTANCE_CASES.json"
                    )
                },
                "acceptance_case_manifest_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "negative_case_manifest_ref": {
                    "const": (
                        "harness-resource://candidate/validation/"
                        "NEGATIVE_CASES.json"
                    )
                },
                "negative_case_manifest_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "acceptance_case_results": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "case_id",
                            "result_ref",
                            "result_sha256",
                            "oracle_decision",
                            "status",
                        ],
                        "properties": {
                            "case_id": {"type": "string", "minLength": 1},
                            "result_ref": {"type": "string", "minLength": 1},
                            "result_sha256": {
                                "type": "string",
                                "pattern": "^[0-9a-f]{64}$",
                            },
                            "oracle_decision": {"const": "PASS"},
                            "status": {"const": "PASS"},
                        },
                    },
                },
                "fixture_results": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 3,
                    "uniqueItems": True,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "fixture_id",
                            "source_id",
                            "job_id",
                            "repository_url",
                            "commit_sha",
                            "input_skill_count",
                            "output_count",
                            "case_result_ref",
                            "case_result_sha256",
                            "video_ref",
                            "video_sha256",
                            "expected_function",
                            "expected_scenario",
                            "expected_effect",
                            "demo_contract_ref",
                            "oracle_decision",
                            "status",
                        ],
                        "properties": {
                            "fixture_id": {"type": "string", "minLength": 1},
                            "source_id": {"type": "string", "minLength": 1},
                            "job_id": {"type": "string", "minLength": 1},
                            "repository_url": {"type": "string", "minLength": 1},
                            "commit_sha": {
                                "type": "string",
                                "pattern": "^[0-9a-f]{40}$",
                            },
                            "input_skill_count": {"const": 1},
                            "output_count": {"const": 1},
                            "case_result_ref": {"type": "string", "minLength": 1},
                            "case_result_sha256": {
                                "type": "string",
                                "pattern": "^[0-9a-f]{64}$",
                            },
                            "video_ref": {"type": "string", "minLength": 1},
                            "video_sha256": {
                                "type": "string",
                                "pattern": "^[0-9a-f]{64}$",
                            },
                            "expected_function": {
                                "type": "string",
                                "minLength": 1,
                            },
                            "expected_scenario": {
                                "type": "string",
                                "minLength": 1,
                            },
                            "expected_effect": {
                                "type": "string",
                                "minLength": 1,
                            },
                            "demo_contract_ref": {
                                "type": "string",
                                "minLength": 1,
                            },
                            "oracle_decision": {"const": "PASS"},
                            "status": {"const": "PASS"},
                        },
                    },
                },
                "negative_case_results": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "case_id",
                            "result_ref",
                            "result_sha256",
                            "mutation_manifest_ref",
                            "mutation_manifest_sha256",
                            "mutation_variant_results",
                            "expected_failure_observed",
                            "observed_failure_code",
                            "side_effect_receipt_ref",
                            "side_effect_receipt_sha256",
                            "side_effects_started",
                            "oracle_decision",
                            "status",
                        ],
                        "properties": {
                            "case_id": {"type": "string", "minLength": 1},
                            "result_ref": {"type": "string", "minLength": 1},
                            "result_sha256": {
                                "type": "string",
                                "pattern": "^[0-9a-f]{64}$",
                            },
                            "mutation_manifest_ref": {
                                "type": "string",
                                "minLength": 1,
                            },
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
                                        "variant_id": {
                                            "type": "string",
                                            "minLength": 1,
                                        },
                                        "base_input_ref": {
                                            "type": "string",
                                            "minLength": 1,
                                        },
                                        "base_input_sha256": deepcopy(hash_field),
                                        "mutated_input_ref": {
                                            "type": "string",
                                            "minLength": 1,
                                        },
                                        "mutated_input_sha256": deepcopy(hash_field),
                                        "mutation_receipt_ref": {
                                            "type": "string",
                                            "minLength": 1,
                                        },
                                        "mutation_receipt_sha256": deepcopy(hash_field),
                                        "command_receipt_ref": {
                                            "type": "string",
                                            "minLength": 1,
                                        },
                                        "command_receipt_sha256": deepcopy(hash_field),
                                        "validator_finding_ref": {
                                            "type": "string",
                                            "minLength": 1,
                                        },
                                        "validator_finding_sha256": deepcopy(hash_field),
                                        "side_effect_receipt_ref": {
                                            "type": "string",
                                            "minLength": 1,
                                        },
                                        "side_effect_receipt_sha256": deepcopy(hash_field),
                                        "observed_failure_code": {
                                            "type": "string",
                                            "minLength": 1,
                                        },
                                        "expected_failure_observed": {"const": True},
                                        "side_effects_started": {"const": False},
                                        "status": {"const": "PASS"},
                                    },
                                },
                            },
                            "expected_failure_observed": {"const": True},
                            "observed_failure_code": {
                                "type": "string",
                                "minLength": 1,
                            },
                            "side_effect_receipt_ref": {
                                "type": "string",
                                "minLength": 1,
                            },
                            "side_effect_receipt_sha256": deepcopy(hash_field),
                            "side_effects_started": {"const": False},
                            "oracle_decision": {"const": "PASS"},
                            "status": {"const": "PASS"},
                        },
                    },
                },
                "oracle_evaluator_registry_ref": {
                    "const": ORACLE_EVALUATOR_REGISTRY_REF
                },
                "oracle_evaluator_registry_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "invariant_negative_case_results": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "case_id",
                            "artifact_kind",
                            "evaluator_id",
                            "invariant_id",
                            "schema_instance_results",
                        ],
                        "properties": {
                            "case_id": {"type": "string", "minLength": 1},
                            "artifact_kind": {
                                "type": "string",
                                "minLength": 1,
                            },
                            "evaluator_id": {
                                "type": "string",
                                "minLength": 1,
                            },
                            "invariant_id": {
                                "type": "string",
                                "minLength": 1,
                            },
                            "schema_instance_results": {
                                "type": "array",
                                "minItems": 1,
                                "uniqueItems": True,
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": [
                                        "schema_sha256",
                                        "result_ref",
                                        "result_sha256",
                                        "base_schema_pass",
                                        "base_oracle_pass",
                                        "mutated_schema_pass",
                                        "observed_failure_code",
                                        "side_effects_started",
                                        "status",
                                    ],
                                    "properties": {
                                        "schema_sha256": {
                                            "type": "string",
                                            "pattern": "^[0-9a-f]{64}$",
                                        },
                                        "result_ref": {
                                            "type": "string",
                                            "minLength": 1,
                                        },
                                        "result_sha256": {
                                            "type": "string",
                                            "pattern": "^[0-9a-f]{64}$",
                                        },
                                        "base_schema_pass": {
                                            "type": "boolean"
                                        },
                                        "base_oracle_pass": {
                                            "type": "boolean"
                                        },
                                        "mutated_schema_pass": {
                                            "type": "boolean"
                                        },
                                        "observed_failure_code": {
                                            "type": "string",
                                            "minLength": 1,
                                        },
                                        "side_effects_started": {
                                            "type": "boolean"
                                        },
                                        "status": {"const": "PASS"},
                                    },
                                },
                            },
                        },
                    },
                },
                "schema_native_negative_case_results": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "case_id",
                            "artifact_kind",
                            "constraint_id",
                            "schema_instance_results",
                        ],
                        "properties": {
                            "case_id": {"type": "string", "minLength": 1},
                            "artifact_kind": {
                                "type": "string",
                                "minLength": 1,
                            },
                            "constraint_id": {
                                "type": "string",
                                "minLength": 1,
                            },
                            "schema_instance_results": {
                                "type": "array",
                                "minItems": 1,
                                "uniqueItems": True,
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": [
                                        "schema_sha256",
                                        "result_ref",
                                        "result_sha256",
                                        "base_schema_pass",
                                        "mutated_schema_pass",
                                        "oracle_started",
                                        "observed_failure_code",
                                        "side_effects_started",
                                        "status",
                                    ],
                                    "properties": {
                                        "schema_sha256": {
                                            "type": "string",
                                            "pattern": "^[0-9a-f]{64}$",
                                        },
                                        "result_ref": {
                                            "type": "string",
                                            "minLength": 1,
                                        },
                                        "result_sha256": {
                                            "type": "string",
                                            "pattern": "^[0-9a-f]{64}$",
                                        },
                                        "base_schema_pass": {
                                            "type": "boolean"
                                        },
                                        "mutated_schema_pass": {
                                            "type": "boolean"
                                        },
                                        "oracle_started": {
                                            "type": "boolean"
                                        },
                                        "observed_failure_code": {
                                            "type": "string",
                                            "minLength": 1,
                                        },
                                        "side_effects_started": {
                                            "type": "boolean"
                                        },
                                        "status": {"const": "PASS"},
                                    },
                                },
                            },
                        },
                    },
                },
                "isolation_policy": {
                    "const": "ONE_REPOSITORY_ONE_JOB_ONE_VIDEO"
                },
                "execution_started": {"const": True},
                "status": {"const": "PASS"},
            },
        }
        if repository_jobs:
            fixture_results = schema["properties"]["fixture_results"]
            fixture_results["minItems"] = len(repository_jobs)
            fixture_results["maxItems"] = len(repository_jobs)
            schema["allOf"] = [
                {
                    "properties": {
                        "fixture_results": {
                            "contains": {
                                "type": "object",
                                "properties": {
                                    "job_id": {"const": job["job_id"]},
                                    "source_id": {"const": job["source_id"]},
                                    "repository_url": {
                                        "const": job["repository_url"]
                                    },
                                    "commit_sha": {"const": job["commit_sha"]},
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
                    }
                }
                for job in repository_jobs
            ]
        acceptance_case_specs = [
            dict(case)
            for case in acceptance_cases or []
            if isinstance(case, Mapping) and case.get("case_id")
        ]
        negative_case_specs = [
            dict(case)
            for case in negative_cases or []
            if isinstance(case, Mapping) and case.get("case_id")
        ]
        if acceptance_case_specs:
            acceptance_results = schema["properties"]["acceptance_case_results"]
            acceptance_results["minItems"] = len(acceptance_case_specs)
            acceptance_results["maxItems"] = len(acceptance_case_specs)
            schema.setdefault("allOf", []).extend(
                {
                    "properties": {
                        "acceptance_case_results": {
                            "contains": {
                                "type": "object",
                                "properties": {
                                    "case_id": {"const": case["case_id"]}
                                },
                                "required": ["case_id"],
                            },
                            "minContains": 1,
                            "maxContains": 1,
                        }
                    }
                }
                for case in acceptance_case_specs
            )
        if negative_case_specs:
            negative_results = schema["properties"]["negative_case_results"]
            negative_results["minItems"] = len(negative_case_specs)
            negative_results["maxItems"] = len(negative_case_specs)
            schema.setdefault("allOf", []).extend(
                {
                    "properties": {
                        "negative_case_results": {
                            "contains": {
                                "type": "object",
                                "properties": {
                                    "case_id": {"const": case["case_id"]},
                                    "observed_failure_code": {
                                        "const": str(
                                            case.get("expected_failure")
                                            or "EXPECTED_REJECTION"
                                        )
                                    },
                                },
                                "required": [
                                    "case_id",
                                    "observed_failure_code",
                                ],
                            },
                            "minContains": 1,
                            "maxContains": 1,
                        }
                    }
                }
                for case in negative_case_specs
            )
        schema["x-invariants"] = [
            "FIXTURE_RESULT_JOB_IDS_EQUAL_FROZEN_REPOSITORY_JOB_IDS",
            "FIXTURE_RESULT_SOURCE_IDS_EQUAL_FROZEN_REPOSITORY_SOURCE_IDS",
            "EXPECTED_FUNCTION_SCENARIO_EFFECT_RESOLVE_TO_JOB_CLAIM_MATRIX",
            "DEMO_CONTRACT_REF_RESOLVES_TO_SAME_JOB_BEFORE_AFTER_CONTRACT",
            "EVERY_FIXTURE_CASE_RESULT_SHA256_MATCHES_REFERENCED_BYTES",
            "EVERY_FIXTURE_VIDEO_SHA256_MATCHES_REFERENCED_BYTES",
            "ACCEPTANCE_CASE_RESULT_IDS_EQUAL_FROZEN_ACCEPTANCE_CASE_IDS",
            "ACCEPTANCE_CASE_RESULT_REFS_EQUAL_FROZEN_CASE_RESULT_REFS",
            "EVERY_ACCEPTANCE_CASE_RESULT_SHA256_MATCHES_REFERENCED_BYTES",
            "NEGATIVE_CASE_RESULT_IDS_EQUAL_COMPLETE_NEGATIVE_CASE_IDS",
            "NEGATIVE_CASE_RESULT_REFS_EQUAL_FROZEN_CASE_RESULT_REFS",
            "EVERY_NEGATIVE_CASE_RESULT_SHA256_MATCHES_REFERENCED_BYTES",
            "EVERY_NEGATIVE_RESULT_OBSERVES_EXPECTED_FAILURE_WITHOUT_SIDE_EFFECTS",
            "NEGATIVE_MUTATION_MANIFEST_HASH_MATCHES_REFERENCED_VARIANTS",
            "NEGATIVE_MUTATION_VARIANT_RESULT_IDS_EQUAL_DECLARED_VARIANT_IDS",
            "EVERY_NEGATIVE_MUTATION_VARIANT_HAS_HASH_BOUND_EXECUTION_EVIDENCE",
            "CASE_MANIFEST_HASHES_MATCH_REFERENCED_CANDIDATE_CASE_DOCUMENTS",
            "ORACLE_EVALUATOR_REGISTRY_HASH_MATCHES_REFERENCED_BYTES",
            "INVARIANT_NEGATIVE_CASE_RESULT_IDS_EQUAL_REGISTRY_CASE_IDS",
            "INVARIANT_NEGATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS",
            "EVERY_INVARIANT_NEGATIVE_RESULT_SHA256_MATCHES_REFERENCED_BYTES",
            "EVERY_INVARIANT_RESULT_COVERS_EXACT_APPLICABLE_SCHEMA_SHA256S",
            "EVERY_INVARIANT_MUTATION_PRESERVES_JSON_SCHEMA_AND_FAILS_DECLARED_INVARIANT",
            "SCHEMA_NATIVE_NEGATIVE_CASE_RESULT_IDS_EQUAL_REGISTRY_CASE_IDS",
            "SCHEMA_NATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS",
            "EVERY_SCHEMA_NATIVE_RESULT_SHA256_MATCHES_REFERENCED_BYTES",
            "EVERY_SCHEMA_NATIVE_MUTATION_FAILS_SCHEMA_WITHOUT_ORACLE_OR_SIDE_EFFECTS",
        ]

    elif artifact_kind == "AUTHORING_STOP_RECEIPT":
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "authoring_state",
                "authoring_execution_mode",
                "authoring_workpack_started",
                "authoring_driver_started",
                "authoring_harness_started",
                "authoring_model_downloaded",
                "authoring_media_rendered",
                "candidate_human_review_closure_ref",
                "candidate_human_review_closure_sha256",
                "status",
            ],
            "properties": {
                "authoring_state": {
                    "const": "START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW"
                },
                "authoring_execution_mode": {
                    "enum": ["AUTHORING_ONLY", "RUNTIME_EXECUTION"]
                },
                "authoring_workpack_started": {"const": False},
                "authoring_driver_started": {"const": False},
                "authoring_harness_started": {"const": False},
                "authoring_model_downloaded": {"const": False},
                "authoring_media_rendered": {"const": False},
                "candidate_human_review_closure_ref": {
                    "type": "string",
                    "minLength": 1,
                },
                "candidate_human_review_closure_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "status": {"const": "PASS"},
            },
            "x-invariants": [
                "AUTHORING_FIELDS_DESCRIBE_THE_IMMUTABLE_CANDIDATE_HANDOFF_NOT_CURRENT_RUNTIME_STATE",
                "HUMAN_REVIEW_CLOSURE_HASH_MATCHES_REFERENCED_CLOSURE_RECEIPT",
            ],
        }

    if schema.get("x-invariants"):
        _bind_invariant_evaluation_contracts(schema)
    return schema


def _bind_artifact_dependencies(requirement_ir: dict[str, Any]) -> None:
    workpack_order = {
        "LAB-PROTOCOL": 0,
        "LAB-CLI": 0,
        "LAB-FIXTURES": 0,
        "LAB-SELFTEST": 0,
        "MB-G0": 0,
        "MB-P1": 1,
        "MB-P2": 2,
        "MB-P3": 3,
        "MB-P4": 4,
        "MB-RELEASE-CANDIDATE": 5,
        "LAB-CERTIFICATION": 100,
    }
    records: list[tuple[str, dict[str, Any]]] = []
    for atom in requirement_ir.get("atoms", []):
        contract = atom.get("production_contract") if isinstance(atom, Mapping) else None
        if not isinstance(contract, Mapping):
            continue
        for obligation in contract.get("workpack_obligations", []):
            if not isinstance(obligation, Mapping):
                continue
            workpack_id = str(obligation.get("workpack_id") or "")
            for artifact in obligation.get("artifact_obligations", []):
                if not isinstance(artifact, dict):
                    continue
                records.append((workpack_id, artifact))

    def latest_ids(
        kind: str, not_after: str, job_id: str | None
    ) -> list[str]:
        maximum = workpack_order.get(not_after, -1)
        candidates = [
            (workpack_order.get(workpack_id, -1), str(artifact["artifact_id"]))
            for workpack_id, artifact in records
            if artifact.get("artifact_kind") == kind
            and workpack_order.get(workpack_id, -1) <= maximum
            and (
                artifact.get("job_id") is None
                or artifact.get("job_id") == job_id
            )
        ]
        if not candidates:
            return []
        latest_rank = max(item[0] for item in candidates)
        return sorted(
            artifact_id
            for rank, artifact_id in candidates
            if rank == latest_rank
        )

    def dependencies(
        workpack_id: str,
        job_id: str | None,
        *artifact_kinds: str,
    ) -> list[str]:
        result: list[str] = []
        for artifact_kind in artifact_kinds:
            for artifact_id in latest_ids(artifact_kind, workpack_id, job_id):
                if artifact_id not in result:
                    result.append(artifact_id)
        return result

    def all_ids(*artifact_kinds: str) -> list[str]:
        return sorted(
            str(artifact["artifact_id"])
            for _workpack_id, artifact in records
            if str(artifact.get("artifact_kind") or "") in artifact_kinds
        )

    artifact_contracts = [artifact for _workpack_id, artifact in records]
    artifact_kinds = {
        str(artifact.get("artifact_kind") or "")
        for artifact in artifact_contracts
        if artifact.get("artifact_kind")
    }
    registry = oracle_evaluator_registry(artifact_kinds, artifact_contracts)
    certification_evidence_refs = [
        *[
            case_result_ref("ACCEPTANCE", str(case["case_id"]))
            for case in requirement_ir.get("acceptance_cases", [])
            if isinstance(case, Mapping) and case.get("case_id")
        ],
        *[
            case_result_ref("NEGATIVE", str(case["case_id"]))
            for case in negative_case_specs_with_mandatory_controls(
                requirement_ir
            )
            if case.get("case_id")
        ],
        *registry_case_result_refs(registry),
    ]
    certification_evidence_refs = sorted(
        dict.fromkeys(certification_evidence_refs)
    )

    for workpack_id, artifact in records:
        kind = artifact.get("artifact_kind")
        job_id = (
            str(artifact["job_id"])
            if isinstance(artifact.get("job_id"), str)
            else None
        )
        if kind == "ASSET_PLAN":
            artifact["depends_on_artifact_ids"] = dependencies(
                workpack_id,
                job_id,
                "SOURCE_FREEZE_RECEIPT",
                "FUNCTION_SCENARIO_EFFECT_MATRIX",
            )
        elif kind == "BEFORE_AFTER_DEMO_CONTRACT":
            artifact["depends_on_artifact_ids"] = dependencies(
                workpack_id,
                job_id,
                "SOURCE_FREEZE_RECEIPT",
                "FUNCTION_SCENARIO_EFFECT_MATRIX",
                "ASSET_PLAN",
                "TARGET_SKILL_EXECUTION_GATE_RECEIPT",
            )
        elif kind == "NARRATION_SCRIPT":
            artifact["depends_on_artifact_ids"] = dependencies(
                workpack_id,
                job_id,
                "SOURCE_FREEZE_RECEIPT",
                "FUNCTION_SCENARIO_EFFECT_MATRIX",
            )
        elif kind == "LOCAL_TTS_RECEIPT":
            artifact["depends_on_artifact_ids"] = dependencies(
                workpack_id,
                job_id,
                "SOURCE_FREEZE_RECEIPT",
                "FUNCTION_SCENARIO_EFFECT_MATRIX",
                "NARRATION_SCRIPT",
            )
        elif kind == "AUDIO_ALIGNMENT_RECEIPT":
            artifact["depends_on_artifact_ids"] = dependencies(
                workpack_id,
                job_id,
                "NARRATION_SCRIPT",
                "LOCAL_TTS_RECEIPT",
            )
        elif kind == "OBJECT_MOTION_IR":
            artifact["depends_on_artifact_ids"] = dependencies(
                workpack_id,
                job_id,
                "AUDIO_ALIGNMENT_RECEIPT",
                "ASSET_PLAN",
                "NARRATION_SCRIPT",
                "FUNCTION_SCENARIO_EFFECT_MATRIX",
            )
        elif kind == "ASSET_BINDING_RECEIPT":
            artifact["depends_on_artifact_ids"] = dependencies(
                workpack_id,
                job_id,
                "ASSET_PLAN",
                "NARRATION_SCRIPT",
                "FUNCTION_SCENARIO_EFFECT_MATRIX",
                "OBJECT_MOTION_IR",
            )
        elif kind == "LOCAL_RENDER_RECEIPT":
            artifact["depends_on_artifact_ids"] = dependencies(
                workpack_id,
                job_id,
                "SOURCE_FREEZE_RECEIPT",
                "FUNCTION_SCENARIO_EFFECT_MATRIX",
                "NARRATION_SCRIPT",
                "LOCAL_TTS_RECEIPT",
                "AUDIO_ALIGNMENT_RECEIPT",
                "OBJECT_MOTION_IR",
                "ASSET_PLAN",
                "ASSET_BINDING_RECEIPT",
                "BEFORE_AFTER_DEMO_CONTRACT",
                "TARGET_SKILL_EXECUTION_GATE_RECEIPT",
            )
        elif kind == "MEDIA_ACCEPTANCE_RECEIPT":
            artifact["depends_on_artifact_ids"] = dependencies(
                workpack_id,
                job_id,
                "LOCAL_RENDER_RECEIPT",
                "NARRATION_SCRIPT",
                "LOCAL_TTS_RECEIPT",
                "AUDIO_ALIGNMENT_RECEIPT",
                "OBJECT_MOTION_IR",
                "ASSET_PLAN",
                "ASSET_BINDING_RECEIPT",
                "BEFORE_AFTER_DEMO_CONTRACT",
                "SOURCE_FREEZE_RECEIPT",
                "FUNCTION_SCENARIO_EFFECT_MATRIX",
                "TARGET_SKILL_EXECUTION_GATE_RECEIPT",
            )
        elif kind == "FIXTURE_ACCEPTANCE_RECEIPT":
            artifact["depends_on_artifact_ids"] = sorted(
                str(candidate["artifact_id"])
                for _candidate_workpack_id, candidate in records
                if candidate is not artifact
                and candidate.get("artifact_id")
            )
            artifact["depends_on_evidence_refs"] = list(
                certification_evidence_refs
            )
            artifact["case_evidence_ownership"] = {
                "writer_workpack_id": CASE_EVIDENCE_WRITER_WORKPACK_ID,
                "result_root_ref": CASE_EXECUTION_RESULT_ROOT_REF,
                "writer_cardinality": "EXACTLY_ONE_WORKPACK",
                "consumer_requires_hash_bound_bytes": True,
            }
        elif kind == "RESUMABLE_STAGE_RECEIPT":
            stage_dependencies = {
                "SOURCE": ("SOURCE_FREEZE_RECEIPT",),
                "REASONING": ("FUNCTION_SCENARIO_EFFECT_MATRIX",),
                "NARRATION": ("NARRATION_SCRIPT",),
                "TTS": ("LOCAL_TTS_RECEIPT",),
                "ALIGNMENT": ("AUDIO_ALIGNMENT_RECEIPT",),
                "ASSETS": ("ASSET_PLAN",),
                "MOTION_IR": ("OBJECT_MOTION_IR",),
                "RENDER": ("LOCAL_RENDER_RECEIPT",),
                "SYNCHRONIZATION": (
                    "AUDIO_ALIGNMENT_RECEIPT",
                    "LOCAL_RENDER_RECEIPT",
                ),
                "TECHNICAL_QA": ("MEDIA_ACCEPTANCE_RECEIPT",),
                "CONTENT_QA": (
                    "BEFORE_AFTER_DEMO_CONTRACT",
                    "MEDIA_ACCEPTANCE_RECEIPT",
                ),
                "PACKAGING": (
                    "MEDIA_ACCEPTANCE_RECEIPT",
                    "BEFORE_AFTER_DEMO_CONTRACT",
                ),
            }
            existing = list(artifact.get("depends_on_artifact_ids") or [])
            for artifact_id in dependencies(
                workpack_id,
                job_id,
                *stage_dependencies.get(
                    str(artifact.get("expected_stage_id") or ""), ()
                ),
            ):
                if artifact_id not in existing:
                    existing.append(artifact_id)
            artifact["depends_on_artifact_ids"] = existing


def build_composite_dependency_graph(
    artifact_index: Mapping[str, Any],
) -> dict[str, Any]:
    """Join artifact, Workpack capability, engineering, and release dependencies."""

    nodes: dict[str, dict[str, str]] = {}
    edges: dict[tuple[str, str, str], dict[str, str]] = {}

    def node(node_id: str, kind: str, label: str) -> None:
        nodes.setdefault(
            node_id,
            {"node_id": node_id, "node_kind": kind, "label": label},
        )

    def edge(source: str, target: str, edge_kind: str) -> None:
        if source == target:
            return
        edges.setdefault(
            (source, target, edge_kind),
            {"from_node_id": source, "to_node_id": target, "edge_kind": edge_kind},
        )

    def capability(value: str) -> str:
        node_id = f"CAPABILITY:{value}"
        node(node_id, "CAPABILITY", value)
        return node_id

    def workpack(value: str) -> str:
        node_id = f"WORKPACK:{value}"
        node(node_id, "WORKPACK", value)
        return node_id

    def engineering_project(value: str) -> str:
        node_id = f"ENGINEERING_PROJECT:{value}"
        node(node_id, "ENGINEERING_PROJECT", value)
        return node_id

    def engineering_node(value: str) -> str:
        node_id = f"ENGINEERING_NODE:{value}"
        node(node_id, "ENGINEERING_NODE", value)
        return node_id

    def release_step(value: str) -> str:
        node_id = f"RELEASE_STEP:{value}"
        node(node_id, "RELEASE_STEP", value)
        return node_id

    artifacts_by_workpack: dict[str, list[str]] = {}
    for artifact_id, raw_artifact in sorted(artifact_index.items()):
        if not isinstance(raw_artifact, Mapping):
            continue
        artifact_node = f"ARTIFACT:{artifact_id}"
        node(artifact_node, "ARTIFACT", str(artifact_id))
        workpack_id = str(raw_artifact.get("workpack_id") or "")
        artifacts_by_workpack.setdefault(workpack_id, []).append(artifact_node)
        for dependency_id in raw_artifact.get("depends_on_artifact_ids", []):
            dependency_node = f"ARTIFACT:{dependency_id}"
            node(dependency_node, "ARTIFACT", str(dependency_id))
            edge(
                dependency_node,
                artifact_node,
                "ARTIFACT_REQUIRED_BY_ARTIFACT",
            )
        for evidence_ref in raw_artifact.get("depends_on_evidence_refs", []):
            evidence_node = f"EVIDENCE:{evidence_ref}"
            node(evidence_node, "EXECUTION_EVIDENCE", str(evidence_ref))
            edge(
                evidence_node,
                artifact_node,
                "EXECUTION_EVIDENCE_REQUIRED_BY_ARTIFACT",
            )

    for workpack_id, contract in sorted(PROJECT_WORKPACK_CONTRACTS.items()):
        workpack_node = workpack(workpack_id)
        project_node = engineering_project(str(contract["project_id"]))
        edge(
            project_node,
            workpack_node,
            "ENGINEERING_PROJECT_OWNS_WORKPACK",
        )
        artifact_nodes = artifacts_by_workpack.get(workpack_id, [])
        requires = [capability(str(value)) for value in contract["requires"]]
        produces = [capability(str(value)) for value in contract["produces"]]
        for required in requires:
            edge(required, workpack_node, "CAPABILITY_REQUIRED_BY_WORKPACK")
        if artifact_nodes:
            for artifact_node in artifact_nodes:
                edge(workpack_node, artifact_node, "WORKPACK_PRODUCES_ARTIFACT")
                for produced in produces:
                    edge(artifact_node, produced, "ARTIFACT_REQUIRED_FOR_CAPABILITY")
        else:
            for produced in produces:
                edge(workpack_node, produced, "WORKPACK_PRODUCES_CAPABILITY")

        for required_capability, source in contract["requirement_sources"].items():
            source_text = str(source)
            if source_text.startswith("PROJECT_WORKPACK:"):
                source_workpack = source_text.removeprefix("PROJECT_WORKPACK:")
                if source_workpack in PROJECT_WORKPACK_CONTRACTS:
                    edge(
                        workpack(source_workpack),
                        workpack_node,
                        "WORKPACK_DEPENDS_ON_WORKPACK",
                    )
            elif source_text.startswith("ENGINEERING_DAG:"):
                source_node_id = source_text.removeprefix("ENGINEERING_DAG:")
                source_node = engineering_node(source_node_id)
                edge(
                    source_node,
                    capability(str(required_capability)),
                    "ENGINEERING_NODE_PROVIDES_CAPABILITY",
                )
                bound_workpacks = [
                    value
                    for value in (
                        DAG_WORKPACK_BINDINGS.get(source_node_id),
                        *DAG_WORKPACK_SEQUENCE_BINDINGS.get(source_node_id, ()),
                    )
                    if value in PROJECT_WORKPACK_CONTRACTS
                ]
                for source_workpack in bound_workpacks:
                    source_artifacts = artifacts_by_workpack.get(
                        str(source_workpack), []
                    )
                    if source_artifacts:
                        for artifact_node in source_artifacts:
                            edge(
                                artifact_node,
                                source_node,
                                "ARTIFACT_COMPLETES_ENGINEERING_NODE",
                            )
                    else:
                        edge(
                            workpack(str(source_workpack)),
                            source_node,
                            "WORKPACK_COMPLETES_ENGINEERING_NODE",
                        )
            elif source_text.startswith("RELEASE_PIPELINE:"):
                source_step_id = source_text.removeprefix("RELEASE_PIPELINE:")
                if source_step_id in RELEASE_STEP_OUTPUT_CAPABILITIES:
                    edge(
                        release_step(source_step_id),
                        capability(str(required_capability)),
                        "RELEASE_STEP_PROVIDES_CAPABILITY",
                    )

    previous_output: str | None = None
    for step_id in RELEASE_STEP_ORDER:
        step_node = release_step(step_id)
        output = capability(RELEASE_STEP_OUTPUT_CAPABILITIES[step_id])
        prerequisites = (
            [previous_output]
            if previous_output is not None
            else [
                capability("P4_LOCAL_GATE_PASS"),
                capability("P3_BUILD_LOCK_OR_APPROVED_P3_NA_LOCK_VALID"),
                capability("C3_CHECKPOINT_PASS"),
            ]
        )
        for prerequisite in prerequisites:
            edge(prerequisite, step_node, "RELEASE_PIPELINE_SEQUENCE")
        edge(step_node, output, "RELEASE_STEP_PRODUCES_CAPABILITY")
        workpack_id = RELEASE_WORKPACK_BINDINGS.get(step_id)
        if workpack_id in PROJECT_WORKPACK_CONTRACTS:
            workpack_artifacts = artifacts_by_workpack.get(
                str(workpack_id), []
            )
            if workpack_artifacts:
                for artifact_node in workpack_artifacts:
                    edge(
                        artifact_node,
                        step_node,
                        "RELEASE_REQUIRES_ARTIFACT_COMPLETION",
                    )
            else:
                edge(
                    workpack(str(workpack_id)),
                    step_node,
                    "RELEASE_REQUIRES_WORKPACK_COMPLETION",
                )
        previous_output = output

    graph = {
        "schema_version": "1.0",
        "graph_kind": "ARTIFACT_WORKPACK_ENGINEERING_RELEASE_COMPOSITE",
        "edge_direction": "PREREQUISITE_TO_CONSUMER",
        "nodes": sorted(nodes.values(), key=lambda item: item["node_id"]),
        "edges": sorted(
            edges.values(),
            key=lambda item: (
                item["from_node_id"],
                item["to_node_id"],
                item["edge_kind"],
            ),
        ),
        "status": "ACYCLIC",
    }
    findings = validate_composite_dependency_graph(graph, artifact_index)
    if findings:
        raise ValueError(
            "composite dependency graph invalid: "
            + ",".join(sorted({str(item["code"]) for item in findings}))
        )
    graph["graph_sha256"] = _hash_without_field(graph, "graph_sha256")
    return graph


def validate_composite_dependency_graph(
    graph: Any,
    artifact_index: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Validate exact graph projection and reject cross-plane dependency cycles."""

    findings: list[dict[str, Any]] = []
    if not isinstance(graph, Mapping):
        return [_finding("COMPOSITE_DEPENDENCY_GRAPH_MISSING", "manifest")]
    if graph.get("edge_direction") != "PREREQUISITE_TO_CONSUMER":
        return [
            _finding(
                "COMPOSITE_DEPENDENCY_GRAPH_INVALID",
                "edge-direction",
            )
        ]
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return [_finding("COMPOSITE_DEPENDENCY_GRAPH_INVALID", "nodes-or-edges")]
    node_ids = {
        str(item.get("node_id"))
        for item in nodes
        if isinstance(item, Mapping) and item.get("node_id")
    }
    expected_artifact_nodes = {f"ARTIFACT:{value}" for value in artifact_index}
    expected_evidence_edges = {
        (
            f"EVIDENCE:{evidence_ref}",
            f"ARTIFACT:{artifact_id}",
            "EXECUTION_EVIDENCE_REQUIRED_BY_ARTIFACT",
        )
        for artifact_id, artifact in artifact_index.items()
        if isinstance(artifact, Mapping)
        for evidence_ref in artifact.get("depends_on_evidence_refs", [])
        if isinstance(evidence_ref, str) and evidence_ref
    }
    expected_artifact_dependency_edges = {
        (
            f"ARTIFACT:{dependency_id}",
            f"ARTIFACT:{artifact_id}",
            "ARTIFACT_REQUIRED_BY_ARTIFACT",
        )
        for artifact_id, artifact in artifact_index.items()
        if isinstance(artifact, Mapping)
        for dependency_id in artifact.get("depends_on_artifact_ids", [])
        if isinstance(dependency_id, str) and dependency_id
    }
    expected_evidence_nodes = {item[0] for item in expected_evidence_edges}
    expected_workpack_nodes = {
        f"WORKPACK:{value}" for value in PROJECT_WORKPACK_CONTRACTS
    }
    expected_project_nodes = {
        f"ENGINEERING_PROJECT:{contract['project_id']}"
        for contract in PROJECT_WORKPACK_CONTRACTS.values()
    }
    expected_engineering_nodes = {
        "ENGINEERING_NODE:" + str(source).removeprefix("ENGINEERING_DAG:")
        for contract in PROJECT_WORKPACK_CONTRACTS.values()
        for source in contract["requirement_sources"].values()
        if str(source).startswith("ENGINEERING_DAG:")
    }
    expected_release_nodes = {
        f"RELEASE_STEP:{value}" for value in RELEASE_STEP_ORDER
    }
    required_plane_nodes = (
        expected_artifact_nodes
        | expected_evidence_nodes
        | expected_workpack_nodes
        | expected_project_nodes
        | expected_engineering_nodes
        | expected_release_nodes
    )
    kind_prefixes = {
        "ARTIFACT": "ARTIFACT:",
        "EXECUTION_EVIDENCE": "EVIDENCE:",
        "CAPABILITY": "CAPABILITY:",
        "WORKPACK": "WORKPACK:",
        "ENGINEERING_PROJECT": "ENGINEERING_PROJECT:",
        "ENGINEERING_NODE": "ENGINEERING_NODE:",
        "RELEASE_STEP": "RELEASE_STEP:",
    }
    invalid_nodes = [
        item
        for item in nodes
        if not isinstance(item, Mapping)
        or item.get("node_kind") not in kind_prefixes
        or not str(item.get("node_id") or "").startswith(
            kind_prefixes.get(str(item.get("node_kind") or ""), "\0")
        )
        or item.get("label")
        != str(item.get("node_id") or "").split(":", 1)[-1]
    ]
    if (
        len(node_ids) != len(nodes)
        or not required_plane_nodes.issubset(node_ids)
        or invalid_nodes
    ):
        findings.append(
            _finding("COMPOSITE_DEPENDENCY_GRAPH_INVALID", "plane-node-coverage")
        )
        return findings
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    indegree = {node_id: 0 for node_id in node_ids}
    edge_keys: set[tuple[str, str, str]] = set()
    for item in edges:
        if not isinstance(item, Mapping):
            findings.append(
                _finding("COMPOSITE_DEPENDENCY_GRAPH_INVALID", "edge-shape")
            )
            continue
        source = str(item.get("from_node_id") or "")
        target = str(item.get("to_node_id") or "")
        edge_kind = str(item.get("edge_kind") or "")
        key = (source, target, edge_kind)
        if (
            source not in node_ids
            or target not in node_ids
            or source == target
            or not edge_kind
            or key in edge_keys
        ):
            findings.append(
                _finding("COMPOSITE_DEPENDENCY_GRAPH_INVALID", f"edge:{key}")
            )
            continue
        edge_keys.add(key)
        if target not in adjacency[source]:
            adjacency[source].add(target)
            indegree[target] += 1
    required_plane_edges = {
        (
            f"ENGINEERING_PROJECT:{contract['project_id']}",
            f"WORKPACK:{workpack_id}",
            "ENGINEERING_PROJECT_OWNS_WORKPACK",
        )
        for workpack_id, contract in PROJECT_WORKPACK_CONTRACTS.items()
    } | {
        (
            f"RELEASE_STEP:{step_id}",
            f"CAPABILITY:{RELEASE_STEP_OUTPUT_CAPABILITIES[step_id]}",
            "RELEASE_STEP_PRODUCES_CAPABILITY",
        )
        for step_id in RELEASE_STEP_ORDER
    }
    if not required_plane_edges.issubset(edge_keys):
        findings.append(
            _finding(
                "COMPOSITE_DEPENDENCY_GRAPH_INVALID",
                "plane-edge-coverage",
            )
        )
    if not expected_evidence_edges.issubset(edge_keys):
        findings.append(
            _finding(
                "COMPOSITE_DEPENDENCY_GRAPH_INVALID",
                "execution-evidence-edge-coverage",
            )
        )
    if not expected_artifact_dependency_edges.issubset(edge_keys):
        findings.append(
            _finding(
                "COMPOSITE_DEPENDENCY_GRAPH_INVALID",
                "artifact-dependency-edge-coverage",
            )
        )
    ready = sorted(node_id for node_id, count in indegree.items() if count == 0)
    visited: list[str] = []
    while ready:
        current = ready.pop(0)
        visited.append(current)
        for target in sorted(adjacency[current]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort()
    if len(visited) != len(node_ids):
        blocked = sorted(node_id for node_id, count in indegree.items() if count > 0)
        findings.append(
            _finding(
                "COMPOSITE_DEPENDENCY_CYCLE",
                ",".join(blocked[:12]),
            )
        )
    return findings


def explicit_production_enabled(requirement_ir: Mapping[str, Any]) -> bool:
    target = requirement_ir.get("target")
    return isinstance(target, Mapping) and (
        target.get("production_semantics_mode") == EXPLICIT_PRODUCTION_MODE
    )


def compile_declared_production_contracts(
    requirement_ir: Mapping[str, Any],
) -> dict[str, Any]:
    """Hydrate exact contracts from frozen Atoms and a declared schema catalog.

    This is a deterministic producer transformation, not an LLM inference.  A
    Requirement may either carry every per-Atom contract directly or select
    this policy and supply any domain-specific schemas in
    ``target.artifact_schema_catalog``.
    """

    compiled = deepcopy(dict(requirement_ir))
    target = compiled.get("target")
    if not (
        isinstance(target, Mapping)
        and target.get("production_semantics_mode") == EXPLICIT_PRODUCTION_MODE
        and target.get("production_contract_derivation_policy")
        == DETERMINISTIC_DERIVATION_POLICY
    ):
        return compiled
    catalog = target.get("artifact_schema_catalog")
    catalog = catalog if isinstance(catalog, Mapping) else {}
    if isinstance(target, dict):
        target["artifact_schema_catalog"] = deepcopy(dict(catalog))
        catalog = target["artifact_schema_catalog"]
    for case in compiled.get("acceptance_cases", []):
        if not isinstance(case, dict):
            continue
        required_kinds = required_artifact_kinds_for_case(case)
        if required_kinds:
            case["required_artifact_kinds"] = required_kinds
            if str(case.get("evidence_type") or "") in (
                TERMINAL_TIMING_EVIDENCE_TYPES
            ):
                case["evidence_closure_policy"] = (
                    "ALL_DECLARED_TIMING_THRESHOLDS_INCLUDE_TERMINAL_"
                    "MEDIA_ACCEPTANCE"
                )
    edge_by_atom = {
        str(item.get("atom_id")): item
        for item in compiled.get("coverage_edges", [])
        if isinstance(item, Mapping) and item.get("atom_id")
    }
    acceptance_by_atom: dict[str, list[str]] = {}
    for case in compiled.get("acceptance_cases", []):
        if not isinstance(case, Mapping) or not case.get("case_id"):
            continue
        for atom_id in case.get("atom_ids", []):
            acceptance_by_atom.setdefault(str(atom_id), []).append(
                str(case["case_id"])
            )
    repository_jobs = repository_job_bindings(compiled)
    acceptance_cases = [
        item
        for item in compiled.get("acceptance_cases", [])
        if isinstance(item, Mapping) and item.get("case_id")
    ]
    negative_cases = negative_case_specs_with_mandatory_controls(compiled)
    derived_ids: list[str] = []
    for atom in compiled.get("atoms", []):
        if not isinstance(atom, dict) or not atom.get("atom_id"):
            continue
        existing_contract = atom.get("production_contract")
        if (
            isinstance(existing_contract, Mapping)
            and existing_contract.get("derivation_policy")
            != DETERMINISTIC_DERIVATION_POLICY
        ):
            continue
        atom_id = str(atom["atom_id"])
        edge = edge_by_atom.get(atom_id, {})
        workpack_ids = [str(value) for value in edge.get("workpack_ids", [])]
        profile = catalog.get(atom_id)
        profile = profile if isinstance(profile, Mapping) else {}
        schema = profile.get("schema")
        if not isinstance(schema, Mapping):
            schema = {
                "type": "object",
                "required": [
                    "artifact_id",
                    "atom_id",
                    "workpack_id",
                    "status",
                    "source_claim_ids",
                    "evidence_refs",
                    "validation_receipt_ref",
                ],
                "properties": {
                    "artifact_id": {"type": "string"},
                    "atom_id": {"const": atom_id},
                    "workpack_id": {"type": "string"},
                    "status": {"enum": ["PASS", "FAIL"]},
                    "source_claim_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string"},
                    },
                    "evidence_refs": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string"},
                    },
                    "validation_receipt_ref": {"type": "string"},
                },
            }
        artifact_name = str(profile.get("artifact_name") or atom_id.lower())
        artifact_kind = str(
            profile.get("artifact_kind") or atom.get("verification_mode")
        )
        if artifact_kind == "FIXTURE_PLAN" and "LAB-CERTIFICATION" in workpack_ids:
            artifact_kind = "FIXTURE_ACCEPTANCE_RECEIPT"
            artifact_name = "three_fixture_acceptance_receipt"
        schema = _strengthen_artifact_schema(
            artifact_kind,
            schema,
            repository_jobs,
            acceptance_cases,
            negative_cases,
        )
        if isinstance(catalog, dict):
            normalized_profile = deepcopy(dict(profile))
            declared_schema = profile.get("schema")
            if (
                "declared_schema_sha256" not in normalized_profile
                and isinstance(declared_schema, Mapping)
            ):
                normalized_profile["declared_schema_sha256"] = hashlib.sha256(
                    json.dumps(
                        declared_schema,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
            normalized_profile.update(
                {
                    "artifact_name": artifact_name,
                    "artifact_kind": artifact_kind,
                    "schema": deepcopy(dict(schema)),
                    "compiled_schema_sha256": hashlib.sha256(
                        json.dumps(
                            schema,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest(),
                    "schema_authority": (
                        "COMPILED_PHASE_CORRECT_SCHEMA_USED_BY_ARTIFACT_"
                        "MANIFEST_AND_WORKPACKS"
                    ),
                }
            )
            if artifact_kind == "AUDIO_ALIGNMENT_RECEIPT":
                normalized_profile["phase_evidence_contract"] = {
                    "owner_phase": "MB-P2",
                    "terminal_video_av_drift_owner_artifact_kind": (
                        "MEDIA_ACCEPTANCE_RECEIPT"
                    ),
                    "terminal_video_av_drift_owner_phase": "MB-P3",
                    "forbidden_fields": [
                        "final_av_drift_frames",
                        "absolute_final_av_drift_frames",
                    ],
                }
                normalized_profile["oracle_decision_rule"] = (
                    "Recompute word anchors from synthesized audio and verify "
                    "anchor ordering, audio hashes, opening dead air, and "
                    "alignment error thresholds."
                )
                if normalized_profile.get("error_code") == "AUDIO_VIDEO_DRIFT":
                    normalized_profile.pop("error_code")
            catalog[atom_id] = normalized_profile
        obligations: list[dict[str, Any]] = []
        for workpack_id in workpack_ids:
            artifact_jobs: list[Mapping[str, str] | None] = (
                list(repository_jobs)
                if artifact_kind in JOB_SCOPED_ARTIFACT_KINDS
                and repository_jobs
                else [None]
            )

            def make_artifact(
                current_kind: str,
                current_name: str,
                current_schema: Mapping[str, Any],
                job: Mapping[str, str] | None,
                *,
                id_suffix: str = "",
            ) -> dict[str, Any]:
                job_suffix = f"-{job['job_id']}" if job is not None else ""
                artifact_id = (
                    f"ART-{atom_id}-{workpack_id}{job_suffix}{id_suffix}"
                )
                if job is None:
                    artifact_ref = (
                        "harness-resource://execution/artifacts/"
                        f"{atom_id}/{workpack_id}/{current_name}.json"
                    )
                    bound_schema = deepcopy(dict(current_schema))
                else:
                    artifact_ref = (
                        "harness-resource://execution/jobs/"
                        f"{job['job_id']}/artifacts/{atom_id}/"
                        f"{workpack_id}/{current_name}.json"
                    )
                    bound_schema = _bind_schema_to_job(
                        current_schema,
                        job,
                        current_kind,
                        repository_jobs,
                    )
                evaluator_id = _artifact_evaluator_id(current_kind)
                phase_incompatible_error_codes = (
                    {"AUDIO_VIDEO_DRIFT"}
                    if current_kind == "AUDIO_ALIGNMENT_RECEIPT"
                    else set()
                )
                declared_error_codes = [
                    str(value)
                    for value in atom.get("error_semantics") or []
                    if value and str(value) not in phase_incompatible_error_codes
                ]
                profile_error_code = str(profile.get("error_code") or "")
                if profile_error_code in phase_incompatible_error_codes:
                    profile_error_code = ""
                primary_error_code = str(
                    profile_error_code
                    or next(
                        iter(declared_error_codes),
                        _ARTIFACT_KIND_FAILURE_RETURN_CODES.get(
                            current_kind,
                            ("PRODUCTION_ARTIFACT_INVALID",),
                        )[0],
                    )
                )
                failure_error_codes: list[str] = []
                for error_code in (
                    primary_error_code,
                    *_ARTIFACT_KIND_FAILURE_RETURN_CODES.get(
                        current_kind, ()
                    ),
                    *declared_error_codes,
                ):
                    if error_code not in failure_error_codes:
                        failure_error_codes.append(error_code)
                failure_returns = [
                    {
                        "error_code": error_code,
                        "control_node_id": str(
                            profile.get("failure_control_node_id")
                            or workpack_id
                        ),
                        "invalidates": str(
                            profile.get("invalidates")
                            or "CURRENT_ARTIFACT_AND_DEPENDENT_RECEIPTS"
                        ),
                    }
                    for error_code in failure_error_codes
                ]
                oracle_decision_rule = str(
                    profile.get("oracle_decision_rule")
                    or "Recompute the declared decision without trusting producer self-report."
                )
                if current_kind == "AUDIO_ALIGNMENT_RECEIPT":
                    oracle_decision_rule = (
                        "Recompute word anchors from synthesized audio and verify "
                        "anchor ordering, audio hashes, opening dead air, and "
                        "alignment error thresholds."
                    )
                artifact = {
                    "artifact_id": artifact_id,
                    "artifact_kind": current_kind,
                    "artifact_ref": artifact_ref,
                    "schema": bound_schema,
                    "production_rule": str(
                        profile.get("production_rule")
                        or "Produce from frozen source claims and measured runtime evidence only."
                    ),
                    "validation_rule": {
                        "validator_owner": str(
                            profile.get("validator_owner")
                            or "PROJECT_VALIDATOR"
                        ),
                        "decision_rule": str(
                            profile.get("validation_decision_rule")
                            or "Schema, declared thresholds, hashes, and evidence references all pass."
                        ),
                        "evidence_required": list(
                            profile.get("evidence_required")
                            or [str(atom.get("verification_mode"))]
                        ),
                    },
                    "oracle": {
                        "oracle_id": f"ORACLE-{artifact_id}",
                        "evaluator_id": evaluator_id,
                        "evaluator_registry_ref": ORACLE_EVALUATOR_REGISTRY_REF,
                        "independence_level": str(
                            profile.get("oracle_independence_level")
                            or "INDEPENDENT_PROJECT_VALIDATOR"
                        ),
                        "decision_rule": oracle_decision_rule,
                        "common_mode_exclusions": list(
                            profile.get("common_mode_exclusions")
                            or [
                                "PRODUCER_SELF_REPORT",
                                "SCHEMA_ONLY_PASS_FOR_BEHAVIORAL_CLAIM",
                            ]
                        ),
                    },
                    "failure_return": deepcopy(failure_returns[0]),
                    "failure_returns": failure_returns,
                }
                if job is not None:
                    artifact.update(
                        {"job_id": job["job_id"], "source_id": job["source_id"]}
                    )
                return artifact

            artifact_obligations: list[dict[str, Any]] = []
            if artifact_kind == "LOCAL_TTS_RECEIPT":
                narration_schema = _strengthen_artifact_schema(
                    "NARRATION_SCRIPT",
                    {},
                    repository_jobs,
                    acceptance_cases,
                    negative_cases,
                )
                for job in artifact_jobs:
                    artifact_obligations.append(
                        make_artifact(
                            "NARRATION_SCRIPT",
                            "narration_script",
                            narration_schema,
                            job,
                            id_suffix="-NARRATION-SCRIPT",
                        )
                    )
            if artifact_kind == "RESUMABLE_STAGE_RECEIPT":
                for job in artifact_jobs:
                    previous_artifact_id: str | None = None
                    for stage_index, stage_id in enumerate(
                        RESUMABLE_STAGE_ORDER
                    ):
                        stage_schema = deepcopy(schema)
                        previous_stage_id = (
                            RESUMABLE_STAGE_ORDER[stage_index - 1]
                            if stage_index
                            else None
                        )
                        stage_schema.update(
                            {
                                "x-expected-stage-id": stage_id,
                                "x-expected-stage-index": stage_index,
                                "x-expected-previous-stage-id": previous_stage_id,
                            }
                        )
                        stage_schema["properties"][
                            "stage_receipt_set_id"
                        ] = {
                            "const": (
                                "RESUMABLE-STAGE-SET-"
                                + str(job["job_id"] if job else atom_id)
                            )
                        }
                        artifact = make_artifact(
                            artifact_kind,
                            (
                                "resumable_stage_receipts/"
                                f"{stage_index:02d}-{stage_id.lower()}"
                            ),
                            stage_schema,
                            job,
                            id_suffix=f"-STAGE-{_safe_id(stage_id)}",
                        )
                        artifact.update(
                            {
                                "expected_stage_id": stage_id,
                                "expected_stage_index": stage_index,
                                "expected_previous_stage_id": previous_stage_id,
                                "depends_on_artifact_ids": (
                                    [previous_artifact_id]
                                    if previous_artifact_id
                                    else []
                                ),
                            }
                        )
                        artifact_obligations.append(artifact)
                        previous_artifact_id = str(artifact["artifact_id"])
            else:
                for job in artifact_jobs:
                    artifact_obligations.append(
                        make_artifact(
                            artifact_kind,
                            artifact_name,
                            schema,
                            job,
                        )
                    )
                if artifact_kind == "OBJECT_MOTION_IR":
                    binding_schema = _strengthen_artifact_schema(
                        "ASSET_BINDING_RECEIPT",
                        {},
                        repository_jobs,
                        acceptance_cases,
                        negative_cases,
                    )
                    for job in artifact_jobs:
                        artifact_obligations.append(
                            make_artifact(
                                "ASSET_BINDING_RECEIPT",
                                "asset_binding_receipt",
                                binding_schema,
                                job,
                                id_suffix="-ASSET-BINDING-RECEIPT",
                            )
                        )
            deterministic_steps = list(
                profile.get("deterministic_steps")
                or [
                    "Resolve every claim and input from the frozen source and Atom bindings.",
                    "Produce the declared artifact at its logical execution reference.",
                    "Run schema validation and the independent Oracle before marking PASS.",
                ]
            )
            completion_rule = str(
                profile.get("completion_rule")
                or "ARTIFACT_SCHEMA_VALID_AND_INDEPENDENT_ORACLE_PASS"
            )
            if artifact_kind == "LOCAL_TTS_RECEIPT":
                deterministic_steps = [
                    (
                        "Draft the canonical Mandarin sentence array, recompute "
                        "the 175-185 second narration budget, and permit at most "
                        "two narration-only repairs without speed-up or truncation."
                    ),
                    (
                        "Require narration_budget_verified=true and a hash-bound "
                        "budget receipt before starting local offline TTS."
                    ),
                    *deterministic_steps,
                ]
            if artifact_kind == "FIXTURE_ACCEPTANCE_RECEIPT":
                deterministic_steps.extend(
                    [
                        "Load the complete Oracle evaluator registry and execute every invariant case against every applicable schema Hash.",
                        "Require the base artifact and the mutated artifact to pass JSON Schema before accepting the declared invariant rejection.",
                        "Execute every schema-native negative case separately and require JSON Schema rejection before any semantic Oracle starts.",
                        "Aggregate exact per-case and per-schema result refs, result Hashes, failure codes, and zero-side-effect receipts.",
                    ]
                )
                completion_rule = (
                    "ALL_ACCEPTANCE_NEGATIVE_AND_INVARIANT_SCHEMA_INSTANCE_RESULTS_"
                    "EXACTLY_COVER_THE_FROZEN_MANIFESTS_AND_ORACLE_REGISTRY"
                )
            obligations.append(
                {
                    "workpack_id": workpack_id,
                    "task_objective": str(atom.get("text_or_lossless_paraphrase")),
                    "required_inputs": [
                        "harness-resource://candidate/canonical_sources/FROZEN_REQUIREMENT_IR.json",
                        "harness-resource://candidate/canonical_sources/SOURCE_MANIFEST.json",
                        *[
                            f"acceptance-case://{case_id}"
                            for case_id in acceptance_by_atom.get(atom_id, [])
                        ],
                    ],
                    "design_questions": list(profile.get("design_questions") or []),
                    "deterministic_steps": deterministic_steps,
                    "forbidden_inferences": list(
                        profile.get("forbidden_inferences")
                        or [
                            "Do not invent unsupported capability, timing, provenance, or execution evidence.",
                            *list(atom.get("explicit_non_goals") or []),
                        ]
                    ),
                    "completion_rule": completion_rule,
                    "artifact_obligations": artifact_obligations,
                }
            )
        atom["production_contract"] = {
            "contract_id": f"PROD-{atom_id}",
            "derivation_policy": DETERMINISTIC_DERIVATION_POLICY,
            "workpack_obligations": obligations,
        }
        derived_ids.append(atom_id)
    _bind_artifact_dependencies(compiled)
    compiled["production_contract_compilation"] = {
        "schema_version": "1.0",
        "policy": DETERMINISTIC_DERIVATION_POLICY,
        "derived_atom_ids": derived_ids,
        "phase_evidence_relocations": [
            {
                "evidence": "FINAL_AUDIO_VIDEO_DRIFT",
                "from_artifact_kind": "AUDIO_ALIGNMENT_RECEIPT",
                "from_phase": "MB-P2",
                "to_artifact_kind": "MEDIA_ACCEPTANCE_RECEIPT",
                "to_phase": "MB-P3",
                "status": "COMPILED_AND_FROZEN",
            }
        ],
        "llm_inference_used": False,
        "status": "COMPILED_NOT_EXECUTED",
    }
    return compiled


def validate_explicit_production_contracts(
    requirement_ir: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return closed findings for an enabled explicit production contract."""

    requirement_ir = compile_declared_production_contracts(requirement_ir)
    if not explicit_production_enabled(requirement_ir):
        return []
    findings: list[dict[str, Any]] = []
    edge_by_atom = {
        str(item.get("atom_id")): item
        for item in requirement_ir.get("coverage_edges", [])
        if isinstance(item, Mapping) and item.get("atom_id")
    }
    contract_ids: set[str] = set()
    artifact_ids: set[str] = set()
    artifact_refs: set[str] = set()
    for atom in requirement_ir.get("atoms", []):
        if not isinstance(atom, Mapping) or not atom.get("atom_id"):
            continue
        atom_id = str(atom["atom_id"])
        contract = atom.get("production_contract")
        if not isinstance(contract, Mapping):
            findings.append(_finding("PRODUCTION_CONTRACT_MISSING", atom_id))
            continue
        contract_id = contract.get("contract_id")
        if not isinstance(contract_id, str) or not contract_id:
            findings.append(_finding("PRODUCTION_CONTRACT_ID_MISSING", atom_id))
        elif contract_id in contract_ids:
            findings.append(_finding("PRODUCTION_CONTRACT_ID_DUPLICATE", contract_id))
        else:
            contract_ids.add(contract_id)
        obligations = contract.get("workpack_obligations")
        if not isinstance(obligations, list) or not obligations:
            findings.append(_finding("WORKPACK_OBLIGATIONS_MISSING", atom_id))
            continue
        expected_workpacks = set(edge_by_atom.get(atom_id, {}).get("workpack_ids", []))
        actual_workpacks = [
            str(item.get("workpack_id"))
            for item in obligations
            if isinstance(item, Mapping) and item.get("workpack_id")
        ]
        if (
            len(actual_workpacks) != len(obligations)
            or len(set(actual_workpacks)) != len(actual_workpacks)
            or set(actual_workpacks) != expected_workpacks
        ):
            findings.append(
                _finding(
                    "WORKPACK_OBLIGATION_COVERAGE_MISMATCH",
                    f"{atom_id}: expected={sorted(expected_workpacks)} actual={sorted(actual_workpacks)}",
                )
            )
        for obligation in obligations:
            if not isinstance(obligation, Mapping):
                continue
            workpack_id = str(obligation.get("workpack_id") or "")
            _validate_task_guidance(findings, atom_id, workpack_id, obligation)
            artifacts = obligation.get("artifact_obligations")
            if not isinstance(artifacts, list) or not artifacts:
                findings.append(
                    _finding(
                        "ARTIFACT_OBLIGATIONS_MISSING",
                        f"{atom_id}:{workpack_id}",
                    )
                )
                continue
            for artifact in artifacts:
                _validate_artifact_obligation(
                    findings,
                    atom_id,
                    workpack_id,
                    artifact,
                    artifact_ids,
                    artifact_refs,
                )
    artifact_records: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for atom in requirement_ir.get("atoms", []):
        contract = atom.get("production_contract") if isinstance(atom, Mapping) else None
        if not isinstance(contract, Mapping):
            continue
        for obligation in contract.get("workpack_obligations", []):
            if not isinstance(obligation, Mapping):
                continue
            workpack_id = str(obligation.get("workpack_id") or "")
            for artifact in obligation.get("artifact_obligations", []):
                if not isinstance(artifact, Mapping):
                    continue
                artifact_id = str(artifact.get("artifact_id") or "")
                if artifact_id:
                    artifact_records[artifact_id] = (workpack_id, artifact)

    for atom in requirement_ir.get("atoms", []):
        contract = atom.get("production_contract") if isinstance(atom, Mapping) else None
        if not isinstance(contract, Mapping):
            continue
        for obligation in contract.get("workpack_obligations", []):
            if not isinstance(obligation, Mapping):
                continue
            workpack_id = str(obligation.get("workpack_id") or "")
            for artifact in obligation.get("artifact_obligations", []):
                if not isinstance(artifact, Mapping):
                    continue
                artifact_id = str(artifact.get("artifact_id") or "")
                dependencies = artifact.get("depends_on_artifact_ids", [])
                evidence_dependencies = artifact.get(
                    "depends_on_evidence_refs", []
                )
                if (
                    not isinstance(dependencies, list)
                    or any(
                        not isinstance(value, str)
                        or not value
                        or value == artifact.get("artifact_id")
                        or value not in artifact_ids
                        for value in dependencies
                    )
                ):
                    findings.append(
                        _finding(
                            "ARTIFACT_DEPENDENCY_INVALID",
                            str(artifact.get("artifact_id")),
                        )
                    )
                    continue
                if (
                    not isinstance(evidence_dependencies, list)
                    or len(evidence_dependencies)
                    != len(set(evidence_dependencies))
                    or any(
                        not isinstance(value, str)
                        or not value.startswith(
                            f"{CASE_EXECUTION_RESULT_ROOT_REF}/"
                        )
                        or ".." in value
                        for value in evidence_dependencies
                    )
                ):
                    findings.append(
                        _finding(
                            "ARTIFACT_EVIDENCE_DEPENDENCY_INVALID",
                            artifact_id,
                        )
                    )
                if artifact.get("artifact_kind") == "FIXTURE_ACCEPTANCE_RECEIPT":
                    ownership = artifact.get("case_evidence_ownership")
                    if (
                        not evidence_dependencies
                        or not isinstance(ownership, Mapping)
                        or ownership.get("writer_workpack_id")
                        != CASE_EVIDENCE_WRITER_WORKPACK_ID
                        or ownership.get("result_root_ref")
                        != CASE_EXECUTION_RESULT_ROOT_REF
                        or ownership.get("writer_cardinality")
                        != "EXACTLY_ONE_WORKPACK"
                        or ownership.get("consumer_requires_hash_bound_bytes")
                        is not True
                    ):
                        findings.append(
                            _finding(
                                "FIXTURE_ACCEPTANCE_EVIDENCE_OWNERSHIP_INVALID",
                                artifact_id,
                            )
                        )
                current_rank = {
                    "LAB-PROTOCOL": 0,
                    "LAB-CLI": 0,
                    "LAB-FIXTURES": 0,
                    "LAB-SELFTEST": 0,
                    "MB-G0": 0,
                    "MB-P1": 1,
                    "MB-P2": 2,
                    "MB-P3": 3,
                    "MB-P4": 4,
                    "MB-RELEASE-CANDIDATE": 5,
                    "LAB-CERTIFICATION": 100,
                }.get(workpack_id, -1)
                for dependency_id in dependencies:
                    dependency_record = artifact_records.get(dependency_id)
                    if dependency_record is None:
                        continue
                    dependency_workpack, dependency = dependency_record
                    dependency_rank = {
                        "LAB-PROTOCOL": 0,
                        "LAB-CLI": 0,
                        "LAB-FIXTURES": 0,
                        "LAB-SELFTEST": 0,
                        "MB-G0": 0,
                        "MB-P1": 1,
                        "MB-P2": 2,
                        "MB-P3": 3,
                        "MB-P4": 4,
                        "MB-RELEASE-CANDIDATE": 5,
                        "LAB-CERTIFICATION": 100,
                    }.get(dependency_workpack, -1)
                    if dependency_rank > current_rank:
                        findings.append(
                            _finding(
                                "ARTIFACT_DEPENDENCY_FUTURE_PHASE",
                                f"{artifact_id}:{dependency_id}",
                            )
                        )
                    artifact_job = artifact.get("job_id")
                    dependency_job = dependency.get("job_id")
                    if (
                        isinstance(artifact_job, str)
                        and isinstance(dependency_job, str)
                        and artifact_job != dependency_job
                    ):
                        findings.append(
                            _finding(
                                "ARTIFACT_DEPENDENCY_CROSSES_JOB",
                                f"{artifact_id}:{dependency_id}",
                            )
                        )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(artifact_id: str) -> bool:
        if artifact_id in visiting:
            return False
        if artifact_id in visited:
            return True
        visiting.add(artifact_id)
        artifact = artifact_records[artifact_id][1]
        for dependency_id in artifact.get("depends_on_artifact_ids", []):
            if dependency_id in artifact_records and not visit(dependency_id):
                return False
        visiting.remove(artifact_id)
        visited.add(artifact_id)
        return True

    for artifact_id in artifact_records:
        if artifact_id not in visited and not visit(artifact_id):
            findings.append(
                _finding("ARTIFACT_DEPENDENCY_CYCLE", artifact_id)
            )
            break
    architecture_input = (
        requirement_ir.get("target", {}).get("architecture_input", {})
        if isinstance(requirement_ir.get("target"), Mapping)
        else {}
    )
    required_failure_returns = (
        architecture_input.get("failure_returns", [])
        if isinstance(architecture_input, Mapping)
        else []
    )
    if isinstance(required_failure_returns, list):
        routed_failure_returns: set[str] = set()
        for _, artifact in artifact_records.values():
            routes = artifact.get("failure_returns")
            if not isinstance(routes, list):
                routes = [artifact.get("failure_return")]
            routed_failure_returns.update(
                str(route["error_code"])
                for route in routes
                if isinstance(route, Mapping) and route.get("error_code")
            )
        missing_failure_returns = sorted(
            {
                str(value)
                for value in required_failure_returns
                if isinstance(value, str) and value
            }
            - routed_failure_returns
        )
        if missing_failure_returns:
            findings.append(
                _finding(
                    "ARCHITECTURE_FAILURE_RETURN_UNROUTED",
                    ",".join(missing_failure_returns),
                )
            )
    return findings


def build_artifact_obligation_manifest(
    requirement_ir: Mapping[str, Any],
    *,
    target_id: str,
    program_id: str,
    requirement_ir_sha256: str,
    atom_catalog_sha256: str,
    coverage_matrix_sha256: str,
) -> dict[str, Any] | None:
    """Compile frozen Atom contracts into one portable production manifest."""

    requirement_ir = compile_declared_production_contracts(requirement_ir)
    if not explicit_production_enabled(requirement_ir):
        return None
    findings = validate_explicit_production_contracts(requirement_ir)
    if findings:
        codes = [item["code"] for item in findings]
        raise ValueError(f"explicit production contracts invalid: {codes}")
    contracts: list[dict[str, Any]] = []
    reverse_workpack_index: dict[str, list[dict[str, Any]]] = {}
    artifact_index: dict[str, dict[str, Any]] = {}
    for atom in requirement_ir.get("atoms", []):
        if not isinstance(atom, Mapping):
            continue
        atom_id = str(atom["atom_id"])
        contract = deepcopy(dict(atom["production_contract"]))
        compiled_contract = {
            "contract_id": str(contract["contract_id"]),
            "atom_id": atom_id,
            "source_id": atom.get("source_id"),
            "verification_mode": atom.get("verification_mode"),
            "status": "FROZEN_NOT_EXECUTED",
            "workpack_obligations": contract["workpack_obligations"],
        }
        contracts.append(compiled_contract)
        for obligation in compiled_contract["workpack_obligations"]:
            workpack_id = str(obligation["workpack_id"])
            artifact_ids = [
                str(item["artifact_id"])
                for item in obligation["artifact_obligations"]
            ]
            reverse_workpack_index.setdefault(workpack_id, []).append(
                {
                    "contract_id": compiled_contract["contract_id"],
                    "atom_id": atom_id,
                    "artifact_ids": artifact_ids,
                }
            )
            for artifact in obligation["artifact_obligations"]:
                artifact_entry = {
                    "atom_id": atom_id,
                    "contract_id": compiled_contract["contract_id"],
                    "workpack_id": workpack_id,
                    "artifact_ref": artifact["artifact_ref"],
                    "artifact_kind": artifact["artifact_kind"],
                    "schema": deepcopy(dict(artifact["schema"])),
                    "depends_on_artifact_ids": list(
                        artifact.get("depends_on_artifact_ids") or []
                    ),
                    "depends_on_evidence_refs": list(
                        artifact.get("depends_on_evidence_refs") or []
                    ),
                }
                if isinstance(artifact.get("case_evidence_ownership"), Mapping):
                    artifact_entry["case_evidence_ownership"] = deepcopy(
                        dict(artifact["case_evidence_ownership"])
                    )
                for field in (
                    "job_id",
                    "source_id",
                    "expected_stage_id",
                    "expected_stage_index",
                    "expected_previous_stage_id",
                ):
                    if field in artifact:
                        artifact_entry[field] = artifact[field]
                artifact_index[str(artifact["artifact_id"])] = artifact_entry
    manifest = {
        "schema_version": "2.9",
        "manifest_id": f"ARTIFACT-OBLIGATIONS-{target_id}",
        "program_id": program_id,
        "target_id": target_id,
        "production_semantics_mode": EXPLICIT_PRODUCTION_MODE,
        "requirement_ir_sha256": requirement_ir_sha256,
        "normative_atom_catalog_sha256": atom_catalog_sha256,
        "atom_coverage_matrix_sha256": coverage_matrix_sha256,
        "contracts": contracts,
        "reverse_workpack_index": reverse_workpack_index,
        "artifact_index": artifact_index,
        "composite_dependency_graph": build_composite_dependency_graph(
            artifact_index
        ),
        "completion_rule": (
            "EVERY_ROUTED_ATOM_HAS_A_FROZEN_TASK_BUNDLE_AND_EVERY_REQUIRED_"
            "ARTIFACT_PASSES_ITS_DECLARED_VALIDATION_AND_ORACLE_RULE"
        ),
        "execution_started": False,
        "status": "FROZEN_NOT_EXECUTED",
    }
    manifest["manifest_sha256"] = _hash_without_field(manifest, "manifest_sha256")
    return manifest


def task_bundle_for_workpack(
    manifest: Mapping[str, Any] | None,
    *,
    workpack_id: str,
    project_id: str,
    program_id: str,
    target_id: str,
    structural_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return the exact semantic task bundle routed to one Workpack."""

    if not isinstance(manifest, Mapping):
        return None
    expected = manifest.get("reverse_workpack_index", {}).get(workpack_id, [])
    if not expected:
        if not isinstance(structural_contract, Mapping):
            return None
        requires = [str(value) for value in structural_contract.get("requires", [])]
        produces = [str(value) for value in structural_contract.get("produces", [])]
        structural_artifacts = []
        for index, produced in enumerate(produces or ["WORKPACK_CONTROL_RESULT"], 1):
            safe_name = "".join(
                character if character.isalnum() else "-"
                for character in produced.upper()
            ).strip("-") or f"OUTPUT-{index}"
            structural_artifacts.append(
                {
                    "artifact_id": f"STRUCTURAL-{workpack_id}-{safe_name}",
                    "artifact_ref": (
                        "harness-resource://execution/evidence/structural/"
                        f"{workpack_id}/{safe_name}.result.json"
                    ),
                    "artifact_kind": "WORKPACK_CONTROL_RESULT",
                    "schema": {
                        "type": "object",
                        "required": [
                            "workpack_id",
                            "produced_capability",
                            "status",
                            "evidence_refs",
                        ],
                        "properties": {
                            "workpack_id": {"const": workpack_id},
                            "produced_capability": {"const": produced},
                            "status": {"const": "PASS"},
                            "evidence_refs": {
                                "type": "array",
                                "minItems": 1,
                                "items": {"type": "string"},
                            },
                        },
                    },
                    "production_rule": (
                        "Produce only after every declared predecessor, command "
                        "receipt, and capability precondition is current."
                    ),
                    "validation_rule": {
                        "validator_owner": "PROJECT_VALIDATOR",
                        "decision_rule": (
                            "PASS_ONLY_WHEN_CAPABILITY_AND_EVIDENCE_HASHES_MATCH"
                        ),
                        "evidence_required": "HASH_BOUND_COMMAND_AND_RESULT_RECEIPTS",
                    },
                    "oracle": {
                        "oracle_id": f"ORACLE-STRUCTURAL-{workpack_id}-{index}",
                        "independence_level": "INDEPENDENT_PROJECT_VALIDATOR",
                        "decision_rule": (
                            "TARGET_SELF_REPORT_CANNOT_SATISFY_THE_RESULT"
                        ),
                        "common_mode_exclusions": [
                            "SCHEMA_ONLY_PASS",
                            "UNEXECUTED_COMMAND_MANIFEST",
                        ],
                    },
                    "failure_return": {
                        "error_code": "STRUCTURAL_WORKPACK_CONTRACT_FAILED",
                        "control_node_id": workpack_id,
                        "invalidates": "CURRENT_WORKPACK_AND_DEPENDENTS",
                    },
                }
            )
        task_contracts = [
            {
                "contract_id": f"STRUCTURAL-CONTRACT-{workpack_id}",
                "atom_id": f"STRUCTURAL-{workpack_id}",
                "workpack_id": workpack_id,
                "task_objective": (
                    f"Materialize and verify {', '.join(produces) or 'the declared control result'} "
                    f"from {', '.join(requires) or 'the frozen predecessor state'}."
                ),
                "required_inputs": requires or ["FROZEN_PROGRAM_CONTROL_STATE"],
                "design_questions": [],
                "deterministic_steps": [
                    "Validate predecessor hashes and the exact Workpack capsule.",
                    "Run only hash-bound commands after a separate authorization.",
                    "Validate produced capabilities with the independent oracle.",
                ],
                "forbidden_inferences": [
                    "Do not treat a planned command or target self-report as execution evidence."
                ],
                "artifact_obligations": structural_artifacts,
                "completion_rule": (
                    "ALL_STRUCTURAL_ARTIFACTS_PASS_SCHEMA_HASH_AND_ORACLE_CHECKS"
                ),
            }
        ]
        artifacts = structural_artifacts
        expected_contract_ids = {f"STRUCTURAL-CONTRACT-{workpack_id}"}
    else:
        expected_contract_ids = {
            str(item["contract_id"])
            for item in expected
            if isinstance(item, Mapping)
        }
        task_contracts = []
        for contract in manifest.get("contracts", []):
            if (
                not isinstance(contract, Mapping)
                or contract.get("contract_id") not in expected_contract_ids
            ):
                continue
            obligation = next(
                item
                for item in contract["workpack_obligations"]
                if item["workpack_id"] == workpack_id
            )
            task_contracts.append(
                {
                    "contract_id": contract["contract_id"],
                    "atom_id": contract["atom_id"],
                    **deepcopy(dict(obligation)),
                }
            )
        artifacts = [
            deepcopy(dict(artifact))
            for contract in task_contracts
            for artifact in contract["artifact_obligations"]
        ]
    bundle = {
        "schema_version": "2.9",
        "task_bundle_id": f"TASK-BUNDLE-{workpack_id}",
        "program_id": program_id,
        "target_id": target_id,
        "project_id": project_id,
        "workpack_id": workpack_id,
        "artifact_obligation_manifest_ref": ARTIFACT_MANIFEST_REF,
        "artifact_obligation_manifest_sha256": manifest.get("manifest_sha256"),
        "intent_atom_ids": [str(item["atom_id"]) for item in task_contracts],
        "production_contract_ids": [
            str(item["contract_id"]) for item in task_contracts
        ],
        "task_contracts": task_contracts,
        "required_artifact_ids": [str(item["artifact_id"]) for item in artifacts],
        "required_artifact_refs": [str(item["artifact_ref"]) for item in artifacts],
        "semantic_hydration_complete": True,
        "runtime_binding_complete": False,
        "execution_authorization_ref": None,
        "execution_started": False,
        "completion_rule": (
            "ALL_DECLARED_ARTIFACTS_EXIST_AT_THEIR_LOGICAL_REFS_AND_PASS_"
            "THEIR_SCHEMA_VALIDATION_ORACLE_AND_FAILURE_RETURN_CONTRACTS"
        ),
        "status": "SEMANTIC_CONTRACT_FROZEN_RUNTIME_NOT_BOUND",
    }
    if workpack_id in {
        "LAB-PROTOCOL",
        "LAB-CLI",
        "LAB-FIXTURES",
        "LAB-CERTIFICATION",
    }:
        artifact_evaluator_ids = sorted(
            {
                _artifact_evaluator_id(str(item.get("artifact_kind")))
                for item in manifest.get("artifact_index", {}).values()
                if isinstance(item, Mapping) and item.get("artifact_kind")
            }
        )
        bundle["lab_case_execution_contract"] = {
            "contract_id": f"LAB-CASE-EXECUTION-{workpack_id}-V1",
            "required_refs": [
                "harness-resource://candidate/validation/CASE_EXECUTION_MANIFEST.json",
                "harness-resource://candidate/validation/ORACLE_EVALUATOR_REGISTRY.json",
                PUBLIC_SKILL_JOB_INTERFACE_REF,
                "harness-resource://candidate/validation/schemas/CASE_RESULT.schema.json",
                "harness-resource://candidate/validation/ACCEPTANCE_CASES.json",
                "harness-resource://candidate/validation/NEGATIVE_CASES.json",
            ],
            "required_command_ids": [
                "LAB-RUN-ACCEPTANCE-CASE",
                "LAB-RUN-NEGATIVE-CASE",
                "LAB-RUN-REGISTRY-CASE",
                "LAB-EVALUATE-CASE-ORACLE",
            ],
            "required_subcommands": [
                "run-acceptance-case",
                "run-negative-case",
                "run-registry-case",
                "evaluate-case-oracle",
            ],
            "assertion_operators": [
                "VALIDATED_RECEIPT_EXISTS",
                "SET_EQUALS",
                "ALL_ARTIFACTS_SCHEMA_HASH_AND_ORACLE_PASS",
                "EXACT_SOURCE_JOBS_MATCH",
                "EQUALS",
            ],
            "required_evaluator_ids": [
                "EXACT_CASE_SET_ORACLE_V1",
                *artifact_evaluator_ids,
            ],
            "implementation_obligations": {
                "LAB-PROTOCOL": [
                    "Implement JSON Schema 2020-12 validation and evaluator registry loading.",
                    "Implement the public Skill URL Job schema and deterministic dynamic schema specialization contract.",
                    "Fail closed on unknown operators, evaluator IDs, or evidence references.",
                ],
                "LAB-CLI": [
                    "Expose the three required subcommands with fixture-ref and result-ref arguments.",
                    "Write hash-bound command and side-effect receipts for every invocation.",
                ],
                "LAB-FIXTURES": [
                    "Execute machine-applicable positive and negative fixtures.",
                    "Execute the unlisted public Skill URL metamorphic vector without replacing it with a frozen fixture URL.",
                    "Reject duplicate, omitted, or substituted assertion, artifact, and source-job members.",
                    "Apply every registry invariant mutation to every applicable schema instance after the base artifact passes schema and Oracle validation.",
                    "Require each invariant mutation to remain JSON-Schema-valid and to fail only its declared x-invariant evaluator.",
                    "Write one hash-bound schema-instance result for every registry case and applicable schema Hash.",
                    "Require every frozen acceptance case and every complete negative case exactly once in the certification aggregate.",
                ],
                "LAB-CERTIFICATION": [
                    "Own the exact execution/evidence/cases result root and every Case runner command.",
                    "Acquire the declared per-Job read leases before loading Job artifacts.",
                    "Recompute every Case, fixture-video, and registry-result SHA-256 from referenced bytes before issuing the aggregate receipt.",
                    "Reject missing, duplicate, stale, substituted, or unreachable result evidence.",
                ],
            }[workpack_id],
            "completion_rule": (
                "IMPLEMENTATION_AND_SELFTESTS_PROVE_THE_BOUND_CASE_SCHEMA_COMMANDS_"
                "OPERATORS_AND_EXACT_SET_ORACLE"
            ),
        }
    bundle["task_bundle_sha256"] = _hash_without_field(
        bundle, "task_bundle_sha256"
    )
    return bundle


def _validate_task_guidance(
    findings: list[dict[str, Any]],
    atom_id: str,
    workpack_id: str,
    obligation: Mapping[str, Any],
) -> None:
    label = f"{atom_id}:{workpack_id}"
    if not obligation.get("task_objective"):
        findings.append(_finding("TASK_OBJECTIVE_MISSING", label))
    for field in (
        "required_inputs",
        "design_questions",
        "deterministic_steps",
        "forbidden_inferences",
    ):
        value = obligation.get(field)
        if not isinstance(value, list) or (
            field != "design_questions" and not value
        ):
            findings.append(_finding("TASK_GUIDANCE_INCOMPLETE", f"{label}:{field}"))
    if not obligation.get("completion_rule"):
        findings.append(_finding("TASK_COMPLETION_RULE_MISSING", label))


def _validate_artifact_obligation(
    findings: list[dict[str, Any]],
    atom_id: str,
    workpack_id: str,
    artifact: Any,
    artifact_ids: set[str],
    artifact_refs: set[str],
) -> None:
    label = f"{atom_id}:{workpack_id}"
    if not isinstance(artifact, Mapping):
        findings.append(_finding("ARTIFACT_OBLIGATION_INVALID", label))
        return
    artifact_id = artifact.get("artifact_id")
    artifact_ref = artifact.get("artifact_ref")
    if not isinstance(artifact_id, str) or not artifact_id:
        findings.append(_finding("ARTIFACT_ID_MISSING", label))
    elif artifact_id in artifact_ids:
        findings.append(_finding("ARTIFACT_ID_DUPLICATE", artifact_id))
    else:
        artifact_ids.add(artifact_id)
    if not artifact.get("artifact_kind"):
        findings.append(_finding("ARTIFACT_KIND_MISSING", str(artifact_id)))
    if (
        not isinstance(artifact_ref, str)
        or not artifact_ref.startswith("harness-resource://execution/")
        or ".." in artifact_ref
    ):
        findings.append(_finding("ARTIFACT_REF_NOT_PORTABLE", str(artifact_ref)))
    elif artifact_ref in artifact_refs:
        findings.append(_finding("ARTIFACT_REF_DUPLICATE", artifact_ref))
    else:
        artifact_refs.add(artifact_ref)
    schema = artifact.get("schema")
    if not isinstance(schema, Mapping):
        findings.append(_finding("ARTIFACT_SCHEMA_MISSING", str(artifact_id)))
    else:
        required = schema.get("required")
        properties = schema.get("properties")
        if (
            schema.get("type") != "object"
            or not isinstance(required, list)
            or not required
            or not isinstance(properties, Mapping)
            or not set(required).issubset(properties)
        ):
            findings.append(_finding("ARTIFACT_SCHEMA_INCOMPLETE", str(artifact_id)))
        artifact_kind = str(artifact.get("artifact_kind") or "")
        if isinstance(artifact.get("job_id"), str):
            if (
                properties.get("job_id", {}).get("const")
                != artifact.get("job_id")
                or properties.get("source_id", {}).get("const")
                != artifact.get("source_id")
                or not {"job_id", "source_id"}.issubset(set(required))
            ):
                findings.append(
                    _finding(
                        "ARTIFACT_JOB_NAMESPACE_BINDING_INVALID",
                        str(artifact_id),
                    )
                )
    if not artifact.get("production_rule"):
        findings.append(_finding("ARTIFACT_PRODUCTION_RULE_MISSING", str(artifact_id)))
    validation_rule = artifact.get("validation_rule")
    if not isinstance(validation_rule, Mapping) or any(
        not validation_rule.get(field)
        for field in ("validator_owner", "decision_rule", "evidence_required")
    ):
        findings.append(_finding("ARTIFACT_VALIDATION_RULE_INCOMPLETE", str(artifact_id)))
    oracle = artifact.get("oracle")
    if not isinstance(oracle, Mapping) or any(
        not oracle.get(field)
        for field in ("oracle_id", "independence_level", "decision_rule")
    ) or not isinstance(oracle.get("common_mode_exclusions"), list):
        findings.append(_finding("ARTIFACT_ORACLE_INCOMPLETE", str(artifact_id)))
    elif artifact.get("artifact_kind") in (
        JOB_SCOPED_ARTIFACT_KINDS | {"FIXTURE_ACCEPTANCE_RECEIPT"}
    ) and (
        not oracle.get("evaluator_id")
        or oracle.get("evaluator_registry_ref") != ORACLE_EVALUATOR_REGISTRY_REF
    ):
        findings.append(
            _finding("ARTIFACT_EXECUTABLE_ORACLE_BINDING_MISSING", str(artifact_id))
        )
    failure_return = artifact.get("failure_return")
    if not isinstance(failure_return, Mapping) or any(
        not failure_return.get(field)
        for field in ("error_code", "control_node_id", "invalidates")
    ):
        findings.append(_finding("ARTIFACT_FAILURE_RETURN_INCOMPLETE", str(artifact_id)))
    failure_returns = artifact.get("failure_returns")
    if failure_returns is not None:
        valid_routes = (
            isinstance(failure_returns, list)
            and bool(failure_returns)
            and all(
                isinstance(route, Mapping)
                and all(
                    route.get(field)
                    for field in ("error_code", "control_node_id", "invalidates")
                )
                for route in failure_returns
            )
        )
        route_codes = (
            [str(route["error_code"]) for route in failure_returns]
            if valid_routes
            else []
        )
        if (
            not valid_routes
            or len(route_codes) != len(set(route_codes))
            or failure_return != failure_returns[0]
        ):
            findings.append(
                _finding(
                    "ARTIFACT_FAILURE_RETURN_SET_INVALID",
                    str(artifact_id),
                )
            )


def _finding(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "message": message}


def _hash_without_field(value: Mapping[str, Any], field: str) -> str:
    document = deepcopy(dict(value))
    document.pop(field, None)
    payload = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
