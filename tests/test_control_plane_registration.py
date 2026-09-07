"""Epoch 40 executable Control Plane Registration closure regressions."""

from __future__ import annotations

import importlib.util
import json
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
from harness_foundry_factory.validator import (
    _check_control_plane_registration_executable_closure,
)
from tests.test_generation_readiness import ROOT, _epoch38_fixture, _rehash
from tests.permissions import make_path_writable, make_tree_writable


class ControlPlaneRegistrationTests(unittest.TestCase):
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
                created_at="2026-08-13T00:00:00Z",
                spec_lock={"content_sha256": "fixture", "files": {}},
                authority_provenance={},
                generation_readiness=readiness,
            )
        cls.shared = cls._load_action(
            "generated_shared_control_baseline",
            cls.candidate / "tools/shared_control_baseline.py",
        )
        cls.registration = cls._load_action(
            "generated_control_plane_registration",
            cls.candidate / "tools/control_plane_registration.py",
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

    @staticmethod
    def _write_json(path: Path, value: dict) -> None:
        make_path_writable(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _candidate_snapshot(self) -> dict[str, str]:
        return {
            path.relative_to(self.candidate).as_posix(): self.shared.file_hash(path)
            for path in self.candidate.rglob("*")
            if path.is_file()
        }

    def _commit_shared_predecessor(self, name: str) -> Path:
        action = self.shared
        execution = self.root / name
        inputs = action._resolve_candidate_inputs(self.candidate)
        candidate_sha = action.candidate_identity(self.candidate)
        implementation_sha = action.file_hash(
            self.candidate / action.IMPLEMENTATION_REF
        )
        human = {
            "schema_version": "1.0",
            "receipt_id": f"HUMAN-{name}",
            "decision": "APPROVED",
            "program_id": inputs["program_id"],
            "candidate_tree_sha256": candidate_sha,
            "requirement_ir_sha256": inputs["requirement_ir_sha256"],
            "next_node": action.NODE_ID,
            "driver_start_authorized": False,
            "workpack_execution_authorized": False,
            "target_install_authorized": False,
        }
        human_path = execution / action.HUMAN_APPROVAL_REF
        self._write_json(human_path, human)
        state = {
            "schema_version": "1.0",
            "program_id": inputs["program_id"],
            "revision": 1,
            "control_plane_epoch": inputs["control_plane_epoch"],
            "epoch_domains": inputs["epoch_domains"],
            "next_node": action.NODE_ID,
            "next_fencing_token": 1,
            "last_event_hash": None,
            "active_authorization_id": f"AUTH-SHARED-{name}",
            "authorization_status": "GRANTED",
            "remaining_transition_budget": 1,
            "driver_started": False,
            "active_workpack": None,
            "state_sha256": "",
        }
        state["state_sha256"] = action.hash_without(state, "state_sha256")
        state_path = execution / action.CONTROL_STATE_REF
        self._write_json(state_path, state)
        lease_id = f"LEASE-SHARED-{name}"
        idempotency_key = action.json_hash(
            {
                "action_id": action.ACTION_ID,
                "authorization_id": f"AUTH-SHARED-{name}",
                "candidate_tree_sha256": candidate_sha,
                "fencing_token": 1,
                "lease_id": lease_id,
                "requirement_ir_sha256": inputs["requirement_ir_sha256"],
            }
        )
        command = {
            "schema_version": "1.0",
            "command_id": action.NODE_ID,
            "action_id": action.ACTION_ID,
            "node_id": action.NODE_ID,
            "authorization_id": f"AUTH-SHARED-{name}",
            "candidate_tree_sha256": candidate_sha,
            "requirement_ir_sha256": inputs["requirement_ir_sha256"],
            "executor_implementation_ref": action.IMPLEMENTATION_REF,
            "executor_implementation_sha256": implementation_sha,
            "action_contract_sha256": action.file_hash(
                self.candidate / action.ACTION_CONTRACT_REF
            ),
            "result_schema_sha256": action.file_hash(
                self.candidate / action.RESULT_SCHEMA_REF
            ),
            "human_approval_receipt_sha256": action.file_hash(human_path),
            "expected_control_state_sha256": action.file_hash(state_path),
            "idempotency_key": idempotency_key,
            "lease_id": lease_id,
            "fencing_token": 1,
        }
        command_path = execution / ".harness-foundry/control/action_inputs/shared.json"
        self._write_json(command_path, command)
        authorization = {
            "schema_version": "1.0",
            "authorization_id": f"AUTH-SHARED-{name}",
            "authorization_class": "REGISTRATION_AUTHORIZATION",
            "status": "GRANTED",
            "one_shot": True,
            "program_id": inputs["program_id"],
            "node_id": action.NODE_ID,
            "allowed_action_id": action.ACTION_ID,
            "command_manifest_sha256": action.file_hash(command_path),
            "candidate_tree_sha256": candidate_sha,
            "requirement_ir_sha256": inputs["requirement_ir_sha256"],
            "executor_implementation_sha256": implementation_sha,
            "human_approval_receipt_sha256": action.file_hash(human_path),
            "expected_control_state_sha256": action.file_hash(state_path),
            "idempotency_key": idempotency_key,
            "lease_id": lease_id,
            "fencing_token": 1,
            "not_before": "2020-01-01T00:00:00Z",
            "expires_at": "2100-01-01T00:00:00Z",
        }
        authorization_path = (
            execution / ".harness-foundry/control/authorizations/shared.json"
        )
        self._write_json(authorization_path, authorization)
        result = action.execute_action(
            self.candidate, execution, command_path, authorization_path
        )
        self.assertEqual(result["disposition"], "COMMITTED")
        return execution

    def _registration_inputs(
        self,
        name: str,
        *,
        executor_sha256: str | None = None,
        fencing_token: int | None = None,
    ) -> tuple[Path, Path, Path]:
        action = self.registration
        execution = self._commit_shared_predecessor(name)
        state_path = execution / action.CONTROL_STATE_REF
        state = json.loads(state_path.read_text(encoding="utf-8"))
        authorization_id = f"AUTH-REGISTER-{name}"
        state.update(
            {
                "active_authorization_id": authorization_id,
                "authorization_status": "GRANTED",
                "remaining_transition_budget": 1,
            }
        )
        state["state_sha256"] = action.hash_without(state, "state_sha256")
        self._write_json(state_path, state)

        contract = action.validate_static_contract(self.candidate)
        inputs = self.shared._resolve_candidate_inputs(self.candidate)
        candidate_sha = action.candidate_identity(self.candidate)
        implementation_sha = executor_sha256 or action.file_hash(
            self.candidate / action.IMPLEMENTATION_REF
        )
        predecessor_path = execution / action.PREDECESSOR_REF
        predecessor = json.loads(predecessor_path.read_text(encoding="utf-8"))
        predecessor_sha = action.file_hash(predecessor_path)
        runtime_bundle_sha = contract["runtime_bundle_sha256"]
        fencing = (
            state["next_fencing_token"]
            if fencing_token is None
            else fencing_token
        )
        lease_id = f"LEASE-REGISTER-{name}"
        idempotency_key = action.json_hash(
            {
                "action_id": action.ACTION_ID,
                "authorization_id": authorization_id,
                "candidate_tree_sha256": candidate_sha,
                "fencing_token": fencing,
                "lease_id": lease_id,
                "requirement_ir_sha256": inputs["requirement_ir_sha256"],
                "shared_control_baseline_result_sha256": predecessor_sha,
                "control_runtime_bundle_sha256": runtime_bundle_sha,
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
            "action_contract_sha256": action.file_hash(
                self.candidate / action.ACTION_CONTRACT_REF
            ),
            "result_schema_sha256": action.file_hash(
                self.candidate / action.RESULT_SCHEMA_REF
            ),
            "shared_control_baseline_result_sha256": predecessor_sha,
            "control_runtime_bundle_sha256": runtime_bundle_sha,
            "expected_control_state_sha256": action.file_hash(state_path),
            "idempotency_key": idempotency_key,
            "lease_id": lease_id,
            "fencing_token": fencing,
        }
        command_path = execution / ".harness-foundry/control/action_inputs/register.json"
        self._write_json(command_path, command)
        authorization = {
            "schema_version": "1.0",
            "authorization_id": authorization_id,
            "authorization_class": "REGISTRATION_AUTHORIZATION",
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
                "execution_mode": "REGISTRATION_ONLY",
                "runtime_internal_write_refs": action.RUNTIME_INTERNAL_WRITE_REFS,
            },
            "command_manifest_hashes": [action.file_hash(command_path)],
            "command_manifest_sha256": action.file_hash(command_path),
            "candidate_tree_sha256": candidate_sha,
            "requirement_ir_sha256": inputs["requirement_ir_sha256"],
            "executor_implementation_sha256": implementation_sha,
            "human_approval_receipt_sha256": predecessor[
                "human_approval_receipt_sha256"
            ],
            "shared_control_baseline_result_sha256": predecessor_sha,
            "control_runtime_bundle_sha256": runtime_bundle_sha,
            "expected_control_state_sha256": action.file_hash(state_path),
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
            execution / ".harness-foundry/control/authorizations/register.json"
        )
        self._write_json(authorization_path, authorization)
        return execution, command_path, authorization_path

    def test_real_compiler_binds_executable_registration_closure(self) -> None:
        self.assertEqual(
            _check_control_plane_registration_executable_closure(self.candidate),
            [],
        )
        contract = self.registration.validate_static_contract(self.candidate)
        manifest = json.loads(
            (self.candidate / "THREE_PROJECT_PROGRAM_MANIFEST.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            manifest["epoch_domains"],
            {
                "schema_version": "1.0",
                "architecture_epoch": 4,
                "architecture_control_plane_epoch": 4,
                "execution_control_plane_epoch": 0,
                "legacy_control_plane_epoch_alias": (
                    "execution_control_plane_epoch"
                ),
                "requirement_architecture_epoch": 4,
                "requirement_architecture_control_plane_epoch": 4,
                "projection_rule": "IDENTITY_REQUIREMENT_EPOCH_PROJECTION",
                "unbound_zero_semantics": False,
            },
        )
        self.assertEqual(
            contract["epoch_domain_contract"], manifest["epoch_domains"]
        )
        self.assertEqual(
            contract["runtime_module_refs"],
            [
                "tools/harness_foundry_runtime/control_kernel.py",
                "tools/harness_foundry_runtime/local_runtime.py",
                "tools/harness_foundry_runtime/local_process.py",
                "tools/harness_foundry_runtime/startup_runtime.py",
                "tools/harness_foundry_runtime/store.py",
                "tools/harness_foundry_runtime/models.py",
                "tools/harness_foundry_runtime/constants.py",
            ],
        )
        dag = json.loads(
            (self.candidate / "ENGINEERING_PROJECT_DAG.json").read_text()
        )
        node = next(
            item
            for item in dag["nodes"]
            if item["node_id"] == "CONTROL_PLANE_REGISTRATION"
        )
        self.assertEqual(
            node["executor_implementation_ref"],
            self.registration.IMPLEMENTATION_REF,
        )
        self.assertEqual(
            node["transaction_protocol"],
            "JOURNALED_ATOMIC_RECONCILIATION_V1",
        )
        authorization_profile = contract["authorization_profile"]
        self.assertEqual(
            authorization_profile["assurance_profile"],
            "SELF_USE_LOCAL_TRUSTED_OPERATOR",
        )
        self.assertEqual(
            authorization_profile["issuer_role"], "LOCAL_TRUSTED_OPERATOR"
        )
        self.assertEqual(authorization_profile["max_transitions"], 1)
        self.assertFalse(authorization_profile["delegation_allowed"])
        self.assertEqual(
            authorization_profile["signature_policy"],
            "NOT_APPLICABLE_SELF_USE_LOCAL_TRUSTED_OPERATOR",
        )
        self.assertEqual(
            node["runtime_internal_write_refs"],
            contract["runtime_internal_write_refs"],
        )
        policy = json.loads(
            (self.candidate / "AUTHORIZATION_POLICY.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            policy["profile_authorization_schemas"]
            ["SELF_USE_LOCAL_TRUSTED_OPERATOR"]
            ["REGISTRATION_AUTHORIZATION"],
            authorization_profile,
        )
        negatives = json.loads(
            (self.candidate / "validation/NEGATIVE_CASES.json").read_text(
                encoding="utf-8"
            )
        )
        registration_cases = {
            case["case_id"]: case
            for case in negatives["cases"]
            if case["case_id"].startswith("NEG-V29-E41-REGISTRATION-")
        }
        self.assertEqual(
            set(registration_cases),
            {
                "NEG-V29-E41-REGISTRATION-AUTHORITY-SCOPE",
                "NEG-V29-E41-REGISTRATION-HUMAN-SIGNATURE-PROFILE",
                "NEG-V29-E41-REGISTRATION-INTERNAL-WRITE-CONTAINMENT",
            },
        )
        self.assertTrue(
            all(
                case["fixture_kind"] == "NON_EXECUTABLE_JSON"
                for case in registration_cases.values()
            )
        )

    def test_static_validator_rejects_profile_or_internal_write_drift(self) -> None:
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            candidate = Path(temporary) / "candidate"
            shutil.copytree(self.candidate, candidate)
            policy_path = candidate / "AUTHORIZATION_POLICY.json"
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["profile_authorization_schemas"][
                "SELF_USE_LOCAL_TRUSTED_OPERATOR"
            ]["REGISTRATION_AUTHORIZATION"]["issuer_role"] = "OTHER_ROLE"
            self._write_json(policy_path, policy)
            codes = {
                finding["code"]
                for finding in _check_control_plane_registration_executable_closure(
                    candidate
                )
            }
            self.assertIn(
                "CONTROL_PLANE_REGISTRATION_AUTHORIZATION_POLICY_INVALID", codes
            )

        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            candidate = Path(temporary) / "candidate"
            shutil.copytree(self.candidate, candidate)
            dag_path = candidate / "ENGINEERING_PROJECT_DAG.json"
            dag = json.loads(dag_path.read_text(encoding="utf-8"))
            node = next(
                item
                for item in dag["nodes"]
                if item["node_id"] == "CONTROL_PLANE_REGISTRATION"
            )
            node["runtime_internal_write_refs"] = [
                "harness-resource://candidate/forbidden-write.json"
            ]
            self._write_json(dag_path, dag)
            codes = {
                finding["code"]
                for finding in _check_control_plane_registration_executable_closure(
                    candidate
                )
            }
            self.assertIn("CONTROL_PLANE_REGISTRATION_DAG_BINDING_INVALID", codes)

        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            candidate = Path(temporary) / "candidate"
            shutil.copytree(self.candidate, candidate)
            contract_path = (
                candidate
                / "validation/CONTROL_PLANE_REGISTRATION_ACTION_CONTRACT.json"
            )
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["authorization_profile"]["scope_contract"] = []
            contract["contract_sha256"] = self.registration.hash_without(
                contract, "contract_sha256"
            )
            self._write_json(contract_path, contract)
            with self.assertRaises(self.registration.ContractError) as caught:
                self.registration.validate_static_contract(candidate)
            self.assertEqual(
                caught.exception.code,
                "CONTROL_PLANE_REGISTRATION_CONTRACT_INVALID",
            )

    def test_unmodified_candidate_self_check_accepts_static_closure(self) -> None:
        completed = subprocess.run(
            [sys.executable, "tools/self_check.py"],
            cwd=self.candidate,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(json.loads(completed.stdout)["status"], "PASS")
        # This deliberately minimal startup closure has the shared local
        # receiver, not the optional full Workpack verification planner.
        self.assertFalse((self.candidate / "tools/harness_foundry_runtime/project_verification.py").exists())
        code = ("import sys; sys.path.insert(0, 'tools'); "
                "from harness_foundry_runtime.local_runtime import _verification_provider; "
                "assert _verification_provider({'command_id':'TEST-LOCAL','executor_role':'LOCAL_PROCESS'}) is None; "
                "print('BASE_LOCAL_RECEIVER_IMPORT_PASS')")
        imported = subprocess.run([sys.executable, "-B", "-c", code], cwd=self.candidate,
                                  capture_output=True, text=True, check=False)
        self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)

    def test_registration_commits_once_without_starting_driver_or_workpack(self) -> None:
        before = self._candidate_snapshot()
        execution, command, authorization = self._registration_inputs("success")
        first = self.registration.execute_action(
            self.candidate, execution, command, authorization
        )
        second = self.registration.execute_action(
            self.candidate, execution, command, authorization
        )
        self.assertEqual(first["disposition"], "COMMITTED")
        self.assertEqual(second["disposition"], "ALREADY_COMMITTED")
        self.assertEqual(first["result"], second["result"])
        self.assertFalse(first["result"]["driver_started"])
        self.assertFalse(first["result"]["workpack_started"])
        events = self.registration.read_events(
            execution / self.registration.CONTROL_EVENTS_REF
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(events[-1]["event_type"], "CONTROL_PLANE_REGISTRATION_COMMITTED")
        state = json.loads(
            (execution / self.registration.CONTROL_STATE_REF).read_text()
        )
        self.assertEqual(state["last_completed_node"], "CONTROL_PLANE_REGISTRATION")
        self.assertEqual(state["next_node"], "PROGRAM_DRIVER_RUNTIME_VERIFIED")
        self.assertEqual(state["authorization_status"], "CONSUMED")
        self.assertEqual(state["remaining_transition_budget"], 0)
        self.assertFalse(state["driver_started"])
        self.assertIsNone(state["active_workpack"])
        self.assertEqual(before, self._candidate_snapshot())

    def test_local_profile_authorization_fields_fail_closed(self) -> None:
        mutations = {
            "missing-issuer": lambda value: value.pop("issuer_role"),
            "wrong-scope": lambda value: value["scope"].update(
                {"node_id": "WRONG_NODE"}
            ),
            "expanded-budget": lambda value: value.update({"max_transitions": 2}),
            "missing-human-receipt": lambda value: value.pop(
                "human_approval_receipt_sha256"
            ),
            "delegation": lambda value: value.update({"delegation_allowed": True}),
            "external-signature": lambda value: value.update(
                {
                    "signature_policy": "EXTERNAL_SIGNATURE_REQUIRED",
                    "signature": "FORGED",
                }
            ),
            "wrong-command-set": lambda value: value.update(
                {"command_manifest_hashes": ["0" * 64]}
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                execution, command, authorization = self._registration_inputs(
                    f"authorization-{name}"
                )
                payload = json.loads(authorization.read_text(encoding="utf-8"))
                mutate(payload)
                self._write_json(authorization, payload)
                with self.assertRaises(self.registration.ContractError) as caught:
                    self.registration.execute_action(
                        self.candidate, execution, command, authorization
                    )
                self.assertEqual(
                    caught.exception.code, "REGISTRATION_AUTHORIZATION_INVALID"
                )
                self.assertFalse(
                    (execution / self.registration.TRANSACTION_REF).exists()
                )

    def test_every_declared_crash_boundary_recovers_without_duplicate_event(self) -> None:
        for index, point in enumerate(sorted(self.registration.CRASH_POINTS), 1):
            with self.subTest(point=point):
                execution, command, authorization = self._registration_inputs(
                    f"crash-{index}"
                )
                with self.assertRaises(self.registration.InjectedCrash):
                    self.registration.execute_action(
                        self.candidate,
                        execution,
                        command,
                        authorization,
                        crash_after=point,
                    )
                recovered = self.registration.execute_action(
                    self.candidate, execution, command, authorization
                )
                self.assertEqual(recovered["status"], "PASS")
                events = self.registration.read_events(
                    execution / self.registration.CONTROL_EVENTS_REF
                )
                self.assertEqual(
                    len(
                        [
                            event
                            for event in events
                            if event["node_id"] == self.registration.NODE_ID
                        ]
                    ),
                    1,
                )
                receipt = json.loads(
                    (execution / self.registration.RECOVERY_REF).read_text()
                )
                self.assertTrue(receipt["recovered"])
                self.assertEqual(receipt["duplicate_side_effect_count"], 0)

    def test_hash_binding_and_state_cas_fail_before_transaction(self) -> None:
        execution, command, authorization = self._registration_inputs(
            "executor-drift", executor_sha256="0" * 64
        )
        with self.assertRaises(self.registration.ContractError) as caught:
            self.registration.execute_action(
                self.candidate, execution, command, authorization
            )
        self.assertEqual(
            caught.exception.code,
            "UNBOUND_OR_DRIFTED_CONTROL_ACTION_IMPLEMENTATION",
        )
        self.assertFalse((execution / self.registration.TRANSACTION_REF).exists())

        execution, command, authorization = self._registration_inputs(
            "fencing-regression", fencing_token=1
        )
        with self.assertRaises(self.registration.ContractError) as caught:
            self.registration.execute_action(
                self.candidate, execution, command, authorization
            )
        self.assertEqual(caught.exception.code, "FENCING_TOKEN_REGRESSION")
        self.assertFalse((execution / self.registration.TRANSACTION_REF).exists())

        execution, command, authorization = self._registration_inputs("state-drift")
        state_path = execution / self.registration.CONTROL_STATE_REF
        state = json.loads(state_path.read_text())
        state["revision"] += 1
        state["state_sha256"] = self.registration.hash_without(
            state, "state_sha256"
        )
        self._write_json(state_path, state)
        with self.assertRaises(self.registration.ContractError) as caught:
            self.registration.execute_action(
                self.candidate, execution, command, authorization
            )
        self.assertEqual(caught.exception.code, "COMMAND_MANIFEST_INVALID")
        self.assertFalse((execution / self.registration.TRANSACTION_REF).exists())


if __name__ == "__main__":
    unittest.main()
