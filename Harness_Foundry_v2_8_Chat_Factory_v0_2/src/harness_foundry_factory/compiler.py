"""Deterministically compile a frozen Requirement IR into a v2.8 candidate."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Mapping

from .constants import (
    DAG_WORKPACK_BINDINGS,
    DAG_WORKPACK_SEQUENCE_BINDINGS,
    ENGINEERING_NODE_ORDER,
    PHASE_ORDER,
    PROJECT_WORKPACK_CONTRACTS,
    PROJECTS,
    RELEASE_WORKPACK_BINDINGS,
    RELEASE_STEP_ORDER,
    ROOT_MATERIALIZATION_COMMAND_IDS,
    ROOT_MATERIALIZATION_PRODUCES,
    ROOT_MATERIALIZATION_REQUIRES,
    TARGET_CANDIDATE_STATE,
    default_spec_root,
)
from .traceability import WORKPACK_PROJECTS, normalize_ir_coverage


PLACEHOLDER_RE = re.compile(r"<[^<>]+>")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
FACTORY_ID = "HARNESS_FOUNDRY_V2_8_CHAT_FACTORY_V0_2"
FACTORY_VERSION = "0.2.0"


def compile_candidate(
    requirement_ir: Mapping[str, Any],
    spec_root: str | Path,
    staging_root: str | Path,
    target_root: str | Path,
    created_at: str,
    spec_lock: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility entrypoint consumed by ``FactoryService``."""

    return compile_start_package(
        requirement_ir,
        spec_root=spec_root,
        staging_root=staging_root,
        candidate_root=target_root,
        created_at=created_at,
        spec_lock=spec_lock,
    )


