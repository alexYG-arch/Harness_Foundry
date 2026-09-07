"""Full frozen-declaration checks, without target code, network or model calls."""

from copy import deepcopy
import hashlib
from types import SimpleNamespace
import unittest

from harness_foundry_factory import lab_protocol as api
from harness_foundry_factory.lab_protocol_contract_checks import contract_case_ids, verify_frozen_protocol_contract
from harness_foundry_factory.semantic_contracts import public_skill_job_interface


class LabProtocolContractChecksTests(unittest.TestCase):
    def setUp(self):
        self.renderer = {"source_id": "TEST-RENDERER", "repository_url": "https://github.com/Fixture/Renderer",
                         "commit_sha": hashlib.sha1(b"test-renderer").hexdigest(),
                         "tree_sha256": hashlib.sha256(b"test-renderer-tree").hexdigest(), "license_spdx": "MIT"}
        self.catalog = {}
        for atom, kind in (("A", "SOURCE_FREEZE_RECEIPT"), ("B", "TARGET_SKILL_EXECUTION_GATE_RECEIPT"),
                           ("C", "LOCAL_RENDER_RECEIPT"), ("D", "OTHER_KIND")):
            schema = {"type": "object", "required": ["nested"], "properties": {
                "repository_url": {"type": "string"}, "commit_sha": {"type": "string"},
                "git_tree_oid": {"type": "string"}, "tree_sha256": {"type": "string"},
                "exact_commit_sha": {"type": "string"}, "nested": {"type": "object", "minProperties": 2}},
                "x-invariants": ["PRESERVE"], "x-invariant-contracts": {"PRESERVE": {"scope": "complete"}}}
            if kind == "LOCAL_RENDER_RECEIPT":
                schema["properties"]["repository_url"] = {"const": self.renderer["repository_url"]}
            self.catalog[atom] = {"artifact_kind": kind, "schema": schema}
        self.interface = public_skill_job_interface({"target": {"artifact_schema_catalog": self.catalog}, "sources": [self.renderer]})
        self.registry = {"evaluators": {name: {"implementation_entrypoint": "test_only.module:" + name}
                                        for name in ("FIRST", "SECOND", "LAST")}}

    def check(self, implementation):
        return verify_frozen_protocol_contract(implementation, self.interface, self.registry, self.catalog)

    def wrapped(self, **changes):
        return SimpleNamespace(**{**{name: getattr(api, name) for name in (
            "specialize_artifact_schema", "load_evaluator_registry", "resolve_evaluator")}, **changes})

    def test_every_registry_and_schema_member_is_checked_without_mutating_inputs(self):
        before = deepcopy((self.interface, self.registry, self.catalog))
        result = self.check(api)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual([row["case_id"] for row in result["cases"]], contract_case_ids(self.registry, self.catalog))
        self.assertEqual(before, (self.interface, self.registry, self.catalog))
        self.assertFalse(result["workpack_accepted"])
        self.assertFalse(result["job_graph_executed"])

    def test_missing_nonfirst_registry_member_fails(self):
        def resolve(registry, key):
            return api.resolve_evaluator(registry, key) if key != "LAST" else {}
        result = self.check(self.wrapped(resolve_evaluator=resolve))
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(next(row["status"] for row in result["cases"] if row["case_id"] == "frozen-registry-resolve:LAST"), "FAIL")

    def test_schema_constraint_loss_and_renderer_content_conflation_fail(self):
        for change in ("constraint", "renderer", "mutation"):
            def specialize(template, job, kind, repositories):
                bound = api.specialize_artifact_schema(template, job, kind, repositories)
                if change == "constraint":
                    bound.pop("x-invariants")
                elif change == "renderer" and kind == "LOCAL_RENDER_RECEIPT":
                    bound["properties"]["repository_url"] = {"const": job["repository_url"]}
                elif change == "mutation":
                    template["unexpected"] = True
                return bound
            self.assertEqual(self.check(self.wrapped(specialize_artifact_schema=specialize))["status"], "FAIL", change)

    def test_omitted_or_extra_template_bindings_fail(self):
        original = deepcopy(self.interface["dynamic_specialization_contract"]["schema_template_bindings"])
        for bindings in (original[:-1], original + [original[0]]):
            self.interface["dynamic_specialization_contract"]["schema_template_bindings"] = bindings
            self.assertEqual(self.check(api)["status"], "FAIL")
