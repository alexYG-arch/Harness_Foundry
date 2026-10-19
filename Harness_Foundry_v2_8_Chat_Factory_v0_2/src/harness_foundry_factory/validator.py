"""Pure static validator for Harness Foundry v2.8 authoring candidates.

The validator deliberately never reads, resolves, or executes content from the
planned execution root. Runtime materialization, executable symlink targets,
authorizations, and receipts belong to the separate Controlled Execution
Runtime.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from .constants import TARGET_CANDIDATE_STATE
from . import legacy_execution_evidence_validator_v0_1 as legacy


SHA256_RE = legacy.SHA256_RE
CheckFunction = Callable[[Path], list[dict[str, Any]]]


def _finding(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _lexical_path(value: Any) -> Path:
    """Return an absolute normalized path without resolving symlinks."""

    return Path(os.path.abspath(os.path.expanduser(str(value))))


def _lexically_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((str(path), str(root))) == str(root)
    except ValueError:
        return False


def _context_roots(
    root: Path, findings: list[dict[str, Any]]
) -> tuple[Path, Path, dict[str, Any]]:
    context = legacy._read_json(root / "START_CONTEXT.json", findings)
    if not isinstance(context, dict):
        return root, root, {}
    candidate_root = _lexical_path(
        context.get("candidate_root") or context.get("target_root") or root
    )
    execution_root = _lexical_path(
        context.get("execution_root") or candidate_root
    )
    return candidate_root, execution_root, context


def _check_candidate_execution_separation(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    candidate_root, execution_root, context = _context_roots(root, findings)
    if not context:
        return findings
    if context.get("candidate_root_access") != "READ_ONLY_AFTER_ATOMIC_PUBLICATION":
        findings.append(
            _finding(
                "CANDIDATE_IMMUTABILITY_POLICY_MISSING",
                "candidate_root_access must be READ_ONLY_AFTER_ATOMIC_PUBLICATION",
            )
        )
        return findings
    if (
        context.get("target_root") != str(candidate_root)
        or context.get("candidate_root") != str(candidate_root)
        or context.get("execution_root") != str(execution_root)
        or context.get("execution_root_status") != "PLANNED_NOT_CREATED"
        or context.get("candidate_execution_root_overlap") is not False
        or candidate_root == execution_root
        or _lexically_within(candidate_root, execution_root)
        or _lexically_within(execution_root, candidate_root)
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
        path = Path(os.path.expanduser(str(value)))
        if not path.is_absolute() or not _lexically_within(
            _lexical_path(path), expected_root
        ):
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
        document = legacy._read_json(path, findings)
        if isinstance(document, (dict, list)):
            visit(document, path.relative_to(root).as_posix())

    capsule = legacy._read_json(root / "CAPSULE.json", findings)
    forbidden = (
        capsule.get("forbidden_write_paths", [])
        if isinstance(capsule, dict)
        else []
    )
    if str(candidate_root) not in forbidden:
        findings.append(
            _finding(
                "CANDIDATE_IMMUTABILITY_VIOLATION",
                "CAPSULE.json must forbid the entire candidate root",
            )
        )
    return findings


def _check_static_authoring_boundary(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    context = legacy._read_json(root / "START_CONTEXT.json", findings)
    program = legacy._read_json(root / "PROGRAM_STATE.json", findings)
    driver = legacy._read_json(root / "PROGRAM_DRIVER_STATE.json", findings)
    authorization = legacy._read_json(
        root / "EXECUTION_AUTHORIZATION.json", findings
    )
    real_install = legacy._read_json(
        root / "REAL_TARGET_INSTALL_AUTHORIZATION.json", findings
    )
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
        for key, expected_value in expected.items():
            if context.get(key) != expected_value:
                findings.append(
                    _finding(
                        "AUTHORING_CONTEXT_VIOLATION",
                        f"{key}={context.get(key)!r}",
                    )
                )
    if isinstance(program, dict):
        if any(
            program.get(key) is not None
            for key in (
                "current_phase",
                "highest_touched_phase",
                "highest_locally_closed_phase",
                "active_workpack",
            )
        ):
            findings.append(
                _finding(
                    "PROGRAM_EXECUTION_STATE_PREPOPULATED",
                    "PROGRAM_STATE.json",
                )
            )
        if program.get("auto_start_generated_workpacks") is not False:
            findings.append(
                _finding("PROGRAM_AUTO_START_FORBIDDEN", "PROGRAM_STATE.json")
            )
    if isinstance(driver, dict) and (
        driver.get("driver_started") is not False
        or driver.get("controlled_auto_advance_enabled") is not False
        or driver.get("side_effects_allowed") is not False
        or driver.get("active_workpack_id") is not None
    ):
        findings.append(
            _finding("DRIVER_STARTED_OR_AUTHORIZED", "PROGRAM_DRIVER_STATE.json")
        )
    if isinstance(authorization, dict) and (
        authorization.get("status") in {"GRANTED", "ISSUED", "ACTIVE"}
        or authorization.get("may_auto_advance") is not False
        or authorization.get("max_transitions") != 0
        or authorization.get("real_target_install_allowed") is not False
    ):
        findings.append(
            _finding(
                "EXECUTION_AUTHORIZATION_PREGRANTED",
                "EXECUTION_AUTHORIZATION.json",
            )
        )
    if isinstance(real_install, dict) and (
        real_install.get("status") in {"GRANTED", "ISSUED", "ACTIVE"}
        or real_install.get("may_be_generated_or_self_granted_by_driver")
        is not False
    ):
        findings.append(
            _finding(
                "REAL_INSTALL_AUTHORIZATION_PREGRANTED",
                "REAL_TARGET_INSTALL_AUTHORIZATION.json",
            )
        )

    _candidate_root, execution_root, _context = _context_roots(
        root, findings
    )
    command_files = [
        root / "COMMAND_MANIFEST.json",
        *root.glob("project_start_packages/*/COMMAND_MANIFEST.json"),
    ]
    for path in command_files:
        command_manifest = legacy._read_json(path, findings)
        if not isinstance(command_manifest, dict):
            continue
        for command in command_manifest.get("commands", []):
            if not isinstance(command, dict):
                continue
            command_id = command.get("command_id")
            executable = command.get(
                "executable_abs", command.get("executable")
            )
            executable_path = (
                _lexical_path(executable) if executable else Path("")
            )
            argv = command.get("argv")
            cwd = command.get("cwd_abs") or command.get("cwd_absolute")
            cwd_path = _lexical_path(cwd) if cwd else Path("")
            if (
                not executable
                or not Path(str(executable)).is_absolute()
                or not _lexically_within(executable_path, execution_root)
            ):
                findings.append(
                    _finding(
                        "COMMAND_EXECUTABLE_NOT_ABSOLUTE",
                        f"{path.name}:{command_id}",
                    )
                )
            if command.get("command_kind") == "PLANNED_EXECUTOR_INTERFACE":
                command_plan_invalid = (
                    argv is not None
                    or not cwd
                    or not Path(str(cwd)).is_absolute()
                    or not _lexically_within(cwd_path, execution_root)
                    or command.get("executable_status")
                    != "PLANNED_NOT_INSTALLED"
                    or not command.get("preflight_gate")
                    or not str(
                        command.get("invocation_contract_status", "")
                    ).startswith("REQUIRES_")
                    or command.get("unverified_cli_flags_forbidden") is not True
                    or command.get("shell") is not False
                )
            else:
                command_plan_invalid = (
                    not isinstance(argv, list)
                    or not argv
                    or argv[0] != str(executable_path)
                    or not cwd
                    or not Path(str(cwd)).is_absolute()
                    or not _lexically_within(cwd_path, execution_root)
                    or command.get("executable_status")
                    != "PLANNED_NOT_INSTALLED"
                    or not command.get("preflight_gate")
                    or command.get("shell") is True
                )
            if command_plan_invalid:
                findings.append(
                    _finding(
                        "COMMAND_PLAN_CONTRACT_INVALID",
                        f"{path.name}:{command_id}",
                    )
                )
            if (
                command.get("auto_execute") is True
                or command.get("authorization_ref") is not None
            ):
                findings.append(
                    _finding(
                        "COMMAND_AUTO_EXECUTION_FORBIDDEN",
                        f"{path.name}:{command_id}",
                    )
                )
    return findings


def _check_automation_profile(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    policy = legacy._read_json(
        root / "PROGRAM_AUTOMATION_POLICY.json", findings
    )
    if not isinstance(policy, dict):
        return findings
    profile = policy.get("automation_profile")
    allowed_levels = {
        "A0_DECLARE_ONLY",
        "A1_PLAN_ONLY",
        "A2_WORKPACK_BOUNDED",
        "A3_PROGRAM_BOUNDED",
    }
    if not isinstance(profile, dict):
        return [
            _finding(
                "AUTOMATION_PROFILE_MISSING",
                "PROGRAM_AUTOMATION_POLICY.json",
            )
        ]
    required = {
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
    }
    if set(profile) != required:
        findings.append(
            _finding(
                "AUTOMATION_PROFILE_FIELDS_INVALID",
                f"expected={sorted(required)}, actual={sorted(profile)}",
            )
        )
        return findings
    if (
        profile.get("schema_version") != "1.0"
        or profile.get("requested_level") not in allowed_levels
        or profile.get("activation_default") != "DISABLED"
        or not isinstance(profile.get("max_transitions"), int)
        or profile["max_transitions"] <= 0
        or not isinstance(profile.get("max_loop_rounds"), int)
        or profile["max_loop_rounds"] <= 0
        or not isinstance(profile.get("max_wall_time_seconds"), int)
        or profile["max_wall_time_seconds"] <= 0
        or not isinstance(profile.get("stop_gate"), str)
        or not profile["stop_gate"]
        or not isinstance(profile.get("retryable_error_codes"), list)
        or not all(
            isinstance(item, str) and item
            for item in profile["retryable_error_codes"]
        )
        or not isinstance(profile.get("mandatory_human_gate_ids"), list)
        or not all(
            isinstance(item, str) and item
            for item in profile["mandatory_human_gate_ids"]
        )
        or profile.get("real_target_install_excluded") is not True
    ):
        findings.append(
            _finding(
                "AUTOMATION_PROFILE_INVALID",
                "PROGRAM_AUTOMATION_POLICY.json",
            )
        )
    configured_limit = policy.get("controlled_auto_advance", {}).get(
        "max_transitions_per_driver_invocation"
    )
    if configured_limit != profile.get("max_transitions"):
        findings.append(
            _finding(
                "AUTOMATION_TRANSITION_LIMIT_MISMATCH",
                f"profile={profile.get('max_transitions')}, policy={configured_limit}",
            )
        )
    return findings


CHECKS: tuple[tuple[str, CheckFunction], ...] = (
    (
        "REQUIRED_INVENTORY_AND_SYNTAX",
        lambda root: legacy._check_inventory(root) + legacy._check_syntax(root),
    ),
    ("NO_UNRESOLVED_TEMPLATES", legacy._check_placeholders),
    ("IDENTITY_REFERENCES_AND_HASHES", legacy._check_identity_and_refs),
    (
        "CANDIDATE_IMMUTABILITY_AND_EXECUTION_ROOT",
        _check_candidate_execution_separation,
    ),
    ("WORKPACK_ARTIFACT_HASH_BINDINGS", legacy._check_artifact_hashes),
    ("SOURCE_ATOM_AND_COVERAGE", legacy._check_sources_atoms_coverage),
    ("PHASE_P3_AND_RELEASE_ORDER", legacy._check_phase_and_release),
    ("THREE_PROJECT_DAG_AND_PACKAGES", legacy._check_three_projects),
    ("AUTHORING_DEFAULTS_AND_AUTHORIZATION", _check_static_authoring_boundary),
    ("AUTOMATION_PROFILE", _check_automation_profile),
    ("CONTROL_PLANE_HASH_AND_EPOCH_BINDINGS", legacy._check_control_bindings),
    (
        "LOOP_REPAIR_INVALIDATION_AND_RECOVERY",
        legacy._check_control_contracts,
    ),
    (
        "CODEX_FALSE_SUCCESS_AND_INSTALL_BOUNDARY",
        legacy._check_negative_contracts,
    ),
)


def validate_candidate(
    root: str | Path,
    spec_lock: Mapping[str, Any] | None = None,
    *,
    expected_target_root: str | Path | None = None,
    require_internal_report: bool = True,
) -> dict[str, Any]:
    """Validate a candidate without observing its execution root."""

    candidate = Path(root).expanduser().resolve()
    before = legacy._tree_snapshot(candidate) if candidate.is_dir() else {}
    checks: list[dict[str, Any]] = []
    for check_id, function in CHECKS:
        try:
            findings = function(candidate)
        except Exception as exc:
            findings = [
                {"code": "VALIDATOR_CHECK_ERROR", "message": str(exc)}
            ]
        checks.append(
            {
                "check_id": check_id,
                "status": "FAIL" if findings else "PASS",
                "findings": findings,
            }
        )

    try:
        handoff_findings = legacy._check_handoff(
            candidate, require_internal_report=require_internal_report
        )
    except Exception as exc:
        handoff_findings = [
            {"code": "VALIDATOR_CHECK_ERROR", "message": str(exc)}
        ]
    checks.append(
        {
            "check_id": "VALIDATION_HANDOFF_AND_NONCLAIMS",
            "status": "FAIL" if handoff_findings else "PASS",
            "findings": handoff_findings,
        }
    )

    logical_root = Path(expected_target_root or candidate).expanduser().resolve()
    binding_findings: list[dict[str, Any]] = []
    context = legacy._read_json(
        candidate / "START_CONTEXT.json", binding_findings
    )
    if isinstance(context, dict) and context.get("target_root") != str(
        logical_root
    ):
        binding_findings.append(
            _finding(
                "TARGET_ROOT_MISMATCH",
                f"expected {logical_root}, got {context.get('target_root')}",
            )
        )
    checks.append(
        {
            "check_id": "LOGICAL_TARGET_ROOT_BINDING",
            "status": "FAIL" if binding_findings else "PASS",
            "findings": binding_findings,
        }
    )

    after = legacy._tree_snapshot(candidate) if candidate.is_dir() else {}
    read_only_findings = (
        []
        if before == after
        else [
            _finding(
                "VALIDATOR_SIDE_EFFECT",
                "candidate tree changed during validation",
            )
        ]
    )
    checks.append(
        {
            "check_id": "VALIDATOR_READ_ONLY",
            "status": "FAIL" if read_only_findings else "PASS",
            "findings": read_only_findings,
        }
    )

    provenance_findings: list[dict[str, Any]] = []
    provenance = legacy._read_json(
        candidate / "FACTORY_PROVENANCE.json", provenance_findings
    )
    if isinstance(provenance, dict):
        spec_hash = str(provenance.get("spec_content_sha256", ""))
        requirement_hash = str(provenance.get("requirement_ir_sha256", ""))
        if (
            provenance.get("factory_id")
            != "HARNESS_FOUNDRY_V2_8_CHAT_FACTORY_V0_2"
            or not SHA256_RE.fullmatch(spec_hash)
            or len(set(spec_hash)) == 1
            or provenance.get("execution_started") is not False
            or not SHA256_RE.fullmatch(requirement_hash)
            or len(set(requirement_hash)) == 1
        ):
            provenance_findings.append(
                _finding(
                    "FACTORY_PROVENANCE_INVALID", "FACTORY_PROVENANCE.json"
                )
            )
        if isinstance(spec_lock, Mapping) and (
            spec_hash != spec_lock.get("content_sha256")
            or provenance.get("spec_file_count") != spec_lock.get("file_count")
        ):
            provenance_findings.append(
                _finding(
                    "SPEC_LOCK_BINDING_MISMATCH", "FACTORY_PROVENANCE.json"
                )
            )
        frozen_ir = legacy._read_json(
            candidate / "canonical_sources/FROZEN_REQUIREMENT_IR.json",
            provenance_findings,
        )
        internal_report = legacy._read_json(
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
            or legacy._json_hash(frozen_ir) != requirement_hash
            or provenance.get("program_id") != frozen_ir.get("program_id")
            or not isinstance(internal_report, dict)
            or internal_report.get("requirement_ir_sha256") != requirement_hash
            or requirement_hash not in handoff_text
        ):
            provenance_findings.append(
                _finding(
                    "REQUIREMENT_IR_PROVENANCE_MISMATCH",
                    "frozen IR/provenance/report/handoff",
                )
            )
    checks.append(
        {
            "check_id": "SPEC_LOCK_AND_FACTORY_PROVENANCE",
            "status": "FAIL" if provenance_findings else "PASS",
            "findings": provenance_findings,
        }
    )

    valid = all(item["status"] == "PASS" for item in checks)
    blocking = [
        finding for item in checks for finding in item.get("findings", [])
    ]
    return {
        "schema_version": "2.0",
        "validator_id": "HARNESS_FOUNDRY_V2_8_STATIC_CANDIDATE_VALIDATOR",
        "candidate_root": str(candidate),
        "logical_target_root": str(logical_root),
        "status": "PASS" if valid else "FAIL",
        "valid": valid,
        "checks": checks,
        "blocking_findings": blocking,
        "permitted_terminal_state": TARGET_CANDIDATE_STATE,
        "writes_performed": False,
        "commands_executed": False,
        "execution_root_observed": False,
        "runtime_claims_verified": False,
    }


def export_execution_handoff(
    root: str | Path,
    spec_lock: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    candidate = Path(root).expanduser().resolve()
    validation = validate_candidate(candidate, spec_lock)
    if validation["status"] != "PASS":
        return {
            "schema_version": "1.0",
            "status": "FAIL",
            "candidate_root": str(candidate),
            "validation": validation,
            "writes_performed": False,
        }
    findings: list[dict[str, Any]] = []
    context = legacy._read_json(candidate / "START_CONTEXT.json", findings)
    provenance = legacy._read_json(
        candidate / "FACTORY_PROVENANCE.json", findings
    )
    policy = legacy._read_json(
        candidate / "PROGRAM_AUTOMATION_POLICY.json", findings
    )
    charter_hash = legacy._file_hash(candidate / "PROGRAM_CHARTER.md")
    profile_hash = legacy._file_hash(candidate / "PROFILE_LOCK.json")
    program_id = provenance.get("program_id")
    if not isinstance(program_id, str) or not program_id:
        findings.append(
            _finding(
                "HANDOFF_PROGRAM_ID_MISSING",
                "FACTORY_PROVENANCE.json",
            )
        )
    for name in (
        "PROGRAM_STATE.json",
        "PROGRAM_DRIVER_STATE.json",
        "ENGINEERING_PROJECT_DAG.json",
        "EXECUTION_AUTHORIZATION.json",
    ):
        document = legacy._read_json(candidate / name, findings)
        if (
            isinstance(document, dict)
            and document.get("program_id") != program_id
        ):
            findings.append(
                _finding("HANDOFF_PROGRAM_ID_MISMATCH", name)
            )
    context_program_id = context.get("program_id")
    if (
        context_program_id is not None
        and context_program_id != program_id
    ):
        findings.append(
            _finding(
                "HANDOFF_PROGRAM_ID_MISMATCH",
                "START_CONTEXT.json",
            )
        )
    if findings:
        return {
            "schema_version": "1.0",
            "status": "FAIL",
            "candidate_root": str(candidate),
            "blocking_findings": findings,
            "writes_performed": False,
            "commands_executed": False,
        }
    body = {
        "schema_version": "1.0",
        "handoff_kind": "HF28_STATIC_CANDIDATE_TO_CONTROLLED_RUNTIME",
        "program_id": program_id,
        "candidate_root": str(candidate),
        "execution_root": context.get("execution_root"),
        "candidate_content_sha256": legacy._candidate_tree_hash(candidate),
        "requirement_ir_sha256": provenance.get("requirement_ir_sha256"),
        "spec_content_sha256": provenance.get("spec_content_sha256"),
        "charter_sha256": charter_hash,
        "profile_lock_sha256": profile_hash,
        "automation_profile": policy.get("automation_profile"),
        "authoring_terminal_state": TARGET_CANDIDATE_STATE,
        "next_runtime_action": "BOOTSTRAP_PLAN",
        "execution_authorization_inherited": False,
        "real_target_install_authorization_inherited": False,
    }
    handoff_sha256 = hashlib.sha256(
        json.dumps(
            body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        **body,
        "handoff_sha256": handoff_sha256,
        "status": "PASS",
        "writes_performed": False,
        "commands_executed": False,
    }


def validate_handoff(
    root: str | Path,
    spec_lock: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    handoff = export_execution_handoff(root, spec_lock)
    return {
        "schema_version": "1.0",
        "validator_id": "HF28_EXECUTION_HANDOFF_VALIDATOR",
        "status": handoff.get("status"),
        "handoff": handoff if handoff.get("status") == "PASS" else None,
        "blocking_findings": (
            []
            if handoff.get("status") == "PASS"
            else handoff.get(
                "blocking_findings",
                handoff.get("validation", {}).get(
                    "blocking_findings", []
                ),
            )
        ),
        "writes_performed": False,
        "commands_executed": False,
    }


_candidate_tree_hash = legacy._candidate_tree_hash
