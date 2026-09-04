"""Epoch 49 Main Execution Package structural-validation regressions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
from harness_foundry_factory.models import content_sha256
from harness_foundry_factory.validator import (
    _check_main_execution_package_validation_executable_closure,
)
from tests.test_generation_readiness import ROOT, _epoch38_fixture, _rehash
from tests.permissions import make_path_writable, make_tree_writable


class MainExecutionPackageValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name).resolve()
        cls.candidate = cls.root / "candidate"
        fixture = _epoch38_fixture(
            cls.candidate,
            active_requirement_epoch=49,
            include_active_requirement_marker=False,
            include_shared_control_baseline=True,
            program_id="PROGRAM-HARNESS-FOUNDRY-V2-9-UPGRADE",
            target_id="HARNESS-FOUNDRY-V2-9-CHAT-FACTORY",
        )
        cls.requirement_ir = fixture["snapshot"]["requirement_ir"]
        cls.authority_provenance = {
            "event_store_revision": 49,
            "event_store_tip_sha256": "f" * 64,
            "requirement_epoch": 49,
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
                cls.requirement_ir,
                spec_root=ROOT.parent / "Harness_Foundry_v2_8_Start_Package",
                staging_root=cls.root / "staging",
                candidate_root=cls.candidate,
                created_at="2026-08-28T00:00:00Z",
                spec_lock={"content_sha256": "fixture", "files": {}},
                authority_provenance=cls.authority_provenance,
                generation_readiness=readiness,
            )
        cls.action = cls._load_action(
            "generated_main_execution_package_validation",
            cls.candidate
            / "tools/harness_foundry_runtime/main_execution_package_validation.py",
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
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

    def _prepare_inputs(self, name: str) -> tuple[Path, Path, Path]:
        action = self.action
        execution = self.root / name
        execution.mkdir()
        repository = execution / action.REPOSITORY_REF
        self._write_json(
            repository / "src/harness_foundry_v2_9/package_contract.json",
            {"schema_version": "1.0", "status": "STRUCTURAL"},
        )
        (repository / "src/harness_foundry_v2_9/__init__.py").write_text(
            '"""fixture"""\n', encoding="utf-8"
        )
        (repository / "tests").mkdir(parents=True)
        (repository / "tests/test_package.py").write_text(
            "import unittest\n\nclass PackageTests(unittest.TestCase):\n    pass\n",
            encoding="utf-8",
        )
        (repository / "pyproject.toml").write_text(
            "[project]\nname = \"harness-foundry-v2-9\"\nversion = \"0.1.0\"\n",
            encoding="utf-8",
        )
        repository_files = action._tree_snapshot(repository)
        repository_tree_sha = action.json_hash(repository_files)
        candidate_sha = action.candidate_identity(self.candidate)
        postflight = {
            "status": "PASS",
            "validation_scope": action.VALIDATION_SCOPE,
            "tree_sha256": repository_tree_sha,
        }
        predecessor = {
            "schema_version": "1.0",
            "status": "PASS",
            "program_id": "PROGRAM-HARNESS-FOUNDRY-V2-9-UPGRADE",
            "node_id": action.PREDECESSOR_NODE_ID,
            "workpack_id": action.WORKPACK_ID,
            "candidate_tree_sha256": candidate_sha,
            "postflight": postflight,
            "independent_review": dict(postflight),
            "validation_scope": action.VALIDATION_SCOPE,
            "produced_capabilities": [
                "MAIN_EXECUTION_PACKAGE_MATERIALIZED_PASS",
                "MAIN_EXECUTION_PACKAGE_MATERIALIZED_READY",
            ],
            "successor_started": False,
            "result_sha256": "",
        }
        predecessor["result_sha256"] = action.hash_without(
            predecessor, "result_sha256"
        )
        predecessor_path = execution / action.PREDECESSOR_RESULT_REF
        self._write_json(predecessor_path, predecessor)
        predecessor_sha = action.file_hash(predecessor_path)

        event = {
            "schema_version": "1.0",
            "event_type": "MAIN_EXECUTION_PACKAGE_MATERIALIZED_ACCEPTED",
            "previous_event_hash": None,
            "event_hash": "",
        }
        event["event_hash"] = action.hash_without(event, "event_hash")
        events_path = execution / action.CONTROL_EVENTS_REF
        events_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.write_text(
            json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        inputs = action.base._resolve_candidate_inputs(self.candidate)
        authorization_id = f"AUTH-MAIN-PACKAGE-VALIDATE-{name}"
        state = {
            "schema_version": "1.0",
            "program_id": inputs["program_id"],
            "revision": 6,
            "epoch_domains": inputs["epoch_domains"],
            "control_plane_epoch": inputs["execution_control_plane_epoch"],
            "last_completed_node": action.PREDECESSOR_NODE_ID,
            "next_node": action.NODE_ID,
            "next_fencing_token": 5,
            "last_event_hash": event["event_hash"],
            "active_authorization_id": authorization_id,
            "authorization_status": "GRANTED",
            "remaining_transition_budget": 1,
            "driver_started": False,
            "active_workpack": None,
            "state_sha256": "",
        }
        state["state_sha256"] = action.hash_without(state, "state_sha256")
        state_path = execution / action.CONTROL_STATE_REF
        self._write_json(state_path, state)
        fencing_token = 5
        lease_id = f"LEASE-MAIN-PACKAGE-VALIDATE-{name}"
        idempotency_key = action.json_hash(
            {
                "action_id": action.ACTION_ID,
                "authorization_id": authorization_id,
                "candidate_tree_sha256": candidate_sha,
                "fencing_token": fencing_token,
                "lease_id": lease_id,
                "materialization_result_sha256": predecessor_sha,
                "materialized_repository_tree_sha256": repository_tree_sha,
                "requirement_ir_sha256": inputs["requirement_ir_sha256"],
            }
        )
        implementation_sha = action.file_hash(
            self.candidate / action.IMPLEMENTATION_REF
        )
        entrypoint_sha = action.file_hash(self.candidate / action.ENTRYPOINT_REF)
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
            "runtime_entrypoint_ref": action.ENTRYPOINT_REF,
            "runtime_entrypoint_sha256": entrypoint_sha,
            "action_contract_sha256": action.file_hash(
                self.candidate / action.ACTION_CONTRACT_REF
            ),
            "result_schema_sha256": action.file_hash(
                self.candidate / action.RESULT_SCHEMA_REF
            ),
            "materialization_result_sha256": predecessor_sha,
            "materialized_repository_tree_sha256": repository_tree_sha,
            "expected_control_state_sha256": action.file_hash(state_path),
            "expected_event_tip": event["event_hash"],
            "node_evidence_write_ref": action.NODE_EVIDENCE_WRITE_REF,
            "validation_scope": action.VALIDATION_SCOPE,
            "idempotency_key": idempotency_key,
            "lease_id": lease_id,
            "fencing_token": fencing_token,
        }
        command_path = (
            execution
            / ".harness-foundry/control/action_inputs/main-package-validation.json"
        )
        self._write_json(command_path, command)
        now = datetime.now(timezone.utc)
        authorization = {
            "schema_version": "1.0",
            "authorization_id": authorization_id,
            "authorization_class": "PROJECT_VALIDATION_AUTHORIZATION",
            "status": "GRANTED",
            "one_shot": True,
            "program_id": inputs["program_id"],
            "issuer_role": "LOCAL_TRUSTED_OPERATOR",
            "issued_at": (now - timedelta(seconds=10)).isoformat().replace(
                "+00:00", "Z"
            ),
            "node_id": action.NODE_ID,
            "allowed_action_id": action.ACTION_ID,
            "scope": {
                "program_id": inputs["program_id"],
                "node_id": action.NODE_ID,
                "allowed_action_id": action.ACTION_ID,
                "execution_mode": "PROJECT_VALIDATION",
                "validation_scope": action.VALIDATION_SCOPE,
                "predecessor_repository_ref": (
                    "harness-resource://execution/project_start_packages/"
                    "main_build/repository"
                ),
                "predecessor_repository_write_allowed": False,
                "node_evidence_write_ref": action.NODE_EVIDENCE_WRITE_REF,
                "runtime_internal_write_refs": action.RUNTIME_INTERNAL_WRITE_REFS,
                "automatic_successor_advance_allowed": False,
            },
            "command_manifest_hashes": [action.file_hash(command_path)],
            "command_manifest_sha256": action.file_hash(command_path),
            "candidate_tree_sha256": candidate_sha,
            "requirement_ir_sha256": inputs["requirement_ir_sha256"],
            "executor_implementation_sha256": implementation_sha,
            "runtime_entrypoint_sha256": entrypoint_sha,
            "materialization_result_sha256": predecessor_sha,
            "materialized_repository_tree_sha256": repository_tree_sha,
            "expected_control_state_sha256": action.file_hash(state_path),
            "expected_event_tip": event["event_hash"],
            "node_evidence_write_ref": action.NODE_EVIDENCE_WRITE_REF,
            "validation_scope": action.VALIDATION_SCOPE,
            "idempotency_key": idempotency_key,
            "lease_id": lease_id,
            "fencing_token": fencing_token,
            "max_transitions": 1,
            "max_loop_rounds": 1,
            "real_target_install_allowed": False,
            "delegation_allowed": False,
            "signature_policy": (
                "NOT_APPLICABLE_SELF_USE_LOCAL_TRUSTED_OPERATOR"
            ),
            "signature": None,
            "not_before": (now - timedelta(seconds=5)).isoformat().replace(
                "+00:00", "Z"
            ),
            "expires_at": (now + timedelta(hours=1)).isoformat().replace(
                "+00:00", "Z"
            ),
        }
        authorization_path = (
            execution
            / f".harness-foundry/control/authorizations/{authorization_id}.json"
        )
        self._write_json(authorization_path, authorization)
        return execution, command_path, authorization_path

    def test_validation_commits_result_event_and_state_promotion_once(self) -> None:
        action = self.action
        execution, command, authorization = self._prepare_inputs("commit")
        repository = execution / action.REPOSITORY_REF
        repository_before = action._tree_snapshot(repository)
        first = action.execute_action(
            self.candidate, execution, command, authorization
        )
        self.assertEqual(first["disposition"], "COMMITTED")
        result = first["result"]
        self.assertEqual(result["next_node"], "MAIN_PROGRAM_REGISTRATION")
        self.assertEqual(
            result["produced_capabilities"],
            ["MAIN_EXECUTION_PACKAGE_VALIDATED_PASS"],
        )
        self.assertTrue(result["predecessor_repository_read_only"])
        self.assertFalse(result["successor_started"])
        self.assertFalse(
            result["structural_validation"]["executed_repository_code"]
        )
        self.assertEqual(repository_before, action._tree_snapshot(repository))
        state = json.loads(
            (execution / action.CONTROL_STATE_REF).read_text(encoding="utf-8")
        )
        self.assertEqual(state["last_completed_node"], action.NODE_ID)
        self.assertEqual(state["next_node"], action.NEXT_NODE_ID)
        self.assertEqual(state["authorization_status"], "CONSUMED")
        events = action.read_events(execution / action.CONTROL_EVENTS_REF)
        self.assertEqual(len(events), 2)
        second = action.execute_action(
            self.candidate, execution, command, authorization
        )
        self.assertEqual(second["disposition"], "ALREADY_COMMITTED")
        self.assertEqual(len(action.read_events(execution / action.CONTROL_EVENTS_REF)), 2)

    def test_repository_drift_fails_before_result_event_or_state_promotion(self) -> None:
        action = self.action
        execution, command, authorization = self._prepare_inputs("drift")
        state_path = execution / action.CONTROL_STATE_REF
        event_path = execution / action.CONTROL_EVENTS_REF
        state_before = action.file_hash(state_path)
        event_before = action.file_hash(event_path)
        (execution / action.REPOSITORY_REF / "unexpected.txt").write_text(
            "drift\n", encoding="utf-8"
        )
        with self.assertRaises(action.ContractError) as raised:
            action.execute_action(
                self.candidate, execution, command, authorization
            )
        self.assertEqual(
            raised.exception.code,
            "MATERIALIZED_REPOSITORY_STRUCTURAL_VALIDATION_FAILED",
        )
        self.assertEqual(action.file_hash(state_path), state_before)
        self.assertEqual(action.file_hash(event_path), event_before)
        self.assertFalse((execution / action.RESULT_REF).exists())
        self.assertFalse((execution / action.TRANSACTION_REF).exists())

    def test_compiler_projects_real_provider_and_static_validator_rejects_drift(
        self,
    ) -> None:
        action = self.action
        self.assertEqual(action.validate_static_contract(self.candidate)["active_requirement_epoch"], 49)
        self.assertEqual(
            _check_main_execution_package_validation_executable_closure(
                self.candidate, active_requirement_epoch=49
            ),
            [],
        )
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            candidate = Path(temporary) / "candidate"
            shutil.copytree(self.candidate, candidate)
            provider = candidate / action.IMPLEMENTATION_REF
            make_path_writable(provider)
            provider.write_text(
                provider.read_text(encoding="utf-8") + "\n# drift\n",
                encoding="utf-8",
            )
            codes = {
                finding["code"]
                for finding in _check_main_execution_package_validation_executable_closure(
                    candidate, active_requirement_epoch=49
                )
            }
            self.assertTrue(
                {
                    "MAIN_EXECUTION_PACKAGE_VALIDATION_CONTRACT_INVALID",
                    "MAIN_EXECUTION_PACKAGE_VALIDATION_PROJECTION_INVALID",
                }.intersection(codes)
            )


if __name__ == "__main__":
    unittest.main()
