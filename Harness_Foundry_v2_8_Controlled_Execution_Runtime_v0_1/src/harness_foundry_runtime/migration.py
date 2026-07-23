"""Read-only legacy analysis and new-epoch migration materialization."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
from typing import Any, Mapping
import uuid

from .engine import RUNTIME_VERSION, RuntimeViolation, _load_control_plan
from .store import RuntimeStore
from .util import (
    file_sha256,
    json_sha256,
    lexical_path,
    read_json,
    tree_sha256,
    utc_now,
)


def migration_plan(
    legacy_candidate_root: str | Path,
    legacy_execution_root: str | Path,
    new_execution_root: str | Path,
    *,
    copy_history_snapshot: bool = False,
) -> dict[str, Any]:
    candidate = Path(legacy_candidate_root).expanduser().resolve()
    legacy = Path(legacy_execution_root).expanduser().resolve()
    target = lexical_path(new_execution_root)
    findings: list[dict[str, str]] = []
    if not candidate.is_dir():
        findings.append(
            {"code": "LEGACY_CANDIDATE_MISSING", "message": str(candidate)}
        )
    if not legacy.is_dir():
        findings.append(
            {"code": "LEGACY_EXECUTION_ROOT_MISSING", "message": str(legacy)}
        )
    if target.exists() and any(target.iterdir()):
        findings.append(
            {"code": "NEW_EXECUTION_ROOT_NOT_EMPTY", "message": str(target)}
        )
    if findings:
        return {
            "schema_version": "1.0",
            "status": "FAIL",
            "blocking_findings": findings,
            "writes_performed": False,
        }
    candidate_hash = tree_sha256(candidate)
    legacy_hash = tree_sha256(legacy)
    legacy_state_path = legacy / "control_plane/state/CONTROL_STATE.json"
    legacy_state: dict[str, Any] = {}
    if legacy_state_path.is_file():
        try:
            legacy_state = read_json(legacy_state_path)
        except (OSError, ValueError, json.JSONDecodeError):
            findings.append(
                {
                    "code": "LEGACY_CONTROL_STATE_UNTRUSTED",
                    "message": str(legacy_state_path),
                }
            )
    candidate_context_path = candidate / "START_CONTEXT.json"
    candidate_context = (
        read_json(candidate_context_path)
        if candidate_context_path.is_file()
        else {}
    )
    plan = _load_control_plan(candidate)
    legacy_completed = set(legacy_state.get("completed_nodes", []))
    classifications = []
    for node in plan["nodes"]:
        node_id = node["node_id"]
        evidence = legacy / "evidence/engineering_dag" / f"{node_id}.result.json"
        if evidence.is_file():
            try:
                document = read_json(evidence)
                status = str(
                    document.get("status")
                    or document.get("result_status")
                    or document.get("gate_status")
                    or ""
                ).upper()
                classification = (
                    "VERIFIED_COMPLETED"
                    if status in {"PASS", "VERIFIED", "COMPLETED"}
                    and node_id in legacy_completed
                    else "REVERIFY_REQUIRED"
                )
                evidence_hash = file_sha256(evidence)
            except (OSError, ValueError, json.JSONDecodeError):
                classification = "UNTRUSTED"
                evidence_hash = None
        elif node_id in legacy_completed:
            classification = "REVERIFY_REQUIRED"
            evidence_hash = None
        else:
            classification = "NOT_STARTED"
            evidence_hash = None
        classifications.append(
            {
                "node_id": node_id,
                "classification": classification,
                "legacy_evidence_ref": (
                    str(evidence) if evidence.is_file() else None
                ),
                "legacy_evidence_sha256": evidence_hash,
                "restores_pass_automatically": False,
            }
        )
    source = {
        "legacy_candidate_root": str(candidate),
        "legacy_candidate_tree_sha256": candidate_hash,
        "legacy_execution_root": str(legacy),
        "legacy_execution_tree_sha256": legacy_hash,
        "legacy_control_state_sha256": (
            file_sha256(legacy_state_path)
            if legacy_state_path.is_file()
            else None
        ),
    }
    body = {
        "schema_version": "1.0",
        "migration_id": (
            f"MIGRATION-{json_sha256({'source': source, 'target': str(target)})[:24].upper()}"
        ),
        "program_id": (
            legacy_state.get("program_id")
            or candidate_context.get("program_id")
            or f"PROGRAM-{candidate_context.get('target_id')}"
        ),
        "source": source,
        "new_execution_root": str(target),
        "node_classifications": classifications,
        "copy_history_snapshot": copy_history_snapshot,
        "legacy_authorizations_imported": False,
        "execution_authorization_created": False,
        "completed_nodes_restored": [],
        "next_gate": "MIGRATION_BOOTSTRAP_REVERIFICATION_REQUIRED",
        "created_at": utc_now(),
    }
    plan_hash = json_sha256(body)
    return {
        **body,
        "migration_plan_sha256": plan_hash,
        "confirmation_text": (
            f"APPLY_READ_ONLY_MIGRATION::{body['migration_id']}::{plan_hash}"
        ),
        "status": "READY_FOR_HUMAN_CONFIRMATION",
        "writes_performed": False,
    }


def migration_apply(
    migration_plan_path: str | Path,
    confirmation_text: str,
) -> dict[str, Any]:
    plan = read_json(Path(migration_plan_path).expanduser().resolve())
    excluded = {
        "migration_plan_sha256",
        "confirmation_text",
        "status",
        "writes_performed",
    }
    body = {key: value for key, value in plan.items() if key not in excluded}
    plan_hash = json_sha256(body)
    expected = (
        f"APPLY_READ_ONLY_MIGRATION::{plan.get('migration_id')}::{plan_hash}"
    )
    if plan.get("migration_plan_sha256") != plan_hash:
        raise RuntimeViolation(
            "MIGRATION_PLAN_HASH_MISMATCH", str(migration_plan_path)
        )
    if confirmation_text != expected:
        raise RuntimeViolation(
            "CONFIRMATION_TEXT_MISMATCH", "migration plan"
        )
    source = plan["source"]
    candidate = Path(source["legacy_candidate_root"]).resolve()
    legacy = Path(source["legacy_execution_root"]).resolve()
    if tree_sha256(candidate) != source["legacy_candidate_tree_sha256"]:
        raise RuntimeViolation(
            "LEGACY_CANDIDATE_HASH_DRIFT", str(candidate)
        )
    if tree_sha256(legacy) != source["legacy_execution_tree_sha256"]:
        raise RuntimeViolation(
            "LEGACY_EXECUTION_HASH_DRIFT", str(legacy)
        )
    new_root = lexical_path(plan["new_execution_root"])
    if new_root.exists() and any(new_root.iterdir()):
        raise RuntimeViolation(
            "NEW_EXECUTION_ROOT_NOT_EMPTY", str(new_root)
        )
    policy_path = candidate / "PROGRAM_AUTOMATION_POLICY.json"
    if policy_path.is_file():
        policy = read_json(policy_path)
        profile = policy.get("automation_profile")
    else:
        profile = None
    if not isinstance(profile, Mapping):
        profile = {
            "schema_version": "1.0",
            "requested_level": "A1_PLAN_ONLY",
            "activation_default": "DISABLED",
            "max_transitions": 1,
            "max_loop_rounds": 1,
            "max_wall_time_seconds": 3600,
            "stop_gate": "MIGRATION_BOOTSTRAP_REVERIFICATION_REQUIRED",
            "retryable_error_codes": [],
            "mandatory_human_gate_ids": [
                "MIGRATION_BOOTSTRAP_REVERIFICATION_REQUIRED",
                "WAIT_REAL_TARGET_INSTALL_AUTHORIZATION",
            ],
            "real_target_install_excluded": True,
        }
    control_plan = _load_control_plan(candidate)
    new_root.mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": "1.0",
        "runtime_version": RUNTIME_VERSION,
        "program_id": plan["program_id"],
        "epoch_id": f"EPOCH-{uuid.uuid4()}",
        "execution_root": str(new_root),
        "candidate_root": str(candidate),
        "candidate_content_sha256": source["legacy_candidate_tree_sha256"],
        "handoff_sha256": None,
        "charter_sha256": (
            file_sha256(candidate / "PROGRAM_CHARTER.md")
            if (candidate / "PROGRAM_CHARTER.md").is_file()
            else None
        ),
        "profile_lock_sha256": (
            file_sha256(candidate / "PROFILE_LOCK.json")
            if (candidate / "PROFILE_LOCK.json").is_file()
            else None
        ),
        "automation_profile": deepcopy(dict(profile)),
        "effective_mode": "A1_PLAN_ONLY",
        "bootstrap_bundle_id": None,
        "bootstrap_child_authorizations": [],
        "driver": {
            "materialized": False,
            "runtime_verified": False,
            "runtime_version": RUNTIME_VERSION,
        },
        "authorization": None,
        "authorization_history": [],
        "control_plan": control_plan,
        "completed_nodes": [],
        "touched_nodes": [],
        "locally_closed_nodes": [],
        "active_workpack": None,
        "active_attempt": None,
        "transitions_used": 0,
        "loop_rounds_used": 0,
        "fencing_counter": 0,
        "state_path_history": [],
        "hard_stop": None,
        "next_human_gate": "MIGRATION_BOOTSTRAP_REVERIFICATION_REQUIRED",
        "evidence_index": {},
        "migration": {
            "migration_id": plan["migration_id"],
            "migration_plan_sha256": plan_hash,
            "source": deepcopy(source),
            "node_classifications": deepcopy(plan["node_classifications"]),
            "historical_pass_restored": False,
        },
        "legacy_authorizations_imported": False,
        "real_target_install_allowed": False,
    }
    store = RuntimeStore(new_root)
    store.initialize(state)
    snapshot_ref = None
    if plan.get("copy_history_snapshot") is True:
        snapshot = new_root / "history_snapshot/legacy_execution"
        shutil.copytree(legacy, snapshot, symlinks=True)
        snapshot_ref = str(snapshot.relative_to(new_root))

    def applied(current: dict[str, Any]) -> None:
        current["migration"]["history_snapshot_ref"] = snapshot_ref
        current["next_human_gate"] = (
            "MIGRATION_BOOTSTRAP_REVERIFICATION_REQUIRED"
        )

    final_state = store.append(
        "READ_ONLY_MIGRATION_APPLIED",
        {
            "migration_id": plan["migration_id"],
            "legacy_candidate_tree_sha256": source[
                "legacy_candidate_tree_sha256"
            ],
            "legacy_execution_tree_sha256": source[
                "legacy_execution_tree_sha256"
            ],
            "legacy_authorizations_imported": False,
            "historical_pass_restored": False,
            "history_snapshot_ref": snapshot_ref,
        },
        mutate=applied,
    )["state"]
    return {
        "schema_version": "1.0",
        "status": "PASS",
        "migration_id": plan["migration_id"],
        "new_execution_root": str(new_root),
        "epoch_id": final_state["epoch_id"],
        "legacy_authorizations_imported": False,
        "historical_pass_restored": False,
        "driver_runtime_verified": False,
        "workpacks_executed": False,
        "target_code_executed": False,
        "next_gate": "MIGRATION_BOOTSTRAP_REVERIFICATION_REQUIRED",
    }
