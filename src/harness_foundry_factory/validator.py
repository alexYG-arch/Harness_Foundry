"""Read-only validator for a materialized Harness Foundry v2.8 candidate."""

from __future__ import annotations

import hashlib
import json
import os
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
    (
        "CANDIDATE_IMMUTABILITY_AND_EXECUTION_ROOT",
        lambda root: _check_candidate_execution_separation(root),
    ),
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


def _context_roots(
    root: Path, findings: list[dict[str, Any]]
) -> tuple[Path, Path, dict[str, Any]]:
    context = _read_json(root / "START_CONTEXT.json", findings)
    if not isinstance(context, dict):
        return root, root, {}
    candidate_root = Path(
        str(context.get("candidate_root") or context.get("target_root") or root)
    ).expanduser().resolve()
    execution_root = Path(
        str(context.get("execution_root") or candidate_root)
    ).expanduser().resolve()
    return candidate_root, execution_root, context


def _check_candidate_execution_separation(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    candidate_root, execution_root, context = _context_roots(root, findings)
    if not context:
        return findings
    immutable = (
        context.get("candidate_root_access")
        == "READ_ONLY_AFTER_ATOMIC_PUBLICATION"
    )
    if not immutable:
        return findings
    if (
        context.get("target_root") != str(candidate_root)
        or context.get("candidate_root") != str(candidate_root)
        or context.get("execution_root") != str(execution_root)
        or context.get("execution_root_status") != "PLANNED_NOT_CREATED"
        or context.get("candidate_execution_root_overlap") is not False
        or candidate_root == execution_root
        or candidate_root.is_relative_to(execution_root)
        or execution_root.is_relative_to(candidate_root)
    ):
        findings.append(
            _finding(
                "CANDIDATE_IMMUTABILITY_VIOLATION",
                "START_CONTEXT candidate and execution roots are not disjoint",
            )
        )

    read_list_keys = {"allowed_read_paths"}
    write_list_keys = {
        "allowed_write_paths",
        "allowed_write_roots",
        "success_output_refs",
    }
    execution_scalar_keys = {
        "workspace_root_abs",
        "cwd_abs",
        "cwd_absolute",
        "executable",
        "executable_abs",
        "driver_entrypoint_abs",
        "root_abs",
        "repository_root_abs",
        "self_validation_ref",
        "final_runtime_entrypoint_abs",
        "build_program_driver_entrypoint_abs",
    }

    def check_path(value: Any, *, expected_root: Path, label: str) -> None:
        path = Path(str(value)).expanduser()
        if not path.is_absolute() or not path.resolve().is_relative_to(expected_root):
            findings.append(
                _finding(
                    "CANDIDATE_IMMUTABILITY_VIOLATION",
                    f"{label} escapes {expected_root}: {value}",
                )
            )

    def visit(value: Any, location: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                label = f"{location}.{key}"
                if key in read_list_keys and isinstance(item, list):
                    for entry in item:
                        check_path(
                            entry, expected_root=candidate_root, label=label
                        )
                elif key in write_list_keys and isinstance(item, list):
                    for entry in item:
                        check_path(
                            entry, expected_root=execution_root, label=label
                        )
                elif key in execution_scalar_keys and item not in (None, ""):
                    check_path(item, expected_root=execution_root, label=label)
                visit(item, label)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{location}[{index}]")

    for path in sorted(root.rglob("*.json")):
        document = _read_json(path, findings)
        if isinstance(document, (dict, list)):
            visit(document, path.relative_to(root).as_posix())

    capsule = _read_json(root / "CAPSULE.json", findings)
    forbidden = capsule.get("forbidden_write_paths", []) if isinstance(capsule, dict) else []
    if str(candidate_root) not in forbidden:
        findings.append(
            _finding(
                "CANDIDATE_IMMUTABILITY_VIOLATION",
                "CAPSULE.json must forbid the entire candidate root",
            )
        )
    return findings


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
        "PLANNED-REF-",
    )
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in {".md", ".json", ".jsonl"}:
            continue
        text = path.read_text(encoding="utf-8")
        if PLACEHOLDER_RE.search(text):
            findings.append(_finding("UNRESOLVED_TEMPLATE_PLACEHOLDER", path.relative_to(root).as_posix()))
        if re.search(
            r'(?m)(?:^\s*PLACEHOLDER\s*$|:\s*"PLACEHOLDER"\s*[,}])',
            text,
        ):
            findings.append(
                _finding(
                    "FORBIDDEN_TEMPLATE_LITERAL",
                    f"{path.relative_to(root)}: PLACEHOLDER",
                )
            )
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
        candidate_root, execution_root, _context = _context_roots(root, findings)
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
            read_paths = step.get("allowed_read_paths", [])
            write_paths = [
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
                    or not Path(str(value)).is_relative_to(candidate_root)
                    for value in read_paths
                )
                or any(
                    not Path(str(value)).is_absolute()
                    or not Path(str(value)).is_relative_to(execution_root)
                    for value in write_paths
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
    candidate_root, execution_root, context = _context_roots(root, findings)
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
            if not root_abs.is_absolute() or not root_abs.is_relative_to(execution_root):
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
            read_paths = node.get("allowed_read_paths", [])
            write_paths = [
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
                    or not Path(str(value)).is_relative_to(candidate_root)
                    for value in read_paths
                )
                or any(
                    not Path(str(value)).is_absolute()
                    or not Path(str(value)).is_relative_to(execution_root)
                    for value in write_paths
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
                    execution_root
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
                    execution_root
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
                    execution_root
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
            candidate_root=candidate_root,
            execution_root=execution_root,
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
                    or not executable.is_relative_to(execution_root)
                    or command.get("authorization_ref") is not None
                ):
                    findings.append(_finding("PROJECT_COMMAND_BOUNDARY_INVALID", f"{directory}:{command.get('command_id') if isinstance(command, dict) else command}"))
    return findings


def _check_project_workpack_execution_contracts(
    root: Path,
    *,
    candidate_root: Path,
    execution_root: Path,
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
                or not executable.is_relative_to(execution_root)
                or not cwd.is_absolute()
                or not cwd.is_relative_to(execution_root)
                or any(
                    not value.is_absolute()
                    or not value.is_relative_to(execution_root)
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
                    not path.is_absolute()
                    or not path.is_relative_to(candidate_root)
                    for path in allowed_read_paths
                )
                or any(
                    not path.is_absolute()
                    or not path.is_relative_to(execution_root)
                    for path in allowed_write_paths
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
    _candidate_root, execution_root, _context = _context_roots(root, findings)
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
            authorized_materialization = (
                executable_path.exists()
                and (
                    _authorized_driver_materialization_precondition(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_driver_materialization(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_codex_executor_materialization(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_lab_bootstrap_materialization(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_lab_self_conformance_materialization(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_lab_tool_release_preparation_materialization(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_lab_tool_release_materialization(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_linkage_tool_release_materialization(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_release_pipeline_handoff_preparation(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_main_p4_local_closure_completion(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_main_p4_local_closure_failure(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_main_p4_local_closure_preparation(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_main_p3_c3_implement_completion(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_main_p3_c3_or_approved_na_preparation(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_main_p2_c2_completion(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_main_p1_c1_completion(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_main_p1_c1_failure(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_main_p1_c1_preparation(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_main_g0_c0_completion(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_main_g0_c0_preparation(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_main_registration_completion(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_main_registration_preparation(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_main_validation_completion(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_main_validation_preparation(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_main_materialization_completion(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_main_materialization_preparation(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_linkage_tool_release_preparation_materialization(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_linkage_self_conformance_materialization(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_linkage_bootstrap_completion_materialization(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_linkage_executor_no_op_failure_materialization(
                        root, execution_root, executable_path, command
                    )
                    or _authorized_linkage_bootstrap_failure_materialization(
                        root, execution_root, executable_path, command
                    )
                )
            )
            if (
                not executable
                or not executable_path.is_absolute()
                or not executable_path.is_relative_to(execution_root)
                or (executable_path.exists() and not authorized_materialization)
            ):
                findings.append(_finding("COMMAND_EXECUTABLE_NOT_ABSOLUTE", f"{path.name}:{command.get('command_id')}"))
            if command.get("command_kind") == "PLANNED_EXECUTOR_INTERFACE":
                command_plan_invalid = (
                    argv is not None
                    or not cwd_path.is_absolute()
                    or not cwd_path.is_relative_to(execution_root)
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
                    or not cwd_path.is_relative_to(execution_root)
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


def _authorized_driver_materialization_precondition(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept only the consumed zero-transition Driver materialization scope."""

    if (
        command.get("executor_role") != "BUILD_PROGRAM_DRIVER"
        or command.get("command_kind") != "PLANNED_EXECUTOR_INTERFACE"
        or command.get("executable_status") != "PLANNED_NOT_INSTALLED"
        or command.get("auto_execute") is not False
        or command.get("authorization_ref") is not None
    ):
        return False
    try:
        contract = json.loads(
            (candidate_root / "PROGRAM_DRIVER_CONTRACT.json").read_text(
                encoding="utf-8"
            )
        )
        charter_lock = json.loads(
            (candidate_root / "CHARTER_LOCK.json").read_text(encoding="utf-8")
        )
        expected_entrypoint = Path(
            str(contract.get("driver_entrypoint_abs", ""))
        ).resolve()
        if executable_path.resolve() != expected_entrypoint:
            return False

        control_root = execution_root / "control_plane"
        evidence_root = (
            execution_root
            / "evidence/control_plane_bootstrap/PROGRAM_DRIVER_MATERIALIZATION"
        )
        run_roots = sorted(
            path for path in evidence_root.glob("RUN_*") if path.is_dir()
        )
        if len(run_roots) != 1:
            return False
        receipt_path = run_roots[0] / "MATERIALIZATION_RECEIPT.json"
        consumption_path = run_roots[0] / "AUTHORIZATION_CONSUMPTION.json"
        authorization_path = (
            control_root
            / "authorizations/PROGRAM_DRIVER_MATERIALIZATION_AUTHORIZATION.json"
        )
        state_path = control_root / "state/CONTROL_STATE.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        consumption = json.loads(consumption_path.read_text(encoding="utf-8"))
        authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
        state = json.loads(state_path.read_text(encoding="utf-8"))

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else execution_root / path).resolve()

        scope = authorization.get("scope", {})
        payload_hashes = receipt.get("runtime_payload_hashes", {})
        if not isinstance(scope, dict) or not isinstance(payload_hashes, dict):
            return False
        required_payloads = {
            "pyproject.toml",
            "src/dag_execution_control/cli.py",
            "src/dag_execution_control/driver.py",
            "tools/program_driver_materialization_runner.py",
        }
        if not required_payloads.issubset(payload_hashes):
            return False
        for relative_name in required_payloads:
            payload_path = (control_root / relative_name).resolve()
            if (
                not payload_path.is_relative_to(control_root.resolve())
                or not payload_path.is_file()
                or payload_hashes.get(relative_name) != _file_hash(payload_path)
            ):
                return False

        expected_write_roots = [str(control_root), str(evidence_root)]
        program_id = contract.get("program_id")
        return bool(
            program_id
            and receipt.get("program_id") == program_id
            and receipt.get("status") == "MATERIALIZED_NOT_RUNTIME_VERIFIED"
            and receipt.get("authorization_id")
            == authorization.get("authorization_id")
            and receipt.get("scope_sha256") == authorization.get("scope_sha256")
            and receipt.get("source_bundle_sha256")
            == authorization.get("source_bundle_sha256")
            and receipt.get("operation_manifest_sha256")
            == authorization.get("operation_manifest_sha256")
            and receipt.get("runtime_control_root") == str(control_root)
            and receipt.get("driver_entrypoint_abs") == str(expected_entrypoint)
            and receipt.get("driver_entrypoint_sha256")
            == _file_hash(executable_path)
            and receipt.get("runtime_payload_file_count") == len(payload_hashes)
            and receipt.get("driver_invoked") is False
            and receipt.get("driver_runtime_verified") is False
            and receipt.get("dag_transition_performed") is False
            and receipt.get("candidate_write_performed") is False
            and receipt.get("workpack_executed") is False
            and receipt.get("target_code_modified") is False
            and receipt.get("real_target_install_performed") is False
            and authorization.get("program_id") == program_id
            and authorization.get("authorization_class")
            == "PROJECT_BOOTSTRAP_AUTHORIZATION"
            and authorization.get("status") == "CONSUMED"
            and authorization.get("consumption_status")
            == "CONSUMED_VALID_MATERIALIZATION"
            and authorization.get("max_transitions") == 0
            and authorization.get("max_materializations") == 1
            and authorization.get("materializations_consumed") == 1
            and authorization.get("materializations_remaining") == 0
            and authorization.get("may_auto_advance") is False
            and authorization.get("may_promote_validated_results") is False
            and authorization.get("may_materialize_program_driver") is True
            and authorization.get("may_start_program_driver") is False
            and authorization.get("may_modify_target_code") is False
            and authorization.get("real_target_install_allowed") is False
            and authorization.get("scope_expansion_allowed") is False
            and authorization.get("delegation_allowed") is False
            and authorization.get("charter_hash")
            == charter_lock.get("charter_sha256")
            and authorization.get("profile_lock_hash")
            == charter_lock.get("profile_lock_sha256")
            and authorization.get("source_snapshot_hash")
            == state.get("approved_candidate_snapshot_hash")
            and scope.get("action_ids")
            == ["PROGRAM_DRIVER_MATERIALIZATION_PRECONDITION_V2"]
            and scope.get("allowed_write_roots") == expected_write_roots
            and scope.get("dag_node_ids") == []
            and scope.get("execution_modes") == ["PROGRAM_CONTROL_BOOTSTRAP"]
            and resolve_ref(authorization.get("materialization_receipt_ref"))
            == receipt_path.resolve()
            and authorization.get("materialization_receipt_sha256")
            == _file_hash(receipt_path)
            and resolve_ref(authorization.get("consumption_ref"))
            == consumption_path.resolve()
            and authorization.get("consumption_sha256")
            == _file_hash(consumption_path)
            and consumption.get("program_id") == program_id
            and consumption.get("authorization_id")
            == authorization.get("authorization_id")
            and consumption.get("scope_sha256")
            == authorization.get("scope_sha256")
            and consumption.get("consumption_status")
            == "CONSUMED_VALID_MATERIALIZATION"
            and consumption.get("consumed_by_action_id")
            == "PROGRAM_DRIVER_MATERIALIZATION_PRECONDITION_V2"
            and consumption.get("materializations_authorized") == 1
            and consumption.get("materializations_consumed") == 1
            and consumption.get("materializations_remaining") == 0
            and consumption.get("max_transitions") == 0
            and consumption.get("dag_transition_performed") is False
            and resolve_ref(consumption.get("materialization_receipt_ref"))
            == receipt_path.resolve()
            and consumption.get("materialization_receipt_sha256")
            == _file_hash(receipt_path)
            and consumption.get("driver_invoked") is False
            and consumption.get("driver_runtime_verified") is False
            and consumption.get("successor_execution_authorized") is False
            and consumption.get("replay_forbidden") is True
            and state.get("program_id") == program_id
            and state.get("control_status")
            == "PROGRAM_DRIVER_MATERIALIZED_PROJECT_VALIDATION_AUTHORIZATION_REQUIRED"
            and state.get("driver_materialized") is True
            and state.get("driver_started") is False
            and state.get("driver_runtime_verified") is False
            and state.get("next_eligible_node") == "PROGRAM_DRIVER_RUNTIME_VERIFIED"
            and state.get("program_execution_started") is False
            and state.get("side_effects_allowed") is False
            and not (
                control_root / "DRIVER_RUNTIME_VERIFICATION_RECEIPT.json"
            ).exists()
            and not (
                execution_root
                / "evidence/engineering_dag/PROGRAM_DRIVER_RUNTIME_VERIFIED.result.json"
            ).exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_driver_materialization(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept only a receipt-bound post-approval Driver materialization."""

    if command.get("executor_role") != "BUILD_PROGRAM_DRIVER":
        return False
    try:
        contract = json.loads(
            (candidate_root / "PROGRAM_DRIVER_CONTRACT.json").read_text(
                encoding="utf-8"
            )
        )
        if executable_path.resolve() != Path(
            str(contract.get("driver_entrypoint_abs", ""))
        ).resolve():
            return False
        build_root = execution_root.parent
        receipt_path = execution_root / "control_plane/DRIVER_RUNTIME_VERIFICATION_RECEIPT.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        authorization_path = resolve_ref(receipt.get("authorization_ref"))
        attestation_path = resolve_ref(receipt.get("runtime_attestation_ref"))
        authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
        attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
        scope = authorization.get("scope", {})
        if not isinstance(scope, dict):
            return False
        return bool(
            receipt.get("status")
            == "DRIVER_RUNTIME_VERIFIED_STOPPED_BEFORE_START"
            and receipt.get("candidate_content_sha256")
            == _candidate_tree_hash(candidate_root)
            and receipt.get("driver_entrypoint_sha256")
            == _file_hash(executable_path)
            and resolve_ref(receipt.get("driver_entrypoint_ref"))
            == executable_path.resolve()
            and receipt.get("authorization_sha256")
            == _file_hash(authorization_path)
            and receipt.get("runtime_attestation_sha256")
            == _file_hash(attestation_path)
            and receipt.get("driver_started") is False
            and receipt.get("execution_started") is False
            and receipt.get("workpack_execution_started") is False
            and receipt.get("install_started") is False
            and authorization.get("status") == "GRANTED"
            and authorization.get("authorization_class")
            == "PROJECT_VALIDATION_AUTHORIZATION"
            and authorization.get("max_transitions") == 1
            and authorization.get("may_auto_advance") is False
            and scope.get("dag_node_ids") == ["PROGRAM_DRIVER_RUNTIME_VERIFIED"]
            and scope.get("workpack_ids") == []
            and "PROGRAM_DRIVER_START"
            in authorization.get("forbidden_actions", [])
            and attestation.get("status") == "PASS"
            and attestation.get("release_candidate_hash")
            == receipt.get("candidate_content_sha256")
            and attestation.get("executor_sha256") == _file_hash(executable_path)
            and attestation.get("self_reported_receipt_used") is False
            and attestation.get("driver_started") is False
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_codex_executor_materialization(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept only a receipt-bound, verified, and uninvoked Codex launcher."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent
        descriptor_path = (
            execution_root / "control_plane/CODEX_EXECUTOR_DESCRIPTOR.json"
        )
        receipt_path = (
            execution_root
            / "control_plane/CODEX_EXECUTOR_PREPARATION_RECEIPT.json"
        )
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        authorization_path = resolve_ref(receipt.get("authorization_ref"))
        authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
        scope = authorization.get("scope", {})
        forbidden = authorization.get("forbidden_actions", [])
        source_binary_path = Path(str(descriptor.get("source_binary_abs", "")))
        if not isinstance(scope, dict) or not isinstance(forbidden, list):
            return False
        return bool(
            descriptor.get("status") == "PREPARED_VERIFIED_NOT_INVOKED"
            and descriptor.get("candidate_content_sha256")
            == _candidate_tree_hash(candidate_root)
            and resolve_ref(descriptor.get("launcher_abs"))
            == executable_path.resolve()
            and descriptor.get("launcher_sha256") == _file_hash(executable_path)
            and descriptor.get("agent_invoked") is False
            and descriptor.get("execution_started") is False
            and descriptor.get("workpack_execution_started") is False
            and descriptor.get("real_target_install_started") is False
            and source_binary_path.is_absolute()
            and source_binary_path.exists()
            and descriptor.get("source_binary_sha256")
            == _file_hash(source_binary_path)
            and receipt.get("status")
            == "CODEX_EXECUTOR_PREPARED_VERIFIED_NOT_INVOKED"
            and resolve_ref(receipt.get("descriptor_ref"))
            == descriptor_path.resolve()
            and receipt.get("descriptor_sha256") == _file_hash(descriptor_path)
            and resolve_ref(receipt.get("launcher_ref"))
            == executable_path.resolve()
            and receipt.get("launcher_sha256") == _file_hash(executable_path)
            and receipt.get("authorization_sha256")
            == _file_hash(authorization_path)
            and receipt.get("agent_invoked") is False
            and receipt.get("driver_started") is False
            and receipt.get("execution_started") is False
            and receipt.get("workpack_execution_started") is False
            and receipt.get("real_target_install_started") is False
            and authorization.get("status") == "GRANTED"
            and authorization.get("authorization_class")
            == "REPAIR_EXECUTION_AUTHORIZATION"
            and authorization.get("max_transitions") == 2
            and authorization.get("may_auto_advance") is False
            and scope.get("workpack_ids") == []
            and {
                "CODEX_CODING_AGENT_INVOCATION",
                "PROGRAM_DRIVER_START",
                "PROJECT_BOOTSTRAP",
                "WORKPACK_EXECUTION",
            }.issubset(set(forbidden))
            and not (execution_root / "project_start_packages/external_lab").exists()
            and not (execution_root / "evidence/engineering_dag/LAB_BOOTSTRAP").exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_lab_bootstrap_materialization(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept a receipt-bound Codex launcher after the limited Lab bootstrap."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        descriptor_path = (
            execution_root
            / "control_plane/CODEX_EXECUTOR_DESCRIPTOR_AFTER_LAB_BOOTSTRAP.json"
        )
        receipt_path = (
            execution_root / "control_plane/LAB_BOOTSTRAP_COMPLETION_RECEIPT.json"
        )
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        authorization_path = resolve_ref(receipt.get("authorization_ref"))
        runtime_state_path = resolve_ref(receipt.get("runtime_state_ref"))
        result_path = resolve_ref(receipt.get("lab_bootstrap_result_ref"))
        authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
        runtime_state = json.loads(runtime_state_path.read_text(encoding="utf-8"))
        result = json.loads(result_path.read_text(encoding="utf-8"))
        repository = execution_root / "project_start_packages/external_lab/repository"
        digest = hashlib.sha256()
        file_count = 0
        for path in sorted(repository.rglob("*")):
            if (
                not path.is_file()
                or "__pycache__" in path.parts
                or path.suffix in {".pyc", ".pyo"}
            ):
                continue
            digest.update(path.relative_to(repository).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(_file_hash(path).encode("ascii"))
            digest.update(b"\n")
            file_count += 1
        forbidden = set(authorization.get("forbidden_actions", []))
        expected_workpacks = ["LAB-PROTOCOL", "LAB-CLI", "LAB-FIXTURES"]
        return bool(
            descriptor.get("status")
            == "ORDERED_LAB_BOOTSTRAP_SCOPE_CONSUMED_STOPPED"
            and descriptor.get("candidate_content_sha256")
            == _candidate_tree_hash(candidate_root)
            and descriptor.get("launcher_sha256") == _file_hash(executable_path)
            and descriptor.get("completion_receipt_sha256")
            == _file_hash(receipt_path)
            and resolve_ref(descriptor.get("completion_receipt_ref"))
            == receipt_path.resolve()
            and descriptor.get("completed_workpack_ids") == expected_workpacks
            and descriptor.get("lab_selftest_started") is False
            and descriptor.get("lab_certification_started") is False
            and descriptor.get("linkage_project_started") is False
            and descriptor.get("main_project_started") is False
            and descriptor.get("real_target_install_started") is False
            and receipt.get("status")
            == "LAB_BOOTSTRAP_COMPLETE_STOPPED_BEFORE_SELFTEST"
            and receipt.get("candidate_content_sha256")
            == _candidate_tree_hash(candidate_root)
            and receipt.get("authorization_sha256")
            == _file_hash(authorization_path)
            and receipt.get("runtime_state_sha256")
            == _file_hash(runtime_state_path)
            and receipt.get("lab_bootstrap_result_sha256") == _file_hash(result_path)
            and receipt.get("completed_workpack_ids") == expected_workpacks
            and receipt.get("authorization_transitions_consumed") == 3
            and receipt.get("repository_content_sha256") == digest.hexdigest()
            and receipt.get("repository_content_file_count") == file_count
            and receipt.get("lab_selftest_started") is False
            and receipt.get("lab_certification_started") is False
            and receipt.get("linkage_project_started") is False
            and receipt.get("main_project_started") is False
            and receipt.get("install_started") is False
            and receipt.get("real_target_install_started", False) is False
            and authorization.get("status") == "GRANTED"
            and authorization.get("authorization_class")
            == "REPAIR_REVERIFY_AND_WORKPACK_RETRY_AUTHORIZATION"
            and authorization.get("max_transitions") == 3
            and authorization.get("scope", {}).get("workpack_ids")
            == expected_workpacks
            and {
                "LAB_SELFTEST",
                "LAB_CERTIFICATION",
                "LINKAGE_PROJECT_BOOTSTRAP",
                "MAIN_PROJECT_BOOTSTRAP",
                "TARGET_RUNTIME_INSTALLATION",
                "REAL_TARGET_INSTALL",
            }.issubset(forbidden)
            and runtime_state.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and runtime_state.get("completed_workpack_ids") == expected_workpacks
            and runtime_state.get("active_workpack_id") is None
            and runtime_state.get("side_effects_allowed") is False
            and result.get("status") == "PASS"
            and result.get("success_gate") == "LAB_BOOTSTRAP_PASS"
            and not (execution_root / "project_start_packages/linkage_review").exists()
            and not (execution_root / "project_start_packages/main_build").exists()
            and not (
                execution_root / "evidence/engineering_dag/LAB_SELF_CONFORMANCE_PASS"
            ).exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_lab_self_conformance_materialization(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept the stopped launcher after the one-Workpack Lab self-test."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        control = execution_root / "control_plane"
        descriptor_path = (
            control / "CODEX_EXECUTOR_DESCRIPTOR_AFTER_LAB_SELF_CONFORMANCE.json"
        )
        receipt_path = control / "LAB_SELF_CONFORMANCE_COMPLETION_RECEIPT.json"
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        authorization_path = resolve_ref(receipt.get("authorization_ref"))
        runtime_path = resolve_ref(receipt.get("runtime_state_ref"))
        result_path = resolve_ref(receipt.get("lab_self_conformance_result_ref"))
        workpack_result_path = resolve_ref(receipt.get("workpack_result_ref"))
        independent_receipt_path = resolve_ref(
            receipt.get("independent_validation_receipt_ref")
        )
        authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        result = json.loads(result_path.read_text(encoding="utf-8"))
        workpack_result = json.loads(
            workpack_result_path.read_text(encoding="utf-8")
        )
        independent_receipt = json.loads(
            independent_receipt_path.read_text(encoding="utf-8")
        )

        repository = execution_root / "project_start_packages/external_lab/repository"
        digest = hashlib.sha256()
        file_count = 0
        for path in sorted(repository.rglob("*")):
            if (
                not path.is_file()
                or "__pycache__" in path.parts
                or path.suffix in {".pyc", ".pyo"}
            ):
                continue
            digest.update(path.relative_to(repository).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(_file_hash(path).encode("ascii"))
            digest.update(b"\n")
            file_count += 1

        expected_workpacks = [
            "LAB-PROTOCOL",
            "LAB-CLI",
            "LAB-FIXTURES",
            "LAB-SELFTEST",
        ]
        forbidden = set(authorization.get("forbidden_actions", []))
        return bool(
            descriptor.get("status")
            == "LAB_SELF_CONFORMANCE_COMPLETE_CODEX_STOPPED"
            and descriptor.get("candidate_content_sha256")
            == _candidate_tree_hash(candidate_root)
            and descriptor.get("launcher_sha256") == _file_hash(executable_path)
            and descriptor.get("agent_invocation_count") == 4
            and descriptor.get("lab_selftest_executor_kind")
            == "PINNED_LOCAL_PYTHON_NO_CODEX_AGENT"
            and descriptor.get("lab_self_conformance_completion_receipt_sha256")
            == _file_hash(receipt_path)
            and resolve_ref(
                descriptor.get("lab_self_conformance_completion_receipt_ref")
            )
            == receipt_path.resolve()
            and descriptor.get("completed_workpack_ids") == expected_workpacks
            and descriptor.get("lab_tool_release_started") is False
            and descriptor.get("lab_certification_started") is False
            and descriptor.get("linkage_project_started") is False
            and descriptor.get("main_project_started") is False
            and descriptor.get("real_target_install_started") is False
            and receipt.get("status")
            == "LAB_SELF_CONFORMANCE_COMPLETE_STOPPED_BEFORE_TOOL_RELEASE"
            and receipt.get("candidate_content_sha256")
            == _candidate_tree_hash(candidate_root)
            and receipt.get("authorization_sha256")
            == _file_hash(authorization_path)
            and receipt.get("runtime_state_sha256") == _file_hash(runtime_path)
            and receipt.get("lab_self_conformance_result_sha256")
            == _file_hash(result_path)
            and receipt.get("workpack_result_sha256")
            == _file_hash(workpack_result_path)
            and receipt.get("independent_validation_receipt_sha256")
            == _file_hash(independent_receipt_path)
            and receipt.get("completed_workpack_ids") == expected_workpacks
            and receipt.get("authorization_transitions_consumed") == 1
            and receipt.get("repository_content_sha256") == digest.hexdigest()
            and receipt.get("repository_content_file_count") == file_count
            and receipt.get("lab_tool_release_started") is False
            and receipt.get("lab_certification_started") is False
            and receipt.get("linkage_project_started") is False
            and receipt.get("main_project_started") is False
            and receipt.get("install_started") is False
            and receipt.get("target_runtime_install_started") is False
            and authorization.get("status") == "GRANTED"
            and authorization.get("authorization_class")
            == "PROJECT_VALIDATION_AUTHORIZATION"
            and authorization.get("max_transitions") == 1
            and authorization.get("may_auto_advance") is False
            and authorization.get("real_target_install_allowed") is False
            and authorization.get("scope", {}).get("dag_node_ids")
            == ["LAB_SELF_CONFORMANCE_PASS"]
            and authorization.get("scope", {}).get("workpack_ids")
            == ["LAB-SELFTEST"]
            and {
                "LAB_CERTIFICATION",
                "LINKAGE_PROJECT_BOOTSTRAP",
                "MAIN_PROJECT_BOOTSTRAP",
                "TARGET_RUNTIME_INSTALLATION",
                "REAL_TARGET_INSTALL",
            }.issubset(forbidden)
            and runtime.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and runtime.get("completed_workpack_ids") == expected_workpacks
            and runtime.get("authorization_consumptions", {}).get(
                authorization.get("authorization_id")
            )
            == 1
            and runtime.get("active_workpack_id") is None
            and runtime.get("side_effects_allowed") is False
            and result.get("status") == "PASS"
            and result.get("success_gate")
            == "LAB_SELF_CONFORMANCE_PASS_PASS"
            and workpack_result.get("status") == "PASS"
            and workpack_result.get("workpack_id") == "LAB-SELFTEST"
            and workpack_result.get("command_exit_code") == 0
            and workpack_result.get("independent_validation_exit_code") == 0
            and independent_receipt.get("status") == "PASS"
            and independent_receipt.get("independent_validation_exit_code") == 0
            and not (execution_root / "project_start_packages/linkage_review").exists()
            and not (execution_root / "project_start_packages/main_build").exists()
            and not (
                execution_root / "evidence/engineering_dag/LAB_TOOL_RELEASE_LOCKED"
            ).exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_lab_tool_release_preparation_materialization(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept the stopped launcher after a receipt-bound release preparation."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        control = execution_root / "control_plane"
        descriptor_path = (
            control / "PROGRAM_DRIVER_DESCRIPTOR_AFTER_PIPELINE_ACTION_REPAIR.json"
        )
        receipt_path = (
            control
            / "DRIVER_PIPELINE_ACTION_REPAIR_AND_LAB_TOOL_RELEASE_PREPARATION_RECEIPT.json"
        )
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        authorization_path = resolve_ref(receipt.get("authorization_ref"))
        runtime_path = resolve_ref(receipt.get("runtime_state_ref"))
        ledger_path = resolve_ref(receipt.get("transition_ledger_ref"))
        manifest_path = resolve_ref(receipt.get("pipeline_action_manifest_ref"))
        draft_path = resolve_ref(receipt.get("package_build_authorization_draft_ref"))
        readiness_path = resolve_ref(receipt.get("readiness_report_ref"))
        attestation_path = resolve_ref(receipt.get("runtime_attestation_ref"))
        authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
        attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
        prior_descriptor_path = resolve_ref(descriptor.get("prior_descriptor_ref"))
        prior_descriptor = json.loads(
            prior_descriptor_path.read_text(encoding="utf-8")
        )
        source_path = resolve_ref(descriptor.get("driver_source_ref"))
        entrypoint_path = resolve_ref(descriptor.get("driver_entrypoint_ref"))
        manifest_items = draft.get("command_manifest_refs", [])
        forbidden = set(authorization.get("forbidden_actions", []))
        runtime_material = dict(runtime)
        claimed_runtime_hash = runtime_material.pop("state_hash", None)
        target_output = (
            execution_root / "evidence/engineering_dag/LAB_TOOL_RELEASE_LOCKED"
        )
        expected_workpacks = [
            "LAB-PROTOCOL",
            "LAB-CLI",
            "LAB-FIXTURES",
            "LAB-SELFTEST",
        ]
        return bool(
            descriptor.get("status")
            == "PIPELINE_ACTION_SUPPORTED_RELEASE_PREPARED_NOT_AUTHORIZED"
            and descriptor.get("candidate_content_sha256")
            == _candidate_tree_hash(candidate_root)
            and descriptor.get("driver_version") == "0.3.0"
            and descriptor.get("driver_source_sha256") == _file_hash(source_path)
            and descriptor.get("driver_entrypoint_sha256")
            == _file_hash(entrypoint_path)
            and descriptor.get("runtime_state_sha256") == _file_hash(runtime_path)
            and descriptor.get("preparation_receipt_sha256")
            == _file_hash(receipt_path)
            and descriptor.get("prior_descriptor_sha256")
            == _file_hash(prior_descriptor_path)
            and prior_descriptor.get("launcher_sha256")
            == _file_hash(executable_path)
            and descriptor.get("completed_workpack_ids") == expected_workpacks
            and descriptor.get("completed_pipeline_action_ids") == []
            and descriptor.get("lab_tool_release_started") is False
            and descriptor.get("lab_certification_started") is False
            and descriptor.get("linkage_project_started") is False
            and descriptor.get("main_project_started") is False
            and descriptor.get("real_target_install_started") is False
            and receipt.get("status")
            == "COMPLETE_READY_FOR_EXPLICIT_PACKAGE_BUILD_AUTHORIZATION"
            and receipt.get("candidate_content_sha256")
            == _candidate_tree_hash(candidate_root)
            and receipt.get("authorization_sha256")
            == _file_hash(authorization_path)
            and receipt.get("runtime_state_sha256") == _file_hash(runtime_path)
            and receipt.get("transition_ledger_sha256") == _file_hash(ledger_path)
            and receipt.get("pipeline_action_manifest_sha256")
            == _file_hash(manifest_path)
            and receipt.get("package_build_authorization_draft_sha256")
            == _file_hash(draft_path)
            and receipt.get("readiness_report_sha256")
            == _file_hash(readiness_path)
            and receipt.get("runtime_attestation_sha256")
            == _file_hash(attestation_path)
            and receipt.get("authorization_transitions_consumed") == 2
            and receipt.get("actual_pipeline_action_executed") is False
            and receipt.get("distribution_build_started") is False
            and receipt.get("install_started") is False
            and receipt.get("lab_certification_started") is False
            and receipt.get("linkage_project_started") is False
            and receipt.get("main_project_started") is False
            and receipt.get("target_runtime_install_started") is False
            and authorization.get("status") == "GRANTED"
            and authorization.get("authorization_class")
            == "REPAIR_EXECUTION_AUTHORIZATION"
            and authorization.get("driver_execution_authorized") is False
            and authorization.get("max_driver_transitions") == 0
            and authorization.get("granted_preparation_transitions") == 2
            and authorization.get("may_auto_advance") is False
            and authorization.get("scope", {}).get("workpack_ids") == []
            and {
                "LAB_TOOL_RELEASE_EXECUTION",
                "PIPELINE_ACTION_EXECUTION",
                "LAB_CERTIFICATION",
                "LINKAGE_PROJECT_BOOTSTRAP",
                "MAIN_PROJECT_BOOTSTRAP",
                "TARGET_RUNTIME_INSTALLATION",
                "REAL_TARGET_INSTALL",
            }.issubset(forbidden)
            and claimed_runtime_hash == _json_hash(runtime_material)
            and runtime.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_REPAIR_PREPARATION"
            and runtime.get("runtime_verification_status")
            == "PASS_REVERIFIED_PIPELINE_ACTION_PREFLIGHT"
            and runtime.get("completed_workpack_ids") == expected_workpacks
            and runtime.get("completed_pipeline_action_ids") == []
            and runtime.get("active_workpack_id") is None
            and runtime.get("active_pipeline_action_id") is None
            and runtime.get("side_effects_allowed") is False
            and manifest.get("status") == "READY_NOT_EXECUTED"
            and manifest.get("execution_unit_kind") == "PIPELINE_ACTION"
            and manifest.get("pipeline_action_id") == "LAB_TOOL_RELEASE_LOCKED"
            and manifest.get("workpack_id") is None
            and manifest.get("execution_started") is False
            and manifest.get("distribution_build_started") is False
            and manifest.get("install_performed") is False
            and draft.get("status") == "DRAFT_READY_NOT_GRANTED"
            and draft.get("grantable") is False
            and draft.get("execution_authorized") is False
            and draft.get("driver_execution_authorized") is False
            and draft.get("max_transitions") == 0
            and draft.get("granted_transitions") == 0
            and draft.get("scope", {}).get("pipeline_action_ids")
            == ["LAB_TOOL_RELEASE_LOCKED"]
            and draft.get("scope", {}).get("workpack_ids") == []
            and len(manifest_items) == 1
            and resolve_ref(manifest_items[0].get("ref")) == manifest_path.resolve()
            and manifest_items[0].get("sha256") == _file_hash(manifest_path)
            and readiness.get("status")
            == "READY_FOR_PACKAGE_BUILD_AUTHORIZATION_NOT_GRANTED"
            and readiness.get("technical_preparation_status") == "PASS"
            and readiness.get("preparation_blocking_findings") == []
            and readiness.get("target_pipeline_action_executed") is False
            and readiness.get("execution_or_build_started") is False
            and readiness.get("release_action_writes_performed") is False
            and attestation.get("status")
            == "PASS_REVERIFIED_PIPELINE_ACTION_PREFLIGHT"
            and attestation.get("actual_pipeline_action_executed") is False
            and attestation.get("target_distribution_build_started") is False
            and not target_output.exists()
            and not (execution_root / "project_start_packages/linkage_review").exists()
            and not (execution_root / "project_start_packages/main_build").exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_lab_tool_release_materialization(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept one receipt-bound Lab tool release stopped before Linkage."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        control = execution_root / "control_plane"
        descriptor_path = (
            control / "PROGRAM_DRIVER_DESCRIPTOR_AFTER_LAB_TOOL_RELEASE.json"
        )
        receipt_path = control / "LAB_TOOL_RELEASE_LOCKED_COMPLETION_RECEIPT.json"
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        authorization_path = resolve_ref(receipt.get("authorization_ref"))
        runtime_path = resolve_ref(receipt.get("runtime_state_ref"))
        manifest_path = resolve_ref(receipt.get("manifest_ref"))
        action_result_path = resolve_ref(receipt.get("action_result_ref"))
        archive_path = resolve_ref(receipt.get("archive_ref"))
        distribution_path = resolve_ref(receipt.get("distribution_descriptor_ref"))
        interface_path = resolve_ref(receipt.get("conformance_interface_ref"))
        independent_path = resolve_ref(receipt.get("independent_validation_receipt_ref"))
        result_path = resolve_ref(receipt.get("lab_tool_release_result_ref"))
        promotion_path = resolve_ref(receipt.get("promotion_ref"))
        transition_ledger_path = resolve_ref(receipt.get("transition_ledger_ref"))
        promotion_ledger_path = resolve_ref(receipt.get("promotion_ledger_ref"))
        authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        action_result = json.loads(action_result_path.read_text(encoding="utf-8"))
        distribution = json.loads(distribution_path.read_text(encoding="utf-8"))
        interface = json.loads(interface_path.read_text(encoding="utf-8"))
        independent = json.loads(independent_path.read_text(encoding="utf-8"))
        result = json.loads(result_path.read_text(encoding="utf-8"))
        promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
        source_path = resolve_ref(descriptor.get("driver_source_ref"))
        entrypoint_path = resolve_ref(descriptor.get("driver_entrypoint_ref"))
        prior_descriptor_path = resolve_ref(descriptor.get("prior_descriptor_ref"))
        forbidden = set(authorization.get("forbidden_actions", []))
        expected_workpacks = [
            "LAB-PROTOCOL",
            "LAB-CLI",
            "LAB-FIXTURES",
            "LAB-SELFTEST",
        ]
        candidate_hash = _candidate_tree_hash(candidate_root)
        authorization_id = authorization.get("authorization_id")
        archive_hash = _file_hash(archive_path)
        runtime_material = dict(runtime)
        claimed_runtime_hash = runtime_material.pop("state_hash", None)
        return bool(
            descriptor.get("status")
            == "LAB_TOOL_RELEASE_LOCKED_PASS_STOPPED_BEFORE_LINKAGE_BOOTSTRAP"
            and descriptor.get("candidate_content_sha256") == candidate_hash
            and descriptor.get("driver_version") == "0.3.0"
            and descriptor.get("driver_source_sha256") == _file_hash(source_path)
            and descriptor.get("driver_entrypoint_sha256")
            == _file_hash(entrypoint_path)
            and descriptor.get("prior_descriptor_sha256")
            == _file_hash(prior_descriptor_path)
            and descriptor.get("runtime_state_sha256") == _file_hash(runtime_path)
            and descriptor.get("completion_receipt_sha256")
            == _file_hash(receipt_path)
            and resolve_ref(descriptor.get("completion_receipt_ref"))
            == receipt_path.resolve()
            and descriptor.get("archive_sha256") == archive_hash
            and descriptor.get("conformance_interface_sha256")
            == _file_hash(interface_path)
            and descriptor.get("completed_workpack_ids") == expected_workpacks
            and descriptor.get("completed_pipeline_action_ids")
            == ["LAB_TOOL_RELEASE_LOCKED"]
            and descriptor.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and descriptor.get("lab_tool_release_started") is True
            and descriptor.get("next_node_id") == "LINKAGE_BOOTSTRAP"
            and descriptor.get("next_node_activated") is False
            and descriptor.get("lab_certification_started") is False
            and descriptor.get("linkage_project_started") is False
            and descriptor.get("main_project_started") is False
            and descriptor.get("install_started") is False
            and descriptor.get("target_runtime_install_started") is False
            and descriptor.get("real_target_install_started") is False
            and receipt.get("status")
            == "LAB_TOOL_RELEASE_LOCKED_COMPLETE_STOPPED_BEFORE_LINKAGE_BOOTSTRAP"
            and receipt.get("candidate_content_sha256") == candidate_hash
            and receipt.get("authorization_sha256") == _file_hash(authorization_path)
            and receipt.get("runtime_state_sha256") == _file_hash(runtime_path)
            and receipt.get("manifest_sha256") == _file_hash(manifest_path)
            and receipt.get("action_result_sha256") == _file_hash(action_result_path)
            and receipt.get("archive_sha256") == archive_hash
            and receipt.get("distribution_descriptor_sha256")
            == _file_hash(distribution_path)
            and receipt.get("conformance_interface_sha256")
            == _file_hash(interface_path)
            and receipt.get("independent_validation_receipt_sha256")
            == _file_hash(independent_path)
            and receipt.get("lab_tool_release_result_sha256")
            == _file_hash(result_path)
            and receipt.get("promotion_sha256") == _file_hash(promotion_path)
            and receipt.get("transition_ledger_sha256")
            == _file_hash(transition_ledger_path)
            and receipt.get("promotion_ledger_sha256")
            == _file_hash(promotion_ledger_path)
            and receipt.get("authorization_transitions_consumed") == 1
            and receipt.get("completed_pipeline_action_ids")
            == ["LAB_TOOL_RELEASE_LOCKED"]
            and receipt.get("command_exit_code") == 0
            and receipt.get("independent_validation_exit_code") == 0
            and receipt.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and receipt.get("install_started") is False
            and receipt.get("lab_certification_started") is False
            and receipt.get("linkage_project_started") is False
            and receipt.get("main_project_started") is False
            and receipt.get("target_runtime_install_started") is False
            and authorization.get("status") == "GRANTED"
            and authorization.get("authorization_class")
            == "PACKAGE_BUILD_AUTHORIZATION"
            and authorization.get("max_transitions") == 1
            and authorization.get("granted_transitions") == 1
            and authorization.get("may_auto_advance") is False
            and authorization.get("real_target_install_allowed") is False
            and authorization.get("scope", {}).get("dag_node_ids")
            == ["LAB_TOOL_RELEASE_LOCKED"]
            and authorization.get("scope", {}).get("pipeline_action_ids")
            == ["LAB_TOOL_RELEASE_LOCKED"]
            and authorization.get("scope", {}).get("workpack_ids") == []
            and {
                "INSTALL",
                "LAB_CERTIFICATION",
                "LINKAGE_PROJECT_BOOTSTRAP",
                "MAIN_PROJECT_BOOTSTRAP",
                "OTHER_PIPELINE_ACTION_EXECUTION",
                "TARGET_RUNTIME_INSTALLATION",
                "REAL_TARGET_INSTALL",
                "WORKPACK_EXECUTION",
            }.issubset(forbidden)
            and claimed_runtime_hash == _json_hash(runtime_material)
            and runtime.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and runtime.get("completed_workpack_ids") == expected_workpacks
            and runtime.get("completed_pipeline_action_ids")
            == ["LAB_TOOL_RELEASE_LOCKED"]
            and runtime.get("authorization_consumptions", {}).get(authorization_id)
            == 1
            and runtime.get("active_workpack_id") is None
            and runtime.get("active_pipeline_action_id") is None
            and runtime.get("active_dag_node") is None
            and runtime.get("side_effects_allowed") is False
            and runtime.get("recovery", {}).get("required") is False
            and manifest.get("status") == "READY_NOT_EXECUTED"
            and manifest.get("execution_unit_kind") == "PIPELINE_ACTION"
            and manifest.get("pipeline_action_id") == "LAB_TOOL_RELEASE_LOCKED"
            and manifest.get("workpack_id") is None
            and action_result.get("status") == "PASS"
            and action_result.get("pipeline_action_id") == "LAB_TOOL_RELEASE_LOCKED"
            and action_result.get("distribution_sha256") == archive_hash
            and action_result.get("release_descriptor_sha256")
            == _file_hash(distribution_path)
            and action_result.get("conformance_interface_sha256")
            == _file_hash(interface_path)
            and distribution.get("pipeline_action_id") == "LAB_TOOL_RELEASE_LOCKED"
            and distribution.get("archive_sha256") == archive_hash
            and distribution.get("install_performed") is False
            and interface.get("interface_status")
            == "LAB_TOOL_DISTRIBUTION_HASH_BOUND"
            and interface.get("lab_tool_distribution_sha256") == archive_hash
            and independent.get("status") == "PASS"
            and independent.get("pipeline_action_id") == "LAB_TOOL_RELEASE_LOCKED"
            and independent.get("archive_sha256") == archive_hash
            and independent.get("command_exit_code") == 0
            and independent.get("independent_validation_exit_code") == 0
            and independent.get("install_performed") is False
            and result.get("status") == "PASS"
            and result.get("success_gate") == "LAB_TOOL_RELEASE_LOCKED_PASS"
            and result.get("pipeline_action_id") == "LAB_TOOL_RELEASE_LOCKED"
            and result.get("authorization_transitions_consumed") == 1
            and result.get("archive_sha256") == archive_hash
            and promotion.get("status")
            == "PROMOTED_STOPPED_BEFORE_LINKAGE_BOOTSTRAP"
            and promotion.get("next_node_id") == "LINKAGE_BOOTSTRAP"
            and promotion.get("next_node_activated") is False
            and promotion.get("linkage_project_started") is False
            and promotion.get("main_project_started") is False
            and promotion.get("install_started") is False
            and not (execution_root / "project_start_packages/linkage_review").exists()
            and not (execution_root / "project_start_packages/main_build").exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_main_materialization_preparation(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept Hash-bound Main G0 preparation without executing its Workpack."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        def read_json(path: Path) -> Mapping[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError(f"expected object: {path}")
            return value

        def bound(document: Mapping[str, Any], ref_key: str, hash_key: str) -> bool:
            path = resolve_ref(document.get(ref_key))
            return bool(path.is_file() and document.get(hash_key) == _file_hash(path))

        control = execution_root / "control_plane"
        evidence = execution_root / "evidence"
        snapshot_path = (
            control
            / "history/MAIN_EXECUTION_PACKAGE_MATERIALIZATION_PREPARATION.preparation_snapshot.json"
        )
        authorization_path = (
            control / "MAIN_EXECUTION_PACKAGE_MATERIALIZATION_PREPARATION_AUTHORIZATION.json"
        )
        baseline_path = control / "MAIN_SHARED_BASELINE_LOCK.json"
        schema_path = (
            execution_root
            / "planned_executors/schemas/MAIN_MATERIALIZATION_AGENT_OUTPUT.schema.json"
        )
        manifest_path = (
            execution_root
            / "planned_executors/manifests/"
            "WP-vscdsl-video-prompt-harness-G0-001.resolved-command.json"
        )
        descriptor_path = control / "MAIN_CODEX_EXECUTOR_DESCRIPTOR.json"
        boundary_path = (
            evidence
            / "main-materialization-preparation/"
            "MAIN_EXECUTION_PACKAGE_MATERIALIZATION_PREPARATION_BOUNDARY_ATTESTATION.json"
        )
        readiness_path = (
            control
            / "MAIN_EXECUTION_PACKAGE_MATERIALIZATION_PREPARATION_READINESS_REPORT.json"
        )
        draft_path = (
            control
            / "MAIN_EXECUTION_PACKAGE_MATERIALIZATION_EXECUTION_AUTHORIZATION_DRAFT.json"
        )
        receipt_path = (
            control / "MAIN_EXECUTION_PACKAGE_MATERIALIZATION_PREPARATION_RECEIPT.json"
        )
        runtime_path = control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json"
        state_path = control / "CONTROL_PLANE_STATE.json"

        snapshot = read_json(snapshot_path)
        authorization = read_json(authorization_path)
        baseline = read_json(baseline_path)
        schema = read_json(schema_path)
        manifest = read_json(manifest_path)
        descriptor = read_json(descriptor_path)
        boundary = read_json(boundary_path)
        readiness = read_json(readiness_path)
        draft = read_json(draft_path)
        receipt = read_json(receipt_path)
        runtime = read_json(runtime_path)
        state = read_json(state_path)

        candidate_hash = _candidate_tree_hash(candidate_root)
        expected_candidate_hash = (
            "5ee5d5a9d6312c2fe3bf2c3fbf535765321b1cd1f72d610b62188d6b4de4112d"
        )
        expected_runtime_hash = (
            "c8407d75e1ad28293a05a905693291e80fab8dad2a9c7f2111c8e72f4e39fcf3"
        )
        expected_runtime_file_hash = (
            "c016966e72c1df97cb47eec49c53d7a91792e4ab44807654289b08e04ba0b44d"
        )
        expected_lab_distribution_hash = (
            "54f8cabe3595b3b9be650367b060cf5aa986494cbf15989565103c8bf5a319aa"
        )
        expected_linkage_distribution_hash = (
            "6c84e325051840e34cfb80333bc4f461233a33bbde0fc0732f6e1ca68fd4fa1b"
        )
        expected_source_hash = (
            "2f55afd156b3391c9021ebcf9b622d7d74c1ee18b1500356c3a3c89e622e046c"
        )
        workpack_id = "WP-vscdsl-video-prompt-harness-G0-001"
        required_authorization_text = (
            "授权 MAIN_EXECUTION_PACKAGE_MATERIALIZATION_EXECUTION，仅允许 Driver 执行一次 "
            "Hash 绑定的 WP-vscdsl-video-prompt-harness-G0-001 Workpack，创建 Main "
            "execution package repository 并生成 MAIN_EXECUTION_PACKAGE_MATERIALIZED 结果及"
            "独立验证证据；不授权 MAIN_EXECUTION_PACKAGE_VALIDATED、MB-G0 或任何后续 Main "
            "Workpack、认证、其他 Workpack、其他 Pipeline Action 或任何安装。"
        )
        preparation_scope = authorization.get("scope", {})
        draft_scope = draft.get("scope", {})
        source = baseline.get("candidate_main_source", {})
        source_root = resolve_ref(source.get("source_root"))
        boundary_checks = boundary.get("checks", [])
        runtime_material = dict(runtime)
        claimed_runtime_hash = runtime_material.pop("state_hash", None)
        expected_workpacks = [
            "LAB-PROTOCOL",
            "LAB-CLI",
            "LAB-FIXTURES",
            "LAB-SELFTEST",
            "LINK-PROTOCOL",
            "LINK-CLI",
            "LINK-SELFTEST",
        ]
        main_state = state.get("main_materialization_preparation", {})
        schema_properties = schema.get("properties", {})

        return bool(
            candidate_hash == expected_candidate_hash
            and snapshot.get("status")
            == "HASH_BOUND_MAIN_MATERIALIZATION_PREPARATION_SNAPSHOT"
            and snapshot.get("authorization_text")
            == "授权：\nMAIN_EXECUTION_PACKAGE_MATERIALIZATION_PREPARATION"
            and snapshot.get("candidate_content_sha256") == candidate_hash
            and snapshot.get("runtime_state_revision") == 26
            and snapshot.get("runtime_state_hash") == expected_runtime_hash
            and snapshot.get("runtime_state_file_sha256")
            == expected_runtime_file_hash
            and snapshot.get("main_candidate_source_tree_sha256")
            == expected_source_hash
            and snapshot.get("main_candidate_source_file_count") == 36
            and snapshot.get("main_repository_existed") is False
            and snapshot.get("main_execution_evidence_existed") is False
            and snapshot.get("workpack_execution_started") is False
            and authorization.get("status") == "GRANTED"
            and authorization.get("authorization_class")
            == "PREPARATION_AUTHORIZATION"
            and authorization.get("candidate_content_sha256") == candidate_hash
            and authorization.get("max_driver_transitions") == 0
            and authorization.get("driver_execution_authorized") is False
            and authorization.get("workpack_execution_authorized") is False
            and authorization.get("authorization_scope_sha256")
            == _json_hash(preparation_scope)
            and preparation_scope.get("dag_node_ids")
            == ["MAIN_EXECUTION_PACKAGE_MATERIALIZED"]
            and preparation_scope.get("project_ids") == ["MAIN_HARNESS_BUILD"]
            and preparation_scope.get("execution_modes") == ["PREPARATION_ONLY"]
            and preparation_scope.get("workpack_ids") == []
            and preparation_scope.get("pipeline_action_ids") == []
            and {
                "DRIVER_START",
                "WORKPACK_EXECUTION",
                "MAIN_EXECUTION_PACKAGE_MATERIALIZED_EXECUTION",
                "MAIN_EXECUTION_PACKAGE_VALIDATION",
                "INSTALL",
            }.issubset(set(authorization.get("forbidden_actions", [])))
            and bound(
                authorization,
                "based_on_preparation_snapshot_ref",
                "based_on_preparation_snapshot_sha256",
            )
            and baseline.get("status")
            == "LOCKED_FOR_MAIN_MATERIALIZATION_PREPARATION"
            and baseline.get("candidate_content_sha256") == candidate_hash
            and source.get("tree_sha256") == expected_source_hash
            and source.get("file_count") == 36
            and source_root.is_dir()
            and baseline.get("main_materialization_contract", {}).get("workpack_id")
            == workpack_id
            and baseline.get("main_materialization_contract", {}).get(
                "authorization_class"
            )
            == "PROJECT_BOOTSTRAP_AUTHORIZATION"
            and baseline.get("lab_release_bindings", {}).get("distribution_sha256")
            == expected_lab_distribution_hash
            and baseline.get("linkage_release_bindings", {}).get(
                "distribution_sha256"
            )
            == expected_linkage_distribution_hash
            and bound(baseline, "authorization_ref", "authorization_sha256")
            and bound(baseline, "snapshot_ref", "snapshot_sha256")
            and schema.get("additionalProperties") is False
            and set(schema.get("required", [])) == set(schema_properties)
            and schema_properties.get("workpack_id", {}).get("const") == workpack_id
            and schema_properties.get("status", {}).get("const") == "PASS"
            and schema_properties.get("blocking_findings", {}).get("maxItems") == 0
            and manifest.get("status") == "READY_NOT_EXECUTED"
            and manifest.get("workpack_id") == workpack_id
            and manifest.get("candidate_content_sha256") == candidate_hash
            and manifest.get("authorization_required") is True
            and manifest.get("auto_execute") is False
            and manifest.get("execution_started") is False
            and manifest.get("shell") is False
            and manifest.get("executable_sha256") == _file_hash(executable_path)
            and manifest.get("output_schema_sha256") == _file_hash(schema_path)
            and manifest.get("main_shared_baseline_sha256")
            == _file_hash(baseline_path)
            and manifest.get("lab_tool_distribution_sha256")
            == expected_lab_distribution_hash
            and manifest.get("linkage_tool_distribution_sha256")
            == expected_linkage_distribution_hash
            and "{attempt_id}" in str(manifest.get("stdout_template_abs"))
            and "{attempt_id}" in str(manifest.get("stderr_template_abs"))
            and descriptor.get("status")
            == "PREPARED_VERIFIED_NOT_INVOKED_FOR_MAIN_MATERIALIZATION"
            and descriptor.get("command_manifest_sha256") == _file_hash(manifest_path)
            and descriptor.get("output_schema_sha256") == _file_hash(schema_path)
            and descriptor.get("shared_baseline_sha256") == _file_hash(baseline_path)
            and descriptor.get("runtime_state_revision") == 26
            and descriptor.get("runtime_state_hash") == expected_runtime_hash
            and descriptor.get("runtime_state_file_sha256")
            == expected_runtime_file_hash
            and descriptor.get("agent_invoked_for_main_materialization") is False
            and descriptor.get("main_materialization_started") is False
            and descriptor.get("main_repository_status") == "NOT_CREATED"
            and boundary.get("status")
            == "PASS_PREPARATION_ONLY_NO_MAIN_EXECUTION"
            and boundary.get("blocking_findings") == []
            and len(boundary_checks) == 10
            and all(check.get("status") == "PASS" for check in boundary_checks)
            and boundary.get("main_repository_exists") is False
            and boundary.get("main_materialization_execution_started") is False
            and boundary.get("workpack_execution_started") is False
            and readiness.get("status")
            == "READY_FOR_EXPLICIT_MAIN_MATERIALIZATION_EXECUTION_AUTHORIZATION_NOT_GRANTED"
            and readiness.get("technical_preparation_status") == "PASS"
            and readiness.get("preparation_blocking_findings") == []
            and readiness.get("required_next_authorization_text")
            == required_authorization_text
            and readiness.get("main_repository_created") is False
            and readiness.get("workpack_execution_started") is False
            and draft.get("status") == "DRAFT_READY_NOT_GRANTED"
            and draft.get("authorization_class")
            == "PROJECT_BOOTSTRAP_AUTHORIZATION"
            and draft.get("grantable") is False
            and draft.get("execution_authorized") is False
            and draft.get("driver_execution_authorized") is False
            and draft.get("main_materialization_authorized") is False
            and draft.get("max_transitions") == 0
            and draft.get("granted_transitions") == 0
            and draft.get("proposed_max_transitions") == 1
            and draft.get("authorization_scope_sha256") == _json_hash(draft_scope)
            and draft_scope.get("dag_node_ids")
            == ["MAIN_EXECUTION_PACKAGE_MATERIALIZED"]
            and draft_scope.get("project_ids") == ["MAIN_HARNESS_BUILD"]
            and draft_scope.get("workpack_ids") == [workpack_id]
            and draft_scope.get("execution_modes") == ["WORKPACK_EXECUTION"]
            and draft.get("required_authorization_text")
            == required_authorization_text
            and "INSTALL" in draft.get("forbidden_actions", [])
            and receipt.get("status")
            == "COMPLETE_READY_FOR_EXPLICIT_MAIN_MATERIALIZATION_EXECUTION_AUTHORIZATION"
            and receipt.get("authorization_transitions_consumed") == 0
            and receipt.get("runtime_state_revision") == 26
            and receipt.get("runtime_state_hash") == expected_runtime_hash
            and receipt.get("runtime_state_file_sha256")
            == expected_runtime_file_hash
            and receipt.get("main_repository_created") is False
            and receipt.get("main_materialization_execution_started") is False
            and receipt.get("workpack_execution_started") is False
            and claimed_runtime_hash == _json_hash(runtime_material)
            and _file_hash(runtime_path) == expected_runtime_file_hash
            and runtime.get("state_revision") == 26
            and runtime.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and runtime.get("completed_workpack_ids") == expected_workpacks
            and runtime.get("completed_pipeline_action_ids")
            == ["LAB_TOOL_RELEASE_LOCKED", "LINKAGE_TOOL_RELEASE_LOCKED"]
            and runtime.get("active_workpack_id") is None
            and runtime.get("active_pipeline_action_id") is None
            and runtime.get("active_dag_node") is None
            and runtime.get("side_effects_allowed") is False
            and state.get("state")
            == "MAIN_EXECUTION_PACKAGE_MATERIALIZATION_PREPARED_WAITING_EXECUTION_AUTHORIZATION"
            and state.get("highest_completed_external_gate")
            == "LINKAGE_TOOL_RELEASE_LOCKED_PASS"
            and state.get("open_blocker_codes")
            == ["MAIN_EXECUTION_PACKAGE_MATERIALIZATION_EXECUTION_AUTHORIZATION_REQUIRED"]
            and state.get("next_eligible_action")
            == "OBTAIN_MAIN_EXECUTION_PACKAGE_MATERIALIZATION_EXECUTION_AUTHORIZATION"
            and state.get("projects", {}).get("MAIN_HARNESS_BUILD")
            == "MATERIALIZATION_PREPARED_NOT_AUTHORIZED"
            and state.get("main_materialization_started") is False
            and state.get("active_dag_node") is None
            and state.get("install_started") is False
            and main_state.get("status") == "PASS_PREPARED_NOT_AUTHORIZED"
            and bound(main_state, "authorization_ref", "authorization_sha256")
            and bound(main_state, "shared_baseline_ref", "shared_baseline_sha256")
            and bound(main_state, "manifest_ref", "manifest_sha256")
            and bound(main_state, "output_schema_ref", "output_schema_sha256")
            and bound(main_state, "descriptor_ref", "descriptor_sha256")
            and bound(main_state, "boundary_attestation_ref", "boundary_attestation_sha256")
            and bound(main_state, "readiness_report_ref", "readiness_report_sha256")
            and bound(main_state, "authorization_draft_ref", "authorization_draft_sha256")
            and bound(main_state, "receipt_ref", "receipt_sha256")
            and bound(descriptor, "command_manifest_ref", "command_manifest_sha256")
            and bound(descriptor, "output_schema_ref", "output_schema_sha256")
            and bound(descriptor, "shared_baseline_ref", "shared_baseline_sha256")
            and bound(boundary, "manifest_ref", "manifest_sha256")
            and bound(boundary, "output_schema_ref", "output_schema_sha256")
            and bound(boundary, "shared_baseline_ref", "shared_baseline_sha256")
            and bound(readiness, "manifest_ref", "manifest_sha256")
            and bound(readiness, "output_schema_ref", "output_schema_sha256")
            and bound(readiness, "shared_baseline_ref", "shared_baseline_sha256")
            and bound(draft, "preparation_readiness_ref", "preparation_readiness_sha256")
            and bound(draft, "shared_baseline_ref", "shared_baseline_sha256")
            and bound(receipt, "authorization_ref", "authorization_sha256")
            and bound(receipt, "boundary_attestation_ref", "boundary_attestation_sha256")
            and bound(receipt, "readiness_report_ref", "readiness_report_sha256")
            and bound(receipt, "main_execution_authorization_draft_ref", "main_execution_authorization_draft_sha256")
            and bound(receipt, "manifest_ref", "manifest_sha256")
            and bound(receipt, "output_schema_ref", "output_schema_sha256")
            and bound(receipt, "shared_baseline_ref", "shared_baseline_sha256")
            and not (execution_root / "project_start_packages/main_build").exists()
            and not (
                evidence / "engineering_dag/MAIN_EXECUTION_PACKAGE_MATERIALIZED"
            ).exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_main_p4_local_closure_completion(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
    *,
    allow_release_preparation_state: bool = False,
) -> bool:
    """Accept only the receipt-bound stdin-isolated MB-P4 successful retry."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    if command.get("command_id") not in {
        "ROOT-CODEX-CODING",
        "MB-CODEX-CODING",
        "LINK-CODEX-CODING",
        "LAB-CODEX-CODING",
    }:
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        def read_json(path: Path) -> Mapping[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError(f"expected object: {path}")
            return value

        def bound(document: Mapping[str, Any], ref_key: str, hash_key: str) -> bool:
            path = resolve_ref(document.get(ref_key))
            return bool(path.is_file() and document.get(hash_key) == _file_hash(path))

        def repository_hash(root: Path) -> tuple[str, int]:
            digest = hashlib.sha256()
            count = 0
            for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
                if (
                    not path.is_file()
                    or ".git" in path.parts
                    or "__pycache__" in path.parts
                    or path.suffix in {".pyc", ".pyo"}
                ):
                    continue
                digest.update(path.relative_to(root).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(_file_hash(path).encode("ascii"))
                digest.update(b"\n")
                count += 1
            return digest.hexdigest(), count

        control = execution_root / "control_plane"
        evidence = execution_root / "evidence"
        repository = execution_root / "project_start_packages/main_build/repository"
        completion_path = control / "MAIN_P4_LOCAL_CLOSURE_COMPLETION_RECEIPT.json"
        descriptor_path = control / (
            "MAIN_P4_LOCAL_CLOSURE_EXECUTOR_DESCRIPTOR_AFTER_SUCCESSFUL_RETRY.json"
        )
        authorization_path = control / "MAIN_P4_STDIN_ISOLATED_RETRY_AUTHORIZATION.json"
        repair_receipt_path = (
            control / "MAIN_P4_STDIN_ISOLATION_REPAIR_REVERIFICATION_RECEIPT.json"
        )
        independent_path = evidence / (
            "project_workpacks/MAIN_HARNESS_BUILD/MB-P4/"
            "INDEPENDENT_RETRY_VALIDATION_RECEIPT.json"
        )
        workpack_path = evidence / (
            "project_workpacks/MAIN_HARNESS_BUILD/MB-P4/WORKPACK_RESULT.json"
        )
        result_path = evidence / "engineering_dag/MAIN_P4_LOCAL_CLOSURE.result.json"
        promotion_path = evidence / (
            "engineering_dag/MAIN_P4_LOCAL_CLOSURE.promotion.json"
        )
        manifest_path = execution_root / (
            "planned_executors/manifests/"
            "MB-P4.stdin-isolated-retry.resolved-command.json"
        )
        runtime_path = control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json"
        state_path = control / "CONTROL_PLANE_STATE.json"

        completion = read_json(completion_path)
        descriptor = read_json(descriptor_path)
        authorization = read_json(authorization_path)
        repair_receipt = read_json(repair_receipt_path)
        independent = read_json(independent_path)
        workpack = read_json(workpack_path)
        result = read_json(result_path)
        promotion = read_json(promotion_path)
        manifest = read_json(manifest_path)
        runtime = read_json(runtime_path)
        state = read_json(state_path)
        scope = authorization.get("scope", {})
        runtime_material = dict(runtime)
        runtime_hash = runtime_material.pop("state_hash", None)
        expected_candidate = (
            "5ee5d5a9d6312c2fe3bf2c3fbf535765321b1cd1f72d610b62188d6b4de4112d"
        )
        expected_repository = (
            "0c489e2a99030545995153b4325b816f93dd8f5e5d98ad4ac7b1082aa55aecc3",
            122,
        )
        expected_workpacks = [
            "LAB-PROTOCOL",
            "LAB-CLI",
            "LAB-FIXTURES",
            "LAB-SELFTEST",
            "LINK-PROTOCOL",
            "LINK-CLI",
            "LINK-SELFTEST",
            "WP-vscdsl-video-prompt-harness-G0-001",
            "MB-G0",
            "MB-P1",
            "MB-P2",
            "MB-P3",
            "MB-P4",
        ]
        expected_control_state = (
            "RELEASE_PIPELINE_HANDOFF_PREPARED_WAITING_ENTRY_EXECUTION_AUTHORIZATION"
            if allow_release_preparation_state
            else "MAIN_P4_LOCAL_CLOSURE_PASS_WAITING_RELEASE_PIPELINE_HANDOFF_PREPARATION_AUTHORIZATION"
        )
        expected_blockers = (
            ["RELEASE_PIPELINE_HANDOFF_ENTRY_EXECUTION_AUTHORIZATION_REQUIRED"]
            if allow_release_preparation_state
            else ["RELEASE_PIPELINE_HANDOFF_PREPARATION_AUTHORIZATION_REQUIRED"]
        )
        expected_next_action = (
            "OBTAIN_RELEASE_PIPELINE_HANDOFF_ENTRY_EXECUTION_AUTHORIZATION"
            if allow_release_preparation_state
            else "OBTAIN_RELEASE_PIPELINE_HANDOFF_PREPARATION_AUTHORIZATION"
        )

        return bool(
            _candidate_tree_hash(candidate_root) == expected_candidate
            and expected_launcher.is_file()
            and _file_hash(expected_launcher)
            == "d3c62048f066d3407fd822a7e445772e549e16f4f657314f33100bf63d6340a6"
            and completion.get("status")
            == "MAIN_P4_LOCAL_CLOSURE_COMPLETE_STOPPED_BEFORE_RELEASE_PIPELINE_HANDOFF"
            and completion.get("candidate_content_sha256") == expected_candidate
            and completion.get("attempt_id")
            == "ATTEMPT-93CB84478F1C4861AF973E9844C1816F"
            and completion.get("completed_workpack_ids") == ["MB-P4"]
            and completion.get("authorization_transitions_consumed") == 1
            and completion.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and completion.get("repository_content_sha256") == expected_repository[0]
            and completion.get("repository_content_file_count") == expected_repository[1]
            and completion.get("next_node_activated") is False
            and completion.get("release_pipeline_handoff_started") is False
            and completion.get("install_started") is False
            and bound(completion, "authorization_ref", "authorization_sha256")
            and bound(completion, "executor_descriptor_ref", "executor_descriptor_sha256")
            and bound(completion, "independent_validation_ref", "independent_validation_sha256")
            and bound(completion, "manifest_ref", "manifest_sha256")
            and bound(completion, "promotion_ref", "promotion_sha256")
            and bound(completion, "result_ref", "result_sha256")
            and bound(completion, "workpack_result_ref", "workpack_result_sha256")
            and bound(completion, "previous_failure_receipt_ref", "previous_failure_receipt_sha256")
            and descriptor.get("status")
            == "MAIN_P4_LOCAL_CLOSURE_COMPLETE_STDIN_ISOLATED_RETRY_VALIDATED_STOPPED_BEFORE_RELEASE"
            and descriptor.get("repository_content_sha256") == expected_repository[0]
            and descriptor.get("repository_content_file_count") == expected_repository[1]
            and descriptor.get("next_node_activated") is False
            and descriptor.get("release_pipeline_handoff_started") is False
            and bound(descriptor, "driver_entrypoint_ref", "driver_entrypoint_sha256")
            and bound(descriptor, "driver_source_ref", "driver_source_sha256")
            and bound(descriptor, "independent_validation_ref", "independent_validation_sha256")
            and authorization.get("status") == "GRANTED"
            and authorization.get("authorization_id")
            == "AUTH-VSCDSL-MAIN-P4-STDIN-ISOLATED-RETRY-V03-001"
            and authorization.get("authorization_scope_sha256") == _json_hash(scope)
            and authorization.get("max_transitions") == 1
            and authorization.get("granted_transitions") == 1
            and scope.get("dag_node_ids") == ["MAIN_P4_LOCAL_CLOSURE"]
            and scope.get("workpack_ids") == ["MB-P4"]
            and scope.get("pipeline_action_ids") == []
            and bound(authorization, "based_on_repair_receipt_ref", "based_on_repair_receipt_sha256")
            and bound(authorization, "driver_entrypoint_ref", "driver_entrypoint_sha256")
            and bound(authorization, "driver_source_ref", "driver_source_sha256")
            and repair_receipt.get("status")
            == "COMPLETE_READY_FOR_SINGLE_HASH_BOUND_MB_P4_STDIN_ISOLATED_RETRY"
            and repair_receipt.get("authorization_transitions_consumed_during_repair") == 0
            and repair_receipt.get("main_repository_changed_during_repair") is False
            and bound(repair_receipt, "descriptor_ref", "descriptor_sha256")
            and bound(repair_receipt, "manifest_ref", "manifest_sha256")
            and manifest.get("workpack_id") == "MB-P4"
            and manifest.get("stdin_isolation") == "SUBPROCESS_DEVNULL_REQUIRED"
            and manifest.get("recursive_program_driver_invocation_forbidden") is True
            and manifest.get("require_changed_files_match_repository_delta") is True
            and manifest.get("require_nonempty_changed_files") is True
            and independent.get("status") == "PASS"
            and independent.get("test_count") == 41
            and independent.get("agent_changed_files_count") == 105
            and independent.get("repository_content_sha256") == expected_repository[0]
            and independent.get("repository_content_file_count") == expected_repository[1]
            and independent.get("stdin_isolation_verified") is True
            and independent.get("stdout_contains_recursive_program_driver_command") is False
            and independent.get("release_pipeline_handoff_started") is False
            and bound(independent, "agent_result_ref", "agent_result_sha256")
            and bound(independent, "git_delivery_inventory_ref", "git_delivery_inventory_sha256")
            and bound(independent, "current_pointer_ref", "current_pointer_sha256")
            and bound(independent, "provenance_ref", "provenance_sha256")
            and bound(independent, "resource_manifest_ref", "resource_manifest_sha256")
            and workpack.get("status") == "PASS"
            and workpack.get("authorization_transitions_consumed") == 1
            and bound(workpack, "independent_validation_ref", "independent_validation_sha256")
            and result.get("status") == "PASS"
            and result.get("success_gate") == "MAIN_P4_LOCAL_CLOSURE_PASS"
            and result.get("completed_workpack_ids") == ["MB-P4"]
            and result.get("next_node_activated") is False
            and bound(result, "workpack_result_ref", "workpack_result_sha256")
            and promotion.get("status")
            == "PROMOTED_STOPPED_BEFORE_RELEASE_PIPELINE_HANDOFF"
            and promotion.get("next_node_activated") is False
            and promotion.get("release_pipeline_handoff_started") is False
            and bound(promotion, "result_ref", "result_sha256")
            and runtime_hash == _json_hash(runtime_material)
            and runtime.get("state_revision") == 46
            and runtime.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and runtime.get("completed_workpack_ids") == expected_workpacks
            and runtime.get("completed_workpack_ids", []).count("MB-P4") == 1
            and runtime.get("authorization_consumptions", {}).get(
                "AUTH-VSCDSL-MAIN-P4-STDIN-ISOLATED-RETRY-V03-001"
            )
            == 1
            and runtime.get("active_dag_node") is None
            and runtime.get("active_workpack_id") is None
            and runtime.get("side_effects_allowed") is False
            and state.get("state") == expected_control_state
            and state.get("highest_completed_external_gate")
            == "MAIN_P4_LOCAL_CLOSURE_PASS"
            and state.get("open_blocker_codes") == expected_blockers
            and state.get("next_eligible_action") == expected_next_action
            and state.get("active_dag_node") is None
            and state.get("active_workpack_id") is None
            and state.get("release_pipeline_handoff_started") is False
            and state.get("install_started") is False
            and repository_hash(repository) == expected_repository
            and not (repository / ".git").exists()
            and not (evidence / "engineering_dag/RELEASE_PIPELINE_HANDOFF").exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (
        KeyError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return False


def _authorized_release_pipeline_handoff_preparation(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept only the zero-transition, receipt-bound Release entry preparation."""

    if not _authorized_main_p4_local_closure_completion(
        candidate_root,
        execution_root,
        executable_path,
        command,
        allow_release_preparation_state=True,
    ):
        return False
    try:
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        def read_json(path: Path) -> Mapping[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError(f"expected object: {path}")
            return value

        def bound(document: Mapping[str, Any], ref_key: str, hash_key: str) -> bool:
            path = resolve_ref(document.get(ref_key))
            return bool(path.is_file() and document.get(hash_key) == _file_hash(path))

        def strict_schema(schema: Any) -> bool:
            if not isinstance(schema, dict):
                return False
            schema_type = schema.get("type")
            if ("const" in schema or "enum" in schema) and not isinstance(
                schema_type, str
            ):
                return False
            if schema_type == "object":
                properties = schema.get("properties")
                required = schema.get("required")
                return bool(
                    isinstance(properties, dict)
                    and schema.get("additionalProperties") is False
                    and isinstance(required, list)
                    and set(required) == set(properties)
                    and all(strict_schema(item) for item in properties.values())
                )
            if schema_type == "array":
                return strict_schema(schema.get("items"))
            return isinstance(schema_type, str)

        control = execution_root / "control_plane"
        evidence = execution_root / "evidence"
        planned = execution_root / "planned_executors"
        snapshot_path = control / (
            "history/RELEASE_PIPELINE_HANDOFF_PREPARATION.preparation_snapshot.json"
        )
        authorization_path = (
            control / "RELEASE_PIPELINE_HANDOFF_PREPARATION_AUTHORIZATION.json"
        )
        baseline_path = control / "RELEASE_PIPELINE_HANDOFF_BASELINE_LOCK.json"
        contract_path = planned / "contracts/P4_BUILD_INPUT_LOCK_CONTRACT.json"
        schema_path = planned / "schemas/P4_BUILD_INPUT_LOCK_OUTPUT.schema.json"
        manifest_path = planned / "manifests/P4_BUILD_INPUT_LOCK.resolved-action.json"
        action_path = planned / "bin/materialize_p4_build_input_lock.py"
        independent_path = (
            planned / "bin/independently_validate_p4_build_input_lock.py"
        )
        descriptor_path = (
            control / "RELEASE_PIPELINE_HANDOFF_EXECUTOR_DESCRIPTOR.json"
        )
        boundary_path = evidence / (
            "release-pipeline-handoff-preparation/"
            "RELEASE_PIPELINE_HANDOFF_PREPARATION_BOUNDARY_ATTESTATION.json"
        )
        readiness_path = (
            control / "RELEASE_PIPELINE_HANDOFF_PREPARATION_READINESS_REPORT.json"
        )
        draft_path = (
            control / "RELEASE_PIPELINE_HANDOFF_ENTRY_EXECUTION_AUTHORIZATION_DRAFT.json"
        )
        receipt_path = control / "RELEASE_PIPELINE_HANDOFF_PREPARATION_RECEIPT.json"
        state_path = control / "CONTROL_PLANE_STATE.json"

        snapshot = read_json(snapshot_path)
        authorization = read_json(authorization_path)
        baseline = read_json(baseline_path)
        contract = read_json(contract_path)
        schema = read_json(schema_path)
        manifest = read_json(manifest_path)
        descriptor = read_json(descriptor_path)
        boundary = read_json(boundary_path)
        readiness = read_json(readiness_path)
        draft = read_json(draft_path)
        receipt = read_json(receipt_path)
        state = read_json(state_path)
        release_manifest_path = candidate_root / "RELEASE_PIPELINE_MANIFEST.json"
        release_manifest = read_json(release_manifest_path)
        authorization_scope = authorization.get("scope", {})
        draft_scope = draft.get("scope", {})
        contract_bindings = contract.get("hash_bound_inputs", [])
        steps = release_manifest.get("steps", [])
        first_step = steps[0] if isinstance(steps, list) and steps else {}
        expected_confirmation = "授权 RELEASE_PIPELINE_HANDOFF_PREPARATION"
        expected_next_text = (
            "授权 RELEASE_PIPELINE_HANDOFF_ENTRY_EXECUTION，仅允许 Driver 执行一次 Hash 绑定的 "
            "P4_BUILD_INPUT_LOCK Pipeline Action，生成 Release Pipeline 的 P4 构建输入锁、"
            "结果、晋级和独立验证证据；不授权 PACK_DRAFT、任何后续 Release Step、认证、"
            "Git 操作或任何安装。"
        )
        state_preparation = state.get("release_pipeline_handoff_preparation", {})

        return bool(
            snapshot.get("status")
            == "HASH_BOUND_RELEASE_PIPELINE_HANDOFF_PREPARATION_SNAPSHOT"
            and snapshot.get("authorization_text") == expected_confirmation
            and snapshot.get("authorization_text_sha256")
            == hashlib.sha256(expected_confirmation.encode()).hexdigest()
            and snapshot.get("p4_build_input_lock_executed") is False
            and authorization.get("status")
            == "GRANTED_AND_CONSUMED_PREPARATION_ONLY"
            and authorization.get("authorization_scope_sha256")
            == _json_hash(authorization_scope)
            and authorization.get("decision_evidence", {}).get("confirmation_text")
            == expected_confirmation
            and authorization.get("max_driver_transitions") == 0
            and authorization.get("execution_authorized") is False
            and authorization.get("driver_execution_authorized") is False
            and authorization_scope.get("release_step_ids")
            == ["P4_BUILD_INPUT_LOCK"]
            and authorization_scope.get("pipeline_action_ids") == []
            and "P4_BUILD_INPUT_LOCK_EXECUTION"
            in authorization.get("forbidden_actions", [])
            and "GIT_INIT_STAGE_COMMIT_PUSH"
            in authorization.get("forbidden_actions", [])
            and bound(
                authorization,
                "based_on_main_p4_completion_ref",
                "based_on_main_p4_completion_sha256",
            )
            and baseline.get("status")
            == "LOCKED_FOR_RELEASE_PIPELINE_HANDOFF_PREPARATION"
            and baseline.get("release_pipeline_contract", {}).get("fixed_step_count")
            == 23
            and baseline.get("first_release_step_contract", {}).get("step_id")
            == "P4_BUILD_INPUT_LOCK"
            and baseline.get("first_release_step_contract", {}).get(
                "allowed_next_step_ids"
            )
            == ["PACK_DRAFT"]
            and bound(baseline, "authorization_ref", "authorization_sha256")
            and bound(
                baseline,
                "release_pipeline_manifest_ref",
                "release_pipeline_manifest_sha256",
            )
            and release_manifest.get("pipeline_status") == "PLANNED_NOT_ACTIVE"
            and len(steps) == 23
            and first_step.get("step_id") == "P4_BUILD_INPUT_LOCK"
            and first_step.get("pipeline_action_id") == "P4_BUILD_INPUT_LOCK"
            and first_step.get("allowed_next_step_ids") == ["PACK_DRAFT"]
            and contract.get("status") == "LOCKED_NOT_EXECUTED"
            and contract.get("pipeline_action_id") == "P4_BUILD_INPUT_LOCK"
            and isinstance(contract_bindings, list)
            and all(
                Path(str(item.get("path_abs", ""))).is_file()
                and item.get("sha256")
                == _file_hash(Path(str(item.get("path_abs"))))
                for item in contract_bindings
            )
            and strict_schema(schema)
            and manifest.get("status") == "READY_NOT_EXECUTED"
            and manifest.get("auto_execute") is False
            and manifest.get("execution_started") is False
            and manifest.get("pipeline_action_id") == "P4_BUILD_INPUT_LOCK"
            and manifest.get("release_step_id") == "P4_BUILD_INPUT_LOCK"
            and manifest.get("pack_draft_started") is False
            and manifest.get("release_pipeline_handoff_started") is False
            and manifest.get("action_script_sha256") == _file_hash(action_path)
            and manifest.get("independent_validator_script_sha256")
            == _file_hash(independent_path)
            and manifest.get("validation_contract_sha256")
            == _file_hash(contract_path)
            and manifest.get("output_schema_sha256") == _file_hash(schema_path)
            and descriptor.get("status")
            == "PREPARED_VERIFIED_NOT_INVOKED_FOR_RELEASE_PIPELINE_HANDOFF_ENTRY"
            and descriptor.get("driver_transition_count") == 0
            and descriptor.get("execution_started") is False
            and bound(descriptor, "manifest_ref", "manifest_sha256")
            and bound(descriptor, "output_schema_ref", "output_schema_sha256")
            and bound(
                descriptor, "validation_contract_ref", "validation_contract_sha256"
            )
            and boundary.get("status")
            == "PASS_PREPARATION_ONLY_NO_RELEASE_STEP_EXECUTED"
            and len(boundary.get("checks", [])) == 12
            and all(
                item.get("status") == "PASS" for item in boundary.get("checks", [])
            )
            and boundary.get("p4_build_input_lock_output_exists") is False
            and boundary.get("driver_transition_count") == 0
            and bound(boundary, "descriptor_ref", "descriptor_sha256")
            and bound(boundary, "manifest_ref", "manifest_sha256")
            and readiness.get("technical_preparation_status") == "PASS"
            and readiness.get("status")
            == "READY_FOR_EXPLICIT_P4_BUILD_INPUT_LOCK_EXECUTION_AUTHORIZATION_NOT_GRANTED"
            and readiness.get("required_next_authorization_text") == expected_next_text
            and readiness.get("required_next_authorization_text_sha256")
            == hashlib.sha256(expected_next_text.encode()).hexdigest()
            and bound(readiness, "boundary_attestation_ref", "boundary_attestation_sha256")
            and bound(readiness, "descriptor_ref", "descriptor_sha256")
            and bound(readiness, "manifest_ref", "manifest_sha256")
            and draft.get("status") == "DRAFT_READY_NOT_GRANTED"
            and draft.get("grantable") is False
            and draft.get("execution_authorized") is False
            and draft.get("driver_execution_authorized") is False
            and draft.get("authorization_scope_sha256") == _json_hash(draft_scope)
            and draft_scope.get("pipeline_action_ids") == ["P4_BUILD_INPUT_LOCK"]
            and draft_scope.get("release_step_ids") == ["P4_BUILD_INPUT_LOCK"]
            and draft_scope.get("workpack_ids") == []
            and draft.get("required_authorization_text") == expected_next_text
            and bound(draft, "preparation_readiness_ref", "preparation_readiness_sha256")
            and receipt.get("status")
            == "COMPLETE_READY_FOR_EXPLICIT_RELEASE_PIPELINE_HANDOFF_ENTRY_EXECUTION_AUTHORIZATION"
            and receipt.get("preparation_authorization_transitions_consumed") == 1
            and receipt.get("driver_transition_count") == 0
            and receipt.get("p4_build_input_lock_started") is False
            and receipt.get("release_pipeline_handoff_started") is False
            and bound(receipt, "authorization_draft_ref", "authorization_draft_sha256")
            and bound(receipt, "boundary_attestation_ref", "boundary_attestation_sha256")
            and bound(receipt, "descriptor_ref", "descriptor_sha256")
            and bound(receipt, "readiness_report_ref", "readiness_report_sha256")
            and state.get("projects", {}).get("MAIN_HARNESS_BUILD")
            == "RELEASE_PIPELINE_HANDOFF_PREPARATION_PASS_NO_RELEASE_STEP_EXECUTED"
            and state.get("workspace_status")
            == "RELEASE_PIPELINE_HANDOFF_PREPARATION_PASS_NO_RELEASE_STEP_EXECUTED"
            and state_preparation.get("status") == "PASS_PREPARED_NOT_EXECUTED"
            and bound(state_preparation, "receipt_ref", "receipt_sha256")
            and state.get("release_pipeline_handoff_started") is False
            and not (
                evidence / "release_pipeline/P4_BUILD_INPUT_LOCK"
            ).exists()
            and not (evidence / "engineering_dag/RELEASE_PIPELINE_HANDOFF").exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (
        KeyError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return False


def _authorized_main_p4_local_closure_failure(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept only the evidence-bound, zero-delta MB-P4 fail-stop boundary."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    if command.get("command_id") not in {
        "ROOT-CODEX-CODING",
        "MB-CODEX-CODING",
        "LINK-CODEX-CODING",
        "LAB-CODEX-CODING",
    }:
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        def read_json(path: Path) -> Mapping[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError(f"expected object: {path}")
            return value

        def bound(document: Mapping[str, Any], ref_key: str, hash_key: str) -> bool:
            path = resolve_ref(document.get(ref_key))
            return bool(path.is_file() and document.get(hash_key) == _file_hash(path))

        def repository_hash(root: Path) -> tuple[str, int]:
            digest = hashlib.sha256()
            count = 0
            for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
                if (
                    not path.is_file()
                    or "__pycache__" in path.parts
                    or path.suffix in {".pyc", ".pyo"}
                ):
                    continue
                digest.update(path.relative_to(root).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(_file_hash(path).encode("ascii"))
                digest.update(b"\n")
                count += 1
            return digest.hexdigest(), count

        control = execution_root / "control_plane"
        evidence = execution_root / "evidence"
        repository = execution_root / "project_start_packages/main_build/repository"
        attempt_id = "ATTEMPT-D569726D8BAF4B718AF8D238CF9CD8BE"
        attempt_root = (
            evidence
            / "project_workpacks/MAIN_HARNESS_BUILD/MB-P4/attempts"
            / attempt_id
        )
        authorization_path = (
            control / "MAIN_P4_LOCAL_CLOSURE_EXECUTION_AUTHORIZATION.json"
        )
        snapshot_path = (
            control / "history/MAIN_P4_LOCAL_CLOSURE.pre_execution_snapshot.json"
        )
        manifest_path = execution_root / "planned_executors/manifests/MB-P4.resolved-command.json"
        agent_path = attempt_root / "MB-P4.agent-result.json"
        independent_path = evidence / (
            "project_workpacks/MAIN_HARNESS_BUILD/MB-P4/"
            "INDEPENDENT_FAILURE_VERIFICATION_RECEIPT.json"
        )
        failed_workpack_path = evidence / (
            "project_workpacks/MAIN_HARNESS_BUILD/MB-P4/FAILED_WORKPACK_RESULT.json"
        )
        failure_result_path = (
            evidence / "engineering_dag/MAIN_P4_LOCAL_CLOSURE.failure-result.json"
        )
        descriptor_path = (
            control / "MAIN_P4_LOCAL_CLOSURE_EXECUTOR_DESCRIPTOR_AFTER_FAILURE.json"
        )
        failure_receipt_path = (
            control / "MAIN_P4_LOCAL_CLOSURE_EXECUTION_FAILURE_RECEIPT.json"
        )
        repair_draft_path = control / (
            "MAIN_P4_CODEX_STDIN_ISOLATION_REPAIR_REVERIFY_AND_RETRY_"
            "AUTHORIZATION_DRAFT.json"
        )
        state_path = control / "CONTROL_PLANE_STATE.json"
        runtime_path = control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json"
        transition_path = control / "runtime/PHASE_TRANSITION_LEDGER.jsonl"
        promotion_ledger_path = control / "runtime/PROMOTION_LEDGER.jsonl"

        authorization = read_json(authorization_path)
        snapshot = read_json(snapshot_path)
        manifest = read_json(manifest_path)
        agent = read_json(agent_path)
        independent = read_json(independent_path)
        failed_workpack = read_json(failed_workpack_path)
        failure_result = read_json(failure_result_path)
        descriptor = read_json(descriptor_path)
        failure_receipt = read_json(failure_receipt_path)
        repair_draft = read_json(repair_draft_path)
        state = read_json(state_path)
        runtime = read_json(runtime_path)
        runtime_material = dict(runtime)
        runtime_hash = runtime_material.pop("state_hash", None)
        scope = authorization.get("scope", {})
        repair_scope = repair_draft.get("scope", {})
        state_p4 = state.get("main_p4_local_closure", {})
        expected_repository = (
            "e74af33c191a4889b1e74b119cb7cc79c46c0ff8f1954dd85576331150726dab",
            22,
        )
        blockers = [
            "MAIN_P4_CODEX_CHILD_STDIN_CONTEXT_CONTAMINATION",
            "MAIN_P4_AGENT_RECURSIVE_DRIVER_INVOCATION",
            "MAIN_P4_CHANGED_FILES_REPOSITORY_DELTA_MISMATCH",
            "MAIN_P4_ZERO_REPOSITORY_DELTA",
            "MAIN_P4_REPAIR_REVERIFY_AND_RETRY_REAUTHORIZATION_REQUIRED",
        ]
        stdout_path = attempt_root / "MB-P4.stdout"
        stderr_path = attempt_root / "MB-P4.stderr"
        stdout_text = stdout_path.read_text(encoding="utf-8")
        stderr_text = stderr_path.read_text(encoding="utf-8")
        evidence_root = evidence / "project_workpacks/MAIN_HARNESS_BUILD/MB-P4"
        actual_evidence_files = {
            path.relative_to(evidence_root).as_posix()
            for path in evidence_root.rglob("*")
            if path.is_file()
        }
        expected_evidence_files = {
            "FAILED_WORKPACK_RESULT.json",
            "INDEPENDENT_FAILURE_VERIFICATION_RECEIPT.json",
            f"attempts/{attempt_id}/MB-P4.agent-result.json",
            f"attempts/{attempt_id}/MB-P4.stderr",
            f"attempts/{attempt_id}/MB-P4.stdout",
        }

        return bool(
            _candidate_tree_hash(candidate_root)
            == "5ee5d5a9d6312c2fe3bf2c3fbf535765321b1cd1f72d610b62188d6b4de4112d"
            and expected_launcher.is_file()
            and _file_hash(expected_launcher)
            == "d3c62048f066d3407fd822a7e445772e549e16f4f657314f33100bf63d6340a6"
            and authorization.get("status") == "GRANTED"
            and authorization.get("authorization_id")
            == "AUTH-VSCDSL-MAIN-P4-LOCAL-CLOSURE-EXECUTION-V03-001"
            and authorization.get("authorization_scope_sha256") == _json_hash(scope)
            and authorization.get("decision_evidence", {}).get(
                "confirmation_text_sha256"
            )
            == "b99ab854d5d386df941f453fa1aba0625856fe9b46417e07fb640c1477f6c255"
            and authorization.get("max_transitions") == 1
            and authorization.get("granted_transitions") == 1
            and scope.get("dag_node_ids") == ["MAIN_P4_LOCAL_CLOSURE"]
            and scope.get("workpack_ids") == ["MB-P4"]
            and scope.get("pipeline_action_ids") == []
            and authorization.get("consumption_policy", {}).get("one_time_only")
            is True
            and authorization.get("consumption_policy", {}).get(
                "require_changed_files_match_repository_delta"
            )
            is True
            and bound(
                authorization,
                "pre_execution_snapshot_ref",
                "pre_execution_snapshot_sha256",
            )
            and resolve_ref(authorization.get("pre_execution_snapshot_ref"))
            == snapshot_path.resolve()
            and snapshot.get("status") == "HASH_BOUND_PRE_EXECUTION_SNAPSHOT"
            and snapshot.get("runtime_state_revision") == 42
            and snapshot.get("main_repository_content_sha256")
            == expected_repository[0]
            and snapshot.get("main_repository_content_file_count")
            == expected_repository[1]
            and manifest.get("workpack_id") == "MB-P4"
            and manifest.get("require_changed_files_match_repository_delta") is True
            and manifest.get("release_pipeline_handoff_started") is False
            and agent.get("status") == "PASS"
            and agent.get("workpack_id") == "MB-P4"
            and len(agent.get("changed_files", [])) == 106
            and independent.get("status")
            == "FAIL_CONFIRMED_ZERO_REPOSITORY_DELTA_STDIN_CONTEXT_CONTAMINATION_STOPPED"
            and independent.get("attempt_id") == attempt_id
            and independent.get("blocking_findings") == blockers
            and independent.get("main_repository_actual_changed_files") == []
            and independent.get("main_repository_content_sha256")
            == expected_repository[0]
            and independent.get("main_repository_content_file_count")
            == expected_repository[1]
            and independent.get("authorization_consumption_count") == 1
            and independent.get("main_p4_local_closure_promotion_created") is False
            and failed_workpack.get("status")
            == "FAIL_STOPPED_ZERO_REPOSITORY_DELTA_CONTEXT_CONTAMINATION"
            and failed_workpack.get("changed_files") == []
            and failed_workpack.get("completed_workpack_recorded") is False
            and failed_workpack.get("promotion_created") is False
            and bound(
                failed_workpack,
                "independent_failure_verification_ref",
                "independent_failure_verification_sha256",
            )
            and failure_result.get("status")
            == "FAIL_STOPPED_ZERO_REPOSITORY_DELTA_CONTEXT_CONTAMINATION"
            and failure_result.get("completed_workpack_ids") == []
            and failure_result.get("promotion_created") is False
            and bound(
                failure_result,
                "failed_workpack_result_ref",
                "failed_workpack_result_sha256",
            )
            and descriptor.get("status")
            == "MAIN_P4_LOCAL_CLOSURE_FAILED_ZERO_REPOSITORY_DELTA_DRIVER_BLOCKED"
            and descriptor.get("codex_child_stdin_isolated") is False
            and descriptor.get("stdin_isolation_repair_required") is True
            and descriptor.get("main_repository_actual_changed_file_count") == 0
            and descriptor.get("main_p4_local_closure_completed") is False
            and descriptor.get("next_node_activated") is False
            and failure_receipt.get("status")
            == "FAILED_ZERO_REPOSITORY_DELTA_STDIN_CONTEXT_CONTAMINATION_STOPPED"
            and failure_receipt.get("authorization_transitions_consumed") == 1
            and failure_receipt.get("completed_workpack_ids") == []
            and failure_receipt.get("code_files_written") == []
            and failure_receipt.get("main_p4_local_closure_promotion_created") is False
            and bound(
                failure_receipt,
                "executor_descriptor_ref",
                "executor_descriptor_sha256",
            )
            and repair_draft.get("status") == "DRAFT_READY_NOT_GRANTED"
            and repair_draft.get("authorization_scope_sha256")
            == _json_hash(repair_scope)
            and repair_draft.get("grantable") is False
            and repair_draft.get("execution_authorized") is False
            and repair_draft.get("driver_execution_authorized") is False
            and repair_draft.get("max_transitions") == 0
            and repair_draft.get("granted_transitions") == 0
            and repair_draft.get("proposed_repair_driver_transitions") == 0
            and repair_draft.get("proposed_retry_driver_transitions") == 1
            and repair_draft.get("required_authorization_text_sha256")
            == "0e8a4247a205452f3b4cd5a38204dccd09b521aae4a03b1ee119b85b395931e1"
            and bound(repair_draft, "failure_receipt_ref", "failure_receipt_sha256")
            and runtime_hash == _json_hash(runtime_material)
            and runtime.get("state_revision") == 44
            and runtime.get("driver_status") == "BLOCKED_WORKPACK_VALIDATION_FAIL"
            and runtime.get("active_dag_node") == "MAIN_P4_LOCAL_CLOSURE"
            and runtime.get("active_workpack_id") is None
            and runtime.get("open_blocker_codes")
            == ["WORKPACK_RESULT_OR_INDEPENDENT_VALIDATION_FAILED"]
            and runtime.get("authorization_consumptions", {}).get(
                "AUTH-VSCDSL-MAIN-P4-LOCAL-CLOSURE-EXECUTION-V03-001"
            )
            == 1
            and runtime.get("active_attempt", {}).get("attempt_id") == attempt_id
            and runtime.get("active_attempt", {}).get("execution_unit_id") == "MB-P4"
            and runtime.get("active_attempt", {}).get("status") == "VALIDATED_FAIL"
            and "MB-P4" not in runtime.get("completed_workpack_ids", [])
            and _file_hash(runtime_path)
            == "6704f6b831f86dae36b8d0737d0e29e0cc5e6957ed9fa32b6abe45708fcad156"
            and _file_hash(transition_path)
            == "0ab205069caae4b8965138ce7cf857f9f4ccc5fd6e8769eb75959ab656c0671f"
            and _file_hash(promotion_ledger_path)
            == "9f4509e33c4ee7383922fc0f9f120bb2a8415f15bc3b14b5fa0cae34ba575dda"
            and repository_hash(repository) == expected_repository
            and state.get("state")
            == "MAIN_P4_LOCAL_CLOSURE_BLOCKED_STDIN_CONTEXT_CONTAMINATION_WAITING_REPAIR_REVERIFY_AND_RETRY_AUTHORIZATION"
            and state.get("highest_completed_external_gate")
            == "MAIN_P3_C3_OR_APPROVED_NA_PASS"
            and state.get("open_blocker_codes") == blockers
            and state.get("next_eligible_action")
            == "OBTAIN_MAIN_P4_CODEX_STDIN_ISOLATION_REPAIR_REVERIFY_AND_RETRY_AUTHORIZATION"
            and state.get("active_dag_node") == "MAIN_P4_LOCAL_CLOSURE"
            and state.get("active_workpack_id") is None
            and state_p4.get("status")
            == "FAIL_STOPPED_ZERO_REPOSITORY_DELTA_CONTEXT_CONTAMINATION"
            and state_p4.get("completed_workpack_ids") == []
            and state_p4.get("promotion_created") is False
            and state.get("main_p4_local_closure_started") is True
            and state.get("mb_p4_started") is True
            and state.get("release_pipeline_handoff_started") is False
            and state.get("install_started") is False
            and actual_evidence_files == expected_evidence_files
            and "Reading additional input from stdin..." in stderr_text
            and "UNKNOWN_COMMIT_STATE_BLOCKS_REEXECUTION" in stdout_text
            and "RECOVERY_NOT_REQUIRED" in stdout_text
            and not (evidence / "engineering_dag/MAIN_P4_LOCAL_CLOSURE").exists()
            and not (
                evidence / "engineering_dag/MAIN_P4_LOCAL_CLOSURE.result.json"
            ).exists()
            and not (
                evidence / "engineering_dag/MAIN_P4_LOCAL_CLOSURE.promotion.json"
            ).exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (
        KeyError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return False


def _authorized_main_p4_local_closure_preparation(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept only the receipt-bound, zero-Driver-transition MB-P4 preparation."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    if command.get("command_id") not in {
        "ROOT-CODEX-CODING",
        "MB-CODEX-CODING",
        "LINK-CODEX-CODING",
        "LAB-CODEX-CODING",
    }:
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        def read_json(path: Path) -> Mapping[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError(f"expected object: {path}")
            return value

        def bound(document: Mapping[str, Any], ref_key: str, hash_key: str) -> bool:
            path = resolve_ref(document.get(ref_key))
            return bool(path.is_file() and document.get(hash_key) == _file_hash(path))

        def repository_hash(root: Path) -> tuple[str, int]:
            digest = hashlib.sha256()
            count = 0
            for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
                if (
                    not path.is_file()
                    or "__pycache__" in path.parts
                    or path.suffix in {".pyc", ".pyo"}
                ):
                    continue
                digest.update(path.relative_to(root).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(_file_hash(path).encode("ascii"))
                digest.update(b"\n")
                count += 1
            return digest.hexdigest(), count

        def source_path_hash(path: Path) -> tuple[str, int]:
            if path.is_symlink():
                return (
                    hashlib.sha256(
                        f"SYMLINK:{os.readlink(path)}".encode("utf-8")
                    ).hexdigest(),
                    1,
                )
            if path.is_file():
                return _file_hash(path), 1
            if not path.is_dir():
                raise OSError(f"invalid source path: {path}")
            digest = hashlib.sha256()
            count = 0
            for child in sorted(path.rglob("*"), key=lambda item: item.as_posix()):
                if child.is_dir():
                    continue
                child_hash, child_count = source_path_hash(child)
                digest.update(child.relative_to(path).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(child_hash.encode("ascii"))
                digest.update(b"\n")
                count += child_count
            return digest.hexdigest(), count

        control = execution_root / "control_plane"
        planned = execution_root / "planned_executors"
        evidence = execution_root / "evidence"
        repository = execution_root / "project_start_packages/main_build/repository"
        authorization_path = (
            control / "MAIN_P4_LOCAL_CLOSURE_PREPARATION_AUTHORIZATION.json"
        )
        snapshot_path = (
            control
            / "history/MAIN_P4_LOCAL_CLOSURE_PREPARATION.preparation_snapshot.json"
        )
        baseline_path = control / "MAIN_P4_LOCAL_CLOSURE_BASELINE_LOCK.json"
        contract_path = (
            planned / "contracts/MAIN_P4_LOCAL_CLOSURE_WORKPACK_CONTRACT.json"
        )
        manifest_path = planned / "manifests/MB-P4.resolved-command.json"
        schema_path = (
            planned / "schemas/MAIN_P4_LOCAL_CLOSURE_WORKPACK_OUTPUT.schema.json"
        )
        descriptor_path = control / "MAIN_P4_LOCAL_CLOSURE_EXECUTOR_DESCRIPTOR.json"
        boundary_path = (
            evidence
            / "main-p4-local-closure-preparation/MAIN_P4_LOCAL_CLOSURE_PREPARATION_BOUNDARY_ATTESTATION.json"
        )
        readiness_path = (
            control / "MAIN_P4_LOCAL_CLOSURE_PREPARATION_READINESS_REPORT.json"
        )
        draft_path = (
            control / "MAIN_P4_LOCAL_CLOSURE_EXECUTION_AUTHORIZATION_DRAFT.json"
        )
        receipt_path = control / "MAIN_P4_LOCAL_CLOSURE_PREPARATION_RECEIPT.json"
        state_path = control / "CONTROL_PLANE_STATE.json"
        runtime_path = control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json"
        p3_receipt_path = control / "MAIN_P3_C3_OR_APPROVED_NA_COMPLETION_RECEIPT.json"
        p3_result_path = (
            evidence / "engineering_dag/MAIN_P3_C3_OR_APPROVED_NA.result.json"
        )
        p3_promotion_path = (
            evidence / "engineering_dag/MAIN_P3_C3_OR_APPROVED_NA.promotion.json"
        )
        p3_lock_path = repository / "control/p3-build-lock.json"

        authorization = read_json(authorization_path)
        snapshot = read_json(snapshot_path)
        baseline = read_json(baseline_path)
        contract = read_json(contract_path)
        manifest = read_json(manifest_path)
        schema = read_json(schema_path)
        descriptor = read_json(descriptor_path)
        boundary = read_json(boundary_path)
        readiness = read_json(readiness_path)
        draft = read_json(draft_path)
        receipt = read_json(receipt_path)
        state = read_json(state_path)
        runtime = read_json(runtime_path)
        p3_receipt = read_json(p3_receipt_path)
        p3_result = read_json(p3_result_path)
        p3_promotion = read_json(p3_promotion_path)
        p3_lock = read_json(p3_lock_path)

        candidate_hash = _candidate_tree_hash(candidate_root)
        current_repository = repository_hash(repository)
        scope = authorization.get("scope", {})
        draft_scope = draft.get("scope", {})
        state_boundary = state.get("main_p4_local_closure_preparation", {})
        runtime_material = dict(runtime)
        runtime_hash = runtime_material.pop("state_hash", None)
        source_registry_path = resolve_ref(baseline["source_corpus_inputs"]["registry_ref"])
        source_registry = read_json(source_registry_path)
        source_inputs = baseline.get("source_corpus_inputs", {}).get("sources", [])
        source_records = {
            item.get("source_id"): item
            for item in source_registry.get("sources", [])
            if isinstance(item, dict)
        }
        expected_sources = [
            ("SRC-AE-JSX-LIBRARY", "53b0189134e94e26228f6b5b73db6a0607d3dc4b4739dd8eba609a96a787fb1b", 60),
            ("SRC-VSCDSL-KB-V2", "0bce4497efaa89acfe0c5afb3bc282f402b9ad8c419da9bd6e85fdb1419ca049", 33),
            ("SRC-VSCDSL-WHITEPAPER", "0dced11a0de4e9d3f8450752b8223b1efa596eb746eeb6b423020258c4363baf", 1),
            ("SRC-SUPPLEMENTAL-PROMPT-COMPILATION-EXAMPLES", "d985529460a22db2a8566fc92e982c109c15c3834e5891f0851611de1fc4e515", 1),
        ]
        actual_source_inputs = [
            (item.get("source_id"), item.get("sha256"), item.get("file_count"))
            for item in source_inputs
            if isinstance(item, dict)
        ]
        source_paths_valid = all(
            source_id in source_records
            and source_records[source_id].get("snapshot_path")
            == next(
                item.get("path")
                for item in source_inputs
                if item.get("source_id") == source_id
            )
            and source_path_hash(Path(source_records[source_id]["snapshot_path"]))
            == (source_hash, file_count)
            for source_id, source_hash, file_count in expected_sources
        )
        expected_checks = [
            "EXACT_MAIN_P4_LOCAL_CLOSURE_PREPARATION_AUTHORIZATION_TEXT_HASH_BOUND",
            "START_PACKAGE_V03_CONTENT_HASH_UNCHANGED",
            "MAIN_P3_IMPLEMENT_PASS_P3_LOCK_AND_C3_HASH_BOUND",
            "MAIN_REPOSITORY_POST_P3_HASH_BOUND",
            "MAIN_P4_LOCAL_CLOSURE_DAG_AND_MB_P4_SOURCE_HASH_BOUND",
            "NINETY_FIVE_FROZEN_SOURCE_PAYLOADS_HASH_VERIFIED_READ_ONLY",
            "SOURCE_FAILURE_RETURN_DISCREPANCY_PRESERVED_FAIL_STOPPED",
            "RESOLVED_MANIFEST_OUTPUT_SCHEMA_AND_EXECUTOR_HASH_BOUND",
            "DRIVER_RUNTIME_REMAINS_STOPPED_AT_REVISION_42",
            "MB_P4_AND_MAIN_P4_LOCAL_CLOSURE_EXECUTION_EVIDENCE_ABSENT",
            "MAIN_REPOSITORY_UNCHANGED_DURING_PREPARATION",
            "SOURCE_PAYLOAD_COPY_NOT_STARTED_DURING_PREPARATION",
            "RELEASE_HANDOFF_CERTIFICATION_AND_INSTALL_NOT_STARTED",
            "EXECUTION_AUTHORIZATION_REMAINS_NOT_GRANTED",
        ]
        boundary_checks = boundary.get("checks", [])

        return bool(
            candidate_hash
            == "5ee5d5a9d6312c2fe3bf2c3fbf535765321b1cd1f72d610b62188d6b4de4112d"
            and expected_launcher.is_file()
            and _file_hash(expected_launcher)
            == "d3c62048f066d3407fd822a7e445772e549e16f4f657314f33100bf63d6340a6"
            and authorization.get("status")
            == "GRANTED_AND_CONSUMED_PREPARATION_ONLY"
            and authorization.get("authorization_class")
            == "PROGRAM_EXECUTION_PREPARATION_AUTHORIZATION"
            and authorization.get("candidate_content_sha256") == candidate_hash
            and authorization.get("authorization_scope_sha256") == _json_hash(scope)
            and authorization.get("preparation_only") is True
            and authorization.get("execution_authorized") is False
            and authorization.get("driver_execution_authorized") is False
            and authorization.get("max_driver_transitions") == 0
            and authorization.get("granted_preparation_transitions") == 1
            and authorization.get("decision_evidence", {}).get(
                "confirmation_text_sha256"
            )
            == "f56482ac6c9f4e189b47edbec7075e7e62efbeb397d64689db7155792c1c68d7"
            and scope.get("dag_node_ids") == ["MAIN_P4_LOCAL_CLOSURE"]
            and scope.get("project_ids") == ["MAIN_HARNESS_BUILD"]
            and scope.get("workpack_ids") == ["MB-P4"]
            and scope.get("pipeline_action_ids") == []
            and scope.get("execution_modes") == ["PREPARATION_ONLY"]
            and bound(
                authorization,
                "based_on_preparation_snapshot_ref",
                "based_on_preparation_snapshot_sha256",
            )
            and resolve_ref(authorization.get("based_on_preparation_snapshot_ref"))
            == snapshot_path.resolve()
            and bound(
                authorization,
                "based_on_main_p3_completion_ref",
                "based_on_main_p3_completion_sha256",
            )
            and snapshot.get("status") == "HASH_BOUND_PREPARATION_SNAPSHOT"
            and snapshot.get("authorization_text_sha256")
            == "f56482ac6c9f4e189b47edbec7075e7e62efbeb397d64689db7155792c1c68d7"
            and snapshot.get("runtime_state_revision") == 42
            and snapshot.get("runtime_state_hash") == runtime_hash
            and snapshot.get("runtime_state_file_sha256") == _file_hash(runtime_path)
            and snapshot.get("main_repository_content_sha256") == current_repository[0]
            and snapshot.get("main_repository_content_file_count")
            == current_repository[1]
            and snapshot.get("source_corpus_file_count") == 95
            and snapshot.get("main_p4_local_closure_started") is False
            and snapshot.get("mb_p4_started") is False
            and snapshot.get("workpack_execution_started") is False
            and snapshot.get("release_pipeline_handoff_started") is False
            and baseline.get("status")
            == "LOCKED_FOR_MAIN_P4_LOCAL_CLOSURE_PREPARATION"
            and baseline.get("candidate_content_sha256") == candidate_hash
            and bound(baseline, "authorization_ref", "authorization_sha256")
            and bound(baseline, "snapshot_ref", "snapshot_sha256")
            and baseline.get("main_repository", {}).get("content_sha256")
            == current_repository[0]
            and baseline.get("main_repository", {}).get("content_file_count")
            == current_repository[1]
            and baseline.get("runtime_binding", {}).get("runtime_state_hash")
            == runtime_hash
            and baseline.get("source_corpus_inputs", {}).get("registry_sha256")
            == _file_hash(source_registry_path)
            and actual_source_inputs == expected_sources
            and source_paths_valid
            and contract.get("workpack_id") == "MB-P4"
            and contract.get("node_id") == "MAIN_P4_LOCAL_CLOSURE"
            and contract.get("next_node_id") == "RELEASE_PIPELINE_HANDOFF"
            and contract.get("source_corpus", {}).get("file_count") == 95
            and bound(contract, "baseline_ref", "baseline_sha256")
            and manifest.get("status") == "READY_NOT_EXECUTED"
            and manifest.get("workpack_id") == "MB-P4"
            and manifest.get("auto_execute") is False
            and manifest.get("execution_started") is False
            and manifest.get("release_pipeline_handoff_started") is False
            and manifest.get("source_corpus_file_count") == 95
            and bound(
                manifest,
                "main_p4_local_closure_baseline_ref",
                "main_p4_local_closure_baseline_sha256",
            )
            and bound(
                manifest,
                "main_p4_local_closure_contract_ref",
                "main_p4_local_closure_contract_sha256",
            )
            and resolve_ref(manifest.get("output_schema_abs")) == schema_path.resolve()
            and manifest.get("output_schema_sha256") == _file_hash(schema_path)
            and schema.get("type") == "object"
            and descriptor.get("status")
            == "PREPARED_VERIFIED_NOT_INVOKED_FOR_MAIN_P4_LOCAL_CLOSURE"
            and descriptor.get("agent_invoked_for_main_p4_local_closure") is False
            and descriptor.get("main_p4_local_closure_started") is False
            and descriptor.get("mb_p4_started") is False
            and bound(descriptor, "command_manifest_ref", "command_manifest_sha256")
            and bound(descriptor, "output_schema_ref", "output_schema_sha256")
            and bound(
                descriptor,
                "main_p4_local_closure_baseline_ref",
                "main_p4_local_closure_baseline_sha256",
            )
            and bound(
                descriptor,
                "main_p4_local_closure_contract_ref",
                "main_p4_local_closure_contract_sha256",
            )
            and boundary.get("status")
            == "PASS_PREPARATION_ONLY_NO_MAIN_P4_LOCAL_CLOSURE_EXECUTION"
            and [item.get("check_id") for item in boundary_checks] == expected_checks
            and all(item.get("status") == "PASS" for item in boundary_checks)
            and bound(boundary, "authorization_ref", "authorization_sha256")
            and bound(boundary, "baseline_ref", "baseline_sha256")
            and bound(boundary, "contract_ref", "contract_sha256")
            and bound(boundary, "manifest_ref", "manifest_sha256")
            and bound(boundary, "output_schema_ref", "output_schema_sha256")
            and bound(boundary, "descriptor_ref", "descriptor_sha256")
            and readiness.get("status")
            == "READY_FOR_EXPLICIT_MAIN_P4_LOCAL_CLOSURE_EXECUTION_AUTHORIZATION_NOT_GRANTED"
            and readiness.get("technical_preparation_status") == "PASS"
            and readiness.get("workpack_execution_started") is False
            and readiness.get("source_corpus_copy_started") is False
            and bound(
                readiness,
                "boundary_attestation_ref",
                "boundary_attestation_sha256",
            )
            and bound(readiness, "contract_ref", "contract_sha256")
            and draft.get("status") == "DRAFT_READY_NOT_GRANTED"
            and draft.get("grantable") is False
            and draft.get("execution_authorized") is False
            and draft.get("driver_execution_authorized") is False
            and draft.get("main_p4_local_closure_authorized") is False
            and draft.get("max_transitions") == 0
            and draft.get("granted_transitions") == 0
            and draft.get("proposed_max_transitions") == 1
            and draft.get("authorization_scope_sha256") == _json_hash(draft_scope)
            and draft.get("required_authorization_text_sha256")
            == "b99ab854d5d386df941f453fa1aba0625856fe9b46417e07fb640c1477f6c255"
            and bound(
                draft,
                "preparation_readiness_ref",
                "preparation_readiness_sha256",
            )
            and bound(
                draft,
                "main_p4_local_closure_baseline_ref",
                "main_p4_local_closure_baseline_sha256",
            )
            and receipt.get("status")
            == "COMPLETE_READY_FOR_EXPLICIT_MAIN_P4_LOCAL_CLOSURE_EXECUTION_AUTHORIZATION"
            and receipt.get("authorization_transitions_consumed") == 1
            and receipt.get("driver_execution_transitions_consumed") == 0
            and receipt.get("main_p4_local_closure_started") is False
            and receipt.get("mb_p4_started") is False
            and receipt.get("workpack_execution_started") is False
            and receipt.get("source_corpus_copy_started") is False
            and receipt.get("release_pipeline_handoff_started") is False
            and receipt.get("next_required_authorization_text_sha256")
            == "b99ab854d5d386df941f453fa1aba0625856fe9b46417e07fb640c1477f6c255"
            and bound(receipt, "authorization_ref", "authorization_sha256")
            and bound(receipt, "preparation_snapshot_ref", "preparation_snapshot_sha256")
            and bound(
                receipt,
                "main_p4_local_closure_baseline_ref",
                "main_p4_local_closure_baseline_sha256",
            )
            and bound(receipt, "contract_ref", "contract_sha256")
            and bound(receipt, "manifest_ref", "manifest_sha256")
            and bound(receipt, "output_schema_ref", "output_schema_sha256")
            and bound(receipt, "descriptor_ref", "descriptor_sha256")
            and bound(
                receipt,
                "boundary_attestation_ref",
                "boundary_attestation_sha256",
            )
            and bound(receipt, "readiness_report_ref", "readiness_report_sha256")
            and bound(
                receipt,
                "main_p4_local_closure_execution_authorization_draft_ref",
                "main_p4_local_closure_execution_authorization_draft_sha256",
            )
            and runtime_hash == _json_hash(runtime_material)
            and runtime.get("state_revision") == 42
            and runtime.get("driver_status") == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and runtime.get("active_dag_node") is None
            and runtime.get("active_workpack_id") is None
            and runtime.get("active_pipeline_action_id") is None
            and runtime.get("side_effects_allowed") is False
            and "MB-P4" not in runtime.get("completed_workpack_ids", [])
            and current_repository
            == (
                "e74af33c191a4889b1e74b119cb7cc79c46c0ff8f1954dd85576331150726dab",
                22,
            )
            and p3_receipt.get("status")
            == "MAIN_P3_C3_OR_APPROVED_NA_COMPLETE_IMPLEMENT_STOPPED_BEFORE_MAIN_P4_LOCAL_CLOSURE"
            and p3_result.get("status") == "PASS"
            and p3_promotion.get("next_node_activated") is False
            and p3_lock.get("produced_capability") == "P3_BUILD_LOCK_VALID"
            and p3_lock.get("c3_checkpoint", {}).get("status") == "PASS"
            and state.get("state")
            == "MAIN_P4_LOCAL_CLOSURE_PREPARED_WAITING_EXECUTION_AUTHORIZATION"
            and state.get("highest_completed_external_gate")
            == "MAIN_P3_C3_OR_APPROVED_NA_PASS"
            and state.get("open_blocker_codes")
            == ["MAIN_P4_LOCAL_CLOSURE_EXECUTION_AUTHORIZATION_REQUIRED"]
            and state.get("next_eligible_action")
            == "OBTAIN_MAIN_P4_LOCAL_CLOSURE_EXECUTION_AUTHORIZATION"
            and state.get("active_dag_node") is None
            and state.get("active_workpack_id") is None
            and state.get("main_p4_local_closure_started") is False
            and state.get("mb_p4_started") is False
            and state.get("release_pipeline_handoff_started") is False
            and state.get("install_started") is False
            and state_boundary.get("status") == "PASS_PREPARED_NOT_EXECUTED"
            and state_boundary.get("source_corpus_file_count") == 95
            and state_boundary.get("source_corpus_copy_started") is False
            and bound(state_boundary, "authorization_ref", "authorization_sha256")
            and bound(state_boundary, "baseline_ref", "baseline_sha256")
            and bound(state_boundary, "contract_ref", "contract_sha256")
            and bound(state_boundary, "manifest_ref", "manifest_sha256")
            and bound(state_boundary, "output_schema_ref", "output_schema_sha256")
            and bound(state_boundary, "descriptor_ref", "descriptor_sha256")
            and bound(state_boundary, "readiness_report_ref", "readiness_report_sha256")
            and bound(
                state_boundary,
                "execution_authorization_draft_ref",
                "execution_authorization_draft_sha256",
            )
            and bound(state_boundary, "receipt_ref", "receipt_sha256")
            and not (control / "MAIN_P4_LOCAL_CLOSURE_EXECUTION_AUTHORIZATION.json").exists()
            and not (evidence / "engineering_dag/MAIN_P4_LOCAL_CLOSURE").exists()
            and not (evidence / "engineering_dag/MAIN_P4_LOCAL_CLOSURE.result.json").exists()
            and not (evidence / "engineering_dag/MAIN_P4_LOCAL_CLOSURE.promotion.json").exists()
            and not (evidence / "project_workpacks/MAIN_HARNESS_BUILD/MB-P4").exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (
        KeyError,
        OSError,
        StopIteration,
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return False


def _authorized_main_p3_c3_implement_completion(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept only the receipt-bound single-transition MB-P3 IMPLEMENT PASS."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    if command.get("command_id") not in {
        "ROOT-CODEX-CODING",
        "MB-CODEX-CODING",
        "LINK-CODEX-CODING",
        "LAB-CODEX-CODING",
    }:
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        def read_json(path: Path) -> Mapping[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError(f"expected object: {path}")
            return value

        def bound(document: Mapping[str, Any], ref_key: str, hash_key: str) -> bool:
            path = resolve_ref(document.get(ref_key))
            return bool(path.is_file() and document.get(hash_key) == _file_hash(path))

        def repository_hash(root: Path) -> tuple[str, int]:
            digest = hashlib.sha256()
            count = 0
            for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
                if (
                    not path.is_file()
                    or "__pycache__" in path.parts
                    or path.suffix in {".pyc", ".pyo"}
                ):
                    continue
                digest.update(path.relative_to(root).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(_file_hash(path).encode("ascii"))
                digest.update(b"\n")
                count += 1
            return digest.hexdigest(), count

        def jsonl_line_count(path: Path) -> int:
            return len(
                [line for line in path.read_text(encoding="utf-8").splitlines() if line]
            )

        control = execution_root / "control_plane"
        evidence = execution_root / "evidence"
        planned = execution_root / "planned_executors"
        repository = execution_root / "project_start_packages/main_build/repository"
        workpack_evidence = evidence / "project_workpacks/MAIN_HARNESS_BUILD/MB-P3"
        dag_evidence = evidence / "engineering_dag"

        authorization_path = control / "MAIN_P3_C3_IMPLEMENT_EXECUTION_AUTHORIZATION.json"
        snapshot_path = control / "history/MAIN_P3_C3_IMPLEMENT.pre_execution_snapshot.json"
        manifest_path = planned / "manifests/MB-P3.resolved-command.json"
        schema_path = planned / "schemas/MAIN_P3_C3_IMPLEMENT_WORKPACK_OUTPUT.schema.json"
        runtime_path = control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json"
        transition_ledger_path = control / "runtime/PHASE_TRANSITION_LEDGER.jsonl"
        promotion_ledger_path = control / "runtime/PROMOTION_LEDGER.jsonl"
        lock_path = repository / "control/p3-build-lock.json"
        independent_path = workpack_evidence / "INDEPENDENT_VALIDATION_RECEIPT.json"
        workpack_result_path = workpack_evidence / "WORKPACK_RESULT.json"
        result_path = dag_evidence / "MAIN_P3_C3_OR_APPROVED_NA.result.json"
        promotion_path = dag_evidence / "MAIN_P3_C3_OR_APPROVED_NA.promotion.json"
        descriptor_path = control / "MAIN_P3_C3_IMPLEMENT_EXECUTOR_DESCRIPTOR_AFTER_EXECUTION.json"
        receipt_path = control / "MAIN_P3_C3_OR_APPROVED_NA_COMPLETION_RECEIPT.json"
        state_path = control / "CONTROL_PLANE_STATE.json"

        authorization = read_json(authorization_path)
        snapshot = read_json(snapshot_path)
        manifest = read_json(manifest_path)
        runtime = read_json(runtime_path)
        p3_lock = read_json(lock_path)
        independent = read_json(independent_path)
        agent_path = resolve_ref(independent.get("agent_result_ref"))
        agent = read_json(agent_path)
        workpack_result = read_json(workpack_result_path)
        result = read_json(result_path)
        promotion = read_json(promotion_path)
        descriptor = read_json(descriptor_path)
        receipt = read_json(receipt_path)
        state = read_json(state_path)

        candidate_hash = _candidate_tree_hash(candidate_root)
        current_repository = repository_hash(repository)
        scope = authorization.get("scope", {})
        authorization_id = authorization.get("authorization_id")
        expected_changed_files = [
            "control/p3-build-lock.json",
            "src/vscdsl_harness/p3_build_lock.py",
            "tests/test_p2_build_lock.py",
            "tests/test_p3_build_lock.py",
        ]
        expected_acceptance_ids = [
            "SOURCE_WORKPACK_AND_BASELINE_HASHES_MATCH",
            "P2_BUILD_LOCK_VALID_PREDECESSOR_HASH_BOUND",
            "P3_BUILD_LAYER_INTERFACE_IS_EXPLICIT",
            "P3_BUILD_LOCK_IS_DETERMINISTIC_AND_FAIL_CLOSED",
            "P3_POSITIVE_NEGATIVE_AND_TAMPER_TESTS_PASS",
            "C3_CHECKPOINT_IS_HASH_BOUND_AND_PASS",
            "FULL_MAIN_REPOSITORY_TEST_SUITE_PASSES",
            "NO_P4_CERTIFICATION_OR_INSTALL_SCOPE_STARTED",
        ]
        acceptance_checks = agent.get("acceptance_checks", [])
        expected_completed = [
            "LAB-PROTOCOL",
            "LAB-CLI",
            "LAB-FIXTURES",
            "LAB-SELFTEST",
            "LINK-PROTOCOL",
            "LINK-CLI",
            "LINK-SELFTEST",
            "WP-vscdsl-video-prompt-harness-G0-001",
            "MB-G0",
            "MB-P1",
            "MB-P2",
            "MB-P3",
        ]
        expected_forbidden = {
            "P3_NOT_APPLICABLE_DECISION",
            "P3_NOT_APPLICABLE_LOCK_EXECUTION",
            "MAIN_P4_LOCAL_CLOSURE",
            "LATER_MAIN_WORKPACK_EXECUTION",
            "OTHER_WORKPACK_EXECUTION",
            "OTHER_PIPELINE_ACTION_EXECUTION",
            "LAB_CERTIFICATION",
            "TARGET_RUNTIME_INSTALLATION",
            "REAL_TARGET_INSTALL",
            "INSTALL",
        }
        runtime_material = dict(runtime)
        runtime_hash = runtime_material.pop("state_hash", None)
        state_boundary = state.get("main_p3_c3_or_approved_na", {})
        p3_lock_hash = p3_lock.get("p3_build_lock_sha256")

        common_documents = (
            workpack_result,
            result,
            descriptor,
            receipt,
        )
        common_completion_valid = all(
            document.get("workpack_id") == "MB-P3"
            and document.get("route") == "IMPLEMENT"
            and document.get("authorization_sha256") == _file_hash(authorization_path)
            and document.get("repository_content_sha256") == current_repository[0]
            and document.get("repository_content_file_count") == current_repository[1]
            and document.get("runtime_state_hash") == runtime_hash
            and document.get("runtime_state_revision") == 42
            for document in common_documents
        )

        return bool(
            candidate_hash
            == "5ee5d5a9d6312c2fe3bf2c3fbf535765321b1cd1f72d610b62188d6b4de4112d"
            and expected_launcher.is_file()
            and _file_hash(expected_launcher)
            == "d3c62048f066d3407fd822a7e445772e549e16f4f657314f33100bf63d6340a6"
            and authorization.get("status") == "GRANTED"
            and authorization.get("authorization_class")
            == "PROGRAM_EXECUTION_AUTHORIZATION"
            and authorization.get("candidate_content_sha256") == candidate_hash
            and authorization.get("authorization_scope_sha256") == _json_hash(scope)
            and authorization.get("branch") == "IMPLEMENT"
            and authorization.get("main_p3_c3_implement_authorized") is True
            and authorization.get("main_p3_c3_approved_na_authorized") is False
            and authorization.get("p3_not_applicable_decision_authorized") is False
            and authorization.get("p3_not_applicable_lock_authorized") is False
            and authorization.get("main_p4_local_closure_authorized") is False
            and authorization.get("execution_authorized") is True
            and authorization.get("driver_execution_authorized") is True
            and authorization.get("max_transitions") == 1
            and authorization.get("granted_transitions") == 1
            and authorization.get("may_auto_advance") is False
            and authorization.get("real_target_install_allowed") is False
            and authorization.get("decision_evidence", {}).get(
                "confirmation_text_sha256"
            )
            == "220b4bb36b8e56f1e07f178e76d8076b120db79942c60fbc7f0822c9f327c916"
            and scope.get("dag_node_ids") == ["MAIN_P3_C3_OR_APPROVED_NA"]
            and scope.get("project_ids") == ["MAIN_HARNESS_BUILD"]
            and scope.get("workpack_ids") == ["MB-P3"]
            and scope.get("pipeline_action_ids") == []
            and scope.get("branch") == "IMPLEMENT"
            and expected_forbidden.issubset(
                set(authorization.get("forbidden_actions", []))
            )
            and authorization.get("command_manifest_refs")
            == [
                {
                    "branch": "IMPLEMENT",
                    "ref": "execution/planned_executors/manifests/MB-P3.resolved-command.json",
                    "sha256": _file_hash(manifest_path),
                    "workpack_id": "MB-P3",
                }
            ]
            and bound(authorization, "based_on_draft_ref", "based_on_draft_sha256")
            and bound(
                authorization,
                "main_p3_c3_or_approved_na_baseline_ref",
                "main_p3_c3_or_approved_na_baseline_sha256",
            )
            and bound(authorization, "output_schema_ref", "output_schema_sha256")
            and resolve_ref(authorization.get("output_schema_ref")) == schema_path.resolve()
            and bound(
                authorization,
                "pre_execution_snapshot_ref",
                "pre_execution_snapshot_sha256",
            )
            and resolve_ref(authorization.get("pre_execution_snapshot_ref"))
            == snapshot_path.resolve()
            and snapshot.get("status") == "HASH_BOUND_PRE_EXECUTION_SNAPSHOT"
            and snapshot.get("authorization_text_sha256")
            == "220b4bb36b8e56f1e07f178e76d8076b120db79942c60fbc7f0822c9f327c916"
            and snapshot.get("selected_branch") == "IMPLEMENT"
            and snapshot.get("runtime_state_revision") == 40
            and snapshot.get("main_repository_content_sha256")
            == "70c6c52f8370701ddfb662f2c6d3a26a772cd68a1db56dbd69c20828d00f58c9"
            and snapshot.get("main_repository_content_file_count") == 19
            and snapshot.get("main_p3_c3_or_approved_na_started") is False
            and snapshot.get("mb_p3_started") is False
            and snapshot.get("p3_not_applicable_decision_recorded") is False
            and snapshot.get("p3_not_applicable_lock_started") is False
            and snapshot.get("main_p4_local_closure_started") is False
            and manifest.get("status") == "READY_NOT_EXECUTED"
            and manifest.get("workpack_id") == "MB-P3"
            and manifest.get("branch") == "IMPLEMENT"
            and manifest.get("auto_execute") is False
            and runtime_hash == _json_hash(runtime_material)
            and runtime.get("state_revision") == 42
            and runtime.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and runtime.get("active_dag_node") is None
            and runtime.get("active_workpack_id") is None
            and runtime.get("active_pipeline_action_id") is None
            and runtime.get("side_effects_allowed") is False
            and runtime.get("completed_workpack_ids") == expected_completed
            and runtime.get("completed_workpack_ids", []).count("MB-P3") == 1
            and runtime.get("authorization_consumptions", {}).get(authorization_id)
            == 1
            and "P3_NOT_APPLICABLE_LOCK"
            not in runtime.get("completed_pipeline_action_ids", [])
            and runtime.get("open_blocker_codes") == []
            and current_repository
            == (
                "e74af33c191a4889b1e74b119cb7cc79c46c0ff8f1954dd85576331150726dab",
                22,
            )
            and p3_lock_hash == _hash_without_field(p3_lock, "p3_build_lock_sha256")
            and p3_lock_hash
            == "608ecb150283ea035c671accea567a83eb9a1e6724dc3c4065fe759dd9fb9258"
            and p3_lock.get("workpack_id") == "MB-P3"
            and p3_lock.get("route") == "IMPLEMENT"
            and p3_lock.get("produced_capability") == "P3_BUILD_LOCK_VALID"
            and p3_lock.get("c3_checkpoint", {}).get("checkpoint_id") == "C3"
            and p3_lock.get("c3_checkpoint", {}).get("status") == "PASS"
            and p3_lock.get("scope", {}).get("p3_not_applicable_decision_used")
            is False
            and p3_lock.get("scope", {}).get("main_p4_local_closure_started")
            is False
            and p3_lock.get("scope", {}).get("certification_started") is False
            and p3_lock.get("scope", {}).get("install_performed") is False
            and agent.get("status") == "PASS"
            and agent.get("workpack_id") == "MB-P3"
            and agent.get("route") == "IMPLEMENT"
            and agent.get("changed_files") == expected_changed_files
            and [check.get("check_id") for check in acceptance_checks]
            == expected_acceptance_ids
            and all(check.get("status") == "PASS" for check in acceptance_checks)
            and agent.get("p3_not_applicable_decision_used") is False
            and agent.get("main_p4_local_closure_started") is False
            and agent.get("install_performed") is False
            and independent.get("status") == "PASS"
            and independent.get("workpack_id") == "MB-P3"
            and independent.get("route") == "IMPLEMENT"
            and independent.get("test_count") == 34
            and independent.get("changed_files") == expected_changed_files
            and independent.get("agent_result_sha256") == _file_hash(agent_path)
            and independent.get("p3_build_lock_sha256") == _file_hash(lock_path)
            and independent.get("p3_build_lock_value_sha256") == p3_lock_hash
            and independent.get("c3_checkpoint", {}).get("status") == "PASS"
            and independent.get("main_p4_local_closure_started") is False
            and independent.get("p3_not_applicable_decision_used") is False
            and independent.get("install_performed") is False
            and independent.get("runtime_state_file_sha256") == _file_hash(runtime_path)
            and independent.get("transition_ledger_sha256")
            == _file_hash(transition_ledger_path)
            and independent.get("transition_ledger_line_count")
            == jsonl_line_count(transition_ledger_path)
            and independent.get("promotion_ledger_sha256")
            == _file_hash(promotion_ledger_path)
            and independent.get("promotion_ledger_line_count")
            == jsonl_line_count(promotion_ledger_path)
            and common_completion_valid
            and workpack_result.get("status") == "PASS"
            and workpack_result.get("authorization_transitions_consumed") == 1
            and workpack_result.get("c3_checkpoint_pass") is True
            and workpack_result.get("independent_validation_sha256")
            == _file_hash(independent_path)
            and result.get("status") == "PASS"
            and result.get("completed_workpack_ids") == ["MB-P3"]
            and result.get("success_gate") == "MAIN_P3_C3_OR_APPROVED_NA_PASS"
            and result.get("next_node_id") == "MAIN_P4_LOCAL_CLOSURE"
            and result.get("next_node_activated") is False
            and result.get("workpack_result_sha256")
            == _file_hash(workpack_result_path)
            and promotion.get("status")
            == "PROMOTED_STOPPED_BEFORE_MAIN_P4_LOCAL_CLOSURE"
            and promotion.get("completed_workpack_ids") == ["MB-P3"]
            and promotion.get("next_node_id") == "MAIN_P4_LOCAL_CLOSURE"
            and promotion.get("next_node_activated") is False
            and promotion.get("result_sha256") == _file_hash(result_path)
            and descriptor.get("status")
            == "MAIN_P3_C3_IMPLEMENT_PASS_STOPPED_BEFORE_MAIN_P4_LOCAL_CLOSURE"
            and descriptor.get("authorization_transitions_consumed") == 1
            and descriptor.get("independent_validation_sha256")
            == _file_hash(independent_path)
            and descriptor.get("result_sha256") == _file_hash(result_path)
            and descriptor.get("promotion_sha256") == _file_hash(promotion_path)
            and receipt.get("status")
            == "MAIN_P3_C3_OR_APPROVED_NA_COMPLETE_IMPLEMENT_STOPPED_BEFORE_MAIN_P4_LOCAL_CLOSURE"
            and receipt.get("authorization_transitions_consumed") == 1
            and receipt.get("c3_checkpoint_pass") is True
            and receipt.get("completed_workpack_ids") == ["MB-P3"]
            and receipt.get("main_p3_c3_or_approved_na_started") is True
            and receipt.get("mb_p3_started") is True
            and receipt.get("p3_not_applicable_decision_recorded") is False
            and receipt.get("p3_not_applicable_lock_started") is False
            and receipt.get("main_p4_local_closure_started") is False
            and receipt.get("install_started") is False
            and receipt.get("target_runtime_install_started") is False
            and receipt.get("executor_descriptor_sha256") == _file_hash(descriptor_path)
            and state.get("state")
            == "MAIN_P3_C3_OR_APPROVED_NA_PASS_WAITING_MAIN_P4_LOCAL_CLOSURE_PREPARATION_AUTHORIZATION"
            and state.get("highest_completed_external_gate")
            == "MAIN_P3_C3_OR_APPROVED_NA_PASS"
            and state.get("open_blocker_codes")
            == ["MAIN_P4_LOCAL_CLOSURE_PREPARATION_AUTHORIZATION_REQUIRED"]
            and state.get("next_eligible_action")
            == "OBTAIN_MAIN_P4_LOCAL_CLOSURE_PREPARATION_AUTHORIZATION"
            and state.get("main_p3_c3_or_approved_na_started") is True
            and state.get("mb_p3_started") is True
            and state.get("main_p4_local_closure_started") is False
            and state.get("install_started") is False
            and state_boundary.get("status")
            == "PASS_COMPLETE_IMPLEMENT_STOPPED_BEFORE_MAIN_P4_LOCAL_CLOSURE"
            and state_boundary.get("route") == "IMPLEMENT"
            and state_boundary.get("authorization_transitions_consumed") == 1
            and state_boundary.get("result_sha256") == _file_hash(result_path)
            and state_boundary.get("promotion_sha256") == _file_hash(promotion_path)
            and state_boundary.get("completion_receipt_sha256")
            == _file_hash(receipt_path)
            and state_boundary.get("workpack_result_sha256")
            == _file_hash(workpack_result_path)
            and state_boundary.get("independent_validation_sha256")
            == _file_hash(independent_path)
            and not (
                control / "MAIN_P3_C3_APPROVED_NA_EXECUTION_AUTHORIZATION.json"
            ).exists()
            and not (dag_evidence / "P3_NOT_APPLICABLE_LOCK.result.json").exists()
            and not (
                evidence
                / "project_pipeline_actions/MAIN_HARNESS_BUILD/P3_NOT_APPLICABLE_LOCK"
            ).exists()
            and not (evidence / "engineering_dag/MAIN_P4_LOCAL_CLOSURE").exists()
            and not (evidence / "project_workpacks/MAIN_HARNESS_BUILD/MB-P4").exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_main_p3_c3_or_approved_na_preparation(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept the exact P3 conditional preparation with neither branch selected."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    if command.get("command_id") not in {
        "ROOT-CODEX-CODING",
        "MB-CODEX-CODING",
        "LINK-CODEX-CODING",
        "LAB-CODEX-CODING",
    }:
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        def read_json(path: Path) -> Mapping[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError(f"expected object: {path}")
            return value

        def bound(document: Mapping[str, Any], ref_key: str, hash_key: str) -> bool:
            path = resolve_ref(document.get(ref_key))
            return bool(path.is_file() and document.get(hash_key) == _file_hash(path))

        def repository_hash(root: Path) -> tuple[str, int]:
            digest = hashlib.sha256()
            count = 0
            for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
                if (
                    not path.is_file()
                    or "__pycache__" in path.parts
                    or path.suffix in {".pyc", ".pyo"}
                ):
                    continue
                digest.update(path.relative_to(root).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(_file_hash(path).encode("ascii"))
                digest.update(b"\n")
                count += 1
            return digest.hexdigest(), count

        control = execution_root / "control_plane"
        evidence = execution_root / "evidence"
        planned = execution_root / "planned_executors"
        repository = execution_root / "project_start_packages/main_build/repository"
        authorization = read_json(
            control / "MAIN_P3_C3_OR_APPROVED_NA_PREPARATION_AUTHORIZATION.json"
        )
        baseline = read_json(control / "MAIN_P3_C3_OR_APPROVED_NA_BASELINE_LOCK.json")
        contract = read_json(
            planned / "contracts/MAIN_P3_C3_OR_APPROVED_NA_BRANCH_CONTRACT.json"
        )
        workpack_manifest = read_json(planned / "manifests/MB-P3.resolved-command.json")
        na_manifest = read_json(
            planned / "manifests/P3_NOT_APPLICABLE_LOCK.resolved-action.json"
        )
        descriptor = read_json(
            control / "MAIN_P3_C3_OR_APPROVED_NA_EXECUTOR_DESCRIPTOR.json"
        )
        boundary = read_json(
            evidence
            / "main-p3-c3-or-approved-na-preparation/"
            "MAIN_P3_C3_OR_APPROVED_NA_PREPARATION_BOUNDARY_ATTESTATION.json"
        )
        readiness = read_json(
            control / "MAIN_P3_C3_OR_APPROVED_NA_PREPARATION_READINESS_REPORT.json"
        )
        implement_draft = read_json(
            control / "MAIN_P3_C3_IMPLEMENT_EXECUTION_AUTHORIZATION_DRAFT.json"
        )
        na_draft = read_json(
            control / "MAIN_P3_C3_APPROVED_NA_EXECUTION_AUTHORIZATION_DRAFT.json"
        )
        receipt = read_json(
            control / "MAIN_P3_C3_OR_APPROVED_NA_PREPARATION_RECEIPT.json"
        )
        runtime = read_json(control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json")
        state = read_json(control / "CONTROL_PLANE_STATE.json")

        expected_candidate_hash = (
            "5ee5d5a9d6312c2fe3bf2c3fbf535765321b1cd1f72d610b62188d6b4de4112d"
        )
        expected_repository = (
            "70c6c52f8370701ddfb662f2c6d3a26a772cd68a1db56dbd69c20828d00f58c9",
            19,
        )
        expected_completed = [
            "LAB-PROTOCOL",
            "LAB-CLI",
            "LAB-FIXTURES",
            "LAB-SELFTEST",
            "LINK-PROTOCOL",
            "LINK-CLI",
            "LINK-SELFTEST",
            "WP-vscdsl-video-prompt-harness-G0-001",
            "MB-G0",
            "MB-P1",
            "MB-P2",
        ]
        scope = authorization.get("scope", {})
        implement_scope = implement_draft.get("scope", {})
        na_scope = na_draft.get("scope", {})
        hash_bindings_valid = True
        for document, excluded_refs in (
            (authorization, set()),
            (baseline, {"runtime_state_ref"}),
            (workpack_manifest, set()),
            (na_manifest, set()),
            (descriptor, {"runtime_state_ref"}),
            (boundary, {"runtime_state_ref"}),
            (readiness, {"runtime_state_ref"}),
            (implement_draft, {"runtime_state_ref"}),
            (na_draft, {"runtime_state_ref"}),
            (receipt, {"runtime_state_ref"}),
        ):
            for key, value in document.items():
                if key.endswith("_ref") and isinstance(value, str):
                    hash_key = f"{key[:-4]}_sha256"
                    if hash_key in document and key not in excluded_refs:
                        hash_bindings_valid = bool(
                            hash_bindings_valid and bound(document, key, hash_key)
                        )

        return bool(
            _candidate_tree_hash(candidate_root) == expected_candidate_hash
            and repository_hash(repository) == expected_repository
            and expected_launcher.is_file()
            and _file_hash(expected_launcher)
            == "d3c62048f066d3407fd822a7e445772e549e16f4f657314f33100bf63d6340a6"
            and authorization.get("status")
            == "GRANTED_AND_CONSUMED_PREPARATION_ONLY"
            and authorization.get("authorization_scope_sha256") == _json_hash(scope)
            and authorization.get("preparation_only") is True
            and authorization.get("execution_authorized") is False
            and authorization.get("driver_execution_authorized") is False
            and authorization.get("route_selection_authorized") is False
            and authorization.get("max_driver_transitions") == 0
            and scope.get("dag_node_ids") == ["MAIN_P3_C3_OR_APPROVED_NA"]
            and scope.get("workpack_ids") == ["MB-P3"]
            and scope.get("pipeline_action_ids") == ["P3_NOT_APPLICABLE_LOCK"]
            and baseline.get("status")
            == "LOCKED_FOR_MAIN_P3_C3_OR_APPROVED_NA_PREPARATION"
            and baseline.get("authorization_sha256")
            == _file_hash(
                control / "MAIN_P3_C3_OR_APPROVED_NA_PREPARATION_AUTHORIZATION.json"
            )
            and baseline.get("candidate_node_contract", {}).get("action_kind")
            == "CONDITIONAL"
            and baseline.get("route_selection_policy", {}).get("selected_branch")
            is None
            and baseline.get("conditional_branches", {}).get("IMPLEMENT", {}).get(
                "workpack_id"
            )
            == "MB-P3"
            and baseline.get("conditional_branches", {})
            .get("APPROVED_NOT_APPLICABLE", {})
            .get("pipeline_action_id")
            == "P3_NOT_APPLICABLE_LOCK"
            and contract.get("baseline_sha256")
            == _file_hash(control / "MAIN_P3_C3_OR_APPROVED_NA_BASELINE_LOCK.json")
            and contract.get("route_selection_policy", {}).get(
                "preparation_authorization_selects_no_branch"
            )
            is True
            and contract.get("nonclaims", {}).get("route_selected") is False
            and workpack_manifest.get("status") == "READY_NOT_EXECUTED"
            and workpack_manifest.get("branch") == "IMPLEMENT"
            and workpack_manifest.get("workpack_id") == "MB-P3"
            and workpack_manifest.get("auto_execute") is False
            and na_manifest.get("status")
            == "READY_NOT_EXECUTED_WAITING_EXPLICIT_HUMAN_DECISION"
            and na_manifest.get("branch") == "APPROVED_NOT_APPLICABLE"
            and na_manifest.get("pipeline_action_id") == "P3_NOT_APPLICABLE_LOCK"
            and na_manifest.get("workpack_id") is None
            and na_manifest.get("decision_authorization_status") == "NOT_RECEIVED"
            and implement_draft.get("status") == "DRAFT_READY_NOT_GRANTED"
            and implement_draft.get("authorization_scope_sha256")
            == _json_hash(implement_scope)
            and implement_draft.get("execution_authorized") is False
            and implement_scope.get("branch") == "IMPLEMENT"
            and na_draft.get("status")
            == "DRAFT_READY_NOT_GRANTED_REQUIRES_EXPLICIT_P3_NA_DECISION"
            and na_draft.get("authorization_scope_sha256") == _json_hash(na_scope)
            and na_draft.get("p3_not_applicable_decision_approved") is False
            and na_draft.get("selected_branch") is None
            and descriptor.get("status")
            == "PREPARED_VERIFIED_NO_BRANCH_SELECTED_OR_INVOKED"
            and descriptor.get("route_selected") is False
            and boundary.get("status")
            == "PASS_PREPARATION_ONLY_NO_BRANCH_SELECTED_OR_EXECUTED"
            and boundary.get("driver_execution_transitions_consumed") == 0
            and boundary.get("writes_to_main_repository_performed") is False
            and readiness.get("technical_preparation_status") == "PASS"
            and readiness.get("no_branch_selected") is True
            and receipt.get("status")
            == "COMPLETE_READY_FOR_EXPLICIT_BRANCH_SELECTION_AND_EXECUTION_AUTHORIZATION"
            and receipt.get("driver_execution_transitions_consumed") == 0
            and receipt.get("no_branch_selected") is True
            and runtime.get("state_revision") == 40
            and runtime.get("state_hash")
            == "6fcefbca704a2b475babf100b9d241fc6cb68f947c8c529eb611b6665dd3c803"
            and runtime.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and runtime.get("completed_workpack_ids") == expected_completed
            and runtime.get("completed_workpack_ids", []).count("MB-P3") == 0
            and "P3_NOT_APPLICABLE_LOCK"
            not in runtime.get("completed_pipeline_action_ids", [])
            and state.get("state")
            == "MAIN_P3_C3_OR_APPROVED_NA_PREPARED_WAITING_BRANCH_SELECTION_AND_EXECUTION_AUTHORIZATION"
            and state.get("highest_completed_external_gate") == "MAIN_P2_C2_PASS"
            and state.get("main_p3_c3_or_approved_na_started") is False
            and state.get("mb_p3_started") is False
            and state.get("install_started") is False
            and hash_bindings_valid
            and not (control / "MAIN_P3_C3_IMPLEMENT_EXECUTION_AUTHORIZATION.json").exists()
            and not (
                control / "MAIN_P3_C3_APPROVED_NA_EXECUTION_AUTHORIZATION.json"
            ).exists()
            and not (evidence / "engineering_dag/MAIN_P3_C3_OR_APPROVED_NA").exists()
            and not (
                evidence / "project_workpacks/MAIN_HARNESS_BUILD/MB-P3"
            ).exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_main_p2_c2_completion(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept only the exact single-transition MB-P2 PASS boundary."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    if command.get("command_id") not in {
        "ROOT-CODEX-CODING",
        "MB-CODEX-CODING",
        "LINK-CODEX-CODING",
        "LAB-CODEX-CODING",
    }:
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        def read_json(path: Path) -> Mapping[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError(f"expected object: {path}")
            return value

        def bound(document: Mapping[str, Any], ref_key: str, hash_key: str) -> bool:
            path = resolve_ref(document.get(ref_key))
            return bool(path.is_file() and document.get(hash_key) == _file_hash(path))

        def repository_hash(root: Path) -> tuple[str, int]:
            digest = hashlib.sha256()
            count = 0
            for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
                if (
                    not path.is_file()
                    or "__pycache__" in path.parts
                    or path.suffix in {".pyc", ".pyo"}
                ):
                    continue
                digest.update(path.relative_to(root).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(_file_hash(path).encode("ascii"))
                digest.update(b"\n")
                count += 1
            return digest.hexdigest(), count

        control = execution_root / "control_plane"
        evidence = execution_root / "evidence"
        planned = execution_root / "planned_executors"
        repository = execution_root / "project_start_packages/main_build/repository"
        attempt_id = "ATTEMPT-AED023D8C06A491F8CEA83854DF831D5"
        workpack_root = evidence / "project_workpacks/MAIN_HARNESS_BUILD/MB-P2"
        authorization = read_json(
            control / "MAIN_P2_C2_EXECUTION_AUTHORIZATION.json"
        )
        manifest = read_json(planned / "manifests/MB-P2.resolved-command.json")
        agent = read_json(
            workpack_root / f"attempts/{attempt_id}/MB-P2.agent-result.json"
        )
        independent = read_json(workpack_root / "INDEPENDENT_VALIDATION_RECEIPT.json")
        workpack = read_json(workpack_root / "WORKPACK_RESULT.json")
        result = read_json(evidence / "engineering_dag/MAIN_P2_C2.result.json")
        promotion = read_json(evidence / "engineering_dag/MAIN_P2_C2.promotion.json")
        completion = read_json(control / "MAIN_P2_C2_COMPLETION_RECEIPT.json")
        descriptor = read_json(
            control / "MAIN_P2_C2_EXECUTOR_DESCRIPTOR_AFTER_EXECUTION.json"
        )
        runtime = read_json(control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json")
        state = read_json(control / "CONTROL_PLANE_STATE.json")
        lock = read_json(repository / "control/p2-build-lock.json")

        expected_candidate_hash = (
            "5ee5d5a9d6312c2fe3bf2c3fbf535765321b1cd1f72d610b62188d6b4de4112d"
        )
        expected_repository = (
            "70c6c52f8370701ddfb662f2c6d3a26a772cd68a1db56dbd69c20828d00f58c9",
            19,
        )
        expected_checks = [
            "SOURCE_WORKPACK_AND_BASELINE_HASHES_MATCH",
            "P1_BUILD_LOCK_VALID_PREDECESSOR_HASH_BOUND",
            "P2_BUILD_LAYER_INTERFACE_IS_EXPLICIT",
            "P2_BUILD_LOCK_IS_DETERMINISTIC_AND_FAIL_CLOSED",
            "P2_POSITIVE_NEGATIVE_AND_TAMPER_TESTS_PASS",
            "SOURCE_FAILURE_RETURN_DISCREPANCY_IS_PRESERVED_AND_FAILS_STOPPED",
            "FULL_MAIN_REPOSITORY_TEST_SUITE_PASSES",
            "NO_P3_CERTIFICATION_OR_INSTALL_SCOPE_STARTED",
        ]
        expected_completed = [
            "LAB-PROTOCOL",
            "LAB-CLI",
            "LAB-FIXTURES",
            "LAB-SELFTEST",
            "LINK-PROTOCOL",
            "LINK-CLI",
            "LINK-SELFTEST",
            "WP-vscdsl-video-prompt-harness-G0-001",
            "MB-G0",
            "MB-P1",
            "MB-P2",
        ]
        scope = authorization.get("scope", {})
        acceptance = agent.get("acceptance_checks", [])
        runtime_material = dict(runtime)
        claimed_runtime_hash = runtime_material.pop("state_hash", None)
        lock_material = dict(lock)
        claimed_lock_hash = lock_material.pop("p2_build_lock_sha256", None)
        hash_bindings_valid = True
        for document, excluded_refs in (
            (authorization, {"runtime_state_ref"}),
            (manifest, set()),
            (agent, set()),
            (independent, set()),
            (workpack, set()),
            (result, set()),
            (promotion, set()),
            (completion, set()),
            (descriptor, set()),
        ):
            for key, value in document.items():
                if key.endswith("_ref") and isinstance(value, str):
                    hash_key = f"{key[:-4]}_sha256"
                    if hash_key in document and key not in excluded_refs:
                        hash_bindings_valid = bool(
                            hash_bindings_valid and bound(document, key, hash_key)
                        )

        return bool(
            _candidate_tree_hash(candidate_root) == expected_candidate_hash
            and repository_hash(repository) == expected_repository
            and expected_launcher.is_file()
            and _file_hash(expected_launcher)
            == "d3c62048f066d3407fd822a7e445772e549e16f4f657314f33100bf63d6340a6"
            and authorization.get("status") == "GRANTED"
            and authorization.get("authorization_id")
            == "AUTH-VSCDSL-MAIN-P2-C2-EXECUTION-V03-001"
            and authorization.get("authorization_scope_sha256") == _json_hash(scope)
            and authorization.get("max_transitions") == 1
            and scope.get("dag_node_ids") == ["MAIN_P2_C2"]
            and scope.get("workpack_ids") == ["MB-P2"]
            and scope.get("pipeline_action_ids") == []
            and "MAIN_P3_C3_OR_APPROVED_NA_EXECUTION"
            in authorization.get("forbidden_actions", [])
            and manifest.get("status") == "READY_NOT_EXECUTED"
            and manifest.get("workpack_id") == "MB-P2"
            and manifest.get("required_acceptance_check_ids") == expected_checks
            and manifest.get("require_changed_files_match_repository_delta") is True
            and agent.get("status") == "PASS"
            and agent.get("workpack_id") == "MB-P2"
            and [item.get("check_id") for item in acceptance] == expected_checks
            and all(item.get("status") == "PASS" for item in acceptance)
            and agent.get("blocking_findings") == []
            and agent.get("main_p3_c3_or_approved_na_started") is False
            and independent.get("status") == "PASS"
            and independent.get("test_count") == 30
            and independent.get("repository_content_sha256")
            == expected_repository[0]
            and workpack.get("status") == "PASS"
            and workpack.get("produced_capability") == "P2_BUILD_LOCK_VALID"
            and result.get("status") == "PASS"
            and result.get("success_gate") == "MAIN_P2_C2_PASS"
            and result.get("next_node_activated") is False
            and promotion.get("status")
            == "PROMOTED_STOPPED_BEFORE_MAIN_P3_C3_OR_APPROVED_NA"
            and promotion.get("next_node_activated") is False
            and completion.get("status")
            == "MAIN_P2_C2_COMPLETE_STOPPED_BEFORE_MAIN_P3_C3_OR_APPROVED_NA"
            and completion.get("main_p3_c3_or_approved_na_started") is False
            and descriptor.get("status")
            == "MAIN_P2_C2_PASS_STOPPED_BEFORE_MAIN_P3_C3_OR_APPROVED_NA"
            and claimed_runtime_hash == _json_hash(runtime_material)
            and claimed_runtime_hash
            == "6fcefbca704a2b475babf100b9d241fc6cb68f947c8c529eb611b6665dd3c803"
            and runtime.get("state_revision") == 40
            and runtime.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and runtime.get("completed_workpack_ids") == expected_completed
            and runtime.get("authorization_consumptions", {}).get(
                authorization.get("authorization_id")
            )
            == 1
            and runtime.get("active_attempt", {}).get("attempt_id") == attempt_id
            and runtime.get("active_attempt", {}).get("status") == "VALIDATED_PASS"
            and state.get("state")
            == "MAIN_P2_C2_PASS_WAITING_MAIN_P3_C3_OR_APPROVED_NA_PREPARATION_AUTHORIZATION"
            and state.get("highest_completed_external_gate") == "MAIN_P2_C2_PASS"
            and state.get("main_p2_c2_started") is True
            and state.get("mb_p2_started") is True
            and state.get("install_started") is False
            and claimed_lock_hash == _json_hash(lock_material)
            and lock.get("produced_capability") == "P2_BUILD_LOCK_VALID"
            and lock.get("requires_capability") == "P1_BUILD_LOCK_VALID"
            and lock.get("failure_contract", {}).get("automatic_reentry") is False
            and not any(lock.get("scope", {}).values())
            and hash_bindings_valid
            and not (evidence / "engineering_dag/MAIN_P3_C3_OR_APPROVED_NA").exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_main_p1_c1_completion(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept the exact repaired, single-retry MB-P1 PASS boundary."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    if command.get("command_id") not in {
        "ROOT-CODEX-CODING",
        "MB-CODEX-CODING",
        "LINK-CODEX-CODING",
        "LAB-CODEX-CODING",
    }:
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        def read_json(path: Path) -> Mapping[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError(f"expected object: {path}")
            return value

        def bound(document: Mapping[str, Any], ref_key: str, hash_key: str) -> bool:
            path = resolve_ref(document.get(ref_key))
            return bool(path.is_file() and document.get(hash_key) == _file_hash(path))

        def repository_hash(root: Path) -> tuple[str, int]:
            digest = hashlib.sha256()
            count = 0
            for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
                if (
                    not path.is_file()
                    or "__pycache__" in path.parts
                    or path.suffix in {".pyc", ".pyo"}
                ):
                    continue
                digest.update(path.relative_to(root).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(_file_hash(path).encode("ascii"))
                digest.update(b"\n")
                count += 1
            return digest.hexdigest(), count

        control = execution_root / "control_plane"
        evidence = execution_root / "evidence"
        planned = execution_root / "planned_executors"
        repository = execution_root / "project_start_packages/main_build/repository"
        attempt_id = "ATTEMPT-1030EB7AC2A24E4BBA8A2C23840EA00A"
        attempt_root = (
            evidence
            / "project_workpacks/MAIN_HARNESS_BUILD/MB-P1/attempts"
            / attempt_id
        )
        repair_auth = read_json(
            control
            / "MAIN_P1_C1_EXECUTOR_CONTEXT_AND_RESULT_COHERENCE_"
            "REPAIR_REVERIFY_AND_RETRY_AUTHORIZATION.json"
        )
        repair_receipt = read_json(
            control / "MAIN_P1_C1_CONTEXT_RESULT_REPAIR_REVERIFICATION_RECEIPT.json"
        )
        authorization = read_json(
            control / "MAIN_P1_C1_CONTEXT_REPAIRED_RETRY_AUTHORIZATION.json"
        )
        manifest = read_json(
            planned / "manifests/MB-P1.context-repaired-retry.resolved-command.json"
        )
        schema = read_json(
            planned / "schemas/MAIN_P1_C1_WORKPACK_RETRY_OUTPUT.schema.json"
        )
        agent = read_json(attempt_root / "MB-P1.agent-result.json")
        independent = read_json(
            evidence
            / "project_workpacks/MAIN_HARNESS_BUILD/MB-P1/"
            "INDEPENDENT_RETRY_VALIDATION_RECEIPT.json"
        )
        workpack = read_json(
            evidence
            / "project_workpacks/MAIN_HARNESS_BUILD/MB-P1/WORKPACK_RESULT.json"
        )
        result = read_json(evidence / "engineering_dag/MAIN_P1_C1.result.json")
        promotion = read_json(
            evidence / "engineering_dag/MAIN_P1_C1.promotion.json"
        )
        completion = read_json(control / "MAIN_P1_C1_COMPLETION_RECEIPT.json")
        descriptor = read_json(
            control / "MAIN_P1_C1_EXECUTOR_DESCRIPTOR_AFTER_EXECUTION.json"
        )
        runtime = read_json(control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json")
        state = read_json(control / "CONTROL_PLANE_STATE.json")
        lock = read_json(repository / "control/p1-build-lock.json")
        p2_receipt_path = control / "MAIN_P2_C2_PREPARATION_RECEIPT.json"
        p2_preparation_present = p2_receipt_path.is_file()
        p2_snapshot: Mapping[str, Any] = {}
        p2_authorization: Mapping[str, Any] = {}
        p2_baseline: Mapping[str, Any] = {}
        p2_contract: Mapping[str, Any] = {}
        p2_schema: Mapping[str, Any] = {}
        p2_manifest: Mapping[str, Any] = {}
        p2_descriptor: Mapping[str, Any] = {}
        p2_boundary: Mapping[str, Any] = {}
        p2_readiness: Mapping[str, Any] = {}
        p2_draft: Mapping[str, Any] = {}
        p2_receipt: Mapping[str, Any] = {}
        if p2_preparation_present:
            p2_snapshot = read_json(
                control / "history/MAIN_P2_C2_PREPARATION.preparation_snapshot.json"
            )
            p2_authorization = read_json(
                control / "MAIN_P2_C2_PREPARATION_AUTHORIZATION.json"
            )
            p2_baseline = read_json(control / "MAIN_P2_C2_BASELINE_LOCK.json")
            p2_contract = read_json(
                planned / "contracts/MAIN_P2_C2_WORKPACK_CONTRACT.json"
            )
            p2_schema = read_json(
                planned / "schemas/MAIN_P2_C2_WORKPACK_OUTPUT.schema.json"
            )
            p2_manifest = read_json(
                planned / "manifests/MB-P2.resolved-command.json"
            )
            p2_descriptor = read_json(
                control / "MAIN_P2_C2_EXECUTOR_DESCRIPTOR.json"
            )
            p2_boundary = read_json(
                evidence
                / "main-p2-c2-preparation/"
                "MAIN_P2_C2_PREPARATION_BOUNDARY_ATTESTATION.json"
            )
            p2_readiness = read_json(
                control / "MAIN_P2_C2_PREPARATION_READINESS_REPORT.json"
            )
            p2_draft = read_json(
                control / "MAIN_P2_C2_EXECUTION_AUTHORIZATION_DRAFT.json"
            )
            p2_receipt = read_json(p2_receipt_path)

        expected_candidate_hash = (
            "5ee5d5a9d6312c2fe3bf2c3fbf535765321b1cd1f72d610b62188d6b4de4112d"
        )
        expected_repository = (
            "3921e19e35d9b68878a5bcd3c3d5daf59044cd031ecf91c3614781886e882846",
            16,
        )
        expected_checks = [
            "SOURCE_WORKPACK_AND_BASELINE_HASHES_MATCH",
            "G0_CONTROL_LOCK_VALID_PREDECESSOR_HASH_BOUND",
            "P1_BUILD_LAYER_INTERFACE_IS_EXPLICIT",
            "P1_BUILD_LOCK_IS_DETERMINISTIC_AND_FAIL_CLOSED",
            "P1_POSITIVE_NEGATIVE_AND_TAMPER_TESTS_PASS",
            "SOURCE_FAILURE_RETURN_DISCREPANCY_IS_PRESERVED_AND_FAILS_STOPPED",
            "FULL_MAIN_REPOSITORY_TEST_SUITE_PASSES",
            "NO_P2_CERTIFICATION_OR_INSTALL_SCOPE_STARTED",
        ]
        changed_files = [
            "README.md",
            "control/p1-build-lock.json",
            "pyproject.toml",
            "src/vscdsl_harness/build_lock.py",
            "tests/test_build_lock.py",
        ]
        expected_completed = [
            "LAB-PROTOCOL",
            "LAB-CLI",
            "LAB-FIXTURES",
            "LAB-SELFTEST",
            "LINK-PROTOCOL",
            "LINK-CLI",
            "LINK-SELFTEST",
            "WP-vscdsl-video-prompt-harness-G0-001",
            "MB-G0",
            "MB-P1",
        ]
        scope = authorization.get("scope", {})
        acceptance = agent.get("acceptance_checks", [])
        runtime_material = dict(runtime)
        claimed_runtime_hash = runtime_material.pop("state_hash", None)
        schema_properties = schema.get("properties", {})
        hash_bindings_valid = True
        for document, excluded_refs in (
            (repair_auth, {"pre_repair_snapshot_ref"}),
            (repair_receipt, {"runtime_state_ref"}),
            (authorization, {"runtime_state_ref"}),
            (manifest, set()),
            (agent, set()),
            (
                independent,
                {"runtime_state_ref", "transition_ledger_ref", "promotion_ledger_ref"},
            ),
            (workpack, {"runtime_state_ref"}),
            (result, {"runtime_state_ref"}),
            (promotion, set()),
            (completion, {"runtime_state_ref"}),
            (descriptor, {"runtime_state_ref"}),
        ):
            for key, value in document.items():
                if key.endswith("_ref") and isinstance(value, str):
                    hash_key = f"{key[:-4]}_sha256"
                    if hash_key in document and key not in excluded_refs:
                        hash_bindings_valid = bool(
                            hash_bindings_valid and bound(document, key, hash_key)
                        )

        p2_hash_bindings_valid = True
        if p2_preparation_present:
            for document, excluded_refs in (
                (p2_snapshot, {"control_plane_state_ref"}),
                (p2_authorization, set()),
                (p2_baseline, set()),
                (p2_contract, set()),
                (p2_manifest, set()),
                (p2_descriptor, set()),
                (p2_boundary, set()),
                (p2_readiness, set()),
                (p2_draft, set()),
                (p2_receipt, set()),
            ):
                for key, value in document.items():
                    if key.endswith("_ref") and isinstance(value, str):
                        hash_key = f"{key[:-4]}_sha256"
                        if hash_key in document and key not in excluded_refs:
                            p2_hash_bindings_valid = bool(
                                p2_hash_bindings_valid
                                and bound(document, key, hash_key)
                            )

        p2_scope = p2_authorization.get("scope", {})
        p2_execution_scope = p2_draft.get("scope", {})
        p2_properties = p2_schema.get("properties", {})
        p2_preparation_valid = bool(
            not p2_preparation_present
            or (
                p2_snapshot.get("status") == "HASH_BOUND_PREPARATION_SNAPSHOT"
                and p2_snapshot.get("authorization_text")
                == "授权MAIN_P2_C2_PREPARATION"
                and p2_snapshot.get("runtime_state_revision") == 38
                and p2_snapshot.get("main_p2_c2_started") is False
                and p2_authorization.get("status")
                == "GRANTED_AND_CONSUMED_PREPARATION_ONLY"
                and p2_authorization.get("authorization_scope_sha256")
                == _json_hash(p2_scope)
                and p2_authorization.get("max_driver_transitions") == 0
                and p2_authorization.get("execution_authorized") is False
                and p2_authorization.get("driver_execution_authorized") is False
                and p2_scope.get("dag_node_ids") == ["MAIN_P2_C2"]
                and p2_scope.get("workpack_ids") == ["MB-P2"]
                and p2_scope.get("execution_modes") == ["PREPARATION_ONLY"]
                and p2_baseline.get("status")
                == "LOCKED_FOR_MAIN_P2_C2_PREPARATION"
                and p2_baseline.get("candidate_content_sha256")
                == expected_candidate_hash
                and p2_baseline.get("main_repository", {}).get("content_sha256")
                == expected_repository[0]
                and p2_baseline.get("main_repository", {}).get("content_file_count")
                == expected_repository[1]
                and p2_baseline.get("runtime_binding", {}).get(
                    "runtime_state_revision"
                )
                == 38
                and p2_baseline.get("candidate_node_contract", {}).get("node_id")
                == "MAIN_P2_C2"
                and p2_baseline.get("candidate_node_contract", {}).get(
                    "workpack_id"
                )
                == "MB-P2"
                and p2_baseline.get("failure_return_contract", {}).get(
                    "candidate_dag_failure_return_node"
                )
                == "MAIN_P1_C1"
                and p2_baseline.get("failure_return_contract", {}).get(
                    "candidate_workpack_return_node"
                )
                == "MAIN_P2_C2"
                and p2_contract.get("workpack_id") == "MB-P2"
                and p2_contract.get("node_id") == "MAIN_P2_C2"
                and p2_contract.get("baseline_sha256")
                == _file_hash(control / "MAIN_P2_C2_BASELINE_LOCK.json")
                and p2_contract.get("required_input_capabilities")
                == ["CHARTER_LOCK_VALID", "P1_BUILD_LOCK_VALID"]
                and p2_contract.get("intent_atom_ids") == []
                and p2_manifest.get("status") == "READY_NOT_EXECUTED"
                and p2_manifest.get("workpack_id") == "MB-P2"
                and p2_manifest.get("auto_execute") is False
                and p2_manifest.get("execution_started") is False
                and p2_manifest.get("main_p2_c2_baseline_sha256")
                == _file_hash(control / "MAIN_P2_C2_BASELINE_LOCK.json")
                and p2_manifest.get("main_p2_c2_contract_sha256")
                == _file_hash(
                    planned / "contracts/MAIN_P2_C2_WORKPACK_CONTRACT.json"
                )
                and p2_manifest.get("output_schema_sha256")
                == _file_hash(
                    planned / "schemas/MAIN_P2_C2_WORKPACK_OUTPUT.schema.json"
                )
                and "{attempt_id}"
                in str(p2_manifest.get("result_output_template_abs"))
                and p2_properties.get("workpack_id", {}).get("const") == "MB-P2"
                and p2_properties.get("produced_capability", {}).get("const")
                == "P2_BUILD_LOCK_VALID"
                and p2_descriptor.get("status")
                == "PREPARED_VERIFIED_NOT_INVOKED_FOR_MAIN_P2_C2"
                and p2_descriptor.get("agent_invoked_for_main_p2_c2") is False
                and p2_descriptor.get("main_p2_c2_started") is False
                and p2_descriptor.get("mb_p2_started") is False
                and p2_boundary.get("status")
                == "PASS_PREPARATION_ONLY_NO_MAIN_P2_C2_EXECUTION"
                and p2_boundary.get("driver_execution_transitions_consumed") == 0
                and p2_boundary.get("main_p2_c2_execution_started") is False
                and p2_readiness.get("technical_preparation_status") == "PASS"
                and p2_readiness.get("main_p2_c2_started") is False
                and p2_readiness.get("mb_p2_started") is False
                and p2_draft.get("status") == "DRAFT_READY_NOT_GRANTED"
                and p2_draft.get("authorization_scope_sha256")
                == _json_hash(p2_execution_scope)
                and p2_draft.get("grantable") is False
                and p2_draft.get("execution_authorized") is False
                and p2_draft.get("max_transitions") == 0
                and p2_execution_scope.get("dag_node_ids") == ["MAIN_P2_C2"]
                and p2_execution_scope.get("workpack_ids") == ["MB-P2"]
                and p2_receipt.get("status")
                == "COMPLETE_READY_FOR_EXPLICIT_MAIN_P2_C2_EXECUTION_AUTHORIZATION"
                and p2_receipt.get("driver_execution_transitions_consumed") == 0
                and p2_receipt.get("workpack_execution_started") is False
                and p2_receipt.get("main_p2_c2_started") is False
                and p2_hash_bindings_valid
                and not (
                    evidence / "project_workpacks/MAIN_HARNESS_BUILD/MB-P2"
                ).exists()
                and not (evidence / "engineering_dag/MAIN_P2_C2").exists()
                and not (
                    evidence / "engineering_dag/MAIN_P2_C2.result.json"
                ).exists()
                and not (
                    evidence / "engineering_dag/MAIN_P2_C2.promotion.json"
                ).exists()
            )
        )

        return bool(
            _candidate_tree_hash(candidate_root) == expected_candidate_hash
            and repository_hash(repository) == expected_repository
            and executable_path.is_file()
            and repair_auth.get("status")
            == "GRANTED_REPAIR_REVERIFY_AND_SINGLE_RETRY_PREPARATION"
            and repair_auth.get("driver_transitions_during_repair") == 0
            and repair_receipt.get("status")
            == "COMPLETE_READY_FOR_SINGLE_HASH_BOUND_MB_P1_RETRY"
            and authorization.get("status") == "GRANTED"
            and authorization.get("authorization_id")
            == "AUTH-VSCDSL-MAIN-P1-C1-CONTEXT-REPAIRED-RETRY-V03-001"
            and authorization.get("authorization_scope_sha256") == _json_hash(scope)
            and authorization.get("max_transitions") == 1
            and scope.get("dag_node_ids") == ["MAIN_P1_C1"]
            and scope.get("workpack_ids") == ["MB-P1"]
            and scope.get("pipeline_action_ids") == []
            and "MAIN_P2_C2_EXECUTION"
            in authorization.get("forbidden_actions", [])
            and manifest.get("status") == "READY_NOT_EXECUTED"
            and manifest.get("workpack_id") == "MB-P1"
            and manifest.get("required_acceptance_check_ids") == expected_checks
            and manifest.get("require_changed_files_match_repository_delta") is True
            and "{attempt_id}" in manifest.get("result_output_template_abs", "")
            and schema_properties.get("workpack_id", {}).get("const") == "MB-P1"
            and schema_properties.get("acceptance_checks", {}).get("minItems") == 8
            and schema_properties.get("acceptance_checks", {}).get("maxItems") == 8
            and agent.get("status") == "PASS"
            and agent.get("workpack_id") == "MB-P1"
            and [item.get("check_id") for item in acceptance] == expected_checks
            and all(item.get("status") == "PASS" for item in acceptance)
            and agent.get("blocking_findings") == []
            and agent.get("changed_files") == changed_files
            and independent.get("status") == "PASS"
            and independent.get("test_count") == 26
            and independent.get("repository_content_sha256")
            == expected_repository[0]
            and workpack.get("status") == "PASS"
            and workpack.get("produced_capability") == "P1_BUILD_LOCK_VALID"
            and workpack.get("authorization_transitions_consumed") == 1
            and result.get("status") == "PASS"
            and result.get("success_gate") == "MAIN_P1_C1_PASS"
            and result.get("next_node_activated") is False
            and promotion.get("status")
            == "PROMOTED_STOPPED_BEFORE_MAIN_P2_C2"
            and promotion.get("next_node_activated") is False
            and completion.get("status")
            == "MAIN_P1_C1_COMPLETE_STOPPED_BEFORE_MAIN_P2_C2"
            and completion.get("main_p2_c2_started") is False
            and descriptor.get("status")
            == "MAIN_P1_C1_PASS_STOPPED_BEFORE_MAIN_P2_C2"
            and claimed_runtime_hash == _json_hash(runtime_material)
            and claimed_runtime_hash
            == "0e410b6e33bec0594b3d1df86677d3ef158317287b986f9b297347ad8324fa14"
            and runtime.get("state_revision") == 38
            and runtime.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and runtime.get("active_dag_node") is None
            and runtime.get("completed_workpack_ids") == expected_completed
            and runtime.get("authorization_consumptions", {}).get(
                authorization.get("authorization_id")
            )
            == 1
            and runtime.get("active_attempt", {}).get("attempt_id") == attempt_id
            and runtime.get("active_attempt", {}).get("status") == "VALIDATED_PASS"
            and p2_preparation_valid
            and state.get("state")
            == (
                "MAIN_P2_C2_PREPARED_WAITING_EXECUTION_AUTHORIZATION"
                if p2_preparation_present
                else "MAIN_P1_C1_PASS_WAITING_MAIN_P2_C2_PREPARATION_AUTHORIZATION"
            )
            and state.get("highest_completed_external_gate") == "MAIN_P1_C1_PASS"
            and state.get("open_blocker_codes")
            == (
                ["MAIN_P2_C2_EXECUTION_AUTHORIZATION_REQUIRED"]
                if p2_preparation_present
                else ["MAIN_P2_C2_PREPARATION_AUTHORIZATION_REQUIRED"]
            )
            and state.get("next_eligible_action")
            == (
                "OBTAIN_MAIN_P2_C2_EXECUTION_AUTHORIZATION"
                if p2_preparation_present
                else "OBTAIN_MAIN_P2_C2_PREPARATION_AUTHORIZATION"
            )
            and state.get("projects", {}).get("MAIN_HARNESS_BUILD")
            == (
                "MAIN_P2_C2_PREPARED_NOT_AUTHORIZED"
                if p2_preparation_present
                else "MAIN_P1_C1_PASS_COMPLETE_STOPPED_BEFORE_MAIN_P2_C2"
            )
            and state.get("main_p2_c2_started") is False
            and (
                not p2_preparation_present
                or state.get("mb_p2_started") is False
            )
            and state.get("install_started") is False
            and lock.get("produced_capability") == "P1_BUILD_LOCK_VALID"
            and lock.get("requires_capability") == "G0_CONTROL_LOCK_VALID"
            and lock.get("failure_contract", {}).get("automatic_reentry") is False
            and not any(lock.get("scope", {}).values())
            and hash_bindings_valid
            and not (evidence / "engineering_dag/MAIN_P1_C1").exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_main_p1_c1_failure(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept the exact one-transition MB-P1 no-code fail-stop boundary."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    if command.get("command_id") not in {
        "ROOT-CODEX-CODING",
        "MB-CODEX-CODING",
        "LINK-CODEX-CODING",
        "LAB-CODEX-CODING",
    }:
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        def read_json(path: Path) -> Mapping[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError(f"expected object: {path}")
            return value

        def bound(document: Mapping[str, Any], ref_key: str, hash_key: str) -> bool:
            path = resolve_ref(document.get(ref_key))
            return bool(path.is_file() and document.get(hash_key) == _file_hash(path))

        def repository_hash(root: Path) -> tuple[str, int]:
            digest = hashlib.sha256()
            count = 0
            for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
                if (
                    not path.is_file()
                    or "__pycache__" in path.parts
                    or path.suffix in {".pyc", ".pyo"}
                ):
                    continue
                digest.update(path.relative_to(root).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(_file_hash(path).encode("ascii"))
                digest.update(b"\n")
                count += 1
            return digest.hexdigest(), count

        control = execution_root / "control_plane"
        evidence = execution_root / "evidence"
        attempt_id = "ATTEMPT-68E74B6A14074D5C972FAA096C7EF2F9"
        attempt_root = (
            evidence
            / "project_workpacks/MAIN_HARNESS_BUILD/MB-P1/attempts"
            / attempt_id
        )
        authorization = read_json(
            control / "MAIN_P1_C1_EXECUTION_AUTHORIZATION.json"
        )
        agent = read_json(attempt_root / "MB-P1.agent-result.json")
        independent = read_json(
            evidence
            / "project_workpacks/MAIN_HARNESS_BUILD/MB-P1/"
            "INDEPENDENT_FAILURE_VERIFICATION_RECEIPT.json"
        )
        workpack_result = read_json(
            evidence
            / "project_workpacks/MAIN_HARNESS_BUILD/MB-P1/FAILED_WORKPACK_RESULT.json"
        )
        failure_result = read_json(
            evidence / "engineering_dag/MAIN_P1_C1.failure-result.json"
        )
        failure_receipt = read_json(control / "MAIN_P1_C1_FAILURE_RECEIPT.json")
        descriptor = read_json(
            control / "MAIN_P1_C1_EXECUTOR_DESCRIPTOR_AFTER_FAILURE.json"
        )
        runtime = read_json(control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json")
        state = read_json(control / "CONTROL_PLANE_STATE.json")
        repository = execution_root / "project_start_packages/main_build/repository"
        evidence_root = evidence / "project_workpacks/MAIN_HARNESS_BUILD/MB-P1"

        expected_candidate_hash = (
            "5ee5d5a9d6312c2fe3bf2c3fbf535765321b1cd1f72d610b62188d6b4de4112d"
        )
        expected_repository = (
            "da4b17a5d68403dc5aaa59aeff1bbb29776c3f06d165c481f923124546ce9c63",
            13,
        )
        expected_runtime_hash = (
            "66587dcefcca8d04b8d168b1c6da76e7fc871fb2055fbf6e713a5e3fac4119aa"
        )
        expected_text = (
            "授权 MAIN_P1_C1_EXECUTION，仅允许 Driver 执行一次 Hash 绑定的 MB-P1 "
            "Workpack，完成 MAIN_P1_C1 的 P1 构建锁并生成结果、晋级和独立验证证据；"
            "不授权 MAIN_P2_C2、任何后续 Main Workpack、认证、其他 Workpack、其他 "
            "Pipeline Action 或任何安装。"
        )
        expected_blockers = [
            "MAIN_P1_C1_WORKPACK_ACCEPTANCE_CHECKS_FAILED",
            "MAIN_P1_C1_NO_CODE_OR_TEST_CHANGES",
            "MAIN_P1_C1_RETRY_REAUTHORIZATION_REQUIRED",
        ]
        expected_failed_checks = [
            "P1_BUILD_LAYER_INTERFACE_IS_EXPLICIT",
            "P1_BUILD_LOCK_IS_DETERMINISTIC_AND_FAIL_CLOSED",
            "P1_POSITIVE_NEGATIVE_AND_TAMPER_TESTS_PASS",
            "FULL_MAIN_REPOSITORY_TEST_SUITE_PASSES",
        ]
        expected_files = {
            "FAILED_WORKPACK_RESULT.json",
            "INDEPENDENT_FAILURE_VERIFICATION_RECEIPT.json",
            f"attempts/{attempt_id}/MB-P1.agent-result.json",
            f"attempts/{attempt_id}/MB-P1.stderr",
            f"attempts/{attempt_id}/MB-P1.stdout",
        }
        actual_files = {
            path.relative_to(evidence_root).as_posix()
            for path in evidence_root.rglob("*")
            if path.is_file()
        }
        runtime_material = dict(runtime)
        claimed_runtime_hash = runtime_material.pop("state_hash", None)
        scope = authorization.get("scope", {})
        failed_checks = [
            item.get("check_id")
            for item in agent.get("acceptance_checks", [])
            if item.get("status") == "FAIL"
        ]
        state_p1 = state.get("main_p1_c1", {})

        hash_bindings_valid = True
        for document, excluded_refs in (
            (authorization, {"runtime_state_ref"}),
            (agent, set()),
            (
                independent,
                {
                    "driver_runtime_state_ref",
                    "promotion_ledger_ref",
                    "transition_ledger_ref",
                },
            ),
            (workpack_result, set()),
            (failure_result, set()),
            (
                failure_receipt,
                {
                    "promotion_ledger_ref",
                    "runtime_state_after_failure_ref",
                    "transition_ledger_ref",
                },
            ),
            (descriptor, {"runtime_state_ref"}),
            (state_p1, set()),
        ):
            for key, value in document.items():
                if (
                    key.endswith("_ref")
                    and isinstance(value, str)
                    and key not in excluded_refs
                ):
                    hash_key = f"{key[:-4]}_sha256"
                    if hash_key in document:
                        hash_bindings_valid = bool(
                            hash_bindings_valid and bound(document, key, hash_key)
                        )

        return bool(
            _candidate_tree_hash(candidate_root) == expected_candidate_hash
            and repository_hash(repository) == expected_repository
            and executable_path.is_file()
            and authorization.get("status") == "GRANTED"
            and authorization.get("authorization_id")
            == "AUTH-VSCDSL-MAIN-P1-C1-EXECUTION-V03-001"
            and authorization.get("candidate_content_sha256")
            == expected_candidate_hash
            and authorization.get("authorization_scope_sha256")
            == _json_hash(scope)
            and authorization.get("max_transitions") == 1
            and authorization.get("granted_transitions") == 1
            and authorization.get("may_auto_advance") is False
            and authorization.get("decision_evidence", {}).get("confirmation_text")
            == expected_text
            and scope.get("dag_node_ids") == ["MAIN_P1_C1"]
            and scope.get("workpack_ids") == ["MB-P1"]
            and scope.get("pipeline_action_ids") == []
            and scope.get("execution_modes") == ["WORKPACK_EXECUTION"]
            and "MAIN_P2_C2_EXECUTION"
            in authorization.get("forbidden_actions", [])
            and "OTHER_WORKPACK_EXECUTION"
            in authorization.get("forbidden_actions", [])
            and "OTHER_PIPELINE_ACTION_EXECUTION"
            in authorization.get("forbidden_actions", [])
            and "INSTALL" in authorization.get("forbidden_actions", [])
            and agent.get("status") == "PASS"
            and agent.get("workpack_id") == "MB-P1"
            and agent.get("changed_files") == ["pending"]
            and agent.get("blocking_findings") == []
            and failed_checks == expected_failed_checks
            and independent.get("status") == "FAIL_CONFIRMED_NO_P1_CODE_STOPPED"
            and independent.get("attempt_id") == attempt_id
            and independent.get("blocking_findings") == expected_blockers
            and independent.get("main_repository_content_sha256")
            == expected_repository[0]
            and independent.get("main_repository_content_file_count")
            == expected_repository[1]
            and independent.get("main_repository_existing_test_count") == 22
            and independent.get("main_p1_c1_promotion_created") is False
            and workpack_result.get("status") == "FAIL_STOPPED_NO_CODE"
            and workpack_result.get("failed_acceptance_check_ids")
            == expected_failed_checks
            and workpack_result.get("authorization_transitions_consumed") == 1
            and workpack_result.get("promotion_created") is False
            and failure_result.get("status") == "FAIL_STOPPED_NO_P1_CODE"
            and failure_result.get("completed_workpack_ids") == []
            and failure_result.get("stop_on_failure_enforced") is True
            and failure_result.get("promotion_created") is False
            and failure_receipt.get("status") == "FAILED_NO_P1_CODE_STOPPED"
            and failure_receipt.get("authorization_transitions_consumed") == 1
            and failure_receipt.get("code_files_written") == []
            and failure_receipt.get("next_workpack_started") is False
            and descriptor.get("status")
            == "MAIN_P1_C1_FAILED_NO_CODE_DRIVER_BLOCKED"
            and descriptor.get("agent_invocation_count") == 10
            and descriptor.get("main_p1_c1_started") is True
            and descriptor.get("main_p1_c1_completed") is False
            and descriptor.get("mb_p1_started") is True
            and descriptor.get("mb_p1_completed") is False
            and claimed_runtime_hash == _json_hash(runtime_material)
            and claimed_runtime_hash == expected_runtime_hash
            and runtime.get("state_revision") == 36
            and runtime.get("driver_status") == "BLOCKED_WORKPACK_VALIDATION_FAIL"
            and runtime.get("active_dag_node") == "MAIN_P1_C1"
            and runtime.get("active_workpack_id") is None
            and runtime.get("active_pipeline_action_id") is None
            and runtime.get("side_effects_allowed") is False
            and runtime.get("authorization_consumptions", {}).get(
                "AUTH-VSCDSL-MAIN-P1-C1-EXECUTION-V03-001"
            )
            == 1
            and runtime.get("active_attempt", {}).get("attempt_id") == attempt_id
            and runtime.get("active_attempt", {}).get("status")
            == "VALIDATED_FAIL"
            and "MB-P1" not in runtime.get("completed_workpack_ids", [])
            and state.get("state")
            == "MAIN_P1_C1_BLOCKED_NO_CODE_WAITING_REPAIR_RETRY_AUTHORIZATION"
            and state.get("highest_completed_external_gate") == "MAIN_G0_C0_PASS"
            and state.get("open_blocker_codes") == expected_blockers
            and state.get("next_eligible_action")
            == "OBTAIN_MAIN_P1_C1_EXECUTOR_CONTEXT_AND_RESULT_COHERENCE_REPAIR_REVERIFY_AND_RETRY_AUTHORIZATION"
            and state.get("main_p1_c1_started") is True
            and state.get("mb_p1_started") is True
            and state.get("main_p2_c2_started") is False
            and state.get("install_started") is False
            and state_p1.get("status") == "FAIL_STOPPED_NO_P1_CODE"
            and state_p1.get("completed_workpack_ids") == []
            and state_p1.get("promotion_created") is False
            and actual_files == expected_files
            and hash_bindings_valid
            and not (evidence / "engineering_dag/MAIN_P1_C1").exists()
            and not (evidence / "engineering_dag/MAIN_P1_C1.result.json").exists()
            and not (evidence / "engineering_dag/MAIN_P1_C1.promotion.json").exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_main_p1_c1_preparation(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept Hash-bound MAIN_P1_C1 preparation without executing MB-P1."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    if command.get("command_id") not in {
        "ROOT-CODEX-CODING",
        "MB-CODEX-CODING",
        "LINK-CODEX-CODING",
        "LAB-CODEX-CODING",
    }:
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        def read_json(path: Path) -> Mapping[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError(f"expected object: {path}")
            return value

        def bound(document: Mapping[str, Any], ref_key: str, hash_key: str) -> bool:
            path = resolve_ref(document.get(ref_key))
            return bool(path.is_file() and document.get(hash_key) == _file_hash(path))

        def repository_hash(root: Path) -> tuple[str, int]:
            digest = hashlib.sha256()
            count = 0
            for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
                if (
                    not path.is_file()
                    or "__pycache__" in path.parts
                    or path.suffix in {".pyc", ".pyo"}
                ):
                    continue
                digest.update(path.relative_to(root).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(_file_hash(path).encode("ascii"))
                digest.update(b"\n")
                count += 1
            return digest.hexdigest(), count

        control = execution_root / "control_plane"
        evidence = execution_root / "evidence"
        planned = execution_root / "planned_executors"
        authorization_path = control / "MAIN_P1_C1_PREPARATION_AUTHORIZATION.json"
        snapshot_path = (
            control / "history/MAIN_P1_C1_PREPARATION.preparation_snapshot.json"
        )
        baseline_path = control / "MAIN_P1_C1_BASELINE_LOCK.json"
        contract_path = planned / "contracts/MAIN_P1_C1_WORKPACK_CONTRACT.json"
        schema_path = planned / "schemas/MAIN_P1_C1_WORKPACK_OUTPUT.schema.json"
        manifest_path = planned / "manifests/MB-P1.resolved-command.json"
        descriptor_path = control / "MAIN_P1_C1_EXECUTOR_DESCRIPTOR.json"
        boundary_path = (
            evidence
            / "main-p1-c1-preparation/MAIN_P1_C1_PREPARATION_BOUNDARY_ATTESTATION.json"
        )
        readiness_path = control / "MAIN_P1_C1_PREPARATION_READINESS_REPORT.json"
        draft_path = control / "MAIN_P1_C1_EXECUTION_AUTHORIZATION_DRAFT.json"
        receipt_path = control / "MAIN_P1_C1_PREPARATION_RECEIPT.json"
        runtime_path = control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json"
        state_path = control / "CONTROL_PLANE_STATE.json"
        repository = execution_root / "project_start_packages/main_build/repository"

        authorization = read_json(authorization_path)
        snapshot = read_json(snapshot_path)
        baseline = read_json(baseline_path)
        contract = read_json(contract_path)
        schema = read_json(schema_path)
        manifest = read_json(manifest_path)
        descriptor = read_json(descriptor_path)
        boundary = read_json(boundary_path)
        readiness = read_json(readiness_path)
        draft = read_json(draft_path)
        receipt = read_json(receipt_path)
        runtime = read_json(runtime_path)
        state = read_json(state_path)

        candidate_hash = _candidate_tree_hash(candidate_root)
        expected_candidate_hash = (
            "5ee5d5a9d6312c2fe3bf2c3fbf535765321b1cd1f72d610b62188d6b4de4112d"
        )
        expected_repository = (
            "da4b17a5d68403dc5aaa59aeff1bbb29776c3f06d165c481f923124546ce9c63",
            13,
        )
        expected_runtime_hash = (
            "0cef58a89b809362e61671ee789499a2bcb110ca92213a407b04c4992e060b2a"
        )
        expected_preparation_text = "授权进行"
        expected_execution_text = (
            "授权 MAIN_P1_C1_EXECUTION，仅允许 Driver 执行一次 Hash 绑定的 MB-P1 "
            "Workpack，完成 MAIN_P1_C1 的 P1 构建锁并生成结果、晋级和独立验证证据；"
            "不授权 MAIN_P2_C2、任何后续 Main Workpack、认证、其他 Workpack、其他 "
            "Pipeline Action 或任何安装。"
        )
        runtime_material = dict(runtime)
        claimed_runtime_hash = runtime_material.pop("state_hash", None)
        preparation_scope = authorization.get("scope", {})
        execution_scope = draft.get("scope", {})
        schema_properties = schema.get("properties", {})
        boundary_checks = boundary.get("checks", [])
        main_state = state.get("main_p1_c1_preparation", {})
        baseline_node = baseline.get("candidate_node_contract", {})
        baseline_failure = baseline.get("failure_return_contract", {})
        contract_failure = contract.get("failure_policy", {})

        hash_bindings_valid = True
        for document, excluded_refs in (
            (snapshot, {"control_plane_state_ref"}),
            (authorization, set()),
            (baseline, set()),
            (contract, set()),
            (manifest, set()),
            (descriptor, set()),
            (boundary, set()),
            (readiness, set()),
            (draft, set()),
            (receipt, set()),
            (main_state, set()),
        ):
            for key, value in document.items():
                if (
                    key.endswith("_ref")
                    and isinstance(value, str)
                    and key not in excluded_refs
                ):
                    hash_key = f"{key[:-4]}_sha256"
                    if hash_key in document:
                        hash_bindings_valid = bool(
                            hash_bindings_valid and bound(document, key, hash_key)
                        )

        return bool(
            candidate_hash == expected_candidate_hash
            and repository_hash(repository) == expected_repository
            and executable_path.is_file()
            and authorization.get("status")
            == "GRANTED_AND_CONSUMED_PREPARATION_ONLY"
            and authorization.get("authorization_class")
            == "PROGRAM_EXECUTION_PREPARATION_AUTHORIZATION"
            and authorization.get("candidate_content_sha256") == candidate_hash
            and authorization.get("authorization_scope_sha256")
            == _json_hash(preparation_scope)
            and authorization.get("preparation_only") is True
            and authorization.get("execution_authorized") is False
            and authorization.get("driver_execution_authorized") is False
            and authorization.get("max_driver_transitions") == 0
            and authorization.get("may_auto_advance") is False
            and authorization.get("decision_evidence", {}).get("confirmation_text")
            == expected_preparation_text
            and authorization.get("decision_evidence", {}).get(
                "confirmation_interpretation"
            )
            == "PRIOR_EXPLICIT_NEXT_ACTION_MAIN_P1_C1_PREPARATION_ONLY"
            and preparation_scope.get("dag_node_ids") == ["MAIN_P1_C1"]
            and preparation_scope.get("workpack_ids") == ["MB-P1"]
            and preparation_scope.get("pipeline_action_ids") == []
            and preparation_scope.get("execution_modes") == ["PREPARATION_ONLY"]
            and "MB_P1_EXECUTION" in authorization.get("forbidden_actions", [])
            and "MAIN_P2_C2_EXECUTION"
            in authorization.get("forbidden_actions", [])
            and "INSTALL" in authorization.get("forbidden_actions", [])
            and snapshot.get("status") == "HASH_BOUND_PREPARATION_SNAPSHOT"
            and snapshot.get("authorization_text") == expected_preparation_text
            and snapshot.get("runtime_state_revision") == 34
            and snapshot.get("runtime_state_hash") == expected_runtime_hash
            and snapshot.get("main_g0_c0_success_gate") == "MAIN_G0_C0_PASS"
            and snapshot.get("main_p1_c1_started") is False
            and snapshot.get("mb_p1_started") is False
            and baseline.get("status") == "LOCKED_FOR_MAIN_P1_C1_PREPARATION"
            and baseline_node.get("node_id") == "MAIN_P1_C1"
            and baseline_node.get("workpack_id") == "MB-P1"
            and baseline_node.get("predecessor_node_id") == "MAIN_G0_C0"
            and baseline_node.get("next_node_id") == "MAIN_P2_C2"
            and baseline_failure.get("candidate_dag_failure_return_node")
            == "MAIN_G0_C0"
            and baseline_failure.get("candidate_workpack_return_node")
            == "MAIN_P1_C1"
            and baseline.get("main_repository", {}).get("content_sha256")
            == expected_repository[0]
            and contract.get("workpack_id") == "MB-P1"
            and contract.get("node_id") == "MAIN_P1_C1"
            and contract.get("execution_mode") == "WORKPACK_EXECUTION"
            and contract.get("baseline_sha256") == _file_hash(baseline_path)
            and contract.get("intent_atom_ids") == []
            and contract.get("required_input_capabilities")
            == ["CHARTER_LOCK_VALID", "G0_CONTROL_LOCK_VALID"]
            and contract_failure.get("candidate_dag_failure_return_node")
            == "MAIN_G0_C0"
            and contract_failure.get("candidate_workpack_return_node")
            == "MAIN_P1_C1"
            and contract_failure.get("automatic_reentry") is False
            and contract.get("nonclaims", {}).get("main_p2_c2_started") is False
            and contract.get("nonclaims", {}).get("install_performed") is False
            and schema.get("additionalProperties") is False
            and set(schema.get("required", [])) == set(schema_properties)
            and schema_properties.get("status", {}).get("const") == "PASS"
            and schema_properties.get("workpack_id", {}).get("const") == "MB-P1"
            and schema_properties.get("produced_capability", {}).get("const")
            == "P1_BUILD_LOCK_VALID"
            and schema_properties.get("main_p2_c2_started", {}).get("const")
            is False
            and schema_properties.get("install_performed", {}).get("const") is False
            and manifest.get("status") == "READY_NOT_EXECUTED"
            and manifest.get("execution_unit_kind") == "WORKPACK"
            and manifest.get("workpack_id") == "MB-P1"
            and manifest.get("pipeline_action_id") is None
            and manifest.get("auto_execute") is False
            and manifest.get("execution_started") is False
            and manifest.get("intent_atom_ids") == []
            and manifest.get("main_p2_c2_started") is False
            and manifest.get("main_p1_c1_baseline_sha256")
            == _file_hash(baseline_path)
            and manifest.get("main_p1_c1_contract_sha256")
            == _file_hash(contract_path)
            and manifest.get("output_schema_sha256") == _file_hash(schema_path)
            and descriptor.get("status")
            == "PREPARED_VERIFIED_NOT_INVOKED_FOR_MAIN_P1_C1"
            and descriptor.get("runtime_state_revision") == 34
            and descriptor.get("agent_invoked_for_main_p1_c1") is False
            and descriptor.get("main_p1_c1_started") is False
            and descriptor.get("mb_p1_started") is False
            and boundary.get("status")
            == "PASS_PREPARATION_ONLY_NO_MAIN_P1_C1_EXECUTION"
            and boundary.get("blocking_findings") == []
            and len(boundary_checks) == 13
            and all(check.get("status") == "PASS" for check in boundary_checks)
            and boundary.get("driver_execution_transitions_consumed") == 0
            and boundary.get("main_p1_c1_execution_started") is False
            and boundary.get("mb_p1_started") is False
            and readiness.get("status")
            == "READY_FOR_EXPLICIT_MAIN_P1_C1_EXECUTION_AUTHORIZATION_NOT_GRANTED"
            and readiness.get("technical_preparation_status") == "PASS"
            and readiness.get("required_next_authorization_text")
            == expected_execution_text
            and readiness.get("main_p1_c1_started") is False
            and readiness.get("mb_p1_started") is False
            and draft.get("status") == "DRAFT_READY_NOT_GRANTED"
            and draft.get("grantable") is False
            and draft.get("execution_authorized") is False
            and draft.get("driver_execution_authorized") is False
            and draft.get("max_transitions") == 0
            and draft.get("granted_transitions") == 0
            and draft.get("proposed_max_transitions") == 1
            and draft.get("authorization_scope_sha256") == _json_hash(execution_scope)
            and execution_scope.get("dag_node_ids") == ["MAIN_P1_C1"]
            and execution_scope.get("workpack_ids") == ["MB-P1"]
            and execution_scope.get("pipeline_action_ids") == []
            and execution_scope.get("execution_modes") == ["WORKPACK_EXECUTION"]
            and draft.get("required_authorization_text") == expected_execution_text
            and receipt.get("status")
            == "COMPLETE_READY_FOR_EXPLICIT_MAIN_P1_C1_EXECUTION_AUTHORIZATION"
            and receipt.get("authorization_transitions_consumed") == 1
            and receipt.get("driver_execution_transitions_consumed") == 0
            and receipt.get("runtime_state_revision") == 34
            and receipt.get("main_p1_c1_started") is False
            and receipt.get("mb_p1_started") is False
            and receipt.get("workpack_execution_started") is False
            and claimed_runtime_hash == _json_hash(runtime_material)
            and claimed_runtime_hash == expected_runtime_hash
            and runtime.get("state_revision") == 34
            and runtime.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and runtime.get("active_dag_node") is None
            and runtime.get("active_workpack_id") is None
            and runtime.get("active_pipeline_action_id") is None
            and runtime.get("side_effects_allowed") is False
            and runtime.get("completed_workpack_ids", [])[-1:] == ["MB-G0"]
            and "MB-P1" not in runtime.get("completed_workpack_ids", [])
            and state.get("state")
            == "MAIN_P1_C1_PREPARED_WAITING_EXECUTION_AUTHORIZATION"
            and state.get("highest_completed_external_gate") == "MAIN_G0_C0_PASS"
            and state.get("open_blocker_codes")
            == ["MAIN_P1_C1_EXECUTION_AUTHORIZATION_REQUIRED"]
            and state.get("next_eligible_action")
            == "OBTAIN_MAIN_P1_C1_EXECUTION_AUTHORIZATION"
            and state.get("projects", {}).get("MAIN_HARNESS_BUILD")
            == "MAIN_P1_C1_PREPARED_NOT_AUTHORIZED"
            and state.get("main_g0_c0_started") is True
            and state.get("mb_g0_started") is True
            and state.get("main_p1_c1_started") is False
            and state.get("mb_p1_started") is False
            and state.get("main_p2_c2_started") is False
            and state.get("install_started") is False
            and main_state.get("status") == "PASS_PREPARED_NOT_AUTHORIZED"
            and main_state.get("workpack_id") == "MB-P1"
            and hash_bindings_valid
            and not (evidence / "project_workpacks/MAIN_HARNESS_BUILD/MB-P1").exists()
            and not (evidence / "engineering_dag/MAIN_P1_C1").exists()
            and not (evidence / "engineering_dag/MAIN_P1_C1.result.json").exists()
            and not (evidence / "engineering_dag/MAIN_P1_C1.promotion.json").exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_main_g0_c0_completion(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept the exact one-transition MAIN_G0_C0 completion boundary."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    if command.get("command_id") not in {
        "ROOT-CODEX-CODING",
        "MB-CODEX-CODING",
        "LINK-CODEX-CODING",
        "LAB-CODEX-CODING",
    }:
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        def read_json(path: Path) -> Mapping[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError(f"expected object: {path}")
            return value

        def bound(document: Mapping[str, Any], ref_key: str, hash_key: str) -> bool:
            path = resolve_ref(document.get(ref_key))
            return bool(path.is_file() and document.get(hash_key) == _file_hash(path))

        def repository_hash(root: Path) -> tuple[str, int]:
            digest = hashlib.sha256()
            count = 0
            for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
                if (
                    not path.is_file()
                    or "__pycache__" in path.parts
                    or path.suffix in {".pyc", ".pyo"}
                ):
                    continue
                digest.update(path.relative_to(root).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(_file_hash(path).encode("ascii"))
                digest.update(b"\n")
                count += 1
            return digest.hexdigest(), count

        control = execution_root / "control_plane"
        evidence = execution_root / "evidence"
        authorization_path = control / "MAIN_G0_C0_EXECUTION_AUTHORIZATION.json"
        runtime_path = control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json"
        state_path = control / "CONTROL_PLANE_STATE.json"
        manifest_path = (
            execution_root / "planned_executors/manifests/MB-G0.resolved-command.json"
        )
        agent_result_path = (
            evidence
            / "project_workpacks/MAIN_HARNESS_BUILD/MB-G0/attempts/"
            "ATTEMPT-656C0CACAB1F477A818A7E619F391135/MB-G0.agent-result.json"
        )
        independent_path = (
            evidence
            / "project_workpacks/MAIN_HARNESS_BUILD/MB-G0/"
            "INDEPENDENT_VALIDATION_RECEIPT.json"
        )
        workpack_result_path = (
            evidence
            / "project_workpacks/MAIN_HARNESS_BUILD/MB-G0/WORKPACK_RESULT.json"
        )
        result_path = evidence / "engineering_dag/MAIN_G0_C0.result.json"
        promotion_path = evidence / "engineering_dag/MAIN_G0_C0.promotion.json"
        completion_path = control / "MAIN_G0_C0_COMPLETION_RECEIPT.json"
        descriptor_path = control / "MAIN_G0_C0_EXECUTOR_DESCRIPTOR_AFTER_EXECUTION.json"
        repository = execution_root / "project_start_packages/main_build/repository"

        authorization = read_json(authorization_path)
        runtime = read_json(runtime_path)
        state = read_json(state_path)
        manifest = read_json(manifest_path)
        agent_result = read_json(agent_result_path)
        independent = read_json(independent_path)
        workpack_result = read_json(workpack_result_path)
        result = read_json(result_path)
        promotion = read_json(promotion_path)
        completion = read_json(completion_path)
        descriptor = read_json(descriptor_path)

        candidate_hash = _candidate_tree_hash(candidate_root)
        expected_candidate_hash = (
            "5ee5d5a9d6312c2fe3bf2c3fbf535765321b1cd1f72d610b62188d6b4de4112d"
        )
        expected_repository = (
            "da4b17a5d68403dc5aaa59aeff1bbb29776c3f06d165c481f923124546ce9c63",
            13,
        )
        expected_attempt = "ATTEMPT-656C0CACAB1F477A818A7E619F391135"
        expected_text = (
            "授权 MAIN_G0_C0_EXECUTION，仅允许 Driver 执行一次 Hash 绑定的 MB-G0 "
            "Workpack，完成 MAIN_G0_C0 的 G0 控制锁并生成结果、晋级和独立验证证据；"
            "不授权 MAIN_P1_C1、任何后续 Main Workpack、认证、其他 Workpack、其他 "
            "Pipeline Action 或任何安装。"
        )
        scope = authorization.get("scope", {})
        runtime_material = dict(runtime)
        claimed_runtime_hash = runtime_material.pop("state_hash", None)
        agent_checks = agent_result.get("acceptance_checks", [])
        independent_checks = independent.get("checks", [])
        expected_mb_g0_files = {
            "INDEPENDENT_VALIDATION_RECEIPT.json",
            "WORKPACK_RESULT.json",
            f"attempts/{expected_attempt}/MB-G0.agent-result.json",
            f"attempts/{expected_attempt}/MB-G0.stderr",
            f"attempts/{expected_attempt}/MB-G0.stdout",
        }
        mb_g0_root = evidence / "project_workpacks/MAIN_HARNESS_BUILD/MB-G0"
        actual_mb_g0_files = {
            path.relative_to(mb_g0_root).as_posix()
            for path in mb_g0_root.rglob("*")
            if path.is_file()
        }
        hash_bindings_valid = all(
            bound(document, ref_key, hash_key)
            for document, ref_key, hash_key in (
                (authorization, "based_on_authorization_draft_ref", "based_on_authorization_draft_sha256"),
                (authorization, "based_on_preparation_receipt_ref", "based_on_preparation_receipt_sha256"),
                (authorization, "command_manifest_refs", "command_manifest_hashes"),
                (independent, "agent_result_ref", "agent_result_sha256"),
                (workpack_result, "independent_validation_ref", "independent_validation_sha256"),
                (result, "workpack_result_ref", "workpack_result_sha256"),
                (promotion, "result_ref", "result_sha256"),
                (completion, "promotion_ref", "promotion_sha256"),
                (descriptor, "completion_receipt_ref", "completion_receipt_sha256"),
            )
            if isinstance(document.get(ref_key), str)
        )

        return bool(
            candidate_hash == expected_candidate_hash
            and repository_hash(repository) == expected_repository
            and executable_path.is_file()
            and authorization.get("status") == "GRANTED"
            and authorization.get("authorization_class")
            == "PROGRAM_EXECUTION_AUTHORIZATION"
            and authorization.get("authorization_scope_sha256") == _json_hash(scope)
            and authorization.get("max_transitions") == 1
            and authorization.get("granted_transitions") == 1
            and authorization.get("execution_authorized") is True
            and authorization.get("driver_execution_authorized") is True
            and authorization.get("decision_evidence", {}).get("confirmation_text")
            == expected_text
            and scope.get("dag_node_ids") == ["MAIN_G0_C0"]
            and scope.get("workpack_ids") == ["MB-G0"]
            and scope.get("pipeline_action_ids") == []
            and scope.get("execution_modes") == ["WORKPACK_EXECUTION"]
            and manifest.get("workpack_id") == "MB-G0"
            and agent_result.get("status") == "PASS"
            and agent_result.get("produced_capability") == "G0_CONTROL_LOCK_VALID"
            and len(agent_checks) == 10
            and all(item.get("status") == "PASS" for item in agent_checks)
            and independent.get("status") == "PASS"
            and independent.get("test_count") == 22
            and len(independent_checks) == 10
            and all(item.get("status") == "PASS" for item in independent_checks)
            and workpack_result.get("status") == "PASS"
            and result.get("status") == "PASS"
            and result.get("success_gate") == "MAIN_G0_C0_PASS"
            and result.get("next_node_activated") is False
            and promotion.get("status") == "PROMOTED_STOPPED_BEFORE_MAIN_P1_C1"
            and promotion.get("next_node_activated") is False
            and completion.get("status")
            == "MAIN_G0_C0_COMPLETE_STOPPED_BEFORE_MAIN_P1_C1"
            and completion.get("authorization_transitions_consumed") == 1
            and completion.get("main_p1_c1_started") is False
            and completion.get("install_started") is False
            and descriptor.get("status")
            == "MAIN_G0_C0_PASS_STOPPED_BEFORE_MAIN_P1_C1"
            and descriptor.get("agent_invocation_count") == 9
            and runtime.get("state_revision") == 34
            and claimed_runtime_hash == _json_hash(runtime_material)
            and runtime.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and runtime.get("completed_workpack_ids", [])[-1:] == ["MB-G0"]
            and runtime.get("authorization_consumptions", {}).get(
                authorization.get("authorization_id")
            )
            == 1
            and runtime.get("active_dag_node") is None
            and runtime.get("active_workpack_id") is None
            and runtime.get("side_effects_allowed") is False
            and state.get("state")
            == "MAIN_G0_C0_PASS_WAITING_MAIN_P1_C1_PREPARATION_AUTHORIZATION"
            and state.get("highest_completed_external_gate") == "MAIN_G0_C0_PASS"
            and state.get("open_blocker_codes")
            == ["MAIN_P1_C1_PREPARATION_AUTHORIZATION_REQUIRED"]
            and state.get("main_g0_c0_started") is True
            and state.get("mb_g0_started") is True
            and state.get("main_p1_c1_started") is False
            and state.get("install_started") is False
            and actual_mb_g0_files == expected_mb_g0_files
            and hash_bindings_valid
            and not (evidence / "engineering_dag/MAIN_P1_C1").exists()
            and not (
                evidence / "project_workpacks/MAIN_HARNESS_BUILD/MB-P1"
            ).exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_main_g0_c0_preparation(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept Hash-bound MAIN_G0_C0 preparation without Workpack execution."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    if command.get("command_id") not in {
        "ROOT-CODEX-CODING",
        "MB-CODEX-CODING",
        "LINK-CODEX-CODING",
        "LAB-CODEX-CODING",
    }:
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        def read_json(path: Path) -> Mapping[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError(f"expected object: {path}")
            return value

        def bound(document: Mapping[str, Any], ref_key: str, hash_key: str) -> bool:
            path = resolve_ref(document.get(ref_key))
            return bool(path.is_file() and document.get(hash_key) == _file_hash(path))

        def repository_hash(root: Path) -> tuple[str, int]:
            digest = hashlib.sha256()
            count = 0
            for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
                if (
                    not path.is_file()
                    or "__pycache__" in path.parts
                    or path.suffix in {".pyc", ".pyo"}
                ):
                    continue
                digest.update(path.relative_to(root).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(_file_hash(path).encode("ascii"))
                digest.update(b"\n")
                count += 1
            return digest.hexdigest(), count

        control = execution_root / "control_plane"
        evidence = execution_root / "evidence"
        authorization_path = control / "MAIN_G0_C0_PREPARATION_AUTHORIZATION.json"
        snapshot_path = (
            control / "history/MAIN_G0_C0_PREPARATION.preparation_snapshot.json"
        )
        baseline_path = control / "MAIN_G0_C0_BASELINE_LOCK.json"
        contract_path = (
            execution_root
            / "planned_executors/contracts/MAIN_G0_C0_WORKPACK_CONTRACT.json"
        )
        schema_path = (
            execution_root
            / "planned_executors/schemas/MAIN_G0_C0_WORKPACK_OUTPUT.schema.json"
        )
        manifest_path = (
            execution_root / "planned_executors/manifests/MB-G0.resolved-command.json"
        )
        descriptor_path = control / "MAIN_G0_C0_EXECUTOR_DESCRIPTOR.json"
        boundary_path = (
            evidence
            / "main-g0-c0-preparation/MAIN_G0_C0_PREPARATION_BOUNDARY_ATTESTATION.json"
        )
        readiness_path = control / "MAIN_G0_C0_PREPARATION_READINESS_REPORT.json"
        draft_path = control / "MAIN_G0_C0_EXECUTION_AUTHORIZATION_DRAFT.json"
        receipt_path = control / "MAIN_G0_C0_PREPARATION_RECEIPT.json"
        runtime_path = control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json"
        state_path = control / "CONTROL_PLANE_STATE.json"
        repository = execution_root / "project_start_packages/main_build/repository"

        authorization = read_json(authorization_path)
        snapshot = read_json(snapshot_path)
        baseline = read_json(baseline_path)
        contract = read_json(contract_path)
        schema = read_json(schema_path)
        manifest = read_json(manifest_path)
        descriptor = read_json(descriptor_path)
        boundary = read_json(boundary_path)
        readiness = read_json(readiness_path)
        draft = read_json(draft_path)
        receipt = read_json(receipt_path)
        runtime = read_json(runtime_path)
        state = read_json(state_path)

        candidate_hash = _candidate_tree_hash(candidate_root)
        expected_candidate_hash = (
            "5ee5d5a9d6312c2fe3bf2c3fbf535765321b1cd1f72d610b62188d6b4de4112d"
        )
        expected_repository = (
            "4b029fc3c620e04cfd084158dadf313c0c7c99622ad85df348682052928191b2",
            13,
        )
        expected_runtime_hash = (
            "68be8d80a53c595c93e2d3a690e404dafd19345f5d43c71082d7f222a03e69ea"
        )
        expected_runtime_file_hash = (
            "d19aec33947b7f9d440d4ebc0844dd68b06d193ba48f5d5e62b5db5d7d3fba28"
        )
        expected_preparation_text = "授权 MAIN_G0_C0_PREPARATION"
        expected_execution_text = (
            "授权 MAIN_G0_C0_EXECUTION，仅允许 Driver 执行一次 Hash 绑定的 MB-G0 "
            "Workpack，完成 MAIN_G0_C0 的 G0 控制锁并生成结果、晋级和独立验证证据；"
            "不授权 MAIN_P1_C1、任何后续 Main Workpack、认证、其他 Workpack、其他 "
            "Pipeline Action 或任何安装。"
        )
        runtime_material = dict(runtime)
        claimed_runtime_hash = runtime_material.pop("state_hash", None)
        preparation_scope = authorization.get("scope", {})
        execution_scope = draft.get("scope", {})
        schema_properties = schema.get("properties", {})
        boundary_checks = boundary.get("checks", [])
        main_state = state.get("main_g0_c0_preparation", {})

        hash_bindings_valid = True
        for document, excluded_refs in (
            (snapshot, {"control_plane_state_ref"}),
            (authorization, set()),
            (baseline, set()),
            (contract, set()),
            (manifest, set()),
            (descriptor, {"runtime_state_ref"}),
            (boundary, set()),
            (readiness, {"runtime_state_ref"}),
            (draft, {"runtime_state_ref"}),
            (receipt, {"runtime_state_ref"}),
            (main_state, set()),
        ):
            for key, value in document.items():
                if key.endswith("_ref") and isinstance(value, str) and key not in excluded_refs:
                    hash_key = f"{key[:-4]}_sha256"
                    if hash_key in document:
                        hash_bindings_valid = bool(
                            hash_bindings_valid and bound(document, key, hash_key)
                        )

        return bool(
            candidate_hash == expected_candidate_hash
            and repository_hash(repository) == expected_repository
            and executable_path.is_file()
            and authorization.get("status")
            == "GRANTED_AND_CONSUMED_PREPARATION_ONLY"
            and authorization.get("authorization_class")
            == "PROGRAM_EXECUTION_PREPARATION_AUTHORIZATION"
            and authorization.get("candidate_content_sha256") == candidate_hash
            and authorization.get("authorization_scope_sha256")
            == _json_hash(preparation_scope)
            and authorization.get("preparation_only") is True
            and authorization.get("execution_authorized") is False
            and authorization.get("driver_execution_authorized") is False
            and authorization.get("max_driver_transitions") == 0
            and authorization.get("decision_evidence", {}).get("confirmation_text")
            == expected_preparation_text
            and authorization.get("decision_evidence", {}).get(
                "confirmation_text_sha256"
            )
            == hashlib.sha256(expected_preparation_text.encode()).hexdigest()
            and preparation_scope.get("dag_node_ids") == ["MAIN_G0_C0"]
            and preparation_scope.get("workpack_ids") == ["MB-G0"]
            and preparation_scope.get("pipeline_action_ids") == []
            and preparation_scope.get("execution_modes") == ["PREPARATION_ONLY"]
            and "MB_G0_EXECUTION" in authorization.get("forbidden_actions", [])
            and "MAIN_P1_C1_EXECUTION"
            in authorization.get("forbidden_actions", [])
            and "INSTALL" in authorization.get("forbidden_actions", [])
            and snapshot.get("status") == "HASH_BOUND_PREPARATION_SNAPSHOT"
            and snapshot.get("runtime_state_revision") == 32
            and snapshot.get("main_program_registered") is True
            and snapshot.get("main_g0_c0_started") is False
            and snapshot.get("mb_g0_started") is False
            and baseline.get("status") == "LOCKED_FOR_MAIN_G0_C0_PREPARATION"
            and baseline.get("candidate_node_contract", {}).get("node_id")
            == "MAIN_G0_C0"
            and baseline.get("candidate_node_contract", {}).get("workpack_id")
            == "MB-G0"
            and baseline.get("main_repository", {}).get("content_sha256")
            == expected_repository[0]
            and contract.get("workpack_id") == "MB-G0"
            and contract.get("node_id") == "MAIN_G0_C0"
            and contract.get("execution_mode") == "WORKPACK_EXECUTION"
            and contract.get("baseline_sha256") == _file_hash(baseline_path)
            and len(contract.get("intent_atom_ids", [])) == 12
            and contract.get("nonclaims", {}).get("main_p1_c1_started") is False
            and contract.get("nonclaims", {}).get("install_performed") is False
            and schema.get("additionalProperties") is False
            and set(schema.get("required", [])) == set(schema_properties)
            and schema_properties.get("status", {}).get("const") == "PASS"
            and schema_properties.get("workpack_id", {}).get("const") == "MB-G0"
            and schema_properties.get("produced_capability", {}).get("const")
            == "G0_CONTROL_LOCK_VALID"
            and schema_properties.get("main_p1_c1_started", {}).get("const")
            is False
            and schema_properties.get("install_performed", {}).get("const") is False
            and manifest.get("status") == "READY_NOT_EXECUTED"
            and manifest.get("execution_unit_kind") == "WORKPACK"
            and manifest.get("workpack_id") == "MB-G0"
            and manifest.get("pipeline_action_id") is None
            and manifest.get("auto_execute") is False
            and manifest.get("execution_started") is False
            and manifest.get("main_g0_c0_baseline_sha256") == _file_hash(baseline_path)
            and manifest.get("main_g0_c0_contract_sha256") == _file_hash(contract_path)
            and manifest.get("output_schema_sha256") == _file_hash(schema_path)
            and descriptor.get("status")
            == "PREPARED_VERIFIED_NOT_INVOKED_FOR_MAIN_G0_C0"
            and descriptor.get("runtime_state_revision") == 32
            and descriptor.get("main_program_registered") is True
            and descriptor.get("agent_invoked_for_main_g0_c0") is False
            and descriptor.get("mb_g0_started") is False
            and boundary.get("status")
            == "PASS_PREPARATION_ONLY_NO_MAIN_G0_C0_EXECUTION"
            and boundary.get("blocking_findings") == []
            and len(boundary_checks) == 12
            and all(check.get("status") == "PASS" for check in boundary_checks)
            and boundary.get("driver_execution_transitions_consumed") == 0
            and boundary.get("mb_g0_started") is False
            and readiness.get("status")
            == "READY_FOR_EXPLICIT_MAIN_G0_C0_EXECUTION_AUTHORIZATION_NOT_GRANTED"
            and readiness.get("technical_preparation_status") == "PASS"
            and readiness.get("required_next_authorization_text")
            == expected_execution_text
            and readiness.get("main_g0_c0_started") is False
            and readiness.get("mb_g0_started") is False
            and draft.get("status") == "DRAFT_READY_NOT_GRANTED"
            and draft.get("grantable") is False
            and draft.get("execution_authorized") is False
            and draft.get("driver_execution_authorized") is False
            and draft.get("max_transitions") == 0
            and draft.get("granted_transitions") == 0
            and draft.get("proposed_max_transitions") == 1
            and draft.get("authorization_scope_sha256") == _json_hash(execution_scope)
            and execution_scope.get("dag_node_ids") == ["MAIN_G0_C0"]
            and execution_scope.get("workpack_ids") == ["MB-G0"]
            and execution_scope.get("pipeline_action_ids") == []
            and execution_scope.get("execution_modes") == ["WORKPACK_EXECUTION"]
            and draft.get("required_authorization_text") == expected_execution_text
            and receipt.get("status")
            == "COMPLETE_READY_FOR_EXPLICIT_MAIN_G0_C0_EXECUTION_AUTHORIZATION"
            and receipt.get("authorization_transitions_consumed") == 1
            and receipt.get("driver_execution_transitions_consumed") == 0
            and receipt.get("runtime_state_revision") == 32
            and receipt.get("main_g0_c0_started") is False
            and receipt.get("mb_g0_started") is False
            and receipt.get("workpack_execution_started") is False
            and _file_hash(runtime_path) == expected_runtime_file_hash
            and claimed_runtime_hash == _json_hash(runtime_material)
            and claimed_runtime_hash == expected_runtime_hash
            and runtime.get("state_revision") == 32
            and runtime.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and runtime.get("active_dag_node") is None
            and runtime.get("active_workpack_id") is None
            and runtime.get("active_pipeline_action_id") is None
            and runtime.get("side_effects_allowed") is False
            and "MB-G0" not in runtime.get("completed_workpack_ids", [])
            and state.get("state")
            == "MAIN_G0_C0_PREPARED_WAITING_EXECUTION_AUTHORIZATION"
            and state.get("highest_completed_external_gate")
            == "MAIN_PROGRAM_REGISTRATION_PASS"
            and state.get("open_blocker_codes")
            == ["MAIN_G0_C0_EXECUTION_AUTHORIZATION_REQUIRED"]
            and state.get("next_eligible_action")
            == "OBTAIN_MAIN_G0_C0_EXECUTION_AUTHORIZATION"
            and state.get("projects", {}).get("MAIN_HARNESS_BUILD")
            == "MAIN_G0_C0_PREPARED_NOT_AUTHORIZED"
            and state.get("main_program_registered") is True
            and state.get("main_g0_c0_started") is False
            and state.get("mb_g0_started") is False
            and state.get("install_started") is False
            and main_state.get("status") == "PASS_PREPARED_NOT_AUTHORIZED"
            and main_state.get("workpack_id") == "MB-G0"
            and hash_bindings_valid
            and not (evidence / "project_workpacks/MAIN_HARNESS_BUILD/MB-G0").exists()
            and not (evidence / "engineering_dag/MAIN_G0_C0").exists()
            and not (evidence / "engineering_dag/MAIN_G0_C0.result.json").exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_main_registration_completion(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept one Hash-bound Main registration action stopped before MB-G0."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    if command.get("command_id") not in {
        "ROOT-CODEX-CODING",
        "MB-CODEX-CODING",
        "LINK-CODEX-CODING",
        "LAB-CODEX-CODING",
    }:
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        def read_json(path: Path) -> Mapping[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError(f"expected object: {path}")
            return value

        def bound(document: Mapping[str, Any], ref_key: str, hash_key: str) -> bool:
            path = resolve_ref(document.get(ref_key))
            return bool(path.is_file() and document.get(hash_key) == _file_hash(path))

        def repository_hash(root: Path) -> tuple[str, int]:
            digest = hashlib.sha256()
            count = 0
            for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
                if (
                    not path.is_file()
                    or "__pycache__" in path.parts
                    or path.suffix in {".pyc", ".pyo"}
                ):
                    continue
                digest.update(path.relative_to(root).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(_file_hash(path).encode("ascii"))
                digest.update(b"\n")
                count += 1
            return digest.hexdigest(), count

        control = execution_root / "control_plane"
        evidence = execution_root / "evidence"
        output_dir = evidence / "engineering_dag/MAIN_PROGRAM_REGISTRATION"
        authorization_path = (
            control / "MAIN_PROGRAM_REGISTRATION_EXECUTION_AUTHORIZATION.json"
        )
        snapshot_path = (
            control / "history/MAIN_PROGRAM_REGISTRATION.pre_execution_snapshot.json"
        )
        manifest_path = (
            execution_root
            / "planned_executors/manifests/MAIN_PROGRAM_REGISTRATION.resolved-action.json"
        )
        interface_path = output_dir / "MAIN_INTERFACE.realized.json"
        record_path = output_dir / "MAIN_PROGRAM_REGISTRATION_RECORD.json"
        action_result_path = output_dir / "MAIN_PROGRAM_REGISTRATION.action-result.json"
        independent_path = output_dir / "INDEPENDENT_VALIDATION_RECEIPT.json"
        result_path = evidence / "engineering_dag/MAIN_PROGRAM_REGISTRATION.result.json"
        promotion_path = (
            evidence / "engineering_dag/MAIN_PROGRAM_REGISTRATION.promotion.json"
        )
        completion_path = (
            control / "MAIN_PROGRAM_REGISTRATION_COMPLETION_RECEIPT.json"
        )
        descriptor_path = (
            control
            / "MAIN_PROGRAM_REGISTRATION_EXECUTOR_DESCRIPTOR_AFTER_REGISTRATION.json"
        )
        runtime_path = control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json"
        transition_ledger_path = control / "runtime/PHASE_TRANSITION_LEDGER.jsonl"
        promotion_ledger_path = control / "runtime/PROMOTION_LEDGER.jsonl"
        state_path = control / "CONTROL_PLANE_STATE.json"
        repository = execution_root / "project_start_packages/main_build/repository"

        authorization = read_json(authorization_path)
        snapshot = read_json(snapshot_path)
        manifest = read_json(manifest_path)
        interface = read_json(interface_path)
        record = read_json(record_path)
        action_result = read_json(action_result_path)
        independent = read_json(independent_path)
        result = read_json(result_path)
        promotion = read_json(promotion_path)
        completion = read_json(completion_path)
        descriptor = read_json(descriptor_path)
        runtime = read_json(runtime_path)
        state = read_json(state_path)

        transition_events = [
            json.loads(line)
            for line in transition_ledger_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        promotion_events = [
            json.loads(line)
            for line in promotion_ledger_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not all(isinstance(item, dict) for item in transition_events + promotion_events):
            return False

        candidate_hash = _candidate_tree_hash(candidate_root)
        expected_candidate_hash = (
            "5ee5d5a9d6312c2fe3bf2c3fbf535765321b1cd1f72d610b62188d6b4de4112d"
        )
        expected_repository = (
            "4b029fc3c620e04cfd084158dadf313c0c7c99622ad85df348682052928191b2",
            13,
        )
        expected_runtime_hash = (
            "68be8d80a53c595c93e2d3a690e404dafd19345f5d43c71082d7f222a03e69ea"
        )
        expected_runtime_file_hash = (
            "d19aec33947b7f9d440d4ebc0844dd68b06d193ba48f5d5e62b5db5d7d3fba28"
        )
        expected_interface_hash = (
            "3d815911e0c72a48afb44ea5def2b796abbffb4ffe00d9f2995cfbc2d41dc1bd"
        )
        expected_record_hash = (
            "7138e3c70d783015daebabf7ad9814f04191344414f8b5b37dde6162fa165100"
        )
        expected_action_hash = (
            "84df8b4797805d14bde944c36fff923f51c26192ca1fac98271e875bb629c00a"
        )
        expected_independent_hash = (
            "88d38f6c94ec4bb042ea7d3df031be2c4b53168b09b6e9b6dced3e6bd2551161"
        )
        expected_result_hash = (
            "eb12b385de71845e595fa791d640657a72b2f5b0d333e5879150ba9621c1b668"
        )
        expected_promotion_hash = (
            "b4eb301720acb34ce3d518a8a399a956922283e892c1432c97fae40b558cc670"
        )
        expected_text = (
            "授权 MAIN_PROGRAM_REGISTRATION_EXECUTION，仅允许 Driver 执行一次 Hash 绑定的 "
            "MAIN_PROGRAM_REGISTRATION Pipeline Action，登记已验证的 Main execution "
            "package、Main 接口及 Lab/Linkage 接口 Hash 绑定并生成结果、晋级和独立验证证据；"
            "不授权 MB-G0、任何 Main Workpack、认证、其他 Workpack、其他 Pipeline Action "
            "或任何安装。"
        )
        expected_output_files = {
            "INDEPENDENT_VALIDATION_RECEIPT.json",
            "MAIN_INTERFACE.realized.json",
            "MAIN_PROGRAM_REGISTRATION.action-result.json",
            "MAIN_PROGRAM_REGISTRATION.stderr",
            "MAIN_PROGRAM_REGISTRATION.stdout",
            "MAIN_PROGRAM_REGISTRATION_RECORD.json",
        }
        actual_output_files = {
            path.name for path in output_dir.iterdir() if path.is_file()
        }
        scope = authorization.get("scope", {})
        runtime_material = dict(runtime)
        claimed_runtime_hash = runtime_material.pop("state_hash", None)
        action_checks = action_result.get("checks", [])
        independent_checks = independent.get("checks", [])
        final_state = state.get("main_program_registration", {})

        hash_bindings_valid = True
        for document, excluded_refs in (
            (
                snapshot,
                {"control_plane_state_ref", "runtime_state_ref"},
            ),
            (authorization, set()),
            (manifest, set()),
            (independent, set()),
            (result, set()),
            (promotion, set()),
            (completion, set()),
            (descriptor, set()),
            (final_state, set()),
        ):
            for key, value in document.items():
                if key.endswith("_ref") and isinstance(value, str) and key not in excluded_refs:
                    hash_key = f"{key[:-4]}_sha256"
                    if hash_key in document:
                        hash_bindings_valid = bool(
                            hash_bindings_valid and bound(document, key, hash_key)
                        )

        return bool(
            candidate_hash == expected_candidate_hash
            and repository_hash(repository) == expected_repository
            and executable_path.is_file()
            and authorization.get("status") == "GRANTED"
            and authorization.get("authorization_class")
            == "REGISTRATION_AUTHORIZATION"
            and authorization.get("candidate_content_sha256") == candidate_hash
            and authorization.get("max_transitions") == 1
            and authorization.get("granted_transitions") == 1
            and authorization.get("driver_execution_authorized") is True
            and authorization.get("main_program_registration_authorized") is True
            and authorization.get("may_auto_advance") is False
            and authorization.get("authorization_scope_sha256") == _json_hash(scope)
            and scope.get("dag_node_ids") == ["MAIN_PROGRAM_REGISTRATION"]
            and scope.get("pipeline_action_ids") == ["MAIN_PROGRAM_REGISTRATION"]
            and scope.get("workpack_ids") == []
            and scope.get("execution_modes") == ["REGISTRATION_ONLY"]
            and authorization.get("decision_evidence", {}).get("confirmation_text")
            == expected_text
            and authorization.get("decision_evidence", {}).get(
                "confirmation_text_sha256"
            )
            == hashlib.sha256(expected_text.encode()).hexdigest()
            and "MB_G0_EXECUTION" in authorization.get("forbidden_actions", [])
            and "INSTALL" in authorization.get("forbidden_actions", [])
            and snapshot.get("status") == "HASH_BOUND_PRE_EXECUTION_SNAPSHOT"
            and snapshot.get("runtime_state_revision") == 30
            and snapshot.get("main_program_registration_output_directory_existed")
            is False
            and manifest.get("status") == "READY_NOT_EXECUTED"
            and manifest.get("execution_unit_kind") == "PIPELINE_ACTION"
            and manifest.get("pipeline_action_id") == "MAIN_PROGRAM_REGISTRATION"
            and manifest.get("workpack_id") is None
            and manifest.get("auto_execute") is False
            and manifest.get("install_performed") is False
            and _file_hash(interface_path) == expected_interface_hash
            and interface.get("interface_status")
            == "VALIDATED_G0_EXECUTION_PACKAGE_REGISTERED"
            and interface.get("harness_complete") is False
            and interface.get("generation_runtime_available") is False
            and interface.get("resource_payload_migration_complete") is False
            and interface.get("resource_payload_migration_owner") == "MB-P4"
            and _file_hash(record_path) == expected_record_hash
            and record.get("main_program_registered") is True
            and record.get("main_interface_registered") is True
            and record.get("main_and_lab_interfaces_registered") is True
            and record.get("main_interface_sha256") == expected_interface_hash
            and record.get("harness_complete") is False
            and record.get("mb_g0_started") is False
            and record.get("target_installed") is False
            and _file_hash(action_result_path) == expected_action_hash
            and action_result.get("status") == "PASS"
            and action_result.get("pipeline_action_id")
            == "MAIN_PROGRAM_REGISTRATION"
            and action_result.get("blocking_findings") == []
            and len(action_checks) == 9
            and all(check.get("status") == "PASS" for check in action_checks)
            and action_result.get("main_program_registered") is True
            and action_result.get("mb_g0_started") is False
            and action_result.get("harness_complete") is False
            and action_result.get("install_performed") is False
            and _file_hash(independent_path) == expected_independent_hash
            and independent.get("status") == "PASS"
            and independent.get("blocking_findings") == []
            and len(independent_checks) == 10
            and all(check.get("status") == "PASS" for check in independent_checks)
            and independent.get("fresh_independent_validation_exit_code") == 0
            and independent.get("runtime_state_revision") == 32
            and independent.get("runtime_state_hash") == expected_runtime_hash
            and _file_hash(result_path) == expected_result_hash
            and result.get("status") == "PASS"
            and result.get("success_gate") == "MAIN_PROGRAM_REGISTRATION_PASS"
            and result.get("main_program_registered") is True
            and result.get("next_node_activated") is False
            and result.get("mb_g0_started") is False
            and _file_hash(promotion_path) == expected_promotion_hash
            and promotion.get("status") == "PROMOTED_STOPPED_BEFORE_MAIN_G0_C0"
            and promotion.get("next_node_id") == "MAIN_G0_C0"
            and promotion.get("next_node_activated") is False
            and promotion.get("mb_g0_started") is False
            and completion.get("status")
            == "MAIN_PROGRAM_REGISTRATION_COMPLETE_STOPPED_BEFORE_MAIN_G0_C0"
            and completion.get("authorization_transitions_consumed") == 1
            and completion.get("main_program_registered") is True
            and completion.get("next_node_activated") is False
            and completion.get("mb_g0_started") is False
            and descriptor.get("status")
            == "MAIN_PROGRAM_REGISTRATION_PASS_STOPPED_BEFORE_MAIN_G0_C0"
            and descriptor.get("completed_pipeline_action_ids", [])[-1:]
            == ["MAIN_PROGRAM_REGISTRATION"]
            and descriptor.get("main_program_registered") is True
            and descriptor.get("next_node_activated") is False
            and descriptor.get("mb_g0_started") is False
            and _file_hash(runtime_path) == expected_runtime_file_hash
            and claimed_runtime_hash == _json_hash(runtime_material)
            and claimed_runtime_hash == expected_runtime_hash
            and runtime.get("state_revision") == 32
            and runtime.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and runtime.get("completed_pipeline_action_ids", [])[-1:]
            == ["MAIN_PROGRAM_REGISTRATION"]
            and runtime.get("authorization_consumptions", {}).get(
                "AUTH-VSCDSL-MAIN-PROGRAM-REGISTRATION-EXECUTION-V03-001"
            )
            == 1
            and runtime.get("active_dag_node") is None
            and runtime.get("active_pipeline_action_id") is None
            and runtime.get("active_workpack_id") is None
            and runtime.get("side_effects_allowed") is False
            and len(transition_events) == 32
            and transition_events[-1].get("event_hash")
            == runtime.get("last_transition_event_hash")
            and len(promotion_events) == 12
            and promotion_events[-1].get("pipeline_action_id")
            == "MAIN_PROGRAM_REGISTRATION"
            and state.get("state")
            == "MAIN_PROGRAM_REGISTRATION_PASS_WAITING_MAIN_G0_C0_PREPARATION_AUTHORIZATION"
            and state.get("highest_completed_external_gate")
            == "MAIN_PROGRAM_REGISTRATION_PASS"
            and state.get("open_blocker_codes")
            == ["MAIN_G0_C0_PREPARATION_AUTHORIZATION_REQUIRED"]
            and state.get("next_eligible_action")
            == "OBTAIN_MAIN_G0_C0_PREPARATION_AUTHORIZATION"
            and state.get("projects", {}).get("MAIN_HARNESS_BUILD")
            == "PROGRAM_REGISTERED_STOPPED_BEFORE_MAIN_G0_C0"
            and state.get("main_program_registration_started") is True
            and state.get("main_program_registered") is True
            and state.get("install_started") is False
            and final_state.get("status")
            == "PASS_COMPLETE_STOPPED_BEFORE_MAIN_G0_C0"
            and actual_output_files == expected_output_files
            and hash_bindings_valid
            and not (evidence / "project_workpacks/MAIN_HARNESS_BUILD/MB-G0").exists()
            and not (evidence / "engineering_dag/MAIN_G0_C0").exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_main_registration_preparation(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept Hash-bound Main registration preparation without executing it."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    if command.get("command_id") not in {
        "ROOT-CODEX-CODING",
        "MB-CODEX-CODING",
        "LINK-CODEX-CODING",
        "LAB-CODEX-CODING",
    }:
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        def read_json(path: Path) -> Mapping[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError(f"expected object: {path}")
            return value

        def bound(document: Mapping[str, Any], ref_key: str, hash_key: str) -> bool:
            path = resolve_ref(document.get(ref_key))
            return bool(path.is_file() and document.get(hash_key) == _file_hash(path))

        def repository_hash(root: Path) -> tuple[str, int]:
            digest = hashlib.sha256()
            count = 0
            for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
                if (
                    not path.is_file()
                    or "__pycache__" in path.parts
                    or path.suffix in {".pyc", ".pyo"}
                ):
                    continue
                digest.update(path.relative_to(root).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(_file_hash(path).encode("ascii"))
                digest.update(b"\n")
                count += 1
            return digest.hexdigest(), count

        control = execution_root / "control_plane"
        evidence = execution_root / "evidence"
        authorization_path = (
            control / "MAIN_PROGRAM_REGISTRATION_PREPARATION_AUTHORIZATION.json"
        )
        snapshot_path = (
            control
            / "history/MAIN_PROGRAM_REGISTRATION_PREPARATION.preparation_snapshot.json"
        )
        baseline_path = control / "MAIN_PROGRAM_REGISTRATION_BASELINE_LOCK.json"
        contract_path = (
            execution_root
            / "planned_executors/contracts/MAIN_PROGRAM_REGISTRATION_CONTRACT.json"
        )
        schema_path = (
            execution_root
            / "planned_executors/schemas/MAIN_PROGRAM_REGISTRATION_OUTPUT.schema.json"
        )
        manifest_path = (
            execution_root
            / "planned_executors/manifests/MAIN_PROGRAM_REGISTRATION.resolved-action.json"
        )
        descriptor_path = (
            control / "MAIN_PROGRAM_REGISTRATION_EXECUTOR_DESCRIPTOR.json"
        )
        boundary_path = (
            evidence
            / "main-program-registration-preparation/"
            "MAIN_PROGRAM_REGISTRATION_PREPARATION_BOUNDARY_ATTESTATION.json"
        )
        readiness_path = (
            control / "MAIN_PROGRAM_REGISTRATION_PREPARATION_READINESS_REPORT.json"
        )
        draft_path = (
            control / "MAIN_PROGRAM_REGISTRATION_EXECUTION_AUTHORIZATION_DRAFT.json"
        )
        receipt_path = control / "MAIN_PROGRAM_REGISTRATION_PREPARATION_RECEIPT.json"
        runtime_path = control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json"
        state_path = control / "CONTROL_PLANE_STATE.json"
        repository = execution_root / "project_start_packages/main_build/repository"

        authorization = read_json(authorization_path)
        snapshot = read_json(snapshot_path)
        baseline = read_json(baseline_path)
        contract = read_json(contract_path)
        schema = read_json(schema_path)
        manifest = read_json(manifest_path)
        descriptor = read_json(descriptor_path)
        boundary = read_json(boundary_path)
        readiness = read_json(readiness_path)
        draft = read_json(draft_path)
        receipt = read_json(receipt_path)
        runtime = read_json(runtime_path)
        state = read_json(state_path)

        candidate_hash = _candidate_tree_hash(candidate_root)
        expected_candidate_hash = (
            "5ee5d5a9d6312c2fe3bf2c3fbf535765321b1cd1f72d610b62188d6b4de4112d"
        )
        expected_repository = (
            "4b029fc3c620e04cfd084158dadf313c0c7c99622ad85df348682052928191b2",
            13,
        )
        expected_runtime_hash = (
            "4ac8c0334459497a8eed0a6ec7173db8d47b763c852e3283bf14c14f062bcb89"
        )
        expected_runtime_file_hash = (
            "f16a45ceaf490827e5183fd9d35ec8e1785798421ddb3e0ae9bb7f0e58ed6b48"
        )
        expected_execution_text = (
            "授权 MAIN_PROGRAM_REGISTRATION_EXECUTION，仅允许 Driver 执行一次 Hash 绑定的 "
            "MAIN_PROGRAM_REGISTRATION Pipeline Action，登记已验证的 Main execution "
            "package、Main 接口及 Lab/Linkage 接口 Hash 绑定并生成结果、晋级和独立验证证据；"
            "不授权 MB-G0、任何 Main Workpack、认证、其他 Workpack、其他 Pipeline Action "
            "或任何安装。"
        )
        preparation_scope = authorization.get("scope", {})
        execution_scope = draft.get("scope", {})
        runtime_material = dict(runtime)
        claimed_runtime_hash = runtime_material.pop("state_hash", None)
        schema_properties = schema.get("properties", {})
        boundary_checks = boundary.get("checks", [])
        main_state = state.get("main_program_registration_preparation", {})

        hash_bindings_valid = True
        for document, excluded_refs in (
            (authorization, set()),
            (baseline, set()),
            (manifest, set()),
            (descriptor, {"runtime_state_ref"}),
            (boundary, set()),
            (readiness, {"runtime_state_ref"}),
            (draft, {"based_on_runtime_state_ref"}),
            (receipt, {"runtime_state_ref"}),
            (main_state, set()),
        ):
            for key, value in document.items():
                if key.endswith("_ref") and isinstance(value, str) and key not in excluded_refs:
                    hash_key = f"{key[:-4]}_sha256"
                    if hash_key in document:
                        hash_bindings_valid = bool(
                            hash_bindings_valid and bound(document, key, hash_key)
                        )

        return bool(
            candidate_hash == expected_candidate_hash
            and authorization.get("status")
            == "GRANTED_AND_CONSUMED_PREPARATION_ONLY"
            and authorization.get("authorization_class")
            == "REGISTRATION_PREPARATION_AUTHORIZATION"
            and authorization.get("candidate_content_sha256") == candidate_hash
            and authorization.get("preparation_only") is True
            and authorization.get("driver_execution_authorized") is False
            and authorization.get("execution_authorized") is False
            and authorization.get("max_driver_transitions") == 0
            and authorization.get("granted_preparation_transitions") == 1
            and authorization.get("authorization_scope_sha256")
            == _json_hash(preparation_scope)
            and preparation_scope.get("dag_node_ids")
            == ["MAIN_PROGRAM_REGISTRATION"]
            and preparation_scope.get("project_ids") == ["MAIN_HARNESS_BUILD"]
            and preparation_scope.get("pipeline_action_ids")
            == ["MAIN_PROGRAM_REGISTRATION"]
            and preparation_scope.get("workpack_ids") == []
            and preparation_scope.get("execution_modes") == ["PREPARATION_ONLY"]
            and authorization.get("decision_evidence", {}).get("confirmation_text")
            == "授权MAIN_PROGRAM_REGISTRATION_PREPARATION"
            and snapshot.get("status")
            == "HASH_BOUND_MAIN_PROGRAM_REGISTRATION_PREPARATION_SNAPSHOT"
            and snapshot.get("runtime_state_revision") == 30
            and snapshot.get("runtime_state_hash") == expected_runtime_hash
            and snapshot.get("main_program_registered") is False
            and snapshot.get("main_registration_pipeline_action_executed") is False
            and baseline.get("status")
            == "LOCKED_FOR_MAIN_PROGRAM_REGISTRATION_PREPARATION"
            and baseline.get("main_program_registration_contract", {}).get("node_id")
            == "MAIN_PROGRAM_REGISTRATION"
            and baseline.get("main_program_registration_contract", {}).get(
                "execution_mode"
            )
            == "REGISTRATION_ONLY"
            and baseline.get("main_program_registration_contract", {}).get(
                "next_node_id"
            )
            == "MAIN_G0_C0"
            and baseline.get("trust_boundaries", {}).get(
                "main_program_registration_execution"
            )
            == "NOT_AUTHORIZED"
            and contract.get("status") == "LOCKED_NOT_EXECUTED"
            and contract.get("pipeline_action_id") == "MAIN_PROGRAM_REGISTRATION"
            and contract.get("execution_mode") == "REGISTRATION_ONLY"
            and contract.get("network") == "NONE"
            and contract.get("nonclaims", {}).get("harness_complete") is False
            and contract.get("nonclaims", {}).get("resource_payload_migration_owner")
            == "MB-P4"
            and repository_hash(repository) == expected_repository
            and schema.get("additionalProperties") is False
            and set(schema.get("required", [])) == set(schema_properties)
            and schema_properties.get("status", {}).get("const") == "PASS"
            and schema_properties.get("pipeline_action_id", {}).get("const")
            == "MAIN_PROGRAM_REGISTRATION"
            and schema_properties.get("harness_complete", {}).get("const") is False
            and schema_properties.get("mb_g0_started", {}).get("const") is False
            and manifest.get("status") == "READY_NOT_EXECUTED"
            and manifest.get("execution_unit_kind") == "PIPELINE_ACTION"
            and manifest.get("pipeline_action_id") == "MAIN_PROGRAM_REGISTRATION"
            and manifest.get("workpack_id") is None
            and manifest.get("auto_execute") is False
            and manifest.get("execution_started") is False
            and manifest.get("shell") is False
            and manifest.get("network") == "NONE"
            and manifest.get("install_performed") is False
            and manifest.get("main_program_registered") is False
            and manifest.get("mb_g0_started") is False
            and manifest.get("action_script_sha256")
            == _file_hash(execution_root / "planned_executors/bin/register_main_program.py")
            and manifest.get("independent_validator_script_sha256")
            == _file_hash(
                execution_root
                / "planned_executors/bin/independently_validate_main_program_registration.py"
            )
            and manifest.get("validation_contract_sha256") == _file_hash(contract_path)
            and manifest.get("output_schema_sha256") == _file_hash(schema_path)
            and manifest.get("main_registration_baseline_sha256")
            == _file_hash(baseline_path)
            and descriptor.get("status")
            == "PREPARED_VERIFIED_NOT_INVOKED_FOR_MAIN_REGISTRATION"
            and descriptor.get("main_program_registration_started") is False
            and descriptor.get("main_program_registered") is False
            and descriptor.get("mb_g0_started") is False
            and descriptor.get("install_started") is False
            and boundary.get("status")
            == "PASS_PREPARATION_ONLY_NO_MAIN_PROGRAM_REGISTRATION_EXECUTION"
            and boundary.get("blocking_findings") == []
            and len(boundary_checks) == 11
            and all(check.get("status") == "PASS" for check in boundary_checks)
            and boundary.get("main_registration_pipeline_action_executed") is False
            and boundary.get("main_program_registration_started") is False
            and boundary.get("main_program_registered") is False
            and boundary.get("mb_g0_started") is False
            and readiness.get("status")
            == "READY_FOR_EXPLICIT_MAIN_PROGRAM_REGISTRATION_EXECUTION_AUTHORIZATION_NOT_GRANTED"
            and readiness.get("technical_preparation_status") == "PASS"
            and readiness.get("required_next_authorization_text")
            == expected_execution_text
            and readiness.get("main_registration_pipeline_action_executed") is False
            and readiness.get("main_program_registration_started") is False
            and readiness.get("main_program_registered") is False
            and readiness.get("mb_g0_started") is False
            and draft.get("status") == "DRAFT_READY_NOT_GRANTED"
            and draft.get("authorization_class") == "REGISTRATION_AUTHORIZATION"
            and draft.get("grantable") is False
            and draft.get("execution_authorized") is False
            and draft.get("driver_execution_authorized") is False
            and draft.get("main_program_registration_authorized") is False
            and draft.get("max_transitions") == 0
            and draft.get("granted_transitions") == 0
            and draft.get("proposed_max_transitions") == 1
            and draft.get("authorization_scope_sha256") == _json_hash(execution_scope)
            and execution_scope.get("pipeline_action_ids")
            == ["MAIN_PROGRAM_REGISTRATION"]
            and execution_scope.get("workpack_ids") == []
            and execution_scope.get("execution_modes") == ["REGISTRATION_ONLY"]
            and draft.get("required_authorization_text") == expected_execution_text
            and receipt.get("status")
            == "COMPLETE_READY_FOR_EXPLICIT_MAIN_PROGRAM_REGISTRATION_EXECUTION_AUTHORIZATION"
            and receipt.get("authorization_transitions_consumed") == 1
            and receipt.get("driver_execution_transitions_consumed") == 0
            and receipt.get("main_registration_pipeline_action_executed") is False
            and receipt.get("main_program_registration_started") is False
            and receipt.get("main_program_registered") is False
            and receipt.get("mb_g0_started") is False
            and receipt.get("install_started") is False
            and _file_hash(runtime_path) == expected_runtime_file_hash
            and claimed_runtime_hash == _json_hash(runtime_material)
            and claimed_runtime_hash == expected_runtime_hash
            and runtime.get("state_revision") == 30
            and runtime.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and runtime.get("active_pipeline_action_id") is None
            and runtime.get("active_workpack_id") is None
            and runtime.get("side_effects_allowed") is False
            and state.get("state")
            == "MAIN_PROGRAM_REGISTRATION_PREPARED_WAITING_EXECUTION_AUTHORIZATION"
            and state.get("highest_completed_external_gate")
            == "MAIN_EXECUTION_PACKAGE_VALIDATED_PASS"
            and state.get("open_blocker_codes")
            == ["MAIN_PROGRAM_REGISTRATION_EXECUTION_AUTHORIZATION_REQUIRED"]
            and state.get("next_eligible_action")
            == "OBTAIN_MAIN_PROGRAM_REGISTRATION_EXECUTION_AUTHORIZATION"
            and state.get("projects", {}).get("MAIN_HARNESS_BUILD")
            == "PROGRAM_REGISTRATION_PREPARED_NOT_AUTHORIZED"
            and state.get("main_program_registration_started") is False
            and state.get("main_program_registered") is False
            and state.get("install_started") is False
            and main_state.get("status") == "PASS_PREPARED_NOT_AUTHORIZED"
            and hash_bindings_valid
            and not (evidence / "engineering_dag/MAIN_PROGRAM_REGISTRATION").exists()
            and not (
                evidence / "project_workpacks/MAIN_HARNESS_BUILD/MB-G0"
            ).exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_main_validation_completion(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept one Hash-bound Main validation action stopped before registration."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    if command.get("command_id") not in {
        "ROOT-CODEX-CODING",
        "MB-CODEX-CODING",
        "LINK-CODEX-CODING",
        "LAB-CODEX-CODING",
    }:
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        def read_json(path: Path) -> Mapping[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError(f"expected object: {path}")
            return value

        def bound(document: Mapping[str, Any], ref_key: str, hash_key: str) -> bool:
            path = resolve_ref(document.get(ref_key))
            return bool(path.is_file() and document.get(hash_key) == _file_hash(path))

        def repository_hash(root: Path) -> tuple[str, int]:
            digest = hashlib.sha256()
            count = 0
            for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
                if (
                    not path.is_file()
                    or "__pycache__" in path.parts
                    or path.suffix in {".pyc", ".pyo"}
                ):
                    continue
                digest.update(path.relative_to(root).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(_file_hash(path).encode("ascii"))
                digest.update(b"\n")
                count += 1
            return digest.hexdigest(), count

        control = execution_root / "control_plane"
        evidence = execution_root / "evidence"
        authorization_path = (
            control / "MAIN_EXECUTION_PACKAGE_VALIDATION_EXECUTION_AUTHORIZATION.json"
        )
        manifest_path = (
            execution_root
            / "planned_executors/manifests/MAIN_EXECUTION_PACKAGE_VALIDATED.resolved-action.json"
        )
        action_result_path = (
            evidence
            / "engineering_dag/MAIN_EXECUTION_PACKAGE_VALIDATED/"
            "MAIN_EXECUTION_PACKAGE_VALIDATED.action-result.json"
        )
        independent_path = (
            evidence
            / "engineering_dag/MAIN_EXECUTION_PACKAGE_VALIDATED/"
            "INDEPENDENT_VALIDATION_RECEIPT.json"
        )
        result_path = (
            evidence / "engineering_dag/MAIN_EXECUTION_PACKAGE_VALIDATED.result.json"
        )
        promotion_path = (
            evidence / "engineering_dag/MAIN_EXECUTION_PACKAGE_VALIDATED.promotion.json"
        )
        completion_path = (
            control / "MAIN_EXECUTION_PACKAGE_VALIDATION_COMPLETION_RECEIPT.json"
        )
        descriptor_path = (
            control / "MAIN_VALIDATION_EXECUTOR_DESCRIPTOR_AFTER_VALIDATION.json"
        )
        runtime_path = control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json"
        state_path = control / "CONTROL_PLANE_STATE.json"
        repository = execution_root / "project_start_packages/main_build/repository"

        authorization = read_json(authorization_path)
        manifest = read_json(manifest_path)
        action_result = read_json(action_result_path)
        independent = read_json(independent_path)
        result = read_json(result_path)
        promotion = read_json(promotion_path)
        completion = read_json(completion_path)
        descriptor = read_json(descriptor_path)
        runtime = read_json(runtime_path)
        state = read_json(state_path)

        candidate_hash = _candidate_tree_hash(candidate_root)
        expected_candidate_hash = (
            "5ee5d5a9d6312c2fe3bf2c3fbf535765321b1cd1f72d610b62188d6b4de4112d"
        )
        expected_repository = (
            "4b029fc3c620e04cfd084158dadf313c0c7c99622ad85df348682052928191b2",
            13,
        )
        expected_runtime_hash = (
            "4ac8c0334459497a8eed0a6ec7173db8d47b763c852e3283bf14c14f062bcb89"
        )
        expected_runtime_file_hash = (
            "f16a45ceaf490827e5183fd9d35ec8e1785798421ddb3e0ae9bb7f0e58ed6b48"
        )
        expected_authorization_text = (
            "授权 MAIN_EXECUTION_PACKAGE_VALIDATION_EXECUTION，仅允许 Driver 执行一次 Hash "
            "绑定的 MAIN_EXECUTION_PACKAGE_VALIDATED Pipeline Action，对已物化 Main "
            "execution package 进行只读独立验证并生成结果、晋级和独立验证证据；不授权 "
            "MAIN_PROGRAM_REGISTRATION、MB-G0 或任何 Main Workpack、认证、其他 Workpack、"
            "其他 Pipeline Action 或任何安装。"
        )
        scope = authorization.get("scope", {})
        consumption_policy = authorization.get("consumption_policy", {})
        forbidden_actions = set(authorization.get("forbidden_actions", []))
        action_checks = action_result.get("checks", [])
        independent_checks = independent.get("checks", [])
        main_state = state.get("main_validation", {})
        runtime_material = dict(runtime)
        claimed_runtime_hash = runtime_material.pop("state_hash", None)

        hash_bindings_valid = True
        for document in (
            authorization,
            independent,
            result,
            promotion,
            completion,
            descriptor,
            main_state,
        ):
            for key, value in document.items():
                if key.endswith("_ref") and isinstance(value, str):
                    hash_key = f"{key[:-4]}_sha256"
                    if hash_key in document:
                        hash_bindings_valid = bool(
                            hash_bindings_valid and bound(document, key, hash_key)
                        )

        return bool(
            candidate_hash == expected_candidate_hash
            and authorization.get("status") == "GRANTED"
            and authorization.get("authorization_class")
            == "PROJECT_VALIDATION_AUTHORIZATION"
            and authorization.get("candidate_content_sha256") == candidate_hash
            and authorization.get("max_transitions") == 1
            and authorization.get("granted_transitions") == 1
            and authorization.get("execution_authorized") is True
            and authorization.get("driver_execution_authorized") is True
            and authorization.get("main_validation_authorized") is True
            and authorization.get("authorization_scope_sha256") == _json_hash(scope)
            and scope.get("dag_node_ids") == ["MAIN_EXECUTION_PACKAGE_VALIDATED"]
            and scope.get("project_ids") == ["MAIN_HARNESS_BUILD"]
            and scope.get("pipeline_action_ids")
            == ["MAIN_EXECUTION_PACKAGE_VALIDATED"]
            and scope.get("workpack_ids") == []
            and scope.get("execution_modes") == ["PROJECT_VALIDATION"]
            and authorization.get("command_manifest_hashes")
            == [_file_hash(manifest_path)]
            and authorization.get("allowed_driver_commands")
            == ["validate-transition", "advance"]
            and authorization.get("decision_evidence", {}).get("confirmation_text")
            == expected_authorization_text
            and consumption_policy.get("exact_pipeline_action_order")
            == ["MAIN_EXECUTION_PACKAGE_VALIDATED"]
            and consumption_policy.get("one_time_only") is True
            and consumption_policy.get(
                "require_independent_validation_after_each_action"
            )
            is True
            and {
                "MAIN_PROGRAM_REGISTRATION",
                "MB_G0_EXECUTION",
                "MAIN_WORKPACK_EXECUTION",
                "OTHER_WORKPACK_EXECUTION",
                "OTHER_PIPELINE_ACTION_EXECUTION",
                "INSTALL",
            }.issubset(forbidden_actions)
            and manifest.get("status") == "READY_NOT_EXECUTED"
            and manifest.get("execution_unit_kind") == "PIPELINE_ACTION"
            and manifest.get("pipeline_action_id")
            == "MAIN_EXECUTION_PACKAGE_VALIDATED"
            and manifest.get("workpack_id") is None
            and manifest.get("network") == "NONE"
            and manifest.get("install_performed") is False
            and action_result.get("status") == "PASS"
            and action_result.get("pipeline_action_id")
            == "MAIN_EXECUTION_PACKAGE_VALIDATED"
            and action_result.get("blocking_findings") == []
            and len(action_checks) == 7
            and all(check.get("status") == "PASS" for check in action_checks)
            and action_result.get("test_count") == 17
            and (
                action_result.get("repository_content_sha256"),
                action_result.get("repository_content_file_count"),
            )
            == expected_repository
            and action_result.get("resource_payload_migration_complete") is False
            and action_result.get("main_program_registration_started") is False
            and action_result.get("mb_g0_started") is False
            and action_result.get("install_performed") is False
            and independent.get("status") == "PASS"
            and independent.get("blocking_findings") == []
            and independent.get("command_exit_code") == 0
            and independent.get("driver_independent_validation_exit_code") == 0
            and independent.get("fresh_independent_validation_exit_code") == 0
            and len(independent_checks) == 9
            and all(check.get("status") == "PASS" for check in independent_checks)
            and independent.get("test_count") == 17
            and (
                independent.get("repository_content_sha256"),
                independent.get("repository_content_file_count"),
            )
            == expected_repository
            and independent.get("nonclaims", {}).get("harness_complete") is False
            and independent.get("nonclaims", {}).get("main_program_registered")
            is False
            and independent.get("nonclaims", {}).get(
                "resource_payload_migration_complete"
            )
            is False
            and independent.get("nonclaims", {}).get("resource_payload_migration_owner")
            == "MB-P4"
            and independent.get("nonclaims", {}).get("target_installed") is False
            and result.get("status") == "PASS"
            and result.get("success_gate") == "MAIN_EXECUTION_PACKAGE_VALIDATED_PASS"
            and result.get("completed_pipeline_action_ids")
            == ["MAIN_EXECUTION_PACKAGE_VALIDATED"]
            and result.get("authorization_transitions_consumed") == 1
            and result.get("command_exit_code") == 0
            and result.get("independent_validation_exit_code") == 0
            and result.get("test_count") == 17
            and result.get("next_node_activated") is False
            and result.get("main_program_registration_started") is False
            and result.get("mb_g0_started") is False
            and result.get("install_performed") is False
            and promotion.get("status")
            == "PROMOTED_STOPPED_BEFORE_MAIN_PROGRAM_REGISTRATION"
            and promotion.get("next_node_id") == "MAIN_PROGRAM_REGISTRATION"
            and promotion.get("next_node_activated") is False
            and promotion.get("main_program_registration_started") is False
            and promotion.get("mb_g0_started") is False
            and promotion.get("install_started") is False
            and completion.get("status")
            == "MAIN_EXECUTION_PACKAGE_VALIDATED_COMPLETE_STOPPED_BEFORE_REGISTRATION"
            and completion.get("runtime_state_revision") == 30
            and completion.get("runtime_state_hash") == expected_runtime_hash
            and completion.get("runtime_state_file_sha256")
            == expected_runtime_file_hash
            and completion.get("authorization_transitions_consumed") == 1
            and completion.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and completion.get("next_node_activated") is False
            and completion.get("main_program_registration_started") is False
            and completion.get("mb_g0_started") is False
            and completion.get("install_started") is False
            and descriptor.get("status")
            == "MAIN_EXECUTION_PACKAGE_VALIDATED_PASS_STOPPED_BEFORE_REGISTRATION"
            and descriptor.get("execution_unit_kind") == "PIPELINE_ACTION"
            and descriptor.get("pipeline_action_id")
            == "MAIN_EXECUTION_PACKAGE_VALIDATED"
            and descriptor.get("runtime_state_revision") == 30
            and descriptor.get("runtime_state_hash") == expected_runtime_hash
            and descriptor.get("main_execution_package_validated") is True
            and descriptor.get("main_validation_started") is True
            and descriptor.get("main_program_registration_started") is False
            and descriptor.get("mb_g0_started") is False
            and descriptor.get("install_started") is False
            and descriptor.get("next_node_activated") is False
            and repository_hash(repository) == expected_repository
            and _file_hash(runtime_path) == expected_runtime_file_hash
            and claimed_runtime_hash == _json_hash(runtime_material)
            and claimed_runtime_hash == expected_runtime_hash
            and runtime.get("state_revision") == 30
            and runtime.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and runtime.get("active_pipeline_action_id") is None
            and runtime.get("active_workpack_id") is None
            and runtime.get("active_dag_node") is None
            and runtime.get("authorization_consumptions", {}).get(
                "AUTH-VSCDSL-MAIN-VALIDATION-EXECUTION-V03-001"
            )
            == 1
            and runtime.get("completed_pipeline_action_ids", [])[-1:]
            == ["MAIN_EXECUTION_PACKAGE_VALIDATED"]
            and runtime.get("side_effects_allowed") is False
            and state.get("state")
            == "MAIN_EXECUTION_PACKAGE_VALIDATED_PASS_WAITING_MAIN_PROGRAM_REGISTRATION_PREPARATION_AUTHORIZATION"
            and state.get("highest_completed_external_gate")
            == "MAIN_EXECUTION_PACKAGE_VALIDATED_PASS"
            and state.get("open_blocker_codes")
            == ["MAIN_PROGRAM_REGISTRATION_PREPARATION_AUTHORIZATION_REQUIRED"]
            and state.get("next_eligible_action")
            == "OBTAIN_MAIN_PROGRAM_REGISTRATION_PREPARATION_AUTHORIZATION"
            and state.get("projects", {}).get("MAIN_HARNESS_BUILD")
            == "EXECUTION_PACKAGE_VALIDATED_REGISTRATION_NOT_STARTED"
            and state.get("main_validation_started") is True
            and state.get("install_started") is False
            and main_state.get("status")
            == "PASS_COMPLETE_STOPPED_BEFORE_REGISTRATION"
            and main_state.get("completed_pipeline_action_ids")
            == ["MAIN_EXECUTION_PACKAGE_VALIDATED"]
            and main_state.get("test_count") == 17
            and hash_bindings_valid
            and not (evidence / "engineering_dag/MAIN_PROGRAM_REGISTRATION").exists()
            and not (
                evidence / "project_workpacks/MAIN_HARNESS_BUILD/MB-G0"
            ).exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_main_validation_preparation(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept Hash-bound Main validation preparation without executing it."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    if command.get("command_id") not in {
        "ROOT-CODEX-CODING",
        "MB-CODEX-CODING",
        "LINK-CODEX-CODING",
        "LAB-CODEX-CODING",
    }:
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        def read_json(path: Path) -> Mapping[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError(f"expected object: {path}")
            return value

        def bound(document: Mapping[str, Any], ref_key: str, hash_key: str) -> bool:
            path = resolve_ref(document.get(ref_key))
            return bool(path.is_file() and document.get(hash_key) == _file_hash(path))

        def repository_hash(root: Path) -> tuple[str, int]:
            digest = hashlib.sha256()
            count = 0
            for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
                if (
                    not path.is_file()
                    or "__pycache__" in path.parts
                    or path.suffix in {".pyc", ".pyo"}
                ):
                    continue
                digest.update(path.relative_to(root).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(_file_hash(path).encode("ascii"))
                digest.update(b"\n")
                count += 1
            return digest.hexdigest(), count

        control = execution_root / "control_plane"
        evidence = execution_root / "evidence"
        authorization_path = (
            control / "MAIN_EXECUTION_PACKAGE_VALIDATION_PREPARATION_AUTHORIZATION.json"
        )
        baseline_path = control / "MAIN_VALIDATION_BASELINE_LOCK.json"
        contract_path = (
            execution_root
            / "planned_executors/contracts/MAIN_EXECUTION_PACKAGE_VALIDATION_CONTRACT.json"
        )
        schema_path = (
            execution_root
            / "planned_executors/schemas/MAIN_EXECUTION_PACKAGE_VALIDATION_OUTPUT.schema.json"
        )
        manifest_path = (
            execution_root
            / "planned_executors/manifests/MAIN_EXECUTION_PACKAGE_VALIDATED.resolved-action.json"
        )
        descriptor_path = control / "MAIN_VALIDATION_EXECUTOR_DESCRIPTOR.json"
        boundary_path = (
            evidence
            / "main-validation-preparation/"
            "MAIN_EXECUTION_PACKAGE_VALIDATION_PREPARATION_BOUNDARY_ATTESTATION.json"
        )
        readiness_path = (
            control
            / "MAIN_EXECUTION_PACKAGE_VALIDATION_PREPARATION_READINESS_REPORT.json"
        )
        draft_path = (
            control / "MAIN_EXECUTION_PACKAGE_VALIDATION_EXECUTION_AUTHORIZATION_DRAFT.json"
        )
        receipt_path = (
            control / "MAIN_EXECUTION_PACKAGE_VALIDATION_PREPARATION_RECEIPT.json"
        )
        runtime_path = control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json"
        state_path = control / "CONTROL_PLANE_STATE.json"
        repository = execution_root / "project_start_packages/main_build/repository"
        completion_path = (
            control / "MAIN_EXECUTION_PACKAGE_MATERIALIZATION_COMPLETION_RECEIPT.json"
        )

        authorization = read_json(authorization_path)
        baseline = read_json(baseline_path)
        contract = read_json(contract_path)
        schema = read_json(schema_path)
        manifest = read_json(manifest_path)
        descriptor = read_json(descriptor_path)
        boundary = read_json(boundary_path)
        readiness = read_json(readiness_path)
        draft = read_json(draft_path)
        receipt = read_json(receipt_path)
        runtime = read_json(runtime_path)
        state = read_json(state_path)
        completion = read_json(completion_path)

        candidate_hash = _candidate_tree_hash(candidate_root)
        expected_candidate_hash = (
            "5ee5d5a9d6312c2fe3bf2c3fbf535765321b1cd1f72d610b62188d6b4de4112d"
        )
        expected_repository = (
            "4b029fc3c620e04cfd084158dadf313c0c7c99622ad85df348682052928191b2",
            13,
        )
        expected_runtime_hash = (
            "69fbc409eb19b7cf9cae2aca7100ebf205410d0cabc08a545be2954468b44eaf"
        )
        expected_runtime_file_hash = (
            "2540b00c4587ff7aa6620f70689fd277b525b5724391230bd2bf54d97ee7172b"
        )
        expected_authorization_text = (
            "授权 MAIN_EXECUTION_PACKAGE_VALIDATION_EXECUTION，仅允许 Driver 执行一次 Hash "
            "绑定的 MAIN_EXECUTION_PACKAGE_VALIDATED Pipeline Action，对已物化 Main "
            "execution package 进行只读独立验证并生成结果、晋级和独立验证证据；不授权 "
            "MAIN_PROGRAM_REGISTRATION、MB-G0 或任何 Main Workpack、认证、其他 Workpack、"
            "其他 Pipeline Action 或任何安装。"
        )
        preparation_scope = authorization.get("scope", {})
        execution_scope = draft.get("scope", {})
        runtime_material = dict(runtime)
        claimed_runtime_hash = runtime_material.pop("state_hash", None)
        schema_properties = schema.get("properties", {})
        boundary_checks = boundary.get("checks", [])
        main_state = state.get("main_validation_preparation", {})

        hash_bindings_valid = True
        for document, excluded_refs in (
            (authorization, set()),
            (baseline, set()),
            (manifest, set()),
            (descriptor, {"runtime_state_ref"}),
            (boundary, set()),
            (readiness, {"runtime_state_ref"}),
            (draft, {"based_on_runtime_state_ref"}),
            (receipt, {"runtime_state_ref"}),
        ):
            for key, value in document.items():
                if key.endswith("_ref") and isinstance(value, str) and key not in excluded_refs:
                    hash_key = f"{key[:-4]}_sha256"
                    if hash_key in document:
                        hash_bindings_valid = bool(
                            hash_bindings_valid and bound(document, key, hash_key)
                        )

        return bool(
            candidate_hash == expected_candidate_hash
            and authorization.get("status")
            == "GRANTED_AND_CONSUMED_PREPARATION_ONLY"
            and authorization.get("authorization_class")
            == "PROJECT_VALIDATION_PREPARATION_AUTHORIZATION"
            and authorization.get("candidate_content_sha256") == candidate_hash
            and authorization.get("preparation_only") is True
            and authorization.get("driver_execution_authorized") is False
            and authorization.get("execution_authorized") is False
            and authorization.get("max_driver_transitions") == 0
            and authorization.get("granted_preparation_transitions") == 1
            and authorization.get("authorization_scope_sha256")
            == _json_hash(preparation_scope)
            and preparation_scope.get("dag_node_ids")
            == ["MAIN_EXECUTION_PACKAGE_VALIDATED"]
            and preparation_scope.get("project_ids") == ["MAIN_HARNESS_BUILD"]
            and preparation_scope.get("pipeline_action_ids")
            == ["MAIN_EXECUTION_PACKAGE_VALIDATED"]
            and preparation_scope.get("workpack_ids") == []
            and preparation_scope.get("execution_modes") == ["PREPARATION_ONLY"]
            and baseline.get("status") == "LOCKED_FOR_MAIN_VALIDATION_PREPARATION"
            and baseline.get("main_validation_contract", {}).get("node_id")
            == "MAIN_EXECUTION_PACKAGE_VALIDATED"
            and baseline.get("main_repository", {}).get("content_sha256")
            == expected_repository[0]
            and baseline.get("main_repository", {}).get("content_file_count")
            == expected_repository[1]
            and contract.get("status") == "LOCKED_NOT_EXECUTED"
            and contract.get("pipeline_action_id")
            == "MAIN_EXECUTION_PACKAGE_VALIDATED"
            and contract.get("execution_mode") == "PROJECT_VALIDATION"
            and contract.get("network") == "NONE"
            and contract.get("tests", {}).get("expected_test_count") == 17
            and contract.get("nonclaims", {}).get(
                "resource_payload_migration_complete"
            )
            is False
            and repository_hash(repository) == expected_repository
            and schema.get("additionalProperties") is False
            and set(schema.get("required", [])) == set(schema_properties)
            and schema_properties.get("status", {}).get("const") == "PASS"
            and schema_properties.get("pipeline_action_id", {}).get("const")
            == "MAIN_EXECUTION_PACKAGE_VALIDATED"
            and manifest.get("status") == "READY_NOT_EXECUTED"
            and manifest.get("execution_unit_kind") == "PIPELINE_ACTION"
            and manifest.get("pipeline_action_id")
            == "MAIN_EXECUTION_PACKAGE_VALIDATED"
            and manifest.get("workpack_id") is None
            and manifest.get("auto_execute") is False
            and manifest.get("execution_started") is False
            and manifest.get("shell") is False
            and manifest.get("network") == "NONE"
            and manifest.get("executable_sha256") == _file_hash(Path("/opt/homebrew/bin/python3"))
            and descriptor.get("status")
            == "PREPARED_VERIFIED_NOT_INVOKED_FOR_MAIN_VALIDATION"
            and descriptor.get("main_validation_started") is False
            and descriptor.get("main_program_registration_started") is False
            and descriptor.get("mb_g0_started") is False
            and descriptor.get("install_started") is False
            and boundary.get("status")
            == "PASS_PREPARATION_ONLY_NO_MAIN_VALIDATION_EXECUTION"
            and boundary.get("blocking_findings") == []
            and len(boundary_checks) == 10
            and all(check.get("status") == "PASS" for check in boundary_checks)
            and boundary.get("pipeline_action_executed") is False
            and readiness.get("status")
            == "READY_FOR_EXPLICIT_MAIN_VALIDATION_EXECUTION_AUTHORIZATION_NOT_GRANTED"
            and readiness.get("technical_preparation_status") == "PASS"
            and readiness.get("required_next_authorization_text")
            == expected_authorization_text
            and readiness.get("main_validation_started") is False
            and draft.get("status") == "DRAFT_READY_NOT_GRANTED"
            and draft.get("authorization_class")
            == "PROJECT_VALIDATION_AUTHORIZATION"
            and draft.get("grantable") is False
            and draft.get("execution_authorized") is False
            and draft.get("driver_execution_authorized") is False
            and draft.get("main_validation_authorized") is False
            and draft.get("max_transitions") == 0
            and draft.get("granted_transitions") == 0
            and draft.get("proposed_max_transitions") == 1
            and draft.get("authorization_scope_sha256") == _json_hash(execution_scope)
            and execution_scope.get("pipeline_action_ids")
            == ["MAIN_EXECUTION_PACKAGE_VALIDATED"]
            and execution_scope.get("workpack_ids") == []
            and execution_scope.get("execution_modes") == ["PROJECT_VALIDATION"]
            and draft.get("required_authorization_text")
            == expected_authorization_text
            and receipt.get("status")
            == "COMPLETE_READY_FOR_EXPLICIT_MAIN_VALIDATION_EXECUTION_AUTHORIZATION"
            and receipt.get("authorization_transitions_consumed") == 1
            and receipt.get("driver_execution_transitions_consumed") == 0
            and receipt.get("main_validation_started") is False
            and receipt.get("pipeline_action_executed") is False
            and receipt.get("main_program_registration_started") is False
            and receipt.get("mb_g0_started") is False
            and receipt.get("install_started") is False
            and completion.get("status")
            == "MAIN_EXECUTION_PACKAGE_MATERIALIZED_COMPLETE_STOPPED_BEFORE_VALIDATION"
            and completion.get("repository_content_sha256") == expected_repository[0]
            and completion.get("repository_content_file_count") == expected_repository[1]
            and _file_hash(runtime_path) == expected_runtime_file_hash
            and claimed_runtime_hash == _json_hash(runtime_material)
            and claimed_runtime_hash == expected_runtime_hash
            and runtime.get("state_revision") == 28
            and runtime.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and runtime.get("active_pipeline_action_id") is None
            and runtime.get("active_workpack_id") is None
            and runtime.get("side_effects_allowed") is False
            and state.get("state")
            == "MAIN_EXECUTION_PACKAGE_VALIDATION_PREPARED_WAITING_EXECUTION_AUTHORIZATION"
            and state.get("highest_completed_external_gate")
            == "MAIN_EXECUTION_PACKAGE_MATERIALIZED_PASS"
            and state.get("open_blocker_codes")
            == ["MAIN_EXECUTION_PACKAGE_VALIDATION_EXECUTION_AUTHORIZATION_REQUIRED"]
            and state.get("next_eligible_action")
            == "OBTAIN_MAIN_EXECUTION_PACKAGE_VALIDATION_EXECUTION_AUTHORIZATION"
            and state.get("projects", {}).get("MAIN_HARNESS_BUILD")
            == "EXECUTION_PACKAGE_VALIDATION_PREPARED_NOT_AUTHORIZED"
            and state.get("install_started") is False
            and main_state.get("status") == "PASS_PREPARED_NOT_AUTHORIZED"
            and bound(main_state, "authorization_ref", "authorization_sha256")
            and bound(main_state, "shared_baseline_ref", "shared_baseline_sha256")
            and bound(main_state, "manifest_ref", "manifest_sha256")
            and bound(main_state, "validation_contract_ref", "validation_contract_sha256")
            and bound(main_state, "output_schema_ref", "output_schema_sha256")
            and bound(main_state, "descriptor_ref", "descriptor_sha256")
            and bound(main_state, "boundary_attestation_ref", "boundary_attestation_sha256")
            and bound(main_state, "readiness_report_ref", "readiness_report_sha256")
            and bound(main_state, "authorization_draft_ref", "authorization_draft_sha256")
            and bound(main_state, "receipt_ref", "receipt_sha256")
            and hash_bindings_valid
            and not (
                evidence / "engineering_dag/MAIN_EXECUTION_PACKAGE_VALIDATED"
            ).exists()
            and not (evidence / "engineering_dag/MAIN_PROGRAM_REGISTRATION").exists()
            and not (
                evidence / "project_workpacks/MAIN_HARNESS_BUILD/MB-G0"
            ).exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_main_materialization_completion(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept the one-Workpack Main repository materialization completion state."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    if command.get("command_id") not in {
        "ROOT-CODEX-CODING",
        "MB-CODEX-CODING",
        "LINK-CODEX-CODING",
        "LAB-CODEX-CODING",
    }:
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        def read_json(path: Path) -> Mapping[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError(f"expected object: {path}")
            return value

        def bound(document: Mapping[str, Any], ref_key: str, hash_key: str) -> bool:
            path = resolve_ref(document.get(ref_key))
            return bool(path.is_file() and document.get(hash_key) == _file_hash(path))

        def repository_hash(root: Path) -> tuple[str, int]:
            digest = hashlib.sha256()
            count = 0
            for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
                if (
                    not path.is_file()
                    or "__pycache__" in path.parts
                    or path.suffix in {".pyc", ".pyo"}
                ):
                    continue
                digest.update(path.relative_to(root).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(_file_hash(path).encode("ascii"))
                digest.update(b"\n")
                count += 1
            return digest.hexdigest(), count

        control = execution_root / "control_plane"
        evidence = execution_root / "evidence"
        authorization_path = (
            control / "MAIN_EXECUTION_PACKAGE_MATERIALIZATION_EXECUTION_AUTHORIZATION.json"
        )
        manifest_path = (
            execution_root
            / "planned_executors/manifests/"
            "WP-vscdsl-video-prompt-harness-G0-001.resolved-command.json"
        )
        independent_path = (
            evidence
            / "engineering_dag/MAIN_EXECUTION_PACKAGE_MATERIALIZED/"
            "INDEPENDENT_VALIDATION_RECEIPT.json"
        )
        result_path = (
            evidence / "engineering_dag/MAIN_EXECUTION_PACKAGE_MATERIALIZED.result.json"
        )
        promotion_path = (
            evidence / "engineering_dag/MAIN_EXECUTION_PACKAGE_MATERIALIZED.promotion.json"
        )
        completion_path = (
            control / "MAIN_EXECUTION_PACKAGE_MATERIALIZATION_COMPLETION_RECEIPT.json"
        )
        descriptor_path = (
            control / "MAIN_CODEX_EXECUTOR_DESCRIPTOR_AFTER_MATERIALIZATION.json"
        )
        runtime_path = control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json"
        state_path = control / "CONTROL_PLANE_STATE.json"
        repository = execution_root / "project_start_packages/main_build/repository"
        agent_result_path = (
            evidence
            / "engineering_dag/MAIN_EXECUTION_PACKAGE_MATERIALIZED/attempts/"
            "ATTEMPT-47393D9DBA7C4EE4894C03D518FD88FC/"
            "WP-vscdsl-video-prompt-harness-G0-001.agent-result.json"
        )

        authorization = read_json(authorization_path)
        manifest = read_json(manifest_path)
        independent = read_json(independent_path)
        result = read_json(result_path)
        promotion = read_json(promotion_path)
        completion = read_json(completion_path)
        descriptor = read_json(descriptor_path)
        runtime = read_json(runtime_path)
        state = read_json(state_path)
        agent_result = read_json(agent_result_path)

        candidate_hash = _candidate_tree_hash(candidate_root)
        expected_candidate_hash = (
            "5ee5d5a9d6312c2fe3bf2c3fbf535765321b1cd1f72d610b62188d6b4de4112d"
        )
        expected_repository = (
            "4b029fc3c620e04cfd084158dadf313c0c7c99622ad85df348682052928191b2",
            13,
        )
        expected_runtime_hash = (
            "69fbc409eb19b7cf9cae2aca7100ebf205410d0cabc08a545be2954468b44eaf"
        )
        expected_runtime_file_hash = (
            "2540b00c4587ff7aa6620f70689fd277b525b5724391230bd2bf54d97ee7172b"
        )
        workpack_id = "WP-vscdsl-video-prompt-harness-G0-001"
        expected_workpacks = [
            "LAB-PROTOCOL",
            "LAB-CLI",
            "LAB-FIXTURES",
            "LAB-SELFTEST",
            "LINK-PROTOCOL",
            "LINK-CLI",
            "LINK-SELFTEST",
            workpack_id,
        ]
        expected_authorization_text = (
            "授权 MAIN_EXECUTION_PACKAGE_MATERIALIZATION_EXECUTION，仅允许 Driver 执行一次 "
            "Hash 绑定的 WP-vscdsl-video-prompt-harness-G0-001 Workpack，创建 Main "
            "execution package repository 并生成 MAIN_EXECUTION_PACKAGE_MATERIALIZED 结果及"
            "独立验证证据；不授权 MAIN_EXECUTION_PACKAGE_VALIDATED、MB-G0 或任何后续 Main "
            "Workpack、认证、其他 Workpack、其他 Pipeline Action 或任何安装。"
        )
        scope = authorization.get("scope", {})
        policy = authorization.get("consumption_policy", {})
        runtime_material = dict(runtime)
        claimed_runtime_hash = runtime_material.pop("state_hash", None)
        acceptance_checks = agent_result.get("acceptance_checks", [])
        independent_checks = independent.get("checks", [])
        main_state = state.get("main_materialization", {})

        hash_bindings_valid = True
        for document, excluded_refs in (
            (authorization, {"runtime_state_ref"}),
            (independent, {"runtime_state_ref"}),
            (result, {"runtime_state_ref"}),
            (promotion, set()),
            (completion, {"runtime_state_ref"}),
            (descriptor, {"runtime_state_ref"}),
        ):
            for key, value in document.items():
                if key.endswith("_ref") and isinstance(value, str) and key not in excluded_refs:
                    hash_key = f"{key[:-4]}_sha256"
                    if hash_key in document:
                        hash_bindings_valid = bool(
                            hash_bindings_valid and bound(document, key, hash_key)
                        )

        return bool(
            candidate_hash == expected_candidate_hash
            and authorization.get("status") == "GRANTED"
            and authorization.get("authorization_class")
            == "PROJECT_BOOTSTRAP_AUTHORIZATION"
            and authorization.get("candidate_content_sha256") == candidate_hash
            and authorization.get("max_transitions") == 1
            and authorization.get("granted_transitions") == 1
            and authorization.get("execution_authorized") is True
            and authorization.get("driver_execution_authorized") is True
            and authorization.get("main_materialization_authorized") is True
            and authorization.get("authorization_scope_sha256") == _json_hash(scope)
            and scope.get("dag_node_ids") == ["MAIN_EXECUTION_PACKAGE_MATERIALIZED"]
            and scope.get("project_ids") == ["MAIN_HARNESS_BUILD"]
            and scope.get("workpack_ids") == [workpack_id]
            and scope.get("pipeline_action_ids") == []
            and scope.get("execution_modes") == ["WORKPACK_EXECUTION"]
            and policy.get("exact_workpack_order") == [workpack_id]
            and policy.get("one_time_only") is True
            and policy.get("require_attempt_scoped_output_paths") is True
            and policy.get("require_workpack_acceptance_checks_all_pass") is True
            and authorization.get("decision_evidence", {}).get("confirmation_text")
            == expected_authorization_text
            and {"MAIN_EXECUTION_PACKAGE_VALIDATION", "MB_G0_EXECUTION", "INSTALL"}
            .issubset(set(authorization.get("forbidden_actions", [])))
            and authorization.get("command_manifest_hashes")
            == [_file_hash(manifest_path)]
            and manifest.get("status") == "READY_NOT_EXECUTED"
            and manifest.get("workpack_id") == workpack_id
            and manifest.get("candidate_content_sha256") == candidate_hash
            and manifest.get("auto_execute") is False
            and manifest.get("execution_started") is False
            and manifest.get("executable_sha256") == _file_hash(expected_launcher)
            and repository_hash(repository) == expected_repository
            and agent_result.get("status") == "PASS"
            and agent_result.get("workpack_id") == workpack_id
            and agent_result.get("blocking_findings") == []
            and bool(acceptance_checks)
            and all(check.get("status") == "PASS" for check in acceptance_checks)
            and independent.get("status") == "PASS"
            and independent.get("blocking_findings") == []
            and independent.get("test_count") == 17
            and len(independent_checks) == 10
            and all(check.get("status") == "PASS" for check in independent_checks)
            and independent.get("nonclaims", {}).get(
                "main_execution_package_validated"
            )
            is False
            and independent.get("nonclaims", {}).get(
                "resource_payload_migration_complete"
            )
            is False
            and result.get("status") == "PASS"
            and result.get("success_gate") == "MAIN_EXECUTION_PACKAGE_MATERIALIZED_PASS"
            and result.get("completed_workpack_ids") == [workpack_id]
            and result.get("next_node_activated") is False
            and result.get("main_execution_package_validated") is False
            and result.get("mb_g0_started") is False
            and result.get("install_performed") is False
            and promotion.get("status")
            == "PROMOTED_STOPPED_BEFORE_MAIN_EXECUTION_PACKAGE_VALIDATION"
            and promotion.get("next_node_id") == "MAIN_EXECUTION_PACKAGE_VALIDATED"
            and promotion.get("next_node_activated") is False
            and completion.get("status")
            == "MAIN_EXECUTION_PACKAGE_MATERIALIZED_COMPLETE_STOPPED_BEFORE_VALIDATION"
            and completion.get("authorization_transitions_consumed") == 1
            and completion.get("completed_workpack_ids") == [workpack_id]
            and completion.get("repository_content_sha256") == expected_repository[0]
            and completion.get("repository_content_file_count") == expected_repository[1]
            and completion.get("main_execution_package_validated") is False
            and completion.get("mb_g0_started") is False
            and completion.get("install_started") is False
            and descriptor.get("status")
            == "MAIN_EXECUTION_PACKAGE_MATERIALIZED_PASS_STOPPED_BEFORE_VALIDATION"
            and descriptor.get("completed_workpack_ids") == expected_workpacks
            and descriptor.get("agent_invoked_for_main_materialization") is True
            and descriptor.get("main_execution_package_validated") is False
            and descriptor.get("mb_g0_started") is False
            and descriptor.get("install_started") is False
            and _file_hash(runtime_path) == expected_runtime_file_hash
            and claimed_runtime_hash == _json_hash(runtime_material)
            and claimed_runtime_hash == expected_runtime_hash
            and runtime.get("state_revision") == 28
            and runtime.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and runtime.get("completed_workpack_ids") == expected_workpacks
            and runtime.get("authorization_consumptions", {}).get(
                authorization.get("authorization_id")
            )
            == 1
            and runtime.get("active_workpack_id") is None
            and runtime.get("active_dag_node") is None
            and runtime.get("side_effects_allowed") is False
            and state.get("state")
            == "MAIN_EXECUTION_PACKAGE_MATERIALIZED_PASS_WAITING_VALIDATION_PREPARATION_AUTHORIZATION"
            and state.get("highest_completed_external_gate")
            == "MAIN_EXECUTION_PACKAGE_MATERIALIZED_PASS"
            and state.get("open_blocker_codes")
            == ["MAIN_EXECUTION_PACKAGE_VALIDATION_PREPARATION_AUTHORIZATION_REQUIRED"]
            and state.get("next_eligible_action")
            == "OBTAIN_MAIN_EXECUTION_PACKAGE_VALIDATION_PREPARATION_AUTHORIZATION"
            and state.get("main_materialization_started") is True
            and state.get("install_started") is False
            and main_state.get("status") == "PASS_COMPLETE_STOPPED_BEFORE_VALIDATION"
            and bound(main_state, "authorization_ref", "authorization_sha256")
            and bound(main_state, "independent_validation_ref", "independent_validation_sha256")
            and bound(main_state, "result_ref", "result_sha256")
            and bound(main_state, "promotion_ref", "promotion_sha256")
            and bound(main_state, "completion_receipt_ref", "completion_receipt_sha256")
            and bound(main_state, "descriptor_ref", "descriptor_sha256")
            and hash_bindings_valid
            and not (
                evidence / "engineering_dag/MAIN_EXECUTION_PACKAGE_VALIDATED"
            ).exists()
            and not (
                evidence / "project_workpacks/MAIN_HARNESS_BUILD/MB-G0"
            ).exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_linkage_tool_release_materialization(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept one receipt-bound Linkage tool release stopped before Main."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        def read_json(path: Path) -> Mapping[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError(f"expected object: {path}")
            return value

        def bound(document: Mapping[str, Any], ref_key: str, hash_key: str) -> bool:
            path = resolve_ref(document.get(ref_key))
            return bool(path.is_file() and document.get(hash_key) == _file_hash(path))

        control = execution_root / "control_plane"
        evidence = execution_root / "evidence"
        repository = execution_root / "project_start_packages/linkage_review/repository"
        descriptor_path = control / "LINKAGE_EXECUTOR_DESCRIPTOR_AFTER_TOOL_RELEASE.json"
        receipt_path = control / "LINKAGE_TOOL_RELEASE_LOCKED_COMPLETION_RECEIPT.json"
        authorization_path = (
            control / "LINKAGE_TOOL_RELEASE_LOCKED_PACKAGE_BUILD_AUTHORIZATION.json"
        )
        runtime_path = control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json"
        state_path = control / "CONTROL_PLANE_STATE.json"
        manifest_path = (
            execution_root
            / "planned_executors/manifests/LINKAGE_TOOL_RELEASE_LOCKED.resolved-action.json"
        )
        release_output = evidence / "engineering_dag/LINKAGE_TOOL_RELEASE_LOCKED"
        action_result_path = (
            release_output / "LINKAGE_TOOL_RELEASE_LOCKED.action-result.json"
        )
        archive_path = release_output / "vscdsl_linkage_review-0.1.0.zip"
        distribution_path = release_output / "LINKAGE_TOOL_DISTRIBUTION_DESCRIPTOR.json"
        interface_path = release_output / "LINKAGE_REVIEW_INTERFACE.realized.json"
        independent_path = release_output / "INDEPENDENT_VALIDATION_RECEIPT.json"
        result_path = evidence / "engineering_dag/LINKAGE_TOOL_RELEASE_LOCKED.result.json"
        promotion_path = (
            evidence / "engineering_dag/LINKAGE_TOOL_RELEASE_LOCKED.promotion.json"
        )

        descriptor = read_json(descriptor_path)
        receipt = read_json(receipt_path)
        authorization = read_json(authorization_path)
        runtime = read_json(runtime_path)
        state = read_json(state_path)
        manifest = read_json(manifest_path)
        action_result = read_json(action_result_path)
        distribution = read_json(distribution_path)
        interface = read_json(interface_path)
        independent = read_json(independent_path)
        result = read_json(result_path)
        promotion = read_json(promotion_path)
        source_path = resolve_ref(descriptor.get("driver_source_ref"))
        entrypoint_path = resolve_ref(descriptor.get("driver_entrypoint_ref"))
        prior_descriptor_path = resolve_ref(descriptor.get("prior_descriptor_ref"))
        candidate_hash = _candidate_tree_hash(candidate_root)
        archive_hash = _file_hash(archive_path)
        authorization_id = authorization.get("authorization_id")
        authorization_scope = authorization.get("scope", {})
        forbidden = set(authorization.get("forbidden_actions", []))
        runtime_material = dict(runtime)
        claimed_runtime_hash = runtime_material.pop("state_hash", None)

        digest = hashlib.sha256()
        repository_count = 0
        for path in sorted(repository.rglob("*"), key=lambda item: item.as_posix()):
            if (
                not path.is_file()
                or "__pycache__" in path.parts
                or path.suffix in {".pyc", ".pyo"}
            ):
                continue
            digest.update(path.relative_to(repository).as_posix().encode())
            digest.update(b"\0")
            digest.update(_file_hash(path).encode("ascii"))
            digest.update(b"\n")
            repository_count += 1
        repository_hash = digest.hexdigest()

        expected_workpacks = [
            "LAB-PROTOCOL",
            "LAB-CLI",
            "LAB-FIXTURES",
            "LAB-SELFTEST",
            "LINK-PROTOCOL",
            "LINK-CLI",
            "LINK-SELFTEST",
        ]
        expected_actions = ["LAB_TOOL_RELEASE_LOCKED", "LINKAGE_TOOL_RELEASE_LOCKED"]
        release_state = state.get("linkage_tool_release", {})
        authorization_state = state.get("authorization", {})

        return bool(
            candidate_hash
            == "5ee5d5a9d6312c2fe3bf2c3fbf535765321b1cd1f72d610b62188d6b4de4112d"
            and descriptor.get("status")
            == "LINKAGE_TOOL_RELEASE_LOCKED_PASS_STOPPED_BEFORE_MAIN_MATERIALIZATION"
            and descriptor.get("candidate_content_sha256") == candidate_hash
            and descriptor.get("driver_version") == "0.3.0"
            and descriptor.get("driver_source_sha256") == _file_hash(source_path)
            and descriptor.get("driver_entrypoint_sha256") == _file_hash(entrypoint_path)
            and descriptor.get("launcher_sha256") == _file_hash(executable_path)
            and descriptor.get("prior_descriptor_sha256")
            == _file_hash(prior_descriptor_path)
            and descriptor.get("runtime_state_sha256") == _file_hash(runtime_path)
            and descriptor.get("completion_receipt_sha256") == _file_hash(receipt_path)
            and descriptor.get("archive_sha256") == archive_hash
            and descriptor.get("linkage_review_interface_sha256")
            == _file_hash(interface_path)
            and descriptor.get("completed_workpack_ids") == expected_workpacks
            and descriptor.get("completed_pipeline_action_ids") == expected_actions
            and descriptor.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and descriptor.get("linkage_tool_release_started") is True
            and descriptor.get("next_node_id") == "MAIN_EXECUTION_PACKAGE_MATERIALIZED"
            and descriptor.get("next_node_activated") is False
            and descriptor.get("main_project_started") is False
            and descriptor.get("install_started") is False
            and descriptor.get("target_runtime_install_started") is False
            and receipt.get("status")
            == "LINKAGE_TOOL_RELEASE_LOCKED_COMPLETE_STOPPED_BEFORE_MAIN_MATERIALIZATION"
            and receipt.get("candidate_content_sha256") == candidate_hash
            and receipt.get("authorization_sha256") == _file_hash(authorization_path)
            and receipt.get("runtime_state_sha256") == _file_hash(runtime_path)
            and receipt.get("manifest_sha256") == _file_hash(manifest_path)
            and receipt.get("action_result_sha256") == _file_hash(action_result_path)
            and receipt.get("archive_sha256") == archive_hash
            and receipt.get("distribution_descriptor_sha256")
            == _file_hash(distribution_path)
            and receipt.get("linkage_review_interface_sha256")
            == _file_hash(interface_path)
            and receipt.get("independent_validation_receipt_sha256")
            == _file_hash(independent_path)
            and receipt.get("linkage_tool_release_result_sha256")
            == _file_hash(result_path)
            and receipt.get("promotion_sha256") == _file_hash(promotion_path)
            and receipt.get("authorization_transitions_consumed") == 1
            and receipt.get("completed_pipeline_action_ids") == expected_actions
            and receipt.get("command_exit_code") == 0
            and receipt.get("independent_validation_exit_code") == 0
            and receipt.get("main_project_started") is False
            and receipt.get("lab_certification_started") is False
            and receipt.get("install_started") is False
            and receipt.get("target_runtime_install_started") is False
            and authorization.get("status") == "GRANTED"
            and authorization.get("authorization_class")
            == "PACKAGE_BUILD_AUTHORIZATION"
            and authorization.get("candidate_content_sha256") == candidate_hash
            and authorization.get("max_transitions") == 1
            and authorization.get("granted_transitions") == 1
            and authorization.get("authorization_scope_sha256")
            == _json_hash(authorization_scope)
            and authorization_scope.get("pipeline_action_ids")
            == ["LINKAGE_TOOL_RELEASE_LOCKED"]
            and authorization_scope.get("workpack_ids") == []
            and authorization.get("consumption_policy", {}).get(
                "exact_pipeline_action_order"
            )
            == ["LINKAGE_TOOL_RELEASE_LOCKED"]
            and authorization.get("consumption_policy", {}).get("one_time_only")
            is True
            and authorization.get("real_target_install_allowed") is False
            and authorization.get("may_auto_advance") is False
            and {
                "INSTALL",
                "LAB_CERTIFICATION",
                "MAIN_PROJECT_BOOTSTRAP",
                "OTHER_PIPELINE_ACTION_EXECUTION",
                "WORKPACK_EXECUTION",
                "TARGET_RUNTIME_INSTALLATION",
                "REAL_TARGET_INSTALL",
            }.issubset(forbidden)
            and manifest.get("status") == "READY_NOT_EXECUTED"
            and manifest.get("execution_unit_kind") == "PIPELINE_ACTION"
            and manifest.get("pipeline_action_id") == "LINKAGE_TOOL_RELEASE_LOCKED"
            and manifest.get("workpack_id") is None
            and manifest.get("auto_execute") is False
            and manifest.get("install_performed") is False
            and action_result.get("status") == "PASS"
            and action_result.get("pipeline_action_id") == "LINKAGE_TOOL_RELEASE_LOCKED"
            and action_result.get("blocking_findings") == []
            and action_result.get("distribution_format")
            == "DETERMINISTIC_ZIP_STORED_V1"
            and action_result.get("distribution_file_count") == 11
            and action_result.get("distribution_sha256") == archive_hash
            and action_result.get("release_descriptor_sha256")
            == _file_hash(distribution_path)
            and action_result.get("linkage_review_interface_sha256")
            == _file_hash(interface_path)
            and action_result.get("repository_content_sha256") == repository_hash
            and distribution.get("pipeline_action_id") == "LINKAGE_TOOL_RELEASE_LOCKED"
            and distribution.get("archive_format") == "DETERMINISTIC_ZIP_STORED_V1"
            and distribution.get("archive_sha256") == archive_hash
            and distribution.get("file_count") == 11
            and len(distribution.get("member_sha256", {})) == 11
            and distribution.get("repository_content_sha256") == repository_hash
            and repository_count == 11
            and distribution.get("install_performed") is False
            and interface.get("interface_status")
            == "LINKAGE_TOOL_DISTRIBUTION_HASH_BOUND"
            and interface.get("linkage_tool_distribution_sha256") == archive_hash
            and interface.get("read_only") is True
            and independent.get("status") == "PASS"
            and independent.get("pipeline_action_id") == "LINKAGE_TOOL_RELEASE_LOCKED"
            and independent.get("blocking_findings") == []
            and independent.get("archive_sha256") == archive_hash
            and independent.get("archive_member_count") == 11
            and independent.get("repository_test_count") == 9
            and independent.get("repository_tests_status") == "PASS"
            and independent.get("command_exit_code") == 0
            and independent.get("independent_validation_exit_code") == 0
            and independent.get("install_performed") is False
            and independent.get("main_project_started") is False
            and result.get("status") == "PASS"
            and result.get("success_gate") == "LINKAGE_TOOL_RELEASE_LOCKED_PASS"
            and result.get("pipeline_action_id") == "LINKAGE_TOOL_RELEASE_LOCKED"
            and result.get("authorization_transitions_consumed") == 1
            and result.get("archive_sha256") == archive_hash
            and result.get("install_performed") is False
            and promotion.get("status")
            == "PROMOTED_STOPPED_BEFORE_MAIN_EXECUTION_PACKAGE_MATERIALIZATION"
            and promotion.get("next_node_id") == "MAIN_EXECUTION_PACKAGE_MATERIALIZED"
            and promotion.get("next_node_activated") is False
            and promotion.get("main_project_started") is False
            and promotion.get("install_started") is False
            and claimed_runtime_hash == _json_hash(runtime_material)
            and runtime.get("state_revision") == 26
            and runtime.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and runtime.get("completed_workpack_ids") == expected_workpacks
            and runtime.get("completed_pipeline_action_ids") == expected_actions
            and runtime.get("authorization_consumptions", {}).get(authorization_id) == 1
            and runtime.get("active_workpack_id") is None
            and runtime.get("active_pipeline_action_id") is None
            and runtime.get("active_dag_node") is None
            and runtime.get("side_effects_allowed") is False
            and state.get("state")
            == "LINKAGE_TOOL_RELEASE_LOCKED_PASS_WAITING_MAIN_MATERIALIZATION_PREPARATION_AUTHORIZATION"
            and state.get("highest_completed_external_gate")
            == "LINKAGE_TOOL_RELEASE_LOCKED_PASS"
            and state.get("open_blocker_codes")
            == [
                "MAIN_EXECUTION_PACKAGE_MATERIALIZATION_PREPARATION_AUTHORIZATION_REQUIRED"
            ]
            and state.get("projects", {}).get("CONFORMANCE_LINKAGE_REVIEW")
            == "TOOL_RELEASE_LOCKED_PASS_COMPLETE"
            and state.get("projects", {}).get("MAIN_HARNESS_BUILD")
            == "NOT_BOOTSTRAPPED"
            and state.get("linkage_tool_release_started") is True
            and state.get("main_project_started") in (None, False)
            and state.get("install_started") is False
            and state.get("active_dag_node") is None
            and release_state.get("status") == "PASS"
            and release_state.get("archive_sha256") == archive_hash
            and authorization_state.get(
                "linkage_tool_release_package_build_authorization_status"
            )
            == "GRANTED_AND_CONSUMED_1_OF_1"
            and bound(receipt, "authorization_ref", "authorization_sha256")
            and bound(receipt, "manifest_ref", "manifest_sha256")
            and bound(receipt, "action_result_ref", "action_result_sha256")
            and bound(receipt, "archive_ref", "archive_sha256")
            and bound(
                receipt,
                "distribution_descriptor_ref",
                "distribution_descriptor_sha256",
            )
            and bound(
                receipt,
                "linkage_review_interface_ref",
                "linkage_review_interface_sha256",
            )
            and bound(
                receipt,
                "independent_validation_receipt_ref",
                "independent_validation_receipt_sha256",
            )
            and bound(
                receipt,
                "linkage_tool_release_result_ref",
                "linkage_tool_release_result_sha256",
            )
            and bound(receipt, "promotion_ref", "promotion_sha256")
            and bound(descriptor, "completion_receipt_ref", "completion_receipt_sha256")
            and bound(descriptor, "runtime_state_ref", "runtime_state_sha256")
            and bound(release_state, "descriptor_ref", "descriptor_sha256")
            and bound(release_state, "completion_receipt_ref", "completion_receipt_sha256")
            and bound(release_state, "result_ref", "result_sha256")
            and bound(release_state, "promotion_ref", "promotion_sha256")
            and not (execution_root / "project_start_packages/main_build").exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_linkage_tool_release_preparation_materialization(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept a receipt-bound Linkage release preparation without release execution."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        def read_json(path: Path) -> Mapping[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError(f"expected object: {path}")
            return value

        def bound(document: Mapping[str, Any], ref_key: str, hash_key: str) -> bool:
            path = resolve_ref(document.get(ref_key))
            return bool(path.is_file() and document.get(hash_key) == _file_hash(path))

        control = execution_root / "control_plane"
        evidence = execution_root / "evidence"
        repository = execution_root / "project_start_packages/linkage_review/repository"
        snapshot_path = (
            control
            / "history/LINKAGE_TOOL_RELEASE_PREPARATION.preparation_snapshot.json"
        )
        authorization_path = control / "LINKAGE_TOOL_RELEASE_PREPARATION_AUTHORIZATION.json"
        manifest_path = (
            execution_root
            / "planned_executors/manifests/LINKAGE_TOOL_RELEASE_LOCKED.resolved-action.json"
        )
        contract_path = (
            execution_root
            / "planned_executors/contracts/LINKAGE_TOOL_RELEASE_DISTRIBUTION_CONTRACT.json"
        )
        schema_path = (
            execution_root
            / "planned_executors/schemas/LINKAGE_TOOL_RELEASE_OUTPUT.schema.json"
        )
        readiness_path = control / "LINKAGE_TOOL_RELEASE_PREPARATION_READINESS_REPORT.json"
        draft_path = (
            control
            / "LINKAGE_TOOL_RELEASE_PACKAGE_BUILD_AUTHORIZATION_AFTER_PREPARATION_DRAFT.json"
        )
        boundary_path = (
            evidence
            / "linkage-tool-release-preparation/LINKAGE_TOOL_RELEASE_PREPARATION_BOUNDARY_ATTESTATION.json"
        )
        receipt_path = control / "LINKAGE_TOOL_RELEASE_PREPARATION_RECEIPT.json"
        descriptor_path = (
            control / "LINKAGE_EXECUTOR_DESCRIPTOR_AFTER_TOOL_RELEASE_PREPARATION.json"
        )
        runtime_path = control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json"
        state_path = control / "CONTROL_PLANE_STATE.json"

        snapshot = read_json(snapshot_path)
        authorization = read_json(authorization_path)
        manifest = read_json(manifest_path)
        contract = read_json(contract_path)
        schema = read_json(schema_path)
        readiness = read_json(readiness_path)
        draft = read_json(draft_path)
        boundary = read_json(boundary_path)
        receipt = read_json(receipt_path)
        descriptor = read_json(descriptor_path)
        runtime = read_json(runtime_path)
        state = read_json(state_path)
        prior_descriptor_path = resolve_ref(descriptor.get("prior_descriptor_ref"))
        prior_descriptor = read_json(prior_descriptor_path)
        preparation_script_path = resolve_ref(manifest.get("action_script_abs"))
        validation_script_path = resolve_ref(manifest.get("validator_script_abs"))

        digest = hashlib.sha256()
        repository_count = 0
        for path in sorted(repository.rglob("*"), key=lambda item: item.as_posix()):
            if (
                not path.is_file()
                or "__pycache__" in path.parts
                or path.suffix in {".pyc", ".pyo"}
            ):
                continue
            digest.update(path.relative_to(repository).as_posix().encode())
            digest.update(b"\0")
            digest.update(_file_hash(path).encode("ascii"))
            digest.update(b"\n")
            repository_count += 1
        repository_hash = digest.hexdigest()
        candidate_hash = _candidate_tree_hash(candidate_root)
        preparation_scope = authorization.get("scope", {})
        draft_scope = draft.get("scope", {})
        boundary_checks = boundary.get("checks", [])
        forbidden = set(authorization.get("forbidden_actions", []))
        draft_forbidden = set(draft.get("forbidden_actions", []))
        target_output = evidence / "engineering_dag/LINKAGE_TOOL_RELEASE_LOCKED"
        required_authorization_text = (
            "授权 LINKAGE_TOOL_RELEASE_LOCKED_PACKAGE_BUILD，仅允许 Driver 执行一次 Hash "
            "绑定的 LINKAGE_TOOL_RELEASE_LOCKED Pipeline Action，生成确定性 Linkage 工具"
            "发行物、只读接口描述、结果与独立验证证据；不授权 Main、认证、任何 "
            "Workpack、其他 Pipeline Action 或任何安装。"
        )

        return bool(
            candidate_hash
            == "5ee5d5a9d6312c2fe3bf2c3fbf535765321b1cd1f72d610b62188d6b4de4112d"
            and snapshot.get("status") == "HASH_BOUND_PREPARATION_SNAPSHOT"
            and snapshot.get("authorization_text")
            == "授权LINKAGE_TOOL_RELEASE_PREPARATION"
            and snapshot.get("authorization_text_sha256")
            == "c3bcc1bc7d18a75b2034755e2b979ebf9ee51cb96e1e2bb420ed646d439afde1"
            and snapshot.get("runtime_state_revision") == 24
            and snapshot.get("linkage_repository_content_sha256") == repository_hash
            and snapshot.get("linkage_repository_content_file_count")
            == repository_count
            and snapshot.get("distribution_output_directory_existed") is False
            and authorization.get("status")
            == "GRANTED_AND_CONSUMED_PREPARATION_ONLY"
            and authorization.get("authorization_class")
            == "RELEASE_PREPARATION_AUTHORIZATION"
            and authorization.get("candidate_content_sha256") == candidate_hash
            and authorization.get("preparation_only") is True
            and authorization.get("driver_execution_authorized") is False
            and authorization.get("execution_authorized") is False
            and authorization.get("max_driver_transitions") == 0
            and authorization.get("granted_preparation_transitions") == 1
            and authorization.get("authorization_scope_sha256")
            == _json_hash(preparation_scope)
            and preparation_scope.get("dag_node_ids")
            == ["LINKAGE_TOOL_RELEASE_LOCKED"]
            and preparation_scope.get("pipeline_action_ids")
            == ["LINKAGE_TOOL_RELEASE_LOCKED"]
            and preparation_scope.get("execution_modes") == ["PREPARATION_ONLY"]
            and preparation_scope.get("workpack_ids") == []
            and authorization.get("decision_evidence", {}).get("confirmation_text")
            == "授权LINKAGE_TOOL_RELEASE_PREPARATION"
            and authorization.get("real_target_install_allowed") is False
            and authorization.get("may_auto_advance") is False
            and {
                "LINKAGE_TOOL_RELEASE_LOCKED_EXECUTION",
                "PIPELINE_ACTION_EXECUTION",
                "WORKPACK_EXECUTION",
                "MAIN_PROJECT_BOOTSTRAP",
                "LAB_CERTIFICATION",
                "TARGET_RUNTIME_INSTALLATION",
                "REAL_TARGET_INSTALL",
                "INSTALL",
            }.issubset(forbidden)
            and contract.get("status") == "LOCKED_NOT_EXECUTED"
            and contract.get("pipeline_action_id") == "LINKAGE_TOOL_RELEASE_LOCKED"
            and contract.get("candidate_content_sha256") == candidate_hash
            and contract.get("repository", {}).get("content_sha256")
            == repository_hash
            and contract.get("repository", {}).get("content_file_count")
            == repository_count
            and contract.get("archive", {}).get("format_id")
            == "DETERMINISTIC_ZIP_STORED_V1"
            and contract.get("archive", {}).get("compression") == "ZIP_STORED"
            and contract.get("distribution", {}).get("install_performed") is False
            and manifest.get("status") == "READY_NOT_EXECUTED"
            and manifest.get("execution_unit_kind") == "PIPELINE_ACTION"
            and manifest.get("pipeline_action_id") == "LINKAGE_TOOL_RELEASE_LOCKED"
            and manifest.get("workpack_id") is None
            and manifest.get("candidate_content_sha256") == candidate_hash
            and manifest.get("auto_execute") is False
            and manifest.get("execution_started") is False
            and manifest.get("distribution_build_started") is False
            and manifest.get("install_performed") is False
            and manifest.get("network") == "NONE"
            and manifest.get("shell") is False
            and manifest.get("action_script_sha256")
            == _file_hash(preparation_script_path)
            and manifest.get("validator_script_sha256")
            == _file_hash(validation_script_path)
            and manifest.get("distribution_contract_sha256") == _file_hash(contract_path)
            and manifest.get("output_schema_sha256") == _file_hash(schema_path)
            and schema.get("additionalProperties") is False
            and schema.get("properties", {}).get("pipeline_action_id", {}).get("const")
            == "LINKAGE_TOOL_RELEASE_LOCKED"
            and schema.get("properties", {}).get("distribution_file_count", {}).get(
                "const"
            )
            == 11
            and readiness.get("status")
            == "READY_FOR_LINKAGE_PACKAGE_BUILD_AUTHORIZATION_NOT_GRANTED"
            and readiness.get("technical_preparation_status") == "PASS"
            and readiness.get("preparation_blocking_findings") == []
            and readiness.get("required_next_authorization_text")
            == required_authorization_text
            and readiness.get("target_pipeline_action_executed") is False
            and readiness.get("execution_or_build_started") is False
            and readiness.get("release_action_writes_performed") is False
            and readiness.get("actual_distribution_output_directory_exists") is False
            and draft.get("status") == "DRAFT_READY_NOT_GRANTED"
            and draft.get("grantable") is False
            and draft.get("execution_authorized") is False
            and draft.get("driver_execution_authorized") is False
            and draft.get("max_transitions") == 0
            and draft.get("granted_transitions") == 0
            and draft.get("proposed_max_transitions") == 1
            and draft.get("authorization_scope_sha256") == _json_hash(draft_scope)
            and draft_scope.get("pipeline_action_ids")
            == ["LINKAGE_TOOL_RELEASE_LOCKED"]
            and draft_scope.get("workpack_ids") == []
            and draft.get("required_authorization_text")
            == required_authorization_text
            and {
                "INSTALL",
                "LAB_CERTIFICATION",
                "MAIN_PROJECT_BOOTSTRAP",
                "OTHER_PIPELINE_ACTION_EXECUTION",
                "WORKPACK_EXECUTION",
                "TARGET_RUNTIME_INSTALLATION",
                "REAL_TARGET_INSTALL",
            }.issubset(draft_forbidden)
            and boundary.get("status")
            == "PASS_PREPARATION_ONLY_NO_RELEASE_EXECUTION"
            and boundary.get("blocking_findings") == []
            and len(boundary_checks) == 6
            and all(check.get("status") == "PASS" for check in boundary_checks)
            and boundary.get("actual_pipeline_action_executed") is False
            and boundary.get("distribution_build_started") is False
            and boundary.get("release_output_directory_exists") is False
            and receipt.get("status")
            == "COMPLETE_READY_FOR_EXPLICIT_LINKAGE_PACKAGE_BUILD_AUTHORIZATION"
            and receipt.get("candidate_content_sha256") == candidate_hash
            and receipt.get("authorization_transitions_consumed") == 1
            and receipt.get("driver_execution_transitions_consumed") == 0
            and receipt.get("actual_pipeline_action_executed") is False
            and receipt.get("distribution_build_started") is False
            and receipt.get("workpack_execution_started") is False
            and receipt.get("linkage_tool_release_started") is False
            and receipt.get("main_project_started") is False
            and receipt.get("install_started") is False
            and descriptor.get("status")
            == "LINKAGE_TOOL_RELEASE_PREPARED_NOT_AUTHORIZED_DRIVER_STOPPED"
            and descriptor.get("candidate_content_sha256") == candidate_hash
            and descriptor.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and descriptor.get("preparation_executor_kind")
            == "STATIC_LOCAL_VALIDATION_NO_DRIVER_TRANSITION"
            and descriptor.get("next_node_id") == "LINKAGE_TOOL_RELEASE_LOCKED"
            and descriptor.get("next_node_activated") is False
            and descriptor.get("completed_pipeline_action_ids")
            == ["LAB_TOOL_RELEASE_LOCKED"]
            and descriptor.get("linkage_tool_release_started") is False
            and descriptor.get("main_project_started") is False
            and descriptor.get("prior_descriptor_sha256")
            == _file_hash(prior_descriptor_path)
            and descriptor.get("launcher_sha256") == _file_hash(executable_path)
            and runtime.get("state_revision") == 24
            and runtime.get("driver_status")
            == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and runtime.get("completed_pipeline_action_ids")
            == ["LAB_TOOL_RELEASE_LOCKED"]
            and runtime.get("active_pipeline_action_id") is None
            and runtime.get("active_dag_node") is None
            and runtime.get("side_effects_allowed") is False
            and state.get("state")
            == "LINKAGE_TOOL_RELEASE_PREPARED_WAITING_PACKAGE_BUILD_AUTHORIZATION"
            and state.get("highest_completed_external_gate")
            == "LINKAGE_SELF_CONFORMANCE_PASS_PASS"
            and state.get("open_blocker_codes")
            == ["LINKAGE_TOOL_RELEASE_LOCKED_PACKAGE_BUILD_AUTHORIZATION_REQUIRED"]
            and state.get("next_eligible_action")
            == "OBTAIN_LINKAGE_TOOL_RELEASE_LOCKED_PACKAGE_BUILD_AUTHORIZATION"
            and state.get("linkage_tool_release_started") is False
            and state.get("install_started") is False
            and state.get("active_dag_node") is None
            and bound(
                authorization,
                "based_on_preparation_snapshot_ref",
                "based_on_preparation_snapshot_sha256",
            )
            and bound(
                authorization,
                "based_on_self_conformance_receipt_ref",
                "based_on_self_conformance_receipt_sha256",
            )
            and bound(readiness, "command_manifest_ref", "command_manifest_sha256")
            and bound(
                readiness, "distribution_contract_ref", "distribution_contract_sha256"
            )
            and bound(readiness, "output_schema_ref", "output_schema_sha256")
            and bound(draft, "readiness_report_ref", "readiness_report_sha256")
            and bound(boundary, "command_manifest_ref", "command_manifest_sha256")
            and bound(
                boundary, "distribution_contract_ref", "distribution_contract_sha256"
            )
            and bound(receipt, "authorization_ref", "authorization_sha256")
            and bound(receipt, "boundary_attestation_ref", "boundary_attestation_sha256")
            and bound(receipt, "readiness_report_ref", "readiness_report_sha256")
            and bound(
                receipt,
                "linkage_tool_release_authorization_draft_ref",
                "linkage_tool_release_authorization_draft_sha256",
            )
            and bound(
                receipt,
                "linkage_tool_release_manifest_ref",
                "linkage_tool_release_manifest_sha256",
            )
            and bound(
                descriptor,
                "linkage_tool_release_preparation_receipt_ref",
                "linkage_tool_release_preparation_receipt_sha256",
            )
            and not target_output.exists()
            and not (execution_root / "project_start_packages/main_build").exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_linkage_self_conformance_materialization(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept one receipt-bound local Linkage self-conformance transition."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        def read_json(path: Path) -> Mapping[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError(f"expected object: {path}")
            return value

        def bound(
            document: Mapping[str, Any], ref_key: str, hash_key: str
        ) -> bool:
            path = resolve_ref(document.get(ref_key))
            return bool(path.is_file() and document.get(hash_key) == _file_hash(path))

        control = execution_root / "control_plane"
        evidence = execution_root / "evidence"
        repository = execution_root / "project_start_packages/linkage_review/repository"
        authorization_path = control / "LINKAGE_SELF_CONFORMANCE_AUTHORIZATION.json"
        manifest_path = (
            execution_root
            / "planned_executors/manifests/LINK-SELFTEST.resolved-command.json"
        )
        schema_path = (
            execution_root
            / "planned_executors/schemas/LINKAGE_SELFTEST_OUTPUT.schema.json"
        )
        runtime_path = control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json"
        state_path = control / "CONTROL_PLANE_STATE.json"
        raw_result_path = (
            evidence
            / "project_workpacks/CONFORMANCE_LINKAGE_REVIEW/LINK-SELFTEST/LINK-SELFTEST.result.json"
        )
        workpack_path = (
            evidence
            / "project_workpacks/CONFORMANCE_LINKAGE_REVIEW/LINK-SELFTEST/WORKPACK_RESULT.json"
        )
        independent_path = (
            evidence
            / "project_workpacks/CONFORMANCE_LINKAGE_REVIEW/LINK-SELFTEST/INDEPENDENT_VALIDATION_RECEIPT.json"
        )
        result_path = evidence / "engineering_dag/LINKAGE_SELF_CONFORMANCE_PASS.result.json"
        promotion_path = (
            evidence / "engineering_dag/LINKAGE_SELF_CONFORMANCE_PASS.promotion.json"
        )
        completion_path = control / "LINKAGE_SELF_CONFORMANCE_COMPLETION_RECEIPT.json"
        descriptor_path = (
            control / "LINKAGE_EXECUTOR_DESCRIPTOR_AFTER_SELF_CONFORMANCE.json"
        )

        authorization = read_json(authorization_path)
        manifest = read_json(manifest_path)
        schema = read_json(schema_path)
        runtime = read_json(runtime_path)
        state = read_json(state_path)
        raw_result = read_json(raw_result_path)
        workpack = read_json(workpack_path)
        independent = read_json(independent_path)
        result = read_json(result_path)
        promotion = read_json(promotion_path)
        completion = read_json(completion_path)
        descriptor = read_json(descriptor_path)

        digest = hashlib.sha256()
        repository_count = 0
        for path in sorted(repository.rglob("*"), key=lambda item: item.as_posix()):
            if (
                not path.is_file()
                or "__pycache__" in path.parts
                or path.suffix in {".pyc", ".pyo"}
            ):
                continue
            digest.update(path.relative_to(repository).as_posix().encode())
            digest.update(b"\0")
            digest.update(_file_hash(path).encode("ascii"))
            digest.update(b"\n")
            repository_count += 1
        repository_hash = digest.hexdigest()
        candidate_hash = _candidate_tree_hash(candidate_root)
        scope = authorization.get("scope", {})
        runtime_material = dict(runtime)
        claimed_runtime_hash = runtime_material.pop("state_hash", None)
        checks = raw_result.get("acceptance_checks", [])
        independent_checks = independent.get("checks", [])
        forbidden_paths = [
            execution_root
            / "planned_executors/manifests/LINKAGE_TOOL_RELEASE_LOCKED.resolved-action.json",
            execution_root / "project_start_packages/main_build",
            execution_root / "planned_runtime",
        ]
        return bool(
            authorization.get("status") == "GRANTED"
            and authorization.get("authorization_class")
            == "PROJECT_VALIDATION_AUTHORIZATION"
            and authorization.get("candidate_content_sha256") == candidate_hash
            and authorization.get("max_transitions") == 1
            and authorization.get("granted_transitions") == 1
            and authorization.get("authorization_scope_sha256") == _json_hash(scope)
            and scope.get("dag_node_ids") == ["LINKAGE_SELF_CONFORMANCE_PASS"]
            and scope.get("workpack_ids") == ["LINK-SELFTEST"]
            and scope.get("execution_modes") == ["PROJECT_VALIDATION"]
            and authorization.get("command_manifest_hashes")
            == [_file_hash(manifest_path)]
            and authorization.get("decision_evidence", {}).get("confirmation_text")
            == "授权 LINKAGE_SELF_CONFORMANCE_PASS"
            and authorization.get("real_target_install_allowed") is False
            and manifest.get("status") == "READY_NOT_EXECUTED"
            and manifest.get("workpack_id") == "LINK-SELFTEST"
            and manifest.get("execution_unit_kind") == "WORKPACK"
            and manifest.get("executor_role") == "LINKAGE_SELFTEST_VALIDATOR"
            and manifest.get("network") == "NONE"
            and manifest.get("auto_execute") is False
            and manifest.get("shell") is False
            and manifest.get("output_schema_sha256") == _file_hash(schema_path)
            and raw_result.get("status") == "PASS"
            and raw_result.get("workpack_id") == "LINK-SELFTEST"
            and raw_result.get("test_count") == 9
            and raw_result.get("blocking_findings") == []
            and len(checks) == 5
            and all(check.get("status") == "PASS" for check in checks)
            and workpack.get("status") == "PASS"
            and workpack.get("attempt_id")
            == "ATTEMPT-60000E8BCD0F443691E54F7C75580627"
            and workpack.get("authorization_sha256") == _file_hash(authorization_path)
            and workpack.get("command_manifest_sha256") == _file_hash(manifest_path)
            and workpack.get("acceptance_checks_all_pass") is True
            and workpack.get("command_exit_code") == 0
            and workpack.get("independent_validation_exit_code") == 0
            and bound(workpack, "result_ref", "result_sha256")
            and bound(workpack, "command_stdout_ref", "command_stdout_sha256")
            and bound(workpack, "command_stderr_ref", "command_stderr_sha256")
            and independent.get("status") == "PASS"
            and independent.get("blocking_findings") == []
            and len(independent_checks) == 9
            and all(check.get("status") == "PASS" for check in independent_checks)
            and bound(independent, "workpack_result_ref", "workpack_result_sha256")
            and claimed_runtime_hash == _json_hash(runtime_material)
            and runtime.get("state_revision") == 24
            and runtime.get("driver_status") == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and runtime.get("active_dag_node") is None
            and runtime.get("completed_workpack_ids", [])[-1:] == ["LINK-SELFTEST"]
            and runtime.get("authorization_consumptions", {}).get(
                authorization.get("authorization_id")
            )
            == 1
            and result.get("status") == "PASS"
            and result.get("success_gate") == "LINKAGE_SELF_CONFORMANCE_PASS_PASS"
            and promotion.get("status")
            == "PROMOTED_STOPPED_BEFORE_LINKAGE_TOOL_RELEASE"
            and promotion.get("next_node_id") == "LINKAGE_TOOL_RELEASE_LOCKED"
            and promotion.get("next_node_activated") is False
            and completion.get("status")
            == "LINKAGE_SELF_CONFORMANCE_COMPLETE_STOPPED_BEFORE_TOOL_RELEASE"
            and completion.get("authorization_transitions_consumed") == 1
            and completion.get("completed_workpack_ids")
            == ["LINK-PROTOCOL", "LINK-CLI", "LINK-SELFTEST"]
            and completion.get("repository_content_sha256") == repository_hash
            and completion.get("repository_content_file_count") == repository_count
            and completion.get("linkage_tool_release_started") is False
            and completion.get("main_project_started") is False
            and completion.get("install_started") is False
            and bound(
                completion,
                "independent_validation_receipt_ref",
                "independent_validation_receipt_sha256",
            )
            and bound(
                completion,
                "linkage_self_conformance_result_ref",
                "linkage_self_conformance_result_sha256",
            )
            and bound(
                completion,
                "linkage_self_conformance_promotion_ref",
                "linkage_self_conformance_promotion_sha256",
            )
            and descriptor.get("status")
            == "LINKAGE_SELF_CONFORMANCE_COMPLETE_LOCAL_VALIDATOR_STOPPED"
            and descriptor.get("linkage_self_conformance_completion_receipt_sha256")
            == _file_hash(completion_path)
            and descriptor.get("linkage_selftest_executor_kind")
            == "PINNED_LOCAL_PYTHON_NO_CODEX_AGENT"
            and descriptor.get("next_node_activated") is False
            and state.get("state")
            == "LINKAGE_SELF_CONFORMANCE_PASS_WAITING_TOOL_RELEASE_PREPARATION_AUTHORIZATION"
            and state.get("highest_completed_external_gate")
            == "LINKAGE_SELF_CONFORMANCE_PASS_PASS"
            and state.get("open_blocker_codes")
            == ["LINKAGE_TOOL_RELEASE_PREPARATION_AUTHORIZATION_REQUIRED"]
            and state.get("active_dag_node") is None
            and state.get("install_started") is False
            and state.get("side_effects_allowed") is False
            and repository_hash
            == "233a86228fdd78526d378628822cdb10d94ddc446b42cdd514ff9635570b80fa"
            and repository_count == 11
            and not any(path.exists() for path in forbidden_paths)
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_linkage_bootstrap_completion_materialization(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept a receipt-bound ordered Linkage bootstrap completion only."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        def read_json(path: Path) -> Mapping[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError(f"expected object: {path}")
            return value

        def bound(
            document: Mapping[str, Any], ref_key: str, hash_key: str
        ) -> bool:
            path = resolve_ref(document.get(ref_key))
            return bool(path.is_file() and document.get(hash_key) == _file_hash(path))

        control = execution_root / "control_plane"
        evidence = execution_root / "evidence"
        repository = execution_root / "project_start_packages/linkage_review/repository"
        linkage_evidence = evidence / "engineering_dag/LINKAGE_BOOTSTRAP"
        repair_authorization_path = (
            control
            / "LINKAGE_EXECUTOR_CONTEXT_RESULT_COHERENCE_AND_EVIDENCE_ISOLATION_REPAIR_REVERIFY_AUTHORIZATION.json"
        )
        repair_attestation_path = (
            evidence / "linkage-executor-context-repair/REVERIFICATION_ATTESTATION.json"
        )
        repaired_descriptor_path = (
            control / "LINKAGE_CODEX_EXECUTOR_DESCRIPTOR_AFTER_CONTEXT_REPAIR.json"
        )
        repair_receipt_path = (
            control
            / "LINKAGE_EXECUTOR_CONTEXT_RESULT_COHERENCE_AND_EVIDENCE_ISOLATION_REPAIR_REVERIFICATION_RECEIPT.json"
        )
        authorization_path = (
            control / "LINKAGE_BOOTSTRAP_RETRY_AFTER_EXECUTOR_CONTEXT_REPAIR_AUTHORIZATION.json"
        )
        runtime_path = control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json"
        state_path = control / "CONTROL_PLANE_STATE.json"
        independent_path = linkage_evidence / "INDEPENDENT_VALIDATION_RECEIPT.json"
        result_path = evidence / "engineering_dag/LINKAGE_BOOTSTRAP.result.json"
        promotion_path = evidence / "engineering_dag/LINKAGE_BOOTSTRAP.promotion.json"
        completion_path = control / "LINKAGE_BOOTSTRAP_COMPLETION_RECEIPT.json"
        completed_descriptor_path = (
            control / "LINKAGE_CODEX_EXECUTOR_DESCRIPTOR_AFTER_BOOTSTRAP.json"
        )

        repair_authorization = read_json(repair_authorization_path)
        repair_attestation = read_json(repair_attestation_path)
        repaired_descriptor = read_json(repaired_descriptor_path)
        repair_receipt = read_json(repair_receipt_path)
        authorization = read_json(authorization_path)
        runtime = read_json(runtime_path)
        state = read_json(state_path)
        independent = read_json(independent_path)
        result = read_json(result_path)
        promotion = read_json(promotion_path)
        completion = read_json(completion_path)
        completed_descriptor = read_json(completed_descriptor_path)

        candidate_hash = _candidate_tree_hash(candidate_root)
        launcher_hash = _file_hash(expected_launcher)
        driver_source = execution_root / "control_plane/driver_runtime/program_driver.py"
        driver_source_hash = _file_hash(driver_source)
        manifest_items = authorization.get("command_manifest_refs", [])
        manifests: list[Mapping[str, Any]] = []
        manifest_hashes: list[str] = []
        manifest_bindings_valid = len(manifest_items) == 2
        for item in manifest_items:
            manifest_path = resolve_ref(item.get("ref"))
            manifest = read_json(manifest_path)
            manifest_hash = _file_hash(manifest_path)
            manifests.append(manifest)
            manifest_hashes.append(manifest_hash)
            workpack_id = str(manifest.get("workpack_id", ""))
            attempt_template = (
                linkage_evidence
                / "attempts/{attempt_id}"
                / f"{workpack_id}.agent-result.json"
            ).resolve()
            argv = manifest.get("argv", [])
            output_value = None
            if isinstance(argv, list) and "--output-last-message" in argv:
                index = argv.index("--output-last-message") + 1
                if index < len(argv):
                    output_value = Path(str(argv[index])).resolve()
            prompt = str(argv[-1]) if isinstance(argv, list) and argv else ""
            manifest_bindings_valid = bool(
                manifest_bindings_valid
                and item.get("sha256") == manifest_hash
                and manifest.get("executable_sha256") == launcher_hash
                and manifest.get("repair_authorization_sha256")
                == _file_hash(repair_authorization_path)
                and manifest.get("prior_target_hash_repair_receipt_sha256")
                == "165fa48e8fd057e978ebe470da1f8ee71c37db311bbc21f278254c9e5b3cd02b"
                and manifest.get("status") == "READY_NOT_EXECUTED"
                and manifest.get("auto_execute") is False
                and Path(str(manifest.get("result_output_template_abs"))).resolve()
                == attempt_template
                and output_value == attempt_template
                and "return PASS only when every acceptance_checks item is PASS"
                in prompt
            )

        repository_digest = hashlib.sha256()
        repository_count = 0
        for path in sorted(repository.rglob("*"), key=lambda item: item.as_posix()):
            if (
                not path.is_file()
                or "__pycache__" in path.parts
                or path.suffix in {".pyc", ".pyo"}
            ):
                continue
            repository_digest.update(path.relative_to(repository).as_posix().encode())
            repository_digest.update(b"\0")
            repository_digest.update(_file_hash(path).encode("ascii"))
            repository_digest.update(b"\n")
            repository_count += 1
        repository_hash = repository_digest.hexdigest()

        expected_attempts = [
            "ATTEMPT-63F293065CC94E52ADA3CC586C9D01D0",
            "ATTEMPT-60458615A11A47319D2AE7A185159893",
        ]
        workpack_results: list[Mapping[str, Any]] = []
        workpack_results_valid = True
        for workpack_id, attempt_id, manifest_hash in zip(
            ["LINK-PROTOCOL", "LINK-CLI"], expected_attempts, manifest_hashes
        ):
            workpack_path = (
                evidence
                / f"project_workpacks/CONFORMANCE_LINKAGE_REVIEW/{workpack_id}/WORKPACK_RESULT.json"
            )
            workpack = read_json(workpack_path)
            agent_path = resolve_ref(workpack.get("agent_result_ref"))
            agent = read_json(agent_path)
            checks = agent.get("acceptance_checks", [])
            attempt_segment = f"/attempts/{attempt_id}/"
            workpack_results.append(workpack)
            workpack_results_valid = bool(
                workpack_results_valid
                and workpack.get("status") == "PASS"
                and workpack.get("workpack_id") == workpack_id
                and workpack.get("attempt_id") == attempt_id
                and workpack.get("authorization_sha256") == _file_hash(authorization_path)
                and workpack.get("command_manifest_sha256") == manifest_hash
                and workpack.get("command_exit_code") == 0
                and workpack.get("independent_validation_exit_code") == 0
                and workpack.get("blocking_findings") == []
                and workpack.get("acceptance_checks_all_pass") is True
                and workpack.get("acceptance_check_count") == len(checks)
                and bool(checks)
                and all(check.get("status") == "PASS" for check in checks)
                and agent.get("status") == "PASS"
                and agent.get("blocking_findings") == []
                and bound(workpack, "agent_result_ref", "agent_result_sha256")
                and bound(workpack, "stdout_ref", "stdout_sha256")
                and bound(workpack, "stderr_ref", "stderr_sha256")
                and all(
                    attempt_segment in str(workpack.get(key, ""))
                    for key in ("agent_result_ref", "stdout_ref", "stderr_ref")
                )
            )

        runtime_material = dict(runtime)
        claimed_runtime_hash = runtime_material.pop("state_hash", None)
        evidence_files = {
            path.relative_to(linkage_evidence).as_posix()
            for path in linkage_evidence.rglob("*")
            if path.is_file()
        }
        expected_evidence_files = {
            "INDEPENDENT_FAILURE_VERIFICATION_RECEIPT.json",
            "INDEPENDENT_HASH_REPAIR_RETRY_FAILURE_VERIFICATION_RECEIPT.json",
            "INDEPENDENT_VALIDATION_RECEIPT.json",
            "LINK-PROTOCOL.hash-repair-retry-001.agent-result.json",
            "LINK-PROTOCOL.hash-repair-retry-001.stderr",
            "LINK-PROTOCOL.hash-repair-retry-001.stdout",
            "LINK-PROTOCOL.stderr",
            "LINK-PROTOCOL.stdout",
            "attempts/ATTEMPT-63F293065CC94E52ADA3CC586C9D01D0/LINK-PROTOCOL.agent-result.json",
            "attempts/ATTEMPT-63F293065CC94E52ADA3CC586C9D01D0/LINK-PROTOCOL.stderr",
            "attempts/ATTEMPT-63F293065CC94E52ADA3CC586C9D01D0/LINK-PROTOCOL.stdout",
            "attempts/ATTEMPT-60458615A11A47319D2AE7A185159893/LINK-CLI.agent-result.json",
            "attempts/ATTEMPT-60458615A11A47319D2AE7A185159893/LINK-CLI.stderr",
            "attempts/ATTEMPT-60458615A11A47319D2AE7A185159893/LINK-CLI.stdout",
        }
        expected_workpacks = ["LINK-PROTOCOL", "LINK-CLI"]
        forbidden_paths = [
            execution_root / "planned_executors/manifests/LINK-SELFTEST.resolved-command.json",
            execution_root
            / "planned_executors/manifests/LINKAGE_TOOL_RELEASE_LOCKED.resolved-action.json",
            execution_root / "project_start_packages/main_build",
            execution_root / "planned_runtime",
        ]
        return bool(
            repair_authorization.get("status") == "GRANTED"
            and repair_authorization.get("authorization_class")
            == "REPAIR_REVERIFY_AUTHORIZATION"
            and repair_authorization.get("candidate_content_sha256") == candidate_hash
            and repair_authorization.get("max_driver_transitions") == 0
            and repair_authorization.get("workpack_execution_authorized") is False
            and repair_attestation.get("status") == "PASS"
            and repair_attestation.get("authorization_sha256")
            == _file_hash(repair_authorization_path)
            and repair_attestation.get("driver_source_sha256") == driver_source_hash
            and len(repair_attestation.get("checks", [])) == 10
            and all(
                check.get("status") == "PASS"
                for check in repair_attestation.get("checks", [])
            )
            and repaired_descriptor.get("status")
            == "REPAIRED_REVERIFIED_READY_FOR_NEW_LINKAGE_BOOTSTRAP_RETRY_AUTHORIZATION"
            and repaired_descriptor.get("authorization_sha256")
            == _file_hash(repair_authorization_path)
            and repaired_descriptor.get("driver_source_sha256") == driver_source_hash
            and repaired_descriptor.get("result_coherence_contract")
            == "TOP_LEVEL_PASS_REQUIRES_ALL_ACCEPTANCE_CHECKS_PASS"
            and repair_receipt.get("status")
            == "COMPLETE_READY_FOR_HASH_BOUND_2_TRANSITION_LINKAGE_BOOTSTRAP_RETRY_AUTHORIZATION"
            and repair_receipt.get("authorization_sha256")
            == _file_hash(repair_authorization_path)
            and repair_receipt.get("descriptor_sha256") == _file_hash(repaired_descriptor_path)
            and repair_receipt.get("authorization_transitions_consumed") == 0
            and authorization.get("status") == "GRANTED"
            and authorization.get("authorization_class")
            == "REPAIR_REVERIFY_AND_WORKPACK_RETRY_AUTHORIZATION"
            and authorization.get("candidate_content_sha256") == candidate_hash
            and authorization.get("max_transitions") == 2
            and authorization.get("granted_transitions") == 2
            and authorization.get("scope", {}).get("workpack_ids") == expected_workpacks
            and authorization.get("consumption_policy", {}).get("exact_workpack_order")
            == expected_workpacks
            and authorization.get("consumption_policy", {}).get(
                "require_attempt_scoped_output_paths"
            )
            is True
            and authorization.get("consumption_policy", {}).get(
                "require_workpack_acceptance_checks_all_pass"
            )
            is True
            and authorization.get("repair_reverification_receipt_sha256")
            == _file_hash(repair_receipt_path)
            and authorization.get("driver_source_sha256") == driver_source_hash
            and authorization.get("command_manifest_hashes") == manifest_hashes
            and manifest_bindings_valid
            and [manifest.get("workpack_id") for manifest in manifests]
            == expected_workpacks
            and workpack_results_valid
            and claimed_runtime_hash == _json_hash(runtime_material)
            and runtime.get("state_revision") == 22
            and runtime.get("driver_status") == "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED"
            and runtime.get("active_dag_node") is None
            and runtime.get("open_blocker_codes") == []
            and runtime.get("completed_workpack_ids")[-2:] == expected_workpacks
            and runtime.get("authorization_consumptions", {}).get(
                authorization.get("authorization_id")
            )
            == 2
            and independent.get("status") == "PASS"
            and independent.get("blocking_findings") == []
            and len(independent.get("checks", [])) == 9
            and all(check.get("status") == "PASS" for check in independent.get("checks", []))
            and independent.get("repository_content_sha256") == repository_hash
            and independent.get("repository_content_file_count") == repository_count
            and result.get("status") == "PASS"
            and result.get("success_gate") == "LINKAGE_BOOTSTRAP_PASS"
            and result.get("completed_workpack_ids") == expected_workpacks
            and result.get("repository_content_sha256") == repository_hash
            and promotion.get("status")
            == "PROMOTED_STOPPED_BEFORE_LINKAGE_SELF_CONFORMANCE"
            and promotion.get("next_node_id") == "LINKAGE_SELF_CONFORMANCE_PASS"
            and promotion.get("next_node_activated") is False
            and completion.get("status")
            == "LINKAGE_BOOTSTRAP_COMPLETE_STOPPED_BEFORE_SELFTEST"
            and completion.get("authorization_sha256") == _file_hash(authorization_path)
            and completion.get("authorization_transitions_consumed") == 2
            and completion.get("completed_workpack_ids") == expected_workpacks
            and completion.get("repository_content_sha256") == repository_hash
            and completion.get("repository_content_file_count") == repository_count
            and completion.get("link_selftest_started") is False
            and completion.get("linkage_self_conformance_started") is False
            and completion.get("linkage_tool_release_started") is False
            and completion.get("main_project_started") is False
            and completion.get("install_started") is False
            and bound(completion, "independent_validation_receipt_ref", "independent_validation_receipt_sha256")
            and bound(completion, "linkage_bootstrap_result_ref", "linkage_bootstrap_result_sha256")
            and bound(completion, "linkage_bootstrap_promotion_ref", "linkage_bootstrap_promotion_sha256")
            and completed_descriptor.get("status")
            == "ORDERED_LINKAGE_BOOTSTRAP_SCOPE_CONSUMED_STOPPED"
            and completed_descriptor.get("completion_receipt_sha256")
            == _file_hash(completion_path)
            and completed_descriptor.get("completed_workpack_ids") == expected_workpacks
            and completed_descriptor.get("driver_source_sha256") == driver_source_hash
            and completed_descriptor.get("next_node_activated") is False
            and state.get("state")
            == "LINKAGE_BOOTSTRAP_PASS_WAITING_SELF_CONFORMANCE_AUTHORIZATION"
            and state.get("highest_completed_external_gate") == "LINKAGE_BOOTSTRAP_PASS"
            and state.get("open_blocker_codes")
            == ["LINKAGE_SELF_CONFORMANCE_AUTHORIZATION_REQUIRED"]
            and state.get("active_dag_node") is None
            and state.get("install_started") is False
            and state.get("side_effects_allowed") is False
            and repository_hash
            == "233a86228fdd78526d378628822cdb10d94ddc446b42cdd514ff9635570b80fa"
            and repository_count == 11
            and evidence_files == expected_evidence_files
            and not any(path.exists() for path in forbidden_paths)
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_linkage_executor_no_op_failure_materialization(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept a Hash-repaired Linkage retry stopped after a verified agent no-op."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        def read_json(path: Path) -> Mapping[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError(f"expected object: {path}")
            return value

        def bound(
            document: Mapping[str, Any], ref_key: str, hash_key: str
        ) -> bool:
            path = resolve_ref(document.get(ref_key))
            return bool(
                path.is_file()
                and document.get(hash_key) == _file_hash(path)
            )

        control = execution_root / "control_plane"
        evidence = execution_root / "evidence"
        repair_authorization_path = (
            control / "LINKAGE_CODEX_TARGET_HASH_DRIFT_REPAIR_REVERIFY_AUTHORIZATION.json"
        )
        repair_attestation_path = (
            evidence / "linkage-bootstrap-executor-repair/REVERIFICATION_ATTESTATION.json"
        )
        repaired_descriptor_path = (
            control / "LINKAGE_CODEX_EXECUTOR_DESCRIPTOR_AFTER_TARGET_HASH_REPAIR.json"
        )
        repair_receipt_path = (
            control / "LINKAGE_CODEX_TARGET_HASH_REPAIR_REVERIFICATION_RECEIPT.json"
        )
        retry_authorization_path = (
            control / "LINKAGE_BOOTSTRAP_RETRY_AFTER_CODEX_TARGET_HASH_REPAIR_AUTHORIZATION.json"
        )
        failure_receipt_path = control / "LINKAGE_EXECUTOR_CONTEXT_NO_OP_FAILURE_RECEIPT.json"
        state_path = control / "CONTROL_PLANE_STATE.json"
        runtime_path = control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json"
        ledger_path = control / "runtime/PHASE_TRANSITION_LEDGER.jsonl"
        failure_result_path = (
            evidence / "engineering_dag/LINKAGE_BOOTSTRAP.hash-repair-retry-failure-result.json"
        )
        failure_verification_path = (
            evidence
            / "engineering_dag/LINKAGE_BOOTSTRAP/INDEPENDENT_HASH_REPAIR_RETRY_FAILURE_VERIFICATION_RECEIPT.json"
        )
        next_draft_path = (
            control
            / "LINKAGE_EXECUTOR_CONTEXT_RESULT_COHERENCE_AND_EVIDENCE_ISOLATION_REPAIR_REVERIFY_AND_BOOTSTRAP_RETRY_AUTHORIZATION_DRAFT.json"
        )
        repair_authorization = read_json(repair_authorization_path)
        repair_attestation = read_json(repair_attestation_path)
        repaired_descriptor = read_json(repaired_descriptor_path)
        repair_receipt = read_json(repair_receipt_path)
        retry_authorization = read_json(retry_authorization_path)
        failure_receipt = read_json(failure_receipt_path)
        state = read_json(state_path)
        runtime = read_json(runtime_path)
        failure_result = read_json(failure_result_path)
        failure_verification = read_json(failure_verification_path)
        next_draft = read_json(next_draft_path)
        agent_result_path = resolve_ref(failure_receipt.get("agent_result_ref"))
        agent_result = read_json(agent_result_path)

        candidate_hash = _candidate_tree_hash(candidate_root)
        launcher_hash = _file_hash(expected_launcher)
        target_path = Path(str(repair_attestation.get("codex_target_abs", ""))).resolve()
        target_hash = _file_hash(target_path)
        retry_authorization_id = retry_authorization.get("authorization_id")
        scope = retry_authorization.get("scope", {})
        runtime_material = dict(runtime)
        claimed_runtime_hash = runtime_material.pop("state_hash", None)
        manifest_items = retry_authorization.get("command_manifest_refs", [])
        manifests: list[Mapping[str, Any]] = []
        manifest_bindings_valid = len(manifest_items) == 2
        for item in manifest_items:
            manifest_path = resolve_ref(item.get("ref"))
            manifest = read_json(manifest_path)
            manifests.append(manifest)
            manifest_bindings_valid = bool(
                manifest_bindings_valid
                and item.get("sha256") == _file_hash(manifest_path)
                and manifest.get("executable_sha256") == launcher_hash
                and manifest.get("status") == "READY_NOT_EXECUTED"
                and manifest.get("auto_execute") is False
            )

        linkage_repository = (
            execution_root / "project_start_packages/linkage_review/repository"
        )
        linkage_evidence = evidence / "engineering_dag/LINKAGE_BOOTSTRAP"
        repository_files = [
            path for path in linkage_repository.rglob("*") if path.is_file()
        ]
        evidence_files = {
            path.relative_to(linkage_evidence).as_posix()
            for path in linkage_evidence.rglob("*")
            if path.is_file()
        }
        expected_evidence_files = {
            "INDEPENDENT_FAILURE_VERIFICATION_RECEIPT.json",
            "INDEPENDENT_HASH_REPAIR_RETRY_FAILURE_VERIFICATION_RECEIPT.json",
            "LINK-PROTOCOL.hash-repair-retry-001.agent-result.json",
            "LINK-PROTOCOL.hash-repair-retry-001.stderr",
            "LINK-PROTOCOL.hash-repair-retry-001.stdout",
            "LINK-PROTOCOL.stderr",
            "LINK-PROTOCOL.stdout",
        }
        blockers = [
            "LINKAGE_EXECUTOR_AUTHORIZATION_CONTEXT_NOT_PROPAGATED",
            "WORKPACK_RESULT_ACCEPTANCE_COHERENCE_REPAIR_REQUIRED",
            "LINKAGE_BOOTSTRAP_RETRY_REAUTHORIZATION_REQUIRED",
        ]
        acceptance_checks = agent_result.get("acceptance_checks", [])
        return bool(
            repair_authorization.get("status") == "GRANTED"
            and repair_authorization.get("authorization_class")
            == "REPAIR_REVERIFY_AUTHORIZATION"
            and repair_authorization.get("candidate_content_sha256") == candidate_hash
            and repair_authorization.get("max_driver_transitions") == 0
            and repair_authorization.get("driver_execution_authorized") is False
            and repair_authorization.get("workpack_execution_authorized") is False
            and repair_attestation.get("status") == "PASS"
            and repair_attestation.get("blocking_findings") == []
            and repair_attestation.get("authorization_sha256")
            == _file_hash(repair_authorization_path)
            and repair_attestation.get("codex_launcher_sha256") == launcher_hash
            and target_path.is_file()
            and repair_attestation.get("codex_target_sha256") == target_hash
            and all(
                check.get("status") == "PASS"
                for check in repair_attestation.get("checks", [])
            )
            and repaired_descriptor.get("status")
            == "REPAIRED_REVERIFIED_READY_FOR_NEW_LINKAGE_BOOTSTRAP_RETRY_AUTHORIZATION"
            and repaired_descriptor.get("authorization_sha256")
            == _file_hash(repair_authorization_path)
            and repaired_descriptor.get("reverification_attestation_sha256")
            == _file_hash(repair_attestation_path)
            and repaired_descriptor.get("launcher_sha256") == launcher_hash
            and repaired_descriptor.get("target_sha256") == target_hash
            and repaired_descriptor.get("runtime_state_revision") == 16
            and repaired_descriptor.get("workpack_execution_started_after_repair")
            is False
            and repair_receipt.get("status")
            == "COMPLETE_READY_FOR_HASH_BOUND_2_TRANSITION_LINKAGE_BOOTSTRAP_RETRY_AUTHORIZATION"
            and repair_receipt.get("authorization_sha256")
            == _file_hash(repair_authorization_path)
            and repair_receipt.get("descriptor_sha256")
            == _file_hash(repaired_descriptor_path)
            and repair_receipt.get("reverification_attestation_sha256")
            == _file_hash(repair_attestation_path)
            and repair_receipt.get("authorization_transitions_consumed") == 0
            and retry_authorization.get("status") == "GRANTED"
            and retry_authorization.get("authorization_class")
            == "REPAIR_REVERIFY_AND_WORKPACK_RETRY_AUTHORIZATION"
            and retry_authorization.get("candidate_content_sha256") == candidate_hash
            and retry_authorization.get("max_transitions") == 2
            and retry_authorization.get("granted_transitions") == 2
            and retry_authorization.get("authorization_scope_sha256")
            == _json_hash(scope)
            and scope.get("workpack_ids") == ["LINK-PROTOCOL", "LINK-CLI"]
            and retry_authorization.get("consumption_policy", {}).get(
                "exact_workpack_order"
            )
            == ["LINK-PROTOCOL", "LINK-CLI"]
            and retry_authorization.get("consumption_policy", {}).get(
                "stop_on_first_failure"
            )
            is True
            and retry_authorization.get("repair_reverification_receipt_sha256")
            == _file_hash(repair_receipt_path)
            and manifest_bindings_valid
            and [manifest.get("workpack_id") for manifest in manifests]
            == ["LINK-PROTOCOL", "LINK-CLI"]
            and failure_receipt.get("status")
            == "FAILED_NO_CODE_AFTER_HASH_REPAIR_STOPPED"
            and failure_receipt.get("candidate_content_sha256") == candidate_hash
            and failure_receipt.get("authorization_sha256")
            == _file_hash(retry_authorization_path)
            and failure_receipt.get("failed_workpack_id") == "LINK-PROTOCOL"
            and failure_receipt.get("codex_command_exit_code") == 0
            and failure_receipt.get("independent_validation_exit_code") == 1
            and failure_receipt.get("code_files_written") == []
            and failure_receipt.get("repository_file_count") == 0
            and failure_receipt.get("link_cli_started") is False
            and failure_receipt.get("next_workpack_started") is False
            and failure_receipt.get(
                "residual_transition_budget_invalidated_by_stop_on_failure"
            )
            is True
            and failure_receipt.get("authorization_transitions_consumed") == 1
            and failure_receipt.get("authorization_transitions_granted") == 2
            and failure_receipt.get("runtime_state_after_failure_sha256")
            == _file_hash(runtime_path)
            and failure_receipt.get("transition_ledger_sha256")
            == _file_hash(ledger_path)
            and bound(failure_receipt, "agent_result_ref", "agent_result_sha256")
            and bound(failure_receipt, "failure_result_ref", "failure_result_sha256")
            and bound(
                failure_receipt,
                "independent_failure_verification_ref",
                "independent_failure_verification_sha256",
            )
            and bound(failure_receipt, "stderr_ref", "stderr_sha256")
            and bound(failure_receipt, "stdout_ref", "stdout_sha256")
            and claimed_runtime_hash == _json_hash(runtime_material)
            and runtime.get("driver_status") == "BLOCKED_WORKPACK_VALIDATION_FAIL"
            and runtime.get("state_revision") == 18
            and runtime.get("active_dag_node") == "LINKAGE_BOOTSTRAP"
            and runtime.get("active_workpack_id") is None
            and runtime.get("side_effects_allowed") is False
            and runtime.get("authorization_consumptions", {}).get(
                retry_authorization_id
            )
            == 1
            and failure_result.get("status")
            == "FAIL_STOPPED_NO_CODE_AFTER_HASH_REPAIR"
            and failure_result.get("blocking_findings") == blockers
            and failure_result.get("completed_workpack_ids") == []
            and failure_result.get("link_cli_started") is False
            and failure_result.get("link_protocol_code_written") is False
            and failure_result.get("residual_transition_budget_reusable") is False
            and failure_verification.get("status")
            == "FAIL_CONFIRMED_NO_CODE_AFTER_HASH_REPAIR"
            and failure_verification.get("blocking_findings") == blockers[:2]
            and failure_verification.get("link_cli_started") is False
            and failure_verification.get("link_protocol_code_written") is False
            and failure_verification.get("repository_file_count") == 0
            and agent_result.get("status") == "PASS"
            and agent_result.get("changed_files") == []
            and any(
                check.get("status") == "FAIL" for check in acceptance_checks
            )
            and state.get("state")
            == "LINKAGE_BOOTSTRAP_BLOCKED_EXECUTOR_CONTEXT_NO_OP_WAITING_REPAIR_RETRY_AUTHORIZATION"
            and state.get("highest_completed_external_gate")
            == "LAB_TOOL_RELEASE_LOCKED_PASS"
            and state.get("open_blocker_codes") == blockers
            and state.get("install_started") is False
            and state.get("side_effects_allowed") is False
            and next_draft.get("status") == "DRAFT_BLOCKED_NOT_GRANTED"
            and next_draft.get("grantable") is False
            and next_draft.get("execution_authorized") is False
            and next_draft.get("max_transitions") == 0
            and next_draft.get("failure_receipt_sha256")
            == _file_hash(failure_receipt_path)
            and linkage_repository.is_dir()
            and repository_files == []
            and evidence_files == expected_evidence_files
            and not (linkage_evidence / "LINK-PROTOCOL.agent-result.json").exists()
            and not (
                evidence / "project_workpacks/CONFORMANCE_LINKAGE_REVIEW"
            ).exists()
            and not (
                execution_root
                / "planned_executors/manifests/LINK-SELFTEST.resolved-command.json"
            ).exists()
            and not (
                execution_root
                / "planned_executors/manifests/LINKAGE_TOOL_RELEASE_LOCKED.resolved-action.json"
            ).exists()
            and not (execution_root / "project_start_packages/main_build").exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _authorized_linkage_bootstrap_failure_materialization(
    candidate_root: Path,
    execution_root: Path,
    executable_path: Path,
    command: Mapping[str, Any],
) -> bool:
    """Accept a receipt-bound Linkage attempt stopped before model or code work."""

    if command.get("executor_role") != "CODEX_CODING_AGENT":
        return False
    try:
        expected_launcher = execution_root / "planned_executors/bin/codex"
        if executable_path.resolve() != expected_launcher.resolve():
            return False
        build_root = execution_root.parent

        def resolve_ref(ref: Any) -> Path:
            path = Path(str(ref))
            return (path if path.is_absolute() else build_root / path).resolve()

        control = execution_root / "control_plane"
        evidence = execution_root / "evidence"
        authorization_path = control / "LINKAGE_BOOTSTRAP_EXECUTION_AUTHORIZATION.json"
        receipt_path = control / "LINKAGE_CODEX_TARGET_HASH_DRIFT_FAILURE_RECEIPT.json"
        state_path = control / "CONTROL_PLANE_STATE.json"
        runtime_path = control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json"
        failure_result_path = evidence / "engineering_dag/LINKAGE_BOOTSTRAP.failure-result.json"
        failure_verification_path = (
            evidence
            / "engineering_dag/LINKAGE_BOOTSTRAP/INDEPENDENT_FAILURE_VERIFICATION_RECEIPT.json"
        )
        authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        state = json.loads(state_path.read_text(encoding="utf-8"))
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        failure_result = json.loads(failure_result_path.read_text(encoding="utf-8"))
        failure_verification = json.loads(
            failure_verification_path.read_text(encoding="utf-8")
        )
        candidate_hash = _candidate_tree_hash(candidate_root)
        authorization_id = authorization.get("authorization_id")
        scope = authorization.get("scope", {})
        forbidden = set(authorization.get("forbidden_actions", []))
        runtime_material = dict(runtime)
        claimed_runtime_hash = runtime_material.pop("state_hash", None)
        manifest_items = authorization.get("command_manifest_refs", [])
        manifests: list[Mapping[str, Any]] = []
        manifest_bindings_valid = len(manifest_items) == 2
        for item in manifest_items:
            manifest_path = resolve_ref(item.get("ref"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifests.append(manifest)
            manifest_bindings_valid = bool(
                manifest_bindings_valid
                and item.get("sha256") == _file_hash(manifest_path)
                and manifest.get("executable_sha256") == _file_hash(expected_launcher)
                and manifest.get("status") == "READY_NOT_EXECUTED"
                and manifest.get("auto_execute") is False
            )
        linkage_repository = (
            execution_root / "project_start_packages/linkage_review/repository"
        )
        linkage_evidence = evidence / "engineering_dag/LINKAGE_BOOTSTRAP"
        repository_files = [
            path for path in linkage_repository.rglob("*") if path.is_file()
        ]
        evidence_files = {
            path.relative_to(linkage_evidence).as_posix()
            for path in linkage_evidence.rglob("*")
            if path.is_file()
        }
        expected_evidence_files = {
            "INDEPENDENT_FAILURE_VERIFICATION_RECEIPT.json",
            "LINK-PROTOCOL.stderr",
            "LINK-PROTOCOL.stdout",
        }
        expected_workpacks = [
            "LAB-PROTOCOL",
            "LAB-CLI",
            "LAB-FIXTURES",
            "LAB-SELFTEST",
        ]
        return bool(
            authorization.get("status") == "GRANTED"
            and authorization.get("authorization_class")
            == "PROJECT_BOOTSTRAP_AUTHORIZATION"
            and authorization.get("candidate_content_sha256") == candidate_hash
            and authorization.get("max_transitions") == 2
            and authorization.get("granted_transitions") == 2
            and authorization.get("may_auto_advance") is False
            and authorization.get("real_target_install_allowed") is False
            and authorization.get("authorization_scope_sha256")
            == _json_hash(scope)
            and scope.get("dag_node_ids") == ["LINKAGE_BOOTSTRAP"]
            and scope.get("project_ids") == ["CONFORMANCE_LINKAGE_REVIEW"]
            and scope.get("workpack_ids") == ["LINK-PROTOCOL", "LINK-CLI"]
            and authorization.get("consumption_policy", {}).get(
                "exact_workpack_order"
            )
            == ["LINK-PROTOCOL", "LINK-CLI"]
            and {
                "LINKAGE_SELF_CONFORMANCE",
                "LINKAGE_TOOL_RELEASE",
                "MAIN_PROJECT_BOOTSTRAP",
                "LAB_CERTIFICATION",
                "TARGET_RUNTIME_INSTALLATION",
                "REAL_TARGET_INSTALL",
                "INSTALL",
            }.issubset(forbidden)
            and manifest_bindings_valid
            and [manifest.get("workpack_id") for manifest in manifests]
            == ["LINK-PROTOCOL", "LINK-CLI"]
            and receipt.get("status")
            == "FAILED_BEFORE_MODEL_WORK_AND_CODE_WRITE_STOPPED"
            and receipt.get("candidate_content_sha256") == candidate_hash
            and receipt.get("authorization_sha256") == _file_hash(authorization_path)
            and resolve_ref(receipt.get("authorization_ref"))
            == authorization_path.resolve()
            and receipt.get("failed_workpack_id") == "LINK-PROTOCOL"
            and receipt.get("command_exit_code") == 126
            and receipt.get("independent_validation_exit_code") == 1
            and receipt.get("code_files_written") == []
            and receipt.get("link_protocol_agent_result_created") is False
            and receipt.get("link_cli_started") is False
            and receipt.get("next_workpack_started") is False
            and receipt.get(
                "residual_transition_budget_invalidated_by_stop_on_failure"
            )
            is True
            and receipt.get("authorization_transitions_consumed") == 1
            and receipt.get("authorization_transitions_granted") == 2
            and receipt.get("codex_launcher_sha256") == _file_hash(expected_launcher)
            and receipt.get("codex_target_current_sha256")
            != receipt.get("codex_target_expected_sha256")
            and receipt.get("runtime_state_after_failure_sha256")
            == _file_hash(runtime_path)
            and resolve_ref(receipt.get("runtime_state_after_failure_ref"))
            == runtime_path.resolve()
            and receipt.get("failure_result_sha256")
            == _file_hash(failure_result_path)
            and resolve_ref(receipt.get("failure_result_ref"))
            == failure_result_path.resolve()
            and receipt.get("independent_failure_verification_sha256")
            == _file_hash(failure_verification_path)
            and resolve_ref(receipt.get("independent_failure_verification_ref"))
            == failure_verification_path.resolve()
            and receipt.get("stderr_sha256")
            == _file_hash(linkage_evidence / "LINK-PROTOCOL.stderr")
            and receipt.get("stdout_sha256")
            == _file_hash(linkage_evidence / "LINK-PROTOCOL.stdout")
            and claimed_runtime_hash == _json_hash(runtime_material)
            and runtime.get("driver_status") == "BLOCKED_WORKPACK_VALIDATION_FAIL"
            and runtime.get("state_revision") == 16
            and runtime.get("active_dag_node") == "LINKAGE_BOOTSTRAP"
            and runtime.get("active_workpack_id") is None
            and runtime.get("active_pipeline_action_id") is None
            and runtime.get("side_effects_allowed") is False
            and runtime.get("completed_workpack_ids") == expected_workpacks
            and runtime.get("completed_pipeline_action_ids")
            == ["LAB_TOOL_RELEASE_LOCKED"]
            and runtime.get("authorization_consumptions", {}).get(authorization_id)
            == 1
            and runtime.get("open_blocker_codes")
            == ["WORKPACK_RESULT_OR_INDEPENDENT_VALIDATION_FAILED"]
            and runtime.get("recovery", {}).get("required") is False
            and failure_result.get("status")
            == "FAIL_STOPPED_BEFORE_MODEL_WORK_AND_CODE_WRITE"
            and failure_result.get("completed_workpack_ids") == []
            and failure_result.get("failed_workpack_id") == "LINK-PROTOCOL"
            and failure_result.get("link_cli_started") is False
            and failure_result.get("link_protocol_code_written") is False
            and failure_result.get("residual_transition_budget_reusable") is False
            and failure_verification.get("status")
            == "FAIL_CONFIRMED_BEFORE_MODEL_WORK_AND_CODE_WRITE"
            and failure_verification.get("link_protocol_code_written") is False
            and failure_verification.get("link_cli_started") is False
            and failure_verification.get("link_protocol_agent_result_created")
            is False
            and state.get("state")
            == "LINKAGE_BOOTSTRAP_BLOCKED_CODEX_TARGET_HASH_DRIFT_WAITING_REPAIR_RETRY_AUTHORIZATION"
            and state.get("highest_completed_external_gate")
            == "LAB_TOOL_RELEASE_LOCKED_PASS"
            and state.get("open_blocker_codes")
            == [
                "CODEX_CLI_TARGET_HASH_DRIFT",
                "LINKAGE_BOOTSTRAP_RETRY_REAUTHORIZATION_REQUIRED",
            ]
            and state.get("install_started") is False
            and state.get("side_effects_allowed") is False
            and linkage_repository.is_dir()
            and repository_files == []
            and evidence_files == expected_evidence_files
            and not (linkage_evidence / "LINK-PROTOCOL.agent-result.json").exists()
            and not (
                evidence / "project_workpacks/CONFORMANCE_LINKAGE_REVIEW"
            ).exists()
            and not (
                execution_root
                / "planned_executors/manifests/LINK-SELFTEST.resolved-command.json"
            ).exists()
            and not (
                execution_root
                / "planned_executors/manifests/LINKAGE_TOOL_RELEASE_LOCKED.resolved-action.json"
            ).exists()
            and not (execution_root / "project_start_packages/main_build").exists()
            and not (execution_root / "planned_runtime").exists()
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


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


def _candidate_tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    excluded_names = {".DS_Store"}
    excluded_parts = {".git", "__pycache__"}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_dir() or path.name in excluded_names:
            continue
        relative = path.relative_to(root)
        if any(part in excluded_parts for part in relative.parts):
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(_file_hash(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()
