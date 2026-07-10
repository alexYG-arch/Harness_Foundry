"""Read-only validator for a materialized Harness Foundry v2.8 candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Mapping

from .constants import (
    DAG_WORKPACK_BINDINGS,
    DAG_WORKPACK_SEQUENCE_BINDINGS,
    ENGINEERING_NODE_ORDER,
    PHASE_ORDER,
    PROJECT_REQUIRED_FILES,
    PROJECT_WORKPACK_CONTRACTS,
    PROJECTS,
    RELEASE_WORKPACK_BINDINGS,
    RELEASE_STEP_ORDER,
    ROOT_MATERIALIZATION_COMMAND_IDS,
    ROOT_MATERIALIZATION_PRODUCES,
    ROOT_MATERIALIZATION_REQUIRES,
    TARGET_CANDIDATE_STATE,
    TARGET_REQUIRED_DIRECTORIES,
    TARGET_REQUIRED_ENTRY_FILES,
)
from .traceability import WORKPACK_PROJECTS, WORKPACK_STAGE_COMPATIBILITY


PLACEHOLDER_RE = re.compile(r"<[^<>]+>")
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


CheckFunction = Callable[[Path], list[dict[str, Any]]]


CHECKS: tuple[tuple[str, CheckFunction], ...] = (
    ("REQUIRED_INVENTORY_AND_SYNTAX", lambda root: _check_inventory(root) + _check_syntax(root)),
    ("NO_UNRESOLVED_TEMPLATES", lambda root: _check_placeholders(root)),
    ("IDENTITY_REFERENCES_AND_HASHES", lambda root: _check_identity_and_refs(root)),
    ("WORKPACK_ARTIFACT_HASH_BINDINGS", lambda root: _check_artifact_hashes(root)),
    ("SOURCE_ATOM_AND_COVERAGE", lambda root: _check_sources_atoms_coverage(root)),
    ("PHASE_P3_AND_RELEASE_ORDER", lambda root: _check_phase_and_release(root)),
    ("THREE_PROJECT_DAG_AND_PACKAGES", lambda root: _check_three_projects(root)),
    ("AUTHORING_DEFAULTS_AND_AUTHORIZATION", lambda root: _check_authoring_boundary(root)),
    ("CONTROL_PLANE_HASH_AND_EPOCH_BINDINGS", lambda root: _check_control_bindings(root)),
    ("LOOP_REPAIR_INVALIDATION_AND_RECOVERY", lambda root: _check_control_contracts(root)),
    ("CODEX_FALSE_SUCCESS_AND_INSTALL_BOUNDARY", lambda root: _check_negative_contracts(root)),
    ("VALIDATION_HANDOFF_AND_NONCLAIMS", lambda root: _check_handoff(root)),
)


def validate_candidate(
    root: str | Path,
    spec_lock: Mapping[str, Any] | None = None,
    *,
    expected_target_root: str | Path | None = None,
    require_internal_report: bool = True,
) -> dict[str, Any]:
    """Validate one target package without importing or executing target code."""

    candidate = Path(root).expanduser().resolve()
    before = _tree_snapshot(candidate) if candidate.is_dir() else {}
    checks: list[dict[str, Any]] = []
    for check_id, function in CHECKS:
        try:
            if check_id == "VALIDATION_HANDOFF_AND_NONCLAIMS":
                findings = _check_handoff(
                    candidate, require_internal_report=require_internal_report
                )
            else:
                findings = function(candidate)
        except Exception as exc:  # keep a closed result even for malformed input
            findings = [{"code": "VALIDATOR_CHECK_ERROR", "message": str(exc)}]
        checks.append(
            {
                "check_id": check_id,
                "status": "FAIL" if findings else "PASS",
                "findings": findings,
            }
        )
    logical_root = Path(expected_target_root or candidate).expanduser().resolve()
    binding_findings: list[dict[str, Any]] = []
    try:
        context = json.loads((candidate / "START_CONTEXT.json").read_text(encoding="utf-8"))
        if context.get("target_root") != str(logical_root):
            binding_findings.append(
                _finding(
                    "TARGET_ROOT_MISMATCH",
                    f"expected {logical_root}, got {context.get('target_root')}",
                )
            )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        binding_findings.append(_finding("START_CONTEXT_INVALID", str(exc)))
    checks.append(
        {
            "check_id": "LOGICAL_TARGET_ROOT_BINDING",
            "status": "FAIL" if binding_findings else "PASS",
            "findings": binding_findings,
        }
    )
    after = _tree_snapshot(candidate) if candidate.is_dir() else {}
    if before != after:
        checks.append(
            {
                "check_id": "VALIDATOR_READ_ONLY",
                "status": "FAIL",
                "findings": [{"code": "VALIDATOR_SIDE_EFFECT", "message": "candidate tree changed during validation"}],
            }
        )
    else:
        checks.append({"check_id": "VALIDATOR_READ_ONLY", "status": "PASS", "findings": []})
    provenance_findings: list[dict[str, Any]] = []
    provenance = _read_json(candidate / "FACTORY_PROVENANCE.json", provenance_findings)
    if isinstance(provenance, dict):
        spec_hash = str(provenance.get("spec_content_sha256", ""))
        requirement_hash = str(provenance.get("requirement_ir_sha256", ""))
        if (
            provenance.get("factory_id") != "HARNESS_FOUNDRY_V2_8_CHAT_FACTORY_V0_1"
            or not SHA256_RE.fullmatch(spec_hash)
            or len(set(spec_hash)) == 1
            or provenance.get("execution_started") is not False
            or not SHA256_RE.fullmatch(requirement_hash)
            or len(set(requirement_hash)) == 1
        ):
            provenance_findings.append(
                _finding("FACTORY_PROVENANCE_INVALID", "FACTORY_PROVENANCE.json")
            )
        if isinstance(spec_lock, Mapping):
            if (
                spec_hash != spec_lock.get("content_sha256")
                or provenance.get("spec_file_count") != spec_lock.get("file_count")
            ):
                provenance_findings.append(
                    _finding("SPEC_LOCK_BINDING_MISMATCH", "FACTORY_PROVENANCE.json")
                )
        elif spec_lock is not None:
            provenance_findings.append(
                _finding("SPEC_LOCK_INVALID", "spec_lock must be an object")
            )
        frozen_ir = _read_json(
            candidate / "canonical_sources/FROZEN_REQUIREMENT_IR.json",
            provenance_findings,
        )
        internal_report = _read_json(
            candidate / "validation/START_PACKAGE_VALIDATION_REPORT.json",
            provenance_findings,
        )
        handoff_text = (
            (candidate / "AUTHORING_HANDOFF.md").read_text(encoding="utf-8")
            if (candidate / "AUTHORING_HANDOFF.md").is_file()
            else ""
        )
        if (
            not isinstance(frozen_ir, dict)
            or _json_hash(frozen_ir) != requirement_hash
            or provenance.get("program_id") != frozen_ir.get("program_id")
            or not isinstance(internal_report, dict)
            or internal_report.get("requirement_ir_sha256") != requirement_hash
            or requirement_hash not in handoff_text
        ):
            provenance_findings.append(
                _finding("REQUIREMENT_IR_PROVENANCE_MISMATCH", "frozen IR/provenance/report/handoff")
            )
    checks.append(
        {
            "check_id": "SPEC_LOCK_AND_FACTORY_PROVENANCE",
            "status": "FAIL" if provenance_findings else "PASS",
            "findings": provenance_findings,
        }
    )
    valid = all(item["status"] == "PASS" for item in checks)
    blocking = [finding for item in checks for finding in item.get("findings", [])]
    return {
        "schema_version": "1.0",
        "validator_id": "HARNESS_FOUNDRY_V2_8_TARGET_CANDIDATE_VALIDATOR",
        "candidate_root": str(candidate),
        "logical_target_root": str(logical_root),
        "status": "PASS" if valid else "FAIL",
        "valid": valid,
        "checks": checks,
        "blocking_findings": blocking,
        "permitted_terminal_state": TARGET_CANDIDATE_STATE,
        "writes_performed": False,
        "commands_executed": False,
        "runtime_claims_verified": False,
    }


def _check_inventory(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if not root.is_dir():
        return [_finding("CANDIDATE_ROOT_MISSING", str(root))]
    manifest = _read_json(root / "PACKAGE_MANIFEST.json", findings)
    declared_files = manifest.get("required_entry_files", []) if isinstance(manifest, dict) else []
    declared_dirs = manifest.get("required_directories", []) if isinstance(manifest, dict) else []
    if declared_files != list(TARGET_REQUIRED_ENTRY_FILES):
        findings.append(
            _finding("REQUIRED_FILE_MANIFEST_TAMPERED", "PACKAGE_MANIFEST.json")
        )
    if declared_dirs != list(TARGET_REQUIRED_DIRECTORIES):
        findings.append(
            _finding("REQUIRED_DIRECTORY_MANIFEST_TAMPERED", "PACKAGE_MANIFEST.json")
        )
    for relative in TARGET_REQUIRED_ENTRY_FILES:
        if not (root / relative).is_file():
            findings.append(_finding("REQUIRED_FILE_MISSING", relative))
    for relative in TARGET_REQUIRED_DIRECTORIES:
        if not (root / relative.rstrip("/")).is_dir():
            findings.append(_finding("REQUIRED_DIRECTORY_MISSING", relative))
    for _project_id, directory in PROJECTS:
        base = root / "project_start_packages" / directory
        for name in PROJECT_REQUIRED_FILES:
            if not (base / name).is_file():
                findings.append(_finding("PROJECT_FILE_MISSING", f"{directory}/{name}"))
    template_names = [path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file() and ".template." in path.name]
    for name in template_names:
        findings.append(_finding("TEMPLATE_FILENAME_FORBIDDEN", name))
    return findings


def _check_syntax(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            findings.append(_finding("JSON_INVALID", f"{path.relative_to(root)}: {exc}"))
    for path in sorted(root.rglob("*.jsonl")):
        try:
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.strip():
                    json.loads(line)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            findings.append(_finding("JSONL_INVALID", f"{path.relative_to(root)}:{line_number}: {exc}"))
    for path in sorted(root.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            findings.append(_finding("MARKDOWN_UNREADABLE", f"{path.relative_to(root)}: {exc}"))
            continue
        for match in LINK_RE.finditer(text):
            target = match.group(1).strip().split("#", 1)[0]
            if not target or target.startswith(("http://", "https://", "#", "/")):
                continue
            target = target.split(" ", 1)[0].strip("<>")
            if target and not (path.parent / target).resolve().exists():
                findings.append(_finding("MARKDOWN_LINK_MISSING", f"{path.relative_to(root)} -> {target}"))
    return findings


def _check_placeholders(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    forbidden_literals = (
        "/absolute/path/to/",
        "TBD",
        "TODO",
        "PLACEHOLDER",
        "PLANNED-REF-",
    )
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in {".md", ".json", ".jsonl"}:
            continue
        text = path.read_text(encoding="utf-8")
        if PLACEHOLDER_RE.search(text):
            findings.append(_finding("UNRESOLVED_TEMPLATE_PLACEHOLDER", path.relative_to(root).as_posix()))
        for literal in forbidden_literals:
            if literal in text:
                findings.append(_finding("FORBIDDEN_TEMPLATE_LITERAL", f"{path.relative_to(root)}: {literal}"))
    return findings


def _check_identity_and_refs(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    manifest = _read_json(root / "PACKAGE_MANIFEST.json", findings)
    context = _read_json(root / "START_CONTEXT.json", findings)
    roles = _read_json(root / "PACKAGE_ROLES.json", findings)
    if not all(isinstance(item, dict) for item in (manifest, context, roles)):
        return findings
    if manifest.get("package_id") != context.get("package_id"):
        findings.append(_finding("PACKAGE_ID_MISMATCH", "manifest and START_CONTEXT differ"))
    if manifest.get("target_id") != context.get("target_id") or roles.get("target_id") != context.get("target_id"):
        findings.append(_finding("TARGET_ID_MISMATCH", "manifest/context/roles differ"))
    for key, relative in context.items():
        if not key.endswith("_ref") or relative is None or not isinstance(relative, str):
            continue
        if key in {"execution_authorization_ref", "real_target_install_authorization_ref"}:
            continue
        if not (root / relative).exists():
            findings.append(_finding("START_CONTEXT_REF_MISSING", f"{key}: {relative}"))
    charter_lock = _read_json(root / "CHARTER_LOCK.json", findings)
    profile_lock = _read_json(root / "PROFILE_LOCK.json", findings)
    if isinstance(charter_lock, dict):
        hash_refs = {
            "charter_sha256": root / "PROGRAM_CHARTER.md",
            "source_manifest_sha256": root / "canonical_sources/SOURCE_MANIFEST.json",
            "normative_atom_catalog_sha256": root / "canonical_sources/NORMATIVE_ATOM_CATALOG.json",
        }
        for key, path in hash_refs.items():
            actual = _file_hash(path) if path.is_file() else None
            if charter_lock.get(key) != actual:
                findings.append(_finding("CONTENT_HASH_MISMATCH", key))
        if charter_lock.get("status") != "PENDING_HUMAN_APPROVAL" or charter_lock.get("approved_by") is not None:
            findings.append(_finding("CHARTER_SELF_APPROVAL_FORBIDDEN", "CHARTER_LOCK.json"))
        if isinstance(profile_lock, dict) and charter_lock.get("profile_lock_sha256") != _json_hash(profile_lock):
            findings.append(_finding("PROFILE_LOCK_HASH_MISMATCH", "profile_lock_sha256"))
    if isinstance(profile_lock, dict):
        if (
            profile_lock.get("selected_profile") != context.get("selected_profile")
            or profile_lock.get("status") != "PENDING_HUMAN_APPROVAL"
            or profile_lock.get("approved_by") is not None
            or profile_lock.get("approved_at") is not None
        ):
            findings.append(_finding("PROFILE_LOCK_BOUNDARY_INVALID", "PROFILE_LOCK.json"))
        profile_text = (root / "TARGET_PROFILE.md").read_text(encoding="utf-8")
        if str(profile_lock.get("selected_profile")) not in profile_text:
            findings.append(_finding("PROFILE_DOCUMENT_LOCK_MISMATCH", "TARGET_PROFILE.md"))
    return findings


def _check_artifact_hashes(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    index = _read_json(root / "WORKPACK_INDEX.json", findings)
    if not isinstance(index, dict) or len(index.get("workpacks", [])) != 1:
        return findings + [_finding("INITIAL_WORKPACK_CARDINALITY_INVALID", "WORKPACK_INDEX.json")]
    item = index["workpacks"][0]
    if not isinstance(item, dict):
        return findings + [_finding("INITIAL_WORKPACK_INVALID", "WORKPACK_INDEX.json")]
    if (
        item.get("requires") != list(ROOT_MATERIALIZATION_REQUIRES)
        or item.get("requirement_sources")
        != {
            "LAB_TOOL_RELEASE_LOCK_VALID": "ENGINEERING_DAG:LAB_TOOL_RELEASE_LOCKED",
            "LINKAGE_TOOL_RELEASE_LOCK_VALID": "ENGINEERING_DAG:LINKAGE_TOOL_RELEASE_LOCKED",
        }
        or item.get("produces") != list(ROOT_MATERIALIZATION_PRODUCES)
        or item.get("command_ids") != list(ROOT_MATERIALIZATION_COMMAND_IDS)
        or item.get("command_execution_order")
        != list(ROOT_MATERIALIZATION_COMMAND_IDS)
    ):
        findings.append(
            _finding(
                "ROOT_MATERIALIZATION_WORKPACK_INVALID", "WORKPACK_INDEX.json"
            )
        )
    refs = {
        "workpack": item.get("workpack_ref"),
        "capsule": item.get("capsule_ref"),
        "command": item.get("command_manifest_ref"),
        "result": item.get("result_ref"),
    }
    paths: dict[str, Path] = {}
    for label, relative in refs.items():
        if not isinstance(relative, str) or not (root / relative).is_file():
            findings.append(_finding("WORKPACK_REF_MISSING", f"{label}:{relative}"))
        else:
            paths[label] = root / relative
    if set(paths) != set(refs):
        return findings
    capsule = _read_json(paths["capsule"], findings)
    command = _read_json(paths["command"], findings)
    result = _read_json(paths["result"], findings)
    if not all(isinstance(value, dict) for value in (capsule, command, result)):
        return findings
    expected = {
        "workpack_sha256": _file_hash(paths["workpack"]),
        "command_manifest_sha256": _file_hash(paths["command"]),
    }
    for key, value in expected.items():
        if capsule.get(key) != value:
            findings.append(_finding("CAPSULE_CONTENT_HASH_MISMATCH", key))
    if capsule.get("predecessor_lock_refs") != item.get(
        "required_predecessor_lock_refs"
    ) or any(
        not (root / str(reference)).is_file()
        for reference in capsule.get("predecessor_lock_refs", [])
    ):
        findings.append(
            _finding("WORKPACK_PREDECESSOR_LOCK_MISMATCH", "CAPSULE.json")
        )
    if (
        capsule.get("requires") != list(ROOT_MATERIALIZATION_REQUIRES)
        or capsule.get("produces") != list(ROOT_MATERIALIZATION_PRODUCES)
        or capsule.get("command_ids") != list(ROOT_MATERIALIZATION_COMMAND_IDS)
        or result.get("expected_capabilities")
        != list(ROOT_MATERIALIZATION_PRODUCES)
    ):
        findings.append(
            _finding("ROOT_MATERIALIZATION_CAPABILITY_INVALID", "CAPSULE.json")
        )
    if capsule.get("hydration_complete") is not False or capsule.get("capsule_sha256") is not None:
        findings.append(_finding("CAPSULE_PREHYDRATION_HASH_INVALID", "capsule_sha256"))
    allowed_paths = [Path(str(value)).resolve() for value in capsule.get("allowed_write_paths", [])]
    forbidden_paths = [Path(str(value)).resolve() for value in capsule.get("forbidden_write_paths", [])]
    workspace = Path(str(capsule.get("workspace_root_abs", "")))
    if (
        len(allowed_paths) != 1
        or not workspace.is_absolute()
        or allowed_paths[0] != workspace
        or capsule.get("workspace_root_status") != "PLANNED_NOT_CREATED"
        or any(
            allowed == forbidden
            or allowed in forbidden.parents
            or forbidden in allowed.parents
            for allowed in allowed_paths
            for forbidden in forbidden_paths
        )
        or not capsule.get("required_inputs")
        or not capsule.get("required_outputs")
        or not capsule.get("return_path")
    ):
        findings.append(_finding("CAPSULE_PATH_OR_RETURN_CONTRACT_INVALID", "CAPSULE.json"))
    if result.get("capsule_sha256") != _file_hash(paths["capsule"]):
        findings.append(_finding("RESULT_CAPSULE_HASH_MISMATCH", "capsule_sha256"))
    if result.get("command_manifest_sha256") != _file_hash(paths["command"]):
        findings.append(_finding("RESULT_COMMAND_HASH_MISMATCH", "command_manifest_sha256"))
    command_without_manifest_hash = dict(command)
    stored_manifest_hash = command_without_manifest_hash.pop("manifest_sha256", None)
    if stored_manifest_hash != _json_hash(command_without_manifest_hash):
        findings.append(_finding("COMMAND_MANIFEST_HASH_MISMATCH", "manifest_sha256"))
    for command_item in command.get("commands", []):
        if not isinstance(command_item, dict):
            continue
        expected_command_hash = (
            _hash_without_field(command_item, "command_sha256")
            if command_item.get("command_kind")
            == "PLANNED_EXECUTOR_INTERFACE"
            else _json_hash(
                {
                    "argv": command_item.get("argv"),
                    "cwd": command_item.get("cwd_abs"),
                }
            )
        )
        if command_item.get("command_sha256") != expected_command_hash:
            findings.append(
                _finding("COMMAND_CONTENT_HASH_MISMATCH", str(command_item.get("command_id")))
            )
    command_ids = [
        item.get("command_id")
        for item in command.get("commands", [])
        if isinstance(item, dict)
    ]
    if (
        command_ids != list(ROOT_MATERIALIZATION_COMMAND_IDS)
        or command.get("execution_started") is not False
    ):
        findings.append(
            _finding("ROOT_MATERIALIZATION_COMMANDS_INVALID", str(command_ids))
        )
    for top_name, referenced in (
        ("CAPSULE.json", paths["capsule"]),
        ("COMMAND_MANIFEST.json", paths["command"]),
        ("WORKPACK_RESULT.json", paths["result"]),
    ):
        if not (root / top_name).is_file() or _file_hash(root / top_name) != _file_hash(referenced):
            findings.append(_finding("SEMANTIC_ROLE_ALIAS_MISMATCH", top_name))
    return findings


def _check_sources_atoms_coverage(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    sources = _read_json(root / "canonical_sources/SOURCE_MANIFEST.json", findings)
    catalog = _read_json(root / "canonical_sources/NORMATIVE_ATOM_CATALOG.json", findings)
    matrix = _read_json(root / "canonical_sources/ATOM_COVERAGE_MATRIX.json", findings)
    acceptance = _read_json(root / "validation/ACCEPTANCE_CASES.json", findings)
    negative = _read_json(root / "validation/NEGATIVE_CASES.json", findings)
    trace_graph = _read_json(root / "canonical_sources/TRACEABILITY_GRAPH.json", findings)
    frozen_ir = _read_json(
        root / "canonical_sources/FROZEN_REQUIREMENT_IR.json", findings
    )
    if not all(isinstance(item, dict) for item in (sources, catalog, matrix)):
        return findings
    source_items = sources.get("sources", [])
    source_id_list = [item.get("source_id") for item in source_items if isinstance(item, dict)]
    source_ids = set(source_id_list)
    if not source_items:
        findings.append(_finding("CANONICAL_SOURCES_EMPTY", "SOURCE_MANIFEST.json"))
    if sources.get("unresolved_source_conflicts"):
        findings.append(_finding("SOURCE_CONFLICT_UNRESOLVED", str(sources.get("unresolved_source_conflicts"))))
    for conflict in sources.get("source_conflicts", []):
        if (
            not isinstance(conflict, dict)
            or str(conflict.get("status", "OPEN")).upper() not in {"RESOLVED", "CLOSED"}
            or not conflict.get("resolution")
            or not conflict.get("decision_ref")
        ):
            findings.append(_finding("SOURCE_CONFLICT_RESOLUTION_INCOMPLETE", str(conflict)))
    if _duplicates(source_id_list) or None in source_ids:
        findings.append(_finding("SOURCE_ID_NOT_UNIQUE", str(source_id_list)))
    for source in source_items:
        source_hash = str(source.get("sha256", "")) if isinstance(source, dict) else ""
        if (
            not isinstance(source, dict)
            or not SHA256_RE.fullmatch(source_hash)
            or len(set(source_hash)) == 1
        ):
            findings.append(_finding("SOURCE_HASH_INVALID", str(source)))
            continue
        location = source.get("path_or_uri") or source.get("path")
        if (
            not location
            or source.get("authority_level")
            not in {
                "HUMAN_APPROVED",
                "HUMAN_PROVIDED",
                "HUMAN_VIA_CODEX_CHAT",
                "LOCKED_SPECIFICATION",
            }
            or source.get("loaded_completely") is not True
        ):
            findings.append(_finding("SOURCE_BINDING_INCOMPLETE", str(source.get("source_id"))))
        elif isinstance(location, str) and "://" not in location:
            path = Path(location).expanduser().resolve()
            if path.is_file() and _file_hash(path) != source_hash:
                findings.append(_finding("SOURCE_CONTENT_HASH_MISMATCH", str(source.get("source_id"))))
    atoms = catalog.get("atoms", [])
    atom_id_list = [item.get("atom_id") for item in atoms if isinstance(item, dict)]
    atom_ids = set(atom_id_list)
    if not atoms:
        findings.append(_finding("INTENT_ATOMS_EMPTY", "NORMATIVE_ATOM_CATALOG.json"))
    if _duplicates(atom_id_list) or None in atom_ids:
        findings.append(_finding("ATOM_ID_NOT_UNIQUE", str(atom_id_list)))
    semantic_fields = (
        "qualifiers",
        "order_constraints",
        "units",
        "defaults",
        "error_semantics",
        "cancel_retry_timeout",
        "compatibility_constraints",
        "explicit_non_goals",
    )
    for atom in atoms:
        if not isinstance(atom, dict) or atom.get("source_id") not in source_ids:
            findings.append(_finding("ATOM_SOURCE_UNRESOLVED", str(atom.get("atom_id") if isinstance(atom, dict) else atom)))
        elif (
            not atom.get("source_locator")
            or not atom.get("verification_mode")
            or not atom.get("text_or_lossless_paraphrase")
            or not atom.get("modality")
            or any(field not in atom or not isinstance(atom[field], list) for field in semantic_fields)
        ):
            findings.append(_finding("ATOM_TRACEABILITY_INCOMPLETE", str(atom.get("atom_id"))))
    if catalog.get("source_manifest_sha256") != _file_hash(root / "canonical_sources/SOURCE_MANIFEST.json"):
        findings.append(_finding("CATALOG_SOURCE_HASH_MISMATCH", "NORMATIVE_ATOM_CATALOG.json"))
    coverage = matrix.get("coverage", [])
    frozen_edges = {
        str(item.get("atom_id")): item
        for item in (frozen_ir or {}).get("coverage_edges", [])
        if isinstance(item, dict) and item.get("atom_id")
    }
    project_workpack_items: dict[str, dict[str, Any]] = {}
    for _project_id, directory in PROJECTS:
        project_index = _read_json(
            root / "project_start_packages" / directory / "WORKPACK_INDEX.json",
            findings,
        )
        if isinstance(project_index, dict):
            for workpack in project_index.get("workpacks", []):
                if isinstance(workpack, dict) and workpack.get("workpack_id"):
                    project_workpack_items[str(workpack["workpack_id"])] = workpack
    valid_workpacks = set(project_workpack_items)
    valid_release_steps = set(RELEASE_STEP_ORDER)
    coverage_ids = [item.get("atom_id") for item in coverage if isinstance(item, dict)]
    covered = set(coverage_ids)
    if _duplicates(coverage_ids):
        findings.append(_finding("COVERAGE_ATOM_ID_NOT_UNIQUE", str(coverage_ids)))
    if covered != atom_ids or matrix.get("missing_required_atoms"):
        findings.append(_finding("INTENT_ATOM_COVERAGE_INCOMPLETE", f"atoms={sorted(atom_ids)}, covered={sorted(covered)}"))
    if set(frozen_edges) != atom_ids:
        findings.append(
            _finding(
                "FROZEN_IR_COVERAGE_INCOMPLETE",
                f"atoms={sorted(atom_ids)}, edges={sorted(frozen_edges)}",
            )
        )
    if matrix.get("source_manifest_sha256") != _file_hash(root / "canonical_sources/SOURCE_MANIFEST.json"):
        findings.append(_finding("MATRIX_SOURCE_HASH_MISMATCH", "ATOM_COVERAGE_MATRIX.json"))
    if matrix.get("normative_atom_catalog_sha256") != _file_hash(root / "canonical_sources/NORMATIVE_ATOM_CATALOG.json"):
        findings.append(_finding("MATRIX_ATOM_HASH_MISMATCH", "ATOM_COVERAGE_MATRIX.json"))
    for item in coverage:
        if not isinstance(item, dict):
            continue
        for field in ("outcome_ids", "workpack_ids", "stage_ids", "release_step_ids", "owner_project_ids", "routing_basis", "scenario_ids", "assertion_ids", "required_evidence_types"):
            if field == "release_step_ids":
                if field not in item or not isinstance(item[field], list):
                    findings.append(_finding("COVERAGE_EDGE_EMPTY", f"{item.get('atom_id')}:{field}"))
                continue
            if not item.get(field):
                findings.append(_finding("COVERAGE_EDGE_EMPTY", f"{item.get('atom_id')}:{field}"))
        if item.get("reverse_mapping_required") is not True:
            findings.append(_finding("REVERSE_COVERAGE_NOT_REQUIRED", str(item.get("atom_id"))))
        atom_id = str(item.get("atom_id"))
        atom = next(
            (value for value in atoms if isinstance(value, dict) and value.get("atom_id") == atom_id),
            {},
        )
        valid_cases = {
            value.get("case_id"): value
            for document in (acceptance, negative)
            if isinstance(document, dict)
            for value in document.get("cases", [])
            if isinstance(value, dict)
        }
        semantic_edges_valid = (
            item.get("outcome_ids") == [f"PO-{atom_id}"]
            and item.get("assertion_ids") == [f"ASSERT-{atom_id}"]
            and set(item.get("workpack_ids", [])).issubset(valid_workpacks)
            and set(item.get("stage_ids", [])).issubset(set(PHASE_ORDER))
            and set(item.get("release_step_ids", [])).issubset(
                valid_release_steps
            )
            and set(item.get("owner_project_ids", []))
            == {
                WORKPACK_PROJECTS[workpack_id]
                for workpack_id in item.get("workpack_ids", [])
                if workpack_id in WORKPACK_PROJECTS
            }
            and frozen_edges.get(atom_id)
            and item.get("workpack_ids")
            == frozen_edges[atom_id].get("workpack_ids")
            and item.get("stage_ids") == frozen_edges[atom_id].get("stage_ids")
            and item.get("release_step_ids")
            == frozen_edges[atom_id].get("release_step_ids")
            and item.get("owner_project_ids")
            == frozen_edges[atom_id].get("owner_project_ids")
            and item.get("routing_basis")
            == frozen_edges[atom_id].get("routing_basis")
            and all(
                workpack_id not in WORKPACK_STAGE_COMPATIBILITY
                or bool(
                    set(item.get("stage_ids", []))
                    & set(WORKPACK_STAGE_COMPATIBILITY[workpack_id])
                )
                for workpack_id in item.get("workpack_ids", [])
            )
            and all(
                scenario in valid_cases
                and atom_id in valid_cases[scenario].get("atom_ids", [])
                for scenario in item.get("scenario_ids", [])
            )
            and atom.get("verification_mode") in item.get("required_evidence_types", [])
        )
        if not semantic_edges_valid:
            findings.append(_finding("COVERAGE_REFERENCE_UNRESOLVED", atom_id))
    case_atom_coverage: dict[str, set[str]] = {"acceptance": set(), "negative": set()}
    for label, document in (("acceptance", acceptance), ("negative", negative)):
        if not isinstance(document, dict):
            continue
        case_ids: list[Any] = []
        for case in document.get("cases", []):
            if not isinstance(case, dict):
                findings.append(_finding("CASE_INVALID", label))
                continue
            case_ids.append(case.get("case_id"))
            refs = case.get("atom_ids")
            if (
                not case.get("case_id")
                or not isinstance(refs, list)
                or not refs
                or not set(refs).issubset(atom_ids)
                or not case.get("description")
            ):
                findings.append(_finding("CASE_TRACEABILITY_INCOMPLETE", str(case.get("case_id"))))
            else:
                case_atom_coverage[label].update(refs)
        if _duplicates(case_ids):
            findings.append(_finding("CASE_ID_NOT_UNIQUE", label))
    for label, covered_atoms in case_atom_coverage.items():
        if covered_atoms != atom_ids:
            findings.append(_finding("CASE_ATOM_COVERAGE_INCOMPLETE", f"{label}:{sorted(covered_atoms)}"))
    if isinstance(trace_graph, dict):
        expected_reverse = {
            f"PO-{atom_id}": atom_id for atom_id in atom_ids
        } | {f"ASSERT-{atom_id}": atom_id for atom_id in atom_ids}
        expected_workpack_ids = list(
            dict.fromkeys(
                workpack_id
                for item in coverage
                if isinstance(item, dict)
                for workpack_id in item.get("workpack_ids", [])
            )
        )
        expected_stage_ids = list(
            dict.fromkeys(
                stage_id
                for item in coverage
                if isinstance(item, dict)
                for stage_id in item.get("stage_ids", [])
            )
        )
        expected_release_step_ids = list(
            dict.fromkeys(
                step_id
                for item in coverage
                if isinstance(item, dict)
                for step_id in item.get("release_step_ids", [])
            )
        )
        expected_workpack_reverse = {
            workpack_id: [
                item["atom_id"]
                for item in coverage
                if isinstance(item, dict)
                and workpack_id in item.get("workpack_ids", [])
            ]
            for workpack_id in expected_workpack_ids
        }
        expected_stage_reverse = {
            stage_id: [
                item["atom_id"]
                for item in coverage
                if isinstance(item, dict)
                and stage_id in item.get("stage_ids", [])
            ]
            for stage_id in expected_stage_ids
        }
        expected_release_reverse = {
            step_id: [
                item["atom_id"]
                for item in coverage
                if isinstance(item, dict)
                and step_id in item.get("release_step_ids", [])
            ]
            for step_id in expected_release_step_ids
        }
        if (
            set(trace_graph.get("atoms", [])) != atom_ids
            or trace_graph.get("forward_edges") != coverage
            or trace_graph.get("reverse_index") != expected_reverse
            or trace_graph.get("workpacks")
            != [
                {
                    "workpack_id": workpack_id,
                    "project_id": WORKPACK_PROJECTS[workpack_id],
                    "role": "PROJECT_REQUIREMENT_IMPLEMENTATION_OR_VERIFICATION",
                }
                for workpack_id in expected_workpack_ids
            ]
            or trace_graph.get("stages") != expected_stage_ids
            or trace_graph.get("release_steps") != expected_release_step_ids
            or trace_graph.get("reverse_workpack_index")
            != expected_workpack_reverse
            or trace_graph.get("reverse_stage_index") != expected_stage_reverse
            or trace_graph.get("reverse_release_step_index")
            != expected_release_reverse
            or len(trace_graph.get("outcomes", [])) != len(atom_ids)
            or len(trace_graph.get("assertions", [])) != len(atom_ids)
            or len(trace_graph.get("evidence_requirements", [])) != len(atom_ids)
        ):
            findings.append(_finding("TRACEABILITY_GRAPH_INCOMPLETE", "TRACEABILITY_GRAPH.json"))
    return findings


def _check_phase_and_release(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    phase = _read_json(root / "PHASE_DEPENDENCY_MANIFEST.json", findings)
    release = _read_json(root / "RELEASE_PIPELINE_MANIFEST.json", findings)
    engineering = _read_json(root / "ENGINEERING_PROJECT_DAG.json", findings)
    root_index = _read_json(root / "WORKPACK_INDEX.json", findings)
    main_index = _read_json(root / "project_start_packages/main_build/WORKPACK_INDEX.json", findings)
    if isinstance(phase, dict):
        order = phase.get("phase_order", [])
        if order != list(PHASE_ORDER):
            findings.append(_finding("P3_PHASE_ORDER_INVALID", str(order)))
        transitions = phase.get("transitions", [])
        transition_ids = [item.get("transition_id") for item in transitions if isinstance(item, dict)]
        required_transition_ids = (
            "T-G0-LOCAL",
            "T-C0",
            "T-G0-CONTROL-LOCK",
            "T-P1",
            "T-C1",
            "T-P1-LOCK",
            "T-P2",
            "T-C2",
            "T-P2-LOCK",
            "T-P3",
            "T-C3",
            "T-P3-LOCK",
            "T-P4",
            "T-P4-BUILD-INPUT",
            "T-C4",
            "T-CERTIFIED",
        )
        if tuple(transition_ids) != required_transition_ids:
            findings.append(_finding("PHASE_TRANSITION_SET_INVALID", str(transition_ids)))
        p4 = next((item for item in transitions if isinstance(item, dict) and item.get("transition_id") == "T-P4"), None)
        requires = p4.get("requires", []) if p4 else []
        if (
            not p4
            or p4.get("from") != "P3_LOCK_READY"
            or p4.get("to") != "P4_READY"
            or set(requires)
            != {"P3_BUILD_LOCK_OR_APPROVED_NA_LOCK_VALID", "C3_CHECKPOINT_PASS"}
        ):
            findings.append(_finding("P4_REQUIRES_P3_AND_C3", str(requires)))
        evidence = phase.get("transition_evidence", {})
        if not all(
            evidence.get(key) is True
            for key in (
                "append_only",
                "predecessor_hash_chain_required",
                "validated_result_required",
                "promotion_event_required",
                "human_decision_required_for_not_applicable",
            )
        ):
            findings.append(_finding("PHASE_EVIDENCE_CONTRACT_INCOMPLETE", str(evidence)))
    if isinstance(release, dict):
        steps = release.get("steps", [])
        ids = [item.get("step_id") for item in steps if isinstance(item, dict)]
        orders = [item.get("order") for item in steps if isinstance(item, dict)]
        if ids != list(RELEASE_STEP_ORDER) or orders != list(range(1, len(RELEASE_STEP_ORDER) + 1)):
            findings.append(_finding("RELEASE_PIPELINE_ORDER_INVALID", str(ids)))
        if (
            release.get("fixed_step_order") != list(RELEASE_STEP_ORDER)
            or release.get("single_active_step") is not True
            or release.get("implicit_edges_forbidden") is not True
            or release.get("terminal_state") != "REAL_TARGET_ACTIVE"
        ):
            findings.append(
                _finding("RELEASE_PIPELINE_CONTROL_FIELDS_INVALID", "RELEASE_PIPELINE_MANIFEST.json")
            )
        produced: set[str] = {
            "P4_LOCAL_GATE_PASS",
            "P3_BUILD_LOCK_OR_APPROVED_NA_LOCK_VALID",
            "C3_CHECKPOINT_PASS",
        }
        previous_step_id: str | None = None
        previous_outputs: list[str] = []
        logical_root = Path(
            str((_read_json(root / "START_CONTEXT.json", findings) or {}).get("target_root", root))
        ).resolve()
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                findings.append(_finding("RELEASE_STEP_INVALID", str(step)))
                continue
            requires = step.get("requires")
            outputs = step.get("produces")
            expected_requires = (
                [
                    "P4_LOCAL_GATE_PASS",
                    "P3_BUILD_LOCK_OR_APPROVED_NA_LOCK_VALID",
                    "C3_CHECKPOINT_PASS",
                ]
                if index == 0
                else previous_outputs
            )
            if step.get("step_id") == "REAL_TARGET_INSTALL":
                expected_requires = [
                    "P4_CERTIFIED_RELEASE_LOCK_VALID",
                    "REAL_TARGET_INSTALL_AUTHORIZATION_GRANTED",
                ]
            next_step = ids[index + 1] if index + 1 < len(ids) else None
            path_values = [
                *step.get("allowed_read_paths", []),
                *step.get("allowed_write_paths", []),
                *step.get("success_output_refs", []),
            ]
            if (
                not isinstance(requires, list)
                or not requires
                or set(requires) != set(expected_requires)
                or not set(requires).issubset(produced)
                or not isinstance(outputs, list)
                or len(outputs) != 1
                or not step.get("authorization_class")
                or not step.get("owner")
                or not step.get("mode")
                or step.get("pipeline_action_id") != step.get("step_id")
                or "project_workpack_id" not in step
                or step.get("project_workpack_id")
                != RELEASE_WORKPACK_BINDINGS.get(str(step.get("step_id")))
                or step.get("required_predecessor_step_ids")
                != ([previous_step_id] if previous_step_id else [])
                or step.get("allowed_next_step_ids")
                != ([next_step] if next_step else [])
                or set(step.get("required_lock_refs", []))
                != {"CHARTER_LOCK.json", "PROFILE_LOCK.json"}
                or step.get("required_input_hashes")
                != {
                    "charter_hash": release.get("charter_hash"),
                    "profile_lock_hash": release.get("profile_lock_hash"),
                }
                or step.get("required_tool_distribution_hashes")
                != {
                    "lab_distribution_hash": None,
                    "linkage_distribution_hash": None,
                    "status": "PLANNED_NOT_AVAILABLE_UNTIL_TOOL_RELEASE",
                }
                or not step.get("environment_id")
                or not step.get("failure_return_step_id")
                or len(step.get("invalidates_on", [])) < 4
                or any(
                    not Path(str(value)).is_absolute()
                    or not Path(str(value)).is_relative_to(logical_root)
                    for value in path_values
                )
            ):
                findings.append(_finding("RELEASE_STEP_DEPENDENCY_INVALID", str(step.get("step_id"))))
            if isinstance(outputs, list):
                produced.update(str(item) for item in outputs)
                previous_outputs = list(outputs)
            previous_step_id = str(step.get("step_id"))
        real = next((item for item in steps if isinstance(item, dict) and item.get("step_id") == "REAL_TARGET_INSTALL"), None)
        wait_real = next((item for item in steps if isinstance(item, dict) and item.get("step_id") == "WAIT_REAL_TARGET_INSTALL_AUTHORIZATION"), None)
        if (
            not real
            or real.get("auto_advance_eligible") is not False
            or set(real.get("requires", []))
            != {"P4_CERTIFIED_RELEASE_LOCK_VALID", "REAL_TARGET_INSTALL_AUTHORIZATION_GRANTED"}
            or not wait_real
            or wait_real.get("auto_advance_eligible") is not False
        ):
            findings.append(_finding("REAL_TARGET_INSTALL_AUTO_FORBIDDEN", "release pipeline"))
        active = next(
            (
                item
                for item in steps
                if isinstance(item, dict)
                and item.get("step_id") == "ACTIVE_INSTANCE_MANIFEST"
            ),
            None,
        )
        if not active or active.get("produces") != ["REAL_TARGET_ACTIVE"]:
            findings.append(
                _finding("ACTIVE_INSTANCE_TERMINAL_MISSING", "release pipeline")
            )
    if isinstance(main_index, dict):
        root_workpack = (
            root_index.get("workpacks", [{}])[0]
            if isinstance(root_index, dict) and root_index.get("workpacks")
            else {}
        )
        materialization = next(
            (
                item
                for item in (engineering or {}).get("nodes", [])
                if isinstance(item, dict)
                and item.get("node_id") == "MAIN_EXECUTION_PACKAGE_MATERIALIZED"
            ),
            None,
        )
        if (
            not isinstance(root_workpack, dict)
            or not materialization
            or materialization.get("workpack_id")
            != root_workpack.get("workpack_id")
            or materialization.get("project_workpack_index_ref")
            != "WORKPACK_INDEX.json"
            or root_workpack.get("workpack_id")
            in {
                item.get("workpack_id")
                for item in main_index.get("workpacks", [])
                if isinstance(item, dict)
            }
        ):
            findings.append(
                _finding(
                    "ROOT_MATERIALIZATION_DAG_BINDING_INVALID",
                    "root Workpack must bind only MAIN_EXECUTION_PACKAGE_MATERIALIZED",
                )
            )
        p4 = next((item for item in main_index.get("workpacks", []) if isinstance(item, dict) and item.get("phase") == "P4"), None)
        if not p4 or not any("P3" in str(item) for item in p4.get("requires", [])):
            findings.append(_finding("MAIN_P4_P3_REQUIREMENT_MISSING", "main workpack index"))
    return findings


def _check_three_projects(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    context = _read_json(root / "START_CONTEXT.json", findings)
    logical_root = Path(str(context.get("target_root", root))).resolve() if isinstance(context, dict) else root
    manifest = _read_json(root / "THREE_PROJECT_PROGRAM_MANIFEST.json", findings)
    dag = _read_json(root / "ENGINEERING_PROJECT_DAG.json", findings)
    release = _read_json(root / "RELEASE_PIPELINE_MANIFEST.json", findings)
    root_workpack_index = _read_json(root / "WORKPACK_INDEX.json", findings)
    root_workpack_id = (
        str(root_workpack_index.get("workpacks", [{}])[0].get("workpack_id"))
        if isinstance(root_workpack_index, dict)
        and root_workpack_index.get("workpacks")
        else None
    )
    expected_ids = [project_id for project_id, _directory in PROJECTS]
    project_directories = dict(PROJECTS)
    expected_dag_by_workpack = {
        workpack_id: node_id
        for node_id, workpack_id in DAG_WORKPACK_BINDINGS.items()
    }
    for node_id, sequence in DAG_WORKPACK_SEQUENCE_BINDINGS.items():
        expected_dag_by_workpack.update(
            {workpack_id: node_id for workpack_id in sequence}
        )
    expected_release_by_workpack = {
        workpack_id: step_id
        for step_id, workpack_id in RELEASE_WORKPACK_BINDINGS.items()
    }
    project_workpack_ids: list[str] = []
    workpack_owner: dict[str, str] = {}
    project_indexes: dict[str, dict[str, Any]] = {}
    for project_id, directory in PROJECTS:
        index = _read_json(
            root / "project_start_packages" / directory / "WORKPACK_INDEX.json",
            findings,
        )
        if not isinstance(index, dict):
            continue
        project_indexes[project_id] = index
        workpacks = index.get("workpacks", [])
        local_ids = [
            str(item.get("workpack_id"))
            for item in workpacks
            if isinstance(item, dict) and item.get("workpack_id")
        ]
        if (
            index.get("project_id") != project_id
            or index.get("single_active_workpack") is not True
            or index.get("auto_start_next_workpack") is not False
            or len(local_ids) != len(workpacks)
            or _duplicates(local_ids)
        ):
            findings.append(
                _finding("PROJECT_WORKPACK_INDEX_INVALID", directory)
            )
        for position, item in enumerate(workpacks, 1):
            if not isinstance(item, dict) or not item.get("workpack_id"):
                continue
            workpack_id = str(item["workpack_id"])
            project_workpack_ids.append(workpack_id)
            if workpack_id in workpack_owner:
                findings.append(
                    _finding("PROJECT_WORKPACK_ID_NOT_UNIQUE", workpack_id)
                )
            workpack_owner[workpack_id] = project_id
            expected_dag_node = expected_dag_by_workpack.get(workpack_id)
            expected_release_step = expected_release_by_workpack.get(workpack_id)
            expected_surface = (
                "ENGINEERING_PROJECT_DAG"
                if expected_dag_node
                else "RELEASE_PIPELINE"
                if expected_release_step
                else "UNBOUND"
            )
            expected_control_id = expected_dag_node or expected_release_step
            if (
                item.get("status") != "PLANNED_NOT_ACTIVE"
                or item.get("topological_order") != position
                or item.get("program_control_surface") != expected_surface
                or item.get("program_control_node_id") != expected_control_id
                or item.get("program_control_binding_status")
                != ("PLANNED_BOUND" if expected_control_id else "INVALID_UNBOUND")
            ):
                findings.append(
                    _finding(
                        "PROJECT_WORKPACK_BACK_REFERENCE_INVALID",
                        f"{directory}:{workpack_id}",
                    )
                )
    if isinstance(manifest, dict):
        projects = manifest.get("projects", [])
        ids = [item.get("project_id") for item in projects if isinstance(item, dict)]
        orders = [item.get("construction_order") for item in projects if isinstance(item, dict)]
        if ids != expected_ids or orders != [1, 2, 3]:
            findings.append(_finding("THREE_PROJECT_ORDER_INVALID", str(ids)))
        for item in projects:
            if not isinstance(item, dict):
                continue
            if item.get("status") != "PLANNED_NOT_STARTED":
                findings.append(_finding("PROJECT_NOT_PLANNED_STOPPED", str(item.get("project_id"))))
            root_abs = Path(str(item.get("root_abs", "")))
            if not root_abs.is_absolute() or not root_abs.is_relative_to(logical_root):
                findings.append(_finding("PROJECT_ROOT_INVALID", str(root_abs)))
    if isinstance(dag, dict):
        nodes = [item.get("node_id") for item in dag.get("nodes", []) if isinstance(item, dict)]
        if nodes != list(ENGINEERING_NODE_ORDER):
            findings.append(_finding("ENGINEERING_DAG_NODE_SET_INVALID", str(nodes)))
        expected_edges = [
            {"from": source, "to": target}
            for source, target in zip(ENGINEERING_NODE_ORDER, ENGINEERING_NODE_ORDER[1:])
        ]
        if dag.get("edges") != expected_edges:
            findings.append(_finding("ENGINEERING_DAG_EDGES_INVALID", str(dag.get("edges"))))
        node_by_id = {
            item.get("node_id"): item
            for item in dag.get("nodes", [])
            if isinstance(item, dict)
        }
        for predecessor, successor in zip(ENGINEERING_NODE_ORDER, ENGINEERING_NODE_ORDER[1:]):
            if predecessor not in node_by_id.get(successor, {}).get("requires", []):
                findings.append(
                    _finding("ENGINEERING_DAG_PREDECESSOR_MISSING", successor)
                )
        for index, node_id in enumerate(ENGINEERING_NODE_ORDER):
            node = node_by_id.get(node_id, {})
            predecessor = ENGINEERING_NODE_ORDER[index - 1] if index else None
            successor = (
                ENGINEERING_NODE_ORDER[index + 1]
                if index + 1 < len(ENGINEERING_NODE_ORDER)
                else None
            )
            expected_workpack_id = (
                root_workpack_id
                if node_id == "MAIN_EXECUTION_PACKAGE_MATERIALIZED"
                else DAG_WORKPACK_BINDINGS.get(node_id)
            )
            expected_sequence = list(
                DAG_WORKPACK_SEQUENCE_BINDINGS.get(node_id, ())
            )
            expected_pipeline_action = (
                None if expected_workpack_id else node_id
            )
            expected_project_directory = project_directories.get(
                str(node.get("project_id"))
            )
            expected_index_ref = (
                "WORKPACK_INDEX.json"
                if node_id == "MAIN_EXECUTION_PACKAGE_MATERIALIZED"
                else f"project_start_packages/{expected_project_directory}/WORKPACK_INDEX.json"
                if expected_project_directory
                else None
            )
            expected_action_kind = (
                "CONDITIONAL"
                if node_id == "MAIN_P3_C3_OR_APPROVED_NA"
                else "WORKPACK_SEQUENCE"
                if expected_sequence
                else "WORKPACK"
                if expected_workpack_id
                else "PIPELINE_ACTION"
            )
            expected_bound_workpacks = [
                *([expected_workpack_id] if expected_workpack_id else []),
                *expected_sequence,
            ]
            expected_project_bound_workpacks = [
                value
                for value in expected_bound_workpacks
                if value in PROJECT_WORKPACK_CONTRACTS
            ]
            expected_workpack_requires = list(
                dict.fromkeys(
                    capability
                    for workpack_id in expected_project_bound_workpacks
                    for capability in PROJECT_WORKPACK_CONTRACTS[workpack_id][
                        "requires"
                    ]
                )
            )
            expected_workpack_produces = list(
                dict.fromkeys(
                    capability
                    for workpack_id in expected_project_bound_workpacks
                    for capability in PROJECT_WORKPACK_CONTRACTS[workpack_id][
                        "produces"
                    ]
                )
            )
            if node_id == "MAIN_EXECUTION_PACKAGE_MATERIALIZED":
                expected_workpack_requires = list(ROOT_MATERIALIZATION_REQUIRES)
                expected_workpack_produces = list(ROOT_MATERIALIZATION_PRODUCES)
            expected_sequence_edges = [
                {
                    "from_workpack_id": left,
                    "to_workpack_id": right,
                    "required_capabilities": [
                        capability
                        for capability in PROJECT_WORKPACK_CONTRACTS[left][
                            "produces"
                        ]
                        if capability
                        in PROJECT_WORKPACK_CONTRACTS[right]["requires"]
                    ],
                }
                for left, right in zip(expected_sequence, expected_sequence[1:])
            ]
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
            expected_produces_capabilities = list(
                dict.fromkeys(
                    [
                        f"{node_id}_PASS",
                        *expected_workpack_produces,
                        *special_capabilities.get(node_id, ()),
                    ]
                )
            )
            required_fields = (
                "node_kind",
                "owner_role",
                "required_predecessor_nodes",
                "required_lock_refs",
                "required_input_hashes",
                "required_tool_distribution_hashes",
                "required_execution_mode",
                "required_authorization_scope",
                "workpack_id",
                "project_workpack_sequence",
                "project_workpack_index_ref",
                "pipeline_action_id",
                "action_kind",
                "completion_rule",
                "single_active_workpack",
                "conditional_branches",
                "project_workpack_required_capabilities",
                "project_workpack_produced_capabilities",
                "project_workpack_sequence_edges",
                "produces_capabilities",
                "allowed_read_paths",
                "allowed_write_paths",
                "environment_id",
                "success_gate",
                "success_output_refs",
                "failure_return_node",
                "invalidates_on",
                "allowed_next_nodes",
                "human_gate",
            )
            path_values = [
                *node.get("allowed_read_paths", []),
                *node.get("allowed_write_paths", []),
                *node.get("success_output_refs", []),
            ]
            action_count = sum(
                value is not None
                for value in (node.get("workpack_id"), node.get("pipeline_action_id"))
            )
            if (
                any(field not in node for field in required_fields)
                or node.get("required_predecessor_nodes")
                != ([predecessor] if predecessor else [])
                or node.get("allowed_next_nodes") != ([successor] if successor else [])
                or set(node.get("required_lock_refs", []))
                != {"CHARTER_LOCK.json", "PROFILE_LOCK.json"}
                or node.get("required_input_hashes")
                != {
                    "charter_hash": dag.get("charter_hash"),
                    "profile_lock_hash": dag.get("profile_lock_hash"),
                }
                or node.get("required_tool_distribution_hashes")
                != {
                    "lab_distribution_hash": None,
                    "linkage_distribution_hash": None,
                    "status": "PLANNED_NOT_AVAILABLE_UNTIL_TOOL_RELEASE",
                }
                or action_count != 1
                or not node.get("environment_id")
                or not node.get("success_gate")
                or not node.get("success_output_refs")
                or not node.get("failure_return_node")
                or len(node.get("invalidates_on", [])) < 4
                or any(
                    not Path(str(value)).is_absolute()
                    or not Path(str(value)).is_relative_to(logical_root)
                    for value in path_values
                )
            ):
                findings.append(
                    _finding("ENGINEERING_DAG_NODE_CONTRACT_INCOMPLETE", node_id)
                )
            if (
                node.get("workpack_id") != expected_workpack_id
                or node.get("project_workpack_sequence") != expected_sequence
                or node.get("project_workpack_index_ref") != expected_index_ref
                or node.get("pipeline_action_id") != expected_pipeline_action
                or node.get("action_kind") != expected_action_kind
                or node.get("single_active_workpack") is not True
                or not node.get("completion_rule")
                or node.get("project_workpack_required_capabilities")
                != expected_workpack_requires
                or node.get("project_workpack_produced_capabilities")
                != expected_workpack_produces
                or node.get("project_workpack_sequence_edges")
                != expected_sequence_edges
                or node.get("produces_capabilities")
                != expected_produces_capabilities
                or (
                    expected_index_ref is not None
                    and not (root / expected_index_ref).is_file()
                )
            ):
                findings.append(
                    _finding("ENGINEERING_WORKPACK_BINDING_INVALID", node_id)
                )
            for workpack_id in [
                *([str(node.get("workpack_id"))] if node.get("workpack_id") else []),
                *[
                    str(value)
                    for value in node.get("project_workpack_sequence", [])
                ],
            ]:
                root_materialization_ref = (
                    node_id == "MAIN_EXECUTION_PACKAGE_MATERIALIZED"
                    and workpack_id == root_workpack_id
                    and node.get("project_id") == "MAIN_HARNESS_BUILD"
                )
                if (
                    not root_materialization_ref
                    and workpack_owner.get(workpack_id) != node.get("project_id")
                ):
                    findings.append(
                        _finding(
                            "ENGINEERING_WORKPACK_REF_UNRESOLVED",
                            f"{node_id}:{workpack_id}",
                        )
                    )
            if node_id in {
                "MAIN_EXECUTION_PACKAGE_MATERIALIZED",
                *(
                    value
                    for value in DAG_WORKPACK_BINDINGS
                    if value.startswith("MAIN_")
                ),
            }:
                main_repository = str(
                    logical_root
                    / "project_start_packages/main_build/repository"
                )
                if main_repository not in node.get("allowed_write_paths", []):
                    findings.append(
                        _finding("MAIN_WORKPACK_WRITE_ROOT_MISSING", node_id)
                    )
            if node_id == "MAIN_PROGRAM_REGISTRATION" and (
                node.get("node_kind") != "CONTROL_REGISTRATION_GATE"
                or node.get("owner_role") != "BUILD_PROGRAM_DRIVER"
                or node.get("required_execution_mode") != "REGISTRATION_ONLY"
                or node.get("workpack_id") is not None
                or node.get("project_workpack_sequence") != []
                or node.get("pipeline_action_id") != node_id
                or str(
                    logical_root
                    / "project_start_packages/main_build/repository"
                )
                in node.get("allowed_write_paths", [])
            ):
                findings.append(
                    _finding("MAIN_PROGRAM_REGISTRATION_BOUNDARY_INVALID", node_id)
                )
            if node_id == "MAIN_P3_C3_OR_APPROVED_NA":
                branches = node.get("conditional_branches", {})
                implementation = branches.get("IMPLEMENT", {})
                not_applicable = branches.get("APPROVED_NOT_APPLICABLE", {})
                main_repository = str(
                    logical_root
                    / "project_start_packages/main_build/repository"
                )
                if (
                    implementation.get("workpack_id") != "MB-P3"
                    or main_repository
                    not in implementation.get("allowed_write_paths", [])
                    or not_applicable.get("pipeline_action_id")
                    != "P3_NOT_APPLICABLE_LOCK"
                    or not_applicable.get("human_decision_required") is not True
                    or main_repository
                    in not_applicable.get("allowed_write_paths", [])
                ):
                    findings.append(
                        _finding("P3_CONDITIONAL_BRANCH_INVALID", node_id)
                    )
        first = node_by_id.get(ENGINEERING_NODE_ORDER[0])
        human = node_by_id.get(ENGINEERING_NODE_ORDER[1])
        if not first or first.get("auto_advance_eligible") is not False or not human or human.get("status") != "WAITING_HUMAN_GATE":
            findings.append(_finding("ENGINEERING_DAG_AUTHORING_GATE_INVALID", "candidate to human approval"))
        if (
            dag.get("dag_status") != "PLANNED_NOT_EXECUTABLE"
            or dag.get("single_active_node") is not True
            or dag.get("global_single_active_workpack") is not True
            or dag.get("implicit_edges_forbidden") is not True
            or dag.get("fixed_node_order") != list(ENGINEERING_NODE_ORDER)
        ):
            findings.append(_finding("ENGINEERING_DAG_PRESTART_INVALID", "ENGINEERING_PROJECT_DAG.json"))
    mapped_workpack_ids: list[str] = []
    if isinstance(dag, dict):
        for node in dag.get("nodes", []):
            if not isinstance(node, dict):
                continue
            if (
                node.get("workpack_id")
                and node.get("node_id")
                != "MAIN_EXECUTION_PACKAGE_MATERIALIZED"
            ):
                mapped_workpack_ids.append(str(node["workpack_id"]))
            mapped_workpack_ids.extend(
                str(value)
                for value in node.get("project_workpack_sequence", [])
            )
    if isinstance(release, dict):
        for step in release.get("steps", []):
            if not isinstance(step, dict):
                continue
            step_id = str(step.get("step_id"))
            expected_workpack_id = RELEASE_WORKPACK_BINDINGS.get(step_id)
            expected_project_id = (
                workpack_owner.get(expected_workpack_id)
                if expected_workpack_id
                else None
            )
            expected_directory = project_directories.get(expected_project_id)
            expected_index_ref = (
                f"project_start_packages/{expected_directory}/WORKPACK_INDEX.json"
                if expected_directory
                else None
            )
            expected_command_ref = (
                f"project_start_packages/{expected_directory}/commands/"
                f"{expected_workpack_id}.commands.json"
                if expected_directory and expected_workpack_id
                else None
            )
            expected_contract = (
                PROJECT_WORKPACK_CONTRACTS[expected_workpack_id]
                if expected_workpack_id
                else None
            )
            if (
                step.get("project_workpack_id") != expected_workpack_id
                or step.get("project_workpack_project_id")
                != expected_project_id
                or step.get("project_workpack_index_ref")
                != expected_index_ref
                or step.get("project_workpack_command_manifest_ref")
                != expected_command_ref
                or step.get("project_workpack_required_capabilities")
                != (
                    list(expected_contract["requires"])
                    if expected_contract
                    else []
                )
                or step.get("project_workpack_produced_capabilities")
                != (
                    list(expected_contract["produces"])
                    if expected_contract
                    else []
                )
                or step.get("project_workpack_command_ids")
                != (
                    list(expected_contract["command_ids"])
                    if expected_contract
                    else []
                )
                or (
                    expected_index_ref is not None
                    and not (root / expected_index_ref).is_file()
                )
                or (
                    expected_command_ref is not None
                    and not (root / expected_command_ref).is_file()
                )
            ):
                findings.append(
                    _finding("RELEASE_WORKPACK_BINDING_INVALID", step_id)
                )
            if step.get("project_workpack_id"):
                mapped_workpack_ids.append(str(step["project_workpack_id"]))
    if (
        set(mapped_workpack_ids) != set(project_workpack_ids)
        or len(mapped_workpack_ids) != len(project_workpack_ids)
        or _duplicates(mapped_workpack_ids)
    ):
        findings.append(
            _finding(
                "PROJECT_WORKPACK_COVERAGE_INVALID",
                "expected="
                + str(sorted(project_workpack_ids))
                + ", mapped="
                + str(sorted(mapped_workpack_ids)),
            )
        )
    findings.extend(
        _check_project_workpack_execution_contracts(
            root,
            logical_root=logical_root,
            project_indexes=project_indexes,
            dag=dag if isinstance(dag, dict) else {},
            release=release if isinstance(release, dict) else {},
        )
    )
    role_expectations = {
        "external_lab": "EXTERNAL_CONFORMANCE_LAB",
        "linkage_review": "READ_ONLY_LINKAGE_REVIEW",
        "main_build": "MAIN_BUILD_PROJECT",
    }
    required_project_terms = {
        "external_lab": ("Mission", "Authority", "Certificate", "Stop rule", "不得"),
        "linkage_review": ("Mission", "read-only", "Linkage PASS", "Finding", "Stop rule"),
        "main_build": ("Mission", "P3", "P4", "Certificate", "REAL_TARGET_INSTALL", "Stop rule"),
    }
    for project_id, directory in PROJECTS:
        state = _read_json(root / "project_start_packages" / directory / "PROJECT_STATE.json", findings)
        commands = _read_json(root / "project_start_packages" / directory / "COMMAND_MANIFEST.json", findings)
        project_root = root / "project_start_packages" / directory
        markdown = "\n".join(
            (project_root / name).read_text(encoding="utf-8")
            for name in ("README.md", "PROJECT_CHARTER.md", "BUILD_INSTALL_PLAN.md")
            if (project_root / name).is_file()
        )
        if (
            len(markdown) < 600
            or "PLANNED_NOT_STARTED" not in markdown
            or not all(term.lower() in markdown.lower() for term in required_project_terms[directory])
        ):
            findings.append(_finding("PROJECT_DOCUMENT_CONTRACT_INCOMPLETE", directory))
        if isinstance(state, dict):
            if state.get("project_id") != project_id or state.get("project_role") != role_expectations[directory]:
                findings.append(_finding("PROJECT_ID_OR_ROLE_MISMATCH", directory))
            if state.get("state") != "PLANNED_NOT_STARTED" or state.get("current_workpack_id") is not None or state.get("auto_advance_enabled") is not False:
                findings.append(_finding("PROJECT_STATE_NOT_AUTHORING_SAFE", directory))
        if isinstance(commands, dict):
            if commands.get("default_disposition") != "DECLARE_ONLY":
                findings.append(_finding("PROJECT_COMMANDS_NOT_DECLARE_ONLY", directory))
            for command in commands.get("commands", []):
                executable = Path(str(command.get("executable", ""))) if isinstance(command, dict) else Path("")
                if (
                    not executable.is_absolute()
                    or not executable.is_relative_to(logical_root)
                    or command.get("authorization_ref") is not None
                ):
                    findings.append(_finding("PROJECT_COMMAND_BOUNDARY_INVALID", f"{directory}:{command.get('command_id') if isinstance(command, dict) else command}"))
    return findings


def _check_project_workpack_execution_contracts(
    root: Path,
    *,
    logical_root: Path,
    project_indexes: Mapping[str, Mapping[str, Any]],
    dag: Mapping[str, Any],
    release: Mapping[str, Any],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    coverage_matrix = _read_json(
        root / "canonical_sources/ATOM_COVERAGE_MATRIX.json", findings
    )
    coverage_rows = (
        coverage_matrix.get("coverage", [])
        if isinstance(coverage_matrix, dict)
        else []
    )
    project_directories = dict(PROJECTS)
    workpack_items: dict[str, Mapping[str, Any]] = {}
    workpack_positions: dict[str, tuple[str, int]] = {}
    for project_id, index in project_indexes.items():
        for position, item in enumerate(index.get("workpacks", []), 1):
            if not isinstance(item, dict) or not item.get("workpack_id"):
                continue
            workpack_id = str(item["workpack_id"])
            workpack_items[workpack_id] = item
            workpack_positions[workpack_id] = (project_id, position)

    dag_nodes = {
        str(item.get("node_id")): item
        for item in dag.get("nodes", [])
        if isinstance(item, dict) and item.get("node_id")
    }
    dag_positions = {
        node_id: position
        for position, node_id in enumerate(ENGINEERING_NODE_ORDER)
    }
    release_steps = {
        str(item.get("step_id")): item
        for item in release.get("steps", [])
        if isinstance(item, dict) and item.get("step_id")
    }
    release_positions = {
        step_id: position for position, step_id in enumerate(RELEASE_STEP_ORDER)
    }

    for project_id, directory in PROJECTS:
        project_root = root / "project_start_packages" / directory
        index = project_indexes.get(project_id)
        if not isinstance(index, Mapping):
            continue
        global_manifest_path = project_root / "COMMAND_MANIFEST.json"
        global_manifest = _read_json(global_manifest_path, findings)
        if not isinstance(global_manifest, dict):
            continue
        global_commands = global_manifest.get("commands", [])
        global_command_ids = [
            item.get("command_id")
            for item in global_commands
            if isinstance(item, dict)
        ]
        if (
            not global_commands
            or len(global_command_ids) != len(global_commands)
            or None in global_command_ids
            or _duplicates(global_command_ids)
            or global_manifest.get("manifest_sha256")
            != _hash_without_field(global_manifest, "manifest_sha256")
            or global_manifest.get("execution_started") is not False
        ):
            findings.append(
                _finding("PROJECT_COMMAND_MANIFEST_INVALID", directory)
            )
        commands_by_id: dict[str, Mapping[str, Any]] = {}
        for command in global_commands:
            if not isinstance(command, dict) or not command.get("command_id"):
                continue
            command_id = str(command["command_id"])
            commands_by_id[command_id] = command
            executable = Path(
                str(command.get("executable_abs") or command.get("executable") or "")
            )
            cwd = Path(str(command.get("cwd_absolute") or ""))
            allowed_write_roots = [
                Path(str(value))
                for value in command.get("allowed_write_roots", [])
            ]
            if (
                command.get("command_sha256")
                != _hash_without_field(command, "command_sha256")
                or not executable.is_absolute()
                or not executable.is_relative_to(logical_root)
                or not cwd.is_absolute()
                or not cwd.is_relative_to(logical_root)
                or any(
                    not value.is_absolute()
                    or not value.is_relative_to(logical_root)
                    for value in allowed_write_roots
                )
                or command.get("authorization_ref") is not None
                or command.get("auto_execute") is not False
            ):
                findings.append(
                    _finding(
                        "PROJECT_COMMAND_CONTRACT_INVALID",
                        f"{directory}:{command_id}",
                    )
                )

        for item in index.get("workpacks", []):
            if not isinstance(item, dict) or not item.get("workpack_id"):
                continue
            workpack_id = str(item["workpack_id"])
            contract = PROJECT_WORKPACK_CONTRACTS.get(workpack_id)
            if not contract or contract.get("project_id") != project_id:
                findings.append(
                    _finding(
                        "PROJECT_WORKPACK_EXECUTION_CONTRACT_MISSING",
                        f"{directory}:{workpack_id}",
                    )
                )
                continue
            expected_intent_atom_ids = [
                str(row["atom_id"])
                for row in coverage_rows
                if isinstance(row, dict)
                and workpack_id in row.get("workpack_ids", [])
            ]
            expected_refs = {
                "workpack_ref": f"workpacks/{workpack_id}.md",
                "command_manifest_ref": f"commands/{workpack_id}.commands.json",
                "capsule_ref": f"capsules/{workpack_id}.capsule.json",
                "result_ref": f"results/{workpack_id}.result.json",
                "loop_state_ref": f"loops/{workpack_id}.loop.json",
            }
            if (
                item.get("requires") != list(contract["requires"])
                or item.get("requirement_sources")
                != dict(contract["requirement_sources"])
                or item.get("produces") != list(contract["produces"])
                or item.get("execution_mode") != contract["execution_mode"]
                or item.get("command_ids") != list(contract["command_ids"])
                or item.get("command_execution_order")
                != list(contract["command_ids"])
                or item.get("intent_atom_ids") != expected_intent_atom_ids
                or any(item.get(key) != value for key, value in expected_refs.items())
                or item.get("execution_authorization_ref") is not None
                or item.get("auto_start") is not False
                or item.get("success_rule")
                != "ALL_REQUIRED_COMMANDS_AND_CAPABILITIES_VALID"
                or not item.get("failure_return_node")
            ):
                findings.append(
                    _finding(
                        "PROJECT_WORKPACK_EXECUTION_CONTRACT_INVALID",
                        f"{directory}:{workpack_id}",
                    )
                )
            resolved_paths = {
                key: project_root / value for key, value in expected_refs.items()
            }
            hash_fields = {
                "workpack_sha256": resolved_paths["workpack_ref"],
                "command_manifest_sha256": resolved_paths[
                    "command_manifest_ref"
                ],
                "capsule_sha256": resolved_paths["capsule_ref"],
                "result_sha256": resolved_paths["result_ref"],
                "loop_state_sha256": resolved_paths["loop_state_ref"],
            }
            if any(not path.is_file() for path in resolved_paths.values()) or any(
                not path.is_file() or item.get(field) != _file_hash(path)
                for field, path in hash_fields.items()
            ):
                findings.append(
                    _finding(
                        "PROJECT_WORKPACK_ARTIFACT_HASH_INVALID",
                        f"{directory}:{workpack_id}",
                    )
                )
                continue
            workpack_text = resolved_paths["workpack_ref"].read_text(
                encoding="utf-8"
            )
            per_commands = _read_json(
                resolved_paths["command_manifest_ref"], findings
            )
            capsule = _read_json(resolved_paths["capsule_ref"], findings)
            result = _read_json(resolved_paths["result_ref"], findings)
            loop = _read_json(resolved_paths["loop_state_ref"], findings)
            if not all(
                isinstance(value, dict)
                for value in (per_commands, capsule, result, loop)
            ):
                continue
            expected_commands = [
                commands_by_id.get(command_id)
                for command_id in contract["command_ids"]
            ]
            if (
                any(command is None for command in expected_commands)
                or per_commands.get("program_id") != index.get("program_id")
                or per_commands.get("project_id") != project_id
                or per_commands.get("workpack_id") != workpack_id
                or per_commands.get("status") != "DECLARE_ONLY"
                or per_commands.get("execution_started") is not False
                or per_commands.get("command_ids")
                != list(contract["command_ids"])
                or per_commands.get("intent_atom_ids")
                != expected_intent_atom_ids
                or per_commands.get("commands") != expected_commands
                or per_commands.get("source_project_command_manifest_sha256")
                != _file_hash(global_manifest_path)
                or per_commands.get("manifest_sha256")
                != _hash_without_field(per_commands, "manifest_sha256")
            ):
                findings.append(
                    _finding(
                        "PROJECT_WORKPACK_COMMAND_BINDING_INVALID",
                        f"{directory}:{workpack_id}",
                    )
                )
            allowed_read_paths = [
                Path(str(value)) for value in item.get("allowed_read_paths", [])
            ]
            allowed_write_paths = [
                Path(str(value)) for value in item.get("allowed_write_paths", [])
            ]
            if (
                not allowed_read_paths
                or not allowed_write_paths
                or any(
                    not path.is_absolute() or not path.is_relative_to(logical_root)
                    for path in [*allowed_read_paths, *allowed_write_paths]
                )
                or capsule.get("status") != "PLANNED_NOT_HYDRATED"
                or capsule.get("hydration_complete") is not False
                or capsule.get("execution_authorization_ref") is not None
                or capsule.get("requires") != list(contract["requires"])
                or capsule.get("requirement_sources")
                != dict(contract["requirement_sources"])
                or capsule.get("produces") != list(contract["produces"])
                or capsule.get("command_ids") != list(contract["command_ids"])
                or capsule.get("intent_atom_ids") != expected_intent_atom_ids
                or capsule.get("command_manifest_sha256")
                != _file_hash(resolved_paths["command_manifest_ref"])
                or capsule.get("allowed_read_paths")
                != item.get("allowed_read_paths")
                or capsule.get("allowed_write_paths")
                != item.get("allowed_write_paths")
            ):
                findings.append(
                    _finding(
                        "PROJECT_WORKPACK_CAPSULE_INVALID",
                        f"{directory}:{workpack_id}",
                    )
                )
            if (
                result.get("status") != "NOT_RUN"
                or result.get("required_capabilities")
                != list(contract["requires"])
                or result.get("expected_capabilities")
                != list(contract["produces"])
                or result.get("intent_atom_ids") != expected_intent_atom_ids
                or result.get("command_manifest_sha256")
                != _file_hash(resolved_paths["command_manifest_ref"])
                or result.get("capsule_sha256")
                != _file_hash(resolved_paths["capsule_ref"])
                or result.get("command_receipts") != []
                or result.get("evidence_refs") != []
                or result.get("promotion_eligible") is not False
            ):
                findings.append(
                    _finding(
                        "PROJECT_WORKPACK_RESULT_INVALID",
                        f"{directory}:{workpack_id}",
                    )
                )
            if (
                loop.get("status") != "NOT_STARTED"
                or loop.get("current_iteration") != 0
                or not isinstance(loop.get("max_iterations"), int)
                or loop.get("max_iterations") <= 0
                or loop.get("authorization_ref") is not None
                or loop.get("promotion_eligible") is not False
            ):
                findings.append(
                    _finding(
                        "PROJECT_WORKPACK_LOOP_INVALID",
                        f"{directory}:{workpack_id}",
                    )
                )
            if (
                f"# Project Workpack: {workpack_id}" not in workpack_text
                or "PLANNED_NOT_ACTIVE" not in workpack_text
                or "Non-claims" not in workpack_text
                or any(atom_id not in workpack_text for atom_id in expected_intent_atom_ids)
            ):
                findings.append(
                    _finding(
                        "PROJECT_WORKPACK_DOCUMENT_INVALID",
                        f"{directory}:{workpack_id}",
                    )
                )

            target_surface = str(item.get("program_control_surface"))
            target_control_id = str(item.get("program_control_node_id"))
            target_project_id, target_position = workpack_positions.get(
                workpack_id, ("", -1)
            )
            for capability, source_ref in contract["requirement_sources"].items():
                source_kind, separator, source_id = str(source_ref).partition(":")
                source_valid = bool(separator and source_id)
                if source_kind == "PROJECT_WORKPACK":
                    source_item = workpack_items.get(source_id)
                    source_project_id, source_position = workpack_positions.get(
                        source_id, ("", -1)
                    )
                    source_valid = source_valid and bool(
                        source_item
                        and capability in source_item.get("produces", [])
                        and source_project_id == target_project_id
                        and source_position < target_position
                    )
                elif source_kind == "ENGINEERING_DAG":
                    source_node = dag_nodes.get(source_id)
                    source_valid = source_valid and bool(
                        source_node
                        and capability
                        in source_node.get("produces_capabilities", [])
                        and (
                            target_surface == "RELEASE_PIPELINE"
                            or dag_positions.get(source_id, -1)
                            < dag_positions.get(target_control_id, -1)
                        )
                    )
                elif source_kind == "RELEASE_PIPELINE":
                    source_step = release_steps.get(source_id)
                    source_valid = source_valid and bool(
                        target_surface == "RELEASE_PIPELINE"
                        and source_step
                        and capability in source_step.get("produces", [])
                        and release_positions.get(source_id, -1)
                        < release_positions.get(target_control_id, -1)
                    )
                else:
                    source_valid = False
                if not source_valid:
                    findings.append(
                        _finding(
                            "PROJECT_WORKPACK_REQUIREMENT_SOURCE_INVALID",
                            f"{workpack_id}:{capability}:{source_ref}",
                        )
                    )
    return findings


def _check_authoring_boundary(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    context = _read_json(root / "START_CONTEXT.json", findings)
    program = _read_json(root / "PROGRAM_STATE.json", findings)
    driver = _read_json(root / "PROGRAM_DRIVER_STATE.json", findings)
    execution = _read_json(root / "EXECUTION_AUTHORIZATION.json", findings)
    real_install = _read_json(root / "REAL_TARGET_INSTALL_AUTHORIZATION.json", findings)
    if isinstance(context, dict):
        expected = {
            "current_state": TARGET_CANDIDATE_STATE,
            "execution_mode": "AUTHORING_ONLY",
            "execution_started": False,
            "install_started": False,
            "certification_started": False,
            "auto_start_generated_workpacks": False,
            "program_driver_started": False,
            "program_driver_runtime_verified": False,
            "active_workpack": None,
            "next_eligible_transition": "HUMAN_REVIEW_OF_START_PACKAGE",
        }
        for key, value in expected.items():
            if context.get(key) != value:
                findings.append(_finding("AUTHORING_CONTEXT_VIOLATION", f"{key}={context.get(key)!r}"))
    if isinstance(program, dict):
        if program.get("current_phase") is not None or program.get("highest_touched_phase") is not None or program.get("highest_locally_closed_phase") is not None or program.get("active_workpack") is not None:
            findings.append(_finding("PROGRAM_EXECUTION_STATE_PREPOPULATED", "PROGRAM_STATE.json"))
        if program.get("auto_start_generated_workpacks") is not False:
            findings.append(_finding("PROGRAM_AUTO_START_FORBIDDEN", "PROGRAM_STATE.json"))
    if isinstance(driver, dict):
        if driver.get("driver_started") is not False or driver.get("controlled_auto_advance_enabled") is not False or driver.get("side_effects_allowed") is not False or driver.get("active_workpack_id") is not None:
            findings.append(_finding("DRIVER_STARTED_OR_AUTHORIZED", "PROGRAM_DRIVER_STATE.json"))
    if isinstance(execution, dict):
        if execution.get("status") in {"GRANTED", "ISSUED", "ACTIVE"} or execution.get("may_auto_advance") is not False or execution.get("max_transitions") != 0 or execution.get("real_target_install_allowed") is not False:
            findings.append(_finding("EXECUTION_AUTHORIZATION_PREGRANTED", "EXECUTION_AUTHORIZATION.json"))
    if isinstance(real_install, dict):
        if real_install.get("status") in {"GRANTED", "ISSUED", "ACTIVE"} or real_install.get("may_be_generated_or_self_granted_by_driver") is not False:
            findings.append(_finding("REAL_INSTALL_AUTHORIZATION_PREGRANTED", "REAL_TARGET_INSTALL_AUTHORIZATION.json"))
    command_files = [root / "COMMAND_MANIFEST.json", *root.glob("project_start_packages/*/COMMAND_MANIFEST.json")]
    logical_root = Path(str(context.get("target_root", root))).resolve() if isinstance(context, dict) else root
    for path in command_files:
        command_manifest = _read_json(path, findings)
        if not isinstance(command_manifest, dict):
            continue
        for command in command_manifest.get("commands", []):
            if not isinstance(command, dict):
                continue
            executable = command.get("executable_abs", command.get("executable"))
            executable_path = Path(str(executable)) if executable else Path("")
            argv = command.get("argv")
            cwd = command.get("cwd_abs") or command.get("cwd_absolute")
            cwd_path = Path(str(cwd)) if cwd else Path("")
            if (
                not executable
                or not executable_path.is_absolute()
                or not executable_path.is_relative_to(logical_root)
                or executable_path.exists()
            ):
                findings.append(_finding("COMMAND_EXECUTABLE_NOT_ABSOLUTE", f"{path.name}:{command.get('command_id')}"))
            if command.get("command_kind") == "PLANNED_EXECUTOR_INTERFACE":
                command_plan_invalid = (
                    argv is not None
                    or not cwd_path.is_absolute()
                    or not cwd_path.is_relative_to(logical_root)
                    or command.get("executable_status")
                    != "PLANNED_NOT_INSTALLED"
                    or not command.get("preflight_gate")
                    or not str(command.get("invocation_contract_status", "")).startswith(
                        "REQUIRES_"
                    )
                    or command.get("unverified_cli_flags_forbidden") is not True
                    or command.get("shell") is not False
                )
            else:
                command_plan_invalid = (
                    not isinstance(argv, list)
                    or not argv
                    or argv[0] != str(executable_path)
                    or not cwd_path.is_absolute()
                    or not cwd_path.is_relative_to(logical_root)
                    or command.get("executable_status")
                    != "PLANNED_NOT_INSTALLED"
                    or not command.get("preflight_gate")
                    or command.get("shell") is True
                )
            if command_plan_invalid:
                findings.append(
                    _finding(
                        "COMMAND_PLAN_CONTRACT_INVALID",
                        f"{path.name}:{command.get('command_id')}",
                    )
                )
            if command.get("auto_execute") is True or command.get("authorization_ref") is not None:
                findings.append(_finding("COMMAND_AUTO_EXECUTION_FORBIDDEN", f"{path.name}:{command.get('command_id')}"))
    return findings


def _check_control_bindings(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    context = _read_json(root / "START_CONTEXT.json", findings)
    profile = _read_json(root / "PROFILE_LOCK.json", findings)
    if not isinstance(context, dict) or not isinstance(profile, dict):
        return findings
    frozen_ir = _read_json(
        root / "canonical_sources/FROZEN_REQUIREMENT_IR.json", findings
    )
    expected = {
        "program_id": frozen_ir.get("program_id")
        if isinstance(frozen_ir, dict)
        else None,
        "profile_lock_hash": _json_hash(profile),
        "charter_hash": _file_hash(root / "PROGRAM_CHARTER.md"),
        "control_plane_epoch": 0,
    }
    asset_names = (
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
    )
    for name in asset_names:
        document = _read_json(root / name, findings)
        if not isinstance(document, dict):
            continue
        if document.get("schema_version") != "2.8" or any(
            document.get(key) != value for key, value in expected.items()
        ):
            findings.append(_finding("CONTROL_ASSET_BINDING_MISMATCH", name))
    for _project_id, directory in PROJECTS:
        for name in ("PROJECT_STATE.json", "WORKPACK_INDEX.json", "COMMAND_MANIFEST.json"):
            path = root / "project_start_packages" / directory / name
            document = _read_json(path, findings)
            if isinstance(document, dict) and (
                document.get("schema_version") != "2.8"
                or any(document.get(key) != value for key, value in expected.items())
            ):
                findings.append(
                    _finding(
                        "PROJECT_CONTROL_BINDING_MISMATCH",
                        f"{directory}/{name}",
                    )
                )
    three = _read_json(root / "THREE_PROJECT_PROGRAM_MANIFEST.json", findings)
    protocol = _read_json(root / "build_program/conformance/CONFORMANCE_INTERFACE.json", findings)
    attestation = _read_json(root / "constitution/RUNTIME_ATTESTATION_POLICY.json", findings)
    if isinstance(three, dict) and isinstance(protocol, dict) and isinstance(attestation, dict):
        baseline = three.get("shared_control_baseline", {})
        if (
            baseline.get("protocol_sha256") != _json_hash(protocol)
            or baseline.get("schema_bundle_sha256") != _json_hash(attestation)
            or any(baseline.get(key) != value for key, value in expected.items() if key != "program_id")
            or baseline.get("status") != "WAITING_START_PACKAGE_HUMAN_APPROVAL"
        ):
            findings.append(
                _finding("SHARED_CONTROL_BASELINE_BINDING_INVALID", "THREE_PROJECT_PROGRAM_MANIFEST.json")
            )
        for project in three.get("projects", []):
            if not isinstance(project, dict) or (
                project.get("entrypoint_status") != "PLANNED_NOT_INSTALLED"
                or project.get("repository_status") != "PLANNED_NOT_CREATED"
                or project.get("self_validation_status") != "PLANNED_NOT_RUN"
                or project.get("tool_distribution_hash") is not None
                or project.get("tool_distribution_status") != "PLANNED_NOT_BUILT"
            ):
                findings.append(
                    _finding("THREE_PROJECT_DISTRIBUTION_STATE_INVALID", str(project))
                )
    return findings


def _check_control_contracts(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    driver = _read_json(root / "PROGRAM_DRIVER_CONTRACT.json", findings)
    driver_state = _read_json(root / "PROGRAM_DRIVER_STATE.json", findings)
    loop_policy = _read_json(root / "LOOP_POLICY.json", findings)
    loop_state = _read_json(root / "LOOP_STATE.json", findings)
    repair = _read_json(root / "REPAIR_ROUTING_RULES.json", findings)
    invalidation = _read_json(root / "INVALIDATION_DAG.json", findings)
    reentry = _read_json(root / "REENTRY_PLAN.json", findings)
    if isinstance(driver, dict):
        invariants = driver.get("safety_invariants", {})
        required = ("single_active_workpack", "no_phase_skip", "real_target_install_never_covered_by_generic_authorization")
        for key in required:
            if invariants.get(key) is not True:
                findings.append(_finding("DRIVER_INVARIANT_MISSING", key))
        commands = {item.get("name") for item in driver.get("commands", []) if isinstance(item, dict)}
        if not {"status", "plan-next", "advance", "resume"}.issubset(commands):
            findings.append(_finding("DRIVER_RECOVERY_INTERFACE_INCOMPLETE", str(sorted(commands))))
        transaction = driver.get("transaction_contract", {})
        recovery = driver.get("crash_recovery_contract", {})
        if not all(value is True for value in transaction.values()) or len(transaction) < 5:
            findings.append(_finding("DRIVER_TRANSACTION_CONTRACT_INCOMPLETE", str(transaction)))
        if not all(value is True for value in recovery.values()) or len(recovery) < 4:
            findings.append(_finding("DRIVER_CRASH_RECOVERY_INCOMPLETE", str(recovery)))
    if isinstance(driver_state, dict):
        lease = driver_state.get("lease", {})
        attempt = driver_state.get("active_attempt", {})
        recovery_state = driver_state.get("recovery", {})
        budget = driver_state.get("transition_budget", {})
        if (
            any(value is not None for value in lease.values())
            or any(value is not None for value in attempt.values())
            or recovery_state.get("required") is not False
            or recovery_state.get("resume_authorization_ref") is not None
            or budget != {"authorized_max": 0, "remaining": 0, "used": 0}
            or driver_state.get("state_revision") != 0
            or driver_state.get("last_ledger_event_hash") is not None
        ):
            findings.append(_finding("DRIVER_STATE_PRESTART_RECOVERY_INVALID", "PROGRAM_DRIVER_STATE.json"))
    if isinstance(loop_policy, dict):
        loop_types = loop_policy.get("loop_types", {})
        required_loop_types = {
            "WORKPACK_EXECUTION",
            "WORKPACK_REVIEW_FIX",
            "RELEASE_GATE_REPAIR",
            "CROSS_PROJECT_REPAIR_REENTRY",
        }
        stop_text = " ".join(str(item) for item in loop_policy.get("mandatory_stop_conditions", []))
        if (
            loop_policy.get("authorization_required") is not True
            or loop_policy.get("automatic_loops_default") is not False
            or set(loop_types) != required_loop_types
            or len(loop_policy.get("iteration_requirements", [])) < 6
            or not loop_policy.get("convergence_rules")
            or not all(
                term in stop_text
                for term in ("HUMAN_GATE", "OSCILLATION", "NO_PROGRESS", "REAL_TARGET_INSTALL")
            )
            or any(
                not isinstance(config, dict)
                or not isinstance(config.get("max_iterations"), int)
                or config.get("max_iterations") <= 0
                or config.get("max_same_finding_repeats", 0) <= 0
                or config.get("max_oscillation_repeats", 0) <= 0
                for config in loop_types.values()
            )
        ):
            findings.append(_finding("LOOP_POLICY_INCOMPLETE", "LOOP_POLICY.json"))
    if isinstance(loop_state, dict):
        if loop_state.get("status") != "NOT_STARTED" or loop_state.get("promotion_eligible") is not False:
            findings.append(_finding("LOOP_STATE_PRESTART_INVALID", "LOOP_STATE.json"))
    if isinstance(repair, dict) and repair.get("single_repair_owner_required") is not True:
        findings.append(_finding("SINGLE_REPAIR_OWNER_NOT_REQUIRED", "REPAIR_ROUTING_RULES.json"))
    if isinstance(invalidation, dict):
        nodes = invalidation.get("nodes", [])
        expected_edges = [
            {"from": source, "to": target}
            for source, target in zip(nodes, nodes[1:])
        ] if isinstance(nodes, list) else []
        propagation = invalidation.get("propagation_policy", {})
        if (
            not isinstance(nodes, list)
            or len(nodes) < 15
            or invalidation.get("edges") != expected_edges
            or len(invalidation.get("triggers", [])) < 8
            or not all(value is True for value in propagation.values())
            or len(propagation) < 4
        ):
            findings.append(_finding("INVALIDATION_DAG_INCOMPLETE", "INVALIDATION_DAG.json"))
    if isinstance(reentry, dict):
        if reentry.get("status") != "DRAFT_NOT_AUTHORIZED" or reentry.get("authorization_ref") is not None or not reentry.get("completion_requires"):
            findings.append(_finding("REENTRY_PLAN_BOUNDARY_INVALID", "REENTRY_PLAN.json"))
    for ledger_name in ("PHASE_TRANSITION_LEDGER.jsonl", "PROMOTION_LEDGER.jsonl", "REVOCATION_LEDGER.jsonl"):
        records = _read_jsonl(root / ledger_name, findings)
        if len(records) != 1 or records[0].get("sequence") != 1 or records[0].get("previous_event_hash") is not None:
            findings.append(_finding("LEDGER_INITIALIZATION_INVALID", ledger_name))
        elif records:
            record = dict(records[0])
            stored_hash = record.pop("event_hash", None)
            if stored_hash != _json_hash(record):
                findings.append(_finding("LEDGER_EVENT_HASH_INVALID", ledger_name))
    return findings


def _check_negative_contracts(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    negative = _read_json(root / "validation/NEGATIVE_CASES.json", findings)
    attestation = _read_json(root / "constitution/RUNTIME_ATTESTATION_POLICY.json", findings)
    runtime = _read_json(root / "constitution/RUNTIME_OWNERSHIP.json", findings)
    roles = _read_json(root / "PACKAGE_ROLES.json", findings)
    if isinstance(negative, dict):
        cases = negative.get("cases", [])
        if not cases:
            findings.append(_finding("NEGATIVE_CASES_EMPTY", "NEGATIVE_CASES.json"))
        structured = [
            case
            for case in cases
            if isinstance(case, dict)
            and case.get("case_id")
            and isinstance(case.get("atom_ids"), list)
            and case.get("atom_ids")
            and case.get("description")
            and case.get("expected_failure")
        ]
        if len(structured) != len(cases) or _duplicates([case.get("case_id") for case in structured]):
            findings.append(_finding("NEGATIVE_CASE_STRUCTURE_INVALID", "NEGATIVE_CASES.json"))
        required_case_ids = {
            "NEG-HF28-CODEX-SELF-REPORT",
            "NEG-HF28-ATTESTATION-REPLAY",
            "NEG-HF28-OUTPUT-SUBSTITUTION",
            "NEG-HF28-STUB-EXECUTOR",
            "NEG-HF28-P3-SKIP",
            "NEG-HF28-STALE-HASH",
            "NEG-HF28-MISSING-STAGE-RECEIPT",
            "NEG-HF28-SOURCE-DRIVER-FALLBACK",
            "NEG-HF28-CERTIFICATE-REUSE",
            "NEG-HF28-AUTH-SCOPE",
            "NEG-HF28-MULTIPLE-NEXT-LEASE",
            "NEG-HF28-RELEASE-SKIP",
            "NEG-HF28-LOOP-OSCILLATION",
            "NEG-HF28-CRASH-DUPLICATE",
            "NEG-HF28-UPSTREAM-INVALIDATION",
            "NEG-HF28-AUTO-REAL-INSTALL",
            "NEG-HF28-THREE-PROJECT-ORDER",
            "NEG-HF28-DUAL-ACTIVE-WORKPACK",
            "NEG-HF28-CANDIDATE-ENV-MISMATCH",
            "NEG-HF28-TOOL-DISTRIBUTION-DRIFT",
            "NEG-HF28-B0-B1-ORDER",
            "NEG-HF28-LINKAGE-AUTHORITY",
        }
        actual_case_ids = {str(case.get("case_id")) for case in structured}
        missing_required = sorted(required_case_ids.difference(actual_case_ids))
        if missing_required:
            findings.append(
                _finding("MANDATORY_NEGATIVE_CASES_MISSING", ",".join(missing_required))
            )
        codex_cases = [
            case
            for case in structured
            if "codex" in json.dumps(case, ensure_ascii=False).lower()
            and any(
                term in json.dumps(case, ensure_ascii=False).lower()
                for term in ("receipt", "invocation", "self-report", "python")
            )
            and "unverified" in str(case.get("expected_failure", "")).lower()
        ]
        p3_cases = [
            case
            for case in structured
            if "p3" in json.dumps(case, ensure_ascii=False).lower()
            and any(
                term in str(case.get("expected_failure", "")).lower()
                for term in ("illegal", "phase", "predecessor")
            )
        ]
        if not codex_cases:
            findings.append(_finding("FALSE_CODEX_RECEIPT_CASE_MISSING", "NEGATIVE_CASES.json"))
        if not p3_cases:
            findings.append(_finding("P3_SKIP_NEGATIVE_CASE_MISSING", "NEGATIVE_CASES.json"))
    if isinstance(attestation, dict):
        text = json.dumps(attestation, ensure_ascii=False).lower()
        for required in ("challenge", "replay", "executor", "raw"):
            if required not in text:
                findings.append(_finding("ATTESTATION_CONTRACT_INCOMPLETE", required))
        if attestation.get("self_reported_receipt_is_sufficient") is not False:
            findings.append(
                _finding(
                    "SELF_REPORTED_RECEIPT_AUTHORITY_FORBIDDEN",
                    "self_reported_receipt_is_sufficient must be false",
                )
            )
        if attestation.get("unverified_invocation_may_complete_stage") is not False:
            findings.append(
                _finding(
                    "UNVERIFIED_INVOCATION_COMPLETION_FORBIDDEN",
                    "unverified_invocation_may_complete_stage must be false",
                )
            )
        trusted_issuer = str(attestation.get("trusted_issuer", "")).upper()
        if (
            "EXTERNAL" not in trusted_issuer
            or not any(value in trusted_issuer for value in ("RUNNER", "LAB"))
            or any(value in trusted_issuer for value in ("PYTHON", "SELF_REPORT", "HARNESS_SELF"))
        ):
            findings.append(
                _finding("ATTESTATION_TRUSTED_ISSUER_INVALID", trusted_issuer)
            )
    if isinstance(runtime, dict):
        final_entry = Path(str(runtime.get("final_runtime_entrypoint_abs", "")))
        driver_entry = Path(str(runtime.get("build_program_driver_entrypoint_abs", "")))
        executor = runtime.get("required_executor", {})
        executor_entry = Path(str(executor.get("executable_abs", ""))) if isinstance(executor, dict) else Path("")
        coding_agent = runtime.get("coding_agent_executor", {})
        coding_agent_entry = (
            Path(str(coding_agent.get("executable_abs", "")))
            if isinstance(coding_agent, dict)
            else Path("")
        )
        if (
            not final_entry.is_absolute()
            or not driver_entry.is_absolute()
            or final_entry == driver_entry
            or runtime.get("entrypoints_must_be_distinct") is not True
            or runtime.get("final_runtime_entrypoint_status") != "PLANNED_NOT_INSTALLED"
            or runtime.get("runtime_attestation_required") is not True
            or runtime.get("source_tree_entrypoint_fallback_allowed") is not False
            or runtime.get("build_program_driver_fallback_allowed") is not False
            or runtime.get("primary_runtime_semantic_role") != "REQUIRED_EXECUTOR_OR_PROVIDER"
            or not executor_entry.is_absolute()
            or executor_entry in {final_entry, driver_entry}
            or executor.get("status") != "PLANNED_NOT_INSTALLED"
            or executor.get("invocation_argv") is not None
            or executor.get("unverified_cli_flags_forbidden") is not True
            or runtime.get("runtime_probe_argv") is not None
            or runtime.get("runtime_probe_status") != "PLANNED_REQUIRES_VERIFIED_CLI_SCHEMA"
            or not coding_agent_entry.is_absolute()
            or coding_agent_entry.name.lower() != "codex"
            or coding_agent_entry in {final_entry, driver_entry}
            or coding_agent.get("name") != "Codex"
            or coding_agent.get("semantic_role")
            != "AUTHORIZED_ENGINEERING_WORKPACK_CODING_AGENT"
            or coding_agent.get("status") != "PLANNED_NOT_INSTALLED"
            or coding_agent.get("invocation_argv") is not None
            or coding_agent.get("unverified_cli_flags_forbidden") is not True
            or runtime.get(
                "coding_agent_must_not_be_substituted_by_verification_runtime"
            )
            is not True
        ):
            findings.append(_finding("RUNTIME_OWNERSHIP_CONTRACT_INVALID", "RUNTIME_OWNERSHIP.json"))
        coding_command_ids: set[str] = set()
        for path in (
            root / "COMMAND_MANIFEST.json",
            *(
                root / "project_start_packages" / directory / "COMMAND_MANIFEST.json"
                for _project_id, directory in PROJECTS
            ),
        ):
            manifest = _read_json(path, findings)
            if not isinstance(manifest, dict):
                continue
            for command in manifest.get("commands", []):
                if not isinstance(command, dict):
                    continue
                command_id = str(command.get("command_id", ""))
                if command_id == "ROOT-CODEX-CODING" or command_id.endswith(
                    "CODEX-CODING"
                ):
                    coding_command_ids.add(command_id)
                    if (
                        Path(
                            str(
                                command.get("executable_abs")
                                or command.get("executable")
                                or ""
                            )
                        )
                        != coding_agent_entry
                        or command.get("command_kind")
                        != "PLANNED_EXECUTOR_INTERFACE"
                        or command.get("executor_role") != "CODEX_CODING_AGENT"
                        or command.get("argv") is not None
                    ):
                        findings.append(
                            _finding(
                                "CODEX_CODING_COMMAND_SUBSTITUTED", command_id
                            )
                        )
        if coding_command_ids != {
            "ROOT-CODEX-CODING",
            "LAB-CODEX-CODING",
            "LINK-CODEX-CODING",
            "MB-CODEX-CODING",
        }:
            findings.append(
                _finding(
                    "CODEX_CODING_COMMAND_COVERAGE_INVALID",
                    str(sorted(coding_command_ids)),
                )
            )
        if "codex" in str(runtime.get("primary_runtime", "")).lower():
            if (
                executor_entry.name.lower() != "codex"
                or "python" in str(executor_entry).lower()
                or runtime.get("python_or_harness_self_report_may_prove_codex") is not False
            ):
                findings.append(_finding("CODEX_RUNTIME_FALLBACK_INVALID", "RUNTIME_OWNERSHIP.json"))
    if isinstance(roles, dict):
        role_data = roles.get("roles", {})
        lab = role_data.get("external_conformance_lab", {})
        linkage = role_data.get("read_only_linkage_review", {})
        main = role_data.get("main_build_project", {})
        author = role_data.get("program_author", {})
        driver_role = role_data.get("build_program_driver", {})
        installer = role_data.get("certification_installer", {})
        if lab.get("may_modify_target") is not False or lab.get("may_issue_certificate") is not True:
            findings.append(_finding("LAB_AUTHORITY_INVALID", "PACKAGE_ROLES.json"))
        if linkage.get("may_repair") is not False or linkage.get("may_issue_certificate") is not False:
            findings.append(_finding("LINKAGE_AUTHORITY_INVALID", "PACKAGE_ROLES.json"))
        if main.get("may_self_certify") is not False:
            findings.append(_finding("MAIN_SELF_CERTIFICATION_FORBIDDEN", "PACKAGE_ROLES.json"))
        if any(
            author.get(key) is not False
            for key in (
                "may_execute_workpacks",
                "may_grant_execution_authorization",
                "may_start_driver",
            )
        ):
            findings.append(_finding("PROGRAM_AUTHOR_AUTHORITY_ESCALATED", "PACKAGE_ROLES.json"))
        if (
            driver_role.get("may_self_authorize") is not False
            or driver_role.get("may_issue_certificate") is not False
            or driver_role.get("may_skip_phase_or_gate") is not False
        ):
            findings.append(_finding("DRIVER_AUTHORITY_INVALID", "PACKAGE_ROLES.json"))
        if (
            installer.get("may_decide_conformance_pass") is not False
            or installer.get("may_modify_source") is not False
            or installer.get("real_target_install_requires_separate_authorization") is not True
        ):
            findings.append(_finding("INSTALLER_AUTHORITY_INVALID", "PACKAGE_ROLES.json"))
    return findings


def _check_handoff(
    root: Path, *, require_internal_report: bool = True
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    handoff_path = root / "AUTHORING_HANDOFF.md"
    start_path = root / "START.md"
    report = _read_json(root / "validation/START_PACKAGE_VALIDATION_REPORT.json", findings)
    combined = ""
    for path in (handoff_path, start_path, root / "README.md"):
        if path.is_file():
            combined += path.read_text(encoding="utf-8") + "\n"
    for required in (TARGET_CANDIDATE_STATE, "AUTHORING_STOP", "HUMAN_REVIEW"):
        if required not in combined:
            findings.append(_finding("HANDOFF_STOP_SEMANTIC_MISSING", required))
    nonclaim_terms = ("Driver", "Workpack", "Harness", "install", "Linkage", "certification")
    if not all(term.lower() in combined.lower() for term in nonclaim_terms):
        findings.append(_finding("HANDOFF_NONCLAIMS_INCOMPLETE", "AUTHORING_HANDOFF.md"))
    if isinstance(report, dict) and require_internal_report:
        if report.get("status") != "PASS" or report.get("permitted_terminal_state") != TARGET_CANDIDATE_STATE or report.get("blocking_findings"):
            findings.append(_finding("AUTHORING_VALIDATION_REPORT_INVALID", "START_PACKAGE_VALIDATION_REPORT.json"))
        if report.get("writes_performed") is not False or report.get("runtime_tests_executed") is not False:
            findings.append(_finding("VALIDATION_REPORT_OVERCLAIM", "START_PACKAGE_VALIDATION_REPORT.json"))
    return findings


def _read_json(path: Path, findings: list[dict[str, Any]]) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        findings.append(_finding("JSON_READ_FAILED", f"{path}: {exc}"))
        return None
    if not isinstance(value, dict):
        findings.append(_finding("JSON_ROOT_NOT_OBJECT", str(path)))
        return None
    return value


def _read_jsonl(path: Path, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("record is not an object")
            records.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        findings.append(_finding("JSONL_READ_FAILED", f"{path}: {exc}"))
    return records


def _finding(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "message": message}


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _hash_without_field(value: Mapping[str, Any], field: str) -> str:
    document = dict(value)
    document.pop(field, None)
    return _json_hash(document)


def _duplicates(values: Iterable[Any]) -> set[Any]:
    seen: set[Any] = set()
    duplicates: set[Any] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _tree_snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    result: dict[str, tuple[int, int, str]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            stat = path.stat()
            result[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns, _file_hash(path))
    return result
