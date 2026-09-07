"""Actual protocol behavior and normal produced support; no target model run."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest

from jsonschema import Draft202012Validator, SchemaError

from harness_foundry_factory import lab_protocol as protocol
from harness_foundry_factory.lab_protocol_checks import verify_protocol_primitives
from harness_foundry_factory.semantic_contracts import public_skill_job_interface
from harness_foundry_factory.validator import _public_skill_job_interface_is_valid, _lab_completion_scope_findings
from harness_foundry_factory import workpack_runtime as runtime
from tests import test_normal_workpack_runtime as normal
from tests import test_semantic_production_contracts as semantic


class LabProtocolTests(unittest.TestCase):
    def setUp(self):
        self.interface = public_skill_job_interface({})
        self.schema = self.interface["job_request_schema"]

    def test_actual_implementation_passes_independently_defined_behavior_probes(self):
        result = verify_protocol_primitives(protocol, self.schema)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(len(result["cases"]), 28)
        self.assertEqual(len({row["case_id"] for row in result["cases"]}), 28)
        self.assertFalse(result["workpack_accepted"])

    def test_each_stubbed_api_fails_behavior_not_a_self_report_check(self):
        for method in ("validate_instance", "load_evaluator_registry", "resolve_evaluator", "require_operator",
                       "resolve_evidence_bytes", "normalize_skill_url", "derive_job_id", "specialize_artifact_schema"):
            with self.subTest(method=method):
                api = SimpleNamespace(**{name: getattr(protocol, name) for name in dir(protocol) if not name.startswith("_")})
                setattr(api, method, lambda *args: "PASS")
                result = verify_protocol_primitives(api, self.schema)
                self.assertEqual(result["status"], "FAIL")
                self.assertTrue(any(row["status"] == "FAIL" for row in result["cases"]))

    def test_producer_public_request_schema_really_loads_and_old_fragment_id_fails(self):
        Draft202012Validator.check_schema(self.schema)
        self.assertTrue(_public_skill_job_interface_is_valid(self.interface, {}))
        self.assertTrue(protocol.validate_instance(self.schema, self.interface["metamorphic_acceptance_vector"]["input"]))
        old = deepcopy(self.interface)
        old["job_request_schema"]["$id"] = "harness-resource://candidate/validation/PUBLIC_SKILL_JOB_INTERFACE.json#/job_request_schema"
        with self.assertRaises(SchemaError):
            Draft202012Validator.check_schema(old["job_request_schema"])
        self.assertFalse(_public_skill_job_interface_is_valid(old, {}))

    def test_job_identity_tracks_immutable_fields_and_ignores_mutable_revision(self):
        identity = {"request_id": "TEST", "normalized_skill_url": "https://github.com/Example/Repo",
                    "skill_entrypoint_ref": "SKILL.md", "resolved_commit_sha": hashlib.sha1(b"commit").hexdigest(),
                    "resolved_git_tree_oid": hashlib.sha1(b"tree").hexdigest(),
                    "resolved_tree_sha256": hashlib.sha256(b"tree-bytes").hexdigest(),
                    "resolved_skill_entrypoint_sha256": hashlib.sha256(b"skill-bytes").hexdigest()}
        original = protocol.derive_job_id(identity)
        self.assertEqual(protocol.derive_job_id({**identity, "requested_revision": "branch"}), original)
        for key in identity:
            changed = dict(identity)
            if key == "normalized_skill_url":
                changed[key] += "-Other"
            elif key == "skill_entrypoint_ref":
                changed[key] = "nested/SKILL.md"
            elif key.endswith("sha") or key.endswith("oid"):
                changed[key] = hashlib.sha1(key.encode()).hexdigest()
            elif key.endswith("sha256"):
                changed[key] = hashlib.sha256(key.encode()).hexdigest()
            else:
                changed[key] += "-other"
            self.assertNotEqual(protocol.derive_job_id(changed), original, key)

    def test_registry_lookup_does_not_import_entrypoint_or_modify_frozen_declaration(self):
        registry = {"evaluators": {"E": {"implementation_entrypoint": "not_installed.module:never_imported"}}}
        loaded = protocol.load_evaluator_registry(registry)
        loaded["E"]["implementation_entrypoint"] = "changed"
        self.assertEqual(protocol.resolve_evaluator(registry, "E"), registry["evaluators"]["E"])
        with self.assertRaises(protocol.ProtocolError) as missing:
            protocol.resolve_evidence_bytes("missing", {"exists": b"bytes"})
        self.assertEqual(missing.exception.code, "EVIDENCE_REF_UNAVAILABLE")

    def test_schema_specialization_preserves_nested_contract_and_execution_gate_identity(self):
        schema = {"type": "object", "properties": {"exact_commit_sha": {"type": "string"},
                  "nested": {"type": "object", "properties": {"count": {"minimum": 3}}}},
                  "x-invariants": ["KEEP"], "x-invariant-contracts": {"KEEP": {"algorithm": "EQUALS"}}}
        before = deepcopy(schema)
        job = {"job_id": "TEST-JOB", "source_id": "TEST-SOURCE", "commit_sha": hashlib.sha1(b"TEST").hexdigest()}
        bound = protocol.specialize_artifact_schema(schema, job, "TARGET_SKILL_EXECUTION_GATE_RECEIPT", [])
        self.assertEqual(bound["properties"]["target_skill_id"], {"const": "TEST-SOURCE"})
        self.assertEqual(bound["properties"]["exact_commit_sha"], {"const": job["commit_sha"]})
        self.assertEqual(bound["x-invariant-contracts"], schema["x-invariant-contracts"])
        bound["properties"]["nested"]["properties"]["count"]["minimum"] = 9
        self.assertEqual(schema, before)

    def test_schema_dependencies_stay_optional_and_are_not_auto_installed(self):
        code = ("from harness_foundry_factory import lab_protocol as p; "
                "print(p.normalize_skill_url('https://github.com/Example/Repo.git'))\n"
                "try: p.validate_instance({}, {})\n"
                "except p.ProtocolError as e: print(e.code)\n")
        completed = subprocess.run([sys.executable, "-S", "-B", "-c", code], capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}, timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.splitlines(), ["https://github.com/Example/Repo", "SCHEMA_DEPENDENCY_UNAVAILABLE"])

    def test_semantic_compatibility_materializes_declared_support_without_local_workpack_runtime(self):
        fixture = semantic.SemanticProductionContractTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.compile()
        support = fixture.candidate / "tools/harness_foundry_runtime"
        self.assertEqual({path.name for path in support.glob("*.py")},
                         {"__init__.py", "lab_protocol.py", "lab_protocol_checks.py"})
        self.assertFalse(fixture.execution.exists())


class ProducedLabProtocolTests(unittest.TestCase):
    target_overrides = normal.NormalWorkpackRuntimeTests.target_overrides
    setUpClass = classmethod(normal.NormalWorkpackRuntimeTests.setUpClass.__func__)
    tearDownClass = classmethod(normal.NormalWorkpackRuntimeTests.tearDownClass.__func__)

    def bundle(self, workpack):
        return json.loads((self.semantic_candidate / f"project_start_packages/external_lab/task_bundles/{workpack}.task_bundle.json").read_text())

    def test_phase_ownership_preserves_shared_context_without_requiring_later_workpack_completion(self):
        contexts = []
        for workpack in ("LAB-PROTOCOL", "LAB-CLI", "LAB-FIXTURES", "LAB-CERTIFICATION"):
            bundle = self.bundle(workpack)
            contract = bundle["lab_case_execution_contract"]
            self.assertEqual(_lab_completion_scope_findings(bundle), [])
            scope = contract["completion_scope"]
            self.assertEqual(scope["workpack_id"], workpack)
            self.assertEqual(len(scope["owned_obligation_refs"]), len(contract["implementation_obligations"]))
            contexts.append({key: contract[key] for key in scope["shared_reference_fields"]})
        self.assertTrue(all(value == contexts[0] for value in contexts))
        self.assertEqual(len(contexts[0]["required_subcommands"]), 7)

    def test_all_emitted_validation_schemas_load_under_the_actual_2020_12_metaschema(self):
        schemas = sorted((self.semantic_candidate / "validation/schemas").glob("*.json"))
        self.assertTrue(schemas)
        for path in schemas:
            with self.subTest(schema=path.name):
                Draft202012Validator.check_schema(json.loads(path.read_text()))

    def test_independent_phase_validator_rejects_wrong_owner_and_dropped_obligation(self):
        for mutation in ("owner", "obligation", "context"):
            bundle = self.bundle("LAB-PROTOCOL")
            scope = bundle["lab_case_execution_contract"]["completion_scope"]
            if mutation == "owner":
                scope["workpack_id"] = "LAB-CLI"
            elif mutation == "obligation":
                scope["owned_obligation_refs"].pop()
            else:
                scope["shared_reference_fields"].append("implementation_obligations")
            self.assertEqual(_lab_completion_scope_findings(bundle)[0]["code"], "LAB_COMPLETION_PHASE_SCOPE_INVALID")

    def test_packaged_protocol_support_runs_actual_behavior_without_factory_imports_or_execution_root(self):
        contract = self.bundle("LAB-PROTOCOL")["lab_case_execution_contract"]["protocol_implementation_support"]
        for key in ("library_ref", "checks_ref"):
            self.assertTrue((self.semantic_candidate / contract[key].removeprefix("harness-resource://candidate/")).is_file())
        before = runtime._tree_snapshot(self.root)
        code = ("import json, sys; from pathlib import Path; from harness_foundry_runtime import lab_protocol as p; "
                "from harness_foundry_runtime.lab_protocol_checks import verify_protocol_primitives; "
                "schema=json.loads(Path(sys.argv[1]).read_text())['job_request_schema']; "
                "result=verify_protocol_primitives(p, schema); assert 'harness_foundry_factory' not in sys.modules; "
                "print(json.dumps(result)); sys.exit(0 if result['status']=='PASS' else 1)")
        completed = subprocess.run([sys.executable, "-B", "-c", code,
            str(self.semantic_candidate / "validation/PUBLIC_SKILL_JOB_INTERFACE.json")], cwd=self.root,
            env={**os.environ, "PYTHONPATH": str(self.semantic_candidate / "tools"), "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertFalse(json.loads(completed.stdout)["workpack_accepted"])
        self.assertEqual(before, runtime._tree_snapshot(self.root))


if __name__ == "__main__":
    unittest.main()
