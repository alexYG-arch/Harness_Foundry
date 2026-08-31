"""Slice 02 Requirement/Architecture readback, lock, and compile contracts."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from harness_foundry_factory.compiler import (
    compile_requirement_architecture_contract,
)
from harness_foundry_factory.constants import default_spec_root
from harness_foundry_factory.models import (
    ContractGateError,
    InvalidTransitionError,
)
from harness_foundry_factory.service import FactoryService
from harness_foundry_factory.store import SQLiteEventStore


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "harness_requirement_ir.json"


class RequirementArchitectureCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.runs_root = self.root / "runs"
        self.program_id = "PROGRAM-SLICE-02"
        self.candidate_root = self.root / "candidate-must-remain-absent"
        self.execution_root = self.root / "execution-must-remain-absent"
        self.spec_root = default_spec_root().resolve()
        self.request_number = 0
        self.store = SQLiteEventStore(
            self.runs_root / self.program_id / "factory.sqlite3"
        )
        self.service = FactoryService(
            self.store,
            spec_root=self.spec_root,
            runs_root=self.runs_root,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _ir(
        self,
        *,
        architecture_epoch: int = 4,
        control_plane_epoch: int = 4,
        complete_architecture: bool = True,
    ) -> dict:
        value = json.loads(FIXTURE.read_text(encoding="utf-8"))
        value["program_id"] = self.program_id
        value["target"].update(
            {
                "output_root": str(self.candidate_root),
                "execution_root": str(self.execution_root),
                "architecture_epoch": architecture_epoch,
                "control_plane_epoch": control_plane_epoch,
                "architecture_input": {
                    "capabilities": ["requirement-and-architecture-compilation"],
                    "stages": ["P1", "C1"],
                    "subharnesses": ["MB-P1"],
                    "modules": [
                        "src/harness_foundry_factory/service.py",
                        "src/harness_foundry_factory/compiler.py",
                    ],
                    "rules": ["Requirement Lock before Architecture Lock"],
                    "policies": ["Dual Lock before compile"],
                    "tools": ["python3", "hffactory"],
                    "interfaces": [
                        "requirement-readback",
                        "architecture-readback",
                        "compile",
                    ],
                    "failure_returns": [
                        "REQUIREMENT_LOCK_MISSING",
                        "ARCHITECTURE_LOCK_MISSING",
                    ],
                    "unresolved_decisions": [],
                },
            }
        )
        if not complete_architecture:
            value["target"]["architecture_input"].pop("modules")
        return value

    def _request(
        self,
        intent: str,
        *,
        expected_state_hash: str | None,
        payload: dict | None = None,
    ) -> dict:
        self.request_number += 1
        return {
            "request_id": f"REQ-SLICE-02-{self.request_number:02d}",
            "idempotency_key": f"IDEM-SLICE-02-{self.request_number:02d}",
            "program_id": self.program_id,
            "expected_state_hash": expected_state_hash,
            "actor": {
                "type": "HUMAN_VIA_CODEX_CHAT",
                "chat_thread_id": "THREAD-SLICE-02",
                "turn_id": f"TURN-SLICE-02-{self.request_number:02d}",
            },
            "intent": intent,
            "payload": payload or {},
        }

    def _freeze_requirements(self, requirement_ir: dict | None = None) -> dict:
        created = self.service.handle_chat_turn(
            self._request(
                "CREATE",
                expected_state_hash=None,
                payload={"requirement_ir": requirement_ir or self._ir()},
            )
        )
        readback = self.service.handle_chat_turn(
            self._request(
                "PREPARE_READBACK",
                expected_state_hash=created["new_state_hash"],
            )
        )
        requested = self.service.handle_chat_turn(
            self._request(
                "REQUEST_FREEZE",
                expected_state_hash=readback["new_state_hash"],
            )
        )
        challenge = requested["approval_challenge"]
        return self.service.handle_chat_turn(
            self._request(
                "CONFIRM_FREEZE",
                expected_state_hash=requested["new_state_hash"],
                payload={
                    "challenge_id": challenge["challenge_id"],
                    "requirement_ir_sha256": challenge["requirement_ir_sha256"],
                    "decision": "APPROVE",
                    "confirmation_text": challenge["confirmation_token"],
                },
            )
        )

    def _lock_architecture(self, frozen: dict) -> dict:
        prepared = self.service.handle_chat_turn(
            self._request(
                "PREPARE_ARCHITECTURE_READBACK",
                expected_state_hash=frozen["new_state_hash"],
            )
        )
        requested = self.service.handle_chat_turn(
            self._request(
                "REQUEST_ARCHITECTURE_LOCK",
                expected_state_hash=prepared["new_state_hash"],
            )
        )
        challenge = requested["approval_challenge"]
        return self.service.handle_chat_turn(
            self._request(
                "CONFIRM_ARCHITECTURE_LOCK",
                expected_state_hash=requested["new_state_hash"],
                payload={
                    "challenge_id": challenge["challenge_id"],
                    "architecture_readback_sha256": challenge[
                        "architecture_readback_sha256"
                    ],
                    "decision": "APPROVE",
                    "confirmation_text": challenge["confirmation_token"],
                },
            )
        )

    def _run_cli(self, command: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "harness_foundry_factory.cli",
                command,
                "--program-id",
                self.program_id,
                "--spec-root",
                str(self.spec_root),
                "--runs-root",
                str(self.runs_root),
                "--json",
            ],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_dual_lock_readbacks_and_compile_are_real_and_read_only(self) -> None:
        frozen = self._freeze_requirements()
        requirement = self.service.requirement_readback(self.program_id)

        self.assertEqual(requirement["status"], "PASS")
        self.assertTrue(requirement["requirement_lock"]["conflicts_closed"])
        self.assertEqual(
            requirement["requirement_lock"]["requirement_ir_sha256"],
            frozen["freeze_lock"]["requirement_ir_sha256"],
        )
        with self.assertRaises(ContractGateError) as blocked:
            self.service.compile_contract(self.program_id)
        self.assertEqual(
            blocked.exception.details["gate_code"], "ARCHITECTURE_LOCK_MISSING"
        )

        locked = self._lock_architecture(frozen)
        self.assertEqual(locked["architecture_lock"]["status"], "LOCKED")
        compiled = self.service.compile_contract(self.program_id)

        self.assertEqual(compiled["status"], "PASS")
        self.assertEqual(compiled["architecture_epoch"], 4)
        self.assertEqual(compiled["control_plane_epoch"], 4)
        self.assertFalse(compiled["writes_performed"])
        self.assertFalse(compiled["execution_started"])
        self.assertFalse(self.candidate_root.exists())
        self.assertFalse(self.execution_root.exists())

    def test_architecture_lock_requires_exact_later_confirmation(self) -> None:
        frozen = self._freeze_requirements()
        prepared = self.service.handle_chat_turn(
            self._request(
                "PREPARE_ARCHITECTURE_READBACK",
                expected_state_hash=frozen["new_state_hash"],
            )
        )
        requested = self.service.handle_chat_turn(
            self._request(
                "REQUEST_ARCHITECTURE_LOCK",
                expected_state_hash=prepared["new_state_hash"],
            )
        )
        challenge = requested["approval_challenge"]

        with self.assertRaises(InvalidTransitionError):
            self.service.handle_chat_turn(
                self._request(
                    "CONFIRM_ARCHITECTURE_LOCK",
                    expected_state_hash=requested["new_state_hash"],
                    payload={
                        "challenge_id": challenge["challenge_id"],
                        "architecture_readback_sha256": challenge[
                            "architecture_readback_sha256"
                        ],
                        "decision": "APPROVE",
                        "confirmation_text": "not-the-bound-token",
                    },
                )
            )
        self.assertEqual(
            self.store.get_program(self.program_id).snapshot[
                "architecture_lifecycle"
            ]["status"],
            "WAITING_HUMAN_CONFIRMATION",
        )

    def test_incomplete_architecture_and_mixed_epoch_fail_closed(self) -> None:
        frozen = self._freeze_requirements(self._ir(complete_architecture=False))
        with self.assertRaises(ContractGateError) as incomplete:
            self.service.architecture_readback(self.program_id)
        self.assertEqual(
            incomplete.exception.details["gate_code"],
            "ARCHITECTURE_DECISION_INCOMPLETE",
        )
        self.assertEqual(
            self.store.get_program(self.program_id).state_hash,
            frozen["new_state_hash"],
        )

        other_program = "PROGRAM-SLICE-02-MIXED"
        other_store = SQLiteEventStore(
            self.runs_root / other_program / "factory.sqlite3"
        )
        other_service = FactoryService(
            other_store,
            spec_root=self.spec_root,
            runs_root=self.runs_root,
        )
        other_ir = self._ir(architecture_epoch=4, control_plane_epoch=3)
        other_ir["program_id"] = other_program
        self.program_id = other_program
        self.store = other_store
        self.service = other_service
        mixed_frozen = self._freeze_requirements(other_ir)
        with self.assertRaises(ContractGateError) as mixed:
            self.service.architecture_readback(other_program)
        self.assertEqual(mixed.exception.details["gate_code"], "MIXED_EPOCH")
        self.assertEqual(other_store.get_program(other_program).state_hash, mixed_frozen["new_state_hash"])

    def test_stale_requirement_or_architecture_binding_is_rejected(self) -> None:
        frozen = self._freeze_requirements()
        self._lock_architecture(frozen)
        record = self.store.get_program(self.program_id)
        requirement = self.service.requirement_readback(self.program_id)
        architecture = self.service.architecture_readback(self.program_id)
        changed_ir = deepcopy(record.snapshot["requirement_ir"])
        changed_ir["target"]["mission"] = "changed after lock"

        with self.assertRaisesRegex(ValueError, "REQUIREMENT_LOCK_STALE"):
            compile_requirement_architecture_contract(
                changed_ir,
                requirement_lock=requirement["requirement_lock"],
                architecture_readback=architecture["architecture_readback"],
                architecture_lock=architecture["architecture_lock"],
            )

    def test_public_cli_commands_emit_json_without_changing_database(self) -> None:
        frozen = self._freeze_requirements()
        self._lock_architecture(frozen)
        database = self.store.database_path
        before = hashlib.sha256(database.read_bytes()).hexdigest()

        for command in (
            "requirement-readback",
            "architecture-readback",
            "compile",
            "verify-run",
        ):
            with self.subTest(command=command):
                completed = self._run_cli(command)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                result = json.loads(completed.stdout)
                self.assertEqual(result["status"], "PASS")
                if command == "verify-run":
                    self.assertEqual(result["program_id"], self.program_id)

        after = hashlib.sha256(database.read_bytes()).hexdigest()
        self.assertEqual(after, before)
        self.assertFalse(self.candidate_root.exists())
        self.assertFalse(self.execution_root.exists())

    def test_product_manifest_binds_implemented_core_capabilities(self) -> None:
        manifest = json.loads(
            (ROOT / "FACTORY_MANIFEST.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest["implemented_core_capabilities"],
            [
                "version",
                "requirement-readback",
                "requirement-lock",
                "architecture-readback",
                "architecture-lock",
                "compile",
                "assurance-profile-program-graph",
                "generic-transition-engine",
                "rule-evaluator",
                "decision-policy",
                "decision-receipt",
                "requirement-classification",
                "charter-clause-disposition",
                "policy-coverage",
                "architecture-candidate",
                "run-contract",
                "evidence-applicability",
                "authoring-readback",
                "auto-advance-to-real-gate",
                "parent-authorization-challenge",
                "machine-derived-attempt-grant",
                "runtime-advance-until-gate",
                "bounded-retry",
                "budget-accounting",
                "advance-trace",
                "checkpoint-bundle",
                "resume-capsule",
                "resume-revalidation",
                "side-effect-reconciliation",
                "explain-stop",
                "portable-local-package",
                "logical-root-resolution",
                "path-containment",
                "dependency-discovery",
                "local-startup-smoke",
                "self-check-diagnostic",
                "product-implementation-manifest",
                "official-core-validator",
                "capability-behavior-matrix",
                "major-failure-path-matrix",
                "implementation-evidence-projection",
            ],
        )
        self.assertEqual(len(manifest["implemented_core_capabilities"]), 41)
        self.assertEqual(
            manifest["implemented_optional_compatibility_capabilities"],
            [
                "profile-aware-candidate-generation-preflight",
                "core-release-ready-local-gate",
                "default-delivery-route-selection",
                "optional-security-route-exclusion",
                "control-plane-registration-executable-closure",
                "program-driver-runtime-verification-executable-closure",
                "controlled-runtime-workpack-executable-closure",
                "main-execution-package-validation-executable-closure",
            ],
        )
        self.assertFalse(manifest["optional_compatibility_default_route"])
        self.assertFalse(manifest["optional_compatibility_core_release_blocking"])
        self.assertEqual(manifest["output"], "LOCAL_HARNESS_FOUNDRY_ENGINEERING_PRODUCT")
        self.assertEqual(
            manifest["public_python_api"],
            [
                "harness_foundry_factory.instantiate_program_graph",
                "harness_foundry_factory.GenericTransitionEngine",
                "harness_foundry_factory.evaluate_decision_policy",
                "harness_foundry_factory.prepare_parent_authorization_challenge",
            ],
        )
        self.assertEqual(
            manifest["compile_boundary"],
            "DUAL_LOCK_REQUIRED_STDOUT_OR_MEMORY_ONLY_NO_CANDIDATE_WRITE",
        )
        self.assertEqual(
            manifest["public_cli"],
            [
                "version",
                "requirement-readback",
                "architecture-readback",
                "compile",
                "advance-authoring-until-gate",
                "advance-until-gate",
                "checkpoint",
                "resume",
                "explain-stop",
                "package-local",
                "self-check-diagnostic",
                "validate-core",
                "project-core-evidence",
            ],
        )
        self.assertEqual(
            manifest["runtime_recovery_boundary"],
            "ATOMIC_CONTROL_EVENT_CHECKPOINT_CAPSULE_NO_SNAPSHOT_AUTHORITY_REVALIDATE_BEFORE_RESUME_UNKNOWN_EFFECT_HARD_STOP",
        )
        self.assertEqual(
            manifest["portable_local_boundary"],
            "ALLOWLIST_LOGICAL_PACKAGE_ROOT_ATOMIC_OUTPUT_DIAGNOSTIC_SELF_CHECK_NO_AUTHORITY_NO_CERTIFICATION",
        )
        self.assertEqual(
            manifest["post_implementation_validation_boundary"],
            "REAL_MODULE_ENTRYPOINT_HASH_AND_BEHAVIOR_TEST_BINDING_READ_ONLY_NO_SELF_REPORT_PROOF_NO_RECEIPT_NO_EXTERNAL_CERTIFICATION",
        )
        self.assertEqual(
            manifest["control_plane_registration_boundary"],
            "REGISTRATION_ONLY_HASH_BOUND_EXECUTABLE_CLOSURE_ONE_SHOT_IDEMPOTENCY_FENCING_EVENT_AND_STATE_CAS_NO_DRIVER_OR_WORKPACK_START",
        )
        self.assertEqual(
            manifest["program_driver_runtime_verification_boundary"],
            "SELF_USE_LOCAL_READ_ONLY_STATUS_PLAN_NEXT_VALIDATE_TRANSITION_HASH_BOUND_ONE_SHOT_STATE_CAS_NO_DRIVER_OR_WORKPACK_START",
        )

    def test_read_only_cli_does_not_create_database_for_unknown_program(self) -> None:
        missing_program = "PROGRAM-DOES-NOT-EXIST"
        missing_database = (
            self.runs_root / missing_program / "factory.sqlite3"
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        environment["PYTHONDONTWRITEBYTECODE"] = "1"

        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "harness_foundry_factory.cli",
                "requirement-readback",
                "--program-id",
                missing_program,
                "--spec-root",
                str(self.spec_root),
                "--runs-root",
                str(self.runs_root),
                "--json",
            ],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 3)
        self.assertEqual(
            json.loads(completed.stdout)["error"]["code"],
            "PROGRAM_NOT_FOUND",
        )
        self.assertFalse(missing_database.exists())


if __name__ == "__main__":
    unittest.main()
