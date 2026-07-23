"""Authorization-bound Driver planning and transactional Workpack execution."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import shutil
import sqlite3
import subprocess
import sys
from typing import Any, Iterable, Mapping
import uuid

from .store import RuntimeStore
from .util import (
    file_sha256,
    json_sha256,
    lexical_path,
    lexically_within,
    parse_utc,
    read_json,
    tree_sha256,
    utc_now,
    write_json,
)


RUNTIME_VERSION = "0.1.4"
BOOTSTRAP_COMPLETED_NODES = (
    "START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW",
    "START_PACKAGE_HUMAN_APPROVAL",
    "SHARED_CONTROL_BASELINE_LOCK",
    "CONTROL_PLANE_REGISTRATION",
    "PROGRAM_DRIVER_RUNTIME_VERIFIED",
)
AUTOMATION_RANK = {
    "A0_DECLARE_ONLY": 0,
    "A1_PLAN_ONLY": 1,
    "A2_WORKPACK_BOUNDED": 2,
    "A3_PROGRAM_BOUNDED": 3,
}
ALWAYS_HUMAN_GATES = {
    "WAIT_REAL_TARGET_INSTALL_AUTHORIZATION",
    "REAL_TARGET_INSTALL",
    "P3_NOT_APPLICABLE_LOCK",
    "SCOPE_EXPANSION",
    "WAIVER",
}


class RuntimeViolation(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def as_finding(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def validate_handoff_document(handoff: Mapping[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    program_id = handoff.get("program_id")
    if not isinstance(program_id, str) or not program_id:
        findings.append(
            {
                "code": "HANDOFF_PROGRAM_ID_MISSING",
                "message": "program_id",
            }
        )
    excluded = {
        "handoff_sha256",
        "status",
        "writes_performed",
        "commands_executed",
    }
    body = {key: value for key, value in handoff.items() if key not in excluded}
    if handoff.get("status") != "PASS":
        findings.append(
            {"code": "HANDOFF_NOT_PASS", "message": str(handoff.get("status"))}
        )
    if handoff.get("handoff_sha256") != json_sha256(body):
        findings.append(
            {"code": "HANDOFF_HASH_MISMATCH", "message": "handoff_sha256"}
        )
    if handoff.get("execution_authorization_inherited") is not False:
        findings.append(
            {
                "code": "INHERITED_AUTHORIZATION_FORBIDDEN",
                "message": "execution_authorization_inherited",
            }
        )
    candidate = Path(str(handoff.get("candidate_root", ""))).expanduser()
    if not candidate.is_dir():
        findings.append(
            {"code": "CANDIDATE_ROOT_MISSING", "message": str(candidate)}
        )
    elif tree_sha256(candidate) != handoff.get("candidate_content_sha256"):
        findings.append(
            {"code": "CANDIDATE_HASH_DRIFT", "message": str(candidate)}
        )
    elif isinstance(program_id, str) and program_id:
        for name in (
            "FACTORY_PROVENANCE.json",
            "PROGRAM_STATE.json",
            "PROGRAM_DRIVER_STATE.json",
            "ENGINEERING_PROJECT_DAG.json",
            "EXECUTION_AUTHORIZATION.json",
        ):
            try:
                document = read_json(candidate / name)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                findings.append(
                    {
                        "code": "HANDOFF_PROGRAM_ID_BINDING_UNREADABLE",
                        "message": f"{name}: {exc}",
                    }
                )
                continue
            if document.get("program_id") != program_id:
                findings.append(
                    {
                        "code": "HANDOFF_PROGRAM_ID_MISMATCH",
                        "message": name,
                    }
                )
        context_path = candidate / "START_CONTEXT.json"
        if context_path.is_file():
            try:
                context = read_json(context_path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                findings.append(
                    {
                        "code": "HANDOFF_PROGRAM_ID_BINDING_UNREADABLE",
                        "message": f"START_CONTEXT.json: {exc}",
                    }
                )
            else:
                context_program_id = context.get("program_id")
                if (
                    context_program_id is not None
                    and context_program_id != program_id
                ):
                    findings.append(
                        {
                            "code": "HANDOFF_PROGRAM_ID_MISMATCH",
                            "message": "START_CONTEXT.json",
                        }
                    )
    profile = handoff.get("automation_profile")
    if (
        not isinstance(profile, Mapping)
        or profile.get("activation_default") != "DISABLED"
        or profile.get("real_target_install_excluded") is not True
    ):
        findings.append(
            {"code": "AUTOMATION_PROFILE_INVALID", "message": "handoff"}
        )
    return findings


def bootstrap_plan(
    handoff_path: str | Path | None, execution_root: str | Path
) -> dict[str, Any]:
    """Create a review bundle without writing the execution root."""

    planned_root = lexical_path(execution_root)
    bootstrap_target_kind = "NEW_HANDOFF_ROOT"
    epoch_id = None
    if handoff_path is not None:
        handoff_file = Path(handoff_path).expanduser().resolve()
        handoff = read_json(handoff_file)
        findings = validate_handoff_document(handoff)
        if str(planned_root) != handoff.get("execution_root"):
            findings.append(
                {
                    "code": "EXECUTION_ROOT_HANDOFF_MISMATCH",
                    "message": f"{planned_root} != {handoff.get('execution_root')}",
                }
            )
        if planned_root.exists() and any(planned_root.iterdir()):
            findings.append(
                {
                    "code": "EXECUTION_ROOT_NOT_EMPTY",
                    "message": str(planned_root),
                }
            )
    else:
        try:
            state = RuntimeStore(planned_root).load_state()
        except (OSError, RuntimeError, sqlite3.Error) as exc:
            return {
                "schema_version": "1.0",
                "status": "FAIL",
                "blocking_findings": [
                    {
                        "code": "MIGRATED_RUNTIME_STATE_MISSING",
                        "message": str(exc),
                    }
                ],
                "writes_performed": False,
            }
        findings = []
        if not state.get("migration"):
            findings.append(
                {
                    "code": "HANDOFF_REQUIRED_FOR_NEW_RUNTIME",
                    "message": str(planned_root),
                }
            )
        if state.get("driver", {}).get("runtime_verified") is True:
            findings.append(
                {
                    "code": "DRIVER_RUNTIME_ALREADY_VERIFIED",
                    "message": str(planned_root),
                }
            )
        candidate = Path(state["candidate_root"])
        if (
            not candidate.is_dir()
            or tree_sha256(candidate)
            != state.get("candidate_content_sha256")
        ):
            findings.append(
                {
                    "code": "CANDIDATE_HASH_DRIFT",
                    "message": str(candidate),
                }
            )
        migration_handoff_body = {
            "schema_version": "1.0",
            "handoff_kind": "HF28_MIGRATED_EPOCH_TO_FRESH_BOOTSTRAP",
            "program_id": state["program_id"],
            "candidate_root": state["candidate_root"],
            "execution_root": state["execution_root"],
            "candidate_content_sha256": state[
                "candidate_content_sha256"
            ],
            "requirement_ir_sha256": None,
            "spec_content_sha256": None,
            "charter_sha256": state.get("charter_sha256"),
            "profile_lock_sha256": state.get("profile_lock_sha256"),
            "automation_profile": state["automation_profile"],
            "authoring_terminal_state": (
                "LEGACY_INPUT_REQUIRES_FRESH_BOOTSTRAP"
            ),
            "next_runtime_action": "BOOTSTRAP_PLAN",
            "execution_authorization_inherited": False,
            "real_target_install_authorization_inherited": False,
        }
        handoff = {
            **migration_handoff_body,
            "handoff_sha256": json_sha256(migration_handoff_body),
            "status": "PASS",
            "writes_performed": False,
            "commands_executed": False,
        }
        bootstrap_target_kind = "MIGRATED_EPOCH"
        epoch_id = state["epoch_id"]
    if findings:
        return {
            "schema_version": "1.0",
            "status": "FAIL",
            "blocking_findings": findings,
            "writes_performed": False,
        }

    bindings = {
        "program_id": handoff["program_id"],
        "candidate_content_sha256": handoff["candidate_content_sha256"],
        "handoff_sha256": handoff["handoff_sha256"],
        "charter_sha256": handoff["charter_sha256"],
        "profile_lock_sha256": handoff["profile_lock_sha256"],
        "execution_root": str(planned_root),
        "bootstrap_target_kind": bootstrap_target_kind,
        "epoch_id": epoch_id,
    }
    child_specs = (
        ("CANDIDATE_APPROVAL", "START_PACKAGE_HUMAN_APPROVAL"),
        ("BASELINE_APPROVAL", "SHARED_CONTROL_BASELINE_LOCK"),
        ("CONTROL_REGISTRATION", "CONTROL_PLANE_REGISTRATION"),
        ("DRIVER_MATERIALIZATION", "DRIVER_MATERIALIZATION"),
        ("RUNTIME_VERIFICATION", "PROGRAM_DRIVER_RUNTIME_VERIFIED"),
    )
    child_authorizations = []
    for child_kind, action in child_specs:
        body = {
            "schema_version": "1.0",
            "authorization_kind": child_kind,
            "action_id": action,
            "bindings": bindings,
            "status": "PENDING_HUMAN_CONFIRMATION",
            "execution_authority_granted": False,
        }
        child_authorizations.append(
            {**body, "authorization_sha256": json_sha256(body)}
        )
    bundle_seed = {
        "program_id": handoff["program_id"],
        "handoff_sha256": handoff["handoff_sha256"],
        "execution_root": str(planned_root),
        "child_authorization_hashes": [
            item["authorization_sha256"] for item in child_authorizations
        ],
    }
    bundle_id = f"BOOTSTRAP-{json_sha256(bundle_seed)[:24].upper()}"
    body = {
        "schema_version": "1.0",
        "bundle_id": bundle_id,
        "bundle_kind": "BOOTSTRAP_APPROVAL_BUNDLE",
        "created_at": utc_now(),
        "handoff": handoff,
        "execution_root": str(planned_root),
        "bootstrap_target_kind": bootstrap_target_kind,
        "epoch_id": epoch_id,
        "child_authorizations": child_authorizations,
        "execution_authorization_included": False,
        "real_target_install_authorization_included": False,
    }
    bundle_hash = json_sha256(body)
    return {
        **body,
        "bundle_sha256": bundle_hash,
        "confirmation_text": (
            f"APPROVE_BOOTSTRAP_BUNDLE::{bundle_id}::{bundle_hash}"
        ),
        "status": "READY_FOR_HUMAN_CONFIRMATION",
        "writes_performed": False,
    }


def bootstrap_apply(
    bundle_path: str | Path, confirmation_text: str
) -> dict[str, Any]:
    bundle = read_json(Path(bundle_path).expanduser().resolve())
    _validate_bootstrap_bundle(bundle, confirmation_text)
    execution_root = lexical_path(bundle["execution_root"])
    migrated_epoch = bundle.get("bootstrap_target_kind") == "MIGRATED_EPOCH"
    if not migrated_epoch and execution_root.exists() and any(
        execution_root.iterdir()
    ):
        raise RuntimeViolation("EXECUTION_ROOT_NOT_EMPTY", str(execution_root))
    handoff = bundle["handoff"]
    candidate = Path(handoff["candidate_root"]).expanduser().resolve()
    if tree_sha256(candidate) != handoff["candidate_content_sha256"]:
        raise RuntimeViolation("CANDIDATE_HASH_DRIFT", str(candidate))
    store = RuntimeStore(execution_root)
    if migrated_epoch:
        existing = store.load_state()
        if (
            existing.get("epoch_id") != bundle.get("epoch_id")
            or existing.get("program_id") != handoff.get("program_id")
            or existing.get("candidate_content_sha256")
            != handoff.get("candidate_content_sha256")
            or not existing.get("migration")
            or existing.get("authorization") is not None
            or existing.get("active_attempt") is not None
        ):
            raise RuntimeViolation(
                "MIGRATED_BOOTSTRAP_BINDING_MISMATCH",
                str(execution_root),
            )
    else:
        control_plan = _load_control_plan(candidate)
        execution_root.mkdir(parents=True, exist_ok=True)
        initial_state = {
            "schema_version": "1.0",
            "runtime_version": RUNTIME_VERSION,
            "program_id": handoff["program_id"],
            "epoch_id": f"EPOCH-{uuid.uuid4()}",
            "execution_root": str(execution_root),
            "candidate_root": str(candidate),
            "candidate_content_sha256": handoff["candidate_content_sha256"],
            "handoff_sha256": handoff["handoff_sha256"],
            "charter_sha256": handoff["charter_sha256"],
            "profile_lock_sha256": handoff["profile_lock_sha256"],
            "automation_profile": handoff["automation_profile"],
            "effective_mode": "A1_PLAN_ONLY",
            "bootstrap_bundle_id": bundle["bundle_id"],
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
            "completed_workpacks": [],
            "touched_nodes": [],
            "locally_closed_nodes": [],
            "active_workpack": None,
            "active_attempt": None,
            "transitions_used": 0,
            "loop_rounds_used": 0,
            "fencing_counter": 0,
            "state_path_history": [],
            "hard_stop": None,
            "next_human_gate": None,
            "next_required_action": None,
            "evidence_index": {},
            "command_overlay_history": [],
            "resolver_history": [],
            "legacy_authorizations_imported": False,
            "real_target_install_allowed": False,
        }
        store.initialize(initial_state)
    child_by_kind = {
        item["authorization_kind"]: item
        for item in bundle["child_authorizations"]
    }

    def consume_child(
        kind: str, completed_nodes: Iterable[str] = ()
    ) -> dict[str, Any]:
        child = child_by_kind[kind]

        def mutation(state: dict[str, Any]) -> None:
            state["bootstrap_bundle_id"] = bundle["bundle_id"]
            consumed = deepcopy(child)
            consumed["status"] = "CONSUMED"
            consumed["consumed_at"] = utc_now()
            state["bootstrap_child_authorizations"].append(consumed)
            for node_id in completed_nodes:
                _append_unique(state["completed_nodes"], node_id)
                _append_unique(state["touched_nodes"], node_id)
                _append_unique(state["locally_closed_nodes"], node_id)

        return store.append(
            f"{kind}_CONSUMED",
            {
                "authorization_sha256": child["authorization_sha256"],
                "action_id": child["action_id"],
            },
            mutate=mutation,
        )["state"]

    consume_child(
        "CANDIDATE_APPROVAL",
        BOOTSTRAP_COMPLETED_NODES[:2],
    )
    consume_child("BASELINE_APPROVAL", BOOTSTRAP_COMPLETED_NODES[2:3])
    consume_child(
        "CONTROL_REGISTRATION", BOOTSTRAP_COMPLETED_NODES[3:4]
    )

    runtime_source = Path(__file__).resolve().parent
    vendored_parent = execution_root / "control_plane/driver/runtime"
    vendored_package = vendored_parent / runtime_source.name
    vendored_package.mkdir(parents=True, exist_ok=True)
    vendored_files = []
    for source in sorted(runtime_source.glob("*.py")):
        destination = vendored_package / source.name
        shutil.copy2(source, destination)
        vendored_files.append(destination)
    entry_path = execution_root / "control_plane/driver/driver_entry.py"
    entry_path.write_text(
        "\n".join(
            (
                "from pathlib import Path",
                "import sys",
                "",
                "runtime_root = Path(__file__).resolve().parent / 'runtime'",
                "sys.path.insert(0, str(runtime_root))",
                "from harness_foundry_runtime.cli import main",
                "",
                "raise SystemExit(main())",
                "",
            )
        ),
        encoding="utf-8",
    )
    launcher_path = execution_root / "control_plane/bin/hfdriver"
    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_path.write_text(
        "#!/bin/sh\n"
        f"exec {shlex.quote(sys.executable)} -I "
        f"{shlex.quote(str(entry_path))} \"$@\"\n",
        encoding="utf-8",
    )
    launcher_path.chmod(0o755)
    descriptor = {
        "schema_version": "1.0",
        "driver_id": "HF28_CONTROLLED_PROGRAM_DRIVER",
        "runtime_version": RUNTIME_VERSION,
        "program_id": handoff["program_id"],
        "epoch_id": store.load_state()["epoch_id"],
        "candidate_content_sha256": handoff["candidate_content_sha256"],
        "entrypoint": str(launcher_path),
        "python_executable": sys.executable,
        "python_executable_sha256": file_sha256(Path(sys.executable)),
        "vendored_runtime_root": str(vendored_parent),
        "side_effects_allowed_without_execution_authorization": False,
    }
    descriptor_path = (
        execution_root / "control_plane/driver/PROGRAM_DRIVER_DESCRIPTOR.json"
    )
    write_json(descriptor_path, descriptor)
    descriptor_hash = file_sha256(descriptor_path)
    launcher_hash = file_sha256(launcher_path)
    entry_hash = file_sha256(entry_path)
    runtime_file_hashes = {
        path.relative_to(execution_root).as_posix(): file_sha256(path)
        for path in vendored_files
    }

    def materialized(state: dict[str, Any]) -> None:
        state["driver"].update(
            {
                "materialized": True,
                "descriptor_sha256": descriptor_hash,
                "launcher_sha256": launcher_hash,
                "entry_sha256": entry_hash,
                "vendored_runtime_file_count": len(runtime_file_hashes),
            }
        )
        state["evidence_index"].update(
            {
                descriptor_path.relative_to(execution_root).as_posix(): descriptor_hash,
                launcher_path.relative_to(execution_root).as_posix(): launcher_hash,
                entry_path.relative_to(execution_root).as_posix(): entry_hash,
                **runtime_file_hashes,
            }
        )

    child = child_by_kind["DRIVER_MATERIALIZATION"]

    def materialization_consumed(state: dict[str, Any]) -> None:
        materialized(state)
        state["bootstrap_child_authorizations"].append(
            {
                **deepcopy(child),
                "status": "CONSUMED",
                "consumed_at": utc_now(),
            }
        )

    store.append(
        "DRIVER_MATERIALIZATION_CONSUMED",
        {"authorization_sha256": child["authorization_sha256"]},
        mutate=materialization_consumed,
    )
    if sys.version_info < (3, 11):
        raise RuntimeViolation(
            "PYTHON_VERSION_UNSUPPORTED", sys.version.split()[0]
        )
    probe = _launch_driver_probe(launcher_path, execution_root)

    runtime_evidence = {
        "schema_version": "1.0",
        "program_id": handoff["program_id"],
        "epoch_id": store.load_state()["epoch_id"],
        "python_version": sys.version.split()[0],
        "descriptor_sha256": descriptor_hash,
        "launcher_sha256": launcher_hash,
        "entry_sha256": entry_hash,
        "vendored_runtime_file_hashes": runtime_file_hashes,
        "python_executable": sys.executable,
        "python_executable_sha256": file_sha256(Path(sys.executable)),
        "driver_probe": probe,
        "candidate_content_sha256": tree_sha256(candidate),
        "status": "PASS",
    }
    runtime_evidence_path = (
        execution_root / "evidence/bootstrap/DRIVER_RUNTIME_VERIFICATION.json"
    )
    write_json(runtime_evidence_path, runtime_evidence)
    runtime_evidence_hash = file_sha256(runtime_evidence_path)
    child = child_by_kind["RUNTIME_VERIFICATION"]

    def verified(state: dict[str, Any]) -> None:
        state["bootstrap_child_authorizations"].append(
            {
                **deepcopy(child),
                "status": "CONSUMED",
                "consumed_at": utc_now(),
            }
        )
        state["driver"]["runtime_verified"] = True
        state["evidence_index"][
            runtime_evidence_path.relative_to(execution_root).as_posix()
        ] = runtime_evidence_hash
        _append_unique(
            state["completed_nodes"], "PROGRAM_DRIVER_RUNTIME_VERIFIED"
        )
        _append_unique(
            state["touched_nodes"], "PROGRAM_DRIVER_RUNTIME_VERIFIED"
        )
        _append_unique(
            state["locally_closed_nodes"], "PROGRAM_DRIVER_RUNTIME_VERIFIED"
        )
        state["next_human_gate"] = None
        state["next_required_action"] = (
            "RESOLVE_OR_REGISTER_COMMAND_OVERLAYS"
        )

    state = store.append(
        "RUNTIME_VERIFICATION_CONSUMED",
        {
            "authorization_sha256": child["authorization_sha256"],
            "evidence_sha256": runtime_evidence_hash,
        },
        mutate=verified,
        evidence_sha256=runtime_evidence_hash,
    )["state"]
    return {
        "schema_version": "1.0",
        "status": "PASS",
        "execution_root": str(execution_root),
        "program_id": state["program_id"],
        "epoch_id": state["epoch_id"],
        "driver_runtime_verified": True,
        "effective_mode": "A1_PLAN_ONLY",
        "execution_authorization": "NOT_GRANTED",
        "next_human_gate": None,
        "next_required_action": "RESOLVE_OR_REGISTER_COMMAND_OVERLAYS",
        "commands_executed": False,
        "workpacks_executed": False,
    }


def _launch_driver_probe(
    launcher_path: Path, execution_root: Path
) -> dict[str, Any]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME"}
    }
    environment["PYTHONNOUSERSITE"] = "1"
    try:
        completed = subprocess.run(
            [
                str(launcher_path),
                "status",
                "--execution-root",
                str(execution_root),
            ],
            cwd=execution_root,
            env=environment,
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeViolation(
            "DRIVER_LAUNCH_FAILED", str(exc)
        ) from exc
    stdout = completed.stdout.decode("utf-8", errors="replace")
    stderr = completed.stderr.decode("utf-8", errors="replace")
    if completed.returncode != 0:
        raise RuntimeViolation(
            "DRIVER_LAUNCH_FAILED",
            f"exit={completed.returncode}; stderr={stderr[:500]}",
        )
    try:
        report = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeViolation(
            "DRIVER_READBACK_INVALID", str(exc)
        ) from exc
    if (
        not isinstance(report, dict)
        or report.get("status") != "PASS"
        or report.get("driver_runtime_verified") is not False
    ):
        raise RuntimeViolation(
            "DRIVER_READBACK_INVALID", stdout[:500]
        )
    return {
        "exit_code": completed.returncode,
        "stdout_sha256": json_sha256({"stdout": stdout}),
        "stderr_sha256": json_sha256({"stderr": stderr}),
        "program_id": report.get("program_id"),
        "runtime_revision": report.get("runtime_revision"),
        "driver_runtime_verified_before_consumption": False,
        "status": "PASS",
    }


def register_command_overlays(
    execution_root: str | Path, bundle_path: str | Path
) -> dict[str, Any]:
    store = RuntimeStore(execution_root)
    state = store.load_state()
    bundle = read_json(Path(bundle_path).expanduser().resolve())
    if state.get("driver", {}).get("runtime_verified") is not True:
        return _overlay_failure(
            "DRIVER_RUNTIME_NOT_VERIFIED",
            "bootstrap verification is required",
        )
    authorization = state.get("authorization")
    if (
        isinstance(authorization, Mapping)
        and authorization.get("status") == "ACTIVE"
    ):
        return _overlay_failure(
            "OVERLAY_REGISTRATION_WITH_AUTHORIZATION_FORBIDDEN",
            str(authorization.get("authorization_id")),
        )
    for field in (
        "program_id",
        "epoch_id",
        "candidate_content_sha256",
    ):
        if bundle.get(field) != state.get(field):
            return _overlay_failure(
                "COMMAND_OVERLAY_BINDING_MISMATCH", field
            )
    if bundle.get("overlay_kind") != "RESOLVED_COMMAND_OVERLAY_BUNDLE":
        return _overlay_failure(
            "COMMAND_OVERLAY_KIND_INVALID",
            str(bundle.get("overlay_kind")),
        )
    manifests = bundle.get("manifests")
    if not isinstance(manifests, Mapping) or not manifests:
        return _overlay_failure(
            "COMMAND_OVERLAY_MANIFESTS_INVALID", "manifests"
        )
    nodes = {
        node["node_id"]: node
        for node in state.get("control_plan", {}).get("nodes", [])
    }
    validated: dict[str, dict[str, Any]] = {}
    for node_id, manifest in manifests.items():
        node = nodes.get(node_id)
        if node is None:
            return _overlay_failure(
                "COMMAND_OVERLAY_NODE_UNKNOWN", str(node_id)
            )
        if (
            node.get("human_gate") is True
            or node_id in ALWAYS_HUMAN_GATES
        ):
            return _overlay_failure(
                "COMMAND_OVERLAY_HUMAN_GATE_FORBIDDEN", str(node_id)
            )
        if node.get("auto_advance_eligible") is not True:
            return _overlay_failure(
                "COMMAND_OVERLAY_NODE_NOT_AUTOMATABLE", str(node_id)
            )
        if node_id in state.get("completed_nodes", []):
            return _overlay_failure(
                "COMMAND_OVERLAY_NODE_ALREADY_COMPLETED", str(node_id)
            )
        if not isinstance(manifest, Mapping):
            return _overlay_failure(
                "COMMAND_OVERLAY_MANIFEST_INVALID", str(node_id)
            )
        try:
            _validate_resolved_manifest(
                state,
                node,
                manifest,
                authorized_write_roots=None,
            )
        except RuntimeViolation as exc:
            return _overlay_failure(exc.code, exc.message)
        validated[node_id] = deepcopy(dict(manifest))

    state_root = lexical_path(state["execution_root"])
    overlay_root = state_root / "control_plane/resolved_commands"
    bindings: dict[str, dict[str, str]] = {}
    for node_id, manifest in validated.items():
        manifest_sha256 = json_sha256(manifest)
        node_key = json_sha256({"node_id": node_id})[:16]
        path = overlay_root / f"{node_key}-{manifest_sha256}.json"
        if path.is_file():
            existing = read_json(path)
            if existing != manifest:
                raise RuntimeViolation(
                    "COMMAND_OVERLAY_HASH_COLLISION", node_id
                )
        else:
            write_json(path, manifest)
        bindings[node_id] = {
            "path": str(path),
            "sha256": file_sha256(path),
        }
    bundle_sha256 = json_sha256(bundle)

    def registered(current: dict[str, Any]) -> None:
        current_authorization = current.get("authorization")
        if (
            isinstance(current_authorization, Mapping)
            and current_authorization.get("status") == "ACTIVE"
        ):
            raise RuntimeViolation(
                "OVERLAY_REGISTRATION_WITH_AUTHORIZATION_FORBIDDEN",
                str(current_authorization.get("authorization_id")),
            )
        current_nodes = {
            node["node_id"]: node
            for node in current["control_plan"]["nodes"]
        }
        for node_id, binding in bindings.items():
            current_nodes[node_id]["command_manifest"] = deepcopy(
                binding
            )
            relative = (
                Path(binding["path"])
                .relative_to(state_root)
                .as_posix()
            )
            current["evidence_index"][relative] = binding["sha256"]
        next_node = _unique_next_node(current)
        if (
            next_node is not None
            and isinstance(
                next_node.get("command_manifest"), Mapping
            )
        ):
            current["next_required_action"] = (
                "PLAN_EXECUTION_AUTHORIZATION"
            )
            current["next_human_gate"] = (
                "EXECUTION_AUTHORIZATION_REQUIRED"
            )
        current.setdefault("command_overlay_history", []).append(
            {
                "bundle_sha256": bundle_sha256,
                "registered_at": utc_now(),
                "command_manifests": deepcopy(bindings),
                "execution_authority_granted": False,
            }
        )

    result = store.append(
        "COMMAND_OVERLAYS_REGISTERED",
        {
            "bundle_sha256": bundle_sha256,
            "node_ids": sorted(bindings),
            "manifest_hashes": {
                node_id: binding["sha256"]
                for node_id, binding in bindings.items()
            },
            "execution_authority_granted": False,
        },
        mutate=registered,
        expected_revision=state["revision"],
    )
    return {
        "schema_version": "1.0",
        "status": "PASS",
        "program_id": result["state"]["program_id"],
        "epoch_id": result["state"]["epoch_id"],
        "bundle_sha256": bundle_sha256,
        "command_manifests": bindings,
        "execution_authority_granted": False,
        "commands_executed": False,
        "writes_performed": True,
    }


def _overlay_failure(code: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": "FAIL",
        "blocking_findings": [{"code": code, "message": message}],
        "writes_performed": False,
        "commands_executed": False,
        "execution_authority_granted": False,
    }


def authorization_plan(
    execution_root: str | Path, request_path: str | Path
) -> dict[str, Any]:
    store = RuntimeStore(execution_root)
    state = store.load_state()
    request = read_json(Path(request_path).expanduser().resolve())
    findings: list[dict[str, str]] = []
    if state.get("driver", {}).get("runtime_verified") is not True:
        findings.append(
            {
                "code": "DRIVER_RUNTIME_NOT_VERIFIED",
                "message": "bootstrap verification is required",
            }
        )
    level = request.get("level")
    requested_level = state.get("automation_profile", {}).get(
        "requested_level", "A1_PLAN_ONLY"
    )
    if level != "A3_PROGRAM_BOUNDED":
        findings.append(
            {"code": "A3_EXACT_LEVEL_REQUIRED", "message": str(level)}
        )
    if AUTOMATION_RANK.get(requested_level, -1) < AUTOMATION_RANK[
        "A3_PROGRAM_BOUNDED"
    ]:
        findings.append(
            {
                "code": "AUTOMATION_PROFILE_LEVEL_TOO_LOW",
                "message": str(requested_level),
            }
        )
    required_fields = {
        "level",
        "dag_node_ids",
        "workpack_ids",
        "command_manifests",
        "allowed_write_roots",
        "environment_ids",
        "expires_at",
        "max_transitions",
        "max_loop_rounds",
        "max_wall_time_seconds",
    }
    missing = sorted(required_fields - set(request))
    if missing:
        findings.append(
            {"code": "AUTHORIZATION_FIELDS_MISSING", "message": str(missing)}
        )
    try:
        expires = parse_utc(str(request.get("expires_at")))
        if expires <= datetime.now(timezone.utc):
            findings.append(
                {
                    "code": "AUTHORIZATION_ALREADY_EXPIRED",
                    "message": str(request.get("expires_at")),
                }
            )
    except (TypeError, ValueError):
        findings.append(
            {
                "code": "AUTHORIZATION_EXPIRY_INVALID",
                "message": str(request.get("expires_at")),
            }
        )
    known_nodes = {
        node["node_id"] for node in state.get("control_plan", {}).get("nodes", [])
    }
    control_nodes = {
        node["node_id"]: node
        for node in state.get("control_plan", {}).get("nodes", [])
    }
    nodes = request.get("dag_node_ids", [])
    if (
        not isinstance(nodes, list)
        or not nodes
        or not set(nodes).issubset(known_nodes)
    ):
        findings.append(
            {"code": "AUTHORIZATION_NODE_SCOPE_INVALID", "message": str(nodes)}
        )
    manifests = request.get("command_manifests", {})
    if not isinstance(manifests, Mapping) or set(manifests) != set(nodes):
        findings.append(
            {
                "code": "COMMAND_MANIFEST_SCOPE_INVALID",
                "message": "one manifest is required per authorized node",
            }
        )
    else:
        for node_id, binding in manifests.items():
            if not isinstance(binding, Mapping):
                findings.append(
                    {
                        "code": "COMMAND_MANIFEST_BINDING_INVALID",
                        "message": str(node_id),
                    }
                )
                continue
            path = lexical_path(str(binding.get("path", "")))
            if (
                not lexically_within(path, state["execution_root"])
                or not path.is_file()
                or file_sha256(path) != binding.get("sha256")
            ):
                findings.append(
                    {
                        "code": "COMMAND_MANIFEST_HASH_MISMATCH",
                        "message": str(node_id),
                    }
                )
            registered = control_nodes.get(node_id, {}).get(
                "command_manifest"
            )
            if not isinstance(registered, Mapping):
                findings.append(
                    {
                        "code": "COMMAND_MANIFEST_NOT_REGISTERED",
                        "message": str(node_id),
                    }
                )
            elif (
                registered.get("path") != str(path)
                or registered.get("sha256") != binding.get("sha256")
            ):
                findings.append(
                    {
                        "code": "COMMAND_MANIFEST_REGISTRATION_MISMATCH",
                        "message": str(node_id),
                    }
                )
    write_roots = request.get("allowed_write_roots", [])
    if (
        not isinstance(write_roots, list)
        or not write_roots
        or not all(
            Path(str(path)).is_absolute()
            and lexically_within(path, state["execution_root"])
            for path in write_roots
        )
    ):
        findings.append(
            {
                "code": "AUTHORIZATION_WRITE_SCOPE_INVALID",
                "message": str(write_roots),
            }
        )
    for key in (
        "max_transitions",
        "max_loop_rounds",
        "max_wall_time_seconds",
    ):
        if (
            not isinstance(request.get(key), int)
            or int(request[key]) <= 0
        ):
            findings.append(
                {"code": "AUTHORIZATION_BUDGET_INVALID", "message": key}
            )
    if findings:
        return {
            "schema_version": "1.0",
            "status": "FAIL",
            "blocking_findings": findings,
            "writes_performed": False,
        }
    profile = state["automation_profile"]
    body = {
        "schema_version": "1.0",
        "authorization_id": (
            f"EXEC-A3-{json_sha256({'request': request, 'epoch': state['epoch_id']})[:24].upper()}"
        ),
        "authorization_kind": "EXECUTION_AUTHORIZATION",
        "status": "READY_FOR_HUMAN_CONFIRMATION",
        "level": "A3_PROGRAM_BOUNDED",
        "program_id": state["program_id"],
        "epoch_id": state["epoch_id"],
        "candidate_content_sha256": state["candidate_content_sha256"],
        "dag_node_ids": list(nodes),
        "workpack_ids": list(request["workpack_ids"]),
        "command_manifests": deepcopy(dict(manifests)),
        "allowed_write_roots": list(write_roots),
        "environment_ids": list(request["environment_ids"]),
        "expires_at": request["expires_at"],
        "max_transitions": min(
            int(profile["max_transitions"]),
            int(request["max_transitions"]),
        ),
        "max_loop_rounds": min(
            int(profile["max_loop_rounds"]),
            int(request["max_loop_rounds"]),
        ),
        "max_wall_time_seconds": min(
            int(profile["max_wall_time_seconds"]),
            int(request["max_wall_time_seconds"]),
        ),
        "retryable_error_codes": list(
            profile.get("retryable_error_codes", [])
        ),
        "real_target_install_allowed": False,
        "bootstrap_authority_inherited": False,
    }
    auth_hash = json_sha256(body)
    return {
        **body,
        "authorization_sha256": auth_hash,
        "confirmation_text": (
            f"APPROVE_EXECUTION_AUTHORIZATION::{body['authorization_id']}::{auth_hash}"
        ),
        "status": "READY_FOR_HUMAN_CONFIRMATION",
        "writes_performed": False,
    }


def authorization_apply(
    execution_root: str | Path,
    authorization_path: str | Path,
    confirmation_text: str,
) -> dict[str, Any]:
    store = RuntimeStore(execution_root)
    planned = read_json(Path(authorization_path).expanduser().resolve())
    excluded = {
        "authorization_sha256",
        "confirmation_text",
        "writes_performed",
    }
    body = {key: value for key, value in planned.items() if key not in excluded}
    expected_hash = json_sha256(body)
    expected_confirmation = (
        f"APPROVE_EXECUTION_AUTHORIZATION::{planned.get('authorization_id')}::{expected_hash}"
    )
    if planned.get("authorization_sha256") != expected_hash:
        raise RuntimeViolation(
            "AUTHORIZATION_HASH_MISMATCH", str(authorization_path)
        )
    if confirmation_text != expected_confirmation:
        raise RuntimeViolation(
            "CONFIRMATION_TEXT_MISMATCH", "execution authorization"
        )
    state = store.load_state()
    if (
        planned.get("program_id") != state["program_id"]
        or planned.get("epoch_id") != state["epoch_id"]
        or planned.get("candidate_content_sha256")
        != state["candidate_content_sha256"]
    ):
        raise RuntimeViolation(
            "AUTHORIZATION_BINDING_MISMATCH", planned["authorization_id"]
        )
    if parse_utc(planned["expires_at"]) <= datetime.now(timezone.utc):
        raise RuntimeViolation(
            "AUTHORIZATION_EXPIRED", planned["authorization_id"]
        )
    active = deepcopy(body)
    active["status"] = "ACTIVE"
    active["activated_at"] = utc_now()
    active["transitions_used"] = 0
    active["loop_rounds_used"] = 0

    def mutation(current: dict[str, Any]) -> None:
        current_authorization = current.get("authorization")
        if (
            isinstance(current_authorization, Mapping)
            and current_authorization.get("status") == "ACTIVE"
        ):
            raise RuntimeViolation(
                "ACTIVE_AUTHORIZATION_ALREADY_EXISTS",
                current_authorization["authorization_id"],
            )
        current["authorization"] = active
        current["effective_mode"] = "A3_PROGRAM_BOUNDED"
        current["next_human_gate"] = None
        current["next_required_action"] = "ADVANCE_UNTIL_GATE"
        current["authorization_history"].append(
            {
                "authorization_id": active["authorization_id"],
                "status": "ACTIVE",
                "authorization_sha256": expected_hash,
            }
        )

    result = store.append(
        "EXECUTION_AUTHORIZATION_ACTIVATED",
        {
            "authorization_id": active["authorization_id"],
            "authorization_sha256": expected_hash,
        },
        mutate=mutation,
    )
    return {
        "schema_version": "1.0",
        "status": "PASS",
        "authorization_id": active["authorization_id"],
        "effective_mode": result["state"]["effective_mode"],
        "effective_transition_budget": active["max_transitions"],
        "effective_loop_budget": active["max_loop_rounds"],
        "real_target_install_allowed": False,
    }


def authorization_revoke(
    execution_root: str | Path, authorization_id: str, reason: str
) -> dict[str, Any]:
    store = RuntimeStore(execution_root)

    def mutation(state: dict[str, Any]) -> None:
        authorization = state.get("authorization")
        if (
            not isinstance(authorization, dict)
            or authorization.get("authorization_id") != authorization_id
        ):
            raise RuntimeViolation(
                "AUTHORIZATION_NOT_FOUND", authorization_id
            )
        authorization["status"] = "REVOKED"
        authorization["revoked_at"] = utc_now()
        authorization["revocation_reason"] = reason
        state["effective_mode"] = "A1_PLAN_ONLY"
        state["next_human_gate"] = "EXECUTION_AUTHORIZATION_REQUIRED"

    store.append(
        "EXECUTION_AUTHORIZATION_REVOKED",
        {"authorization_id": authorization_id, "reason": reason},
        mutate=mutation,
    )
    return {
        "schema_version": "1.0",
        "status": "PASS",
        "authorization_id": authorization_id,
        "authorization_status": "REVOKED",
    }


def status(execution_root: str | Path) -> dict[str, Any]:
    store = RuntimeStore(execution_root)
    state = store.load_state()
    authorization = state.get("authorization") or {}
    plan = plan_next(execution_root)
    return {
        "schema_version": "1.0",
        "status": "PASS",
        "program_id": state["program_id"],
        "epoch_id": state["epoch_id"],
        "runtime_revision": state["revision"],
        "effective_mode": state["effective_mode"],
        "driver_runtime_verified": state["driver"]["runtime_verified"],
        "next_required_action": state.get("next_required_action"),
        "registered_command_manifest_count": sum(
            1
            for node in state["control_plan"]["nodes"]
            if isinstance(node.get("command_manifest"), Mapping)
        ),
        "highest_touched": (
            state["touched_nodes"][-1] if state["touched_nodes"] else None
        ),
        "highest_locally_closed": (
            state["locally_closed_nodes"][-1]
            if state["locally_closed_nodes"]
            else None
        ),
        "touched_nodes": state["touched_nodes"],
        "locally_closed_nodes": state["locally_closed_nodes"],
        "completed_workpacks": state.get("completed_workpacks", []),
        "active_workpack": state["active_workpack"],
        "active_attempt": state["active_attempt"],
        "authorization": {
            "authorization_id": authorization.get("authorization_id"),
            "status": authorization.get("status", "NOT_GRANTED"),
            "expires_at": authorization.get("expires_at"),
        },
        "budget": {
            "transitions_used": state["transitions_used"],
            "transitions_max": authorization.get("max_transitions", 0),
            "loop_rounds_used": state["loop_rounds_used"],
            "loop_rounds_max": authorization.get("max_loop_rounds", 0),
        },
        "next": plan,
        "hard_stop": state["hard_stop"],
        "real_target_install_allowed": False,
    }


def plan_next(execution_root: str | Path) -> dict[str, Any]:
    state = RuntimeStore(execution_root).load_state()
    if state.get("hard_stop"):
        return {
            "decision": "HARD_STOP",
            "hard_stop": state["hard_stop"],
            "unique_return_path": state["hard_stop"]["return_path"],
        }
    if state.get("active_attempt"):
        return {
            "decision": "RESUME_REQUIRED",
            "attempt_id": state["active_attempt"]["attempt_id"],
            "node_id": state["active_attempt"]["node_id"],
        }
    if state.get("migration") and state.get("driver", {}).get(
        "runtime_verified"
    ) is not True:
        return {
            "decision": "HUMAN_GATE",
            "human_gate_id": "MIGRATION_BOOTSTRAP_REVERIFICATION_REQUIRED",
            "reason": {
                "code": "MIGRATED_RUNTIME_REQUIRES_FRESH_BOOTSTRAP",
                "message": "legacy PASS and authorization were not restored",
            },
        }
    history = state.get("state_path_history", [])
    if (
        len(history) >= 3
        and history[-1] == history[-3]
        and history[-1] != history[-2]
    ):
        return {
            "decision": "HARD_STOP",
            "reason": {
                "code": "STATE_OSCILLATION_DETECTED",
                "message": "A_TO_B_TO_A",
            },
            "unique_return_path": "RETURN_TO_FINDING_REPAIR_GATE",
        }
    node = _unique_next_node(state)
    if node is None:
        return {
            "decision": "PROGRAM_PLAN_COMPLETE",
            "next_human_gate": None,
        }
    node_id = node["node_id"]
    mandatory = set(
        state.get("automation_profile", {}).get(
            "mandatory_human_gate_ids", []
        )
    )
    if (
        node.get("human_gate") is True
        or node_id in mandatory
        or node_id in ALWAYS_HUMAN_GATES
    ):
        return {
            "decision": "HUMAN_GATE",
            "node_id": node_id,
            "human_gate_id": node.get("human_gate_id") or node_id,
        }
    if "P3_C3_OR_APPROVED_NA" in node_id and not state.get(
        "branch_decisions", {}
    ).get(node_id):
        return {
            "decision": "HUMAN_GATE",
            "node_id": node_id,
            "human_gate_id": "P3_IMPLEMENT_OR_APPROVED_NA_SELECTION",
        }
    if state.get("driver", {}).get("runtime_verified") is not True:
        return {
            "decision": "HUMAN_GATE",
            "node_id": node_id,
            "human_gate_id": "BOOTSTRAP_APPROVAL_REQUIRED",
        }
    if not isinstance(node.get("command_manifest"), Mapping):
        return {
            "decision": "PREPARATION_REQUIRED",
            "node_id": node_id,
            "required_action": "RESOLVE_OR_REGISTER_COMMAND_OVERLAYS",
            "reason": {
                "code": "COMMAND_OVERLAY_REQUIRED",
                "message": node_id,
            },
        }
    authorization = state.get("authorization")
    issue = _authorization_issue(state, node, authorization)
    if issue is not None:
        return {
            "decision": "HUMAN_GATE"
            if issue["code"] in {
                "AUTHORIZATION_MISSING",
                "AUTHORIZATION_EXPIRED",
                "AUTHORIZATION_REVOKED",
                "TRANSITION_BUDGET_EXHAUSTED",
                "LOOP_BUDGET_EXHAUSTED",
            }
            else "HARD_STOP",
            "node_id": node_id,
            "human_gate_id": "EXECUTION_AUTHORIZATION_REQUIRED",
            "reason": issue,
        }
    binding = authorization["command_manifests"].get(node_id)
    return {
        "decision": "ADVANCE",
        "node_id": node_id,
        "workpack_ids": _node_workpacks(node),
        "command_manifest": binding,
        "effective_transition_budget_remaining": (
            authorization["max_transitions"]
            - authorization.get("transitions_used", 0)
        ),
        "effective_loop_budget_remaining": (
            authorization["max_loop_rounds"]
            - authorization.get("loop_rounds_used", 0)
        ),
    }


def verify_run(execution_root: str | Path) -> dict[str, Any]:
    root = Path(execution_root).expanduser().resolve()
    store = RuntimeStore(root)
    report = store.verify()
    if report["status"] == "FAIL":
        return report
    state = store.load_state()
    findings: list[dict[str, str]] = []
    candidate = Path(state["candidate_root"])
    if not candidate.is_dir() or tree_sha256(candidate) != state.get(
        "candidate_content_sha256"
    ):
        findings.append(
            {"code": "CANDIDATE_HASH_DRIFT", "message": str(candidate)}
        )
    if state.get("active_workpack") and not state.get("active_attempt"):
        findings.append(
            {
                "code": "ACTIVE_WORKPACK_WITHOUT_ATTEMPT",
                "message": str(state["active_workpack"]),
            }
        )
    active_count = 1 if state.get("active_attempt") else 0
    if active_count > 1:
        findings.append(
            {
                "code": "MULTIPLE_ACTIVE_ATTEMPTS",
                "message": str(active_count),
            }
        )
    report["blocking_findings"].extend(findings)
    report["status"] = "FAIL" if findings else "PASS"
    report["valid"] = not findings
    report["candidate_hash_verified"] = not any(
        item["code"] == "CANDIDATE_HASH_DRIFT" for item in findings
    )
    return report


def advance_one(execution_root: str | Path) -> dict[str, Any]:
    root = Path(execution_root).expanduser().resolve()
    store = RuntimeStore(root)
    decision = plan_next(root)
    if decision["decision"] != "ADVANCE":
        if decision["decision"] == "HARD_STOP":
            state = store.load_state()
            if not state.get("hard_stop"):
                reason = decision.get("reason") or {
                    "code": "PLANNING_HARD_STOP",
                    "message": str(decision),
                }
                return _record_hard_stop(
                    store,
                    reason["code"],
                    reason.get("message", str(decision)),
                )
        return {
            "schema_version": "1.0",
            "status": "STOPPED",
            "transition_committed": False,
            "stop": decision,
        }
    state = store.load_state()
    node = next(
        item
        for item in state["control_plan"]["nodes"]
        if item["node_id"] == decision["node_id"]
    )
    try:
        manifest = _load_authorized_manifest(state, node)
        _validate_command_manifest(state, node, manifest)
    except RuntimeViolation as exc:
        return _record_hard_stop(store, exc.code, exc.message)
    attempt_id = f"ATTEMPT-{uuid.uuid4()}"
    try:
        fencing_token, _reserved = store.reserve(
            node["node_id"],
            attempt_id,
            expected_revision=state["revision"],
        )
    except RuntimeError as exc:
        return _record_hard_stop(
            store, "RESERVATION_CONFLICT", str(exc)
        )
    return _execute_attempt(
        store,
        node,
        manifest,
        attempt_id=attempt_id,
        fencing_token=fencing_token,
        resumed=False,
    )


def advance_until_gate(execution_root: str | Path) -> dict[str, Any]:
    root = Path(execution_root).expanduser().resolve()
    transitions: list[dict[str, Any]] = []
    while True:
        decision = plan_next(root)
        if decision["decision"] != "ADVANCE":
            return {
                "schema_version": "1.0",
                "status": "STOPPED_AT_GATE"
                if decision["decision"] == "HUMAN_GATE"
                else "STOPPED",
                "transitions_committed": len(transitions),
                "transitions": transitions,
                "stop": decision,
            }
        result = advance_one(root)
        transitions.append(result)
        if result.get("status") != "PASS":
            return {
                "schema_version": "1.0",
                "status": "STOPPED",
                "transitions_committed": sum(
                    1
                    for item in transitions
                    if item.get("transition_committed")
                ),
                "transitions": transitions,
                "stop": result,
            }


def resume(execution_root: str | Path) -> dict[str, Any]:
    root = Path(execution_root).expanduser().resolve()
    store = RuntimeStore(root)
    state = store.load_state()
    attempt = state.get("active_attempt")
    if not isinstance(attempt, Mapping):
        return {
            "schema_version": "1.0",
            "status": "NO_ACTIVE_ATTEMPT",
            "authorization_created": False,
            "budget_reset": False,
        }
    current = attempt.get("current_command")
    if isinstance(current, Mapping) and current.get("idempotent") is not True:
        return _record_hard_stop(
            store,
            "UNKNOWN_NON_IDEMPOTENT_OUTCOME",
            str(current.get("command_id")),
        )
    node = next(
        (
            item
            for item in state["control_plan"]["nodes"]
            if item["node_id"] == attempt["node_id"]
        ),
        None,
    )
    if node is None:
        return _record_hard_stop(
            store, "ATTEMPT_NODE_MISSING", str(attempt["node_id"])
        )
    try:
        manifest = _load_authorized_manifest(state, node)
        _validate_command_manifest(state, node, manifest)
    except RuntimeViolation as exc:
        return _record_hard_stop(store, exc.code, exc.message)
    return _execute_attempt(
        store,
        node,
        manifest,
        attempt_id=str(attempt["attempt_id"]),
        fencing_token=int(attempt["fencing_token"]),
        resumed=True,
    )


def _execute_attempt(
    store: RuntimeStore,
    node: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    attempt_id: str,
    fencing_token: int,
    resumed: bool,
) -> dict[str, Any]:
    state = store.load_state()
    if not _active_fence_matches(
        state, attempt_id, fencing_token
    ):
        return _record_hard_stop(
            store,
            "STALE_FENCING_TOKEN",
            f"{attempt_id}:{fencing_token}",
        )
    candidate = Path(state["candidate_root"])
    if tree_sha256(candidate) != state["candidate_content_sha256"]:
        return _record_hard_stop(
            store, "CANDIDATE_HASH_DRIFT", str(candidate)
        )
    workpack_steps = _manifest_workpack_steps(node, manifest)
    workpacks = [step["workpack_id"] for step in workpack_steps]

    def hydrated(current: dict[str, Any]) -> None:
        attempt = _require_active_attempt(
            current, attempt_id, fencing_token
        )
        attempt["status"] = "ACTIVE"
        attempt["phase"] = "HYDRATED"
        attempt["resumed"] = resumed
        attempt["manifest_sha256"] = file_sha256(
            lexical_path(
                current["authorization"]["command_manifests"][
                    node["node_id"]
                ]["path"]
            )
        )
        _append_unique(current["touched_nodes"], node["node_id"])

    store.append(
        "ATTEMPT_HYDRATED",
        {
            "attempt_id": attempt_id,
            "node_id": node["node_id"],
            "workpack_ids": workpacks,
            "resumed": resumed,
        },
        mutate=hydrated,
        fencing_token=fencing_token,
    )

    for step in workpack_steps:
        workpack_id = str(step["workpack_id"])
        if workpack_id in store.load_state().get(
            "completed_workpacks", []
        ):
            continue

        def activated(current: dict[str, Any]) -> None:
            attempt = _require_active_attempt(
                current, attempt_id, fencing_token
            )
            current["active_workpack"] = workpack_id
            attempt["workpack_id"] = workpack_id
            attempt["phase"] = "WORKPACK_ACTIVE"

        store.append(
            "WORKPACK_ACTIVATED",
            {
                "attempt_id": attempt_id,
                "node_id": node["node_id"],
                "workpack_id": workpack_id,
            },
            mutate=activated,
            fencing_token=fencing_token,
        )
        stop = _execute_workpack_step(
            store,
            node,
            workpack_id,
            step["commands"],
            attempt_id,
            fencing_token,
        )
        if stop is not None:
            return stop
        _promote_workpack(
            store,
            node,
            workpack_id,
            attempt_id,
            fencing_token,
        )

    return _promote_node(
        store,
        node,
        manifest,
        attempt_id,
        fencing_token,
    )


def _execute_workpack_step(
    store: RuntimeStore,
    node: Mapping[str, Any],
    workpack_id: str,
    command_definitions: list[dict[str, Any]],
    attempt_id: str,
    fencing_token: int,
) -> dict[str, Any] | None:
    commands = [
        deepcopy(command)
        for command in command_definitions
        if isinstance(command, Mapping)
    ]
    execute_commands = [
        command for command in commands if command.get("stage") == "execute"
    ]
    postflight_commands = [
        command
        for command in commands
        if command.get("stage") == "postflight"
    ]
    review_commands = [
        command for command in commands if command.get("stage") == "review"
    ]
    fix_commands = [
        command for command in commands if command.get("stage") == "fix"
    ]
    cleanup_commands = [
        command for command in commands if command.get("stage") == "cleanup"
    ]
    attempt = store.load_state()["active_attempt"]
    current_loop_round = int(attempt.get("loop_round", 0))
    successful_execute = {
        receipt["command_id"]
        for receipt in attempt.get("receipts", [])
        if receipt.get("status") == "PASS"
        and receipt.get("workpack_id") == workpack_id
    }
    successful_current_round = {
        receipt["command_id"]
        for receipt in attempt.get("receipts", [])
        if receipt.get("status") == "PASS"
        and receipt.get("workpack_id") == workpack_id
        and int(receipt.get("loop_round", 0)) == current_loop_round
    }
    failure = _run_command_group(
        store,
        node,
        workpack_id,
        execute_commands,
        attempt_id,
        fencing_token,
        skip_ids=successful_execute,
    )
    while failure is not None:
        current = store.load_state()
        authorization = current["authorization"]
        retryable = (
            failure["error_code"]
            in authorization.get("retryable_error_codes", [])
            and failure.get("side_effect_cleanup_confirmed") is True
        )
        if not retryable:
            return _record_hard_stop(
                store,
                failure["error_code"],
                failure["message"],
                return_path="HUMAN_REVIEW_REQUIRED",
            )
        if not _consume_loop_budget(
            store,
            attempt_id,
            fencing_token,
            reason="TRANSIENT_RETRY",
        ):
            return _record_hard_stop(
                store,
                "LOOP_BUDGET_EXHAUSTED",
                node["node_id"],
                return_path="REQUEST_NEW_EXECUTION_AUTHORIZATION",
            )
        cleanup_failure = _run_command_group(
            store,
            node,
            workpack_id,
            cleanup_commands,
            attempt_id,
            fencing_token,
            skip_ids=set(),
        )
        if cleanup_failure is not None:
            return _record_hard_stop(
                store,
                "RETRY_CLEANUP_FAILED",
                cleanup_failure["message"],
            )
        failure = _run_command_group(
            store,
            node,
            workpack_id,
            execute_commands,
            attempt_id,
            fencing_token,
            skip_ids=set(),
        )

    failure = _run_command_group(
        store,
        node,
        workpack_id,
        postflight_commands,
        attempt_id,
        fencing_token,
        skip_ids=successful_current_round,
    )
    if failure is None:
        failure = _run_read_only_review(
            store,
            node,
            workpack_id,
            review_commands,
            attempt_id,
            fencing_token,
            skip_ids=successful_current_round,
        )
    while failure is not None:
        if failure.get("requires_immediate_hard_stop") is True:
            return _record_hard_stop(
                store,
                str(failure["error_code"]),
                str(failure["message"]),
                return_path="HUMAN_REVIEW_REQUIRED",
            )
        finding = _write_finding(
            store,
            node,
            workpack_id,
            attempt_id,
            fencing_token,
            failure,
        )
        if not fix_commands:
            return _record_hard_stop(
                store,
                "ACCEPTANCE_FINDING_REQUIRES_REPAIR",
                finding["finding_id"],
                return_path="RETURN_TO_FINDING_REPAIR_GATE",
            )
        if not _consume_loop_budget(
            store,
            attempt_id,
            fencing_token,
            reason="FINDING_REPAIR",
        ):
            return _record_hard_stop(
                store,
                "LOOP_BUDGET_EXHAUSTED",
                finding["finding_id"],
                return_path="RETURN_TO_FINDING_REPAIR_GATE",
            )
        before = _write_scope_fingerprint(store.load_state(), node)
        bound_fix_commands = [
            _bind_finding_context(command, store, finding)
            for command in fix_commands
        ]
        fix_failure = _run_command_group(
            store,
            node,
            workpack_id,
            bound_fix_commands,
            attempt_id,
            fencing_token,
            skip_ids=set(),
        )
        if fix_failure is not None:
            return _record_hard_stop(
                store,
                "BOUNDED_FIX_FAILED",
                fix_failure["message"],
                return_path="RETURN_TO_FINDING_REPAIR_GATE",
            )
        after = _write_scope_fingerprint(store.load_state(), node)
        if before == after:
            return _record_hard_stop(
                store,
                "NO_PROGRESS_DETECTED",
                node["node_id"],
                return_path="RETURN_TO_FINDING_REPAIR_GATE",
            )
        failure = _run_command_group(
            store,
            node,
            workpack_id,
            postflight_commands,
            attempt_id,
            fencing_token,
            skip_ids=set(),
        )
        if failure is None:
            failure = _run_read_only_review(
                store,
                node,
                workpack_id,
                review_commands,
                attempt_id,
                fencing_token,
                skip_ids=set(),
            )

    return None


def _run_read_only_review(
    store: RuntimeStore,
    node: Mapping[str, Any],
    workpack_id: str,
    commands: list[dict[str, Any]],
    attempt_id: str,
    fencing_token: int,
    *,
    skip_ids: set[str],
) -> dict[str, Any] | None:
    state = store.load_state()
    attempt = _require_active_attempt(
        state, attempt_id, fencing_token
    )
    loop_round = int(attempt.get("loop_round", 0))
    snapshots = attempt.get("review_scope_snapshots", {})
    snapshot = (
        snapshots.get(workpack_id)
        if isinstance(snapshots, Mapping)
        else None
    )
    if (
        not isinstance(snapshot, Mapping)
        or snapshot.get("loop_round") != loop_round
    ):
        before = _write_scope_fingerprint(state, node)

        def captured(current: dict[str, Any]) -> None:
            current_attempt = _require_active_attempt(
                current, attempt_id, fencing_token
            )
            current_attempt.setdefault(
                "review_scope_snapshots", {}
            )[workpack_id] = {
                "loop_round": loop_round,
                "fingerprint": before,
            }

        store.append(
            "REVIEW_SCOPE_SNAPSHOT_CAPTURED",
            {
                "attempt_id": attempt_id,
                "node_id": node["node_id"],
                "workpack_id": workpack_id,
                "loop_round": loop_round,
                "scope_fingerprint": before,
            },
            mutate=captured,
            fencing_token=fencing_token,
        )
    else:
        before = str(snapshot["fingerprint"])
    failure = _run_command_group(
        store,
        node,
        workpack_id,
        commands,
        attempt_id,
        fencing_token,
        skip_ids=skip_ids,
    )
    after = _write_scope_fingerprint(store.load_state(), node)
    if before != after:
        return {
            "error_code": "REVIEW_MUTATED_TARGET",
            "message": f"{node['node_id']}:{workpack_id}",
            "side_effect_cleanup_confirmed": False,
            "requires_immediate_hard_stop": True,
        }
    return failure


def _bind_finding_context(
    command: Mapping[str, Any],
    store: RuntimeStore,
    finding: Mapping[str, Any],
) -> dict[str, Any]:
    context = {
        "{{HF_FINDING_REF}}": str(
            store.execution_root / str(finding["finding_ref"])
        ),
        "{{HF_FINDING_SHA256}}": str(finding["finding_sha256"]),
    }
    return _replace_tokens(deepcopy(dict(command)), context)


def _replace_tokens(value: Any, context: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        for token, replacement in context.items():
            value = value.replace(token, replacement)
        return value
    if isinstance(value, list):
        return [_replace_tokens(item, context) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_tokens(item, context)
            for key, item in value.items()
        }
    return value


def _run_command_group(
    store: RuntimeStore,
    node: Mapping[str, Any],
    workpack_id: str,
    commands: list[dict[str, Any]],
    attempt_id: str,
    fencing_token: int,
    *,
    skip_ids: set[str],
) -> dict[str, Any] | None:
    for command in commands:
        command_id = str(command["command_id"])
        if command_id in skip_ids:
            continue
        loop_round = int(
            store.load_state()["active_attempt"].get("loop_round", 0)
        )

        def started(state: dict[str, Any]) -> None:
            attempt = _require_active_attempt(
                state, attempt_id, fencing_token
            )
            attempt["phase"] = str(command["stage"]).upper()
            attempt["current_command"] = {
                "command_id": command_id,
                "workpack_id": workpack_id,
                "loop_round": loop_round,
                "idempotent": command.get("idempotent") is True,
                "started_at": utc_now(),
            }

        store.append(
            "COMMAND_STARTED",
            {
                "attempt_id": attempt_id,
                "node_id": node["node_id"],
                "workpack_id": workpack_id,
                "command_id": command_id,
                "stage": command["stage"],
                "loop_round": loop_round,
            },
            mutate=started,
            fencing_token=fencing_token,
        )
        result = _run_command(command)
        receipt = {
            "schema_version": "1.0",
            "attempt_id": attempt_id,
            "node_id": node["node_id"],
            "workpack_id": workpack_id,
            "command_id": command_id,
            "stage": command["stage"],
            "loop_round": loop_round,
            "status": "PASS" if result["passed"] else "FAIL",
            "started_at": result["started_at"],
            "completed_at": utc_now(),
            "executable_realpath": result["executable_realpath"],
            "executable_sha256": result["executable_sha256"],
            "command_definition_sha256": json_sha256(command),
            "exit_code": result.get("exit_code"),
            "timed_out": result.get("timed_out", False),
            "stdout": result.get("stdout", "")[-262144:],
            "stderr": result.get("stderr", "")[-262144:],
            "error_code": result.get("error_code"),
            "side_effect_cleanup_confirmed": command.get(
                "side_effect_cleanup_confirmed", False
            ),
            "fencing_token": fencing_token,
        }
        receipt_ordinal = (
            len(
                store.load_state()["active_attempt"].get(
                    "receipts", []
                )
            )
            + 1
        )
        receipt_path = (
            store.execution_root
            / "evidence/attempts"
            / attempt_id
            / f"{receipt_ordinal:04d}-{command_id}.receipt.json"
        )
        write_json(receipt_path, receipt)
        receipt_hash = file_sha256(receipt_path)
        relative = receipt_path.relative_to(store.execution_root).as_posix()

        def recorded(state: dict[str, Any]) -> None:
            attempt = _require_active_attempt(
                state, attempt_id, fencing_token
            )
            attempt["current_command"] = None
            attempt["receipts"].append(
                {
                    "command_id": command_id,
                    "workpack_id": workpack_id,
                    "stage": command["stage"],
                    "loop_round": loop_round,
                    "status": receipt["status"],
                    "receipt_ref": relative,
                    "receipt_sha256": receipt_hash,
                }
            )
            state["evidence_index"][relative] = receipt_hash

        store.append(
            "COMMAND_RECEIPT_RECORDED",
            {
                "attempt_id": attempt_id,
                "node_id": node["node_id"],
                "workpack_id": workpack_id,
                "command_id": command_id,
                "status": receipt["status"],
                "loop_round": loop_round,
                "receipt_sha256": receipt_hash,
            },
            mutate=recorded,
            fencing_token=fencing_token,
            evidence_sha256=receipt_hash,
        )
        if not result["passed"]:
            return {
                "error_code": result["error_code"],
                "message": (
                    f"{node['node_id']}:{command_id}:"
                    f"{result.get('exit_code')}"
                ),
                "side_effect_cleanup_confirmed": command.get(
                    "side_effect_cleanup_confirmed", False
                ),
            }
    return None


def _run_command(command: Mapping[str, Any]) -> dict[str, Any]:
    executable = Path(str(command["executable_abs"]))
    started_at = utc_now()
    try:
        completed = subprocess.run(
            list(command["argv"]),
            cwd=str(command["cwd_abs"]),
            env=_bounded_environment(command.get("environment", {})),
            capture_output=True,
            text=True,
            timeout=int(command.get("timeout_seconds", 300)),
            shell=False,
            check=False,
        )
        expected = command.get("expected_exit_codes", [0])
        passed = completed.returncode in expected
        return {
            "passed": passed,
            "started_at": started_at,
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "timed_out": False,
            "error_code": (
                None
                if passed
                else command.get(
                    "failure_error_code", "COMMAND_EXIT_NONZERO"
                )
            ),
            "executable_realpath": str(executable.resolve()),
            "executable_sha256": file_sha256(executable),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "passed": False,
            "started_at": started_at,
            "exit_code": None,
            "stdout": _decode_stream(exc.stdout),
            "stderr": _decode_stream(exc.stderr),
            "timed_out": True,
            "error_code": (
                "COMMAND_TIMEOUT"
                if command.get("idempotent") is True
                else "UNKNOWN_NON_IDEMPOTENT_OUTCOME"
            ),
            "executable_realpath": str(executable.resolve()),
            "executable_sha256": file_sha256(executable),
        }
    except OSError as exc:
        return {
            "passed": False,
            "started_at": started_at,
            "exit_code": None,
            "stdout": "",
            "stderr": str(exc),
            "timed_out": False,
            "error_code": (
                "COMMAND_LAUNCH_FAILED"
                if command.get("idempotent") is True
                else "UNKNOWN_NON_IDEMPOTENT_OUTCOME"
            ),
            "executable_realpath": str(executable.resolve()),
            "executable_sha256": file_sha256(executable),
        }


def _validate_command_manifest(
    state: Mapping[str, Any],
    node: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> None:
    authorization = state["authorization"]
    _validate_resolved_manifest(
        state,
        node,
        manifest,
        authorized_write_roots=authorization[
            "allowed_write_roots"
        ],
    )


def _validate_resolved_manifest(
    state: Mapping[str, Any],
    node: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    authorized_write_roots: Iterable[str] | None,
) -> None:
    node_id = node["node_id"]
    if manifest.get("schema_version") != "1.0":
        raise RuntimeViolation(
            "COMMAND_MANIFEST_SCHEMA_UNSUPPORTED",
            str(manifest.get("schema_version")),
        )
    if manifest.get("node_id") != node_id:
        raise RuntimeViolation(
            "COMMAND_MANIFEST_NODE_MISMATCH", node_id
        )
    steps = _manifest_workpack_steps(node, manifest)
    commands = [
        command
        for step in steps
        for command in step["commands"]
    ]
    command_ids = [
        command.get("command_id")
        for command in commands
        if isinstance(command, Mapping)
    ]
    if (
        len(command_ids) != len(commands)
        or any(
            not isinstance(command_id, str) or not command_id
            for command_id in command_ids
        )
        or len(command_ids) != len(set(command_ids))
    ):
        raise RuntimeViolation(
            "COMMAND_IDS_INVALID", node_id
        )
    for step in steps:
        step_commands = step["commands"]
        stages = {
            command.get("stage")
            for command in step_commands
            if isinstance(command, Mapping)
        }
        if not {"execute", "postflight", "review"}.issubset(stages):
            raise RuntimeViolation(
                "WORKPACK_LOOP_STAGES_MISSING",
                f"{step['workpack_id']}:{sorted(stages)}",
            )
        review_commands = [
            command
            for command in step_commands
            if isinstance(command, Mapping)
            and command.get("stage") == "review"
        ]
        if not review_commands or not all(
            command.get("independent_review") is True
            and command.get("review_target_mode") == "READ_ONLY"
            and command.get("allowed_write_roots") == []
            for command in review_commands
        ):
            raise RuntimeViolation(
                "INDEPENDENT_REVIEW_REQUIRED",
                str(step["workpack_id"]),
            )
        reviewer_identities = {
            command.get("executor_identity")
            for command in review_commands
        }
        mutating_identities = {
            command.get("executor_identity")
            for command in step_commands
            if command.get("stage") in {"execute", "fix"}
        }
        if (
            None in reviewer_identities
            or None in mutating_identities
            or reviewer_identities & mutating_identities
        ):
            raise RuntimeViolation(
                "REVIEWER_IDENTITY_NOT_INDEPENDENT",
                str(step["workpack_id"]),
            )
        for command in step_commands:
            if command.get("stage") == "fix" and not (
                _contains_token(command, "{{HF_FINDING_REF}}")
                and _contains_token(command, "{{HF_FINDING_SHA256}}")
            ):
                raise RuntimeViolation(
                    "FIX_FINDING_BINDING_REQUIRED",
                    str(command.get("command_id")),
                )
    authorized_writes = (
        [
            lexical_path(path)
            for path in authorized_write_roots
        ]
        if authorized_write_roots is not None
        else None
    )
    node_writes = [
        lexical_path(path)
        for path in node.get("allowed_write_paths", [])
    ]
    for command in commands:
        if not isinstance(command, Mapping):
            raise RuntimeViolation(
                "COMMAND_DEFINITION_INVALID", node_id
            )
        executable = Path(str(command.get("executable_abs", "")))
        argv = command.get("argv")
        cwd = Path(str(command.get("cwd_abs", "")))
        if (
            not executable.is_absolute()
            or not executable.is_file()
            or not isinstance(argv, list)
            or not argv
            or not all(isinstance(item, str) for item in argv)
            or argv[0] != str(executable)
            or not cwd.is_absolute()
            or not cwd.is_dir()
            or command.get("shell") is not False
            or file_sha256(executable)
            != command.get("executable_sha256")
        ):
            raise RuntimeViolation(
                "COMMAND_RUNTIME_CONTRACT_INVALID",
                str(command.get("command_id")),
            )
        declared_writes = command.get("allowed_write_roots")
        if not isinstance(declared_writes, list):
            raise RuntimeViolation(
                "COMMAND_WRITE_SCOPE_MISSING",
                str(command.get("command_id")),
            )
        for path in declared_writes:
            lexical = lexical_path(path)
            if not lexically_within(
                lexical, state["execution_root"]
            ):
                raise RuntimeViolation(
                    "COMMAND_WRITE_SCOPE_OUTSIDE_EXECUTION_ROOT",
                    str(path),
                )
            if authorized_writes is not None and not any(
                lexically_within(lexical, root)
                for root in authorized_writes
            ):
                raise RuntimeViolation(
                    "COMMAND_WRITE_SCOPE_UNAUTHORIZED", str(path)
                )
            if node_writes and not any(
                lexically_within(lexical, root)
                or lexically_within(root, lexical)
                for root in node_writes
            ):
                raise RuntimeViolation(
                    "COMMAND_WRITE_SCOPE_OUTSIDE_NODE", str(path)
                )
        if not (
            lexically_within(
                cwd.resolve(), Path(state["execution_root"]).resolve()
            )
            or lexically_within(
                cwd.resolve(), Path(state["candidate_root"]).resolve()
            )
        ):
            raise RuntimeViolation(
                "COMMAND_CWD_OUTSIDE_BOUND_ROOTS", str(cwd)
            )
    environment_id = manifest.get("environment_id")
    if environment_id != node.get("environment_id"):
        raise RuntimeViolation(
            "COMMAND_ENVIRONMENT_NODE_MISMATCH",
            str(environment_id),
        )
    if (
        authorized_write_roots is not None
        and environment_id
        not in state["authorization"]["environment_ids"]
    ):
        raise RuntimeViolation(
            "COMMAND_ENVIRONMENT_UNAUTHORIZED", str(environment_id)
        )


def _load_authorized_manifest(
    state: Mapping[str, Any], node: Mapping[str, Any]
) -> dict[str, Any]:
    authorization = state.get("authorization")
    issue = _authorization_issue(state, node, authorization)
    if issue:
        raise RuntimeViolation(issue["code"], issue["message"])
    binding = authorization["command_manifests"][node["node_id"]]
    path = lexical_path(binding["path"])
    if (
        not lexically_within(path, state["execution_root"])
        or not path.is_file()
        or file_sha256(path) != binding["sha256"]
    ):
        raise RuntimeViolation(
            "COMMAND_MANIFEST_HASH_DRIFT", node["node_id"]
        )
    return read_json(path)


def _promote_workpack(
    store: RuntimeStore,
    node: Mapping[str, Any],
    workpack_id: str,
    attempt_id: str,
    fencing_token: int,
) -> dict[str, Any]:
    state = store.load_state()
    attempt = _require_active_attempt(
        state, attempt_id, fencing_token
    )
    receipt_hashes = [
        receipt["receipt_sha256"]
        for receipt in attempt.get("receipts", [])
        if receipt.get("workpack_id") == workpack_id
    ]
    result = {
        "schema_version": "1.0",
        "attempt_id": attempt_id,
        "node_id": node["node_id"],
        "workpack_id": workpack_id,
        "receipt_hashes": receipt_hashes,
        "fencing_token": fencing_token,
        "postflight": "PASS",
        "independent_review": "PASS",
        "promotion": "PASS",
    }
    node_key = json_sha256({"node_id": node["node_id"]})[:16]
    workpack_key = json_sha256({"workpack_id": workpack_id})[:16]
    result_path = (
        store.execution_root
        / "evidence/promotions/workpacks"
        / f"{node_key}-{workpack_key}.result.json"
    )
    write_json(result_path, result)
    result_hash = file_sha256(result_path)
    relative = result_path.relative_to(store.execution_root).as_posix()

    def promoted(current: dict[str, Any]) -> None:
        current_attempt = _require_active_attempt(
            current, attempt_id, fencing_token
        )
        if current.get("active_workpack") != workpack_id:
            raise RuntimeViolation(
                "ACTIVE_WORKPACK_MISMATCH", workpack_id
            )
        _append_unique(
            current.setdefault("completed_workpacks", []),
            workpack_id,
        )
        current["active_workpack"] = None
        current_attempt["workpack_id"] = None
        current_attempt["phase"] = "WORKPACK_PROMOTED"
        current["evidence_index"][relative] = result_hash

    store.append(
        "WORKPACK_PROMOTED",
        {
            "attempt_id": attempt_id,
            "node_id": node["node_id"],
            "workpack_id": workpack_id,
            "result_sha256": result_hash,
        },
        mutate=promoted,
        fencing_token=fencing_token,
        evidence_sha256=result_hash,
    )
    return {
        "schema_version": "1.0",
        "status": "PASS",
        "node_id": node["node_id"],
        "workpack_id": workpack_id,
        "evidence_sha256": result_hash,
    }


def _promote_node(
    store: RuntimeStore,
    node: Mapping[str, Any],
    manifest: Mapping[str, Any],
    attempt_id: str,
    fencing_token: int,
) -> dict[str, Any]:
    state = store.load_state()
    _require_active_attempt(state, attempt_id, fencing_token)
    result = {
        "schema_version": "1.0",
        "attempt_id": attempt_id,
        "node_id": node["node_id"],
        "workpack_ids": _node_workpacks(node),
        "manifest_sha256": json_sha256(manifest),
        "receipt_hashes": [
            item["receipt_sha256"]
            for item in state["active_attempt"]["receipts"]
        ],
        "fencing_token": fencing_token,
        "postflight": "PASS",
        "independent_review": "PASS",
        "promotion": "PASS",
    }
    result_path = (
        store.execution_root
        / "evidence/promotions"
        / f"{node['node_id']}.result.json"
    )
    write_json(result_path, result)
    result_hash = file_sha256(result_path)
    relative = result_path.relative_to(store.execution_root).as_posix()

    def promoted(current: dict[str, Any]) -> None:
        _require_active_attempt(current, attempt_id, fencing_token)
        _append_unique(current["completed_nodes"], node["node_id"])
        _append_unique(current["touched_nodes"], node["node_id"])
        _append_unique(current["locally_closed_nodes"], node["node_id"])
        current["transitions_used"] += 1
        current["authorization"]["transitions_used"] = (
            current["authorization"].get("transitions_used", 0) + 1
        )
        current["active_attempt"] = None
        current["active_workpack"] = None
        current["evidence_index"][relative] = result_hash
        fingerprint = json_sha256(
            {
                "completed_nodes": current["completed_nodes"],
                "locally_closed_nodes": current["locally_closed_nodes"],
            }
        )
        current["state_path_history"].append(fingerprint)
        current["state_path_history"] = current["state_path_history"][-6:]

    final_state = store.append(
        "NODE_PROMOTED",
        {
            "attempt_id": attempt_id,
            "node_id": node["node_id"],
            "result_sha256": result_hash,
        },
        mutate=promoted,
        fencing_token=fencing_token,
        evidence_sha256=result_hash,
    )["state"]
    return {
        "schema_version": "1.0",
        "status": "PASS",
        "transition_committed": True,
        "node_id": node["node_id"],
        "workpack_ids": _node_workpacks(node),
        "attempt_id": attempt_id,
        "fencing_token": fencing_token,
        "evidence_sha256": result_hash,
        "transitions_used": final_state["transitions_used"],
    }


def _write_finding(
    store: RuntimeStore,
    node: Mapping[str, Any],
    workpack_id: str,
    attempt_id: str,
    fencing_token: int,
    failure: Mapping[str, Any],
) -> dict[str, Any]:
    finding = {
        "schema_version": "1.0",
        "finding_id": f"FINDING-{uuid.uuid4()}",
        "attempt_id": attempt_id,
        "node_id": node["node_id"],
        "workpack_id": workpack_id,
        "error_code": failure["error_code"],
        "message": failure["message"],
        "classification": "ACCEPTANCE_FAILURE_NOT_RETRY",
        "return_path": "RETURN_TO_FINDING_REPAIR_GATE",
        "fencing_token": fencing_token,
    }
    path = (
        store.execution_root
        / "evidence/findings"
        / f"{finding['finding_id']}.json"
    )
    write_json(path, finding)
    finding_hash = file_sha256(path)
    relative = path.relative_to(store.execution_root).as_posix()
    finding["finding_ref"] = relative
    finding["finding_sha256"] = finding_hash

    def mutation(state: dict[str, Any]) -> None:
        attempt = _require_active_attempt(
            state, attempt_id, fencing_token
        )
        attempt.setdefault("findings", []).append(
            {
                "finding_id": finding["finding_id"],
                "workpack_id": workpack_id,
                "finding_ref": relative,
                "finding_sha256": finding_hash,
            }
        )
        state["evidence_index"][relative] = finding_hash

    store.append(
        "ACCEPTANCE_FINDING_RECORDED",
        {
            "attempt_id": attempt_id,
            "node_id": node["node_id"],
            "workpack_id": workpack_id,
            "finding_id": finding["finding_id"],
            "finding_sha256": finding_hash,
        },
        mutate=mutation,
        fencing_token=fencing_token,
        evidence_sha256=finding_hash,
    )
    return finding


def _consume_loop_budget(
    store: RuntimeStore,
    attempt_id: str,
    fencing_token: int,
    *,
    reason: str,
) -> bool:
    state = store.load_state()
    authorization = state["authorization"]
    if authorization.get("loop_rounds_used", 0) >= authorization.get(
        "max_loop_rounds", 0
    ):
        return False

    def mutation(current: dict[str, Any]) -> None:
        attempt = _require_active_attempt(
            current, attempt_id, fencing_token
        )
        attempt["loop_round"] = attempt.get("loop_round", 0) + 1
        current["loop_rounds_used"] += 1
        current["authorization"]["loop_rounds_used"] = (
            current["authorization"].get("loop_rounds_used", 0) + 1
        )

    store.append(
        "LOOP_BUDGET_CONSUMED",
        {
            "attempt_id": attempt_id,
            "reason": reason,
        },
        mutate=mutation,
        fencing_token=fencing_token,
    )
    return True


def _record_hard_stop(
    store: RuntimeStore,
    code: str,
    message: str,
    *,
    return_path: str | None = None,
) -> dict[str, Any]:
    chosen_return = return_path or _return_path_for(code)
    stop = {
        "schema_version": "1.0",
        "hard_stop_id": f"HARD-STOP-{uuid.uuid4()}",
        "code": code,
        "message": message,
        "recorded_at": utc_now(),
        "return_path": chosen_return,
    }

    def mutation(state: dict[str, Any]) -> None:
        state["hard_stop"] = stop
        state["active_attempt"] = None
        state["active_workpack"] = None
        state["effective_mode"] = "A1_PLAN_ONLY"
        state["next_human_gate"] = chosen_return

    store.append(
        "HARD_STOP_RECORDED",
        stop,
        mutate=mutation,
    )
    return {
        "schema_version": "1.0",
        "status": "HARD_STOP",
        "transition_committed": False,
        "hard_stop": stop,
        "unique_return_path": chosen_return,
    }


def _return_path_for(code: str) -> str:
    if "AUTHORIZATION" in code or "BUDGET" in code:
        return "REQUEST_NEW_EXECUTION_AUTHORIZATION"
    if "HASH" in code:
        return "REBUILD_HANDOFF_OR_MIGRATION_PLAN"
    if "FINDING" in code or "PROGRESS" in code or "OSCILLATION" in code:
        return "RETURN_TO_FINDING_REPAIR_GATE"
    if "UNKNOWN_NON_IDEMPOTENT" in code:
        return "HUMAN_OUTCOME_RECONCILIATION"
    return "HUMAN_REVIEW_REQUIRED"


def _require_active_attempt(
    state: Mapping[str, Any],
    attempt_id: str,
    fencing_token: int,
) -> dict[str, Any]:
    attempt = state.get("active_attempt")
    if not isinstance(attempt, dict):
        raise RuntimeViolation(
            "ACTIVE_ATTEMPT_MISSING", attempt_id
        )
    if (
        attempt.get("attempt_id") != attempt_id
        or int(attempt.get("fencing_token", -1)) != fencing_token
    ):
        raise RuntimeViolation(
            "STALE_FENCING_TOKEN",
            f"{attempt_id}:{fencing_token}",
        )
    return attempt


def _active_fence_matches(
    state: Mapping[str, Any], attempt_id: str, fencing_token: int
) -> bool:
    try:
        _require_active_attempt(state, attempt_id, fencing_token)
        return True
    except RuntimeViolation:
        return False


def _write_scope_fingerprint(
    state: Mapping[str, Any], node: Mapping[str, Any]
) -> str:
    digest_input = []
    for value in node.get("allowed_write_paths", []):
        path = Path(str(value))
        if path.is_dir():
            digest_input.append((str(path), tree_sha256(path)))
        elif path.is_file():
            digest_input.append((str(path), file_sha256(path)))
        else:
            digest_input.append((str(path), None))
    return json_sha256(digest_input)


def _bounded_environment(extra: Any) -> dict[str, str]:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", ""),
    }
    if isinstance(extra, Mapping):
        for key, value in extra.items():
            if (
                isinstance(key, str)
                and isinstance(value, str)
                and key not in {"HOME", "CODEX_HOME"}
            ):
                environment[key] = value
    return environment


def _decode_stream(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _validate_bootstrap_bundle(
    bundle: Mapping[str, Any], confirmation_text: str
) -> None:
    excluded = {
        "bundle_sha256",
        "confirmation_text",
        "status",
        "writes_performed",
    }
    body = {key: value for key, value in bundle.items() if key not in excluded}
    bundle_hash = json_sha256(body)
    expected = (
        f"APPROVE_BOOTSTRAP_BUNDLE::{bundle.get('bundle_id')}::{bundle_hash}"
    )
    if bundle.get("bundle_sha256") != bundle_hash:
        raise RuntimeViolation(
            "BOOTSTRAP_BUNDLE_HASH_MISMATCH", str(bundle.get("bundle_id"))
        )
    if confirmation_text != expected:
        raise RuntimeViolation(
            "CONFIRMATION_TEXT_MISMATCH", "bootstrap bundle"
        )
    findings = validate_handoff_document(bundle.get("handoff", {}))
    if findings:
        raise RuntimeViolation(
            findings[0]["code"], findings[0]["message"]
        )
    children = bundle.get("child_authorizations")
    if not isinstance(children, list) or len(children) != 5:
        raise RuntimeViolation(
            "BOOTSTRAP_CHILD_AUTHORIZATIONS_INVALID", "expected five"
        )
    for child in children:
        child_body = {
            key: value
            for key, value in child.items()
            if key != "authorization_sha256"
        }
        if child.get("authorization_sha256") != json_sha256(child_body):
            raise RuntimeViolation(
                "BOOTSTRAP_CHILD_HASH_MISMATCH",
                str(child.get("authorization_kind")),
            )


def _load_control_plan(candidate: Path) -> dict[str, Any]:
    dag = read_json(candidate / "ENGINEERING_PROJECT_DAG.json")
    release = read_json(candidate / "RELEASE_PIPELINE_MANIFEST.json")
    nodes = [deepcopy(item) for item in dag.get("nodes", [])]
    engineering_tail = nodes[-1]["node_id"] if nodes else None
    for index, step in enumerate(release.get("steps", [])):
        node = deepcopy(step)
        node["node_id"] = step["step_id"]
        node["required_predecessor_nodes"] = (
            [engineering_tail]
            if index == 0 and engineering_tail
            else list(step.get("required_predecessor_step_ids", []))
        )
        node["workpack_id"] = step.get("project_workpack_id")
        node["project_workpack_sequence"] = []
        node["allowed_write_paths"] = list(
            step.get("allowed_write_paths", [])
        )
        node["environment_id"] = step.get("environment_id")
        node["human_gate"] = step.get("human_gate", False)
        node["human_gate_id"] = (
            step["step_id"] if step.get("human_gate") else None
        )
        node["auto_advance_eligible"] = not step.get("human_gate", False)
        node["plan_source"] = "RELEASE_PIPELINE"
        nodes.append(node)
    ids = [node.get("node_id") for node in nodes]
    if not ids or len(ids) != len(set(ids)):
        raise RuntimeViolation(
            "CONTROL_PLAN_NODE_IDS_INVALID", str(ids)
        )
    return {
        "schema_version": "1.0",
        "engineering_dag_sha256": file_sha256(
            candidate / "ENGINEERING_PROJECT_DAG.json"
        ),
        "release_pipeline_sha256": file_sha256(
            candidate / "RELEASE_PIPELINE_MANIFEST.json"
        ),
        "nodes": nodes,
    }


def _unique_next_node(state: Mapping[str, Any]) -> dict[str, Any] | None:
    completed = set(state.get("completed_nodes", []))
    eligible = []
    for node in state.get("control_plan", {}).get("nodes", []):
        node_id = node["node_id"]
        if node_id in completed:
            continue
        predecessors = set(node.get("required_predecessor_nodes", []))
        if predecessors.issubset(completed):
            eligible.append(node)
    if not eligible:
        remaining = [
            node["node_id"]
            for node in state.get("control_plan", {}).get("nodes", [])
            if node["node_id"] not in completed
        ]
        if remaining:
            raise RuntimeViolation(
                "NO_UNIQUE_LEGAL_SUCCESSOR", str(remaining)
            )
        return None
    if len(eligible) != 1:
        raise RuntimeViolation(
            "AMBIGUOUS_LEGAL_SUCCESSOR",
            str([node["node_id"] for node in eligible]),
        )
    return eligible[0]


def _authorization_issue(
    state: Mapping[str, Any],
    node: Mapping[str, Any],
    authorization: Mapping[str, Any] | None,
) -> dict[str, str] | None:
    if not isinstance(authorization, Mapping):
        return {
            "code": "AUTHORIZATION_MISSING",
            "message": "A3_PROGRAM_BOUNDED is required",
        }
    status_value = authorization.get("status")
    if status_value == "REVOKED":
        return {
            "code": "AUTHORIZATION_REVOKED",
            "message": str(authorization.get("authorization_id")),
        }
    if status_value != "ACTIVE":
        return {
            "code": "AUTHORIZATION_INACTIVE",
            "message": str(status_value),
        }
    if parse_utc(str(authorization.get("expires_at"))) <= datetime.now(
        timezone.utc
    ):
        return {
            "code": "AUTHORIZATION_EXPIRED",
            "message": str(authorization.get("authorization_id")),
        }
    activated_at = authorization.get("activated_at")
    if activated_at:
        elapsed = (
            datetime.now(timezone.utc) - parse_utc(str(activated_at))
        ).total_seconds()
        if elapsed >= int(authorization.get("max_wall_time_seconds", 0)):
            return {
                "code": "AUTHORIZATION_WALL_TIME_EXHAUSTED",
                "message": str(authorization.get("authorization_id")),
            }
    if (
        authorization.get("program_id") != state.get("program_id")
        or authorization.get("epoch_id") != state.get("epoch_id")
        or authorization.get("candidate_content_sha256")
        != state.get("candidate_content_sha256")
    ):
        return {
            "code": "AUTHORIZATION_BINDING_MISMATCH",
            "message": str(authorization.get("authorization_id")),
        }
    node_id = node["node_id"]
    if node_id not in authorization.get("dag_node_ids", []):
        return {
            "code": "AUTHORIZATION_NODE_SCOPE_MISMATCH",
            "message": node_id,
        }
    workpacks = set(_node_workpacks(node))
    if not workpacks.issubset(
        set(authorization.get("workpack_ids", []))
    ):
        return {
            "code": "AUTHORIZATION_WORKPACK_SCOPE_MISMATCH",
            "message": str(sorted(workpacks)),
        }
    if node_id not in authorization.get("command_manifests", {}):
        return {
            "code": "COMMAND_MANIFEST_NOT_AUTHORIZED",
            "message": node_id,
        }
    if authorization.get("transitions_used", 0) >= authorization.get(
        "max_transitions", 0
    ):
        return {
            "code": "TRANSITION_BUDGET_EXHAUSTED",
            "message": node_id,
        }
    if authorization.get("loop_rounds_used", 0) > authorization.get(
        "max_loop_rounds", 0
    ):
        return {
            "code": "LOOP_BUDGET_EXHAUSTED",
            "message": node_id,
        }
    return None


def _node_workpacks(node: Mapping[str, Any]) -> list[str]:
    values = []
    if node.get("workpack_id"):
        values.append(str(node["workpack_id"]))
    values.extend(str(item) for item in node.get("project_workpack_sequence", []))
    return list(dict.fromkeys(values))


def _manifest_workpack_steps(
    node: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    expected = _node_workpacks(node) or [f"PIPELINE:{node['node_id']}"]
    steps = manifest.get("workpack_steps")
    if steps is None:
        commands = manifest.get("commands")
        if len(expected) != 1:
            raise RuntimeViolation(
                "WORKPACK_STEPS_REQUIRED",
                str(node["node_id"]),
            )
        if not isinstance(commands, list) or not commands:
            raise RuntimeViolation(
                "COMMAND_MANIFEST_EMPTY",
                str(node["node_id"]),
            )
        return [{"workpack_id": expected[0], "commands": commands}]
    if not isinstance(steps, list) or not steps:
        raise RuntimeViolation(
            "WORKPACK_STEPS_INVALID",
            str(node["node_id"]),
        )
    actual = [
        step.get("workpack_id")
        for step in steps
        if isinstance(step, Mapping)
    ]
    if len(actual) != len(steps) or actual != expected:
        raise RuntimeViolation(
            "WORKPACK_SEQUENCE_MISMATCH",
            f"expected={expected}, actual={actual}",
        )
    normalized = []
    for step in steps:
        commands = step.get("commands")
        if not isinstance(commands, list) or not commands:
            raise RuntimeViolation(
                "COMMAND_MANIFEST_EMPTY",
                str(step.get("workpack_id")),
            )
        normalized.append(
            {
                "workpack_id": str(step["workpack_id"]),
                "commands": commands,
            }
        )
    return normalized


def _contains_token(value: Any, token: str) -> bool:
    if isinstance(value, str):
        return token in value
    if isinstance(value, list):
        return any(_contains_token(item, token) for item in value)
    if isinstance(value, Mapping):
        return any(_contains_token(item, token) for item in value.values())
    return False


def _append_unique(values: list[Any], value: Any) -> None:
    if value not in values:
        values.append(value)
