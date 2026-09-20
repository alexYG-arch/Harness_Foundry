"""Approved local process-stage wiring; temporary fixtures, not Harness acceptance.

The opt-in tests use the real public CLI and OS sandbox, without test adapters.
Their Parent records are explicit test authorizations, never production grants.
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import jsonschema

from harness_foundry_factory.compiler import _job_artifact_lease_contract
from harness_foundry_factory.control_kernel import (
    ControlKernelError, GenericTransitionEngine, InjectedKernelCrash,
    prepare_parent_authorization_challenge, rebuild_control_projections,
)
from harness_foundry_factory.local_runtime import (
    LOCAL_CLASS, LOCAL_MODE, bind_local_workpack_transition, prepare_local_runtime,
    validate_local_execution,
)
from harness_foundry_factory.store import ControlEventStore
from tests import test_runtime_advance_cli as support


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class LocalRuntimeFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.candidate = self.root / "candidate"
        self.execution = self.root / "execution"
        self.candidate.mkdir()
        self.execution.mkdir()
        self.database = self.execution / ".harness-foundry/control.sqlite3"
        self.program = "PROGRAM-TEST-LOCAL-STAGE"
        self.store = ControlEventStore(self.database)
        self.engine = GenericTransitionEngine(self.store, {})
        self.code = ("from pathlib import Path; import sys, json; "
                     "lease = json.loads(Path(sys.argv[2]).read_text()); assert lease['job_id'] == 'JOB-A'; "
                     "Path('output').write_text(Path(sys.argv[1]).read_text()); print('ACTUAL')")
        self.tools = {"harness-resource://runtime-tools/python": sys.executable}
        runtime_reads = [sys.prefix, sys.base_prefix, str(Path(sys._base_executable).parent),
                         *json.loads(os.environ.get("HFFACTORY_TEST_PYTHON_READ_ROOTS", "[]"))]
        self.tools.update({f"harness-resource://runtime-tools/lib-{index}": str(path)
                           for index, path in enumerate(runtime_reads)})
        self.native = {
            "command_id": "TEST-LOCAL-VERIFY", "executor_role": "LOCAL_PROCESS",
            "allowed_read_roots": ["harness-resource://candidate"], "allowed_write_roots": [],
            "job_artifact_lease_required": True,
            "job_artifact_lease_contract": _job_artifact_lease_contract(
                command_id="TEST-LOCAL-VERIFY", workpack_id="TEST-WORKPACK",
                read_scopes=[{"job_id": job, "allowed_read_roots": [f"harness-resource://execution/jobs/{job}/input"]}
                             for job in ("JOB-A", "JOB-B")],
                write_scopes=[{"job_id": job, "allowed_write_roots": [f"harness-resource://execution/jobs/{job}/output"]}
                              for job in ("JOB-A", "JOB-B")]),
        }
        for job in ("JOB-A", "JOB-B"):
            folder = self.execution / "jobs" / job / "input"
            folder.mkdir(parents=True)
            (folder / "value").write_text(job)
        self.parent = support.parent(self.program)
        self.parent.update(allowed_read_roots=["harness-resource://candidate", "harness-resource://execution/jobs",
                                               "harness-resource://execution/evidence/job_artifact_leases",
                                               "harness-resource://runtime-tools"],
                           allowed_write_roots=["harness-resource://execution/jobs",
                                                "harness-resource://execution/evidence/job_artifact_leases"],
                           command_classes=[LOCAL_CLASS])
        # A fixture receiver that cannot provide the required interface, unless
        # the operator explicitly opts into the actual installed sandbox tests.
        receiver = os.environ.get("HFFACTORY_TEST_CODEX_SANDBOX", "/usr/bin/true")
        self.parent["local_execution"] = {
            "mode": LOCAL_MODE, "candidate_root": str(self.candidate), "execution_root": str(self.execution),
            "control_db": str(self.database),
            "receiver": {"executable_abs": receiver, "executable_sha256": digest(receiver)},
            "runtime_resources": self.tools, "transitions": {"T-LOCAL": self.transition()},
        }

    def transition(self, *, job="JOB-A", code=None):
        return bind_local_workpack_transition(support.transition("T-LOCAL", "STATE"),
            native_command=self.native, project_id="TEST-PROJECT", workpack_id="TEST-WORKPACK",
            argv=[{"resource_ref": "harness-resource://runtime-tools/python"}, "-B", "-c", code or self.code,
                  {"resource_ref": f"harness-resource://execution/jobs/{job}/input/value"},
                  {"resource_ref": f"harness-resource://execution/evidence/job_artifact_leases/TEST-WORKPACK/TEST-LOCAL-VERIFY/{job}.lease.json"}],
            cwd_ref=f"harness-resource://execution/jobs/{job}/output", executable_sha256=digest(sys.executable),
            runtime_read_refs=list(self.tools), job_id=job, timeout_seconds=10)

    def approve(self):
        self.challenge = prepare_parent_authorization_challenge(self.parent, expected_bindings=support.bindings())
        self.engine.register_approved_parent_authorization(self.parent, self.challenge, {
            "decision": "APPROVE", "challenge_sha256": self.challenge["challenge_sha256"],
            "approved_by": {"type": "HUMAN_VIA_CODEX_CHAT", "chat_thread_id": "TEST-ONLY", "turn_id": "TEST-ONLY"},
            "approved_at": support.NOW}, created_at=support.NOW)

    def request(self):
        return {"adapter_mode": LOCAL_MODE, "program_id": self.program,
                "parent_authorization_id": self.parent["authorization_id"],
                "contracts": deepcopy(self.parent["local_execution"]["transitions"]),
                "inputs_by_transition": {"T-LOCAL": {"approved": True}}, "start_transition_id": "T-LOCAL",
                "max_transitions": 1,
                "expected_bindings": support.bindings(),
                "expected_control_state_sha256": self.engine.control_state_sha256(self.program),
                "environment_manifest": {"scope": "TEST_ONLY_LOCAL_STAGE"}, "artifact_manifest": {"artifacts": []}}

    def cli(self, request, *, command="advance-until-gate", database=None):
        path = self.root / "request.json"
        path.write_text(json.dumps(request))
        env = os.environ.copy()
        env.pop("HFFACTORY_ALLOW_TEST_ADAPTERS", None)
        env.update(PYTHONPATH=str(support.ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
        completed = subprocess.run([sys.executable, "-B", "-m", "tests.legacy_cli", command,
            "--request", str(path), "--control-db", str(database or self.database), "--json"],
            capture_output=True, text=True, env=env, timeout=45)
        self.assertTrue(completed.stdout, completed.stderr)
        return completed, json.loads(completed.stdout)

    def observations(self):
        return [event for event in self.store.list_events(self.program) if event["event_type"] == "COMMAND_RESULT_OBSERVED"]


class LocalRuntimeContractTests(LocalRuntimeFixture):
    def test_parent_challenge_discloses_plan_and_narrowed_job_reads(self):
        self.approve()
        self.assertEqual(self.challenge["local_execution"], self.parent["local_execution"])
        self.assertEqual(self.challenge["read_roots"], self.parent["allowed_read_roots"])
        transition = self.parent["local_execution"]["transitions"]["T-LOCAL"]
        self.assertIn("harness-resource://execution/jobs/JOB-A/input", transition["allowed_read_roots"])
        self.assertFalse(any("JOB-B" in root for root in transition["allowed_read_roots"] + transition["allowed_write_roots"]))
        self.assertEqual(transition["command_contract"]["local_invocation"]["native_command"], self.native)

    def test_request_cannot_select_unapproved_job_or_modify_command(self):
        self.approve()
        before = self.store.list_events(self.program)
        for replacement in (self.transition(job="JOB-B"), self.transition(code="print('REPLACED')")):
            with self.subTest(replacement=replacement["command_contract"]["local_invocation"]["job_id"]):
                request = self.request()
                request["contracts"]["T-LOCAL"] = replacement
                completed, result = self.cli(request)
                self.assertNotEqual(completed.returncode, 0, result)
                self.assertEqual(result["error"]["reason_code"], "LOCAL_RUNTIME_BINDING_INVALID")
        self.assertEqual(before, self.store.list_events(self.program))

    def test_no_parent_or_missing_database_never_creates_execution_root(self):
        absent = self.root / "absent/.harness-foundry/control.sqlite3"
        completed, result = self.cli(self.request(), database=absent)
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertFalse(absent.parent.exists())
        completed, result = self.cli(self.request())
        self.assertNotEqual(completed.returncode, 0, result)
        self.assertEqual(result["error"]["reason_code"], "PARENT_AUTHORIZATION_NOT_ACTIVE")

    def test_legacy_controller_and_test_only_request_fields_are_refused(self):
        self.approve()
        before = self.store.list_events(self.program)
        for field, value in (("created_at", support.NOW), ("test_adapter_results", {})):
            request = self.request()
            request[field] = value
            _, result = self.cli(request)
            self.assertEqual(result["error"]["reason_code"], "LOCAL_RUNTIME_REQUEST_INVALID")
        legacy = self.execution / ".harness-foundry/control/PROGRAM_CONTROL_EVENTS.jsonl"
        legacy.parent.mkdir()
        legacy.write_text("")
        _, result = self.cli(self.request())
        self.assertEqual(result["error"]["reason_code"], "LOCAL_LEGACY_CONTROLLER_PRESENT")
        self.assertEqual(before, self.store.list_events(self.program))

    def test_offline_binding_refuses_model_driver_and_cross_job_scopes(self):
        for native in ({**self.native, "command_id": "MB-CODEX-CODING"},
                       {**self.native, "executor_role": "BUILD_PROGRAM_DRIVER"},
                       {**self.native, "allowed_read_roots": ["harness-resource://execution/jobs/JOB-B"]}):
            with self.subTest(native=native["command_id"]), self.assertRaises(ControlKernelError):
                original, self.native = self.native, native
                try:
                    self.transition()
                finally:
                    self.native = original

    def test_native_lease_identity_and_runtime_path_traversal_are_rejected(self):
        parent = deepcopy(self.parent)
        invocation = parent["local_execution"]["transitions"]["T-LOCAL"]["command_contract"]["local_invocation"]
        invocation["workpack_id"] = "ANOTHER-WORKPACK"
        with self.assertRaises(ControlKernelError):
            validate_local_execution(parent)
        parent = deepcopy(self.parent)
        parent["local_execution"]["runtime_resources"]["harness-resource://runtime-tools/python"] = "/tmp/../bin/python"
        with self.assertRaises(ControlKernelError):
            validate_local_execution(parent)

    def test_tool_alias_cannot_open_another_job_or_controller_domain(self):
        self.parent["local_execution"]["runtime_resources"]["harness-resource://runtime-tools/python"] = str(self.execution / "jobs/JOB-B")
        self.approve()
        _, result = self.cli(self.request())
        self.assertEqual(result["status"], "STOPPED_AT_REAL_GATE", result)
        observation = self.observations()[0]["payload"]["result"]
        self.assertFalse(observation["process_result"]["workload_started"])
        self.assertIn("tool alias", observation["process_result"]["diagnostic"])
        self.assertFalse((self.execution / "jobs/JOB-A/output").exists())

    def test_executable_drift_is_observed_without_dispatch(self):
        executable = self.root / "python-fixture"
        executable.write_bytes(b"BEFORE")
        self.parent["local_execution"]["runtime_resources"]["harness-resource://runtime-tools/python"] = str(executable)
        self.parent["local_execution"]["transitions"]["T-LOCAL"]["command_contract"]["local_invocation"]["executable_sha256"] = digest(executable)
        self.approve()
        executable.write_bytes(b"AFTER")
        _, result = self.cli(self.request())
        self.assertEqual(result["status"], "STOPPED_AT_REAL_GATE", result)
        self.assertFalse(self.observations()[0]["payload"]["result"]["process_result"]["workload_started"])
        self.assertFalse((self.execution / "jobs/JOB-A/output").exists())

    def test_expiry_uses_real_clock_not_fixture_time(self):
        self.parent["expires_at"] = "2026-08-13T00:00:00Z"
        self.approve()
        _, result = self.cli(self.request())
        self.assertEqual(result["status"], "ERROR", result)
        self.assertIn("EXPIRED", result["error"]["reason_code"])
        self.assertEqual(self.observations(), [])


@unittest.skipUnless(os.environ.get("HFFACTORY_TEST_CODEX_SANDBOX"), "real local sandbox opt-in not configured")
class RealLocalRuntimeCliTests(LocalRuntimeFixture):
    def test_public_cli_runs_actual_process_and_consumes_native_selected_job_grant(self):
        self.approve()
        completed, result = self.cli(self.request())
        self.assertEqual(completed.returncode, 0, result)
        self.assertEqual(result["stop_reason"], "TRANSITION_PATH_COMPLETE", result)
        self.assertEqual(result["transition_receipts"][0]["status"], "COMMITTED", result)
        self.assertEqual((self.execution / "jobs/JOB-A/output/output").read_text(), "JOB-A")
        self.assertFalse((self.execution / "jobs/JOB-B/output").exists())
        observed = self.observations()[0]["payload"]["result"]
        self.assertEqual(observed["process_result"]["exit_code"], 0)
        self.assertEqual(observed["process_result"]["stdout"].strip(), "ACTUAL")
        lease = observed["job_lease"]
        jsonschema.validate(lease, self.native["job_artifact_lease_contract"]["receipt_schema"])
        path = self.execution / lease["lease_receipt_ref"].removeprefix("harness-resource://execution/")
        self.assertEqual(json.loads(path.read_text()), lease)
        grants = rebuild_control_projections(self.store.list_events(self.program))["grant_ledger"]["derived_grants"]
        self.assertEqual(len(grants), 1)
        grant = next(iter(grants.values()))
        self.assertEqual(grant["status"], "CONSUMED")
        self.assertEqual(grant["grant_id"], lease["lease_id"])
        self.assertEqual(grant["scope"]["allowed_read_roots"], self.parent["local_execution"]["transitions"]["T-LOCAL"]["allowed_read_roots"])
        self.assertEqual(self.store.verify_stream(self.program)["status"], "PASS")

    def test_actual_nonzero_is_not_success_or_redispatched(self):
        self.parent["local_execution"]["transitions"]["T-LOCAL"] = self.transition(code="import sys; print('PASS'); sys.exit(7)")
        self.approve()
        _, result = self.cli(self.request())
        self.assertEqual(result["status"], "STOPPED_AT_REAL_GATE", result)
        self.assertEqual(self.observations()[0]["payload"]["result"]["process_result"]["exit_code"], 7)
        self.cli(self.request())
        self.assertEqual(len(self.observations()), 1)

    def test_public_cli_recovers_observed_process_without_executing_again(self):
        self.parent["local_execution"]["transitions"]["T-LOCAL"] = self.transition(
            code="with open('effects', 'a') as f: f.write('APPLIED\\n')")
        self.approve()
        contract = self.parent["local_execution"]["transitions"]["T-LOCAL"]
        adapter = prepare_local_runtime(self.database, self.program, self.parent["authorization_id"], {"T-LOCAL": contract})
        engine = GenericTransitionEngine(adapter.store, {LOCAL_CLASS: adapter})
        with self.assertRaises(InjectedKernelCrash):
            engine.execute_transition(self.program, self.parent["authorization_id"], contract, {"approved": True},
                created_at=datetime.now(timezone.utc).isoformat(), inject_crash_after_command=True)
        self.assertEqual(self.observations()[0]["payload"]["result"]["process_result"]["exit_code"], 0)
        _, result = self.cli(self.request())
        self.assertEqual(result["stop_reason"], "TRANSITION_PATH_COMPLETE", result)
        self.assertEqual(result["transition_receipts"][0]["status"], "COMMITTED", result)
        self.assertEqual((self.execution / "jobs/JOB-A/output/effects").read_text(), "APPLIED\n")
        self.assertEqual(len(self.observations()), 1)

    def test_public_resume_uses_same_bound_local_plan(self):
        self.approve()
        request = self.request()
        checkpoint = self.engine.create_checkpoint(self.program, self.parent["authorization_id"],
            expected_bindings=support.bindings(), expected_control_state_sha256=request["expected_control_state_sha256"],
            environment_manifest=request["environment_manifest"], artifact_manifest=request["artifact_manifest"],
            resume_node="T-LOCAL", created_at=datetime.now(timezone.utc).isoformat())
        capsule = checkpoint["resume_capsule"]
        resume_request = {key: value for key, value in self.request().items()
                          if key in {"adapter_mode", "expected_bindings", "expected_control_state_sha256", "environment_manifest", "artifact_manifest"}}
        resume_request.update(resume_capsule=capsule, transition=request["contracts"]["T-LOCAL"],
                              inputs={"approved": True}, expected_fencing_token=capsule["fencing_token"])
        _, result = self.cli(resume_request, command="resume")
        self.assertEqual(result["status"], "RESUMED", result)
        self.assertEqual(result["transition_receipt"]["status"], "COMMITTED", result)
        self.assertEqual((self.execution / "jobs/JOB-A/output/output").read_text(), "JOB-A")