def compile_start_package(
    requirement_ir: Mapping[str, Any],
    *,
    spec_root: str | Path | None = None,
    staging_root: str | Path,
    candidate_root: str | Path,
    created_at: str,
    spec_lock: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile, fully materialize, and atomically publish one authoring candidate."""

    ir = normalize_ir_coverage(requirement_ir)
    candidate = Path(candidate_root).expanduser().resolve()
    ir_target = ir.get("target")
    if isinstance(ir_target, dict) and ir_target.get("execution_root") in (
        None,
        "",
    ):
        ir_target["execution_root"] = str(
            candidate.with_name(f"{candidate.name}_Execution_Runtime")
        )
    target = _validate_ir(ir)
    spec = Path(spec_root or default_spec_root()).expanduser().resolve()
    staging = Path(staging_root).expanduser().resolve()
    execution = Path(
        str(target["execution_root"])
    ).expanduser().resolve()
    if not spec.is_dir():
        raise ValueError(f"v2.8 spec root does not exist: {spec}")
    target_id = str(target["id"])
    target_name = str(target["name"])
    target_type = str(target["type"]).upper()
    profile = str(target["profile"]).upper()
    program_id = str(ir.get("program_id") or f"PROGRAM-{target_id}")
    package_id = f"{target_id}-START-PACKAGE"
    ir_hash = _json_hash(ir)
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
            else "LEGACY_COMBINED_CANDIDATE_AND_EXECUTION_ROOT"
        ),
        "created_at": created_at,
        "ir_hash": ir_hash,
        "first_workpack_id": first_workpack_id,
        "primary_runtime": str(target["primary_runtime"]),
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
            "factory_version": FACTORY_VERSION,
            "program_id": program_id,
            "target_id": target_id,
            "requirement_ir_sha256": ir_hash,
            "spec_content_sha256": spec_hash,
            "spec_file_count": spec_file_count,
            "created_at": created_at,
            "execution_started": False,
        },
    )

    _write_markdown_documents(staging, ir, context)
    source_manifest = _source_manifest(ir, context)
    _write_json(staging / "canonical_sources/SOURCE_MANIFEST.json", source_manifest)
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
        {"schema_version": "2.8", "target_id": target_id, "cases": ir["acceptance_cases"], "status": "PLANNED_NOT_RUN"},
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

    _patch_critical_documents(documents, ir, context, staging, candidate)
    for destination, document in documents.items():
        _write_json(staging / destination, document)
    _write_json(
        staging / "constitution/RUNTIME_OWNERSHIP.json",
        _runtime_ownership(context, candidate),
    )

    _materialize_workpack_files(staging, ir, context, documents)
    _materialize_project_packages(staging, spec, ir, context, candidate)
    _write_ledgers(staging, context)
    _write_validation_report(staging, context)

    unresolved = _scan_placeholders(staging)
    if unresolved:
        raise ValueError(f"compiler left unresolved template placeholders: {unresolved[:5]}")
    template_files = [path for path in staging.rglob("*") if path.is_file() and ".template." in path.name]
    if template_files:
        raise ValueError("compiler copied template filenames into the candidate")

    from .validator import validate_candidate

    staging_report = validate_candidate(
        staging,
        expected_target_root=candidate,
        require_internal_report=False,
    )
    repair_attempts = 0
    while staging_report.get("status") != "PASS" and repair_attempts < 3:
        repair_attempts += 1
        _repair_structural_hashes(staging)
        staging_report = validate_candidate(
            staging,
            expected_target_root=candidate,
            require_internal_report=False,
        )
    if staging_report.get("status") != "PASS":
        _write_json(staging / "validation/STAGING_VALIDATION_FAILURE.json", staging_report)
        codes = [item.get("code") for item in staging_report.get("blocking_findings", [])]
        raise ValueError(f"candidate staging validation failed: {codes}")
    _write_validation_report(
        staging,
        context,
        validator_report=staging_report,
        repair_attempts=repair_attempts,
    )
    final_staging_report = validate_candidate(
        staging,
        expected_target_root=candidate,
        require_internal_report=True,
    )
    if final_staging_report.get("status") != "PASS":
        raise ValueError(
            "candidate final staging validation failed: "
            f"{[item.get('code') for item in final_staging_report.get('blocking_findings', [])]}"
        )

    candidate.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, candidate)
    content_hash, file_count = _tree_hash(candidate)
    return {
        "program_id": program_id,
        "target_id": target_id,
        "candidate_path": str(candidate),
        "manifest_path": str(candidate / "PACKAGE_MANIFEST.json"),
        "file_count": file_count,
        "content_sha256": content_hash,
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
    immutability = target.get("start_package_immutability_policy") or ir.get(
        "start_package_immutability_policy"
    )
    if isinstance(immutability, Mapping) and execution_root_value in (None, ""):
        raise ValueError(
            "target.execution_root is required by start_package_immutability_policy"
        )
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
    required_automation_fields = {
        "schema_version",
        "requested_level",
        "activation_default",
        "max_transitions",
        "max_loop_rounds",
        "max_wall_time_seconds",
        "stop_gate",
        "retryable_error_codes",
        "mandatory_human_gate_ids",
        "real_target_install_excluded",
        "execution_mode",
        "auto_start_generated_workpacks",
        "execution_started",
    }
    if set(automation) != required_automation_fields:
        raise ValueError(
            "requirement_ir.automation must use the complete v1.0 Automation Profile"
        )
    if automation.get("schema_version") != "1.0":
        raise ValueError("requirement_ir.automation.schema_version must be 1.0")
    if automation.get("requested_level") not in {
        "A0_DECLARE_ONLY",
        "A1_PLAN_ONLY",
        "A2_WORKPACK_BOUNDED",
        "A3_PROGRAM_BOUNDED",
    }:
        raise ValueError("requirement_ir.automation.requested_level is invalid")
    if (
        automation.get("activation_default") != "DISABLED"
        or automation.get("real_target_install_excluded") is not True
        or automation.get("execution_mode") != "AUTHORING_ONLY"
        or automation.get("auto_start_generated_workpacks") is not False
        or automation.get("execution_started") is not False
    ):
        raise ValueError("requirement_ir.automation violates the authoring boundary")
    for key in (
        "max_transitions",
        "max_loop_rounds",
        "max_wall_time_seconds",
    ):
        if key in automation and (
            not isinstance(automation[key], int) or automation[key] <= 0
        ):
            raise ValueError(f"requirement_ir.automation.{key} must be a positive integer")
    for key in ("retryable_error_codes", "mandatory_human_gate_ids"):
        if (
            not isinstance(automation.get(key), list)
            or not all(
                isinstance(item, str) and item
                for item in automation.get(key, [])
            )
            or len(set(automation.get(key, []))) != len(automation.get(key, []))
        ):
            raise ValueError(
                f"requirement_ir.automation.{key} must contain unique strings"
            )
    if not isinstance(automation.get("stop_gate"), str) or not automation[
        "stop_gate"
    ]:
        raise ValueError("requirement_ir.automation.stop_gate must be non-empty")
    return dict(target)


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


def _atom_catalog(ir: Mapping[str, Any], source_manifest: Mapping[str, Any], context: Mapping[str, str]) -> dict[str, Any]:
    default_source = source_manifest["sources"][0]["source_id"]
    atoms: list[dict[str, Any]] = []
    for index, raw in enumerate(ir["atoms"], 1):
        item = dict(raw) if isinstance(raw, Mapping) else {"text_or_lossless_paraphrase": str(raw)}
        atom_id = str(item.get("atom_id") or f"ATOM-{index:03d}")
        atoms.append(
            {
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
        )
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


def _patch_critical_documents(
    docs: dict[str, Any],
    ir: Mapping[str, Any],
    context: Mapping[str, str],
    staging: Path,
    candidate: Path,
) -> None:
    target = ir["target"]
    execution = Path(context["execution_root"])
    manifest = docs["PACKAGE_MANIFEST.json"]
    manifest.update(
        {
            "package_id": context["package_id"],
            "target_id": context["target_id"],
            "version": "0.2.0-draft",
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
            "package_version": "0.2.0-draft",
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
    start["controlled_auto_advance"].update(
        {"enabled": False, "authorization_status": "NOT_GRANTED", "real_target_install_excluded": True}
    )

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
    automation = dict(ir.get("automation", {}))
    automation_profile = {
        "schema_version": "1.0",
        "requested_level": str(
            automation.get("requested_level", "A1_PLAN_ONLY")
        ),
        "activation_default": "DISABLED",
        "max_transitions": int(automation.get("max_transitions", 32)),
        "max_loop_rounds": int(automation.get("max_loop_rounds", 3)),
        "max_wall_time_seconds": int(
            automation.get("max_wall_time_seconds", 3600)
        ),
        "stop_gate": str(
            automation.get("stop_gate", "P4_CERTIFIED_RELEASE_LOCK")
        ),
        "retryable_error_codes": list(
            automation.get(
                "retryable_error_codes",
                ["RUNNER_TRANSPORT_TEMPORARY_FAILURE"],
            )
        ),
        "mandatory_human_gate_ids": list(
            automation.get(
                "mandatory_human_gate_ids",
                [
                    "START_PACKAGE_HUMAN_APPROVAL",
                    "P3_NOT_APPLICABLE_DECISION",
                    "REAL_TARGET_INSTALL",
                ],
            )
        ),
        "real_target_install_excluded": True,
    }
    docs["PROGRAM_AUTOMATION_POLICY.json"].update(
        {
            "program_id": context["program_id"],
            "default_mode": "AUTHORING_ONLY",
            "automatic_progress_default": False,
            "authoring_may_start_driver": False,
            "automation_profile": automation_profile,
            "planned_limits_from_frozen_ir": {
                "max_transitions": automation_profile["max_transitions"],
                "max_loop_rounds": automation_profile["max_loop_rounds"],
                "max_wall_time_seconds": automation_profile[
                    "max_wall_time_seconds"
                ],
                "stop_gate": automation_profile["stop_gate"],
            },
        }
    )
    docs["PROGRAM_AUTOMATION_POLICY.json"].setdefault(
        "controlled_auto_advance", {}
    )["max_transitions_per_driver_invocation"] = automation_profile[
        "max_transitions"
    ]
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
    max_loop_rounds = automation_profile["max_loop_rounds"]
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
            "intent_atom_ids": [str(item.get("atom_id")) for item in ir["atoms"]],
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
            "required_outputs": [
                *ROOT_MATERIALIZATION_PRODUCES,
                "MAIN_PACKAGE_VALIDATION_INPUTS_READY",
            ],
            "requires": list(ROOT_MATERIALIZATION_REQUIRES),
            "requirement_sources": {
                "LAB_TOOL_RELEASE_LOCK_VALID": "ENGINEERING_DAG:LAB_TOOL_RELEASE_LOCKED",
                "LINKAGE_TOOL_RELEASE_LOCK_VALID": "ENGINEERING_DAG:LINKAGE_TOOL_RELEASE_LOCKED",
            },
            "produces": list(ROOT_MATERIALIZATION_PRODUCES),
            "command_ids": list(ROOT_MATERIALIZATION_COMMAND_IDS),
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
    binding = {
        "program_id": context["program_id"],
        "profile_lock_hash": profile_hash,
        "charter_hash": charter_hash,
        "control_plane_epoch": 0,
    }
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


def _engineering_nodes(
    context: Mapping[str, str],
    candidate: Path,
    *,
    profile_hash: str,
    charter_hash: str,
) -> list[dict[str, Any]]:
    execution = Path(context["execution_root"])
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
        write_paths = []
        if index > 1:
            write_paths = [str(execution / "evidence/engineering_dag" / node_id)]
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
                "allowed_read_paths": [str(candidate)],
                "allowed_write_paths": write_paths,
                "environment_id": f"ENV-{_slug(node_id)}-PLANNED",
                "success_gate": success_gate,
                "success_output_refs": [
                    str(execution / "evidence/engineering_dag" / f"{node_id}.result.json")
                ],
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


def _mandatory_negative_cases(ir: Mapping[str, Any]) -> list[dict[str, Any]]:
    atom_ids = [
        str(item.get("atom_id"))
        for item in ir.get("atoms", [])
        if isinstance(item, Mapping) and item.get("atom_id")
    ]
    mandatory = (
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
    cases = [
        deepcopy(dict(item))
        for item in ir.get("negative_cases", [])
        if isinstance(item, Mapping)
    ]
    for case in cases:
        if not case.get("expected_failure"):
            case["expected_failure"] = "EXPECTED_REJECTION"
        if not case.get("origin"):
            case["origin"] = "FROZEN_REQUIREMENT_IR"
    existing = {str(item.get("case_id")) for item in cases}
    for case_id, description, expected_failure in mandatory:
        if case_id not in existing:
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


def _materialize_workpack_files(staging: Path, ir: Mapping[str, Any], context: Mapping[str, str], docs: Mapping[str, Any]) -> None:
    workpack_id = context["first_workpack_id"]
    mission = str(ir["target"]["mission"])
    atom_ids = [str(item.get("atom_id")) for item in ir["atoms"] if isinstance(item, Mapping)]
    workpack = f"""# Workpack: {workpack_id}

Status: `PLANNED_NOT_ACTIVE`

## Objective

Materialize the Main execution package and its G0 control foundation for {context['target_name']}: {mission}

## Boundary

- Program DAG node: `MAIN_EXECUTION_PACKAGE_MATERIALIZED`
- Project: `MAIN_HARNESS_BUILD`
- Required atoms: {', '.join(atom_ids)}
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

- Positive, negative, and boundary cases are mapped to the frozen Atom catalog.
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


def _materialize_project_workpack_contracts(
    output: Path,
    *,
    project_id: str,
    directory: str,
    coverage_edges: list[Mapping[str, Any]],
    context: Mapping[str, str],
    candidate: Path,
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
    evidence_root = execution / "evidence/project_workpacks" / project_id
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
        coding_workpack = any(
            command_id.endswith("CODEX-CODING") for command_id in command_ids
        )
        allowed_write_paths = [str(evidence_root / workpack_id)]
        if coding_workpack:
            allowed_write_paths.append(str(repository))
        workpack_ref = f"workpacks/{workpack_id}.md"
        command_ref = f"commands/{workpack_id}.commands.json"
        capsule_ref = f"capsules/{workpack_id}.capsule.json"
        result_ref = f"results/{workpack_id}.result.json"
        loop_ref = f"loops/{workpack_id}.loop.json"
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
                "allowed_read_paths": [str(candidate)],
                "allowed_write_paths": allowed_write_paths,
                "execution_authorization_ref": None,
                "auto_start": False,
                "success_rule": "ALL_REQUIRED_COMMANDS_AND_CAPABILITIES_VALID",
                "failure_return_node": workpack["program_control_node_id"],
            }
        )
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

