"""Real temporary Factory approval to scoped runtime, preserving unbound epochs.

The authoring and Parent decisions below are TEST ONLY. No production Program,
model, target Workpack, Driver, or media is executed by these integration tests.
"""

from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
import unittest

from harness_foundry_factory.control_kernel import (
    ControlKernelError, GenericTransitionEngine, START_PACKAGE_BINDING_KIND,
    _validate_program_graph_bindings, prepare_parent_authorization_challenge,
    rebuild_control_projections,
)
from harness_foundry_factory.execution_handoff import ExecutionHandoffError, verify_runtime_factory_binding
from harness_foundry_factory.local_runtime import LOCAL_CLASS
from harness_foundry_factory.service import _tree_hash
from tests import test_execution_handoff as handoff_support
from tests import test_local_runtime as local_support
from tests import test_runtime_advance_cli as support


class ApprovedStartPackageRuntimeTests(unittest.TestCase):
    def setUp(self):
        class Fixture(handoff_support.ExecutionHandoffTests):
            def _canonical_ir(self):
                ir = super()._canonical_ir()
                ir["target"].update(architecture_epoch=None, control_plane_epoch=None)
                return ir

        self.factory = Fixture()
        self.factory.setUp()
        self.addCleanup(self.factory.tearDown)
        self.handoff = self.factory._approve()
        self.local = local_support.LocalRuntimeFixture()
        self.local.setUp()
        self.addCleanup(self.local.doCleanups)
        self.local.program = "PROGRAM-1"
        self.parent = self.local.parent
        self.parent.update(program_id=self.local.program, authorization_id="PARENT-TEST-FACTORY-RUNTIME",
                           bindings=deepcopy(self.handoff["runtime_bindings"]))
        plan = self.parent["local_execution"]
        plan["candidate_root"] = self.handoff["candidate_root"]
        plan["factory_source"] = {"database_path": str(self.factory.store.database_path),
                                  "runs_root": str(self.factory.root / "runs")}
        self.transition = plan["transitions"]["T-LOCAL"]
        self.transition["bindings"] = deepcopy(self.parent["bindings"])

    def approve_runtime(self):
        challenge = prepare_parent_authorization_challenge(self.parent, expected_bindings=self.parent["bindings"])
        self.local.engine.register_approved_parent_authorization(self.parent, challenge, {
            "decision": "APPROVE", "challenge_sha256": challenge["challenge_sha256"],
            "approved_by": {"type": "HUMAN_VIA_CODEX_CHAT", "chat_thread_id": "TEST-ONLY", "turn_id": "TEST-ONLY"},
            "approved_at": support.NOW}, created_at=support.NOW)
        return challenge

    def request(self):
        request = self.local.request()
        request["expected_bindings"] = deepcopy(self.parent["bindings"])
        return request

    def checkpoint_request(self):
        request = {key: value for key, value in self.request().items() if key in {
            "adapter_mode", "program_id", "parent_authorization_id", "expected_bindings",
            "expected_control_state_sha256", "environment_manifest", "artifact_manifest"}}
        return {**request, "resume_node": "T-LOCAL"}

    def checkpoint(self):
        completed, result = self.local.cli(self.checkpoint_request(), command="checkpoint")
        self.assertEqual(completed.returncode, 0, result)
        self.assertEqual(result["status"], "RESUME_READY", result)
        return result["resume_capsule"]

    def resume_request(self, capsule):
        request = {key: value for key, value in self.checkpoint_request().items() if key not in {
            "program_id", "parent_authorization_id", "resume_node"}}
        return {**request, "resume_capsule": capsule, "transition": self.transition,
                "inputs": {"approved": True}, "expected_fencing_token": capsule["fencing_token"]}

    def test_actual_handoff_preserves_nulls_without_fabricated_lock_hashes(self):
        binding = self.parent["bindings"]
        self.assertEqual(binding["binding_kind"], START_PACKAGE_BINDING_KIND)
        self.assertIsNone(binding["architecture_epoch"])
        self.assertIsNone(binding["control_plane_epoch"])
        self.assertNotIn("architecture_lock_sha256", binding)
        self.assertNotIn("requirement_lock_sha256", binding)
        self.assertNotIn("compiled_contract_sha256", binding)
        for key in ("requirement_ir_sha256", "candidate_tree_sha256", "factory_candidate_content_sha256"):
            self.assertEqual(binding[key], self.handoff["approval_receipt"][key])
        before = _tree_hash(self.factory.root)
        self.assertEqual(verify_runtime_factory_binding(self.parent), binding)
        self.assertEqual(before, _tree_hash(self.factory.root))
        self.assertFalse(self.handoff["approval_receipt"]["execution_authorized"])

    def test_handoff_does_not_itself_grant_a_runtime_parent(self):
        completed, result = self.local.cli(self.request())
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertEqual(result["error"]["reason_code"], "PARENT_AUTHORIZATION_NOT_ACTIVE")
        self.assertEqual(self.local.store.list_events(self.local.program), [])

    def test_kind_epoch_and_program_changes_cannot_reuse_the_approval_contract(self):
        for changes in ({"architecture_epoch": 0, "control_plane_epoch": 0},
                        {"architecture_epoch": False, "control_plane_epoch": False},
                        {"architecture_epoch": 1}, {"binding_kind": "UNKNOWN"},
                        {"program_id": "OTHER"}):
            with self.subTest(changes=changes):
                parent = deepcopy(self.parent)
                parent["bindings"].update(changes)
                with self.assertRaises(ControlKernelError):
                    prepare_parent_authorization_challenge(parent, expected_bindings=parent["bindings"])
        legacy = support.parent("PROGRAM-LEGACY")
        legacy["bindings"].update(architecture_epoch=None, control_plane_epoch=None)
        with self.assertRaises(ControlKernelError):
            prepare_parent_authorization_challenge(legacy, expected_bindings=legacy["bindings"])

    def test_graph_projection_retains_the_complete_discriminated_binding(self):
        binding = self.parent["bindings"]
        profile, template = {"bindings": binding}, {"bindings": binding}
        self.assertEqual(_validate_program_graph_bindings(profile, template, {"T": self.transition}, binding), binding)
        changed = deepcopy(self.transition)
        changed["bindings"]["architecture_epoch"] = 0
        with self.assertRaises(ControlKernelError):
            _validate_program_graph_bindings(profile, template, {"T": changed}, binding)
        positive = {**binding, "architecture_epoch": 1, "control_plane_epoch": 1}
        self.assertEqual(_validate_program_graph_bindings({"bindings": positive}, {"bindings": positive},
                                                         {"T": {"bindings": positive}}, positive), positive)
        # Python bool/int equality cannot turn a Boolean into a positive lock.
        changed = {**positive, "architecture_epoch": True, "control_plane_epoch": True}
        with self.assertRaises(ControlKernelError):
            _validate_program_graph_bindings({"bindings": positive}, {"bindings": changed}, {}, positive)

    def test_generic_engine_requires_live_verifier_before_reserving_command(self):
        challenge = self.approve_runtime()
        self.assertEqual(challenge["bindings"], self.parent["bindings"])
        self.assertEqual(challenge["local_execution"]["factory_source"], self.parent["local_execution"]["factory_source"])
        before = self.local.store.list_events(self.local.program)
        engine = GenericTransitionEngine(self.local.store, {LOCAL_CLASS: lambda context: self.fail("must not dispatch")})
        with self.assertRaises(ControlKernelError) as caught:
            engine.execute_transition(self.local.program, self.parent["authorization_id"], self.transition,
                                      {"approved": True}, created_at=datetime.now(timezone.utc).isoformat())
        self.assertEqual(caught.exception.code, "RUNTIME_BINDING_VERIFIER_REQUIRED")
        self.assertEqual(before, self.local.store.list_events(self.local.program))

    def test_cli_rechecks_reopened_factory_before_any_command_intent(self):
        self.approve_runtime()
        self.factory.send("REOPEN", {"reason": "TEST invalidation before dispatch"}, delegated=False)
        before = self.local.store.list_events(self.local.program)
        completed, result = self.local.cli(self.request())
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertEqual(result["error"]["code"], "EXECUTION_HANDOFF_BLOCKED")
        self.assertEqual(before, self.local.store.list_events(self.local.program))
        self.assertFalse((self.local.execution / "jobs/JOB-A/output").exists())

    def test_cli_rejects_another_physical_candidate_root(self):
        self.parent["local_execution"]["candidate_root"] = str(self.local.candidate)
        self.approve_runtime()
        completed, result = self.local.cli(self.request())
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertEqual(result["error"]["details"]["reason"], "HANDOFF_ROOT_MISMATCH")
        self.assertEqual(self.local.observations(), [])

    def test_cli_rechecks_published_bytes_before_command_intent(self):
        self.approve_runtime()
        path = self.factory.candidate / "README.md"
        path.chmod(path.stat().st_mode | 0o200)
        path.write_text(path.read_text() + "\nTemporary fixture byte drift.\n")
        before = self.local.store.list_events(self.local.program)
        completed, result = self.local.cli(self.request())
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertEqual(result["error"]["details"]["reason"], "CANDIDATE_BINDING_STALE")
        self.assertEqual(before, self.local.store.list_events(self.local.program))
        self.assertFalse((self.local.execution / "jobs/JOB-A/output").exists())

    def test_public_checkpoint_preserves_binding_and_does_not_execute(self):
        self.approve_runtime()
        before = _tree_hash(self.factory.root)
        capsule = self.checkpoint()
        self.assertEqual(capsule["bindings"], self.parent["bindings"])
        self.assertIsNone(capsule["bindings"]["architecture_epoch"])
        self.assertEqual(before, _tree_hash(self.factory.root))
        self.assertFalse((self.local.execution / "jobs/JOB-A/output").exists())
        self.assertEqual(self.local.observations(), [])

    def test_checkpoint_rejects_unapproved_node_or_caller_time_without_writes(self):
        self.approve_runtime()
        before = self.local.store.list_events(self.local.program)
        for updates in ({"resume_node": "T-NOT-APPROVED"}, {"created_at": support.NOW},
                        {"adapter_mode": "TEST_ONLY"}):
            with self.subTest(updates=updates):
                completed, result = self.local.cli({**self.checkpoint_request(), **updates}, command="checkpoint")
                self.assertNotEqual(completed.returncode, 0, result)
                self.assertEqual(result["error"]["reason_code"], "LOCAL_RUNTIME_REQUEST_INVALID")
                self.assertEqual(before, self.local.store.list_events(self.local.program))

    def test_checkpoint_and_resume_recheck_factory_before_recording_recovery_events(self):
        self.approve_runtime()
        capsule = self.checkpoint()
        self.factory.send("REOPEN", {"reason": "TEST invalidation before recovery"}, delegated=False)
        before = self.local.store.list_events(self.local.program)
        for command, request in (("resume", self.resume_request(capsule)),
                                 ("checkpoint", self.checkpoint_request())):
            with self.subTest(command=command):
                completed, result = self.local.cli(request, command=command)
                self.assertNotEqual(completed.returncode, 0, result)
                self.assertEqual(result["error"]["code"], "EXECUTION_HANDOFF_BLOCKED")
                self.assertEqual(before, self.local.store.list_events(self.local.program))
        self.assertFalse((self.local.execution / "jobs/JOB-A/output").exists())

    def test_factory_change_after_effect_retains_observation_without_stale_commit_or_replay(self):
        self.approve_runtime()
        effect = self.local.root / "observed-effects"

        def adapter(context):
            with effect.open("a") as stream:
                stream.write("ONCE\n")
            self.factory.send("REOPEN", {"reason": "TEST invalidation during command"}, delegated=False)
            return {"status": "PASS", "reason_code": "TEST_EFFECT_WRITTEN", "artifact_id": "TEST-EFFECT",
                    "process_result": {"exit_code": 0}, "job_lease": {}}

        engine = GenericTransitionEngine(self.local.store, {LOCAL_CLASS: adapter},
                                         binding_verifier=verify_runtime_factory_binding)
        for _ in range(2):
            with self.assertRaises(ExecutionHandoffError):
                engine.execute_transition(self.local.program, self.parent["authorization_id"], self.transition,
                                          {"approved": True}, created_at=datetime.now(timezone.utc).isoformat())
        self.assertEqual(effect.read_text(), "ONCE\n")
        self.assertEqual(len(self.local.observations()), 1)
        ledger = rebuild_control_projections(self.local.store.list_events(self.local.program))
        self.assertEqual(ledger["program_control_state"]["completed_transitions"], {})

    @unittest.skipUnless(os.environ.get("HFFACTORY_TEST_CODEX_SANDBOX"), "real local sandbox opt-in not configured")
    def test_real_public_cli_executes_with_null_epochs_and_keeps_factory_read_only(self):
        self.approve_runtime()
        before = _tree_hash(self.factory.root)
        completed, result = self.local.cli(self.request())
        self.assertEqual(completed.returncode, 0, result)
        self.assertEqual(result["stop_reason"], "TRANSITION_PATH_COMPLETE", result)
        receipt = result["transition_receipts"][0]
        self.assertEqual(receipt["status"], "COMMITTED")
        self.assertEqual(receipt["result"]["process_result"]["exit_code"], 0)
        self.assertEqual((self.local.execution / "jobs/JOB-A/output/output").read_text(), "JOB-A")
        self.assertEqual(before, _tree_hash(self.factory.root))
        self.assertEqual(self.local.store.verify_stream(self.local.program)["status"], "PASS")

    @unittest.skipUnless(os.environ.get("HFFACTORY_TEST_CODEX_SANDBOX"), "real local sandbox opt-in not configured")
    def test_real_public_checkpoint_and_resume_use_the_same_factory_binding(self):
        self.approve_runtime()
        before = _tree_hash(self.factory.root)
        capsule = self.checkpoint()
        completed, result = self.local.cli(self.resume_request(capsule), command="resume")
        self.assertEqual(completed.returncode, 0, result)
        self.assertEqual(result["status"], "RESUMED", result)
        self.assertEqual(result["transition_receipt"]["status"], "COMMITTED", result)
        self.assertEqual((self.local.execution / "jobs/JOB-A/output/output").read_text(), "JOB-A")
        self.assertEqual(before, _tree_hash(self.factory.root))
        self.assertEqual(self.local.store.verify_stream(self.local.program)["status"], "PASS")
