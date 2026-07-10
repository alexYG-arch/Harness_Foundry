"""Shared constants for the Factory, compiler, and validator."""

from __future__ import annotations

from pathlib import Path


FACTORY_VERSION = "0.1.0"
SCHEMA_VERSION = "1.0"
HF28_SCHEMA_VERSION = "2.8"
HF28_PACKAGE_ID = "HARNESS_FOUNDRY_V2_8_START_PACKAGE"

FACTORY_STATES = (
    "NEW",
    "INTAKE_OPEN",
    "CLARIFYING",
    "REQUIREMENTS_READBACK_READY",
    "WAITING_REQUIREMENTS_FREEZE",
    "REQUIREMENTS_FROZEN",
    "GENERATING",
    "VALIDATING",
    "CANDIDATE_READY_FOR_HUMAN_REVIEW",
    "BLOCKED_SOURCE_CONFLICT",
    "BLOCKED_REQUIREMENT_GAP",
    "SPEC_DRIFT",
    "STATE_CONFLICT",
    "OUTPUT_COLLISION",
    "REOPEN_REQUIRED",
)

TERMINAL_CANDIDATE_STATE = "CANDIDATE_READY_FOR_HUMAN_REVIEW"
TARGET_CANDIDATE_STATE = "START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW"

PROJECTS = (
    ("EXTERNAL_CONFORMANCE_LAB", "external_lab"),
    ("CONFORMANCE_LINKAGE_REVIEW", "linkage_review"),
    ("MAIN_HARNESS_BUILD", "main_build"),
)

# The engineering DAG is intentionally higher-level than the project-local
# Workpack indexes.  These bindings make that relationship explicit so a
# Driver never has to infer a Workpack from a node name.
DAG_WORKPACK_BINDINGS = {
    "LAB_SELF_CONFORMANCE_PASS": "LAB-SELFTEST",
    "LINKAGE_SELF_CONFORMANCE_PASS": "LINK-SELFTEST",
    "MAIN_G0_C0": "MB-G0",
    "MAIN_P1_C1": "MB-P1",
    "MAIN_P2_C2": "MB-P2",
    "MAIN_P3_C3_OR_APPROVED_NA": "MB-P3",
    "MAIN_P4_LOCAL_CLOSURE": "MB-P4",
}

DAG_WORKPACK_SEQUENCE_BINDINGS = {
    "LAB_BOOTSTRAP": ("LAB-PROTOCOL", "LAB-CLI", "LAB-FIXTURES"),
    "LINKAGE_BOOTSTRAP": ("LINK-PROTOCOL", "LINK-CLI"),
}

# Project-local Workpacks that execute only after the engineering DAG hands
# control to the release pipeline.
RELEASE_WORKPACK_BINDINGS = {
    "LINKAGE_A_INTERFACE_COMPLETENESS": "LINK-PREFLIGHT",
    "P4_RELEASE_CANDIDATE_LOCK": "MB-RELEASE-CANDIDATE",
    "LINKAGE_D_INSTALLED_HANDSHAKE": "LINK-D",
    "LAB_INSTALLED_POSITIVE_NEGATIVE_TAMPER_TESTS": "LAB-CERTIFICATION",
}