## Command and path contract

- Command IDs in order: {', '.join(command_ids)}
- Intent Atom IDs: {', '.join(intent_atom_ids) if intent_atom_ids else 'none explicitly routed'}
- Allowed read root: `{candidate}`
- Allowed write roots: {', '.join(f'`{value}`' for value in allowed_write_paths)}
- Execution authorization: not granted

## Completion and return

All required command receipts, input capability sources, produced capability evidence, Hash bindings, and the owning Program control Gate must validate. Failure returns to `{workpack['program_control_node_id']}` through the single-owner repair and reentry contract.

## Non-claims

This Workpack is declarative and has not been hydrated, executed, promoted, installed, or certified.
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
            "commands": [deepcopy(commands_by_id[value]) for value in command_ids],
        }
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
            "allowed_read_paths": [str(candidate)],
            "allowed_write_paths": allowed_write_paths,
            "repository_root_abs": str(repository),
            "repository_status": "PLANNED_NOT_CREATED",
            "execution_authorization_ref": None,
            "hydration_complete": False,
            "success_rule": "ALL_REQUIRED_COMMANDS_AND_CAPABILITIES_VALID",
            "return_node": workpack["program_control_node_id"],
        }
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
    _write_json(index_path, index)


def _materialize_project_packages(
    staging: Path,
    spec: Path,
    ir: Mapping[str, Any],
    context: Mapping[str, str],
    candidate: Path,
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
        )


