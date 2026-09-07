"""Normal Candidate + real stored observations; no semantic acceptance claims."""

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from harness_foundry_factory import workpack_acceptance as acceptance
from harness_foundry_factory import workpack_runtime as runtime
from harness_foundry_factory.coding_runtime import CODING_CLASS, prepare_coding_runtime
from harness_foundry_factory.control_kernel import GenericTransitionEngine, InjectedKernelCrash
from harness_foundry_factory.execution_handoff import verify_runtime_factory_binding
from harness_foundry_factory.store import ControlEventStore
from tests import test_normal_workpack_runtime as normal, test_coding_runtime as coding


class WorkpackCompletionTests(unittest.TestCase):
    target_overrides = normal.NormalWorkpackRuntimeTests.target_overrides
    setUpClass = classmethod(normal.NormalWorkpackRuntimeTests.setUpClass.__func__)
    tearDownClass = classmethod(normal.NormalWorkpackRuntimeTests.tearDownClass.__func__)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(temporary.cleanup)
        self.execution = Path(temporary.name)

    def audit(self):
        return acceptance.audit_workpack_completion(self.semantic_candidate, self.execution, "LAB_BOOTSTRAP", "LAB-PROTOCOL")

    def artifact(self):
        plan = acceptance.plan_workpack_completion(self.semantic_candidate, "LAB_BOOTSTRAP", "LAB-PROTOCOL")
        artifact = plan["artifacts"][0]
        path = self.execution / artifact["artifact_ref"].removeprefix("harness-resource://execution/")
        path.parent.mkdir(parents=True)
        return artifact, path

    def test_complete_native_unit_and_non_artifact_obligations_survive_every_workpack_plan(self):
        dag = json.loads((self.semantic_candidate / runtime.DAG_REF).read_text())
        seen = []
        before = runtime._tree_snapshot(self.root)
        for node in dag["nodes"]:
            if not (node.get("project_workpack_sequence") or node.get("workpack_id")):
                continue
            native = runtime.plan_workpack_node(self.semantic_candidate, node["node_id"])
            for index, unit in enumerate(native["units"]):
                plan = acceptance.plan_workpack_completion(self.semantic_candidate, node["node_id"], unit["workpack_id"])
                self.assertEqual(plan["unit"], unit)
                self.assertEqual(plan["semantic_contract"], unit["task_bundle"])
                self.assertEqual(plan["command_execution_order"], unit["workpack"]["command_execution_order"])
                self.assertEqual(plan["required_prior_workpacks"], [item["workpack_id"] for item in native["units"][:index]])
                seen.append(unit["workpack_id"])
        self.assertIn("LAB-PROTOCOL", seen)
        self.assertIn("LINK-PROTOCOL", seen)
        self.assertIn("MB-P4", seen)
        self.assertEqual(before, runtime._tree_snapshot(self.root))

    def test_schema_valid_self_report_cannot_become_independent_workpack_acceptance(self):
        artifact, path = self.artifact()
        value = {key: rule["const"] for key, rule in artifact["schema"]["properties"].items() if "const" in rule}
        value["evidence_refs"] = ["TEST-ONLY-SELF-REPORT-PASS"]
        path.write_text(json.dumps(value))
        before = runtime._tree_snapshot(self.root)
        result = self.audit()
        self.assertEqual(result["artifact_observations"][0]["schema"], "PASS")
        self.assertEqual(result["artifact_observations"][0]["oracle"], "NOT_EVALUATED")
        self.assertEqual(result["command_observations"][0]["status"], "MISSING")
        self.assertIn("lab_case_execution_contract", result["remaining_semantic_scope"]["task_contract"])
        self.assertEqual(result["status"], "WORKPACK_EVIDENCE_INCOMPLETE")
        self.assertFalse(result["workpack_accepted"])
        self.assertEqual(result["produced_capabilities"], [])
        self.assertEqual(before, runtime._tree_snapshot(self.root))

    def test_missing_and_schema_invalid_artifacts_have_distinct_observations(self):
        result = self.audit()
        self.assertEqual(result["artifact_observations"][0]["schema"], "MISSING")
        _, path = self.artifact()
        path.write_text('{"status":"PASS"}')
        result = self.audit()
        self.assertEqual(result["artifact_observations"][0]["schema"], "FAIL")
        self.assertTrue(result["artifact_observations"][0]["errors"])
        self.assertFalse(result["workpack_accepted"])

    def test_job_bytes_are_not_read_without_a_current_read_lease(self):
        artifact, _ = self.artifact()
        artifact["artifact_ref"] = "harness-resource://execution/jobs/JOB-1/output/result.json"
        with patch.object(Path, "read_bytes", side_effect=AssertionError("Job bytes must not be opened")):
            result = acceptance._schema_observation(self.semantic_candidate, self.execution, artifact)
        self.assertEqual(result["reason_code"], "JOB_READ_LEASE_REQUIRED")

    def test_schema_references_do_not_trigger_network_or_silent_dialect_fallback(self):
        artifact, path = self.artifact()
        path.write_text("{}")
        artifact["schema"] = {"$ref": "https://example.invalid/not-authorized.json"}
        result = acceptance._schema_observation(self.semantic_candidate, self.execution, artifact)
        self.assertEqual(result["reason_code"], "JSON_SCHEMA_CONTRACT_UNRESOLVED")
        artifact["schema"] = {"$schema": "http://json-schema.org/draft-07/schema#"}
        result = acceptance._schema_observation(self.semantic_candidate, self.execution, artifact)
        self.assertEqual(result["reason_code"], "JSON_SCHEMA_DIALECT_UNSUPPORTED")

    def test_structural_only_or_wrong_workpack_is_not_silently_completed(self):
        with self.assertRaises(runtime.RuntimeContractError):
            acceptance.plan_workpack_completion(self.semantic_candidate, "LAB_BOOTSTRAP", "LINK-PROTOCOL")
        result = acceptance.audit_workpack_completion(self.candidate, self.execution, "LAB_BOOTSTRAP", "LAB-PROTOCOL")
        self.assertIn("NATIVE_SEMANTIC_TASK_BUNDLE_MISSING", result["unresolved_requirements"])
        self.assertFalse(result["workpack_accepted"])

    def test_packaged_cli_is_read_only_and_incomplete_audit_has_nonzero_exit(self):
        before = runtime._tree_snapshot(self.root)
        command = [sys.executable, "-B", str(self.semantic_candidate / runtime.RUNTIME_ENTRYPOINT_REF),
                   "completion-plan", "--candidate-root", str(self.semantic_candidate),
                   "--node-id", "LAB_BOOTSTRAP", "--workpack-id", "LAB-PROTOCOL"]
        planned = subprocess.run(command, capture_output=True, text=True, timeout=60)
        self.assertEqual(planned.returncode, 0, planned.stderr)
        self.assertEqual(json.loads(planned.stdout)["status"], "DECLARED_WORKPACK_COMPLETION_PLAN")
        command[3] = "audit-completion"
        audited = subprocess.run([*command, "--execution-root", str(self.execution)], capture_output=True, text=True, timeout=60)
        self.assertEqual(audited.returncode, 1, audited.stderr)
        self.assertEqual(json.loads(audited.stdout)["status"], "WORKPACK_EVIDENCE_INCOMPLETE")
        self.assertEqual(before, runtime._tree_snapshot(self.root))

    def test_committed_wal_bytes_are_included_without_opening_source_sqlite(self):
        database = self.execution / ".harness-foundry/control.sqlite3"
        store = ControlEventStore(database)
        # Keep a real connection open so the committed event stays in WAL.
        connection = sqlite3.connect(database)
        self.addCleanup(connection.close)
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("BEGIN")
        connection.execute("SELECT count(*) FROM control_events").fetchone()
        expected = store.append_batch("TEST-PROGRAM", [{"event_type": "TEST_ONLY", "payload": {"value": 1}}],
            idempotency_key="TEST-1", created_at="2026-09-07T00:00:00Z")
        self.assertGreater(Path(str(database) + "-wal").stat().st_size, 0)
        before = runtime._tree_snapshot(self.execution)
        events, status = acceptance._read_events(database, "TEST-PROGRAM")
        self.assertEqual(events, expected)
        self.assertEqual(status, "STABLE_FILESET_DIAGNOSTIC_COPY")
        self.assertEqual(before, runtime._tree_snapshot(self.execution))

    def test_packaged_audit_without_optional_dependencies_remains_unavailable_not_pass(self):
        _, path = self.artifact()
        path.write_text('{}')
        before = runtime._tree_snapshot(self.root)
        completed = subprocess.run([
            sys.executable, "-S", "-B", str(self.semantic_candidate / runtime.RUNTIME_ENTRYPOINT_REF),
            "audit-completion", "--candidate-root", str(self.semantic_candidate),
            "--node-id", "LAB_BOOTSTRAP", "--workpack-id", "LAB-PROTOCOL",
            "--execution-root", str(self.execution)], capture_output=True, text=True, timeout=60)
        self.assertEqual(completed.returncode, 1, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["artifact_observations"][0]["reason_code"], "JSON_SCHEMA_DEPENDENCY_UNAVAILABLE")
        self.assertFalse(result["workpack_accepted"])
        self.assertEqual(before, runtime._tree_snapshot(self.root))

    def test_changed_fileset_is_reported_instead_of_being_used_for_authorization(self):
        database = self.execution / ".harness-foundry/control.sqlite3"
        store = ControlEventStore(database)
        copyfile = acceptance.shutil.copyfile

        def concurrent_write(source, target):
            result = copyfile(source, target)
            store.append_batch("TEST-PROGRAM", [{"event_type": "TEST_ONLY", "payload": {}}],
                idempotency_key="TEST-CONCURRENT", created_at="2026-09-07T00:00:00Z")
            return result

        with patch.object(acceptance.shutil, "copyfile", side_effect=concurrent_write), self.assertRaises(runtime.RuntimeContractError):
            acceptance._read_events(database, "TEST-PROGRAM")


