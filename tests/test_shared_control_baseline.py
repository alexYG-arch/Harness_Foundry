"""Executable v0.9 Shared Control Baseline contract and recovery tests."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from harness_foundry_factory.compiler import compile_candidate
from harness_foundry_factory.validator import validate_candidate
from tests.permissions import make_path_writable, make_tree_writable


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SPEC_ROOT = REPOSITORY_ROOT.parent / "Harness_Foundry_v2_8_Start_Package"
IR_FIXTURE = REPOSITORY_ROOT / "tests/fixtures/harness_requirement_ir.json"
CONTRACT_FIXTURE = (
    REPOSITORY_ROOT / "tests/fixtures/shared_control_baseline_contract.json"
)


class SharedControlBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name).resolve()
        cls.candidate = cls.root / "candidate"
        ir = json.loads(IR_FIXTURE.read_text(encoding="utf-8"))
        fixture = json.loads(CONTRACT_FIXTURE.read_text(encoding="utf-8"))
        ir["target"].update(
            {
                "output_root": str(cls.candidate),
                "execution_root": str(cls.root / "declared-execution"),
                "portability_mode": "LOGICAL_RESOURCE_URI",
                "shared_control_baseline_execution_contract": fixture[
                    "execution_contract"
                ],
                "shared_control_baseline_test_contract": fixture["test_contract"],
                "human_review_v0_8_closure": {
                    "superseded_candidate": "Candidate_v0_8",
                    "replacement_candidate": "Candidate_v0_9",
                    "required_closures": [
                        "Executable action, exact schema, hash binding, and recovery are required."
                    ],
                    "status": "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT",
                    "workpack_execution_authorized": False,
                },
            }
        )
        ir["target"]["start_package_immutability_policy"] = {
            "candidate_root_read_only_after_atomic_publication": True,
            "candidate_execution_roots_must_not_overlap": True,
        }
        compile_candidate(
            ir,
            SPEC_ROOT,
            cls.root / "staging",
            cls.candidate,
            "2026-08-04T00:00:00Z",
        )
        action_path = cls.candidate / "tools/shared_control_baseline.py"
        spec = importlib.util.spec_from_file_location(
            "generated_shared_control_baseline", action_path
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("generated Shared Control Baseline cannot be imported")
        cls.action = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.action)

    @classmethod
    def tearDownClass(cls) -> None:
        make_tree_writable(cls.root)
        cls.temporary.cleanup()

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
            path.relative_to(self.candidate).as_posix(): self.action.file_hash(path)
            for path in self.candidate.rglob("*")
            if path.is_file()
        }

    def _runtime_inputs(
        self,
        name: str,
        *,
        executor_sha256: str | None = None,
        fencing_token: int = 1,
        authorization_status: str = "GRANTED",
    ) -> tuple[Path, Path, Path]:
        execution = self.root / name
        inputs = self.action._resolve_candidate_inputs(self.candidate)
        candidate_sha = self.action.candidate_identity(self.candidate)
        implementation_sha = executor_sha256 or self.action.file_hash(
            self.candidate / self.action.IMPLEMENTATION_REF
        )
        human = {
            "schema_version": "1.0",
            "receipt_id": f"HUMAN-{name}",
            "decision": "APPROVED",
            "program_id": inputs["program_id"],
            "candidate_tree_sha256": candidate_sha,
            "requirement_ir_sha256": inputs["requirement_ir_sha256"],
            "next_node": self.action.NODE_ID,
            "driver_start_authorized": False,
            "workpack_execution_authorized": False,
            "target_install_authorized": False,
        }
        human_path = execution / self.action.HUMAN_APPROVAL_REF
        self._write_json(human_path, human)
        state = {
            "schema_version": "1.0",
            "program_id": inputs["program_id"],
            "revision": 1,
            "control_plane_epoch": inputs["control_plane_epoch"],
            "epoch_domains": inputs["epoch_domains"],
            "next_node": self.action.NODE_ID,
            "next_fencing_token": 1,
            "last_event_hash": None,
            "active_authorization_id": f"AUTH-{name}",
            "authorization_status": "GRANTED",
            "remaining_transition_budget": 1,
            "driver_started": False,
            "active_workpack": None,
            "state_sha256": "",
        }
        state["state_sha256"] = self.action.hash_without(state, "state_sha256")
        state_path = execution / self.action.CONTROL_STATE_REF
        self._write_json(state_path, state)
        lease_id = f"LEASE-{name}"
        idempotency_key = self.action.json_hash(
            {
                "action_id": self.action.ACTION_ID,
                "authorization_id": f"AUTH-{name}",
                "candidate_tree_sha256": candidate_sha,
                "fencing_token": fencing_token,
                "lease_id": lease_id,
                "requirement_ir_sha256": inputs["requirement_ir_sha256"],
            }
        )
        command = {
            "schema_version": "1.0",
            "command_id": self.action.NODE_ID,
            "action_id": self.action.ACTION_ID,
            "node_id": self.action.NODE_ID,
            "authorization_id": f"AUTH-{name}",
            "candidate_tree_sha256": candidate_sha,
            "requirement_ir_sha256": inputs["requirement_ir_sha256"],
            "executor_implementation_ref": self.action.IMPLEMENTATION_REF,
            "executor_implementation_sha256": implementation_sha,
            "action_contract_sha256": self.action.file_hash(
                self.candidate / self.action.ACTION_CONTRACT_REF
            ),
            "result_schema_sha256": self.action.file_hash(
                self.candidate / self.action.RESULT_SCHEMA_REF
            ),
            "human_approval_receipt_sha256": self.action.file_hash(human_path),
            "expected_control_state_sha256": self.action.file_hash(state_path),
            "idempotency_key": idempotency_key,
            "lease_id": lease_id,
            "fencing_token": fencing_token,
        }
        command_path = execution / ".harness-foundry/control/action_inputs/command.json"
        self._write_json(command_path, command)
        authorization = {
            "schema_version": "1.0",
            "authorization_id": f"AUTH-{name}",
            "authorization_class": "REGISTRATION_AUTHORIZATION",
            "status": authorization_status,
            "one_shot": True,
            "program_id": inputs["program_id"],
            "node_id": self.action.NODE_ID,
            "allowed_action_id": self.action.ACTION_ID,
            "command_manifest_sha256": self.action.file_hash(command_path),
            "candidate_tree_sha256": candidate_sha,
            "requirement_ir_sha256": inputs["requirement_ir_sha256"],
            "executor_implementation_sha256": implementation_sha,
            "human_approval_receipt_sha256": self.action.file_hash(human_path),
            "expected_control_state_sha256": self.action.file_hash(state_path),
            "idempotency_key": idempotency_key,
            "lease_id": lease_id,
            "fencing_token": fencing_token,
            "not_before": "2020-01-01T00:00:00Z",
            "expires_at": "2100-01-01T00:00:00Z",
        }
        authorization_path = (
            execution / ".harness-foundry/control/action_inputs/authorization.json"
        )
        self._write_json(authorization_path, authorization)
        return execution, command_path, authorization_path

    def test_real_candidate_action_commits_exact_result_once(self) -> None:
        before = self._candidate_snapshot()
        execution, command, authorization = self._runtime_inputs("success")
        first = self.action.execute_action(
            self.candidate, execution, command, authorization
        )
        second = self.action.execute_action(
            self.candidate, execution, command, authorization
        )
        self.assertEqual(first["disposition"], "COMMITTED")
        self.assertEqual(second["disposition"], "ALREADY_COMMITTED")
        self.assertEqual(first["result"], second["result"])
        self.assertEqual(
            len(self.action.read_events(execution / self.action.CONTROL_EVENTS_REF)),
            1,
        )
        state = json.loads(
            (execution / self.action.CONTROL_STATE_REF).read_text(encoding="utf-8")
        )
        self.assertEqual(state["authorization_status"], "CONSUMED")
        self.assertEqual(state["remaining_transition_budget"], 0)
        self.assertFalse(state["driver_started"])
        self.assertIsNone(state["active_workpack"])
        self.assertEqual(before, self._candidate_snapshot())

    def test_every_declared_crash_point_recovers_without_duplicate(self) -> None:
        declared = set(
            json.loads(
                (self.candidate / self.action.ACTION_CONTRACT_REF).read_text(
                    encoding="utf-8"
                )
            )["execution_contract"]["recovery_contract"]["crash_points"]
        )
        self.assertEqual(declared, self.action.CRASH_POINTS)
        for index, point in enumerate(sorted(declared), 1):
            with self.subTest(point=point):
                execution, command, authorization = self._runtime_inputs(
                    f"crash-{index}"
                )
                with self.assertRaises(self.action.InjectedCrash):
                    self.action.execute_action(
                        self.candidate,
                        execution,
                        command,
                        authorization,
                        crash_after=point,
                    )
                recovered = self.action.execute_action(
                    self.candidate, execution, command, authorization
                )
                self.assertEqual(recovered["status"], "PASS")
                self.assertEqual(
                    len(
                        self.action.read_events(
                            execution / self.action.CONTROL_EVENTS_REF
                        )
                    ),
                    1,
                )
                receipt = json.loads(
                    (execution / self.action.RECOVERY_REF).read_text(encoding="utf-8")
                )
                self.assertTrue(receipt["recovered"])
                self.assertEqual(receipt["duplicate_side_effect_count"], 0)

    def test_executor_hash_fencing_and_revocation_fail_closed(self) -> None:
        cases = [
            (
                "executor-drift",
                {"executor_sha256": "0" * 64},
                "UNBOUND_OR_DRIFTED_CONTROL_ACTION_IMPLEMENTATION",
            ),
            ("fencing-regression", {"fencing_token": 0}, "FENCING_TOKEN_INVALID"),
            (
                "revoked",
                {"authorization_status": "REVOKED"},
                "REGISTRATION_AUTHORIZATION_REVOKED",
            ),
        ]
        for name, options, expected_code in cases:
            with self.subTest(name=name):
                execution, command, authorization = self._runtime_inputs(
                    name, **options
                )
                with self.assertRaises(self.action.ContractError) as caught:
                    self.action.execute_action(
                        self.candidate, execution, command, authorization
                    )
                self.assertEqual(caught.exception.code, expected_code)
                self.assertFalse((execution / self.action.RESULT_REF).exists())

    def test_architecture_epoch_cannot_be_used_as_execution_epoch(self) -> None:
        execution, command, authorization = self._runtime_inputs(
            "mixed-epoch-domains"
        )
        state_path = execution / self.action.CONTROL_STATE_REF
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["control_plane_epoch"] = 4
        state["state_sha256"] = self.action.hash_without(
            state, "state_sha256"
        )
        self._write_json(state_path, state)
        command_document = json.loads(command.read_text(encoding="utf-8"))
        command_document["expected_control_state_sha256"] = (
            self.action.file_hash(state_path)
        )
        self._write_json(command, command_document)
        authorization_document = json.loads(
            authorization.read_text(encoding="utf-8")
        )
        authorization_document["command_manifest_sha256"] = (
            self.action.file_hash(command)
        )
        authorization_document["expected_control_state_sha256"] = (
            self.action.file_hash(state_path)
        )
        self._write_json(authorization, authorization_document)

        with self.assertRaises(self.action.ContractError) as caught:
            self.action.execute_action(
                self.candidate, execution, command, authorization
            )
        self.assertEqual(caught.exception.code, "PROGRAM_CONTROL_STATE_INVALID")

    def test_result_schema_and_static_validator_bind_all_artifacts(self) -> None:
        report = validate_candidate(self.candidate)
        self.assertEqual(report["status"], "PASS")
        contract = self.action.validate_static_contract(self.candidate)
        schema = json.loads(
            (self.candidate / self.action.RESULT_SCHEMA_REF).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            schema["required"],
            contract["execution_contract"]["required_result_fields"],
        )
        execution, command, authorization = self._runtime_inputs("schema")
        result = self.action.execute_action(
            self.candidate, execution, command, authorization
        )["result"]
        invalid = dict(result)
        invalid.pop("executor_implementation_sha256")
        with self.assertRaises(self.action.ContractError) as caught:
            self.action.validate_result_document(invalid, schema, contract)
        self.assertEqual(
            caught.exception.code, "SHARED_CONTROL_BASELINE_RESULT_INVALID"
        )

    def test_validator_rejects_tampered_executor_contract(self) -> None:
        tampered = self.root / "tampered-candidate"
        shutil.copytree(self.candidate, tampered)
        contract_path = tampered / self.action.ACTION_CONTRACT_REF
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["executor_implementation_sha256"] = "0" * 64
        self._write_json(contract_path, contract)
        codes = {
            item["code"]
            for item in validate_candidate(tampered)["blocking_findings"]
        }
        self.assertIn("SHARED_CONTROL_BASELINE_CONTRACT_INVALID", codes)


if __name__ == "__main__":
    unittest.main()
