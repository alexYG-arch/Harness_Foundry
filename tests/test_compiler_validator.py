"""Compiler determinism, output safety, and validator mutation tests."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest

from harness_foundry_factory.compiler import (
    _repair_structural_hashes,
    compile_candidate,
)
from harness_foundry_factory.validator import (
    _authorized_driver_materialization_precondition,
    _authorized_lab_bootstrap_materialization,
    _authorized_lab_self_conformance_materialization,
    _authorized_lab_tool_release_materialization,
    _authorized_lab_tool_release_preparation_materialization,
    _authorized_linkage_bootstrap_failure_materialization,
    _authorized_linkage_executor_no_op_failure_materialization,
    _candidate_tree_hash,
    validate_candidate,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SPEC_ROOT = REPOSITORY_ROOT.parent / "Harness_Foundry_v2_8_Start_Package"
FIXTURE_PATH = REPOSITORY_ROOT / "tests/fixtures/harness_requirement_ir.json"
CREATED_AT = "2026-07-10T00:00:00Z"


class CompilerValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.candidate = self.root / "candidate"
        self.ir = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.ir["target"]["output_root"] = str(self.candidate)
        self.compile_result = self._compile("staging")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _compile(self, staging_name: str, candidate: Path | None = None) -> dict:
        target = candidate or self.candidate
        return compile_candidate(
            self.ir,
            SPEC_ROOT,
            self.root / staging_name,
            target,
            CREATED_AT,
        )

    def _mutate_json(self, relative_path: str, change) -> None:
        path = self.candidate / relative_path
        value = json.loads(path.read_text(encoding="utf-8"))
        change(value)
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _finding_codes(self) -> set[str]:
        report = validate_candidate(self.candidate)
        return {item["code"] for item in report["blocking_findings"]}

    @staticmethod
    def _tree_snapshot(root: Path) -> dict[str, str]:
        return {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def test_complete_fixture_compiles_and_validates(self) -> None:
        report = validate_candidate(self.candidate)

        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["valid"])
        self.assertEqual(report["blocking_findings"], [])
        self.assertGreaterEqual(self.compile_result["file_count"], 72)
        self.assertEqual(
            self.compile_result["authoring_terminal_state"],
            "START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW",
        )
        for directory in ("external_lab", "linkage_review", "main_build"):
            self.assertTrue(
                (self.candidate / "project_start_packages" / directory).is_dir()
            )

    def test_immutable_candidate_uses_disjoint_external_execution_root(self) -> None:
        candidate = self.root / "immutable-candidate"
        execution = self.root / "build-program" / "execution"
        ir = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        ir["target"].update(
            {"output_root": str(candidate), "execution_root": str(execution)}
        )
        ir["target"]["start_package_immutability_policy"] = {
            "candidate_root_read_only_after_atomic_publication": True,
            "candidate_execution_roots_must_not_overlap": True,
        }

        compile_candidate(
            ir,
            SPEC_ROOT,
            self.root / "immutable-staging",
            candidate,
            CREATED_AT,
        )

        context = json.loads(
            (candidate / "START_CONTEXT.json").read_text(encoding="utf-8")
        )
        capsule = json.loads(
            (candidate / "CAPSULE.json").read_text(encoding="utf-8")
        )
        driver = json.loads(
            (candidate / "PROGRAM_DRIVER_CONTRACT.json").read_text(
                encoding="utf-8"
            )
        )
        projects = json.loads(
            (candidate / "THREE_PROJECT_PROGRAM_MANIFEST.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(context["candidate_root"], str(candidate))
        self.assertEqual(context["target_root"], str(candidate))
        self.assertEqual(context["execution_root"], str(execution))
        self.assertEqual(
            context["candidate_root_access"],
            "READ_ONLY_AFTER_ATOMIC_PUBLICATION",
        )
        self.assertFalse(context["candidate_execution_root_overlap"])
        self.assertIn(str(candidate), capsule["forbidden_write_paths"])
        self.assertTrue(
            Path(capsule["workspace_root_abs"]).is_relative_to(execution)
        )
        self.assertTrue(
            Path(driver["driver_entrypoint_abs"]).is_relative_to(execution)
        )
        self.assertTrue(
            all(Path(item["root_abs"]).is_relative_to(execution) for item in projects["projects"])
        )
        self.assertFalse(execution.exists())
        self.assertEqual(validate_candidate(candidate)["status"], "PASS")

    def test_authorized_materialized_driver_preserves_candidate_validity(self) -> None:
        candidate = self.root / "approved-candidate"
        build_root = self.root / "approved-build-program"
        execution = build_root / "execution"
        ir = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        ir["target"].update(
            {"output_root": str(candidate), "execution_root": str(execution)}
        )
        ir["target"]["start_package_immutability_policy"] = {
            "candidate_root_read_only_after_atomic_publication": True,
            "candidate_execution_roots_must_not_overlap": True,
        }
        compile_candidate(
            ir,
            SPEC_ROOT,
            self.root / "approved-staging",
            candidate,
            CREATED_AT,
        )

        control = execution / "control_plane"
        executable = control / ".venv/bin/program-driver"
        executable.parent.mkdir(parents=True)
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
        executable_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
        candidate_hash = _candidate_tree_hash(candidate)

        authorization_path = control / "DRIVER_VALIDATION_AUTHORIZATION.json"
        authorization = {
            "authorization_class": "PROJECT_VALIDATION_AUTHORIZATION",
            "forbidden_actions": ["PROGRAM_DRIVER_START"],
            "max_transitions": 1,
            "may_auto_advance": False,
            "scope": {
                "dag_node_ids": ["PROGRAM_DRIVER_RUNTIME_VERIFIED"],
                "workpack_ids": [],
            },
            "status": "GRANTED",
        }
        authorization_path.write_text(
            json.dumps(authorization, sort_keys=True) + "\n", encoding="utf-8"
        )
        authorization_hash = hashlib.sha256(
            authorization_path.read_bytes()
        ).hexdigest()

        attestation_path = (
            execution
            / "evidence/driver-runtime-verification/RUNTIME_ATTESTATION.json"
        )
        attestation_path.parent.mkdir(parents=True)
        attestation = {
            "driver_started": False,
            "executor_sha256": executable_hash,
            "release_candidate_hash": candidate_hash,
            "self_reported_receipt_used": False,
            "status": "PASS",
        }
        attestation_path.write_text(
            json.dumps(attestation, sort_keys=True) + "\n", encoding="utf-8"
        )
        attestation_hash = hashlib.sha256(attestation_path.read_bytes()).hexdigest()

        receipt = {
            "authorization_ref": authorization_path.relative_to(
                build_root
            ).as_posix(),
            "authorization_sha256": authorization_hash,
            "candidate_content_sha256": candidate_hash,
            "driver_entrypoint_ref": executable.relative_to(build_root).as_posix(),
            "driver_entrypoint_sha256": executable_hash,
            "driver_started": False,
            "execution_started": False,
            "install_started": False,
            "runtime_attestation_ref": attestation_path.relative_to(
                build_root
            ).as_posix(),
            "runtime_attestation_sha256": attestation_hash,
            "status": "DRIVER_RUNTIME_VERIFIED_STOPPED_BEFORE_START",
            "workpack_execution_started": False,
        }
        (control / "DRIVER_RUNTIME_VERIFICATION_RECEIPT.json").write_text(
            json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8"
        )

        self.assertEqual(validate_candidate(candidate)["status"], "PASS")

    def test_materialization_precondition_requires_consumed_uninvoked_receipt(
        self,
    ) -> None:
        candidate = self.root / "materialization-candidate"
        execution = self.root / "materialization-runtime"
        control = execution / "control_plane"
        evidence = (
            execution
            / "evidence/control_plane_bootstrap/PROGRAM_DRIVER_MATERIALIZATION/RUN_TEST"
        )
        entrypoint = control / ".venv/bin/program-driver"
        program_id = "PROGRAM-MATERIALIZATION-TEST"
        snapshot_hash = "1" * 64
        source_bundle_hash = "2" * 64
        operation_manifest_hash = "3" * 64
        scope_hash = "4" * 64

        def write_json(path: Path, value: dict) -> str:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(value, sort_keys=True) + "\n", encoding="utf-8"
            )
            return hashlib.sha256(path.read_bytes()).hexdigest()

        candidate.mkdir()
        write_json(
            candidate / "PROGRAM_DRIVER_CONTRACT.json",
            {
                "driver_entrypoint_abs": str(entrypoint),
                "program_id": program_id,
            },
        )
        write_json(
            candidate / "CHARTER_LOCK.json",
            {
                "charter_sha256": "5" * 64,
                "profile_lock_sha256": "6" * 64,
            },
        )
        entrypoint.parent.mkdir(parents=True)
        entrypoint.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        entrypoint.chmod(0o755)

        payload_hashes: dict[str, str] = {}
        for relative_name in (
            "pyproject.toml",
            "src/dag_execution_control/cli.py",
            "src/dag_execution_control/driver.py",
            "tools/program_driver_materialization_runner.py",
        ):
            payload_path = control / relative_name
            payload_path.parent.mkdir(parents=True, exist_ok=True)
            payload_path.write_text(f"payload:{relative_name}\n", encoding="utf-8")
            payload_hashes[relative_name] = hashlib.sha256(
                payload_path.read_bytes()
            ).hexdigest()

        receipt_path = evidence / "MATERIALIZATION_RECEIPT.json"
        receipt = {
            "authorization_id": "AUTH-MATERIALIZATION-TEST",
            "candidate_write_performed": False,
            "dag_transition_performed": False,
            "driver_entrypoint_abs": str(entrypoint),
            "driver_entrypoint_sha256": hashlib.sha256(
                entrypoint.read_bytes()
            ).hexdigest(),
            "driver_invoked": False,
            "driver_runtime_verified": False,
            "operation_manifest_sha256": operation_manifest_hash,
            "program_id": program_id,
            "real_target_install_performed": False,
            "runtime_control_root": str(control),
            "runtime_payload_file_count": len(payload_hashes),
            "runtime_payload_hashes": payload_hashes,
            "scope_sha256": scope_hash,
            "source_bundle_sha256": source_bundle_hash,
            "status": "MATERIALIZED_NOT_RUNTIME_VERIFIED",
            "target_code_modified": False,
            "workpack_executed": False,
        }
        receipt_hash = write_json(receipt_path, receipt)
        consumption_path = evidence / "AUTHORIZATION_CONSUMPTION.json"
        consumption = {
            "authorization_id": "AUTH-MATERIALIZATION-TEST",
            "consumed_by_action_id": "PROGRAM_DRIVER_MATERIALIZATION_PRECONDITION_V2",
            "consumption_status": "CONSUMED_VALID_MATERIALIZATION",
            "dag_transition_performed": False,
            "driver_invoked": False,
            "driver_runtime_verified": False,
            "materialization_receipt_ref": str(receipt_path),
            "materialization_receipt_sha256": receipt_hash,
            "materializations_authorized": 1,
            "materializations_consumed": 1,
            "materializations_remaining": 0,
            "max_transitions": 0,
            "program_id": program_id,
            "replay_forbidden": True,
            "scope_sha256": scope_hash,
            "successor_execution_authorized": False,
        }
        consumption_hash = write_json(consumption_path, consumption)
        authorization_path = (
            control
            / "authorizations/PROGRAM_DRIVER_MATERIALIZATION_AUTHORIZATION.json"
        )
        authorization = {
            "authorization_class": "PROJECT_BOOTSTRAP_AUTHORIZATION",
            "authorization_id": "AUTH-MATERIALIZATION-TEST",
            "charter_hash": "5" * 64,
            "consumption_ref": str(consumption_path),
            "consumption_sha256": consumption_hash,
            "consumption_status": "CONSUMED_VALID_MATERIALIZATION",
            "delegation_allowed": False,
            "materialization_receipt_ref": str(receipt_path),
            "materialization_receipt_sha256": receipt_hash,
            "materializations_consumed": 1,
            "materializations_remaining": 0,
            "max_materializations": 1,
            "max_transitions": 0,
            "may_auto_advance": False,
            "may_materialize_program_driver": True,
            "may_modify_target_code": False,
            "may_promote_validated_results": False,
            "may_start_program_driver": False,
            "operation_manifest_sha256": operation_manifest_hash,
            "profile_lock_hash": "6" * 64,
            "program_id": program_id,
            "real_target_install_allowed": False,
            "scope": {
                "action_ids": ["PROGRAM_DRIVER_MATERIALIZATION_PRECONDITION_V2"],
                "allowed_write_roots": [
                    str(control),
                    str(evidence.parent),
                ],
                "dag_node_ids": [],
                "execution_modes": ["PROGRAM_CONTROL_BOOTSTRAP"],
            },
            "scope_expansion_allowed": False,
            "scope_sha256": scope_hash,
            "source_bundle_sha256": source_bundle_hash,
            "source_snapshot_hash": snapshot_hash,
            "status": "CONSUMED",
        }
        write_json(authorization_path, authorization)
        write_json(
            control / "state/CONTROL_STATE.json",
            {
                "approved_candidate_snapshot_hash": snapshot_hash,
                "control_status": "PROGRAM_DRIVER_MATERIALIZED_PROJECT_VALIDATION_AUTHORIZATION_REQUIRED",
                "driver_materialized": True,
                "driver_runtime_verified": False,
                "driver_started": False,
                "next_eligible_node": "PROGRAM_DRIVER_RUNTIME_VERIFIED",
                "program_execution_started": False,
                "program_id": program_id,
                "side_effects_allowed": False,
            },
        )
        command = {
            "authorization_ref": None,
            "auto_execute": False,
            "command_kind": "PLANNED_EXECUTOR_INTERFACE",
            "executable_status": "PLANNED_NOT_INSTALLED",
            "executor_role": "BUILD_PROGRAM_DRIVER",
        }

        self.assertTrue(
            _authorized_driver_materialization_precondition(
                candidate, execution, entrypoint, command
            )
        )

        receipt["driver_invoked"] = True
        receipt_hash = write_json(receipt_path, receipt)
        consumption["materialization_receipt_sha256"] = receipt_hash
        consumption_hash = write_json(consumption_path, consumption)
        authorization["materialization_receipt_sha256"] = receipt_hash
        authorization["consumption_sha256"] = consumption_hash
        write_json(authorization_path, authorization)

        self.assertFalse(
            _authorized_driver_materialization_precondition(
                candidate, execution, entrypoint, command
            )
        )

    def test_authorized_materialized_codex_executor_preserves_candidate_validity(
        self,
    ) -> None:
        candidate = self.root / "executor-approved-candidate"
        build_root = self.root / "executor-approved-build-program"
        execution = build_root / "execution"
        ir = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        ir["target"].update(
            {"output_root": str(candidate), "execution_root": str(execution)}
        )
        ir["target"]["start_package_immutability_policy"] = {
            "candidate_root_read_only_after_atomic_publication": True,
            "candidate_execution_roots_must_not_overlap": True,
        }
        compile_candidate(
            ir,
            SPEC_ROOT,
            self.root / "executor-approved-staging",
            candidate,
            CREATED_AT,
        )

        control = execution / "control_plane"
        launcher = execution / "planned_executors/bin/codex"
        source_binary = build_root / "codex-source"
        launcher.parent.mkdir(parents=True)
        control.mkdir(parents=True)
        launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        source_binary.write_text("verified source binary\n", encoding="utf-8")
        launcher.chmod(0o755)
        source_binary.chmod(0o755)
        launcher_hash = hashlib.sha256(launcher.read_bytes()).hexdigest()
        source_hash = hashlib.sha256(source_binary.read_bytes()).hexdigest()

        authorization_path = control / "EXECUTOR_PREPARATION_AUTHORIZATION.json"
        authorization = {
            "authorization_class": "REPAIR_EXECUTION_AUTHORIZATION",
            "forbidden_actions": [
                "CODEX_CODING_AGENT_INVOCATION",
                "PROGRAM_DRIVER_START",
                "PROJECT_BOOTSTRAP",
                "WORKPACK_EXECUTION",
            ],
            "max_transitions": 2,
            "may_auto_advance": False,
            "scope": {"workpack_ids": []},
            "status": "GRANTED",
        }
        authorization_path.write_text(
            json.dumps(authorization, sort_keys=True) + "\n", encoding="utf-8"
        )

        descriptor_path = control / "CODEX_EXECUTOR_DESCRIPTOR.json"
        descriptor = {
            "agent_invoked": False,
            "candidate_content_sha256": _candidate_tree_hash(candidate),
            "execution_started": False,
            "launcher_abs": str(launcher),
            "launcher_sha256": launcher_hash,
            "real_target_install_started": False,
            "source_binary_abs": str(source_binary),
            "source_binary_sha256": source_hash,
            "status": "PREPARED_VERIFIED_NOT_INVOKED",
            "workpack_execution_started": False,
        }
        descriptor_path.write_text(
            json.dumps(descriptor, sort_keys=True) + "\n", encoding="utf-8"
        )

        receipt = {
            "agent_invoked": False,
            "authorization_ref": authorization_path.relative_to(
                build_root
            ).as_posix(),
            "authorization_sha256": hashlib.sha256(
                authorization_path.read_bytes()
            ).hexdigest(),
            "descriptor_ref": descriptor_path.relative_to(build_root).as_posix(),
            "descriptor_sha256": hashlib.sha256(
                descriptor_path.read_bytes()
            ).hexdigest(),
            "driver_started": False,
            "execution_started": False,
            "launcher_ref": launcher.relative_to(build_root).as_posix(),
            "launcher_sha256": launcher_hash,
            "real_target_install_started": False,
            "status": "CODEX_EXECUTOR_PREPARED_VERIFIED_NOT_INVOKED",
            "workpack_execution_started": False,
        }
        (control / "CODEX_EXECUTOR_PREPARATION_RECEIPT.json").write_text(
            json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8"
        )

        self.assertEqual(validate_candidate(candidate)["status"], "PASS")

    def test_authorized_linkage_hash_drift_failure_preserves_candidate_validity(
        self,
    ) -> None:
        candidate = self.root / "linkage-failure-candidate"
        build_root = self.root / "linkage-failure-build"
        execution = build_root / "execution"
        ir = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        ir["target"].update(
            {"output_root": str(candidate), "execution_root": str(execution)}
        )
        compile_candidate(
            ir,
            SPEC_ROOT,
            self.root / "linkage-failure-staging",
            candidate,
            CREATED_AT,
        )

        def write_json(path: Path, value: dict) -> str:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return hashlib.sha256(path.read_bytes()).hexdigest()

        def json_hash(value: dict) -> str:
            return hashlib.sha256(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()

        control = execution / "control_plane"
        launcher = execution / "planned_executors/bin/codex"
        repository = execution / "project_start_packages/linkage_review/repository"
        evidence = execution / "evidence/engineering_dag/LINKAGE_BOOTSTRAP"
        launcher.parent.mkdir(parents=True)
        repository.mkdir(parents=True)
        evidence.mkdir(parents=True)
        launcher.write_text("#!/bin/sh\nexit 126\n", encoding="utf-8")
        launcher.chmod(0o755)
        launcher_hash = hashlib.sha256(launcher.read_bytes()).hexdigest()
        candidate_hash = _candidate_tree_hash(candidate)

        manifest_refs = []
        for workpack in ("LINK-PROTOCOL", "LINK-CLI"):
            manifest_path = (
                execution
                / f"planned_executors/manifests/{workpack}.resolved-command.json"
            )
            manifest_hash = write_json(
                manifest_path,
                {
                    "auto_execute": False,
                    "executable_sha256": launcher_hash,
                    "status": "READY_NOT_EXECUTED",
                    "workpack_id": workpack,
                },
            )
            manifest_refs.append(
                {
                    "ref": manifest_path.relative_to(build_root).as_posix(),
                    "sha256": manifest_hash,
                }
            )

        scope = {
            "dag_node_ids": ["LINKAGE_BOOTSTRAP"],
            "project_ids": ["CONFORMANCE_LINKAGE_REVIEW"],
            "workpack_ids": ["LINK-PROTOCOL", "LINK-CLI"],
        }
        authorization_path = control / "LINKAGE_BOOTSTRAP_EXECUTION_AUTHORIZATION.json"
        authorization = {
            "authorization_class": "PROJECT_BOOTSTRAP_AUTHORIZATION",
            "authorization_id": "AUTH-LINKAGE-FAILURE-TEST",
            "authorization_scope_sha256": json_hash(scope),
            "candidate_content_sha256": candidate_hash,
            "command_manifest_refs": manifest_refs,
            "consumption_policy": {
                "exact_workpack_order": ["LINK-PROTOCOL", "LINK-CLI"]
            },
            "forbidden_actions": [
                "LINKAGE_SELF_CONFORMANCE",
                "LINKAGE_TOOL_RELEASE",
                "MAIN_PROJECT_BOOTSTRAP",
                "LAB_CERTIFICATION",
                "TARGET_RUNTIME_INSTALLATION",
                "REAL_TARGET_INSTALL",
                "INSTALL",
            ],
            "granted_transitions": 2,
            "max_transitions": 2,
            "may_auto_advance": False,
            "real_target_install_allowed": False,
            "scope": scope,
            "status": "GRANTED",
        }
        authorization_hash = write_json(authorization_path, authorization)

        runtime_path = control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json"
        runtime = {
            "active_dag_node": "LINKAGE_BOOTSTRAP",
            "active_pipeline_action_id": None,
            "active_workpack_id": None,
            "authorization_consumptions": {"AUTH-LINKAGE-FAILURE-TEST": 1},
            "completed_pipeline_action_ids": ["LAB_TOOL_RELEASE_LOCKED"],
            "completed_workpack_ids": [
                "LAB-PROTOCOL",
                "LAB-CLI",
                "LAB-FIXTURES",
                "LAB-SELFTEST",
            ],
            "driver_status": "BLOCKED_WORKPACK_VALIDATION_FAIL",
            "open_blocker_codes": [
                "WORKPACK_RESULT_OR_INDEPENDENT_VALIDATION_FAILED"
            ],
            "recovery": {"required": False},
            "side_effects_allowed": False,
            "state_revision": 16,
        }
        runtime["state_hash"] = json_hash(runtime)
        runtime_hash = write_json(runtime_path, runtime)

        stderr_path = evidence / "LINK-PROTOCOL.stderr"
        stdout_path = evidence / "LINK-PROTOCOL.stdout"
        stderr_path.write_text("Codex CLI target hash drift\n", encoding="utf-8")
        stdout_path.write_text("", encoding="utf-8")
        verification_path = evidence / "INDEPENDENT_FAILURE_VERIFICATION_RECEIPT.json"
        verification_hash = write_json(
            verification_path,
            {
                "link_cli_started": False,
                "link_protocol_agent_result_created": False,
                "link_protocol_code_written": False,
                "status": "FAIL_CONFIRMED_BEFORE_MODEL_WORK_AND_CODE_WRITE",
            },
        )
        failure_result_path = (
            execution / "evidence/engineering_dag/LINKAGE_BOOTSTRAP.failure-result.json"
        )
        failure_result_hash = write_json(
            failure_result_path,
            {
                "completed_workpack_ids": [],
                "failed_workpack_id": "LINK-PROTOCOL",
                "link_cli_started": False,
                "link_protocol_code_written": False,
                "residual_transition_budget_reusable": False,
                "status": "FAIL_STOPPED_BEFORE_MODEL_WORK_AND_CODE_WRITE",
            },
        )
        receipt_path = control / "LINKAGE_CODEX_TARGET_HASH_DRIFT_FAILURE_RECEIPT.json"
        receipt = {
            "authorization_ref": authorization_path.relative_to(build_root).as_posix(),
            "authorization_sha256": authorization_hash,
            "authorization_transitions_consumed": 1,
            "authorization_transitions_granted": 2,
            "candidate_content_sha256": candidate_hash,
            "code_files_written": [],
            "codex_launcher_sha256": launcher_hash,
            "codex_target_current_sha256": "current-hash",
            "codex_target_expected_sha256": "expected-hash",
            "command_exit_code": 126,
            "failed_workpack_id": "LINK-PROTOCOL",
            "failure_result_ref": failure_result_path.relative_to(
                build_root
            ).as_posix(),
            "failure_result_sha256": failure_result_hash,
            "independent_failure_verification_ref": verification_path.relative_to(
                build_root
            ).as_posix(),
            "independent_failure_verification_sha256": verification_hash,
            "independent_validation_exit_code": 1,
            "link_cli_started": False,
            "link_protocol_agent_result_created": False,
            "next_workpack_started": False,
            "residual_transition_budget_invalidated_by_stop_on_failure": True,
            "runtime_state_after_failure_ref": runtime_path.relative_to(
                build_root
            ).as_posix(),
            "runtime_state_after_failure_sha256": runtime_hash,
            "status": "FAILED_BEFORE_MODEL_WORK_AND_CODE_WRITE_STOPPED",
            "stderr_sha256": hashlib.sha256(stderr_path.read_bytes()).hexdigest(),
            "stdout_sha256": hashlib.sha256(stdout_path.read_bytes()).hexdigest(),
        }
        write_json(receipt_path, receipt)
        write_json(
            control / "CONTROL_PLANE_STATE.json",
            {
                "highest_completed_external_gate": "LAB_TOOL_RELEASE_LOCKED_PASS",
                "install_started": False,
                "open_blocker_codes": [
                    "CODEX_CLI_TARGET_HASH_DRIFT",
                    "LINKAGE_BOOTSTRAP_RETRY_REAUTHORIZATION_REQUIRED",
                ],
                "side_effects_allowed": False,
                "state": "LINKAGE_BOOTSTRAP_BLOCKED_CODEX_TARGET_HASH_DRIFT_WAITING_REPAIR_RETRY_AUTHORIZATION",
            },
        )

        command = {"executor_role": "CODEX_CODING_AGENT"}
        self.assertTrue(
            _authorized_linkage_bootstrap_failure_materialization(
                candidate, execution, launcher, command
            )
        )
        self.assertEqual(validate_candidate(candidate)["status"], "PASS")

        receipt["link_cli_started"] = True
        write_json(receipt_path, receipt)
        self.assertFalse(
            _authorized_linkage_bootstrap_failure_materialization(
                candidate, execution, launcher, command
            )
        )

    def test_authorized_linkage_hash_repaired_no_op_failure_is_receipt_bound(
        self,
    ) -> None:
        candidate = self.root / "linkage-no-op-candidate"
        build_root = self.root / "linkage-no-op-build"
        execution = build_root / "execution"
        ir = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        ir["target"].update(
            {"output_root": str(candidate), "execution_root": str(execution)}
        )
        compile_candidate(
            ir,
            SPEC_ROOT,
            self.root / "linkage-no-op-staging",
            candidate,
            CREATED_AT,
        )

        def write_json(path: Path, value: dict) -> str:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return hashlib.sha256(path.read_bytes()).hexdigest()

        def json_hash(value: dict) -> str:
            return hashlib.sha256(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()

        def ref(path: Path) -> str:
            return path.relative_to(build_root).as_posix()

        control = execution / "control_plane"
        linkage_evidence = execution / "evidence/engineering_dag/LINKAGE_BOOTSTRAP"
        repair_evidence = execution / "evidence/linkage-bootstrap-executor-repair"
        repository = execution / "project_start_packages/linkage_review/repository"
        launcher = execution / "planned_executors/bin/codex"
        target = build_root / "codex-target"
        repository.mkdir(parents=True)
        launcher.parent.mkdir(parents=True)
        linkage_evidence.mkdir(parents=True)
        repair_evidence.mkdir(parents=True)
        launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        launcher.chmod(0o755)
        target.write_text("codex target", encoding="utf-8")
        launcher_hash = hashlib.sha256(launcher.read_bytes()).hexdigest()
        target_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        candidate_hash = _candidate_tree_hash(candidate)

        manifest_refs = []
        for workpack in ("LINK-PROTOCOL", "LINK-CLI"):
            manifest_path = (
                execution
                / f"planned_executors/manifests/{workpack}.resolved-command.json"
            )
            manifest_hash = write_json(
                manifest_path,
                {
                    "auto_execute": False,
                    "executable_sha256": launcher_hash,
                    "status": "READY_NOT_EXECUTED",
                    "workpack_id": workpack,
                },
            )
            manifest_refs.append(
                {"ref": ref(manifest_path), "sha256": manifest_hash}
            )

        repair_authorization_path = (
            control / "LINKAGE_CODEX_TARGET_HASH_DRIFT_REPAIR_REVERIFY_AUTHORIZATION.json"
        )
        repair_authorization_hash = write_json(
            repair_authorization_path,
            {
                "authorization_class": "REPAIR_REVERIFY_AUTHORIZATION",
                "candidate_content_sha256": candidate_hash,
                "driver_execution_authorized": False,
                "max_driver_transitions": 0,
                "status": "GRANTED",
                "workpack_execution_authorized": False,
            },
        )
        repair_attestation_path = repair_evidence / "REVERIFICATION_ATTESTATION.json"
        repair_attestation_hash = write_json(
            repair_attestation_path,
            {
                "authorization_sha256": repair_authorization_hash,
                "blocking_findings": [],
                "checks": [{"check_id": "TARGET", "status": "PASS"}],
                "codex_launcher_sha256": launcher_hash,
                "codex_target_abs": str(target),
                "codex_target_sha256": target_hash,
                "status": "PASS",
            },
        )
        descriptor_path = (
            control / "LINKAGE_CODEX_EXECUTOR_DESCRIPTOR_AFTER_TARGET_HASH_REPAIR.json"
        )
        descriptor_hash = write_json(
            descriptor_path,
            {
                "authorization_sha256": repair_authorization_hash,
                "launcher_sha256": launcher_hash,
                "reverification_attestation_sha256": repair_attestation_hash,
                "runtime_state_revision": 16,
                "status": "REPAIRED_REVERIFIED_READY_FOR_NEW_LINKAGE_BOOTSTRAP_RETRY_AUTHORIZATION",
                "target_sha256": target_hash,
                "workpack_execution_started_after_repair": False,
            },
        )
        repair_receipt_path = (
            control / "LINKAGE_CODEX_TARGET_HASH_REPAIR_REVERIFICATION_RECEIPT.json"
        )
        repair_receipt_hash = write_json(
            repair_receipt_path,
            {
                "authorization_sha256": repair_authorization_hash,
                "authorization_transitions_consumed": 0,
                "descriptor_sha256": descriptor_hash,
                "reverification_attestation_sha256": repair_attestation_hash,
                "status": "COMPLETE_READY_FOR_HASH_BOUND_2_TRANSITION_LINKAGE_BOOTSTRAP_RETRY_AUTHORIZATION",
            },
        )
        scope = {"workpack_ids": ["LINK-PROTOCOL", "LINK-CLI"]}
        retry_authorization_path = (
            control / "LINKAGE_BOOTSTRAP_RETRY_AFTER_CODEX_TARGET_HASH_REPAIR_AUTHORIZATION.json"
        )
        retry_authorization = {
            "authorization_class": "REPAIR_REVERIFY_AND_WORKPACK_RETRY_AUTHORIZATION",
            "authorization_id": "AUTH-LINKAGE-NO-OP-TEST",
            "authorization_scope_sha256": json_hash(scope),
            "candidate_content_sha256": candidate_hash,
            "command_manifest_refs": manifest_refs,
            "consumption_policy": {
                "exact_workpack_order": ["LINK-PROTOCOL", "LINK-CLI"],
                "stop_on_first_failure": True,
            },
            "granted_transitions": 2,
            "max_transitions": 2,
            "repair_reverification_receipt_sha256": repair_receipt_hash,
            "scope": scope,
            "status": "GRANTED",
        }
        retry_authorization_hash = write_json(
            retry_authorization_path, retry_authorization
        )

        runtime_path = control / "runtime/PROGRAM_DRIVER_RUNTIME_STATE.json"
        runtime = {
            "active_dag_node": "LINKAGE_BOOTSTRAP",
            "active_workpack_id": None,
            "authorization_consumptions": {"AUTH-LINKAGE-NO-OP-TEST": 1},
            "driver_status": "BLOCKED_WORKPACK_VALIDATION_FAIL",
            "side_effects_allowed": False,
            "state_revision": 18,
        }
        runtime["state_hash"] = json_hash(runtime)
        runtime_hash = write_json(runtime_path, runtime)
        ledger_path = control / "runtime/PHASE_TRANSITION_LEDGER.jsonl"
        ledger_path.write_text("{}\n", encoding="utf-8")
        ledger_hash = hashlib.sha256(ledger_path.read_bytes()).hexdigest()

        (linkage_evidence / "LINK-PROTOCOL.stderr").write_text(
            "Codex CLI target hash drift\n", encoding="utf-8"
        )
        (linkage_evidence / "LINK-PROTOCOL.stdout").write_text("", encoding="utf-8")
        write_json(
            linkage_evidence / "INDEPENDENT_FAILURE_VERIFICATION_RECEIPT.json",
            {"status": "FAIL_CONFIRMED_BEFORE_MODEL_WORK_AND_CODE_WRITE"},
        )
        agent_result_path = (
            linkage_evidence / "LINK-PROTOCOL.hash-repair-retry-001.agent-result.json"
        )
        agent_result_hash = write_json(
            agent_result_path,
            {
                "acceptance_checks": [{"check_id": "LINK-PROTOCOL", "status": "FAIL"}],
                "changed_files": [],
                "status": "PASS",
            },
        )
        stderr_path = linkage_evidence / "LINK-PROTOCOL.hash-repair-retry-001.stderr"
        stdout_path = linkage_evidence / "LINK-PROTOCOL.hash-repair-retry-001.stdout"
        stderr_path.write_text("", encoding="utf-8")
        stdout_path.write_text("agent completed\n", encoding="utf-8")
        blockers = [
            "LINKAGE_EXECUTOR_AUTHORIZATION_CONTEXT_NOT_PROPAGATED",
            "WORKPACK_RESULT_ACCEPTANCE_COHERENCE_REPAIR_REQUIRED",
            "LINKAGE_BOOTSTRAP_RETRY_REAUTHORIZATION_REQUIRED",
        ]
        failure_verification_path = (
            linkage_evidence
            / "INDEPENDENT_HASH_REPAIR_RETRY_FAILURE_VERIFICATION_RECEIPT.json"
        )
        failure_verification_hash = write_json(
            failure_verification_path,
            {
                "blocking_findings": blockers[:2],
                "link_cli_started": False,
                "link_protocol_code_written": False,
                "repository_file_count": 0,
                "status": "FAIL_CONFIRMED_NO_CODE_AFTER_HASH_REPAIR",
            },
        )
        failure_result_path = (
            execution / "evidence/engineering_dag/LINKAGE_BOOTSTRAP.hash-repair-retry-failure-result.json"
        )
        failure_result_hash = write_json(
            failure_result_path,
            {
                "blocking_findings": blockers,
                "completed_workpack_ids": [],
                "link_cli_started": False,
                "link_protocol_code_written": False,
                "residual_transition_budget_reusable": False,
                "status": "FAIL_STOPPED_NO_CODE_AFTER_HASH_REPAIR",
            },
        )
        failure_receipt_path = control / "LINKAGE_EXECUTOR_CONTEXT_NO_OP_FAILURE_RECEIPT.json"
        failure_receipt = {
            "agent_result_ref": ref(agent_result_path),
            "agent_result_sha256": agent_result_hash,
            "authorization_ref": ref(retry_authorization_path),
            "authorization_sha256": retry_authorization_hash,
            "authorization_transitions_consumed": 1,
            "authorization_transitions_granted": 2,
            "candidate_content_sha256": candidate_hash,
            "code_files_written": [],
            "codex_command_exit_code": 0,
            "failed_workpack_id": "LINK-PROTOCOL",
            "failure_result_ref": ref(failure_result_path),
            "failure_result_sha256": failure_result_hash,
            "independent_failure_verification_ref": ref(failure_verification_path),
            "independent_failure_verification_sha256": failure_verification_hash,
            "independent_validation_exit_code": 1,
            "link_cli_started": False,
            "next_workpack_started": False,
            "repository_file_count": 0,
            "residual_transition_budget_invalidated_by_stop_on_failure": True,
            "runtime_state_after_failure_ref": ref(runtime_path),
            "runtime_state_after_failure_sha256": runtime_hash,
            "status": "FAILED_NO_CODE_AFTER_HASH_REPAIR_STOPPED",
            "stderr_ref": ref(stderr_path),
            "stderr_sha256": hashlib.sha256(stderr_path.read_bytes()).hexdigest(),
            "stdout_ref": ref(stdout_path),
            "stdout_sha256": hashlib.sha256(stdout_path.read_bytes()).hexdigest(),
            "transition_ledger_ref": ref(ledger_path),
            "transition_ledger_sha256": ledger_hash,
        }
        failure_receipt_hash = write_json(failure_receipt_path, failure_receipt)
        next_draft_path = (
            control
            / "LINKAGE_EXECUTOR_CONTEXT_RESULT_COHERENCE_AND_EVIDENCE_ISOLATION_"
            "REPAIR_REVERIFY_AND_BOOTSTRAP_RETRY_AUTHORIZATION_DRAFT.json"
        )
        next_draft = {
            "execution_authorized": False,
            "failure_receipt_sha256": failure_receipt_hash,
            "grantable": False,
            "max_transitions": 0,
            "status": "DRAFT_BLOCKED_NOT_GRANTED",
        }
        write_json(next_draft_path, next_draft)
        write_json(
            control / "CONTROL_PLANE_STATE.json",
            {
                "highest_completed_external_gate": "LAB_TOOL_RELEASE_LOCKED_PASS",
                "install_started": False,
                "open_blocker_codes": blockers,
                "side_effects_allowed": False,
                "state": "LINKAGE_BOOTSTRAP_BLOCKED_EXECUTOR_CONTEXT_NO_OP_WAITING_REPAIR_RETRY_AUTHORIZATION",
            },
        )

        command = {"executor_role": "CODEX_CODING_AGENT"}
        self.assertTrue(
            _authorized_linkage_executor_no_op_failure_materialization(
                candidate, execution, launcher, command
            )
        )
        self.assertEqual(validate_candidate(candidate)["status"], "PASS")

        next_draft["status"] = "GRANTED"
        write_json(next_draft_path, next_draft)
        self.assertFalse(
            _authorized_linkage_executor_no_op_failure_materialization(
                candidate, execution, launcher, command
            )
        )

    def test_receipt_bound_lab_bootstrap_and_self_conformance_are_accepted(self) -> None:
        candidate = self.root / "bootstrap-candidate"
        build_root = self.root / "bootstrap-build"
        execution = build_root / "execution"
        ir = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        ir["target"].update(
            {"output_root": str(candidate), "execution_root": str(execution)}
        )
        compile_candidate(
            ir,
            SPEC_ROOT,
            self.root / "bootstrap-staging",
            candidate,
            CREATED_AT,
        )
        expected_workpacks = ["LAB-PROTOCOL", "LAB-CLI", "LAB-FIXTURES"]
        launcher = execution / "planned_executors/bin/codex"
        repository = execution / "project_start_packages/external_lab/repository"
        control = execution / "control_plane"
        evidence = execution / "evidence/engineering_dag"
        launcher.parent.mkdir(parents=True)
        repository.mkdir(parents=True)
        control.mkdir(parents=True)
        evidence.mkdir(parents=True)
        launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        launcher.chmod(0o755)
        (repository / "lab.py").write_text("READY = True\n", encoding="utf-8")

        authorization_path = control / "retry-authorization.json"
        authorization = {
            "authorization_class": "REPAIR_REVERIFY_AND_WORKPACK_RETRY_AUTHORIZATION",
            "forbidden_actions": [
                "LAB_SELFTEST",
                "LAB_CERTIFICATION",
                "LINKAGE_PROJECT_BOOTSTRAP",
                "MAIN_PROJECT_BOOTSTRAP",
                "TARGET_RUNTIME_INSTALLATION",
                "REAL_TARGET_INSTALL",
            ],
            "max_transitions": 3,
            "scope": {"workpack_ids": expected_workpacks},
            "status": "GRANTED",
        }
        authorization_path.write_text(
            json.dumps(authorization, sort_keys=True) + "\n", encoding="utf-8"
        )
        runtime_path = control / "runtime-state.json"
        runtime = {
            "active_workpack_id": None,
            "completed_workpack_ids": expected_workpacks,
            "driver_status": "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED",
            "side_effects_allowed": False,
        }
        runtime_path.write_text(
            json.dumps(runtime, sort_keys=True) + "\n", encoding="utf-8"
        )
        result_path = evidence / "LAB_BOOTSTRAP.result.json"
        result_path.write_text(
            json.dumps(
                {"status": "PASS", "success_gate": "LAB_BOOTSTRAP_PASS"},
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        repository_hash = hashlib.sha256()
        repository_hash.update(b"lab.py\0")
        repository_hash.update(
            hashlib.sha256((repository / "lab.py").read_bytes()).hexdigest().encode()
        )
        repository_hash.update(b"\n")
        receipt_path = control / "LAB_BOOTSTRAP_COMPLETION_RECEIPT.json"
        receipt = {
            "authorization_ref": authorization_path.relative_to(build_root).as_posix(),
            "authorization_sha256": hashlib.sha256(
                authorization_path.read_bytes()
            ).hexdigest(),
            "authorization_transitions_consumed": 3,
            "candidate_content_sha256": _candidate_tree_hash(candidate),
            "completed_workpack_ids": expected_workpacks,
            "install_started": False,
            "lab_bootstrap_result_ref": result_path.relative_to(
                build_root
            ).as_posix(),
            "lab_bootstrap_result_sha256": hashlib.sha256(
                result_path.read_bytes()
            ).hexdigest(),
            "lab_certification_started": False,
            "lab_selftest_started": False,
            "linkage_project_started": False,
            "main_project_started": False,
            "repository_content_file_count": 1,
            "repository_content_sha256": repository_hash.hexdigest(),
            "runtime_state_ref": runtime_path.relative_to(build_root).as_posix(),
            "runtime_state_sha256": hashlib.sha256(
                runtime_path.read_bytes()
            ).hexdigest(),
            "status": "LAB_BOOTSTRAP_COMPLETE_STOPPED_BEFORE_SELFTEST",
        }
        receipt_path.write_text(
            json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8"
        )
        descriptor_path = (
            control / "CODEX_EXECUTOR_DESCRIPTOR_AFTER_LAB_BOOTSTRAP.json"
        )
        descriptor = {
            "candidate_content_sha256": _candidate_tree_hash(candidate),
            "completed_workpack_ids": expected_workpacks,
            "completion_receipt_ref": receipt_path.relative_to(
                build_root
            ).as_posix(),
            "completion_receipt_sha256": hashlib.sha256(
                receipt_path.read_bytes()
            ).hexdigest(),
            "lab_certification_started": False,
            "lab_selftest_started": False,
            "launcher_sha256": hashlib.sha256(launcher.read_bytes()).hexdigest(),
            "linkage_project_started": False,
            "main_project_started": False,
            "real_target_install_started": False,
            "status": "ORDERED_LAB_BOOTSTRAP_SCOPE_CONSUMED_STOPPED",
        }
        descriptor_path.write_text(
            json.dumps(descriptor, sort_keys=True) + "\n", encoding="utf-8"
        )

        self.assertTrue(
            _authorized_lab_bootstrap_materialization(
                candidate,
                execution,
                launcher,
                {"executor_role": "CODEX_CODING_AGENT"},
            )
        )

        self_authorization_path = control / "self-authorization.json"
        self_authorization = {
            "authorization_class": "PROJECT_VALIDATION_AUTHORIZATION",
            "authorization_id": "AUTH-LAB-SELFTEST",
            "forbidden_actions": [
                "LAB_CERTIFICATION",
                "LINKAGE_PROJECT_BOOTSTRAP",
                "MAIN_PROJECT_BOOTSTRAP",
                "TARGET_RUNTIME_INSTALLATION",
                "REAL_TARGET_INSTALL",
            ],
            "max_transitions": 1,
            "may_auto_advance": False,
            "real_target_install_allowed": False,
            "scope": {
                "dag_node_ids": ["LAB_SELF_CONFORMANCE_PASS"],
                "workpack_ids": ["LAB-SELFTEST"],
            },
            "status": "GRANTED",
        }
        self_authorization_path.write_text(
            json.dumps(self_authorization, sort_keys=True) + "\n", encoding="utf-8"
        )
        runtime.update(
            {
                "authorization_consumptions": {"AUTH-LAB-SELFTEST": 1},
                "completed_workpack_ids": expected_workpacks + ["LAB-SELFTEST"],
            }
        )
        runtime_path.write_text(
            json.dumps(runtime, sort_keys=True) + "\n", encoding="utf-8"
        )
        self_result_path = evidence / "LAB_SELF_CONFORMANCE_PASS.result.json"
        self_result_path.write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "success_gate": "LAB_SELF_CONFORMANCE_PASS_PASS",
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        self_workpack_path = (
            execution
            / "evidence/project_workpacks/EXTERNAL_CONFORMANCE_LAB/LAB-SELFTEST/WORKPACK_RESULT.json"
        )
        self_workpack_path.parent.mkdir(parents=True)
        self_workpack_path.write_text(
            json.dumps(
                {
                    "command_exit_code": 0,
                    "independent_validation_exit_code": 0,
                    "status": "PASS",
                    "workpack_id": "LAB-SELFTEST",
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        independent_path = self_workpack_path.parent / "INDEPENDENT_VALIDATION_RECEIPT.json"
        independent_path.write_text(
            json.dumps(
                {"independent_validation_exit_code": 0, "status": "PASS"},
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        self_receipt_path = control / "LAB_SELF_CONFORMANCE_COMPLETION_RECEIPT.json"
        self_receipt = {
            "authorization_ref": self_authorization_path.relative_to(build_root).as_posix(),
            "authorization_sha256": hashlib.sha256(
                self_authorization_path.read_bytes()
            ).hexdigest(),
            "authorization_transitions_consumed": 1,
            "candidate_content_sha256": _candidate_tree_hash(candidate),
            "completed_workpack_ids": expected_workpacks + ["LAB-SELFTEST"],
            "independent_validation_receipt_ref": independent_path.relative_to(
                build_root
            ).as_posix(),
            "independent_validation_receipt_sha256": hashlib.sha256(
                independent_path.read_bytes()
            ).hexdigest(),
            "install_started": False,
            "lab_certification_started": False,
            "lab_self_conformance_result_ref": self_result_path.relative_to(
                build_root
            ).as_posix(),
            "lab_self_conformance_result_sha256": hashlib.sha256(
                self_result_path.read_bytes()
            ).hexdigest(),
            "lab_tool_release_started": False,
            "linkage_project_started": False,
            "main_project_started": False,
            "repository_content_file_count": 1,
            "repository_content_sha256": repository_hash.hexdigest(),
            "runtime_state_ref": runtime_path.relative_to(build_root).as_posix(),
            "runtime_state_sha256": hashlib.sha256(runtime_path.read_bytes()).hexdigest(),
            "status": "LAB_SELF_CONFORMANCE_COMPLETE_STOPPED_BEFORE_TOOL_RELEASE",
            "target_runtime_install_started": False,
            "workpack_result_ref": self_workpack_path.relative_to(build_root).as_posix(),
            "workpack_result_sha256": hashlib.sha256(
                self_workpack_path.read_bytes()
            ).hexdigest(),
        }
        self_receipt_path.write_text(
            json.dumps(self_receipt, sort_keys=True) + "\n", encoding="utf-8"
        )
        self_descriptor_path = (
            control / "CODEX_EXECUTOR_DESCRIPTOR_AFTER_LAB_SELF_CONFORMANCE.json"
        )
        self_descriptor = {
            "agent_invocation_count": 4,
            "candidate_content_sha256": _candidate_tree_hash(candidate),
            "completed_workpack_ids": expected_workpacks + ["LAB-SELFTEST"],
            "lab_certification_started": False,
            "lab_self_conformance_completion_receipt_ref": self_receipt_path.relative_to(
                build_root
            ).as_posix(),
            "lab_self_conformance_completion_receipt_sha256": hashlib.sha256(
                self_receipt_path.read_bytes()
            ).hexdigest(),
            "lab_selftest_executor_kind": "PINNED_LOCAL_PYTHON_NO_CODEX_AGENT",
            "lab_tool_release_started": False,
            "launcher_sha256": hashlib.sha256(launcher.read_bytes()).hexdigest(),
            "linkage_project_started": False,
            "main_project_started": False,
            "real_target_install_started": False,
            "status": "LAB_SELF_CONFORMANCE_COMPLETE_CODEX_STOPPED",
        }
        self_descriptor_path.write_text(
            json.dumps(self_descriptor, sort_keys=True) + "\n", encoding="utf-8"
        )

        self.assertTrue(
            _authorized_lab_self_conformance_materialization(
                candidate,
                execution,
                launcher,
                {"executor_role": "CODEX_CODING_AGENT"},
            )
        )

        driver_source = control / "program_driver.py"
        driver_entrypoint = control / "program-driver"
        driver_source.write_text("VERSION = '0.3.0'\n", encoding="utf-8")
        driver_entrypoint.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        repair_authorization_path = control / "pipeline-repair-authorization.json"
        repair_authorization = {
            "authorization_class": "REPAIR_EXECUTION_AUTHORIZATION",
            "driver_execution_authorized": False,
            "forbidden_actions": [
                "LAB_TOOL_RELEASE_EXECUTION",
                "PIPELINE_ACTION_EXECUTION",
                "LAB_CERTIFICATION",
                "LINKAGE_PROJECT_BOOTSTRAP",
                "MAIN_PROJECT_BOOTSTRAP",
                "TARGET_RUNTIME_INSTALLATION",
                "REAL_TARGET_INSTALL",
            ],
            "granted_preparation_transitions": 2,
            "max_driver_transitions": 0,
            "may_auto_advance": False,
            "scope": {"workpack_ids": []},
            "status": "GRANTED",
        }
        repair_authorization_path.write_text(
            json.dumps(repair_authorization, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest_path = control / "release-action.json"
        manifest = {
            "distribution_build_started": False,
            "execution_started": False,
            "execution_unit_kind": "PIPELINE_ACTION",
            "install_performed": False,
            "pipeline_action_id": "LAB_TOOL_RELEASE_LOCKED",
            "status": "READY_NOT_EXECUTED",
            "workpack_id": None,
        }
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
        )
        draft_path = control / "release-authorization-draft.json"
        draft = {
            "command_manifest_refs": [
                {
                    "ref": manifest_path.relative_to(build_root).as_posix(),
                    "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                }
            ],
            "driver_execution_authorized": False,
            "execution_authorized": False,
            "grantable": False,
            "granted_transitions": 0,
            "max_transitions": 0,
            "scope": {
                "pipeline_action_ids": ["LAB_TOOL_RELEASE_LOCKED"],
                "workpack_ids": [],
            },
            "status": "DRAFT_READY_NOT_GRANTED",
        }
        draft_path.write_text(
            json.dumps(draft, sort_keys=True) + "\n", encoding="utf-8"
        )
        readiness_path = control / "release-readiness.json"
        readiness = {
            "execution_or_build_started": False,
            "preparation_blocking_findings": [],
            "release_action_writes_performed": False,
            "status": "READY_FOR_PACKAGE_BUILD_AUTHORIZATION_NOT_GRANTED",
            "target_pipeline_action_executed": False,
            "technical_preparation_status": "PASS",
        }
        readiness_path.write_text(
            json.dumps(readiness, sort_keys=True) + "\n", encoding="utf-8"
        )
        attestation_path = control / "pipeline-repair-attestation.json"
        attestation = {
            "actual_pipeline_action_executed": False,
            "status": "PASS_REVERIFIED_PIPELINE_ACTION_PREFLIGHT",
            "target_distribution_build_started": False,
        }
        attestation_path.write_text(
            json.dumps(attestation, sort_keys=True) + "\n", encoding="utf-8"
        )
        ledger_path = control / "pipeline-repair-ledger.jsonl"
        ledger_path.write_text("{}\n", encoding="utf-8")
        runtime.update(
            {
                "active_pipeline_action_id": None,
                "completed_pipeline_action_ids": [],
                "driver_status": "STOPPED_AFTER_AUTHORIZED_REPAIR_PREPARATION",
                "runtime_verification_status": "PASS_REVERIFIED_PIPELINE_ACTION_PREFLIGHT",
            }
        )
        runtime["state_hash"] = hashlib.sha256(
            json.dumps(
                runtime,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        runtime_path.write_text(
            json.dumps(runtime, sort_keys=True) + "\n", encoding="utf-8"
        )
        preparation_receipt_path = (
            control
            / "DRIVER_PIPELINE_ACTION_REPAIR_AND_LAB_TOOL_RELEASE_PREPARATION_RECEIPT.json"
        )
        preparation_receipt = {
            "actual_pipeline_action_executed": False,
            "authorization_ref": repair_authorization_path.relative_to(
                build_root
            ).as_posix(),
            "authorization_sha256": hashlib.sha256(
                repair_authorization_path.read_bytes()
            ).hexdigest(),
            "authorization_transitions_consumed": 2,
            "candidate_content_sha256": _candidate_tree_hash(candidate),
            "distribution_build_started": False,
            "install_started": False,
            "lab_certification_started": False,
            "linkage_project_started": False,
            "main_project_started": False,
            "package_build_authorization_draft_ref": draft_path.relative_to(
                build_root
            ).as_posix(),
            "package_build_authorization_draft_sha256": hashlib.sha256(
                draft_path.read_bytes()
            ).hexdigest(),
            "pipeline_action_manifest_ref": manifest_path.relative_to(
                build_root
            ).as_posix(),
            "pipeline_action_manifest_sha256": hashlib.sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            "readiness_report_ref": readiness_path.relative_to(
                build_root
            ).as_posix(),
            "readiness_report_sha256": hashlib.sha256(
                readiness_path.read_bytes()
            ).hexdigest(),
            "runtime_attestation_ref": attestation_path.relative_to(
                build_root
            ).as_posix(),
            "runtime_attestation_sha256": hashlib.sha256(
                attestation_path.read_bytes()
            ).hexdigest(),
            "runtime_state_ref": runtime_path.relative_to(build_root).as_posix(),
            "runtime_state_sha256": hashlib.sha256(runtime_path.read_bytes()).hexdigest(),
            "status": "COMPLETE_READY_FOR_EXPLICIT_PACKAGE_BUILD_AUTHORIZATION",
            "target_runtime_install_started": False,
            "transition_ledger_ref": ledger_path.relative_to(build_root).as_posix(),
            "transition_ledger_sha256": hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
        }
        preparation_receipt_path.write_text(
            json.dumps(preparation_receipt, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        repaired_descriptor_path = (
            control / "PROGRAM_DRIVER_DESCRIPTOR_AFTER_PIPELINE_ACTION_REPAIR.json"
        )
        repaired_descriptor = {
            "candidate_content_sha256": _candidate_tree_hash(candidate),
            "completed_pipeline_action_ids": [],
            "completed_workpack_ids": expected_workpacks + ["LAB-SELFTEST"],
            "driver_entrypoint_ref": driver_entrypoint.relative_to(
                build_root
            ).as_posix(),
            "driver_entrypoint_sha256": hashlib.sha256(
                driver_entrypoint.read_bytes()
            ).hexdigest(),
            "driver_source_ref": driver_source.relative_to(build_root).as_posix(),
            "driver_source_sha256": hashlib.sha256(
                driver_source.read_bytes()
            ).hexdigest(),
            "driver_version": "0.3.0",
            "lab_certification_started": False,
            "lab_tool_release_started": False,
            "linkage_project_started": False,
            "main_project_started": False,
            "preparation_receipt_sha256": hashlib.sha256(
                preparation_receipt_path.read_bytes()
            ).hexdigest(),
            "prior_descriptor_ref": self_descriptor_path.relative_to(
                build_root
            ).as_posix(),
            "prior_descriptor_sha256": hashlib.sha256(
                self_descriptor_path.read_bytes()
            ).hexdigest(),
            "real_target_install_started": False,
            "runtime_state_sha256": hashlib.sha256(runtime_path.read_bytes()).hexdigest(),
            "status": "PIPELINE_ACTION_SUPPORTED_RELEASE_PREPARED_NOT_AUTHORIZED",
        }
        repaired_descriptor_path.write_text(
            json.dumps(repaired_descriptor, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        self.assertTrue(
            _authorized_lab_tool_release_preparation_materialization(
                candidate,
                execution,
                launcher,
                {"executor_role": "CODEX_CODING_AGENT"},
            )
        )

        def write_json(path: Path, payload: dict[str, object]) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
            )

        release_dir = evidence / "LAB_TOOL_RELEASE_LOCKED"
        archive_path = release_dir / "vscdsl_external_lab-0.1.0.zip"
        archive_path.parent.mkdir(parents=True)
        archive_path.write_bytes(b"deterministic-archive")
        archive_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()

        distribution_path = release_dir / "LAB_TOOL_DISTRIBUTION_DESCRIPTOR.json"
        write_json(
            distribution_path,
            {
                "archive_sha256": archive_hash,
                "install_performed": False,
                "pipeline_action_id": "LAB_TOOL_RELEASE_LOCKED",
            },
        )
        interface_path = release_dir / "CONFORMANCE_INTERFACE.realized.json"
        write_json(
            interface_path,
            {
                "interface_status": "LAB_TOOL_DISTRIBUTION_HASH_BOUND",
                "lab_tool_distribution_sha256": archive_hash,
            },
        )
        action_result_path = release_dir / "LAB_TOOL_RELEASE_LOCKED.action-result.json"
        write_json(
            action_result_path,
            {
                "conformance_interface_sha256": hashlib.sha256(
                    interface_path.read_bytes()
                ).hexdigest(),
                "distribution_sha256": archive_hash,
                "pipeline_action_id": "LAB_TOOL_RELEASE_LOCKED",
                "release_descriptor_sha256": hashlib.sha256(
                    distribution_path.read_bytes()
                ).hexdigest(),
                "status": "PASS",
            },
        )
        release_authorization_path = control / (
            "LAB_TOOL_RELEASE_LOCKED_PACKAGE_BUILD_AUTHORIZATION.json"
        )
        release_authorization = {
            "authorization_class": "PACKAGE_BUILD_AUTHORIZATION",
            "authorization_id": "AUTH-LAB-TOOL-RELEASE",
            "forbidden_actions": [
                "INSTALL",
                "LAB_CERTIFICATION",
                "LINKAGE_PROJECT_BOOTSTRAP",
                "MAIN_PROJECT_BOOTSTRAP",
                "OTHER_PIPELINE_ACTION_EXECUTION",
                "TARGET_RUNTIME_INSTALLATION",
                "REAL_TARGET_INSTALL",
                "WORKPACK_EXECUTION",
            ],
            "granted_transitions": 1,
            "max_transitions": 1,
            "may_auto_advance": False,
            "real_target_install_allowed": False,
            "scope": {
                "dag_node_ids": ["LAB_TOOL_RELEASE_LOCKED"],
                "pipeline_action_ids": ["LAB_TOOL_RELEASE_LOCKED"],
                "workpack_ids": [],
            },
            "status": "GRANTED",
        }
        write_json(release_authorization_path, release_authorization)
        transition_ledger_path = control / "release-transition-ledger.jsonl"
        transition_ledger_path.write_text("{}\n", encoding="utf-8")
        promotion_ledger_path = control / "release-promotion-ledger.jsonl"
        promotion_ledger_path.write_text("{}\n", encoding="utf-8")
        independent_path = release_dir / "INDEPENDENT_VALIDATION_RECEIPT.json"
        write_json(
            independent_path,
            {
                "archive_sha256": archive_hash,
                "command_exit_code": 0,
                "independent_validation_exit_code": 0,
                "install_performed": False,
                "pipeline_action_id": "LAB_TOOL_RELEASE_LOCKED",
                "status": "PASS",
            },
        )
        release_result_path = evidence / "LAB_TOOL_RELEASE_LOCKED.result.json"
        write_json(
            release_result_path,
            {
                "archive_sha256": archive_hash,
                "authorization_transitions_consumed": 1,
                "pipeline_action_id": "LAB_TOOL_RELEASE_LOCKED",
                "status": "PASS",
                "success_gate": "LAB_TOOL_RELEASE_LOCKED_PASS",
            },
        )
        promotion_path = evidence / "LAB_TOOL_RELEASE_LOCKED.promotion.json"
        write_json(
            promotion_path,
            {
                "install_started": False,
                "linkage_project_started": False,
                "main_project_started": False,
                "next_node_activated": False,
                "next_node_id": "LINKAGE_BOOTSTRAP",
                "result_sha256": hashlib.sha256(
                    release_result_path.read_bytes()
                ).hexdigest(),
                "status": "PROMOTED_STOPPED_BEFORE_LINKAGE_BOOTSTRAP",
            },
        )
        runtime.update(
            {
                "active_dag_node": None,
                "active_pipeline_action_id": None,
                "authorization_consumptions": {"AUTH-LAB-TOOL-RELEASE": 1},
                "completed_pipeline_action_ids": ["LAB_TOOL_RELEASE_LOCKED"],
                "completed_workpack_ids": expected_workpacks + ["LAB-SELFTEST"],
                "driver_status": "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED",
                "recovery": {"required": False},
            }
        )
        runtime.pop("state_hash", None)
        runtime["state_hash"] = hashlib.sha256(
            json.dumps(
                runtime,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        write_json(runtime_path, runtime)
        completion_receipt_path = (
            control / "LAB_TOOL_RELEASE_LOCKED_COMPLETION_RECEIPT.json"
        )
        completion_receipt = {
            "action_result_ref": action_result_path.relative_to(build_root).as_posix(),
            "action_result_sha256": hashlib.sha256(
                action_result_path.read_bytes()
            ).hexdigest(),
            "archive_ref": archive_path.relative_to(build_root).as_posix(),
            "archive_sha256": archive_hash,
            "authorization_ref": release_authorization_path.relative_to(
                build_root
            ).as_posix(),
            "authorization_sha256": hashlib.sha256(
                release_authorization_path.read_bytes()
            ).hexdigest(),
            "authorization_transitions_consumed": 1,
            "candidate_content_sha256": _candidate_tree_hash(candidate),
            "command_exit_code": 0,
            "completed_pipeline_action_ids": ["LAB_TOOL_RELEASE_LOCKED"],
            "conformance_interface_ref": interface_path.relative_to(
                build_root
            ).as_posix(),
            "conformance_interface_sha256": hashlib.sha256(
                interface_path.read_bytes()
            ).hexdigest(),
            "distribution_descriptor_ref": distribution_path.relative_to(
                build_root
            ).as_posix(),
            "distribution_descriptor_sha256": hashlib.sha256(
                distribution_path.read_bytes()
            ).hexdigest(),
            "driver_status": "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED",
            "independent_validation_exit_code": 0,
            "independent_validation_receipt_ref": independent_path.relative_to(
                build_root
            ).as_posix(),
            "independent_validation_receipt_sha256": hashlib.sha256(
                independent_path.read_bytes()
            ).hexdigest(),
            "install_started": False,
            "lab_certification_started": False,
            "lab_tool_release_result_ref": release_result_path.relative_to(
                build_root
            ).as_posix(),
            "lab_tool_release_result_sha256": hashlib.sha256(
                release_result_path.read_bytes()
            ).hexdigest(),
            "linkage_project_started": False,
            "main_project_started": False,
            "manifest_ref": manifest_path.relative_to(build_root).as_posix(),
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "promotion_ledger_ref": promotion_ledger_path.relative_to(
                build_root
            ).as_posix(),
            "promotion_ledger_sha256": hashlib.sha256(
                promotion_ledger_path.read_bytes()
            ).hexdigest(),
            "promotion_ref": promotion_path.relative_to(build_root).as_posix(),
            "promotion_sha256": hashlib.sha256(
                promotion_path.read_bytes()
            ).hexdigest(),
            "runtime_state_ref": runtime_path.relative_to(build_root).as_posix(),
            "runtime_state_sha256": hashlib.sha256(
                runtime_path.read_bytes()
            ).hexdigest(),
            "status": "LAB_TOOL_RELEASE_LOCKED_COMPLETE_STOPPED_BEFORE_LINKAGE_BOOTSTRAP",
            "target_runtime_install_started": False,
            "transition_ledger_ref": transition_ledger_path.relative_to(
                build_root
            ).as_posix(),
            "transition_ledger_sha256": hashlib.sha256(
                transition_ledger_path.read_bytes()
            ).hexdigest(),
        }
        write_json(completion_receipt_path, completion_receipt)
        release_descriptor_path = (
            control / "PROGRAM_DRIVER_DESCRIPTOR_AFTER_LAB_TOOL_RELEASE.json"
        )
        release_descriptor = {
            "archive_sha256": archive_hash,
            "candidate_content_sha256": _candidate_tree_hash(candidate),
            "completed_pipeline_action_ids": ["LAB_TOOL_RELEASE_LOCKED"],
            "completed_workpack_ids": expected_workpacks + ["LAB-SELFTEST"],
            "completion_receipt_ref": completion_receipt_path.relative_to(
                build_root
            ).as_posix(),
            "completion_receipt_sha256": hashlib.sha256(
                completion_receipt_path.read_bytes()
            ).hexdigest(),
            "conformance_interface_sha256": hashlib.sha256(
                interface_path.read_bytes()
            ).hexdigest(),
            "driver_entrypoint_ref": driver_entrypoint.relative_to(
                build_root
            ).as_posix(),
            "driver_entrypoint_sha256": hashlib.sha256(
                driver_entrypoint.read_bytes()
            ).hexdigest(),
            "driver_source_ref": driver_source.relative_to(build_root).as_posix(),
            "driver_source_sha256": hashlib.sha256(
                driver_source.read_bytes()
            ).hexdigest(),
            "driver_status": "STOPPED_AFTER_AUTHORIZED_SCOPE_CONSUMED",
            "driver_version": "0.3.0",
            "install_started": False,
            "lab_certification_started": False,
            "lab_tool_release_started": True,
            "linkage_project_started": False,
            "main_project_started": False,
            "next_node_activated": False,
            "next_node_id": "LINKAGE_BOOTSTRAP",
            "prior_descriptor_ref": repaired_descriptor_path.relative_to(
                build_root
            ).as_posix(),
            "prior_descriptor_sha256": hashlib.sha256(
                repaired_descriptor_path.read_bytes()
            ).hexdigest(),
            "real_target_install_started": False,
            "runtime_state_sha256": hashlib.sha256(
                runtime_path.read_bytes()
            ).hexdigest(),
            "status": "LAB_TOOL_RELEASE_LOCKED_PASS_STOPPED_BEFORE_LINKAGE_BOOTSTRAP",
            "target_runtime_install_started": False,
        }
        write_json(release_descriptor_path, release_descriptor)

        self.assertFalse(
            _authorized_lab_tool_release_preparation_materialization(
                candidate,
                execution,
                launcher,
                {"executor_role": "CODEX_CODING_AGENT"},
            )
        )
        self.assertTrue(
            _authorized_lab_tool_release_materialization(
                candidate,
                execution,
                launcher,
                {"executor_role": "CODEX_CODING_AGENT"},
            )
        )

    def test_immutable_candidate_rejects_candidate_internal_write_root(self) -> None:
        candidate = self.root / "mutated-immutable-candidate"
        execution = self.root / "mutated-build-program" / "execution"
        ir = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        ir["target"].update(
            {"output_root": str(candidate), "execution_root": str(execution)}
        )
        ir["target"]["start_package_immutability_policy"] = {
            "candidate_root_read_only_after_atomic_publication": True
        }
        compile_candidate(
            ir,
            SPEC_ROOT,
            self.root / "mutated-immutable-staging",
            candidate,
            CREATED_AT,
        )
        capsule_path = candidate / "CAPSULE.json"
        capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
        capsule["allowed_write_paths"] = [str(candidate / "repository")]
        capsule_path.write_text(
            json.dumps(capsule, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        codes = {
            item["code"]
            for item in validate_candidate(candidate)["blocking_findings"]
        }
        self.assertIn("CANDIDATE_IMMUTABILITY_VIOLATION", codes)

    def test_overlapping_candidate_and_execution_roots_are_rejected(self) -> None:
        candidate = self.root / "overlap-candidate"
        ir = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        ir["target"].update(
            {
                "output_root": str(candidate),
                "execution_root": str(candidate / "execution"),
            }
        )
        ir["target"]["start_package_immutability_policy"] = {
            "candidate_root_read_only_after_atomic_publication": True
        }

        with self.assertRaisesRegex(ValueError, "must not overlap"):
            compile_candidate(
                ir,
                SPEC_ROOT,
                self.root / "overlap-staging",
                candidate,
                CREATED_AT,
            )

    def test_immutable_policy_requires_an_execution_root(self) -> None:
        candidate = self.root / "missing-execution-root-candidate"
        ir = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        ir["target"]["output_root"] = str(candidate)
        ir["target"]["start_package_immutability_policy"] = {
            "candidate_root_access": "READ_ONLY_AFTER_ATOMIC_PUBLICATION"
        }

        with self.assertRaisesRegex(ValueError, "execution_root is required"):
            compile_candidate(
                ir,
                SPEC_ROOT,
                self.root / "missing-execution-root-staging",
                candidate,
                CREATED_AT,
            )

    def test_frozen_provenance_authority_aliases_and_unstructured_negative_cases_compile(self) -> None:
        candidate = self.root / "normalized-frozen-input-candidate"
        ir = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        ir["target"]["output_root"] = str(candidate)
        ir["sources"][0]["authority_level"] = "NORMATIVE_USER_SELECTED"
        ir["sources"].append(
            {
                **ir["sources"][0],
                "source_id": "SRC-SUPPLEMENTAL-001",
                "path_or_uri": "chat://reference/thread-1/supplement",
                "sha256": "ba5f" * 16,
                "authority_level": "HUMAN_PROVIDED_SUPPLEMENT",
            }
        )
        ir["negative_cases"][0].pop("expected_failure")
        ir["decisions"].append(
            {
                "decision_id": "DEC-PLACEHOLDER-HISTORY-001",
                "decision": "A prior placeholder example was normalized before freeze.",
                "status": "CONFIRMED",
            }
        )

        compile_candidate(
            ir,
            SPEC_ROOT,
            self.root / "normalized-frozen-input-staging",
            candidate,
            CREATED_AT,
        )

        manifest = json.loads(
            (candidate / "canonical_sources/SOURCE_MANIFEST.json").read_text(
                encoding="utf-8"
            )
        )
        authorities = {
            item["source_id"]: item["authority_level"]
            for item in manifest["sources"]
        }
        negative = json.loads(
            (candidate / "validation/NEGATIVE_CASES.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(authorities["SRC-CHAT-001"], "HUMAN_APPROVED")
        self.assertEqual(authorities["SRC-SUPPLEMENTAL-001"], "HUMAN_PROVIDED")
        self.assertEqual(
            negative["cases"][0]["expected_failure"], "EXPECTED_REJECTION"
        )
        self.assertEqual(validate_candidate(candidate)["status"], "PASS")

    def test_structural_hash_repair_preserves_planned_executor_hash_contract(self) -> None:
        _repair_structural_hashes(self.candidate)

        self.assertEqual(validate_candidate(self.candidate)["status"], "PASS")

    def test_rebuild_at_same_path_has_identical_content_hash(self) -> None:
        first_hash = self.compile_result["content_sha256"]
        shutil.rmtree(self.candidate)

        second = self._compile("staging-rebuild")

        self.assertEqual(second["content_sha256"], first_hash)
        self.assertEqual(second["file_count"], self.compile_result["file_count"])
        self.assertEqual(validate_candidate(self.candidate)["status"], "PASS")

    def test_same_ir_existing_candidate_is_recovered_without_overwrite(self) -> None:
        provenance_before = (
            self.candidate / "FACTORY_PROVENANCE.json"
        ).read_bytes()

        recovered = self._compile("unused-recovery-staging")

        self.assertTrue(recovered["recovered_existing_candidate"])
        self.assertEqual(
            recovered["content_sha256"], self.compile_result["content_sha256"]
        )
        self.assertFalse((self.root / "unused-recovery-staging").exists())
        self.assertEqual(
            (self.candidate / "FACTORY_PROVENANCE.json").read_bytes(),
            provenance_before,
        )
        self.assertEqual(validate_candidate(self.candidate)["status"], "PASS")

    def test_nonempty_output_directory_is_rejected(self) -> None:
        occupied = self.root / "occupied"
        occupied.mkdir()
        (occupied / "user-owned.txt").write_text("preserve", encoding="utf-8")

        with self.assertRaisesRegex(FileExistsError, "candidate root is not empty"):
            self._compile("staging-collision", occupied)

        self.assertEqual(
            (occupied / "user-owned.txt").read_text(encoding="utf-8"), "preserve"
        )

    def test_deleting_p3_from_phase_order_is_rejected(self) -> None:
        self._mutate_json(
            "PHASE_DEPENDENCY_MANIFEST.json",
            lambda value: value.update(
                {"phase_order": [item for item in value["phase_order"] if item != "P3"]}
            ),
        )

        self.assertIn("P3_PHASE_ORDER_INVALID", self._finding_codes())

    def test_reordering_release_steps_is_rejected(self) -> None:
        def swap_first_two(value: dict) -> None:
            value["steps"][0], value["steps"][1] = value["steps"][1], value["steps"][0]

        self._mutate_json("RELEASE_PIPELINE_MANIFEST.json", swap_first_two)

        self.assertIn("RELEASE_PIPELINE_ORDER_INVALID", self._finding_codes())

    def test_granting_execution_authorization_is_rejected(self) -> None:
        self._mutate_json(
            "EXECUTION_AUTHORIZATION.json",
            lambda value: value.update(
                {"status": "GRANTED", "may_auto_advance": True, "max_transitions": 1}
            ),
        )

        self.assertIn("EXECUTION_AUTHORIZATION_PREGRANTED", self._finding_codes())

    def test_removing_codex_false_receipt_negative_case_is_rejected(self) -> None:
        def remove_codex_case(value: dict) -> None:
            value["cases"] = [
                item
                for item in value["cases"]
                if item.get("case_id")
                not in {"NEG-001", "NEG-HF28-CODEX-SELF-REPORT"}
            ]

        self._mutate_json("validation/NEGATIVE_CASES.json", remove_codex_case)

        self.assertIn("FALSE_CODEX_RECEIPT_CASE_MISSING", self._finding_codes())

    def test_forged_self_reported_codex_receipt_authority_is_rejected(self) -> None:
        self._mutate_json(
            "constitution/RUNTIME_ATTESTATION_POLICY.json",
            lambda value: value.update(
                {
                    "self_reported_receipt_is_sufficient": True,
                    "trusted_issuer": "PYTHON_SELF_REPORT",
                    "unverified_invocation_may_complete_stage": True,
                }
            ),
        )

        self.assertEqual(validate_candidate(self.candidate)["status"], "FAIL")

    def test_relative_executable_is_rejected(self) -> None:
        def make_relative(value: dict) -> None:
            value["commands"][0]["executable"] = "python3"
            value["commands"][0]["executable_abs"] = "python3"

        self._mutate_json("COMMAND_MANIFEST.json", make_relative)

        self.assertIn("COMMAND_EXECUTABLE_NOT_ABSOLUTE", self._finding_codes())

    def test_target_id_path_traversal_is_rejected_without_writes(self) -> None:
        before = self._tree_snapshot(self.root)
        traversal_ir = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        traversal_ir["target"]["id"] = "x/../../../escaped"
        traversal_ir["target"]["output_root"] = str(
            self.root / "traversal-candidate"
        )

        with self.assertRaisesRegex(ValueError, "path-safe identifier"):
            compile_candidate(
                traversal_ir,
                SPEC_ROOT,
                self.root / "traversal-staging",
                self.root / "traversal-candidate",
                CREATED_AT,
            )

        self.assertEqual(self._tree_snapshot(self.root), before)

    def test_manifest_cannot_hide_deleted_start_here(self) -> None:
        self._mutate_json(
            "PACKAGE_MANIFEST.json",
            lambda value: value.update(
                {
                    "required_entry_files": [
                        item
                        for item in value["required_entry_files"]
                        if item != "START_HERE.md"
                    ]
                }
            ),
        )
        (self.candidate / "START_HERE.md").unlink()

        codes = self._finding_codes()
        self.assertIn("REQUIRED_FILE_MANIFEST_TAMPERED", codes)
        self.assertIn("REQUIRED_FILE_MISSING", codes)

    def test_duplicate_atom_id_is_rejected(self) -> None:
        self._mutate_json(
            "canonical_sources/NORMATIVE_ATOM_CATALOG.json",
            lambda value: value["atoms"].append(dict(value["atoms"][0])),
        )

        self.assertIn("ATOM_ID_NOT_UNIQUE", self._finding_codes())

    def test_empty_engineering_dag_edges_are_rejected(self) -> None:
        self._mutate_json(
            "ENGINEERING_PROJECT_DAG.json",
            lambda value: value.update({"edges": []}),
        )

        self.assertIn("ENGINEERING_DAG_EDGES_INVALID", self._finding_codes())

    def test_release_step_with_empty_requires_is_rejected(self) -> None:
        self._mutate_json(
            "RELEASE_PIPELINE_MANIFEST.json",
            lambda value: value["steps"][2].update({"requires": []}),
        )

        self.assertIn("RELEASE_STEP_DEPENDENCY_INVALID", self._finding_codes())

    def test_existing_system_executable_is_rejected_as_planned_target(self) -> None:
        def use_system_executable(value: dict) -> None:
            command = next(
                item
                for item in value["commands"]
                if isinstance(item.get("argv"), list) and item["argv"]
            )
            command["executable"] = "/bin/true"
            command["executable_abs"] = "/bin/true"
            command["argv"][0] = "/bin/true"

        self._mutate_json("COMMAND_MANIFEST.json", use_system_executable)

        self.assertIn("COMMAND_EXECUTABLE_NOT_ABSOLUTE", self._finding_codes())

    def test_empty_three_project_markdown_is_rejected(self) -> None:
        for directory in ("external_lab", "linkage_review", "main_build"):
            for name in ("README.md", "PROJECT_CHARTER.md", "BUILD_INSTALL_PLAN.md"):
                (self.candidate / "project_start_packages" / directory / name).write_text(
                    "", encoding="utf-8"
                )

        self.assertIn("PROJECT_DOCUMENT_CONTRACT_INCOMPLETE", self._finding_codes())

    def test_zero_iteration_loop_policy_is_rejected(self) -> None:
        self._mutate_json(
            "LOOP_POLICY.json",
            lambda value: value["loop_types"]["WORKPACK_REVIEW_FIX"].update(
                {"max_iterations": 0}
            ),
        )

        self.assertIn("LOOP_POLICY_INCOMPLETE", self._finding_codes())

    def test_engineering_node_machine_contract_cannot_be_compressed(self) -> None:
        self._mutate_json(
            "ENGINEERING_PROJECT_DAG.json",
            lambda value: value["nodes"][5].pop("failure_return_node"),
        )

        self.assertIn(
            "ENGINEERING_DAG_NODE_CONTRACT_INCOMPLETE", self._finding_codes()
        )

    def test_every_project_workpack_is_bound_once_and_main_paths_are_explicit(
        self,
    ) -> None:
        dag = json.loads(
            (self.candidate / "ENGINEERING_PROJECT_DAG.json").read_text(
                encoding="utf-8"
            )
        )
        release = json.loads(
            (self.candidate / "RELEASE_PIPELINE_MANIFEST.json").read_text(
                encoding="utf-8"
            )
        )
        nodes = {item["node_id"]: item for item in dag["nodes"]}
        registration = nodes["MAIN_PROGRAM_REGISTRATION"]
        self.assertEqual(registration["node_kind"], "CONTROL_REGISTRATION_GATE")
        self.assertEqual(registration["owner_role"], "BUILD_PROGRAM_DRIVER")
        self.assertIsNone(registration["workpack_id"])
        self.assertEqual(
            registration["pipeline_action_id"], "MAIN_PROGRAM_REGISTRATION"
        )
        main_repository = str(
            self.candidate / "project_start_packages/main_build/repository"
        )
        for node_id in (
            "MAIN_EXECUTION_PACKAGE_MATERIALIZED",
            "MAIN_G0_C0",
            "MAIN_P1_C1",
            "MAIN_P2_C2",
            "MAIN_P3_C3_OR_APPROVED_NA",
            "MAIN_P4_LOCAL_CLOSURE",
        ):
            self.assertIn(main_repository, nodes[node_id]["allowed_write_paths"])

        mapped = [
            item["workpack_id"]
            for item in dag["nodes"]
            if item.get("workpack_id")
            and item["node_id"] != "MAIN_EXECUTION_PACKAGE_MATERIALIZED"
        ]
        mapped.extend(
            workpack_id
            for item in dag["nodes"]
            for workpack_id in item.get("project_workpack_sequence", [])
        )
        mapped.extend(
            item["project_workpack_id"]
            for item in release["steps"]
            if item.get("project_workpack_id")
        )
        declared = []
        for directory in ("external_lab", "linkage_review", "main_build"):
            index = json.loads(
                (
                    self.candidate
                    / "project_start_packages"
                    / directory
                    / "WORKPACK_INDEX.json"
                ).read_text(encoding="utf-8")
            )
            declared.extend(item["workpack_id"] for item in index["workpacks"])
        self.assertEqual(sorted(mapped), sorted(declared))
        self.assertEqual(len(mapped), len(set(mapped)))
        self.assertEqual(len(mapped), 16)
        root_index = json.loads(
            (self.candidate / "WORKPACK_INDEX.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            nodes["MAIN_EXECUTION_PACKAGE_MATERIALIZED"]["workpack_id"],
            root_index["workpacks"][0]["workpack_id"],
        )
        self.assertNotIn(root_index["workpacks"][0]["workpack_id"], declared)

    def test_unknown_engineering_workpack_reference_is_rejected(self) -> None:
        def replace_workpack(value: dict) -> None:
            node = next(item for item in value["nodes"] if item.get("workpack_id"))
            node["workpack_id"] = "TOTALLY-NONEXISTENT-WORKPACK"

        self._mutate_json("ENGINEERING_PROJECT_DAG.json", replace_workpack)

        codes = self._finding_codes()
        self.assertIn("ENGINEERING_WORKPACK_BINDING_INVALID", codes)
        self.assertIn("ENGINEERING_WORKPACK_REF_UNRESOLVED", codes)

    def test_project_workpack_sequence_or_release_mapping_cannot_be_dropped(
        self,
    ) -> None:
        def drop_sequence_item(value: dict) -> None:
            node = next(
                item for item in value["nodes"] if item["node_id"] == "LAB_BOOTSTRAP"
            )
            node["project_workpack_sequence"] = node[
                "project_workpack_sequence"
            ][:-1]

        self._mutate_json("ENGINEERING_PROJECT_DAG.json", drop_sequence_item)

        codes = self._finding_codes()
        self.assertIn("ENGINEERING_WORKPACK_BINDING_INVALID", codes)
        self.assertIn("PROJECT_WORKPACK_COVERAGE_INVALID", codes)

    def test_unknown_release_workpack_reference_is_rejected(self) -> None:
        def replace_workpack(value: dict) -> None:
            step = next(
                item
                for item in value["steps"]
                if item.get("project_workpack_id")
            )
            step["project_workpack_id"] = "TOTALLY-NONEXISTENT-WORKPACK"

        self._mutate_json("RELEASE_PIPELINE_MANIFEST.json", replace_workpack)

        codes = self._finding_codes()
        self.assertIn("RELEASE_WORKPACK_BINDING_INVALID", codes)
        self.assertIn("PROJECT_WORKPACK_COVERAGE_INVALID", codes)

    def test_never_produced_project_workpack_requirement_is_rejected(self) -> None:
        self._mutate_json(
            "project_start_packages/external_lab/WORKPACK_INDEX.json",
            lambda value: value["workpacks"][1].update(
                {"requires": ["NEVER_PRODUCED_CAPABILITY"]}
            ),
        )

        self.assertIn(
            "PROJECT_WORKPACK_EXECUTION_CONTRACT_INVALID",
            self._finding_codes(),
        )

    def test_deleting_project_command_surface_is_rejected(self) -> None:
        self._mutate_json(
            "project_start_packages/main_build/COMMAND_MANIFEST.json",
            lambda value: value.update({"commands": []}),
        )

        codes = self._finding_codes()
        self.assertIn("PROJECT_COMMAND_MANIFEST_INVALID", codes)
        self.assertIn("PROJECT_WORKPACK_COMMAND_BINDING_INVALID", codes)

    def test_phase_atom_routes_to_matching_project_workpacks_and_artifacts(
        self,
    ) -> None:
        matrix = json.loads(
            (
                self.candidate
                / "canonical_sources/ATOM_COVERAGE_MATRIX.json"
            ).read_text(encoding="utf-8")
        )
        atom = next(item for item in matrix["coverage"] if item["atom_id"] == "ATOM-002")
        self.assertEqual(atom["workpack_ids"], ["MB-P2", "MB-P3", "MB-P4"])
        self.assertEqual(
            atom["stage_ids"], ["P2", "P3", "C3", "P4_BUILD_INPUT"]
        )
        for workpack_id in ("MB-P3", "MB-P4"):
            index = json.loads(
                (
                    self.candidate
                    / "project_start_packages/main_build/WORKPACK_INDEX.json"
                ).read_text(encoding="utf-8")
            )
            item = next(
                value
                for value in index["workpacks"]
                if value["workpack_id"] == workpack_id
            )
            capsule = json.loads(
                (
                    self.candidate
                    / f"project_start_packages/main_build/capsules/{workpack_id}.capsule.json"
                ).read_text(encoding="utf-8")
            )
            result = json.loads(
                (
                    self.candidate
                    / f"project_start_packages/main_build/results/{workpack_id}.result.json"
                ).read_text(encoding="utf-8")
            )
            self.assertIn("ATOM-002", item["intent_atom_ids"])
            self.assertIn("ATOM-002", capsule["intent_atom_ids"])
            self.assertIn("ATOM-002", result["intent_atom_ids"])

    def test_atom_coverage_cannot_be_redirected_to_wrong_phase(self) -> None:
        self._mutate_json(
            "canonical_sources/ATOM_COVERAGE_MATRIX.json",
            lambda value: next(
                item
                for item in value["coverage"]
                if item["atom_id"] == "ATOM-002"
            ).update(
                {
                    "workpack_ids": ["MB-G0"],
                    "stage_ids": ["G0"],
                    "owner_project_ids": ["MAIN_HARNESS_BUILD"],
                }
            ),
        )

        self.assertIn("COVERAGE_REFERENCE_UNRESOLVED", self._finding_codes())

    def test_project_workpack_atom_reverse_binding_cannot_be_removed(self) -> None:
        def remove_atom(value: dict) -> None:
            item = next(
                row for row in value["workpacks"] if row["workpack_id"] == "MB-P4"
            )
            item["intent_atom_ids"] = []

        self._mutate_json(
            "project_start_packages/main_build/WORKPACK_INDEX.json",
            remove_atom,
        )

        self.assertIn(
            "PROJECT_WORKPACK_EXECUTION_CONTRACT_INVALID",
            self._finding_codes(),
        )

    def test_explicit_frozen_atom_coverage_overrides_semantic_default(self) -> None:
        explicit_candidate = self.root / "explicit-coverage-candidate"
        self.ir["target"]["output_root"] = str(explicit_candidate)
        self.ir["coverage_edges"] = [
            {
                "atom_id": "ATOM-001",
                "workpack_ids": ["MB-P1"],
                "stage_ids": ["P1"],
                "release_step_ids": [],
                "owner_project_ids": ["MAIN_HARNESS_BUILD"],
                "routing_basis": "EXPLICIT_USER_CONFIRMED",
            }
        ]

        compile_candidate(
            self.ir,
            SPEC_ROOT,
            self.root / "explicit-coverage-staging",
            explicit_candidate,
            CREATED_AT,
        )

        matrix = json.loads(
            (
                explicit_candidate
                / "canonical_sources/ATOM_COVERAGE_MATRIX.json"
            ).read_text(encoding="utf-8")
        )
        atom = next(
            item for item in matrix["coverage"] if item["atom_id"] == "ATOM-001"
        )
        self.assertEqual(atom["workpack_ids"], ["MB-P1"])
        self.assertEqual(atom["stage_ids"], ["P1"])
        self.assertEqual(atom["routing_basis"], "EXPLICIT_USER_CONFIRMED")
        self.assertEqual(validate_candidate(explicit_candidate)["status"], "PASS")

    def test_python_target_still_requires_codex_for_coding_workpacks(self) -> None:
        python_candidate = self.root / "python-runtime-candidate"
        self.ir["target"]["output_root"] = str(python_candidate)
        self.ir["target"]["primary_runtime"] = "Python 3.11"

        compile_candidate(
            self.ir,
            SPEC_ROOT,
            self.root / "python-runtime-staging",
            python_candidate,
            CREATED_AT,
        )

        ownership = json.loads(
            (
                python_candidate / "constitution/RUNTIME_OWNERSHIP.json"
            ).read_text(encoding="utf-8")
        )
        commands = json.loads(
            (
                python_candidate
                / "project_start_packages/main_build/COMMAND_MANIFEST.json"
            ).read_text(encoding="utf-8")
        )
        coding = next(
            item
            for item in commands["commands"]
            if item["command_id"] == "MB-CODEX-CODING"
        )
        self.assertEqual(ownership["required_executor"]["name"], "Python 3.11")
        self.assertEqual(ownership["coding_agent_executor"]["name"], "Codex")
        self.assertTrue(coding["executable_abs"].endswith("/codex"))
        self.assertIsNone(coding["argv"])
        self.assertEqual(validate_candidate(python_candidate)["status"], "PASS")

    def test_codex_coding_command_cannot_be_replaced_by_python(self) -> None:
        def replace_executor(value: dict) -> None:
            command = next(
                item
                for item in value["commands"]
                if item["command_id"] == "MB-CODEX-CODING"
            )
            python = str(
                self.candidate
                / "project_start_packages/main_build/.venv/bin/python"
            )
            command["executable"] = python
            command["executable_abs"] = python

        self._mutate_json(
            "project_start_packages/main_build/COMMAND_MANIFEST.json",
            replace_executor,
        )

        self.assertIn("CODEX_CODING_COMMAND_SUBSTITUTED", self._finding_codes())

    def test_release_pipeline_cannot_omit_certification_environment_node(self) -> None:
        def remove_node(value: dict) -> None:
            value["steps"] = [
                item
                for item in value["steps"]
                if item["step_id"] != "SINGLE_CERTIFICATION_ENV_CREATE"
            ]

        self._mutate_json("RELEASE_PIPELINE_MANIFEST.json", remove_node)

        self.assertIn("RELEASE_PIPELINE_ORDER_INVALID", self._finding_codes())

    def test_control_plane_epoch_and_hash_binding_drift_is_rejected(self) -> None:
        self._mutate_json(
            "PROGRAM_AUTOMATION_POLICY.json",
            lambda value: value.update(
                {"control_plane_epoch": 1, "profile_lock_hash": "f" * 64}
            ),
        )

        self.assertIn("CONTROL_ASSET_BINDING_MISMATCH", self._finding_codes())

    def test_empty_invalidation_edges_are_rejected(self) -> None:
        self._mutate_json(
            "INVALIDATION_DAG.json",
            lambda value: value.update({"edges": []}),
        )

        self.assertIn("INVALIDATION_DAG_INCOMPLETE", self._finding_codes())

    def test_tampered_ledger_event_hash_is_rejected(self) -> None:
        path = self.candidate / "PHASE_TRANSITION_LEDGER.jsonl"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["event_hash"] = "0" * 64
        path.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")

        self.assertIn("LEDGER_EVENT_HASH_INVALID", self._finding_codes())

    def test_profile_lock_drift_is_rejected(self) -> None:
        self._mutate_json(
            "PROFILE_LOCK.json",
            lambda value: value.update({"selected_profile": "LITE"}),
        )

        codes = self._finding_codes()
        self.assertIn("PROFILE_LOCK_HASH_MISMATCH", codes)
        self.assertIn("PROFILE_LOCK_BOUNDARY_INVALID", codes)

    def test_program_author_role_escalation_is_rejected(self) -> None:
        self._mutate_json(
            "PACKAGE_ROLES.json",
            lambda value: value["roles"]["program_author"].update(
                {"may_execute_workpacks": True}
            ),
        )

        self.assertIn("PROGRAM_AUTHOR_AUTHORITY_ESCALATED", self._finding_codes())

    def test_duplicate_coverage_row_is_rejected(self) -> None:
        self._mutate_json(
            "canonical_sources/ATOM_COVERAGE_MATRIX.json",
            lambda value: value["coverage"].append(dict(value["coverage"][0])),
        )

        self.assertIn("COVERAGE_ATOM_ID_NOT_UNIQUE", self._finding_codes())


if __name__ == "__main__":
    unittest.main()
