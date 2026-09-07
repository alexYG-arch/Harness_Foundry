"""Temporary audited Candidate -> actual native actions -> one SQLite stream.

All authorizations are TEST ONLY. No production Program, model or Workpack runs.
"""

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import unittest

from harness_foundry_factory.control_kernel import ControlKernelError, GenericTransitionEngine, InjectedKernelCrash
from harness_foundry_factory.execution_handoff import verify_runtime_factory_binding
from harness_foundry_factory.service import _tree_hash
from harness_foundry_factory.startup_runtime import (
    STARTUP_MODE, STARTUP_CLASS, STARTUP_NODES, STATE_REF, EVENTS_REF,
    prepare_startup_runtime, project_startup_views, startup_transitions,
)
from tests import test_approved_start_package_runtime as support


class StartupSQLiteRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = support.ApprovedStartPackageRuntimeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.local = self.fixture.local
        self.parent = self.fixture.parent
        old = self.parent.pop("local_execution")
        self.local_plan = old
        self.parent.update(command_classes=[STARTUP_CLASS],
                           allowed_read_roots=["harness-resource://candidate", "harness-resource://execution"],
                           allowed_write_roots=["harness-resource://execution/.harness-foundry/control",
                                                "harness-resource://execution/evidence/engineering_dag"])
        self.parent["startup_execution"] = {
            "mode": STARTUP_MODE, **{field: old[field] for field in ("candidate_root", "execution_root", "control_db", "factory_source")},
            "approval_receipt": deepcopy(self.fixture.handoff["approval_receipt"]),
            "transitions": startup_transitions(old["candidate_root"], self.parent["bindings"])}
        self.transitions = self.parent["startup_execution"]["transitions"]

    def approve(self):
        return self.fixture.approve_runtime()

    def request(self, node=None):
        return {"adapter_mode": STARTUP_MODE, "program_id": self.local.program,
                "parent_authorization_id": self.parent["authorization_id"],
                "contracts": self.transitions, "inputs_by_transition": {node: {"requested": True} for node in STARTUP_NODES},
                "start_transition_id": node or STARTUP_NODES[0], "max_transitions": 3,
                "expected_bindings": self.parent["bindings"],
                "expected_control_state_sha256": self.local.engine.control_state_sha256(self.local.program),
                "environment_manifest": {"scope": "TEST_ONLY_NATIVE_STARTUP"}, "artifact_manifest": {"artifacts": []}}

    def test_public_cli_commits_native_startup_in_one_store_and_stops_before_lab(self):
        self.approve()
        before = _tree_hash(self.fixture.factory.root)
        completed, result = self.local.cli(self.request())
        self.assertEqual(completed.returncode, 0, result)
        self.assertEqual(result["stop_reason"], "TRANSITION_PATH_COMPLETE", result)
        rows = project_startup_views(self.local.store, self.local.program, self.local.execution)
        self.assertEqual([row["transition_id"] for row in rows], list(STARTUP_NODES))
        state = json.loads((self.local.execution / STATE_REF).read_text())
        self.assertEqual(state["next_node"], "LAB_BOOTSTRAP")
        self.assertFalse(state["driver_started"])
        self.assertIsNone(state["active_workpack"])
        self.assertIsNone(self.parent["bindings"]["architecture_epoch"])
        self.assertEqual(len((self.local.execution / EVENTS_REF).read_text().splitlines()), 3)
        for row in rows:
            native = row["result"]["native_transaction"]["result_payload"]
            self.assertEqual(native["status"], "PASS")
            self.assertEqual(native["authorization_id"], row["grant_id"])
        self.assertEqual(before, _tree_hash(self.fixture.factory.root))
        tip = self.local.store.list_events(self.local.program)
        repeated, receipt = self.local.cli(self.request())
        self.assertEqual(repeated.returncode, 0, receipt)
        self.assertEqual(tip, self.local.store.list_events(self.local.program))

    def test_observed_native_proposal_recovers_without_repeating_preparation(self):
        self.approve()
        adapter = prepare_startup_runtime(self.local.database, self.local.program,
                                          self.parent["authorization_id"], self.transitions)
        engine = GenericTransitionEngine(self.local.store, {STARTUP_CLASS: adapter}, binding_verifier=verify_runtime_factory_binding)
        with self.assertRaises(InjectedKernelCrash):
            engine.execute_transition(self.local.program, self.parent["authorization_id"], self.transitions[STARTUP_NODES[0]],
                                      {"requested": True}, created_at=datetime.now(timezone.utc).isoformat(), inject_crash_after_command=True)
        self.assertFalse((self.local.execution / "evidence/engineering_dag" / STARTUP_NODES[0] / "result.json").exists())
        completed, result = self.local.cli(self.request())
        self.assertEqual(completed.returncode, 0, result)
        self.assertEqual(result["stop_reason"], "TRANSITION_PATH_COMPLETE", result)
        observed = self.local.observations()
        self.assertEqual(len(observed), 3)
        self.assertEqual(self.local.store.verify_stream(self.local.program)["status"], "PASS")

    def test_missing_parent_reopen_and_skipped_node_fail_before_new_control_events(self):
        before = self.local.store.list_events(self.local.program)
        completed, result = self.local.cli(self.request())
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertEqual(before, self.local.store.list_events(self.local.program))
        self.approve()
        before = self.local.store.list_events(self.local.program)
        completed, result = self.local.cli(self.request(STARTUP_NODES[1]))
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertEqual(before, self.local.store.list_events(self.local.program))
        self.fixture.factory.send("REOPEN", {"reason": "TEST revoked startup approval"}, delegated=False)
        completed, result = self.local.cli(self.request())
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertEqual(result["error"]["code"], "EXECUTION_HANDOFF_BLOCKED")
        self.assertEqual(before, self.local.store.list_events(self.local.program))
        self.assertFalse((self.local.execution / STATE_REF).exists())

    def test_committed_views_rebuild_and_legacy_writers_cannot_commit(self):
        self.approve()
        completed, result = self.local.cli(self.request())
        self.assertEqual(completed.returncode, 0, result)
        from harness_foundry_factory.startup_runtime import _action, verify_startup_views
        expected = (self.local.execution / STATE_REF).read_bytes()
        before = self.local.store.list_events(self.local.program)
        (self.local.execution / STATE_REF).write_text('{"test":"corrupted derived view"}')
        with self.assertRaises(ControlKernelError):
            verify_startup_views(self.local.store, self.local.program, self.local.execution, self.parent["bindings"])
        repeated, receipt = self.local.cli(self.request())
        self.assertEqual(repeated.returncode, 0, receipt)
        self.assertEqual((self.local.execution / STATE_REF).read_bytes(), expected)
        self.assertEqual(before, self.local.store.list_events(self.local.program))
        verify_startup_views(self.local.store, self.local.program, self.local.execution, self.parent["bindings"])
        for node in STARTUP_NODES:
            action = _action(Path(self.parent["startup_execution"]["candidate_root"]), node)
            with self.assertRaises(action.ContractError) as caught:
                action.execute_action(Path(self.parent["startup_execution"]["candidate_root"]), self.local.execution,
                                      self.local.execution / "no-command", self.local.execution / "no-authorization")
            self.assertEqual(caught.exception.code, "SQLITE_CONTROLLER_OWNS_STATE")
        from harness_foundry_factory.workpack_runtime import RuntimeContractError, execute_hydrated_workpack
        with self.assertRaises(RuntimeContractError) as caught:
            execute_hydrated_workpack(Path(self.parent["startup_execution"]["candidate_root"]), self.local.execution, {}, {})
        self.assertEqual(caught.exception.code, "SQLITE_CONTROLLER_OWNS_STATE")

    @unittest.skipUnless(os.environ.get("HFFACTORY_TEST_CODEX_SANDBOX"), "real local sandbox opt-in not configured")
    def test_native_startup_and_job_process_share_one_authoritative_stream(self):
        self.approve()
        completed, result = self.local.cli(self.request())
        self.assertEqual(completed.returncode, 0, result)
        job_parent = deepcopy(self.parent)
        job_parent.pop("startup_execution")
        job_parent.update(authorization_id=self.parent["authorization_id"] + "-JOB",
                          allowed_read_roots=["harness-resource://candidate", "harness-resource://execution/jobs",
                                              "harness-resource://execution/evidence/job_artifact_leases", "harness-resource://runtime-tools"],
                          allowed_write_roots=["harness-resource://execution/jobs", "harness-resource://execution/evidence/job_artifact_leases"],
                          local_execution=self.local_plan)
        from harness_foundry_factory.local_runtime import LOCAL_CLASS
        job_parent["command_classes"] = [LOCAL_CLASS]
        self.fixture.parent = self.local.parent = job_parent
        self.fixture.approve_runtime()
        completed, result = self.local.cli(self.fixture.request())
        self.assertEqual(completed.returncode, 0, result)
        self.assertEqual(result["stop_reason"], "TRANSITION_PATH_COMPLETE", result)
        self.assertEqual((self.local.execution / "jobs/JOB-A/output/output").read_text(), "JOB-A")
        from harness_foundry_factory.control_kernel import rebuild_control_projections
        projection = rebuild_control_projections(self.local.store.list_events(self.local.program))
        self.assertEqual(set(projection["program_control_state"]["completed_transitions"]), {*STARTUP_NODES, "T-LOCAL"})
        self.assertEqual(self.local.store.verify_stream(self.local.program)["status"], "PASS")

    def test_unowned_legacy_state_is_not_imported_or_overwritten(self):
        self.approve()
        path = self.local.execution / STATE_REF
        path.parent.mkdir(parents=True)
        path.write_text('{"test":"existing legacy controller"}')
        before = self.local.store.list_events(self.local.program)
        completed, result = self.local.cli(self.request())
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertEqual(result["error"]["reason_code"], "LOCAL_LEGACY_CONTROLLER_PRESENT")
        self.assertEqual(path.read_text(), '{"test":"existing legacy controller"}')
        self.assertEqual(before, self.local.store.list_events(self.local.program))

    def test_independent_validator_requires_the_produced_preparation_interface(self):
        from harness_foundry_factory.validator import _control_startup_profile_ref
        candidate = Path(self.parent["startup_execution"]["candidate_root"])
        profile = json.loads((candidate / "validation/CONTROL_STARTUP_PROFILE.json").read_text())
        self.assertEqual(profile["sqlite_controller_contract"]["mode"], STARTUP_MODE)
        path = candidate / "tools/control_plane_registration.py"
        path.chmod(path.stat().st_mode | 0o200)
        path.write_text(path.read_text().replace("def prepare_action(", "def removed_preparation("))
        findings = []
        _control_startup_profile_ref(candidate, findings)
        self.assertIn("CONTROL_ACTION_PREPARATION_MISSING", {finding["code"] for finding in findings})

    def test_input_publication_failure_is_observed_and_never_replayed(self):
        self.approve()
        outside = self.local.root / "unrelated-input-root"
        outside.mkdir()
        control = self.local.execution / ".harness-foundry/control"
        control.mkdir()
        (control / "action_inputs").symlink_to(outside, target_is_directory=True)
        completed, result = self.local.cli(self.request())
        self.assertEqual(completed.returncode, 0, result)
        self.assertEqual(result["stop_reason"], "DETERMINISTIC_VALIDATION_FAILURE", result)
        self.assertEqual(list(outside.iterdir()), [])
        before = self.local.store.list_events(self.local.program)
        completed, result = self.local.cli(self.request())
        self.assertEqual(completed.returncode, 0, result)
        self.assertEqual(result["stop_reason"], "DETERMINISTIC_VALIDATION_FAILURE", result)
        self.assertEqual(before, self.local.store.list_events(self.local.program))
        self.assertEqual(len(self.local.observations()), 1)

    def test_public_checkpoint_resume_then_remaining_startup_uses_the_same_store(self):
        self.approve()
        checkpoint = {key: value for key, value in self.request().items() if key in {
            "adapter_mode", "program_id", "parent_authorization_id", "expected_bindings",
            "expected_control_state_sha256", "environment_manifest", "artifact_manifest"}}
        completed, result = self.local.cli({**checkpoint, "resume_node": STARTUP_NODES[0]}, command="checkpoint")
        self.assertEqual(completed.returncode, 0, result)
        capsule = result["resume_capsule"]
        resume = {key: value for key, value in checkpoint.items() if key not in {"program_id", "parent_authorization_id"}}
        resume.update(resume_capsule=capsule, transition=self.transitions[STARTUP_NODES[0]], inputs={"requested": True},
                      expected_fencing_token=capsule["fencing_token"],
                      expected_control_state_sha256=self.local.engine.control_state_sha256(self.local.program))
        completed, result = self.local.cli(resume, command="resume")
        self.assertEqual(completed.returncode, 0, result)
        self.assertEqual(result["status"], "RESUMED")
        completed, result = self.local.cli(self.request(STARTUP_NODES[1]))
        self.assertEqual(completed.returncode, 0, result)
        self.assertEqual(len(project_startup_views(self.local.store, self.local.program, self.local.execution)), 3)
