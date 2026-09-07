"""Real generated commands and worker processes; TEST-only model/receiver fixture.

The fixture receiver forwards local processes, not an OS sandbox or Codex.
Formal authoring state and real model services are never used by these tests.
"""

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from harness_foundry_factory.project_verification import (
    COMMAND_ID, plan_project_verification, observe_project_verification,
)
from harness_foundry_factory.lab_protocol_checks import PROTOCOL_CASE_IDS
from harness_foundry_factory.local_runtime import LOCAL_MODE, LOCAL_CLASS, bind_local_workpack_transition
from harness_foundry_factory.local_runtime import prepare_local_runtime
from harness_foundry_factory.local_process import LocalCommand, CodexSandboxRunner
from harness_foundry_factory.control_kernel import GenericTransitionEngine, InjectedKernelCrash
from harness_foundry_factory.execution_handoff import verify_runtime_factory_binding
from harness_foundry_factory.validator import _project_verification_command_findings
from harness_foundry_factory.workpack_acceptance import audit_workpack_completion
from harness_foundry_factory import workpack_runtime as runtime
from tests import test_normal_workpack_runtime as normal, test_coding_runtime as coding
from tests import test_local_runtime as local, test_runtime_advance_cli as support


def write_project(root, *, broken=False):
    package = root / "external_lab"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text('"""TEST-only project implementation."""\n')
    (package / "protocol.py").write_text(
        "from harness_foundry_runtime.lab_protocol import *\n"
        + ("def validate_instance(*args): return True\n" if broken else ""))


def test_receiver(root):
    path = root / "test-only-offline-receiver"
    path.write_text(f"#!{sys.executable}\n" + '''
# TEST ONLY: process transport, NOT an OS sandbox or model service.
import subprocess, sys
if '--help' in sys.argv:
    print('[COMMAND] --permission-profile --include-managed-config --cd')
    raise SystemExit(0)
args = sys.argv[sys.argv.index('--') + 1:]
raise SystemExit(subprocess.run(args).returncode)
''')
    path.chmod(0o755)
    return path


