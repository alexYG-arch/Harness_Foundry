"""Normal Candidate compilation must supply its declared first control action.

No optional execution contract is inserted into the Requirement and neither
the Candidate Validator nor the compiler is mocked. Runtime data is isolated
test input, never a production approval or execution receipt.
"""

import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest

from harness_foundry_factory.compiler import compile_candidate
from harness_foundry_factory.validator import (
    validate_candidate, _check_shared_control_baseline_executable_contract,
)
from tests.permissions import make_tree_writable
from tests import test_shared_control_baseline as existing
from tests import test_program_driver_runtime_verification as driver_support


ROOT = Path(__file__).resolve().parents[1]


class DefaultStartupContractTests(unittest.TestCase):
    target_overrides = {}
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name).resolve()
        cls.candidate = cls.root / "candidate"
        ir = json.loads((ROOT / "tests/fixtures/harness_requirement_ir.json").read_text())
        ir["target"].update(output_root=str(cls.candidate), portability_mode="LOGICAL_RESOURCE_URI")
        ir["target"].update(cls.target_overrides)
        assert "shared_control_baseline_execution_contract" not in ir["target"]
        compile_candidate(ir, ROOT.parent / "Harness_Foundry_v2_8_Start_Package",
                          cls.root / "staging", cls.candidate, "2026-09-06T00:00:00Z")

    @classmethod
    def tearDownClass(cls):
        make_tree_writable(cls.root)
        cls.temporary.cleanup()

    _write_json = staticmethod(existing.SharedControlBaselineTests._write_json)
    _runtime_inputs = existing.SharedControlBaselineTests._runtime_inputs
    _candidate_snapshot = existing.SharedControlBaselineTests._candidate_snapshot

    def _load_action(self):
        path = self.candidate / "tools/shared_control_baseline.py"
        self.assertTrue(path.is_file(), "normal Candidate declares the control node but omits its executor")
        spec = importlib.util.spec_from_file_location("default_startup_shared", path)
        action = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(action)
        self.action = action
        return action

    def test_normal_candidate_supplies_a_valid_executable_first_control_action(self):
        action = self._load_action()
        action.validate_static_contract(self.candidate)
        self.assertEqual(validate_candidate(self.candidate)["status"], "PASS")
        frozen = json.loads((self.candidate / "canonical_sources/FROZEN_REQUIREMENT_IR.json").read_text())
        self.assertNotIn("shared_control_baseline_execution_contract", frozen["target"])

    def test_default_emitted_action_commits_and_reenters_without_candidate_writes(self):
        self._load_action()
        before = self._candidate_snapshot()
        execution, command, authorization = self._runtime_inputs("default-startup")
        first = self.action.execute_action(self.candidate, execution, command, authorization)
        second = self.action.execute_action(self.candidate, execution, command, authorization)
        self.assertEqual(first["disposition"], "COMMITTED")
        self.assertEqual(second["disposition"], "ALREADY_COMMITTED")
        self.assertEqual(first["result"], second["result"])
        self.assertEqual(len(self.action.read_events(execution / self.action.CONTROL_EVENTS_REF)), 1)
        self.assertEqual(before, self._candidate_snapshot())

    def test_independent_validator_does_not_skip_the_default_contract(self):
        self._load_action()
        contract = self.candidate / "validation/SHARED_CONTROL_BASELINE_ACTION_CONTRACT.json"
        original = contract.read_bytes()
        original_mode = contract.stat().st_mode
        contract.chmod(original_mode | 0o200)
        try:
            payload = json.loads(original)
            payload["execution_contract"]["produced_capabilities"] = []
            contract.write_text(json.dumps(payload))
            findings = _check_shared_control_baseline_executable_contract(self.candidate)
            self.assertTrue(findings, "default startup is not optional just because IR omitted the override")
        finally:
            contract.write_bytes(original)
            contract.chmod(original_mode)