# Every project-local Workpack has an explicit capability and command contract.
# ``requirement_sources`` identifies the one machine surface that must produce
# each required capability before the Workpack can become eligible.
PROJECT_WORKPACK_CONTRACTS = {
    "LAB-PROTOCOL": {
        "project_id": "EXTERNAL_CONFORMANCE_LAB",
        "requires": ("SHARED_PROTOCOL_LOCK_VALID",),
        "requirement_sources": {
            "SHARED_PROTOCOL_LOCK_VALID": "ENGINEERING_DAG:SHARED_CONTROL_BASELINE_LOCK",
        },
        "produces": ("LAB_PROTOCOL_SCHEMA_PASS",),
        "command_ids": ("LAB-CODEX-CODING",),
        "execution_mode": "WORKPACK_EXECUTION",
    },
    "LAB-CLI": {
        "project_id": "EXTERNAL_CONFORMANCE_LAB",
        "requires": ("LAB_PROTOCOL_SCHEMA_PASS",),
        "requirement_sources": {
            "LAB_PROTOCOL_SCHEMA_PASS": "PROJECT_WORKPACK:LAB-PROTOCOL",
        },
        "produces": ("LAB_CLI_READY",),
        "command_ids": ("LAB-CODEX-CODING",),
        "execution_mode": "WORKPACK_EXECUTION",
    },
    "LAB-FIXTURES": {
        "project_id": "EXTERNAL_CONFORMANCE_LAB",
        "requires": ("LAB_CLI_READY",),
        "requirement_sources": {
            "LAB_CLI_READY": "PROJECT_WORKPACK:LAB-CLI",
        },
        "produces": ("POSITIVE_AND_NEGATIVE_FIXTURES_READY",),
        "command_ids": ("LAB-CODEX-CODING",),
        "execution_mode": "WORKPACK_EXECUTION",
    },
    "LAB-SELFTEST": {
        "project_id": "EXTERNAL_CONFORMANCE_LAB",
        "requires": ("POSITIVE_AND_NEGATIVE_FIXTURES_READY",),
        "requirement_sources": {
            "POSITIVE_AND_NEGATIVE_FIXTURES_READY": "PROJECT_WORKPACK:LAB-FIXTURES",
        },
        "produces": ("LAB_SELFTEST_PASS",),
        "command_ids": ("LAB-SELFTEST",),
        "execution_mode": "PROJECT_VALIDATION",
    },
    "LAB-CERTIFICATION": {
        "project_id": "EXTERNAL_CONFORMANCE_LAB",
        "requires": (
            "LAB_SELFTEST_PASS",
            "P4_RELEASE_CANDIDATE_LOCK_VALID",
            "CERTIFICATION_INSTALL_ONCE_PASS",
            "LINKAGE_D_PASS",
        ),
        "requirement_sources": {
            "LAB_SELFTEST_PASS": "PROJECT_WORKPACK:LAB-SELFTEST",
            "P4_RELEASE_CANDIDATE_LOCK_VALID": "RELEASE_PIPELINE:P4_RELEASE_CANDIDATE_LOCK",
            "CERTIFICATION_INSTALL_ONCE_PASS": "RELEASE_PIPELINE:CERTIFICATION_INSTALL_ONCE",
            "LINKAGE_D_PASS": "RELEASE_PIPELINE:LINKAGE_D_INSTALLED_HANDSHAKE",
        },
        "produces": ("LAB_INSTALLED_TEST_EVIDENCE_READY",),
        "command_ids": ("LAB-CERTIFY",),
        "execution_mode": "LAB_CERTIFICATION",
    },
    "LINK-PROTOCOL": {
        "project_id": "CONFORMANCE_LINKAGE_REVIEW",
        "requires": ("SHARED_PROTOCOL_LOCK_VALID",),
        "requirement_sources": {
            "SHARED_PROTOCOL_LOCK_VALID": "ENGINEERING_DAG:SHARED_CONTROL_BASELINE_LOCK",
        },
        "produces": ("LINK_PROTOCOL_SCHEMA_PASS",),
        "command_ids": ("LINK-CODEX-CODING",),
        "execution_mode": "WORKPACK_EXECUTION",
    },
    "LINK-CLI": {
        "project_id": "CONFORMANCE_LINKAGE_REVIEW",
        "requires": (
            "LINK_PROTOCOL_SCHEMA_PASS",
            "EXTERNAL_LAB_INTERFACE_REGISTERED",
        ),
        "requirement_sources": {
            "LINK_PROTOCOL_SCHEMA_PASS": "PROJECT_WORKPACK:LINK-PROTOCOL",
            "EXTERNAL_LAB_INTERFACE_REGISTERED": "ENGINEERING_DAG:LAB_TOOL_RELEASE_LOCKED",
        },
        "produces": ("LINK_CLI_READY", "READ_ONLY_NEGATIVE_TESTS_READY"),
        "command_ids": ("LINK-CODEX-CODING",),
        "execution_mode": "WORKPACK_EXECUTION",
    },
    "LINK-SELFTEST": {
        "project_id": "CONFORMANCE_LINKAGE_REVIEW",
        "requires": ("LINK_CLI_READY", "READ_ONLY_NEGATIVE_TESTS_READY"),
        "requirement_sources": {
            "LINK_CLI_READY": "PROJECT_WORKPACK:LINK-CLI",
            "READ_ONLY_NEGATIVE_TESTS_READY": "PROJECT_WORKPACK:LINK-CLI",
        },
        "produces": ("LINK_SELFTEST_PASS",),
        "command_ids": ("LINK-SELFTEST",),
        "execution_mode": "PROJECT_VALIDATION",
    },
    "LINK-PREFLIGHT": {
        "project_id": "CONFORMANCE_LINKAGE_REVIEW",
        "requires": ("LINK_SELFTEST_PASS", "MAIN_AND_LAB_INTERFACES_REGISTERED"),
        "requirement_sources": {
            "LINK_SELFTEST_PASS": "PROJECT_WORKPACK:LINK-SELFTEST",
            "MAIN_AND_LAB_INTERFACES_REGISTERED": "ENGINEERING_DAG:MAIN_PROGRAM_REGISTRATION",
        },
        "produces": ("LINKAGE_A_EVIDENCE_READY",),
        "command_ids": ("LINK-PREFLIGHT-CHECK",),
        "execution_mode": "LINKAGE_READ_ONLY",
    },
    "LINK-D": {
        "project_id": "CONFORMANCE_LINKAGE_REVIEW",
        "requires": (
            "P4_RELEASE_CANDIDATE_LOCK_VALID",
            "INSTALLED_TARGET_DESCRIPTOR_VERIFIED",
        ),
        "requirement_sources": {
            "P4_RELEASE_CANDIDATE_LOCK_VALID": "RELEASE_PIPELINE:P4_RELEASE_CANDIDATE_LOCK",
            "INSTALLED_TARGET_DESCRIPTOR_VERIFIED": "RELEASE_PIPELINE:INSTALLED_TARGET_DESCRIPTOR",
        },
        "produces": ("LINKAGE_D_EVIDENCE_READY",),
        "command_ids": ("LINK-D",),
        "execution_mode": "LINKAGE_READ_ONLY",
    },
    "MB-G0": {
        "project_id": "MAIN_HARNESS_BUILD",
        "requires": ("CHARTER_LOCK_VALID",),
        "requirement_sources": {
            "CHARTER_LOCK_VALID": "ENGINEERING_DAG:SHARED_CONTROL_BASELINE_LOCK",
        },
        "produces": ("G0_CONTROL_LOCK_VALID",),
        "command_ids": ("MB-CODEX-CODING", "MB-TEST"),
        "execution_mode": "WORKPACK_EXECUTION",
    },
    "MB-P1": {
        "project_id": "MAIN_HARNESS_BUILD",
        "requires": ("G0_CONTROL_LOCK_VALID",),
        "requirement_sources": {
            "G0_CONTROL_LOCK_VALID": "PROJECT_WORKPACK:MB-G0",
        },
        "produces": ("P1_BUILD_LOCK_VALID",),
        "command_ids": ("MB-CODEX-CODING", "MB-TEST"),
        "execution_mode": "WORKPACK_EXECUTION",
    },
    "MB-P2": {
        "project_id": "MAIN_HARNESS_BUILD",
        "requires": ("P1_BUILD_LOCK_VALID",),
        "requirement_sources": {
            "P1_BUILD_LOCK_VALID": "PROJECT_WORKPACK:MB-P1",
        },
        "produces": ("P2_BUILD_LOCK_VALID",),
        "command_ids": ("MB-CODEX-CODING", "MB-TEST"),
        "execution_mode": "WORKPACK_EXECUTION",
    },
    "MB-P3": {
        "project_id": "MAIN_HARNESS_BUILD",
        "requires": ("P2_BUILD_LOCK_VALID",),
        "requirement_sources": {
            "P2_BUILD_LOCK_VALID": "PROJECT_WORKPACK:MB-P2",
        },
        "produces": ("P3_BUILD_LOCK_VALID",),
        "command_ids": ("MB-CODEX-CODING", "MB-TEST"),
        "execution_mode": "WORKPACK_EXECUTION",
    },
    "MB-P4": {
        "project_id": "MAIN_HARNESS_BUILD",
        "requires": (
            "P3_BUILD_LOCK_OR_APPROVED_P3_NA_LOCK_VALID",
            "C3_CHECKPOINT_PASS",
        ),
        "requirement_sources": {
            "P3_BUILD_LOCK_OR_APPROVED_P3_NA_LOCK_VALID": "ENGINEERING_DAG:MAIN_P3_C3_OR_APPROVED_NA",
            "C3_CHECKPOINT_PASS": "ENGINEERING_DAG:MAIN_P3_C3_OR_APPROVED_NA",
        },
        "produces": ("P4_LOCAL_GATE_PASS",),
        "command_ids": ("MB-CODEX-CODING", "MB-TEST"),
        "execution_mode": "WORKPACK_EXECUTION",
    },
    "MB-RELEASE-CANDIDATE": {
        "project_id": "MAIN_HARNESS_BUILD",
        "requires": (
            "P4_BUILD_INPUT_LOCK_VALID",
            "PACK_B1_PASS",
            "P4_INSTALLABILITY_PASS",
        ),
        "requirement_sources": {
            "P4_BUILD_INPUT_LOCK_VALID": "RELEASE_PIPELINE:P4_BUILD_INPUT_LOCK",
            "PACK_B1_PASS": "RELEASE_PIPELINE:LINKAGE_B1_ARTIFACT_BINDING",
            "P4_INSTALLABILITY_PASS": "RELEASE_PIPELINE:P4_INSTALLABILITY_RECEIPT",
        },
        "produces": ("MAIN_RELEASE_CANDIDATE_PREPARED",),
        "command_ids": ("MB-RELEASE-CANDIDATE-PREPARE",),
        "execution_mode": "REGISTRATION_ONLY",
    },
}