class ProducedProjectVerificationTests(unittest.TestCase):
    target_overrides = normal.NormalWorkpackRuntimeTests.target_overrides
    setUpClass = classmethod(normal.NormalWorkpackRuntimeTests.setUpClass.__func__)
    tearDownClass = classmethod(normal.NormalWorkpackRuntimeTests.tearDownClass.__func__)

    def test_produced_verifier_is_ordered_read_only_and_not_self_acceptance(self):
        planned = plan_project_verification(self.semantic_candidate, "LAB_BOOTSTRAP", "LAB-PROTOCOL", COMMAND_ID)
        self.assertEqual(planned["completion_plan"]["command_execution_order"], ["LAB-CODEX-CODING", COMMAND_ID])
        self.assertEqual(planned["native_command"]["allowed_write_roots"], [])
        self.assertEqual(planned["native_command"]["shared_artifact_write_roots"], [])
        self.assertFalse(planned["workpack_accepted"])
        self.assertEqual(_project_verification_command_findings(planned["native_command"]), [])
        for field, value in (("argv", ["python", "--version"]), ("allowed_write_roots", ["harness-resource://execution"]),
                             ("executor_role", "CODEX_CODING_AGENT")):
            changed = {**planned["native_command"], field: value}
            self.assertEqual(_project_verification_command_findings(changed)[0]["code"], "PROJECT_VERIFICATION_COMMAND_INVALID")

    def test_packaged_planner_does_not_import_or_execute_the_project(self):
        before = runtime._tree_snapshot(self.root)
        completed = subprocess.run([sys.executable, "-B", str(self.semantic_candidate / runtime.RUNTIME_ENTRYPOINT_REF),
            "verification-plan", "--candidate-root", str(self.semantic_candidate), "--node-id", "LAB_BOOTSTRAP",
            "--workpack-id", "LAB-PROTOCOL", "--command-id", COMMAND_ID], capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertFalse(json.loads(completed.stdout)["execution_authorized"])
        self.assertEqual(before, runtime._tree_snapshot(self.root))

    def test_verifier_hydration_removes_inherited_successor_and_retry(self):
        planned = plan_project_verification(self.semantic_candidate, "LAB_BOOTSTRAP", "LAB-PROTOCOL", COMMAND_ID)
        transition = support.transition("TEST-VERIFY", LOCAL_CLASS)
        transition.update(next_transition_id="TEST-LATER", retry_policy={"max_retries": 2})
        bound = bind_local_workpack_transition(transition, native_command=planned["native_command"],
            project_id="EXTERNAL_CONFORMANCE_LAB", workpack_id="LAB-PROTOCOL",
            argv=[{"resource_ref": "harness-resource://runtime-tools/python"}, *planned["argv_tail"]],
            cwd_ref=planned["cwd_ref"], executable_sha256=local.digest(sys.executable),
            runtime_read_refs=["harness-resource://runtime-tools/python"])
        self.assertIsNone(bound["next_transition_id"])
        self.assertIsNone(bound["stop_gate"])
        self.assertEqual(bound["retry_policy"], {"max_retries": 0})
        self.assertEqual(transition["next_transition_id"], "TEST-LATER")

    def test_real_worker_selects_project_implementation_and_rejects_missing_or_broken_code(self):
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            repository = Path(temporary)
            command = [sys.executable, "-I", "-B", str(self.semantic_candidate / "tools/lab_protocol_worker.py"),
                       "--project-root", str(repository), "--schema-file", str(self.semantic_candidate / "validation/PUBLIC_SKILL_JOB_INTERFACE.json")]
            for state in ("missing", "correct", "broken"):
                if state != "missing":
                    write_project(repository, broken=state == "broken")
                before = runtime._tree_snapshot(self.root)
                completed = subprocess.run(command, cwd=repository, capture_output=True, text=True, timeout=30)
                result = json.loads(completed.stdout)
                self.assertEqual(completed.returncode, 0 if state == "correct" else 1, completed.stdout + completed.stderr)
                self.assertEqual(result["status"], {"correct": "PASS", "missing": "INCONCLUSIVE", "broken": "FAIL"}[state])
                self.assertFalse(result["workpack_accepted"])
                self.assertEqual(before, runtime._tree_snapshot(self.root))

    def test_observation_requires_actual_complete_case_set_and_successful_capture(self):
        result = {"status": "PASS", "evidence_scope": "LAB_PROTOCOL_PRIMITIVES_ONLY", "workpack_accepted": False,
                  "execution_authorized": False, "implementation_module": "external_lab.protocol",
                  "cases": [{"case_id": case, "status": "PASS"} for case in PROTOCOL_CASE_IDS]}
        capture = {"status": "PASS", "stdout": json.dumps(result), "exit_code": 0, "timed_out": False, "output_truncated": False}
        self.assertEqual(observe_project_verification(capture)["status"], "PASS")
        for mutation in ({"stdout": "PASS"}, {"exit_code": 1}, {"timed_out": True}, {"output_truncated": True},
                         {"stdout": json.dumps({**result, "cases": result["cases"][:-1]})},
                         {"stdout": json.dumps({**result, "workpack_accepted": True})}):
            self.assertEqual(observe_project_verification({**capture, **mutation})["status"], "FAIL")

    @unittest.skipUnless(os.environ.get("HFFACTORY_TEST_CODEX_SANDBOX"), "explicit offline OS sandbox test opt-in required")
    def test_actual_offline_sandbox_verifies_project_but_denies_implementation_rewrites(self):
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            repository = Path(temporary)
            write_project(repository)
            reads = [self.semantic_candidate, repository, sys.prefix, sys.base_prefix, Path(sys._base_executable).parent,
                     *json.loads(os.environ.get("HFFACTORY_TEST_PYTHON_READ_ROOTS", "[]"))]
            command = LocalCommand.prepare(argv=[sys.executable, "-I", "-B", str(self.semantic_candidate / "tools/lab_protocol_worker.py"),
                "--project-root", str(repository), "--schema-file", str(self.semantic_candidate / "validation/PUBLIC_SKILL_JOB_INTERFACE.json")],
                cwd=repository, read_roots=reads, write_roots=[], timeout_seconds=30)
            runner = CodexSandboxRunner(os.environ["HFFACTORY_TEST_CODEX_SANDBOX"])
            before = runtime._tree_snapshot(self.root)
            observed = runner.run(command)
            self.assertEqual(observe_project_verification(observed)["status"], "PASS", observed)
            self.assertEqual(before, runtime._tree_snapshot(self.root))
            implementation = repository / "external_lab/protocol.py"
            implementation.write_text("from pathlib import Path\nPath(__file__).write_text('unauthorized rewrite')\n")
            before = runtime._tree_snapshot(self.root)
            rejected = runner.run(command)
            self.assertEqual(observe_project_verification(rejected)["status"], "FAIL")
            self.assertIn("PermissionError", json.loads(rejected["stdout"])["diagnostic"])
            self.assertEqual(before, runtime._tree_snapshot(self.root))


class ProjectVerificationRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = coding.CodingRuntimeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.plan = plan_project_verification(f.candidate, "LAB_BOOTSTRAP", "LAB-PROTOCOL", COMMAND_ID)
        receiver = test_receiver(f.local.root)
        self.transition = bind_local_workpack_transition(support.transition("T-VERIFY", LOCAL_CLASS),
            native_command=self.plan["native_command"], project_id="EXTERNAL_CONFORMANCE_LAB", workpack_id="LAB-PROTOCOL",
            argv=[{"resource_ref": "harness-resource://runtime-tools/python"}, *self.plan["argv_tail"]],
            cwd_ref=self.plan["cwd_ref"], executable_sha256=local.digest(sys.executable),
            runtime_read_refs=list(f.local.tools), timeout_seconds=20)
        self.transition["bindings"] = f.bindings
        self.parent = support.parent(f.local.program)
        self.parent.update(authorization_id="TEST-INDEPENDENT-VERIFICATION", bindings=f.bindings, command_classes=[LOCAL_CLASS],
            allowed_read_roots=self.transition["allowed_read_roots"], allowed_write_roots=[])
        self.parent["local_execution"] = {**f.common_plan, "mode": LOCAL_MODE, "runtime_resources": f.local.tools,
            "receiver": {"executable_abs": str(receiver), "executable_sha256": local.digest(receiver)},
            "transitions": {"T-VERIFY": self.transition}}

    def request(self):
        f = self.fixture
        return {"adapter_mode": LOCAL_MODE, "program_id": f.local.program, "parent_authorization_id": self.parent["authorization_id"],
            "contracts": {"T-VERIFY": self.transition}, "start_transition_id": "T-VERIFY", "max_transitions": 1,
            "inputs_by_transition": {"T-VERIFY": {"approved": True}}, "expected_bindings": f.bindings,
            "expected_control_state_sha256": f.local.engine.control_state_sha256(f.local.program),
            "environment_manifest": {"scope": "TEST_ONLY_PROCESS_TRANSPORT_NO_OS_ISOLATION"}, "artifact_manifest": {"artifacts": []}}

    def test_real_worker_result_commits_once_and_does_not_accept_or_unlock_next_workpack(self):
        f = self.fixture
        f.start()
        completed, result = f.local.cli(f.request())
        self.assertEqual(completed.returncode, 0, result)
        write_project(f.repository)
        f.approve(self.parent)
        before = runtime._tree_snapshot(f.candidate)
        completed, result = f.local.cli(self.request())
        self.assertEqual(completed.returncode, 0, result)
        observation = f.local.observations()[-1]["payload"]["result"]
        proof = observation["process_result"]["project_verification"]
        self.assertEqual(proof["status"], "PASS", observation)
        self.assertFalse(proof["workpack_accepted"])
        self.assertEqual(len(proof["report"]["cases"]), 28)
        count = len(f.local.observations())
        f.local.cli(self.request())
        self.assertEqual(len(f.local.observations()), count)
        audit = audit_workpack_completion(f.candidate, f.local.execution, "LAB_BOOTSTRAP", "LAB-PROTOCOL")
        self.assertTrue(all(row["status"] == "OBSERVED" for row in audit["command_observations"]))
        self.assertFalse(audit["workpack_accepted"])
        self.assertEqual(before, runtime._tree_snapshot(f.candidate))

    def test_verification_cannot_skip_committed_coding_or_replace_the_frozen_worker(self):
        f = self.fixture
        f.start(approve_coding=False)
        write_project(f.repository)
        f.approve(self.parent)
        completed, result = f.local.cli(self.request())
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertEqual(result["error"]["reason_code"], "PROJECT_VERIFICATION_BINDING_INVALID")
        self.assertEqual(len(f.local.observations()), 3)  # Startup only; verifier was not dispatched.
        continuation = deepcopy(self.parent)
        continuation["authorization_id"] = "TEST-EARLY-SUCCESSOR"
        continuation["local_execution"]["transitions"]["T-VERIFY"]["next_transition_id"] = "TEST-LATER"
        completed, result = f.local.cli({"parent": continuation}, command="prepare-runtime-authorization")
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertEqual(result["error"]["reason_code"], "LOCAL_RUNTIME_BINDING_INVALID")
        changed = deepcopy(self.parent)
        changed["authorization_id"] = "TEST-WORKER-SUBSTITUTION"
        changed["local_execution"]["transitions"]["T-VERIFY"]["command_contract"]["local_invocation"]["argv"] = [
            {"resource_ref": "harness-resource://runtime-tools/python"}, "--version"]
        completed, result = f.local.cli({"parent": changed}, command="prepare-runtime-authorization")
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertEqual(result["error"]["reason_code"], "PROJECT_VERIFICATION_BINDING_INVALID")

    def test_failed_project_behavior_is_observed_but_never_committed_as_pass(self):
        f = self.fixture
        f.start()
        completed, result = f.local.cli(f.request())
        self.assertEqual(completed.returncode, 0, result)
        write_project(f.repository, broken=True)
        f.approve(self.parent)
        f.local.cli(self.request())
        result = f.local.observations()[-1]["payload"]["result"]
        self.assertEqual(result["status"], "VALIDATION_FAILED", result)
        self.assertEqual(result["process_result"]["project_verification"]["status"], "FAIL")
        events = f.local.store.list_events(f.local.program)
        self.assertFalse(any(event["event_type"] == "TRANSITION_COMMITTED"
                             and event["payload"]["transition_id"] == "T-VERIFY" for event in events))

    def test_observed_verification_recovers_without_running_changed_project_again(self):
        f = self.fixture
        f.start()
        completed, result = f.local.cli(f.request())
        self.assertEqual(completed.returncode, 0, result)
        write_project(f.repository)
        f.approve(self.parent)
        adapter = prepare_local_runtime(f.local.database, f.local.program, self.parent["authorization_id"], {"T-VERIFY": self.transition})
        engine = GenericTransitionEngine(adapter.store, {LOCAL_CLASS: adapter}, binding_verifier=verify_runtime_factory_binding)
        with self.assertRaises(InjectedKernelCrash):
            engine.execute_transition(f.local.program, self.parent["authorization_id"], self.transition, {"approved": True},
                created_at=datetime.now(timezone.utc).isoformat(), inject_crash_after_command=True)
        count = len(f.local.observations())
        # This would fail if a resume silently reran the workload. The recovered
        # observation is historical protocol evidence, not fresh code acceptance.
        write_project(f.repository, broken=True)
        completed, result = f.local.cli(self.request())
        self.assertEqual(completed.returncode, 0, result)
        self.assertEqual(len(f.local.observations()), count)
        self.assertEqual(f.local.observations()[-1]["payload"]["result"]["process_result"]["project_verification"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
