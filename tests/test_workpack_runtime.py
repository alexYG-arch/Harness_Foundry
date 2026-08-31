"""Epoch 45 controlled Workpack Runtime executable-closure regressions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from harness_foundry_factory.compiler import compile_start_package
from harness_foundry_factory.core_validation import (
    _project_validated_core_evidence,
    validate_core,
)
from harness_foundry_factory.generation_readiness import (
    evaluate_generation_readiness,
)
from harness_foundry_factory.models import content_sha256
from harness_foundry_factory.validator import (
    _check_controlled_workpack_runtime_executable_closure,
    validate_candidate,
)
from harness_foundry_factory import workpack_runtime as runtime
from tests import (
    test_program_driver_runtime_verification as verification_test_support,
)
from tests.test_generation_readiness import ROOT, _epoch38_fixture, _rehash


class ControlledWorkpackRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name).resolve()
        cls.candidate = cls.root / "candidate"
        fixture = _epoch38_fixture(
            cls.candidate,
            active_requirement_epoch=47,
            include_active_requirement_marker=False,
            include_shared_control_baseline=True,
            program_id="PROGRAM-HARNESS-FOUNDRY-V2-9-UPGRADE",
            target_id="HARNESS-FOUNDRY-V2-9-CHAT-FACTORY",
        )
        cls.requirement_ir = fixture["snapshot"]["requirement_ir"]
        cls.authority_provenance = {
            "event_store_revision": 47,
            "event_store_tip_sha256": "f" * 64,
            "requirement_epoch": 47,
            "source_registry_sha256": content_sha256([]),
            "requirement_ir_sha256": content_sha256(cls.requirement_ir),
        }
        validation = validate_core(execute_tests=False)
        validation["status"] = "PASS"
        validation["core_regression"]["status"] = "PASS"
        validation["core_regression"]["tests_executed"] = True
        for item in validation["selector_results"]:
            item["status"] = "PASS"
        for item in validation["major_failure_path_matrix"]:
            item["status"] = "PASS"
        validation["validation_sha256"] = _rehash(
            validation, "validation_sha256"
        )
        projection = _project_validated_core_evidence(validation)
        readiness = evaluate_generation_readiness(
            fixture["snapshot"],
            requirement_lock=fixture["requirement_lock"],
            architecture_readback=fixture["architecture_readback"],
            architecture_lock=fixture["architecture_lock"],
            compiled_contract=fixture["compiled_contract"],
            core_validation=validation,
            core_evidence_projection=projection,
        )
        pass_report = {
            "status": "PASS",
            "validator_id": "HARNESS_FOUNDRY_FACTORY_VALIDATOR",
            "checks": [
                {
                    "check_id": "FACTORY_LOCAL_SOURCE_CONSISTENCY",
                    "status": "PASS",
                    "findings": [],
                    "validation_basis": "FACTORY_SUPPLIED_LOCAL_CONSISTENCY_INPUT",
                },
                {
                    "check_id": "FACTORY_LOCAL_REQUIREMENT_IR_CONSISTENCY",
                    "status": "PASS",
                    "findings": [],
                    "validation_basis": "FACTORY_SUPPLIED_LOCAL_CONSISTENCY_INPUT",
                },
            ],
            "blocking_findings": [],
            "commands_executed": [],
        }
        with patch(
            "harness_foundry_factory.validator.validate_candidate",
            return_value=pass_report,
        ), patch(
            "harness_foundry_factory.validator."
            "_validate_prepublication_staging_candidate",
            return_value=pass_report,
        ):
            compile_start_package(
                fixture["snapshot"]["requirement_ir"],
                spec_root=ROOT.parent / "Harness_Foundry_v2_8_Start_Package",
                staging_root=cls.root / "staging",
                candidate_root=cls.candidate,
                created_at="2026-08-25T00:00:00Z",
                spec_lock={"content_sha256": "fixture", "files": {}},
                authority_provenance={},
                generation_readiness=readiness,
            )
        load_action = (
            verification_test_support.ProgramDriverRuntimeVerificationTests._load_action
        )
        cls.shared = load_action(
            "workpack_runtime_shared",
            cls.candidate / "tools/shared_control_baseline.py",
        )
        cls.registration = load_action(
            "workpack_runtime_registration",
            cls.candidate / "tools/control_plane_registration.py",
        )
        cls.verification = load_action(
            "workpack_runtime_driver_verification",
            cls.candidate / "tools/program_driver_runtime_verification.py",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    @staticmethod
    def _write_json(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

    _commit_shared_predecessor = (
        verification_test_support.ProgramDriverRuntimeVerificationTests._commit_shared_predecessor
    )
    _registration_inputs = (
        verification_test_support.ProgramDriverRuntimeVerificationTests._registration_inputs
    )
    _commit_registration = (
        verification_test_support.ProgramDriverRuntimeVerificationTests._commit_registration
    )
    _verification_inputs = (
        verification_test_support.ProgramDriverRuntimeVerificationTests._verification_inputs
    )
    _candidate_snapshot = (
        verification_test_support.ProgramDriverRuntimeVerificationTests._candidate_snapshot
    )

    def _execution_root(self, name: str) -> Path:
        execution = self.root / name
        execution.mkdir()
        candidate_sha = runtime.candidate_identity(self.candidate)
        event = {
            "schema_version": "1.0",
            "event_id": f"EVENT-{name}",
            "event_type": "PROGRAM_DRIVER_RUNTIME_VERIFIED_COMMITTED",
            "previous_event_hash": None,
            "event_hash": "",
        }
        event["event_hash"] = runtime.hash_without(event, "event_hash")
        event_path = execution / runtime.CONTROL_EVENTS_REF
        event_path.parent.mkdir(parents=True, exist_ok=True)
        event_path.write_text(
            json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        state = {
            "schema_version": "1.0",
            "program_id": "PROGRAM-HARNESS-FOUNDRY-V2-9-UPGRADE",
            "revision": 5,
            "last_completed_node": "PROGRAM_DRIVER_RUNTIME_VERIFIED",
            "next_node": runtime.NODE_ID,
            "next_fencing_token": 4,
            "last_event_hash": event["event_hash"],
            "active_authorization_id": None,
            "authorization_status": "CONSUMED",
            "remaining_transition_budget": 0,
            "driver_started": False,
            "active_workpack": None,
            "state_sha256": "",
        }
        state["state_sha256"] = runtime.hash_without(state, "state_sha256")
        self._write_json(execution / runtime.CONTROL_STATE_REF, state)
        self._write_json(
            execution / runtime.PREDECESSOR_RESULT_REF,
            {
                "schema_version": "1.0",
                "status": "PASS",
                "node_id": "PROGRAM_DRIVER_RUNTIME_VERIFIED",
                "candidate_tree_sha256": candidate_sha,
                "next_node": runtime.NODE_ID,
                "driver_started": False,
                "workpack_started": False,
            },
        )
        return execution

    def _overlay(self, execution: Path) -> dict:
        executable = Path(sys.executable).resolve()
        repository = execution / runtime.REPOSITORY_REF
        evidence = execution / runtime.NODE_EVIDENCE_REF
        return {
            "schema_version": "1.0",
            "node_id": runtime.NODE_ID,
            "workpack_id": runtime.WORKPACK_ID,
            "candidate_tree_sha256": runtime.candidate_identity(self.candidate),
            "allowed_write_roots": [str(repository), str(evidence)],
            "max_transitions": 1,
            "max_loop_rounds": 1,
            "real_target_install_allowed": False,
            "validation_scope": runtime.VALIDATION_SCOPE,
            "commands": [
                {
                    "command_id": "ROOT-CODEX-CODING",
                    "executable_abs": str(executable),
                    "executable_sha256": runtime.file_hash(executable),
                    "argv": [
                        str(executable),
                        "exec",
                        "--sandbox",
                        "workspace-write",
                        "--skip-git-repo-check",
                        "materialize the structural package",
                    ],
                    "cwd_abs": str(repository),
                    "allowed_write_roots": [str(repository)],
                },
                {
                    "command_id": "ROOT-MATERIALIZATION-VERIFY",
                    "executable_abs": str(executable),
                    "executable_sha256": runtime.file_hash(executable),
                    "argv": [
                        str(executable),
                        "-m",
                        "unittest",
                        "discover",
                        "-s",
                        "tests",
                    ],
                    "cwd_abs": str(repository),
                    "allowed_write_roots": [str(repository)],
                },
            ],
            "verified_cli_schema": {
                "probe_argv": [str(executable), "exec", "--help"],
                "exit_code": 0,
                "required_tokens": ["--sandbox", "--skip-git-repo-check"],
                "help_sha256": "a" * 64,
                "schema_verified": True,
            },
        }

    @staticmethod
    def _authorization(hydration: dict) -> dict:
        codex = hydration["resolved_commands"][0]
        now = datetime.now(timezone.utc)
        return {
            "schema_version": "1.0",
            "authorization_id": "A3-E45-WORKPACK-01",
            "authorization_class": runtime.AUTHORIZATION_CLASS,
            "status": "GRANTED",
            "one_shot": True,
            "program_id": hydration["program_id"],
            "node_id": runtime.NODE_ID,
            "workpack_id": runtime.WORKPACK_ID,
            "candidate_tree_sha256": hydration["candidate_tree_sha256"],
            "hydration_sha256": hydration["hydration_sha256"],
            "resolved_command_sha256s": hydration[
                "resolved_command_sha256s"
            ],
            "provider_implementation_sha256": hydration[
                "provider_implementation_sha256"
            ],
            "codex_executable_sha256": codex["executable_sha256"],
            "codex_cli_help_sha256": hydration["codex_cli_schema"][
                "help_sha256"
            ],
            "allowed_write_roots": hydration["allowed_write_roots"],
            "max_transitions": 1,
            "max_loop_rounds": 1,
            "real_target_install_allowed": False,
            "validation_scope": runtime.VALIDATION_SCOPE,
            "network_allowed": False,
            "target_install_allowed": False,
            "delegation_allowed": False,
            "not_before": (now - timedelta(minutes=1)).isoformat().replace(
                "+00:00", "Z"
            ),
            "expires_at": (now + timedelta(minutes=30)).isoformat().replace(
                "+00:00", "Z"
            ),
        }

    def test_runtime_hydration_binds_candidate_overlay_cli_and_control_state(
        self,
    ) -> None:
        execution = self._execution_root("hydrate-pass")
        hydration = runtime.hydrate_workpack_runtime(
            self.candidate,
            execution,
            self._overlay(execution),
            verify_cli_schema=False,
        )
        self.assertEqual(hydration["status"], "READY_FOR_A3_PREPARATION")
        self.assertFalse(hydration["execution_authorized"])
        self.assertFalse(hydration["workpack_executed"])
        self.assertEqual(hydration["max_transitions"], 1)
        self.assertEqual(hydration["max_loop_rounds"], 1)
        self.assertEqual(
            hydration["hydration_sha256"],
            runtime.hash_without(hydration, "hydration_sha256"),
        )
        self.assertEqual(
            runtime.validate_a3_authorization(
                hydration, self._authorization(hydration)
            )["status"],
            "GRANTED",
        )

    def test_real_verifier_result_hydrates_successor_workpack(self) -> None:
        execution, command, authorization = self._verification_inputs(
            "real-successor-hydration"
        )
        committed = self.verification.execute_action(
            self.candidate, execution, command, authorization
        )
        self.assertEqual(committed["result"]["next_node"], runtime.NODE_ID)
        hydration = runtime.hydrate_workpack_runtime(
            self.candidate,
            execution,
            self._overlay(execution),
            verify_cli_schema=False,
        )
        self.assertEqual(hydration["status"], "READY_FOR_A3_PREPARATION")
        self.assertFalse(hydration["execution_authorized"])
        self.assertFalse((execution / runtime.REPOSITORY_REF).exists())
        self.assertFalse((execution / runtime.NODE_EVIDENCE_REF).exists())

    def test_runtime_rejects_hash_write_root_and_a3_scope_drift_before_execution(
        self,
    ) -> None:
        execution = self._execution_root("fail-closed")
        overlay = self._overlay(execution)
        overlay["commands"][0]["executable_sha256"] = "0" * 64
        with self.assertRaises(runtime.RuntimeContractError) as caught:
            runtime.hydrate_workpack_runtime(
                self.candidate, execution, overlay, verify_cli_schema=False
            )
        self.assertEqual(
            caught.exception.code, "COMMAND_OVERLAY_EXECUTABLE_INVALID"
        )
        self.assertFalse((execution / runtime.REPOSITORY_REF).exists())

        overlay = self._overlay(execution)
        overlay["allowed_write_roots"].append(str(execution / "outside"))
        with self.assertRaises(runtime.RuntimeContractError) as caught:
            runtime.hydrate_workpack_runtime(
                self.candidate, execution, overlay, verify_cli_schema=False
            )
        self.assertEqual(caught.exception.code, "COMMAND_OVERLAY_SCOPE_INVALID")

        hydration = runtime.hydrate_workpack_runtime(
            self.candidate,
            execution,
            self._overlay(execution),
            verify_cli_schema=False,
        )
        authorization = self._authorization(hydration)
        authorization["max_transitions"] = 2
        with self.assertRaises(runtime.RuntimeContractError) as caught:
            runtime.execute_hydrated_workpack(
                self.candidate, execution, hydration, authorization
            )
        self.assertEqual(caught.exception.code, "A3_AUTHORIZATION_INVALID")
        self.assertFalse((execution / runtime.REPOSITORY_REF).exists())

    def test_real_provider_uses_subprocess_and_stops_before_successor(self) -> None:
        execution = self._execution_root("execute-provider")
        hydration = runtime.hydrate_workpack_runtime(
            self.candidate,
            execution,
            self._overlay(execution),
            verify_cli_schema=False,
        )
        authorization = self._authorization(hydration)

        def completed(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            cwd = Path(str(kwargs["cwd"]))
            if argv[1] == "exec":
                (cwd / "src/package").mkdir(parents=True)
                (cwd / "tests").mkdir(parents=True)
                (cwd / "pyproject.toml").write_text("[project]\nname='x'\n")
                (cwd / "src/package/__init__.py").write_text("")
                (cwd / "tests/test_smoke.py").write_text("# structural fixture\n")
            return subprocess.CompletedProcess(argv, 0, "PASS", "")

        with patch.object(runtime.subprocess, "run", side_effect=completed) as run:
            result = runtime.execute_hydrated_workpack(
                self.candidate, execution, hydration, authorization
            )
        self.assertEqual(run.call_count, 2)
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["successor_started"])
        self.assertEqual(result["loop_rounds_consumed"], 0)
        self.assertEqual(
            result["produced_capabilities"],
            [
                "MAIN_EXECUTION_PACKAGE_MATERIALIZED_PASS",
                "MAIN_EXECUTION_PACKAGE_MATERIALIZED_READY",
            ],
        )
        evidence = execution / runtime.NODE_EVIDENCE_REF
        self.assertEqual(
            json.loads((evidence / "result.json").read_text()),
            result,
        )
        self.assertTrue((evidence / "ROOT-CODEX-CODING.stdout.txt").is_file())
        self.assertTrue((evidence / "ROOT-MATERIALIZATION-VERIFY.result.json").is_file())
        review = json.loads((evidence / "INDEPENDENT_REVIEW.json").read_text())
        self.assertEqual(review["status"], "PASS")
        self.assertEqual(review["verification_exit_code"], 0)

    def test_compiler_projects_provider_and_static_validator_rejects_drift(
        self,
    ) -> None:
        self.assertEqual(
            _check_controlled_workpack_runtime_executable_closure(
                self.candidate,
                active_requirement_epoch=47,
            ),
            [],
        )
        drifted = self.root / "drifted-candidate"
        shutil.copytree(self.candidate, drifted)
        provider = drifted / runtime.PROVIDER_IMPLEMENTATION_REF
        provider.write_text(
            provider.read_text(encoding="utf-8") + "\n# drift\n",
            encoding="utf-8",
        )
        codes = {
            finding["code"]
            for finding in _check_controlled_workpack_runtime_executable_closure(
                drifted,
                active_requirement_epoch=47,
            )
        }
        self.assertTrue(
            {
                "CONTROLLED_WORKPACK_RUNTIME_CONTRACT_INVALID",
                "CONTROLLED_WORKPACK_RUNTIME_PROJECTION_INVALID",
                "CONTROLLED_WORKPACK_RUNTIME_PORTABLE_BINDING_INVALID",
            }.intersection(codes)
        )

    def test_epoch47_successor_readiness_projects_runtime_closure(self) -> None:
        profile = json.loads(
            (self.candidate / "EPOCH38_GENERATION_PROFILE.json").read_text()
        )
        contract = json.loads(
            (
                self.candidate
                / "validation/CONTROLLED_WORKPACK_RUNTIME_CONTRACT.json"
            ).read_text()
        )
        self.assertEqual(profile["profile_origin_requirement_epoch"], 38)
        self.assertEqual(profile["active_requirement_epoch"], 47)
        self.assertEqual(contract["profile_origin_requirement_epoch"], 38)
        self.assertEqual(contract["active_requirement_epoch"], 47)

        with patch(
            "harness_foundry_factory.validator."
            "_factory_required_regression_execution",
            return_value=([], {}, False),
        ):
            report = validate_candidate(
                self.candidate,
                require_internal_report=False,
                authoritative_requirement_ir=self.requirement_ir,
                authority_provenance=self.authority_provenance,
            )
        check = next(
            item
            for item in report["checks"]
            if item["check_id"]
            == "CONTROLLED_WORKPACK_RUNTIME_EXECUTABLE_CLOSURE"
        )
        self.assertEqual(check["status"], "PASS")
        self.assertEqual(
            check["validation_basis"],
            "FACTORY_AUTHORITY_PROVENANCE_REQUIREMENT_EPOCH",
        )
        self.assertFalse(report["commands_executed"])

    def test_epoch47_static_validator_rejects_missing_runtime_artifact(
        self,
    ) -> None:
        missing = self.root / "missing-runtime-candidate"
        shutil.copytree(self.candidate, missing)
        (missing / runtime.PROVIDER_IMPLEMENTATION_REF).unlink()
        with patch(
            "harness_foundry_factory.validator."
            "_factory_required_regression_execution",
            return_value=([], {}, False),
        ):
            report = validate_candidate(
                missing,
                require_internal_report=False,
                authoritative_requirement_ir=self.requirement_ir,
                authority_provenance=self.authority_provenance,
            )
        check = next(
            item
            for item in report["checks"]
            if item["check_id"]
            == "CONTROLLED_WORKPACK_RUNTIME_EXECUTABLE_CLOSURE"
        )
        self.assertEqual(check["status"], "FAIL")
        self.assertIn(
            "CONTROLLED_WORKPACK_RUNTIME_ARTIFACT_MISSING",
            {finding["code"] for finding in check["findings"]},
        )
        self.assertFalse(report["commands_executed"])

    def test_epoch47_invalid_factory_binding_cannot_pass_outside_scope(
        self,
    ) -> None:
        invalid_provenance = dict(self.authority_provenance)
        invalid_provenance["requirement_ir_sha256"] = "0" * 64
        with patch(
            "harness_foundry_factory.validator."
            "_factory_required_regression_execution",
            return_value=([], {}, False),
        ):
            report = validate_candidate(
                self.candidate,
                require_internal_report=False,
                authoritative_requirement_ir=self.requirement_ir,
                authority_provenance=invalid_provenance,
            )
        check = next(
            item
            for item in report["checks"]
            if item["check_id"]
            == "CONTROLLED_WORKPACK_RUNTIME_EXECUTABLE_CLOSURE"
        )
        self.assertEqual(check["status"], "FAIL")
        self.assertEqual(
            check["validation_basis"],
            "FACTORY_AUTHORITY_PROVENANCE_INVALID",
        )
        self.assertIn(
            "CONTROLLED_WORKPACK_RUNTIME_FACTORY_AUTHORITY_PROVENANCE_INVALID",
            {finding["code"] for finding in check["findings"]},
        )
        self.assertFalse(report["commands_executed"])


if __name__ == "__main__":
    unittest.main()
