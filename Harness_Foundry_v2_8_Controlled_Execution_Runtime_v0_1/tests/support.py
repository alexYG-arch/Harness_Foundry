"""Synthetic, side-effect-contained runtime fixtures."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any

from harness_foundry_runtime.engine import (
    authorization_apply,
    authorization_plan,
    bootstrap_apply,
    bootstrap_plan,
    register_command_overlays,
)
from harness_foundry_runtime.util import (
    file_sha256,
    json_sha256,
    read_json,
    tree_sha256,
    write_json,
)


BOOTSTRAP_NODES = [
    "START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW",
    "START_PACKAGE_HUMAN_APPROVAL",
    "SHARED_CONTROL_BASELINE_LOCK",
    "CONTROL_PLANE_REGISTRATION",
    "PROGRAM_DRIVER_RUNTIME_VERIFIED",
]


class SyntheticRuntime:
    def __init__(
        self,
        root: Path,
        *,
        include_p3: bool = False,
        multi_workpack: bool = False,
    ):
        self.root = root
        self.candidate = root / "candidate"
        self.execution = root / "execution"
        self.workspace = self.execution / "workspace"
        self.bundle_path = root / "BOOTSTRAP_APPROVAL_BUNDLE.json"
        self.authorization_path = root / "EXECUTION_AUTHORIZATION.json"
        self.handoff_path = root / "EXECUTION_HANDOFF.json"
        self.program_id = "PROGRAM-GENERIC-RUNTIME-TEST"
        self.include_p3 = include_p3
        self.multi_workpack = multi_workpack
        self.node_ids = ["NODE_A", "NODE_B"]
        if include_p3:
            self.node_ids = ["MAIN_P3_C3_OR_APPROVED_NA"]
        self._make_candidate()
        self._make_handoff()

    def _make_candidate(self) -> None:
        self.candidate.mkdir(parents=True)
        (self.candidate / "PROGRAM_CHARTER.md").write_text(
            "# Synthetic Charter\n", encoding="utf-8"
        )
        write_json(
            self.candidate / "PROFILE_LOCK.json",
            {"schema_version": "1.0", "profile": "FULL"},
        )
        for name in (
            "FACTORY_PROVENANCE.json",
            "PROGRAM_STATE.json",
            "PROGRAM_DRIVER_STATE.json",
            "EXECUTION_AUTHORIZATION.json",
            "START_CONTEXT.json",
        ):
            write_json(
                self.candidate / name,
                {
                    "schema_version": "1.0",
                    "program_id": self.program_id,
                },
            )
        nodes = []
        predecessor = None
        for index, node_id in enumerate(BOOTSTRAP_NODES):
            nodes.append(
                {
                    "node_id": node_id,
                    "required_predecessor_nodes": (
                        [predecessor] if predecessor else []
                    ),
                    "workpack_id": None,
                    "project_workpack_sequence": [],
                    "allowed_write_paths": [],
                    "environment_id": "BOOTSTRAP",
                    "human_gate": index == 1,
                    "human_gate_id": node_id if index == 1 else None,
                }
            )
            predecessor = node_id
        for node_id in self.node_ids:
            is_multi = self.multi_workpack and node_id == "NODE_A"
            nodes.append(
                {
                    "node_id": node_id,
                    "required_predecessor_nodes": [predecessor],
                    "workpack_id": (
                        None if is_multi else f"WP-{node_id}"
                    ),
                    "project_workpack_sequence": (
                        ["WP-NODE_A-1", "WP-NODE_A-2"]
                        if is_multi
                        else []
                    ),
                    "allowed_write_paths": [str(self.workspace)],
                    "allowed_read_paths": [
                        str(self.candidate.resolve())
                    ],
                    "environment_id": "TEST-ENV",
                    "human_gate": False,
                    "human_gate_id": None,
                    "auto_advance_eligible": True,
                }
            )
            predecessor = node_id
        if not self.include_p3:
            nodes.append(
                {
                    "node_id": "WAIT_REAL_TARGET_INSTALL_AUTHORIZATION",
                    "required_predecessor_nodes": [predecessor],
                    "workpack_id": None,
                    "project_workpack_sequence": [],
                    "allowed_write_paths": [],
                    "environment_id": "INSTALL-ENV",
                    "human_gate": True,
                    "human_gate_id": "WAIT_REAL_TARGET_INSTALL_AUTHORIZATION",
                }
            )
        write_json(
            self.candidate / "ENGINEERING_PROJECT_DAG.json",
            {
                "schema_version": "1.0",
                "program_id": self.program_id,
                "nodes": nodes,
            },
        )
        write_json(
            self.candidate / "RELEASE_PIPELINE_MANIFEST.json",
            {"schema_version": "1.0", "steps": []},
        )

    def _make_handoff(self) -> None:
        body = {
            "schema_version": "1.0",
            "handoff_kind": "HF28_STATIC_CANDIDATE_TO_CONTROLLED_RUNTIME",
            "program_id": self.program_id,
            "candidate_root": str(self.candidate),
            "execution_root": str(self.execution),
            "candidate_content_sha256": tree_sha256(self.candidate),
            "requirement_ir_sha256": "1" * 64,
            "spec_content_sha256": "2" * 64,
            "charter_sha256": file_sha256(
                self.candidate / "PROGRAM_CHARTER.md"
            ),
            "profile_lock_sha256": file_sha256(
                self.candidate / "PROFILE_LOCK.json"
            ),
            "automation_profile": {
                "schema_version": "1.0",
                "requested_level": "A3_PROGRAM_BOUNDED",
                "activation_default": "DISABLED",
                "max_transitions": 8,
                "max_loop_rounds": 3,
                "max_wall_time_seconds": 3600,
                "stop_gate": "WAIT_REAL_TARGET_INSTALL_AUTHORIZATION",
                "retryable_error_codes": [
                    "TEMPORARY_EXTERNAL_FAILURE"
                ],
                "mandatory_human_gate_ids": [
                    "WAIT_REAL_TARGET_INSTALL_AUTHORIZATION"
                ],
                "real_target_install_excluded": True,
            },
            "authoring_terminal_state": (
                "START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW"
            ),
            "next_runtime_action": "BOOTSTRAP_PLAN",
            "execution_authorization_inherited": False,
            "real_target_install_authorization_inherited": False,
        }
        write_json(
            self.handoff_path,
            {
                **body,
                "handoff_sha256": json_sha256(body),
                "status": "PASS",
                "writes_performed": False,
                "commands_executed": False,
            },
        )

    def bootstrap(self) -> dict[str, Any]:
        bundle = bootstrap_plan(self.handoff_path, self.execution)
        write_json(self.bundle_path, bundle)
        return bootstrap_apply(
            self.bundle_path, bundle["confirmation_text"]
        )

    def command(
        self,
        command_id: str,
        stage: str,
        code: str,
        *,
        independent_review: bool = False,
        failure_error_code: str = "COMMAND_EXIT_NONZERO",
        cleanup_confirmed: bool = False,
        idempotent: bool = True,
    ) -> dict[str, Any]:
        executable = Path(sys.executable)
        is_review = stage == "review"
        return {
            "command_id": command_id,
            "stage": stage,
            "executable_abs": str(executable),
            "executable_sha256": file_sha256(executable),
            "argv": [str(executable), "-c", code],
            "cwd_abs": str(self.workspace),
            "allowed_read_roots": [
                str(self.candidate.resolve()),
                str(self.workspace),
            ],
            "allowed_write_roots": (
                [] if is_review else [str(self.workspace)]
            ),
            "environment": {},
            "expected_exit_codes": [0],
            "timeout_seconds": 5,
            "shell": False,
            "idempotent": idempotent,
            "independent_review": independent_review,
            "executor_identity": (
                "INDEPENDENT_REVIEWER"
                if is_review
                else "WORKPACK_EXECUTOR"
            ),
            "review_target_mode": (
                "READ_ONLY" if is_review else "NOT_APPLICABLE"
            ),
            "failure_error_code": failure_error_code,
            "side_effect_cleanup_confirmed": cleanup_confirmed,
        }

    def make_manifest(
        self,
        node_id: str,
        *,
        mode: str = "pass",
    ) -> Path:
        marker = self.workspace / f"{node_id}.marker"
        repaired = self.workspace / f"{node_id}.repaired"
        self.workspace.mkdir(parents=True, exist_ok=True)
        execute_code = (
            "from pathlib import Path;"
            f"Path({str(marker)!r}).write_text('ok')"
        )
        postflight_code = (
            "from pathlib import Path;"
            f"raise SystemExit(0 if Path({str(marker)!r}).is_file() else 9)"
        )
        review_code = postflight_code
        commands = [
            self.command(f"{node_id}-EXECUTE", "execute", execute_code),
            self.command(
                f"{node_id}-POSTFLIGHT", "postflight", postflight_code
            ),
            self.command(
                f"{node_id}-REVIEW",
                "review",
                review_code,
                independent_review=True,
            ),
        ]
        if mode == "retry":
            transient = self.workspace / f"{node_id}.transient"
            transient_code = (
                "from pathlib import Path;"
                f"p=Path({str(transient)!r});"
                "exists=p.exists();"
                "p.write_text('seen');"
                "raise SystemExit(0 if exists else 75)"
            )
            commands[0] = self.command(
                f"{node_id}-EXECUTE",
                "execute",
                transient_code,
                failure_error_code="TEMPORARY_EXTERNAL_FAILURE",
                cleanup_confirmed=True,
            )
            commands.insert(
                1,
                self.command(
                    f"{node_id}-CLEANUP",
                    "cleanup",
                    "raise SystemExit(0)",
                ),
            )
            commands[2] = self.command(
                f"{node_id}-POSTFLIGHT",
                "postflight",
                (
                    "from pathlib import Path;"
                    f"raise SystemExit(0 if Path({str(transient)!r}).is_file() else 9)"
                ),
            )
            commands[3] = self.command(
                f"{node_id}-REVIEW",
                "review",
                (
                    "from pathlib import Path;"
                    f"raise SystemExit(0 if Path({str(transient)!r}).is_file() else 9)"
                ),
                independent_review=True,
            )
        elif mode == "review_mutates":
            review_output = self.workspace / f"{node_id}.review-write"
            commands[2] = self.command(
                f"{node_id}-REVIEW",
                "review",
                (
                    "from pathlib import Path;"
                    f"Path({str(review_output)!r}).write_text('forbidden')"
                ),
                independent_review=True,
            )
        elif mode in {"repair", "no_progress"}:
            needs_repair = (
                "from pathlib import Path;"
                f"raise SystemExit(0 if Path({str(repaired)!r}).is_file() else 8)"
            )
            commands[1] = self.command(
                f"{node_id}-POSTFLIGHT", "postflight", needs_repair
            )
            commands[2] = self.command(
                f"{node_id}-REVIEW",
                "review",
                needs_repair,
                independent_review=True,
            )
            fix_code = (
                "import hashlib,os;"
                "from pathlib import Path;"
                "p=Path(os.environ['HF_FINDING_REF']);"
                "assert p.is_file();"
                "assert hashlib.sha256(p.read_bytes()).hexdigest()=="
                "os.environ['HF_FINDING_SHA256'];"
                f"Path({str(repaired)!r}).write_text('fixed')"
                if mode == "repair"
                else "raise SystemExit(0)"
            )
            commands.append(
                self.command(f"{node_id}-FIX", "fix", fix_code)
            )
            commands[-1]["environment"] = {
                "HF_FINDING_REF": "{{HF_FINDING_REF}}",
                "HF_FINDING_SHA256": "{{HF_FINDING_SHA256}}",
            }
        manifest = {
            "schema_version": "1.0",
            "node_id": node_id,
            "environment_id": "TEST-ENV",
            "commands": commands,
        }
        path = (
            self.execution
            / "control_plane/resolved_commands"
            / f"{node_id}.json"
        )
        write_json(path, manifest)
        return path

    def authorize(
        self,
        *,
        node_ids: list[str] | None = None,
        modes: dict[str, str] | None = None,
        max_transitions: int = 8,
        max_loop_rounds: int = 3,
    ) -> dict[str, Any]:
        selected = node_ids or self.node_ids
        modes = modes or {}
        manifests = self.register_overlays(
            node_ids=selected, modes=modes
        )
        return self.apply_authorization(
            manifests,
            node_ids=selected,
            max_transitions=max_transitions,
            max_loop_rounds=max_loop_rounds,
        )

    def apply_authorization(
        self,
        manifests: dict[str, dict[str, str]],
        *,
        node_ids: list[str],
        max_transitions: int = 8,
        max_loop_rounds: int = 3,
    ) -> dict[str, Any]:
        selected = node_ids
        state = read_json(
            self.execution
            / "control_plane/state/PROGRAM_DRIVER_STATE.json"
        )
        nodes = {
            node["node_id"]: node
            for node in state["control_plan"]["nodes"]
        }
        workpack_ids = []
        for node_id in selected:
            node = nodes[node_id]
            if node.get("workpack_id"):
                workpack_ids.append(node["workpack_id"])
            workpack_ids.extend(node.get("project_workpack_sequence", []))
        request = {
            "level": "A3_PROGRAM_BOUNDED",
            "dag_node_ids": selected,
            "workpack_ids": workpack_ids,
            "command_manifests": manifests,
            "allowed_write_roots": [str(self.workspace)],
            "environment_ids": ["TEST-ENV"],
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(hours=1)
            )
            .isoformat()
            .replace("+00:00", "Z"),
            "max_transitions": max_transitions,
            "max_loop_rounds": max_loop_rounds,
            "max_wall_time_seconds": 600,
        }
        request_path = self.root / "AUTHORIZATION_REQUEST.json"
        write_json(request_path, request)
        authorization = authorization_plan(
            self.execution, request_path
        )
        write_json(self.authorization_path, authorization)
        return authorization_apply(
            self.execution,
            self.authorization_path,
            authorization["confirmation_text"],
        )

    def register_overlays(
        self,
        *,
        node_ids: list[str] | None = None,
        modes: dict[str, str] | None = None,
    ) -> dict[str, dict[str, str]]:
        selected = node_ids or self.node_ids
        modes = modes or {}
        overlay_documents = {}
        for node_id in selected:
            path = self.make_manifest(
                node_id, mode=modes.get(node_id, "pass")
            )
            overlay_documents[node_id] = read_json(path)
        state = read_json(
            self.execution
            / "control_plane/state/PROGRAM_DRIVER_STATE.json"
        )
        overlay_path = self.root / "COMMAND_OVERLAY_BUNDLE.json"
        write_json(
            overlay_path,
            {
                "schema_version": "1.0",
                "overlay_kind": "RESOLVED_COMMAND_OVERLAY_BUNDLE",
                "program_id": self.program_id,
                "epoch_id": state["epoch_id"],
                "candidate_content_sha256": (
                    state["candidate_content_sha256"]
                ),
                "manifests": overlay_documents,
            },
        )
        manifests = register_command_overlays(
            self.execution, overlay_path
        )["command_manifests"]
        return manifests
