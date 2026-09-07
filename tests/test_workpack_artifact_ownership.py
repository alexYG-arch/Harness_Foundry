"""Acceptance-owned receipts remain required but cannot be written by coding."""

import json
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest
from copy import deepcopy

from harness_foundry_factory import workpack_runtime as runtime
from harness_foundry_factory.coding_protocol import plan_coding_command
from harness_foundry_factory.workpack_acceptance import plan_workpack_completion
from harness_foundry_factory.validator import validate_candidate, _acceptance_write_roots, _check_three_projects
from tests import test_normal_workpack_runtime as normal


def covered(ref, roots):
    return any(ref == root or ref.startswith(root.rstrip("/") + "/") for root in roots)


class WorkpackArtifactOwnershipTests(unittest.TestCase):
    target_overrides = normal.NormalWorkpackRuntimeTests.target_overrides
    setUpClass = classmethod(normal.NormalWorkpackRuntimeTests.setUpClass.__func__)
    tearDownClass = classmethod(normal.NormalWorkpackRuntimeTests.tearDownClass.__func__)

    def test_coding_cannot_write_its_own_future_acceptance_receipt(self):
        plan = plan_workpack_completion(self.semantic_candidate, "LAB_BOOTSTRAP", "LAB-PROTOCOL")
        coding = plan_coding_command(self.semantic_candidate, "LAB_BOOTSTRAP", "LAB-PROTOCOL", "LAB-CODEX-CODING")
        self.assertTrue(plan["artifacts"])
        for artifact in plan["artifacts"]:
            self.assertEqual(artifact["artifact_kind"], "WORKPACK_CONTROL_RESULT")
            self.assertFalse(covered(artifact["artifact_ref"], coding["task_input"]["native_effective_roots"]["allowed_write_roots"]))
            self.assertEqual(artifact.get("production_owner"), "WORKPACK_ACCEPTANCE_CONTROLLER")
            self.assertEqual(artifact.get("production_timing"), "AFTER_NATIVE_COMMANDS_AND_ORACLES")
            self.assertIn(artifact["artifact_ref"], plan["unit"]["workpack"]["required_artifact_refs"])
            self.assertTrue(covered(artifact["artifact_ref"], plan["unit"]["workpack"]["allowed_write_paths"]))
        self.assertEqual(plan["artifact_production_groups"]["acceptance_controller"], [a["artifact_id"] for a in plan["artifacts"]])
        self.assertEqual(plan["artifact_production_groups"]["task_executor"], [])
        self.assertFalse(plan["workpack_accepted"])

    def test_complete_artifact_sets_and_business_command_writes_are_preserved(self):
        structural_count = business_count = 0
        dag = json.loads((self.semantic_candidate / runtime.DAG_REF).read_text())
        for node in dag["nodes"]:
            if not (node.get("project_workpack_sequence") or node.get("workpack_id")):
                continue
            for unit in runtime.plan_workpack_node(self.semantic_candidate, node["node_id"])["units"]:
                if unit["task_bundle"] is None:
                    continue
                artifacts = [a for task in unit["task_bundle"]["task_contracts"] for a in task["artifact_obligations"]]
                self.assertEqual([a["artifact_ref"] for a in artifacts], unit["workpack"]["required_artifact_refs"])
                task_writes = [root for command in unit["commands"] for root in command["shared_artifact_write_roots"]]
                task_writes += [root for command in unit["commands"] for scope in command["job_artifact_write_scopes"]
                                for root in scope["allowed_write_roots"]]
                for artifact in artifacts:
                    control = artifact["artifact_kind"] == "WORKPACK_CONTROL_RESULT"
                    self.assertEqual(covered(artifact["artifact_ref"], task_writes), not control, artifact["artifact_id"])
                    structural_count += control
                    business_count += not control
        self.assertGreater(structural_count, 0)
        self.assertGreater(business_count, 0)

    def test_produced_ownership_passes_factory_and_standalone_projection(self):
        result = validate_candidate(self.semantic_candidate)
        self.assertEqual(result["status"], "PASS", result.get("findings"))
        standalone = runpy.run_path(str(self.semantic_candidate / "tools/self_check.py"))
        dag = json.loads((self.semantic_candidate / runtime.DAG_REF).read_text())
        self.assertEqual(standalone["check_project_workpack_write_projection"](self.semantic_candidate, dag), [])

    def test_both_oracles_reject_control_owner_or_timing_relabeling(self):
        unit = runtime.plan_workpack_node(self.semantic_candidate, "LAB_BOOTSTRAP")["units"][0]
        standalone = runpy.run_path(str(self.semantic_candidate / "tools/self_check.py"))
        for field, value in (("production_owner", "CODEX_CODING_AGENT"), ("production_timing", "BEFORE_CODING"),
                             ("artifact_kind", "BUSINESS_ARTIFACT")):
            bundle = deepcopy(unit["task_bundle"])
            bundle["task_contracts"][0]["artifact_obligations"][0][field] = value
            self.assertIsNone(_acceptance_write_roots(bundle))
            self.assertIsNone(standalone["acceptance_write_roots"](bundle))

    def test_both_oracles_reject_returning_controller_writes_to_coding(self):
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            root = Path(temporary) / "candidate-copy"
            shutil.copytree(self.semantic_candidate, root)
            project = root / "project_start_packages/external_lab"
            index = json.loads((project / "WORKPACK_INDEX.json").read_text())
            unit = index["workpacks"][0]
            command_path = project / unit["command_manifest_ref"]
            manifest = json.loads(command_path.read_text())
            command = manifest["commands"][0]
            controller_root = manifest["workpack_acceptance_write_roots"][0]
            command["allowed_write_roots"].append(controller_root)
            command["shared_artifact_write_roots"].append(controller_root)
            command["command_sha256"] = runtime.hash_without(command, "command_sha256")
            manifest["manifest_sha256"] = runtime.hash_without(manifest, "manifest_sha256")
            # Mutate only the disposable copy; original Candidate modes/bytes stay intact.
            command_path.chmod(0o644)
            command_path.write_text(json.dumps(manifest))
            unit["command_manifest_sha256"] = runtime.file_hash(command_path)
            index_path = project / "WORKPACK_INDEX.json"
            index_path.chmod(0o644)
            index_path.write_text(json.dumps(index))
            self.assertIn("PROJECT_WORKPACK_COMMAND_BINDING_INVALID", {f["code"] for f in _check_three_projects(root)})
            standalone = runpy.run_path(str(root / "tools/self_check.py"))
            dag = json.loads((root / runtime.DAG_REF).read_text())
            self.assertIn("PROJECT_WORKPACK_WRITE_ROOT_CONTRACT_INVALID", {
                f["code"] for f in standalone["check_project_workpack_write_projection"](root, dag)})
