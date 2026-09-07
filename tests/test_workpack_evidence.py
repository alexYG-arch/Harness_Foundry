"""Actual temporary startup provenance; no model process or formal Program."""

from copy import deepcopy
import unittest

from harness_foundry_factory.workpack_acceptance import plan_workpack_completion, audit_workpack_completion
from harness_foundry_factory.workpack_evidence import committed_native_attempts, predecessor_capability_observations
from harness_foundry_factory.coding_runtime import _predecessors
from harness_foundry_factory.control_kernel import ControlKernelError
from tests import test_coding_runtime as coding


class WorkpackEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = coding.CodingRuntimeTests()
        cls.fixture.setUp()
        cls.addClassCleanup(cls.fixture.doCleanups)
        cls.fixture.start(approve_coding=False)
        cls.events = cls.fixture.local.store.list_events(cls.fixture.local.program)
        cls.plan = plan_workpack_completion(cls.fixture.candidate, "LAB_BOOTSTRAP", "LAB-PROTOCOL")

    def test_startup_capability_has_actual_parent_observation_and_commit(self):
        result = predecessor_capability_observations(self.events, self.plan)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "ENGINEERING_DAG:SHARED_CONTROL_BASELINE_LOCK")
        self.assertEqual(result[0]["status"], "OBSERVED", result)
        self.assertEqual(len(result[0]["observations"]), 1)
        self.assertEqual(len(list(committed_native_attempts(self.events, self.plan["program_id"], self.plan["candidate_tree_sha256"]))), 3)
        self.assertEqual(self.events, self.fixture.local.store.list_events(self.fixture.local.program))
        self.assertFalse(self.fixture.repository.exists())

    def test_unobserved_or_uncommitted_startup_cannot_supply_capability(self):
        for missing in ("COMMAND_RESULT_OBSERVED", "TRANSITION_COMMITTED"):
            events = [event for event in self.events if event["event_type"] != missing]
            self.assertEqual(predecessor_capability_observations(events, self.plan)[0]["status"], "MISSING")

    def test_another_program_or_candidate_does_not_reuse_capability(self):
        for key, value in (("program_id", "ANOTHER-PROGRAM"), ("candidate_tree_sha256", "OTHER-CANDIDATE")):
            self.assertEqual(predecessor_capability_observations(self.events, {**self.plan, key: value})[0]["status"], "MISSING")

    def test_observation_must_belong_to_the_exact_native_attempt(self):
        for field in ("attempt_id", "transition_id"):
            events = deepcopy(self.events)
            for event in events:
                if event["event_type"] == "COMMAND_RESULT_OBSERVED":
                    event["payload"][field] = "ANOTHER-ATTEMPT"
            self.assertEqual(predecessor_capability_observations(events, self.plan)[0]["status"], "MISSING")

    def test_workpack_acceptance_is_not_inferred_from_a_declared_or_unknown_source(self):
        for source in ("PROJECT_WORKPACK:LAB-PROTOCOL", "UNREGISTERED:LAB-PROTOCOL", None):
            plan = {**self.plan, "capability_sources": {self.plan["required_capabilities"][0]: source}}
            self.assertEqual(predecessor_capability_observations(self.events, plan)[0]["status"], "PROVIDER_NOT_IMPLEMENTED")

    def test_missing_capability_or_mismatched_observation_does_not_pass(self):
        plan = {**self.plan, "required_capabilities": ["NOT-PRODUCED"],
                "capability_sources": {"NOT-PRODUCED": "ENGINEERING_DAG:SHARED_CONTROL_BASELINE_LOCK"}}
        self.assertEqual(predecessor_capability_observations(self.events, plan)[0]["status"], "MISSING")
        events = deepcopy(self.events)
        for event in events:
            if event["event_type"] == "COMMAND_RESULT_OBSERVED":
                event["payload"]["result"]["status"] = "VALIDATION_FAILED"
        self.assertEqual(predecessor_capability_observations(events, self.plan)[0]["status"], "MISSING")

    def test_coding_preflight_consumes_the_required_capability_provenance(self):
        f = self.fixture
        _predecessors(f.local.store, f.parent, f.task)
        task = deepcopy(f.task)
        task["task_input"]["workpack"]["requires"] = ["NOT-PRODUCED"]
        task["task_input"]["workpack"]["requirement_sources"] = {
            "NOT-PRODUCED": "ENGINEERING_DAG:SHARED_CONTROL_BASELINE_LOCK"}
        with self.assertRaises(ControlKernelError) as error:
            _predecessors(f.local.store, f.parent, task)
        self.assertEqual(error.exception.code, "CODING_REQUIRED_CAPABILITY_EVIDENCE_MISSING")
        self.assertFalse(f.repository.exists())
        self.assertEqual(self.events, f.local.store.list_events(f.local.program))

    def test_read_only_audit_reports_proven_startup_without_accepting_workpack(self):
        f = self.fixture
        result = audit_workpack_completion(f.candidate, f.local.execution, "LAB_BOOTSTRAP", "LAB-PROTOCOL")
        self.assertEqual(result["capability_observations"][0]["status"], "OBSERVED")
        self.assertTrue(all(row["status"] == "MISSING" for row in result["command_observations"]))
        self.assertFalse(result["workpack_accepted"])
        self.assertEqual(result["produced_capabilities"], [])
        self.assertFalse(result["controller_events_written"])
        self.assertEqual(self.events, f.local.store.list_events(f.local.program))