class NormalLocalStartupTests(unittest.TestCase):
    # A public assurance choice, not an injected private execution contract or
    # a fabricated epoch 38/45 self-upgrade fixture.
    target_overrides = {"start_package_assurance_profile": "LOCAL_EXEC_UNTRUSTED_INPUT"}

    @classmethod
    def setUpClass(cls):
        DefaultStartupContractTests.setUpClass.__func__(cls)
        support = driver_support.ProgramDriverRuntimeVerificationTests
        cls.shared = support._load_action("normal_local_shared", cls.candidate / "tools/shared_control_baseline.py")
        cls.registration = support._load_action("normal_local_registration", cls.candidate / "tools/control_plane_registration.py")
        cls.verification = support._load_action("normal_local_verification", cls.candidate / "tools/program_driver_runtime_verification.py")

    @classmethod
    def tearDownClass(cls):
        DefaultStartupContractTests.tearDownClass.__func__(cls)

    _write_json = staticmethod(driver_support.ProgramDriverRuntimeVerificationTests._write_json)
    _commit_shared_predecessor = driver_support.ProgramDriverRuntimeVerificationTests._commit_shared_predecessor
    _registration_inputs = driver_support.ProgramDriverRuntimeVerificationTests._registration_inputs
    _commit_registration = driver_support.ProgramDriverRuntimeVerificationTests._commit_registration
    _verification_inputs = driver_support.ProgramDriverRuntimeVerificationTests._verification_inputs
    _candidate_snapshot = driver_support.ProgramDriverRuntimeVerificationTests._candidate_snapshot

    def test_normal_local_candidate_validates_without_historical_profile_or_case_injection(self):
        self.assertFalse((self.candidate / "EPOCH38_GENERATION_PROFILE.json").exists())
        self.assertEqual(validate_candidate(self.candidate)["status"], "PASS")
        for action in (self.shared, self.registration, self.verification):
            action.validate_static_contract(self.candidate)
        cases = json.loads((self.candidate / "validation/NEGATIVE_CASES.json").read_text())["cases"]
        self.assertFalse(any(case["case_id"].startswith(("NEG-V29-E41-", "NEG-V29-E43-")) for case in cases))

    def test_real_startup_actions_follow_dag_to_lab_without_starting_it(self):
        before = self._candidate_snapshot()
        execution, command, authorization = self._verification_inputs("normal-startup")
        result = self.verification.execute_action(self.candidate, execution, command, authorization)
        self.assertEqual(result["disposition"], "COMMITTED")
        self.assertEqual(result["result"]["next_node"], "LAB_BOOTSTRAP")
        self.assertFalse(result["result"]["driver_started"])
        self.assertFalse(result["result"]["workpack_started"])
        repeat = self.verification.execute_action(self.candidate, execution, command, authorization)
        self.assertEqual(repeat["disposition"], "ALREADY_COMMITTED")
        self.assertEqual(repeat["result"], result["result"])
        state = json.loads((execution / self.shared.CONTROL_STATE_REF).read_text())
        self.assertEqual(state["next_node"], "LAB_BOOTSTRAP")
        self.assertEqual(len(self.shared.read_events(execution / self.shared.CONTROL_EVENTS_REF)), 3)
        self.assertEqual(before, self._candidate_snapshot())

    def test_normal_local_candidate_passes_its_actual_portable_self_check(self):
        completed = subprocess.run([sys.executable, "tools/self_check.py"], cwd=self.candidate,
                                   capture_output=True, text=True, check=False, timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "PASS")

    def test_revoked_registration_authorization_never_commits(self):
        execution, command, authorization = self._registration_inputs("revoked-register")
        payload = json.loads(authorization.read_text())
        payload["status"] = "REVOKED"
        self._write_json(authorization, payload)
        before = self.shared.read_events(execution / self.shared.CONTROL_EVENTS_REF)
        with self.assertRaises(self.registration.ContractError):
            self.registration.execute_action(self.candidate, execution, command, authorization)
        self.assertFalse((execution / self.registration.RESULT_REF).exists())
        self.assertEqual(before, self.shared.read_events(execution / self.shared.CONTROL_EVENTS_REF))

    def test_driver_probe_scope_expansion_never_commits(self):
        execution, command, authorization = self._verification_inputs("widened-probes")
        payload = json.loads(authorization.read_text())
        payload["read_only_probe_commands"].append("advance")
        self._write_json(authorization, payload)
        before = self.shared.read_events(execution / self.shared.CONTROL_EVENTS_REF)
        with self.assertRaises(self.verification.ContractError):
            self.verification.execute_action(self.candidate, execution, command, authorization)
        self.assertFalse((execution / self.verification.RESULT_REF).exists())
        self.assertEqual(before, self.shared.read_events(execution / self.shared.CONTROL_EVENTS_REF))

    def test_independent_validator_and_runtime_reject_skipped_lab_successor(self):
        from harness_foundry_factory.validator import _check_program_driver_runtime_verification_executable_closure
        path = self.candidate / self.verification.ACTION_CONTRACT_REF
        original, mode = path.read_bytes(), path.stat().st_mode
        path.chmod(mode | 0o200)
        try:
            contract = json.loads(original)
            contract["execution_contract"]["successor_node_id"] = "MAIN_EXECUTION_PACKAGE_MATERIALIZED"
            contract["contract_sha256"] = self.shared.hash_without(contract, "contract_sha256")
            path.write_text(json.dumps(contract))
            findings = _check_program_driver_runtime_verification_executable_closure(self.candidate)
            self.assertIn("PROGRAM_DRIVER_RUNTIME_VERIFICATION_CONTRACT_INVALID", {f["code"] for f in findings})
            with self.assertRaises(self.verification.ContractError):
                self.verification.validate_static_contract(self.candidate)
        finally:
            path.write_bytes(original)
            path.chmod(mode)

    def test_independent_validator_requires_default_registration_artifact(self):
        from harness_foundry_factory.validator import _check_control_plane_registration_executable_closure
        path = self.candidate / self.registration.IMPLEMENTATION_REF
        directory_mode = path.parent.stat().st_mode
        backup = path.with_suffix(".held")
        path.parent.chmod(directory_mode | 0o200)
        try:
            path.rename(backup)
            findings = _check_control_plane_registration_executable_closure(self.candidate)
            self.assertIn("CONTROL_PLANE_REGISTRATION_EXECUTABLE_ARTIFACT_MISSING", {f["code"] for f in findings})
        finally:
            backup.rename(path)
            path.parent.chmod(directory_mode)