def _write_markdown_documents(staging: Path, ir: Mapping[str, Any], context: Mapping[str, str]) -> None:
    target = ir["target"]
    scope = "\n".join(f"- {item}" for item in target["scope"])
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

{target['mission']}

## Target

- ID: `{context['target_id']}`
- Type: `{context['target_type']}`
- Profile: `{context['profile']}`
- Primary runtime: `{target['primary_runtime']}`

## Scope

{scope}

## Non-goals

{non_goals}

## Authority and completion

The Program Author may generate and statically validate this candidate only. Human approval, registration, engineering execution, release, certification, and real target installation are separate authorities and states. Completion of authoring proves only review readiness.
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
        "ARTIFACT_AND_INTERFACE_CONTRACTS.md": """# Artifact and Interface Contracts

All future artifacts bind the frozen source, Atom, Charter, Profile, predecessor Lock, tool distribution, environment, command, evidence, and current Hash. A self-report, file presence, or exit code cannot independently promote a result.
""",
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


def _write_validation_report(
    staging: Path,
    context: Mapping[str, str],
    *,
    validator_report: Mapping[str, Any] | None = None,
    repair_attempts: int = 0,
) -> None:
    validated = validator_report is not None and validator_report.get("status") == "PASS"
    evidence_refs = [
        "PACKAGE_MANIFEST.json",
        "START_CONTEXT.json",
        "canonical_sources/ATOM_COVERAGE_MATRIX.json",
        "PHASE_DEPENDENCY_MANIFEST.json",
        "ENGINEERING_PROJECT_DAG.json",
        "AUTHORING_HANDOFF.md",
    ]
    checks = []
    if validator_report:
        checks = [
            {
                "check_id": item.get("check_id"),
                "status": item.get("status"),
                "finding_count": len(item.get("findings", [])),
                "evidence_refs": evidence_refs,
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


def _recover_existing_candidate(
    candidate: Path,
    *,
    requirement_ir_sha256: str,
    spec_content_sha256: str,
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

    report = validate_candidate(candidate)
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


def _scan_placeholders(root: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in {".md", ".json", ".jsonl"}:
            continue
        text = path.read_text(encoding="utf-8")
        if PLACEHOLDER_RE.search(text) or "/absolute/path/to/" in text or "TBD" in text or "TODO" in text:
            findings.append(path.relative_to(root).as_posix())
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


def _slug(value: str) -> str:
    result = re.sub(r"[^A-Z0-9]+", "-", value.upper()).strip("-")
    return result or "VALUE"
