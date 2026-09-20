"""Actual Factory/startup/SQLite integration; the model subprocess is TEST ONLY."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from harness_foundry_factory.coding_process import client_state_root, instruction_read_preflight
from harness_foundry_factory.coding_protocol import plan_coding_command
from harness_foundry_factory.coding_runtime import CODING_CLASS, CODING_MODE, bind_coding_transition, prepare_coding_runtime
from harness_foundry_factory.control_kernel import GenericTransitionEngine, InjectedKernelCrash
from harness_foundry_factory.execution_handoff import verify_runtime_factory_binding
from harness_foundry_factory.startup_runtime import STARTUP_CLASS, STARTUP_MODE, STARTUP_NODES, startup_transitions
from harness_foundry_factory.service import _tree_hash
from tests import test_execution_handoff as handoff_support, test_local_runtime as local_support
from tests import test_runtime_advance_cli as support, test_semantic_production_contracts as semantic_support
from tests.test_coding_process import fixture_executable


class CodingRuntimeTests(unittest.TestCase):
    def setUp(self):
        class Factory(handoff_support.ExecutionHandoffTests):
            def _canonical_ir(self):
                ir = super()._canonical_ir()
                semantic = semantic_support.semantic_ir(self.root / "unused-output", self.root / "planned-execution")
                for key in ("atoms", "coverage_edges", "acceptance_cases", "negative_cases"):
                    ir[key] = semantic[key]
                for atom in ir["atoms"]:
                    # The real UPDATE_REQUIREMENTS turn registers this test
                    # input. Do not retain the other fixture's source ID.
                    atom.pop("source_id", None)
                ir["target"].update(architecture_epoch=None, control_plane_epoch=None,
                                    production_semantics_mode=semantic["target"]["production_semantics_mode"])
                return ir
        self.factory = Factory()
        self.addCleanup(self.factory.tearDown)
        self.factory.setUp()
        self.handoff = self.factory._approve()
        self.local = local_support.LocalRuntimeFixture()
        self.local.setUp()
        self.addCleanup(self.local.doCleanups)
        self.local.program = "PROGRAM-1"
        self.bindings = self.handoff["runtime_bindings"]
        self.candidate = Path(self.handoff["candidate_root"])
        self.common_plan = {"candidate_root": str(self.candidate), "execution_root": str(self.local.execution),
            "control_db": str(self.local.database), "factory_source": {
                "database_path": str(self.factory.store.database_path), "runs_root": str(self.factory.root / "runs")}}
        self.startup = support.parent(self.local.program)
        self.startup.update(authorization_id="TEST-STARTUP", bindings=self.bindings, command_classes=[STARTUP_CLASS],
            allowed_read_roots=["harness-resource://candidate", "harness-resource://execution"],
            allowed_write_roots=["harness-resource://execution/.harness-foundry/control", "harness-resource://execution/evidence/engineering_dag"])
        self.startup["startup_execution"] = {**self.common_plan, "mode": STARTUP_MODE,
            "approval_receipt": self.handoff["approval_receipt"], "transitions": startup_transitions(self.candidate, self.bindings)}
        self.executable = fixture_executable(self.local.root)
        # The receiver now checks instruction reads even for this fake service.
        # Bind only existing instruction files, never the client/auth directory.
        self.instruction_resources = {
            f"harness-resource://runtime-tools/instruction-{index}": path
            for index, path in enumerate(instruction_read_preflight(self.local.root, [])["instruction_files"])
        }
        self.task = plan_coding_command(self.candidate, "LAB_BOOTSTRAP", "LAB-PROTOCOL", "LAB-CODEX-CODING")
        self.transition = self.coding_transition(self.task)
        self.parent = support.parent(self.local.program)
        self.parent.update(authorization_id="TEST-CODING", bindings=self.bindings, command_classes=[CODING_CLASS],
            allowed_read_roots=self.transition["allowed_read_roots"], allowed_write_roots=self.transition["allowed_write_roots"],
            network_mode="DECLARED_WRITE", secret_access=True, external_effect_class="EXTERNAL_REVERSIBLE",
            permissions=self.transition["risk"]["permissions"])
        self.parent["coding_execution"] = {**self.common_plan, "mode": CODING_MODE,
            "receiver": {"executable_abs": str(self.executable), "executable_sha256": local_support.digest(self.executable)},
            "runtime_resources": {"harness-resource://runtime-tools/codex": str(self.executable),
                                  **self.instruction_resources},
            "client_state_root": str(client_state_root()), "model": None, "output_limit_bytes": 65536,
            "transitions": {"T-CODING": self.transition}}
        self.repository = self.local.execution / "project_start_packages/external_lab/repository"

    def coding_transition(self, task):
        result = bind_coding_transition(support.transition("T-CODING", CODING_CLASS), task,
                                       runtime_read_refs=["harness-resource://runtime-tools/codex", *self.instruction_resources],
                                       timeout_seconds=10)
        result["bindings"] = self.bindings
        return result

    def approve(self, parent):
        completed, readback = self.local.cli({"parent": parent}, command="prepare-runtime-authorization")
        self.assertEqual(completed.returncode, 0, readback)
        challenge = readback["challenge"]
        completed, result = self.local.cli({"parent": parent, "challenge": challenge, "approval": {
            "decision": "APPROVE", "challenge_sha256": challenge["challenge_sha256"],
            "approved_by": {"type": "HUMAN_VIA_CODEX_CHAT", "chat_thread_id": "TEST-ONLY", "turn_id": "TEST-ONLY"},
            "approved_at": datetime.now(timezone.utc).isoformat()}}, command="approve-runtime-authorization")
        self.assertEqual(completed.returncode, 0, result)
        return challenge

    def request(self, startup=False):
        parent, key, mode = (self.startup, "startup_execution", STARTUP_MODE) if startup else (self.parent, "coding_execution", CODING_MODE)
        transitions = parent[key]["transitions"]
        return {"adapter_mode": mode, "program_id": self.local.program, "parent_authorization_id": parent["authorization_id"],
            "contracts": transitions, "inputs_by_transition": {node: {"requested": True} if startup else {"approved": True} for node in transitions},
            "start_transition_id": STARTUP_NODES[0] if startup else "T-CODING", "max_transitions": 3 if startup else 1,
            "expected_bindings": self.bindings, "expected_control_state_sha256": self.local.engine.control_state_sha256(self.local.program),
            "environment_manifest": {"scope": "TEST_ONLY_CODING_PROCESS_FIXTURE"}, "artifact_manifest": {"artifacts": []}}

    def start(self, *, approve_coding=True):
        self.approve(self.startup)
        completed, result = self.local.cli(self.request(startup=True))
        self.assertEqual(completed.returncode, 0, result)
        return self.approve(self.parent) if approve_coding else None

    def test_public_authorization_and_actual_process_use_the_existing_store_without_accepting_workpack(self):
        challenge = self.start()
        before = _tree_hash(self.factory.root)
        self.assertEqual(challenge["coding_execution"], self.parent["coding_execution"])
        self.assertTrue(challenge["coding_client_effects"]["may_refresh_saved_auth_and_write_client_state"])
        completed, result = self.local.cli(self.request())
        self.assertEqual(completed.returncode, 0, result)
        self.assertEqual((self.repository / "fixture-calls.txt").read_text().splitlines(), ["TEST_ONLY_NO_MODEL_REQUEST"])
        received = json.loads((self.repository / "fixture-input.json").read_text())
        self.assertTrue(received["prompt"].startswith(self.task["stdin_prompt"] + "\nHOST_RUNTIME_BINDINGS\n"))
        context = json.loads(received["prompt"].rsplit("\n", 1)[1])
        self.assertEqual(context["cwd"], str(self.repository))
        for field in ("read", "write"):
            self.assertEqual(sorted(context[f"allowed_{field}_bindings"]), self.transition[f"allowed_{field}_roots"])
        self.assertNotIn(str(self.factory.store.database_path), received["prompt"])
        self.assertNotIn(str(client_state_root()), context["allowed_read_bindings"].values())
        self.assertNotIn(str(client_state_root() / "auth.json"), received["prompt"])
        observation = self.local.observations()[-1]["payload"]["result"]
        self.assertEqual(observation["model_result"]["status"], "MODEL_TURN_COMPLETED")
        self.assertFalse(observation["workpack_accepted"])
        self.assertEqual(before, _tree_hash(self.factory.root))
        repeated, result = self.local.cli(self.request())
        self.assertEqual(repeated.returncode, 0, result)
        self.assertEqual(len((self.repository / "fixture-calls.txt").read_text().splitlines()), 1)

    def test_observed_process_recovers_without_model_redispatch(self):
        self.start()
        adapter = prepare_coding_runtime(self.local.database, self.local.program, self.parent["authorization_id"],
            {"T-CODING": self.transition}, binding_verifier=verify_runtime_factory_binding)
        engine = GenericTransitionEngine(self.local.store, {CODING_CLASS: adapter}, binding_verifier=verify_runtime_factory_binding)
        with self.assertRaises(InjectedKernelCrash):
            engine.execute_transition(self.local.program, self.parent["authorization_id"], self.transition,
                {"approved": True}, created_at=datetime.now(timezone.utc).isoformat(), inject_crash_after_command=True)
        completed, result = self.local.cli(self.request())
        self.assertEqual(completed.returncode, 0, result)
        self.assertEqual(len((self.repository / "fixture-calls.txt").read_text().splitlines()), 1)

    def test_public_checkpoint_and_resume_preserve_model_stage_binding(self):
        self.start()
        request = self.request()
        checkpoint_request = {key: value for key, value in request.items() if key in {
            "adapter_mode", "program_id", "parent_authorization_id", "expected_bindings",
            "expected_control_state_sha256", "environment_manifest", "artifact_manifest"}}
        checkpoint_request["resume_node"] = "T-CODING"
        completed, checkpoint = self.local.cli(checkpoint_request, command="checkpoint")
        self.assertEqual(completed.returncode, 0, checkpoint)
        capsule = checkpoint["resume_capsule"]
        request = self.request()
        resumed = {key: value for key, value in request.items() if key in {
            "adapter_mode", "expected_bindings", "expected_control_state_sha256", "environment_manifest", "artifact_manifest"}}
        resumed.update(resume_capsule=capsule, transition=self.transition, inputs={"approved": True},
                       expected_fencing_token=capsule["fencing_token"])
        completed, result = self.local.cli(resumed, command="resume")
        self.assertEqual(completed.returncode, 0, result)
        self.assertEqual(result["status"], "RESUMED")
        self.assertFalse(self.local.observations()[-1]["payload"]["result"]["workpack_accepted"])
        self.assertEqual(len((self.repository / "fixture-calls.txt").read_text().splitlines()), 1)

    def test_partial_capture_does_not_redispatch_a_model_stage(self):
        self.start()
        self.repository.mkdir(parents=True)
        (self.repository / "fixture-mode").write_text("malformed")
        completed, result = self.local.cli(self.request())
        self.assertEqual(result["stop_reason"], "UNKNOWN_SIDE_EFFECT", result)
        self.local.cli(self.request())
        self.assertEqual(len((self.repository / "fixture-calls.txt").read_text().splitlines()), 1)

    def test_no_parent_no_startup_or_missing_workpack_predecessor_cannot_dispatch(self):
        completed, result = self.local.cli(self.request())
        self.assertNotEqual(completed.returncode, 0, result)
        self.approve(self.parent)
        completed, result = self.local.cli(self.request())
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertFalse(self.repository.exists())
        self.start(approve_coding=False)
        later = plan_coding_command(self.candidate, "LAB_BOOTSTRAP", "LAB-CLI", "LAB-CODEX-CODING")
        self.transition = self.coding_transition(later)
        self.parent["authorization_id"] = "TEST-LATER-CODING"
        self.parent["allowed_read_roots"] = self.transition["allowed_read_roots"]
        self.parent["allowed_write_roots"] = self.transition["allowed_write_roots"]
        self.parent["coding_execution"]["transitions"] = {"T-CODING": self.transition}
        self.approve(self.parent)
        completed, result = self.local.cli(self.request())
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertEqual(result["error"]["reason_code"], "CODING_PREDECESSOR_ACCEPTANCE_REQUIRED")
        self.assertFalse(self.repository.exists())

    def test_task_substitution_and_factory_reopen_are_rejected_before_coding_output(self):
        invalid = deepcopy(self.parent)
        invalid["coding_execution"]["transitions"]["T-CODING"]["command_contract"]["coding_invocation"]["task_input"]["selection"]["node_id"] = "MISSING"
        completed, result = self.local.cli({"parent": invalid}, command="prepare-runtime-authorization")
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertIn("reason_code", result["error"])
        self.start()
        request = deepcopy(self.request())
        request["contracts"]["T-CODING"]["command_contract"]["coding_invocation"]["task_input"]["workpack"]["success_rule"] = "INVENTED"
        completed, result = self.local.cli(request)
        self.assertNotEqual(completed.returncode, 0, result)
        self.factory.send("REOPEN", {"reason": "TEST binding changed"}, delegated=False)
        completed, result = self.local.cli(self.request())
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertFalse(self.repository.exists())

    def test_offline_or_delegated_approval_cannot_grant_model_service_access(self):
        changed = deepcopy(self.parent)
        changed.update(network_mode="DENY", secret_access=False)
        completed, result = self.local.cli({"parent": changed}, command="prepare-runtime-authorization")
        self.assertNotEqual(completed.returncode, 0, result)
        completed, readback = self.local.cli({"parent": self.parent}, command="prepare-runtime-authorization")
        self.assertEqual(completed.returncode, 0, readback)
        challenge = readback["challenge"]
        completed, result = self.local.cli({"parent": self.parent, "challenge": challenge, "approval": {
            "decision": "APPROVE", "challenge_sha256": challenge["challenge_sha256"],
            "approved_by": {"type": "CODEX_DELEGATED_AGENT", "delegation_id": "TEST-ONLY-PREBUILD"},
            "approved_at": datetime.now(timezone.utc).isoformat()}}, command="approve-runtime-authorization")
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertFalse(self.repository.exists())