class WorkpackObservedEvidenceTests(unittest.TestCase):
    def test_only_the_real_observed_and_committed_native_attempt_is_reported(self):
        fixture = coding.CodingRuntimeTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        fixture.start()
        audit = lambda workpack="LAB-PROTOCOL": acceptance.audit_workpack_completion(
            fixture.candidate, fixture.local.execution, "LAB_BOOTSTRAP", workpack)
        self.assertEqual(audit()["command_observations"][0]["status"], "MISSING")
        adapter = prepare_coding_runtime(fixture.local.database, fixture.local.program, fixture.parent["authorization_id"],
                                        {"T-CODING": fixture.transition}, binding_verifier=verify_runtime_factory_binding)
        engine = GenericTransitionEngine(fixture.local.store, {CODING_CLASS: adapter}, binding_verifier=verify_runtime_factory_binding)
        with self.assertRaises(InjectedKernelCrash):
            engine.execute_transition(fixture.local.program, fixture.parent["authorization_id"], fixture.transition,
                {"approved": True}, created_at=datetime.now(timezone.utc).isoformat(), inject_crash_after_command=True)
        self.assertEqual(audit()["command_observations"][0]["status"], "MISSING")
        completed, result = fixture.local.cli(fixture.request())
        self.assertEqual(completed.returncode, 0, result)
        before = runtime._tree_snapshot(fixture.local.execution)
        observed = audit()
        self.assertEqual(observed["command_observations"][0]["status"], "OBSERVED")
        self.assertEqual(observed["command_observations"][0]["observations"][0]["evidence_scope"], "MODEL_TURN_ONLY")
        self.assertFalse(observed["workpack_accepted"])
        # LAB-CLI uses the same command ID, but is a different Workpack.
        self.assertEqual(audit("LAB-CLI")["command_observations"][0]["status"], "MISSING")
        self.assertEqual(before, runtime._tree_snapshot(fixture.local.execution))


if __name__ == "__main__":
    unittest.main()
