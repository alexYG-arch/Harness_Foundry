#!/usr/bin/env python3
"""Read-only validator for the Harness Foundry v2.8 documentation package."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote


AUTOMATION_TEMPLATE_KEYS = {
    "THREE_PROJECT_PROGRAM_MANIFEST.template.json": (
        "schema_version", "manifest_id", "program_id", "projects",
        "construction_sequence", "automatic_progress",
    ),
    "ENGINEERING_PROJECT_DAG.template.json": (
        "schema_version", "dag_id", "nodes", "edges", "forbidden_progressions",
        "evidence_requirements",
    ),
    "RELEASE_PIPELINE_MANIFEST.template.json": (
        "schema_version", "pipeline_id", "steps", "ordering_invariants", "failure_behavior",
    ),
    "PROGRAM_DRIVER_CONTRACT.template.json": (
        "schema_version", "contract_id", "driver_role", "required_inputs", "commands",
        "decision_algorithm", "safety_invariants", "hard_stop_states",
    ),
    "PROGRAM_DRIVER_STATE.template.json": (
        "schema_version", "state_id", "driver_status", "controlled_auto_advance_enabled",
        "active_execution_authorization_ref", "next_eligible_transition",
    ),
    "PROGRAM_AUTOMATION_POLICY.template.json": (
        "schema_version", "policy_id", "default_mode", "automatic_progress_default",
        "activation_requirements", "mode_policy", "controlled_auto_advance",
        "generic_authorization_exclusions",
    ),
    "AUTHORIZATION_POLICY.template.json": (
        "schema_version", "policy_id", "default_disposition", "authorization_classes",
        "required_token_fields", "validation_rules", "real_target_install_rules",
    ),
    "EXECUTION_AUTHORIZATION.template.json": (
        "schema_version", "authorization_id", "authorization_class", "status", "scope",
        "command_manifest_hashes", "max_transitions", "may_auto_advance",
        "real_target_install_allowed", "signature",
    ),
    "REAL_TARGET_INSTALL_AUTHORIZATION.template.json": (
        "schema_version", "authorization_id", "authorization_class", "status", "bindings",
        "approved_command_ids", "approved_command_manifest_hashes",
        "may_be_generated_or_self_granted_by_driver",
        "may_be_substituted_by_generic_execution_authorization", "signature",
    ),
    "LOOP_POLICY.template.json": (
        "schema_version", "policy_id", "automatic_loops_default", "authorization_required",
        "loop_types", "mandatory_stop_conditions", "convergence_rules",
        "forbidden_loop_behavior",
    ),
    "LOOP_STATE.template.json": (
        "schema_version", "loop_id", "status", "authorization_ref", "current_iteration",
        "max_iterations", "same_finding_repeat_count", "oscillation_repeat_count",
        "stop_reason", "promotion_eligible",
    ),
    "WORKPACK_RESULT.template.json": (
        "schema_version", "result_id", "workpack_id", "status", "authorization_ref",
        "command_results", "acceptance_checks", "postflight_status",
        "result_validation_status", "promotion_eligible", "promotion_status",
    ),
    "FINDING_SCHEMA.template.json": (
        "schema_version", "schema_id", "record_type", "finding", "invariants",
    ),
    "REPAIR_ROUTING_RULES.template.json": (
        "schema_version", "ruleset_id", "default_disposition", "single_repair_owner_required",
        "rules", "routing_algorithm", "forbidden_routing",
    ),
    "INVALIDATION_DAG.template.json": (
        "schema_version", "dag_id", "nodes", "edges", "triggers", "propagation_policy",
    ),
    "REENTRY_PLAN.template.json": (
        "schema_version", "plan_id", "status", "finding_ids", "repair_owner",
        "invalidation_event_refs", "earliest_required_reentry_gate", "steps",
        "authorization_ref", "completion_requires",
    ),
}

PROJECT_TEMPLATE_NAMES = (
    "README.md",
    "PROJECT_CHARTER.template.md",
    "PROJECT_STATE.template.json",
    "WORKPACK_INDEX.template.json",
    "COMMAND_MANIFEST.template.json",
    "BUILD_INSTALL_PLAN.template.md",
)
PROJECT_DIRS = ("main_build", "external_lab", "linkage_review")
RELEASE_STEP_ORDER = [
    "P4_LOCAL_CLOSURE",
    "P4_BUILD_INPUT_LOCK",
    "PACK_DRAFT",
    "LINKAGE_A",
    "LINKAGE_B0",
    "LINKAGE_C",
    "PACKAGE_BUILD",
    "LINKAGE_B1",
    "P4_INSTALLABILITY",
    "P4_RELEASE_CANDIDATE_LOCK",
    "CERTIFICATION_INSTALL",
    "LINKAGE_D",
    "LAB_C4",
    "CONFORMANCE_CERTIFICATE",
    "P4_CERTIFIED_RELEASE_LOCK",
    "WAIT_REAL_TARGET_INSTALL_AUTHORIZATION",
    "REAL_TARGET_INSTALL",
]
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _format_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _without_fenced_blocks(text: str) -> str:
    kept: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        match = FENCE_RE.match(line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            kept.append("")
        elif fence is None:
            kept.append(line)
        else:
            kept.append("")
    return "\n".join(kept)


def _relative_link_target(raw_target: str) -> str | None:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    elif " " in target:
        target = target.split(" ", 1)[0]
    target = unquote(target).split("#", 1)[0].split("?", 1)[0]
    if not target or target.startswith(("#", "/")):
        return None
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
        return None
    if "<" in target or ">" in target:
        return None
    return target


def _iter_markdown_links(path: Path) -> Iterable[str]:
    text = _without_fenced_blocks(path.read_text(encoding="utf-8"))
    for match in LINK_RE.finditer(text):
        target = _relative_link_target(match.group(1))
        if target is not None:
            yield target


def _check_json(root: Path) -> list[str]:
    errors: list[str] = []
    for path in sorted(root.rglob("*.json")):
        try:
            _read_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"{_format_path(path, root)}: {exc}")
    for path in sorted(root.rglob("*.jsonl")):
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    try:
                        json.loads(line)
                    except json.JSONDecodeError as exc:
                        errors.append(
                            f"{_format_path(path, root)}:{line_number}: {exc.msg}"
                        )
        except (OSError, UnicodeError) as exc:
            errors.append(f"{_format_path(path, root)}: {exc}")
    return errors


def _check_markdown_links(root: Path) -> list[str]:
    errors: list[str] = []
    for path in sorted(root.rglob("*.md")):
        try:
            targets = _iter_markdown_links(path)
            for target in targets:
                resolved = (path.parent / target).resolve()
                if not resolved.exists():
                    errors.append(
                        f"{_format_path(path, root)}: missing relative target {target}"
                    )
        except (OSError, UnicodeError) as exc:
            errors.append(f"{_format_path(path, root)}: {exc}")
    return errors


def _check_identity(root: Path) -> list[str]:
    errors: list[str] = []
    manifest_path = root / "PACKAGE_MANIFEST.json"
    if not manifest_path.is_file():
        return ["PACKAGE_MANIFEST.json is missing"]
    try:
        manifest = _read_json(manifest_path)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ["PACKAGE_MANIFEST.json cannot be inspected because it is invalid"]
    if manifest.get("version") != "2.8.0":
        errors.append("PACKAGE_MANIFEST.json version must be 2.8.0")
    if "V2_8" not in str(manifest.get("package_id", "")):
        errors.append("PACKAGE_MANIFEST.json package_id must identify V2_8")
    for entrypoint in ("README.md", "START_HERE.md"):
        path = root / entrypoint
        if not path.is_file():
            errors.append(f"{entrypoint} is missing")
        elif "2.8" not in path.read_text(encoding="utf-8"):
            errors.append(f"{entrypoint} does not identify version 2.8")
    return errors


def _check_automation_templates(root: Path) -> list[str]:
    errors: list[str] = []
    template_root = root / "templates" / "target_start_package"
    for name, required_keys in AUTOMATION_TEMPLATE_KEYS.items():
        path = template_root / name
        if not path.is_file():
            errors.append(f"templates/target_start_package/{name} is missing")
            continue
        try:
            data = _read_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            errors.append(f"{name} must contain a JSON object")
            continue
        missing = [key for key in required_keys if key not in data]
        if missing:
            errors.append(f"{name} missing keys: {', '.join(missing)}")
        if str(data.get("schema_version", "")) != "2.8":
            errors.append(f"{name} schema_version must be 2.8")

        if name == "THREE_PROJECT_PROGRAM_MANIFEST.template.json":
            projects = data.get("projects", [])
            project_ids = [project.get("project_id") for project in projects if isinstance(project, dict)]
            expected_ids = [
                "EXTERNAL_CONFORMANCE_LAB",
                "CONFORMANCE_LINKAGE_REVIEW",
                "MAIN_HARNESS_BUILD",
            ]
            if project_ids != expected_ids:
                errors.append(f"{name} must declare the three engineering projects in construction order")
            orders = [project.get("construction_order") for project in projects if isinstance(project, dict)]
            if orders != [1, 2, 3]:
                errors.append(f"{name} construction_order must be 1, 2, 3")
            if data.get("automatic_progress", {}).get("enabled") is not False:
                errors.append(f"{name} automatic progress must default to false")

        if name == "RELEASE_PIPELINE_MANIFEST.template.json":
            steps = data.get("steps", [])
            orders = [step.get("order") for step in steps if isinstance(step, dict)]
            if orders != list(range(1, len(steps) + 1)) or not steps:
                errors.append(f"{name} steps must have a complete contiguous order")
            step_ids = [step.get("step_id") for step in steps if isinstance(step, dict)]
            if step_ids != RELEASE_STEP_ORDER:
                errors.append(f"{name} must contain the complete ordered release step chain")
            install = next(
                (step for step in steps if step.get("step_id") == "REAL_TARGET_INSTALL"),
                None,
            )
            if install is None or install.get("auto_advance_eligible") is not False:
                errors.append(f"{name} REAL_TARGET_INSTALL must not be auto-advance eligible")
            elif "REAL_TARGET_INSTALL_AUTHORIZATION_GRANTED" not in install.get("requires", []):
                errors.append(f"{name} REAL_TARGET_INSTALL must require separate authorization")

        if name == "PROGRAM_DRIVER_CONTRACT.template.json":
            invariants = data.get("safety_invariants", {})
            if invariants.get("no_phase_skip") is not True:
                errors.append(f"{name} must prohibit phase skipping")
            if invariants.get("real_target_install_never_covered_by_generic_authorization") is not True:
                errors.append(f"{name} must exclude real install from generic authorization")

        if name == "LOOP_POLICY.template.json":
            if data.get("automatic_loops_default") is not False:
                errors.append(f"{name} automatic loops must default to false")
            if data.get("authorization_required") is not True:
                errors.append(f"{name} must require loop authorization")

    for optional_ledger in ("PROMOTION_LEDGER.template.jsonl", "REVOCATION_LEDGER.template.jsonl"):
        path = template_root / optional_ledger
        if path.exists() and not path.is_file():
            errors.append(f"templates/target_start_package/{optional_ledger} is not a file")
        elif path.is_file():
            try:
                records = [
                    json.loads(line)
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if not records:
                errors.append(f"{optional_ledger} must contain an initialization event")
                continue
            first = records[0]
            ledger_keys = {
                "schema_version", "event_id", "sequence", "previous_event_hash",
                "event_type", "program_id", "authorization_ref", "actor_role",
                "timestamp", "event_hash",
            }
            missing = sorted(ledger_keys.difference(first))
            if missing:
                errors.append(f"{optional_ledger} missing keys: {', '.join(missing)}")
            if first.get("schema_version") != "2.8":
                errors.append(f"{optional_ledger} schema_version must be 2.8")
    return errors


def _check_project_templates(root: Path) -> list[str]:
    errors: list[str] = []
    project_root = root / "templates" / "project_start_packages"
    expected_roles = {
        "main_build": "MAIN_BUILD_PROJECT",
        "external_lab": "EXTERNAL_CONFORMANCE_LAB",
        "linkage_review": "READ_ONLY_LINKAGE_REVIEW",
    }
    for directory in PROJECT_DIRS:
        base = project_root / directory
        for name in PROJECT_TEMPLATE_NAMES:
            if not (base / name).is_file():
                errors.append(
                    f"templates/project_start_packages/{directory}/{name} is missing"
                )
        state_path = base / "PROJECT_STATE.template.json"
        if state_path.is_file():
            try:
                state = _read_json(state_path)
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if state.get("schema_version") != "2.8":
                errors.append(f"{directory} PROJECT_STATE schema_version must be 2.8")
            if state.get("project_role") != expected_roles[directory]:
                errors.append(f"{directory} PROJECT_STATE has the wrong project_role")
    return errors


def _check_control_state_and_roles(root: Path) -> list[str]:
    errors: list[str] = []
    template_root = root / "templates/target_start_package"
    state_path = template_root / "PROGRAM_STATE.template.json"
    required_state_keys = {
        "current_phase",
        "next_eligible_phase",
        "valid_locks",
        "invalidated_locks",
        "blockers",
    }
    try:
        state = _read_json(state_path)
        missing = sorted(required_state_keys.difference(state))
        if missing:
            errors.append(f"PROGRAM_STATE missing keys: {', '.join(missing)}")
        if state.get("schema_version") != "2.8":
            errors.append("PROGRAM_STATE schema_version must be 2.8")
    except FileNotFoundError:
        errors.append("PROGRAM_STATE.template.json is missing")
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass

    roles_path = template_root / "PACKAGE_ROLES.template.json"
    required_roles = {
        "build_program_driver",
        "trusted_runner",
        "certification_installer",
        "human_gate_owner",
    }
    try:
        package_roles = _read_json(roles_path)
        roles = package_roles.get("roles", {})
        missing = sorted(required_roles.difference(roles)) if isinstance(roles, dict) else sorted(required_roles)
        if missing:
            errors.append(f"PACKAGE_ROLES missing control roles: {', '.join(missing)}")
        if package_roles.get("schema_version") != "2.8":
            errors.append("PACKAGE_ROLES schema_version must be 2.8")
    except FileNotFoundError:
        errors.append("PACKAGE_ROLES.template.json is missing")
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    return errors


def _check_authoring_defaults(root: Path) -> list[str]:
    errors: list[str] = []
    context_path = root / "templates/target_start_package/START_CONTEXT.template.json"
    try:
        context = _read_json(context_path)
        if context.get("execution_mode") != "AUTHORING_ONLY":
            errors.append("START_CONTEXT execution_mode must default to AUTHORING_ONLY")
        if context.get("auto_start_generated_workpacks") is not False:
            errors.append("START_CONTEXT auto_start_generated_workpacks must be false")
    except FileNotFoundError:
        errors.append("START_CONTEXT.template.json is missing")
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass

    driver_state_path = root / "templates/target_start_package/PROGRAM_DRIVER_STATE.template.json"
    if driver_state_path.is_file():
        try:
            driver_state = _read_json(driver_state_path)
            if driver_state.get("controlled_auto_advance_enabled") is not False:
                errors.append(
                    "PROGRAM_DRIVER_STATE controlled_auto_advance_enabled must default to false"
                )
            if driver_state.get("driver_started") is not False:
                errors.append("PROGRAM_DRIVER_STATE driver_started must default to false")
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass

    policy_path = root / "templates/target_start_package/PROGRAM_AUTOMATION_POLICY.template.json"
    if policy_path.is_file():
        try:
            policy = _read_json(policy_path)
            if policy.get("default_mode") != "AUTHORING_ONLY":
                errors.append("PROGRAM_AUTOMATION_POLICY must default to AUTHORING_ONLY")
            if policy.get("automatic_progress_default") is not False:
                errors.append("PROGRAM_AUTOMATION_POLICY automatic progress must default to false")
            if policy.get("authoring_may_start_driver") is not False:
                errors.append("PROGRAM_AUTOMATION_POLICY must not start the Driver from authoring")
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass

    execution_auth_path = root / "templates/target_start_package/EXECUTION_AUTHORIZATION.template.json"
    if execution_auth_path.is_file():
        try:
            authorization = _read_json(execution_auth_path)
            if authorization.get("status") == "GRANTED":
                errors.append("EXECUTION_AUTHORIZATION must not ship granted")
            if authorization.get("may_auto_advance") is not False:
                errors.append("EXECUTION_AUTHORIZATION may_auto_advance must default to false")
            if authorization.get("max_transitions") != 0:
                errors.append("EXECUTION_AUTHORIZATION transition budget must default to zero")
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass

    for directory in PROJECT_DIRS:
        base = root / "templates/project_start_packages" / directory
        state_path = base / "PROJECT_STATE.template.json"
        index_path = base / "WORKPACK_INDEX.template.json"
        try:
            state = _read_json(state_path)
            if state.get("auto_advance_enabled") is not False:
                errors.append(f"{directory} auto_advance_enabled must default to false")
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
        try:
            index = _read_json(index_path)
            if index.get("auto_start_next_workpack") is not False:
                errors.append(f"{directory} auto_start_next_workpack must default to false")
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    return errors


def _check_real_target_authorization(root: Path) -> list[str]:
    errors: list[str] = []
    template_root = root / "templates/target_start_package"
    dedicated = template_root / "REAL_TARGET_INSTALL_AUTHORIZATION.template.json"
    if not dedicated.is_file():
        errors.append("REAL_TARGET_INSTALL_AUTHORIZATION template is missing")
    else:
        try:
            install_authorization = _read_json(dedicated)
            if install_authorization.get("authorization_class") != "REAL_TARGET_INSTALL_AUTHORIZATION":
                errors.append("Real target install must use its dedicated authorization class")
            if install_authorization.get("status") == "GRANTED":
                errors.append("Real target install authorization must not ship granted")
            if install_authorization.get("may_be_generated_or_self_granted_by_driver") is not False:
                errors.append("Driver must not generate or self-grant real target install authorization")
            if install_authorization.get(
                "may_be_substituted_by_generic_execution_authorization"
            ) is not False:
                errors.append("Generic execution authorization must not substitute for real install")
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass

    auth_policy_path = template_root / "AUTHORIZATION_POLICY.template.json"
    if auth_policy_path.is_file():
        try:
            auth_policy = _read_json(auth_policy_path)
            rules = auth_policy.get("real_target_install_rules", {})
            if auth_policy.get("default_disposition") != "DENY":
                errors.append("Authorization policy must default to DENY")
            if rules.get("separate_token_type_required") is not True:
                errors.append("Authorization policy must require a separate real install token")
            if rules.get("may_not_be_included_in_execution_authorization") is not True:
                errors.append("Real install must be excluded from execution authorization")
            if rules.get("human_signature_required") is not True:
                errors.append("Real install authorization must require a human signature")
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass

    execution_auth_path = template_root / "EXECUTION_AUTHORIZATION.template.json"
    if execution_auth_path.is_file():
        try:
            execution_auth = _read_json(execution_auth_path)
            if execution_auth.get("real_target_install_allowed") is not False:
                errors.append("Generic execution authorization must deny real target install")
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass

    lock_path = template_root / "CERTIFIED_RELEASE_LOCK.template.json"
    try:
        lock = _read_json(lock_path)
        if "real_target_install_authorization_ref" not in lock:
            errors.append("CERTIFIED_RELEASE_LOCK lacks real_target_install_authorization_ref")
        elif lock["real_target_install_authorization_ref"] is not None:
            errors.append("Certified Release must not pre-authorize real target installation")
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass

    main_state_path = root / "templates/project_start_packages/main_build/PROJECT_STATE.template.json"
    try:
        main_state = _read_json(main_state_path)
        install = main_state.get("real_target_install", {})
        if install.get("separate_authorization_required") is not True:
            errors.append("Main Build must require separate real target install authorization")
        if install.get("authorization_ref") is not None:
            errors.append("Main Build must not ship with real target install authorization")
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass

    for path in sorted(root.glob("templates/project_start_packages/*/COMMAND_MANIFEST.template.json")):
        try:
            manifest = _read_json(path)
            if manifest.get("real_target_install_command_present") is not False:
                errors.append(
                    f"{_format_path(path, root)} must not contain a real target install command"
                )
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    return errors


def _check_command_manifests(root: Path) -> list[str]:
    errors: list[str] = []
    paths = sorted(root.rglob("COMMAND_MANIFEST.template.json"))
    if not paths:
        return ["No COMMAND_MANIFEST.template.json files found"]
    for path in paths:
        try:
            manifest = _read_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        commands = manifest.get("commands")
        if "auto_execute" in manifest and manifest.get("auto_execute") is not False:
            errors.append(f"{_format_path(path, root)} auto_execute must default to false")
        if not isinstance(commands, list) or not commands:
            errors.append(f"{_format_path(path, root)} commands must be a non-empty list")
            continue
        for index, command in enumerate(commands):
            if not isinstance(command, dict):
                errors.append(f"{_format_path(path, root)} command {index} must be an object")
                continue
            executable = command.get("executable_abs", command.get("executable"))
            if not isinstance(executable, str) or not executable.startswith("/"):
                errors.append(
                    f"{_format_path(path, root)} command {index} executable must be absolute"
                )
            authorization = command.get("authorization_ref")
            if not isinstance(authorization, str) or not authorization.strip():
                errors.append(
                    f"{_format_path(path, root)} command {index} authorization_ref is required"
                )
            expected_exit_codes = command.get("expected_exit_codes")
            if (
                not isinstance(expected_exit_codes, list)
                or not expected_exit_codes
                or any(not isinstance(code, int) for code in expected_exit_codes)
            ):
                errors.append(
                    f"{_format_path(path, root)} command {index} expected_exit_codes is required"
                )
            combined_evidence = (
                command.get("stdout_stderr_exit_code_required") is True
                or command.get("stdout_stderr_evidence_required") is True
            )
            separate_evidence = (
                command.get("stdout_evidence_required") is True
                and command.get("stderr_evidence_required") is True
            )
            if not combined_evidence and not separate_evidence:
                errors.append(
                    f"{_format_path(path, root)} command {index} must require stdout/stderr evidence"
                )
    return errors


def _p4_requires_p3(index: dict[str, Any]) -> bool:
    for workpack in index.get("workpacks", []):
        if workpack.get("phase") == "P4" or workpack.get("workpack_id") == "MB-P4":
            return any("P3" in str(item) for item in workpack.get("requires", []))
    return False


def _check_p3_not_skippable(root: Path) -> list[str]:
    errors: list[str] = []
    phase_path = root / "templates/target_start_package/PHASE_DEPENDENCY_MANIFEST.template.json"
    try:
        phase = _read_json(phase_path)
        p4_transition = next(
            (item for item in phase.get("transitions", []) if item.get("to") == "P4_READY"),
            None,
        )
        if p4_transition is None or not any(
            "P3" in str(item) for item in p4_transition.get("requires", [])
        ):
            errors.append("P4_READY must require a P3 Lock or approved P3 N/A Lock")
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass

    main_index_path = root / "templates/project_start_packages/main_build/WORKPACK_INDEX.template.json"
    try:
        main_index = _read_json(main_index_path)
        if not _p4_requires_p3(main_index):
            errors.append("Main Build P4 Workpack must require P3 evidence")
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass

    release_path = root / "templates/target_start_package/RELEASE_PIPELINE_MANIFEST.template.json"
    try:
        release = _read_json(release_path)
        p4_local = next(
            (item for item in release.get("steps", []) if item.get("step_id") == "P4_LOCAL_CLOSURE"),
            None,
        )
        if p4_local is None or not any(
            "P3" in str(item) for item in p4_local.get("requires", [])
        ):
            errors.append("Release P4 local closure must require P3 evidence")
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    return errors


CHECKS = (
    ("JSON_AND_JSONL_PARSE", _check_json),
    ("MARKDOWN_RELATIVE_LINKS", _check_markdown_links),
    ("PACKAGE_IDENTITY_V2_8", _check_identity),
    ("AUTOMATION_TEMPLATES", _check_automation_templates),
    ("PROJECT_START_PACKAGES", _check_project_templates),
    ("CONTROL_STATE_AND_ROLES", _check_control_state_and_roles),
    ("AUTHORING_DEFAULT_DISABLED", _check_authoring_defaults),
    ("REAL_TARGET_INSTALL_SEPARATE_AUTHORIZATION", _check_real_target_authorization),
    ("COMMAND_ABSOLUTE_EXECUTABLE_AND_AUTHORIZATION", _check_command_manifests),
    ("P3_NOT_SKIPPABLE", _check_p3_not_skippable),
)


def validate_package(root: Path) -> dict[str, Any]:
    root = root.resolve()
    checks: list[dict[str, Any]] = []
    for check_id, check in CHECKS:
        errors = check(root)
        item: dict[str, Any] = {
            "check_id": check_id,
            "status": "FAIL" if errors else "PASS",
        }
        if errors:
            item["errors"] = errors
        checks.append(item)
    status = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    return {
        "schema_version": "1.0",
        "validator_id": "HARNESS_FOUNDRY_V2_8_PACKAGE_VALIDATOR",
        "package_root": str(root),
        "status": status,
        "checks": checks,
        "metrics": {
            "files": sum(1 for path in root.rglob("*") if path.is_file()),
            "markdown_files": sum(1 for _ in root.rglob("*.md")),
            "json_files": sum(1 for _ in root.rglob("*.json")),
            "jsonl_files": sum(1 for _ in root.rglob("*.jsonl")),
        },
        "writes_performed": False,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "package_root",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Harness Foundry v2.8 package root (defaults to this script's package)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="emit the complete result as JSON on stdout",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.package_root.is_dir():
        result = {
            "schema_version": "1.0",
            "validator_id": "HARNESS_FOUNDRY_V2_8_PACKAGE_VALIDATOR",
            "package_root": str(args.package_root.resolve()),
            "status": "FAIL",
            "checks": [
                {
                    "check_id": "PACKAGE_ROOT_EXISTS",
                    "status": "FAIL",
                    "errors": ["package root is not a directory"],
                }
            ],
            "writes_performed": False,
        }
    else:
        result = validate_package(args.package_root)
    if args.json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Harness Foundry v2.8 validation: {result['status']}")
        for check in result["checks"]:
            print(f"- {check['check_id']}: {check['status']}")
            for error in check.get("errors", []):
                print(f"  {error}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