ROOT_MATERIALIZATION_REQUIRES = (
    "LAB_TOOL_RELEASE_LOCK_VALID",
    "LINKAGE_TOOL_RELEASE_LOCK_VALID",
)
ROOT_MATERIALIZATION_PRODUCES = ("MAIN_EXECUTION_PACKAGE_MATERIALIZED_READY",)
ROOT_MATERIALIZATION_COMMAND_IDS = (
    "ROOT-CODEX-CODING",
    "ROOT-MATERIALIZATION-VERIFY",
)

PROJECT_REQUIRED_FILES = (
    "README.md",
    "PROJECT_CHARTER.md",
    "PROJECT_STATE.json",
    "WORKPACK_INDEX.json",
    "COMMAND_MANIFEST.json",
    "BUILD_INSTALL_PLAN.md",
)

TARGET_REQUIRED_DIRECTORIES = (
    "canonical_sources/",
    "workpacks/",
    "capsules/",
    "commands/",
    "results/",
    "loops/",
    "evidence/",
    "validation/",
    "build_program/conformance/",
    "constitution/",
)

TARGET_REQUIRED_ENTRY_FILES = (
    "README.md",
    "START_HERE.md",
    "START.md",
    "PACKAGE_MANIFEST.json",
    "START_CONTEXT.json",
    "PROGRAM_CHARTER.md",
    "TARGET_PROFILE.md",
    "PROFILE_LOCK.json",
    "CHARTER_LOCK.json",
    "PROGRAM_STATE.json",
    "THREE_PROJECT_PROGRAM_MANIFEST.json",
    "ENGINEERING_PROJECT_DAG.json",
    "PHASE_DEPENDENCY_MANIFEST.json",
    "PHASE_TRANSITION_LEDGER.jsonl",
    "WORKPACK_INDEX.json",
    "WORKPACK_RESULT.json",
    "COMMAND_MANIFEST.json",
    "CAPSULE.json",
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
    "PROMOTION_LEDGER.jsonl",
    "REVOCATION_LEDGER.jsonl",
    "PACKAGE_ROLES.json",
    "AUTHORITY_AND_EXECUTION_BOUNDARY.md",
    "AUTHORING_HANDOFF.md",
)

