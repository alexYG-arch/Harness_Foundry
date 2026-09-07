"""Ordinary project compilation and Workpack selection, not self-upgrade fixtures.

Temporary predecessor/process fixtures are not proof of Lab/Linkage builds or
Codex generation. The compiler and Candidate validators are not mocked.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

from harness_foundry_factory import workpack_runtime as runtime
from harness_foundry_factory.compiler import compile_start_package
from harness_foundry_factory.local_runtime import bind_local_workpack_transition
from harness_foundry_factory.models import content_sha256
from harness_foundry_factory.validator import validate_candidate, _check_controlled_workpack_runtime_executable_closure
from tests import test_default_startup_contracts as startup
from tests import test_workpack_runtime as process_support
from tests import test_semantic_production_contracts as semantic_support
from tests import test_runtime_advance_cli as control_support
from tests.permissions import make_path_writable, make_tree_writable


class NormalWorkpackRuntimeTests(unittest.TestCase):
    target_overrides = {"start_package_assurance_profile": "LOCAL_EXEC_UNTRUSTED_INPUT"}

    @classmethod
    def setUpClass(cls):
        startup.NormalLocalStartupTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        startup.DefaultStartupContractTests.tearDownClass.__func__(cls)

    _write_json = staticmethod(process_support.ControlledWorkpackRuntimeTests._write_json)
    _real_process_hydration = process_support.ControlledWorkpackRuntimeTests._real_process_hydration
    _commit_shared_predecessor = startup.NormalLocalStartupTests._commit_shared_predecessor
    _registration_inputs = startup.NormalLocalStartupTests._registration_inputs
    _commit_registration = startup.NormalLocalStartupTests._commit_registration
    _verification_inputs = startup.NormalLocalStartupTests._verification_inputs

    def _execution_root(self, name):
        # This creates a protocol fixture, not a claim that Lab/Linkage ran.
        execution = process_support.ControlledWorkpackRuntimeTests._execution_root(self, name)
        plan = runtime.plan_workpack_node(self.candidate, runtime.NODE_ID)
        predecessor_id = plan["required_predecessor_nodes"][0]
        state = json.loads((execution / runtime.CONTROL_STATE_REF).read_text())
        state.update(program_id=plan["program_id"], last_completed_node=predecessor_id)
        state["state_sha256"] = runtime.hash_without(state, "state_sha256")
        self._write_json(execution / runtime.CONTROL_STATE_REF, state)
        predecessor = json.loads((execution / runtime.PREDECESSOR_RESULT_REF).read_text())
        predecessor.update(node_id=predecessor_id, evidence_scope="TEST_ONLY_PREDECESSOR_FIXTURE")
        self._write_json(execution / f"evidence/engineering_dag/{predecessor_id}/result.json", predecessor)
        return execution

    def _overlay(self, execution):
        overlay = process_support.ControlledWorkpackRuntimeTests._overlay(self, execution)
        overlay["workpack_id"] = runtime.plan_workpack_node(self.candidate, runtime.NODE_ID)["units"][0]["workpack_id"]
        return overlay

    @staticmethod
    def _authorization(hydration):
        authorization = process_support.ControlledWorkpackRuntimeTests._authorization(hydration)
        authorization["workpack_id"] = hydration["workpack_id"]
        return authorization

    def test_normal_candidate_packages_its_own_materialization_provider(self):
        self.assertTrue((self.candidate / runtime.RUNTIME_ENTRYPOINT_REF).is_file())
        self.assertEqual(validate_candidate(self.candidate)["status"], "PASS")
        contract = json.loads((self.candidate / runtime.RUNTIME_CONTRACT_REF).read_text())
        self.assertEqual(contract["contract_id"], "LOCAL_CONTROLLED_WORKPACK_RUNTIME_V1")
        self.assertNotEqual(contract["workpack_id"], runtime.WORKPACK_ID)
        self.assertNotIn("profile_origin_requirement_epoch", contract)

    def test_ordered_lab_plan_is_candidate_derived_and_read_only(self):
        before = runtime.candidate_identity(self.candidate)
        plan = runtime.plan_workpack_node(self.candidate, "LAB_BOOTSTRAP")
        self.assertEqual([unit["workpack_id"] for unit in plan["units"]],
                         ["LAB-PROTOCOL", "LAB-CLI", "LAB-FIXTURES"])
        self.assertEqual(plan["required_predecessor_nodes"], ["PROGRAM_DRIVER_RUNTIME_VERIFIED"])
        self.assertTrue(all(unit["command_manifest_ref"].startswith("project_start_packages/external_lab/")
                            for unit in plan["units"]))
        self.assertFalse(plan["execution_authorized"])
        self.assertFalse(plan["writes_performed"])
        self.assertEqual(before, runtime.candidate_identity(self.candidate))

    def test_native_local_command_keeps_repository_reads_through_final_projection(self):
        # Previously this final native command had no reads at all. Checking
        # only the initial producer helper missed the later refresh overwrite.
        plan = runtime.plan_workpack_node(self.candidate, "LAB_SELF_CONFORMANCE_PASS")
        unit = plan["units"][0]
        native = next(command for command in unit["commands"] if command["command_id"] == "LAB-SELFTEST")
        cwd = "harness-resource://execution/project_start_packages/external_lab/repository"
        self.assertIn(cwd, native["allowed_read_roots"])
        self.assertIn("harness-resource://candidate", native["allowed_read_roots"])
        transition = bind_local_workpack_transition(control_support.transition("T-LOCAL", "STATE"),
            native_command=native, project_id=unit["project_id"], workpack_id=unit["workpack_id"],
            argv=[{"resource_ref": "harness-resource://runtime-tools/python"}, "-B", "--version"],
            cwd_ref=cwd, executable_sha256=runtime.file_hash(Path(sys.executable)),
            runtime_read_refs=["harness-resource://runtime-tools/python"])
        self.assertIn(cwd, transition["allowed_read_roots"])
        self.assertFalse(any("/jobs/" in root for root in transition["allowed_read_roots"]))
        self.assertEqual(transition["command_contract"]["local_invocation"]["native_command"], native)

    def test_independent_validator_rejects_removed_native_repository_reads(self):
        candidate = self.root / "removed-native-reads"
        shutil.copytree(self.candidate, candidate)
        ref = "project_start_packages/external_lab/commands/LAB-SELFTEST.commands.json"
        document = json.loads((candidate / ref).read_text())
        for command in document["commands"]:
            command["allowed_read_roots"] = []
            command["command_sha256"] = runtime.hash_without(command, "command_sha256")
        document["manifest_sha256"] = runtime.hash_without(document, "manifest_sha256")
        self._write_json(candidate / ref, document)
        index_ref = "project_start_packages/external_lab/WORKPACK_INDEX.json"
        index = json.loads((candidate / index_ref).read_text())
        item = next(item for item in index["workpacks"] if item["workpack_id"] == "LAB-SELFTEST")
        item["command_manifest_sha256"] = runtime.file_hash(candidate / ref)
        self._write_json(candidate / index_ref, index)
        inventory = json.loads((candidate / runtime.PORTABLE_MANIFEST_REF).read_text())
        for updated in (ref, index_ref):
            inventory["files"][updated] = runtime.file_hash(candidate / updated)
        self._write_json(candidate / runtime.PORTABLE_MANIFEST_REF, inventory)
        report = validate_candidate(candidate)
        self.assertIn("PROJECT_WORKPACK_COMMAND_BINDING_INVALID", {item["code"] for item in report["blocking_findings"]})

    def test_candidate_packages_local_runtime_import_closure(self):
        for name in ("local_runtime.py", "local_process.py"):
            ref = f"tools/harness_foundry_runtime/{name}"
            self.assertEqual((self.candidate / ref).read_bytes(),
                             (startup.ROOT / "src/harness_foundry_factory" / name).read_bytes())
        code = "from harness_foundry_runtime.local_runtime import LOCAL_MODE; print(LOCAL_MODE)"
        env = dict(os.environ, PYTHONPATH=str(self.candidate / "tools"), PYTHONDONTWRITEBYTECODE="1")
        completed = subprocess.run([sys.executable, "-B", "-c", code], cwd=self.root,
                                   capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "LOCAL_OFFLINE_PROCESSES")

    def test_every_workpack_bearing_engineering_node_preserves_its_native_contracts(self):
        dag = json.loads((self.candidate / runtime.DAG_REF).read_text())
        observed = []
        for node in dag["nodes"]:
            ids = node.get("project_workpack_sequence") or ([node["workpack_id"]] if node.get("workpack_id") else [])
            if not ids:
                continue
            with self.subTest(node=node["node_id"]):
                plan = runtime.plan_workpack_node(self.candidate, node["node_id"])
                self.assertEqual([unit["workpack_id"] for unit in plan["units"]], ids)
                observed.extend(ids)
                for unit in plan["units"]:
                    source = json.loads((self.candidate / unit["command_manifest_ref"]).read_text())
                    self.assertEqual(unit["command_manifest"], source)
                    by_id = {command["command_id"]: command for command in source["commands"]}
                    self.assertEqual(unit["commands"], [by_id[key] for key in unit["workpack"]["command_execution_order"]])
                    if unit["task_bundle_ref"]:
                        self.assertEqual(unit["task_bundle"], json.loads((self.candidate / unit["task_bundle_ref"]).read_text()))
        self.assertIn("LAB-PROTOCOL", observed)
        self.assertIn("LINK-PROTOCOL", observed)
        self.assertIn("MB-P3", observed)

    def test_packaged_plan_cli_is_read_only(self):
        candidate = self.root / "writable-plan-copy"
        shutil.copytree(self.candidate, candidate)
        make_tree_writable(candidate)
        environment = os.environ.copy()
        environment.pop("PYTHONDONTWRITEBYTECODE", None)
        before = runtime._tree_snapshot(self.root)
        completed = subprocess.run([
            sys.executable, str(candidate / runtime.RUNTIME_ENTRYPOINT_REF),
            "plan", "--candidate-root", str(candidate), "--node-id", "LINKAGE_BOOTSTRAP",
        ], capture_output=True, text=True, check=False, timeout=60, env=environment)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual([unit["workpack_id"] for unit in json.loads(completed.stdout)["units"]], ["LINK-PROTOCOL", "LINK-CLI"])
        self.assertEqual(before, runtime._tree_snapshot(self.root))

    def test_real_three_action_startup_cannot_skip_lab_and_linkage(self):
        execution, command, authorization = self._verification_inputs("cannot-skip-lab")
        self.verification.execute_action(self.candidate, execution, command, authorization)
        before = runtime._tree_snapshot(execution)
        with self.assertRaises(runtime.RuntimeContractError):
            runtime.hydrate_workpack_runtime(self.candidate, execution, self._overlay(execution), verify_cli_schema=False)
        self.assertEqual(before, runtime._tree_snapshot(execution))
        self.assertFalse((execution / runtime.REPOSITORY_REF).exists())

    def test_normal_materialization_executes_actual_fixture_process_for_declared_workpack(self):
        execution, _executable, hydration, authorization = self._real_process_hydration("normal-process")
        self.assertNotEqual(hydration["workpack_id"], runtime.WORKPACK_ID)
        result = runtime.execute_hydrated_workpack(self.candidate, execution, hydration, authorization)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["workpack_id"], hydration["workpack_id"])
        self.assertEqual([item["exit_code"] for item in result["command_results"]], [0, 0])
        self.assertFalse(result["successor_started"])
        self.assertEqual(result["validation_scope"], "STRUCTURAL_PACKAGE_CONTRACT_ONLY")

    def test_independent_validator_requires_normal_provider(self):
        missing = self.root / "missing-normal-provider"
        shutil.copytree(self.candidate, missing)
        path = missing / runtime.PROVIDER_IMPLEMENTATION_REF
        make_path_writable(path.parent)
        path.unlink()
        findings = _check_controlled_workpack_runtime_executable_closure(missing)
        self.assertIn("CONTROLLED_WORKPACK_RUNTIME_ARTIFACT_MISSING", {item["code"] for item in findings})

    def test_plan_rejects_index_identity_drift_even_when_file_inventory_is_current(self):
        drifted = self.root / "cross-project-workpack"
        shutil.copytree(self.candidate, drifted)
        ref = "project_start_packages/external_lab/WORKPACK_INDEX.json"
        index = json.loads((drifted / ref).read_text())
        index["project_id"] = "WRONG_PROJECT"
        self._write_json(drifted / ref, index)
        inventory = json.loads((drifted / runtime.PORTABLE_MANIFEST_REF).read_text())
        inventory["files"][ref] = runtime.file_hash(drifted / ref)
        self._write_json(drifted / runtime.PORTABLE_MANIFEST_REF, inventory)
        with self.assertRaises(runtime.RuntimeContractError) as caught:
            runtime.plan_workpack_node(drifted, "LAB_BOOTSTRAP")
        self.assertEqual(caught.exception.code, "WORKPACK_PLAN_INVALID")

    def test_another_project_at_later_requirement_epoch_does_not_become_self_upgrade(self):
        candidate = self.root / "another-project"
        ir = json.loads((startup.ROOT / "tests/fixtures/harness_requirement_ir.json").read_text())
        ir["program_id"] = "PROGRAM-ANOTHER-LOCAL-PROJECT"
        ir["target"].update(id="ANOTHER-LOCAL-PROJECT", output_root=str(candidate),
                            portability_mode="LOGICAL_RESOURCE_URI", **self.target_overrides)
        provenance = {"requirement_epoch": 73, "requirement_ir_sha256": content_sha256(ir)}
        compile_start_package(
            ir, spec_root=startup.ROOT.parent / "Harness_Foundry_v2_8_Start_Package",
            staging_root=self.root / "another-staging", candidate_root=candidate,
            created_at="2026-09-07T00:00:00Z", active_requirement_epoch=73,
            authority_provenance=provenance,
        )
        contract = json.loads((candidate / runtime.RUNTIME_CONTRACT_REF).read_text())
        self.assertEqual(contract["active_requirement_epoch"], 73)
        self.assertEqual(contract["workpack_id"], "WP-ANOTHER-LOCAL-PROJECT-G0-001")
        self.assertEqual(contract["contract_id"], "LOCAL_CONTROLLED_WORKPACK_RUNTIME_V1")
        report = validate_candidate(candidate, authoritative_requirement_ir=ir, authority_provenance=provenance)
        self.assertEqual(report["status"], "PASS", report["blocking_findings"])

    def test_native_task_and_runtime_binding_drift_are_rejected(self):
        semantic = self.root / "semantic-binding-input"
        ir = semantic_support.semantic_ir(semantic, self.root / "semantic-planned-execution")
        ir["target"].update(self.target_overrides)
        compile_start_package(
            ir, spec_root=startup.ROOT.parent / "Harness_Foundry_v2_8_Start_Package",
            staging_root=self.root / "semantic-staging", candidate_root=semantic,
            created_at="2026-09-07T00:00:00Z",
        )
        plan = runtime.plan_workpack_node(semantic, "LAB_BOOTSTRAP")
        for unit in plan["units"]:
            self.assertIsNotNone(unit["task_bundle"])
            self.assertEqual(unit["task_bundle"], json.loads((semantic / unit["task_bundle_ref"]).read_text()))
        for label, ref, field, code in (
            ("task", "project_start_packages/external_lab/task_bundles/LAB-PROTOCOL.task_bundle.json",
             "workpack_id", "WORKPACK_PLAN_INVALID"),
            ("runtime", runtime.RUNTIME_CONTRACT_REF, "workpack_id", "WORKPACK_RUNTIME_SOURCE_STATE_INVALID"),
        ):
            with self.subTest(binding=label):
                drifted = self.root / f"wrong-{label}-binding"
                shutil.copytree(semantic, drifted)
                document = json.loads((drifted / ref).read_text())
                document[field] = "ANOTHER-WORKPACK"
                if "contract_sha256" in document:
                    document["contract_sha256"] = runtime.hash_without(document, "contract_sha256")
                self._write_json(drifted / ref, document)
                inventory = json.loads((drifted / runtime.PORTABLE_MANIFEST_REF).read_text())
                inventory["files"][ref] = runtime.file_hash(drifted / ref)
                self._write_json(drifted / runtime.PORTABLE_MANIFEST_REF, inventory)
                with self.assertRaises(runtime.RuntimeContractError) as caught:
                    if label == "task":
                        runtime.plan_workpack_node(drifted, "LAB_BOOTSTRAP")
                    else:
                        runtime._load_candidate_contracts(drifted)
                self.assertEqual(caught.exception.code, code)
