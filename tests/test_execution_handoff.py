"""Real temporary authoring -> audited decision -> read-only runtime handoff.

No compiler/Validator mocks, private startup contracts, or production approvals.
The separate runtime authorization in the wire test is test-only input.
"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

from harness_foundry_factory.constants import default_spec_root
from harness_foundry_factory.execution_handoff import ExecutionHandoffError, validate_live_handoff
from harness_foundry_factory.service import _tree_hash
from tests import test_prebuild_delegation as support
from tests import test_shared_control_baseline as runtime_support
from tests.permissions import make_tree_writable


ROOT = Path(__file__).resolve().parents[1]


class ExecutionHandoffTests(unittest.TestCase):
    _clock = support.PrebuildDelegationTests._clock
    _actor = staticmethod(support.PrebuildDelegationTests._actor)
    _request = support.PrebuildDelegationTests._request
    _create_and_complete_requirements = support.PrebuildDelegationTests._create_and_complete_requirements
    _freeze = support.PrebuildDelegationTests._freeze
    send = support.PrebuildDelegationTests.send
    grant = support.PrebuildDelegationTests.grant
    reopen_and_freeze = support.PrebuildDelegationTests.reopen_and_freeze

    def _canonical_ir(self):
        ir = support.PrebuildDelegationTests._canonical_ir(self)
        ir["target"].update(portability_mode="LOGICAL_RESOURCE_URI",
                            start_package_assurance_profile="LOCAL_EXEC_UNTRUSTED_INPUT")
        return ir

    def setUp(self):
        support.PrebuildDelegationTests.setUp(self)
        self.service.spec_root = default_spec_root().resolve()
        self.grant()
        self.reopen_and_freeze()
        generated = self.send("GENERATE")["candidate"]
        self.candidate = Path(generated["candidate_path"])
        self.approval = {
            "decision": "APPROVE",
            "candidate_content_sha256": generated["compiler_result"]["content_sha256"],
            "requirement_ir_sha256": generated["requirement_ir_sha256"],
            "review": {"summary": "Temporary integration fixture; not production approval",
                       "findings": [], "reviewed_refs": ["harness-resource://candidate/START_CONTEXT.json"]},
        }

    def tearDown(self):
        make_tree_writable(self.root)
        support.PrebuildDelegationTests.tearDown(self)

    def _approve(self):
        self.send("REVIEW_CANDIDATE", self.approval)
        return self.service.prepare_execution_handoff("PROGRAM-1")

    def test_actual_decision_projects_distinct_identity_domains_without_writes(self):
        self.send("REVIEW_CANDIDATE", self.approval)
        before = _tree_hash(self.root)
        handoff = self.service.prepare_execution_handoff("PROGRAM-1")
        receipt = handoff["approval_receipt"]
        self.assertEqual(receipt["approval_mode"], "DELEGATED")
        self.assertEqual(receipt["actor"]["type"], "CODEX_DELEGATED_AGENT")
        self.assertNotEqual(receipt["candidate_tree_sha256"], receipt["factory_candidate_content_sha256"])
        self.assertEqual(receipt["factory_candidate_content_sha256"], self.approval["candidate_content_sha256"])
        self.assertFalse(receipt["execution_authorized"])
        self.assertEqual(len(handoff["startup_bindings"]), 3)
        self.assertEqual(self.store.get_program("PROGRAM-1").snapshot["candidate"]["human_approval_status"], "PENDING")
        self.assertEqual(validate_live_handoff(self.service, "PROGRAM-1", handoff), handoff)
        self.assertEqual(before, _tree_hash(self.root))

    def test_public_cli_returns_the_same_handoff_without_an_execution_root(self):
        expected = self._approve()
        before = _tree_hash(self.root)
        completed = subprocess.run([
            sys.executable, str(ROOT / "tools/hffactory.py"), "prepare-execution-handoff",
            "--program-id", "PROGRAM-1", "--db", str(self.store.database_path),
            "--runs-root", str(self.root / "runs"), "--json",
        ], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(json.loads(completed.stdout), expected)
        self.assertEqual(before, _tree_hash(self.root))

    def test_unapproved_or_rejected_candidate_does_not_project_an_approval(self):
        with self.assertRaises(ExecutionHandoffError):
            self.service.prepare_execution_handoff("PROGRAM-1")
        self.send("REVIEW_CANDIDATE", {**self.approval, "decision": "REJECT"})
        with self.assertRaises(ExecutionHandoffError):
            self.service.prepare_execution_handoff("PROGRAM-1")

    def test_reopened_or_relabelled_projection_is_not_accepted(self):
        handoff = self._approve()
        changed = deepcopy(handoff)
        changed["approval_receipt"]["actor"]["type"] = "HUMAN_VIA_CODEX_CHAT"
        with self.assertRaises(ExecutionHandoffError):
            validate_live_handoff(self.service, "PROGRAM-1", changed)
        self.send("REOPEN", {"reason": "Test invalidation after approval"}, delegated=False)
        with self.assertRaises(ExecutionHandoffError):
            validate_live_handoff(self.service, "PROGRAM-1", handoff)

    def test_published_byte_drift_prevents_handoff(self):
        self._approve()
        path = self.candidate / "README.md"
        path.chmod(path.stat().st_mode | 0o200)
        path.write_text(path.read_text() + "\nTest-only byte drift.\n")
        with self.assertRaises(ExecutionHandoffError) as caught:
            self.service.prepare_execution_handoff("PROGRAM-1")
        self.assertEqual(caught.exception.details["reason"], "CANDIDATE_BINDING_STALE")

    def _write_json(self, path, value):
        if path.as_posix().endswith("/evidence/engineering_dag/START_PACKAGE_HUMAN_APPROVAL/result.json"):
            # The compatibility path does not convert a delegated decision to Human.
            value = self.handoff["approval_receipt"]
        runtime_support.SharedControlBaselineTests._write_json(path, value)

    def test_projection_fits_real_control_action_but_is_not_execution_authorization(self):
        self.handoff = self._approve()
        spec = importlib.util.spec_from_file_location("handoff_shared_control", self.candidate / "tools/shared_control_baseline.py")
        self.action = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.action)
        before = _tree_hash(self.candidate)
        execution, command, authorization = runtime_support.SharedControlBaselineTests._runtime_inputs(self, "runtime-wire")
        projection_path = execution / self.action.HUMAN_APPROVAL_REF
        with self.assertRaises(self.action.ContractError):
            self.action.execute_action(self.candidate, execution, command, projection_path)
        self.assertFalse((execution / self.action.RESULT_REF).exists())
        result = self.action.execute_action(self.candidate, execution, command, authorization)
        self.assertEqual(result["disposition"], "COMMITTED")
        self.assertEqual(result["result"]["human_approval_receipt_sha256"], self.action.file_hash(projection_path))
        self.assertEqual(json.loads(projection_path.read_text())["approval_mode"], "DELEGATED")
        self.assertEqual(before, _tree_hash(self.candidate))