PHASE_ORDER = (
    "G0",
    "C0",
    "P1",
    "C1",
    "P2",
    "C2",
    "P3",
    "C3",
    "P4_BUILD_INPUT",
    "RELEASE_PIPELINE",
    "C4",
    "CERTIFIED_RELEASE",
)

ENGINEERING_NODE_ORDER = (
    "START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW",
    "START_PACKAGE_HUMAN_APPROVAL",
    "SHARED_CONTROL_BASELINE_LOCK",
    "CONTROL_PLANE_REGISTRATION",
    "PROGRAM_DRIVER_RUNTIME_VERIFIED",
    "LAB_BOOTSTRAP",
    "LAB_SELF_CONFORMANCE_PASS",
    "LAB_TOOL_RELEASE_LOCKED",
    "LINKAGE_BOOTSTRAP",
    "LINKAGE_SELF_CONFORMANCE_PASS",
    "LINKAGE_TOOL_RELEASE_LOCKED",
    "MAIN_EXECUTION_PACKAGE_MATERIALIZED",
    "MAIN_EXECUTION_PACKAGE_VALIDATED",
    "MAIN_PROGRAM_REGISTRATION",
    "MAIN_G0_C0",
    "MAIN_P1_C1",
    "MAIN_P2_C2",
    "MAIN_P3_C3_OR_APPROVED_NA",
    "MAIN_P4_LOCAL_CLOSURE",
    "RELEASE_PIPELINE_HANDOFF",
)

