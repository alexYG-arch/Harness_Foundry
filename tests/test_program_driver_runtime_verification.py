"""Epoch 43 portable Program Driver runtime-verification regressions."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
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
from harness_foundry_factory.validator import (
    _check_program_driver_runtime_verification_executable_closure,
)
from tests import test_control_plane_registration as registration_test_support
from tests.test_generation_readiness import ROOT, _epoch38_fixture, _rehash
from tests.permissions import make_path_writable, make_tree_writable


class ProgramDriverRuntimeVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name).resolve()
        cls.candidate = cls.root / "candidate"
        fixture = _epoch38_fixture(
            cls.candidate,
            active_requirement_epoch=40,
            include_shared_control_baseline=True,
        )
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
                    "validation_basis": (
                        "FACTORY_SUPPLIED_LOCAL_CONSISTENCY_INPUT"
                    ),
                },
                {
                    "check_id": "FACTORY_LOCAL_REQUIREMENT_IR_CONSISTENCY",
                    "status": "PASS",
                    "findings": [],
                    "validation_basis": (
                        "FACTORY_SUPPLIED_LOCAL_CONSISTENCY_INPUT"
                    ),
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
                created_at="2026-08-19T00:00:00Z",
                spec_lock={"content_sha256": "fixture", "files": {}},
                authority_provenance={},
                generation_readiness=readiness,
            )
        cls.shared = cls._load_action(
            "driver_verify_shared",
            cls.candidate / "tools/shared_control_baseline.py",
        )
        cls.registration = cls._load_action(
            "driver_verify_registration",
            cls.candidate / "tools/control_plane_registration.py",
        )
        cls.verification = cls._load_action(
            "generated_program_driver_runtime_verification",
            cls.candidate / "tools/program_driver_runtime_verification.py",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        make_tree_writable(cls.root)
        cls.temporary.cleanup()

    @staticmethod
    def _load_action(name: str, path: Path):
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot import generated action: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    _write_json = staticmethod(
        registration_test_support.ControlPlaneRegistrationTests._write_json
    )
    _commit_shared_predecessor = (
        registration_test_support.ControlPlaneRegistrationTests._commit_shared_predecessor
    )
    _registration_inputs = (
        registration_test_support.ControlPlaneRegistrationTests._registration_inputs
    )
    _candidate_snapshot = (
        registration_test_support.ControlPlaneRegistrationTests._candidate_snapshot
    )

    def _commit_registration(self, name: str) -> Path:
        execution, command, authorization = self._registration_inputs(name)
        result = self.registration.execute_action(
            self.candidate, execution, command, authorization
        )
        self.assertEqual(result["disposition"], "COMMITTED")
        return execution

    def _verification_inputs(
        self,
        name: str,
        *,
        entrypoint_sha256: str | None = None,
        fencing_token: int | None = None,
    ) -> tuple[Path, Path, Path]:
        action = self.verification
        execution = self._commit_registration(name)
        state_path = execution / action.CONTROL_STATE_REF
        state = json.loads(state_path.read_text(encoding="utf-8"))
        authorization_id = f"AUTH-DRIVER-VERIFY-{name}"
        state.update(
            {
                "active_authorization_id": authorization_id,
                "authorization_status": "GRANTED",
                "remaining_transition_budget": 1,
            }
        )
        state["state_sha256"] = action.hash_without(state, "state_sha256")
        self._write_json(state_path, state)
        inputs = self.shared._resolve_candidate_inputs(self.candidate)
        candidate_sha = action.candidate_identity(self.candidate)
        predecessor_path = execution / action.PREDECESSOR_REF
        predecessor_sha = action.file_hash(predecessor_path)
        baseline_path = execution / action.HUMAN_BINDING_PREDECESSOR_REF
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        implementation_sha = action.file_hash(
            self.candidate / action.IMPLEMENTATION_REF
        )
        entrypoint_sha = entrypoint_sha256 or action.file_hash(
            self.candidate / action.DRIVER_ENTRYPOINT_REF
        )
        fencing = (
            state["next_fencing_token"]
            if fencing_token is None
            else fencing_token
        )
        lease_id = f"LEASE-DRIVER-VERIFY-{name}"
        idempotency_key = action.json_hash(
            {
                "action_id": action.ACTION_ID,
                "authorization_id": authorization_id,
                "candidate_tree_sha256": candidate_sha,
                "control_plane_registration_result_sha256": predecessor_sha,
                "driver_entrypoint_sha256": entrypoint_sha,
                "fencing_token": fencing,
                "lease_id": lease_id,
                "requirement_ir_sha256": inputs["requirement_ir_sha256"],
            }
        )
        command = {
            "schema_version": "1.0",
            "command_id": action.NODE_ID,
            "action_id": action.ACTION_ID,
            "node_id": action.NODE_ID,
            "authorization_id": authorization_id,
            "candidate_tree_sha256": candidate_sha,
            "requirement_ir_sha256": inputs["requirement_ir_sha256"],
            "executor_implementation_ref": action.IMPLEMENTATION_REF,
            "executor_implementation_sha256": implementation_sha,
            "driver_entrypoint_ref": action.DRIVER_ENTRYPOINT_REF,
            "driver_entrypoint_sha256": entrypoint_sha,
            "action_contract_sha256": action.file_hash(
                self.candidate / action.ACTION_CONTRACT_REF
            ),
            "result_schema_sha256": action.file_hash(
                self.candidate / action.RESULT_SCHEMA_REF
            ),
            "control_plane_registration_result_sha256": predecessor_sha,
            "expected_control_state_sha256": action.file_hash(state_path),
            "expected_event_tip": state["last_event_hash"],
            "read_only_probe_commands": list(action.PROBE_COMMANDS),
            "idempotency_key": idempotency_key,
            "lease_id": lease_id,
            "fencing_token": fencing,
        }
        command_path = (
            execution
            / ".harness-foundry/control/action_inputs/driver-verify.json"
        )
        self._write_json(command_path, command)
        authorization = {
            "schema_version": "1.0",
            "authorization_id": authorization_id,
            "authorization_class": "PROJECT_VALIDATION_AUTHORIZATION",
            "status": "GRANTED",
            "one_shot": True,
            "program_id": inputs["program_id"],
            "issuer_role": "LOCAL_TRUSTED_OPERATOR",
            "issued_at": "2020-01-01T00:00:00Z",
            "node_id": action.NODE_ID,
            "allowed_action_id": action.ACTION_ID,
            "scope": {
                "program_id": inputs["program_id"],
                "node_id": action.NODE_ID,
                "allowed_action_id": action.ACTION_ID,
                "execution_mode": "PROJECT_VALIDATION",
                "read_only_probe_commands": list(action.PROBE_COMMANDS),
                "runtime_internal_write_refs": action.RUNTIME_INTERNAL_WRITE_REFS,
            },
            "command_manifest_hashes": [action.file_hash(command_path)],
            "command_manifest_sha256": action.file_hash(command_path),
            "candidate_tree_sha256": candidate_sha,
            "requirement_ir_sha256": inputs["requirement_ir_sha256"],
            "executor_implementation_sha256": implementation_sha,
            "driver_entrypoint_sha256": entrypoint_sha,
            "human_approval_receipt_sha256": baseline[
                "human_approval_receipt_sha256"
            ],
            "control_plane_registration_result_sha256": predecessor_sha,
            "expected_control_state_sha256": action.file_hash(state_path),
            "expected_event_tip": state["last_event_hash"],
            "read_only_probe_commands": list(action.PROBE_COMMANDS),
            "forbidden_actions": list(action.FORBIDDEN_ACTIONS),
            "idempotency_key": idempotency_key,
            "lease_id": lease_id,
            "fencing_token": fencing,
            "max_transitions": 1,
            "delegation_allowed": False,
            "signature_policy": (
                "NOT_APPLICABLE_SELF_USE_LOCAL_TRUSTED_OPERATOR"
            ),
            "signature": None,
            "not_before": "2020-01-01T00:00:00Z",
            "expires_at": "2100-01-01T00:00:00Z",
        }
        authorization_path = (
            execution
            / ".harness-foundry/control/authorizations/driver-verify.json"
        )
        self._write_json(authorization_path, authorization)
        return execution, command_path, authorization_path

    def test_real_compiler_binds_driver_runtime_verification_closure(self) -> None:
        self.assertEqual(
            _check_program_driver_runtime_verification_executable_closure(
                self.candidate
            ),
            [],
        )
        contract = self.verification.validate_static_contract(self.candidate)
        self.assertEqual(
            contract["read_only_probe_commands"],
            ["status", "plan-next", "validate-transition"],
        )
        driver = json.loads(
            (self.candidate / "PROGRAM_DRIVER_CONTRACT.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIsNotNone(driver["runtime_verification_ref"])
        self.assertEqual(
            driver["driver_entrypoint_ref"], "tools/program_driver.py"
        )
        self.assertEqual(
            driver["driver_entrypoint_abs"],
            (
                "harness-resource://execution/control_plane/.venv/bin/"
                "program-driver"
            ),
        )
        negatives = json.loads(
            (self.candidate / "validation/NEGATIVE_CASES.json").read_text(
                encoding="utf-8"
            )
        )
        cases = [
            case
            for case in negatives["cases"]
            if case["case_id"].startswith("NEG-V29-E43-DRIVER-VERIFY-")
        ]
        self.assertEqual(len(cases), 3)
        self.assertTrue(
            all(case["fixture_kind"] == "NON_EXECUTABLE_JSON" for case in cases)
        )

    def test_read_only_driver_probes_do_not_mutate_candidate_or_runtime(self) -> None:
        execution = self._commit_registration("read-only-probes")
        candidate_before = self._candidate_snapshot()
        execution_before = self.verification._tree_snapshot(execution)
        results = {
            command: self.verification._run_read_only_probes(
                self.candidate,
                execution,
                candidate_sha=self.verification.candidate_identity(self.candidate),
                state_file_sha=self.verification.file_hash(
                    execution / self.verification.CONTROL_STATE_REF
                ),
                state_payload_sha=json.loads(
                    (
                        execution / self.verification.CONTROL_STATE_REF
                    ).read_text(encoding="utf-8")
                )["state_sha256"],
            )[command]
            for command in ("status",)
        }
        self.assertTrue(results["status"]["read_only"])
        self.assertEqual(candidate_before, self._candidate_snapshot())
        self.assertEqual(
            execution_before, self.verification._tree_snapshot(execution)
        )

    def test_verification_commits_once_without_starting_driver_or_workpack(self) -> None:
        before = self._candidate_snapshot()
        execution, command, authorization = self._verification_inputs("success")
        first = self.verification.execute_action(
            self.candidate, execution, command, authorization
        )
        second = self.verification.execute_action(
            self.candidate, execution, command, authorization
        )
        self.assertEqual(first["disposition"], "COMMITTED")
        self.assertEqual(second["disposition"], "ALREADY_COMMITTED")
        self.assertEqual(first["result"], second["result"])
        self.assertEqual(
            first["result"]["next_node"],
            "MAIN_EXECUTION_PACKAGE_MATERIALIZED",
        )
        self.assertFalse(first["result"]["driver_started"])
        self.assertFalse(first["result"]["workpack_started"])
        events = self.verification.read_events(
            execution / self.verification.CONTROL_EVENTS_REF
        )
        self.assertEqual(
            len(
                [
                    event
                    for event in events
                    if event["node_id"] == self.verification.NODE_ID
                ]
            ),
            1,
        )
        state = json.loads(
            (execution / self.verification.CONTROL_STATE_REF).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            state["last_completed_node"], "PROGRAM_DRIVER_RUNTIME_VERIFIED"
        )
        self.assertEqual(
            state["next_node"], "MAIN_EXECUTION_PACKAGE_MATERIALIZED"
        )
        self.assertFalse(state["driver_started"])
        self.assertIsNone(state["active_workpack"])
        self.assertEqual(before, self._candidate_snapshot())

    def test_hash_authorization_and_fencing_fail_before_transaction(self) -> None:
        execution, command, authorization = self._verification_inputs(
            "entrypoint-drift", entrypoint_sha256="0" * 64
        )
        with self.assertRaises(self.verification.ContractError) as caught:
            self.verification.execute_action(
                self.candidate, execution, command, authorization
            )
        self.assertEqual(
            caught.exception.code,
            "UNBOUND_OR_DRIFTED_PROGRAM_DRIVER_ENTRYPOINT",
        )
        self.assertFalse((execution / self.verification.TRANSACTION_REF).exists())

        execution, command, authorization = self._verification_inputs(
            "fencing-regression", fencing_token=1
        )
        with self.assertRaises(self.verification.ContractError) as caught:
            self.verification.execute_action(
                self.candidate, execution, command, authorization
            )
        self.assertEqual(caught.exception.code, "FENCING_TOKEN_REGRESSION")
        self.assertFalse((execution / self.verification.TRANSACTION_REF).exists())

        execution, command, authorization = self._verification_inputs(
            "scope-expansion"
        )
        payload = json.loads(authorization.read_text(encoding="utf-8"))
        payload["scope"]["read_only_probe_commands"] = ["advance"]
        self._write_json(authorization, payload)
        with self.assertRaises(self.verification.ContractError) as caught:
            self.verification.execute_action(
                self.candidate, execution, command, authorization
            )
        self.assertEqual(
            caught.exception.code, "PROJECT_VALIDATION_AUTHORIZATION_INVALID"
        )
        self.assertFalse((execution / self.verification.TRANSACTION_REF).exists())

    def test_static_validator_rejects_policy_and_entrypoint_drift(self) -> None:
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            candidate = Path(temporary) / "candidate"
            shutil.copytree(self.candidate, candidate)
            policy_path = candidate / "AUTHORIZATION_POLICY.json"
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["profile_authorization_schemas"][
                "SELF_USE_LOCAL_TRUSTED_OPERATOR"
            ]["PROJECT_VALIDATION_AUTHORIZATION"]["issuer_role"] = "OTHER"
            self._write_json(policy_path, policy)
            codes = {
                finding["code"]
                for finding in _check_program_driver_runtime_verification_executable_closure(
                    candidate
                )
            }
            self.assertIn(
                "PROGRAM_DRIVER_RUNTIME_VERIFICATION_AUTHORIZATION_POLICY_INVALID",
                codes,
            )

        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            candidate = Path(temporary) / "candidate"
            shutil.copytree(self.candidate, candidate)
            entrypoint = candidate / "tools/program_driver.py"
            make_path_writable(entrypoint)
            entrypoint.write_text(
                entrypoint.read_text(encoding="utf-8") + "\n# drift\n",
                encoding="utf-8",
            )
            codes = {
                finding["code"]
                for finding in _check_program_driver_runtime_verification_executable_closure(
                    candidate
                )
            }
            self.assertTrue(
                {
                    "PROGRAM_DRIVER_RUNTIME_VERIFICATION_CONTRACT_INVALID",
                    "PROGRAM_DRIVER_RUNTIME_VERIFICATION_DAG_BINDING_INVALID",
                }.intersection(codes)
            )

        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            candidate = Path(temporary) / "candidate"
            shutil.copytree(self.candidate, candidate)
            schema_path = (
                candidate
                / "contracts/PROGRAM_DRIVER_RUNTIME_VERIFICATION_RESULT.schema.json"
            )
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            schema["properties"]["next_node"]["const"] = "OTHER"
            self._write_json(schema_path, schema)
            codes = {
                finding["code"]
                for finding in _check_program_driver_runtime_verification_executable_closure(
                    candidate
                )
            }
            self.assertIn(
                "PROGRAM_DRIVER_RUNTIME_VERIFICATION_RESULT_SCHEMA_INVALID",
                codes,
            )


if __name__ == "__main__":
    unittest.main()