RELEASE_STEP_ORDER = (
    "P4_BUILD_INPUT_LOCK",
    "PACK_DRAFT",
    "LINKAGE_A_INTERFACE_COMPLETENESS",
    "LINKAGE_B0_NORMATIVE_BINDING",
    "LINKAGE_C_EVIDENCE_COMPATIBILITY",
    "IMMUTABLE_ARTIFACT_BUILD",
    "LINKAGE_B1_ARTIFACT_BINDING",
    "P4_INSTALLABILITY_ENV_CREATE",
    "EXACT_ARTIFACT_INSTALL_AND_ORIGIN_CHECK",
    "P4_INSTALLABILITY_RECEIPT",
    "P4_RELEASE_CANDIDATE_LOCK",
    "SINGLE_CERTIFICATION_ENV_CREATE",
    "CERTIFICATION_INSTALL_ONCE",
    "INSTALLED_TARGET_DESCRIPTOR",
    "LINKAGE_D_INSTALLED_HANDSHAKE",
    "LAB_INSTALLED_POSITIVE_NEGATIVE_TAMPER_TESTS",
    "C4_REPORT",
    "CONFORMANCE_CERTIFICATE",
    "P4_CERTIFIED_RELEASE_LOCK",
    "WAIT_REAL_TARGET_INSTALL_AUTHORIZATION",
    "REAL_TARGET_INSTALL",
    "REAL_TARGET_INSTALLATION_RECEIPT",
    "ACTIVE_INSTANCE_MANIFEST",
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_spec_root() -> Path:
    return project_root().parent / "Harness_Foundry_v2_8_Start_Package"


def default_runs_root() -> Path:
    return project_root() / "runs"
