from hashlib import sha256
import json
from unittest import TestCase

from harness_foundry_factory.mutation_contracts import (
    canonical_recomputations, prepare_mutated_document, classify_mutation_result,
)
from harness_foundry_factory.semantic_contracts import _strengthen_artifact_schema, oracle_evaluator_registry
from harness_foundry_factory.validator import _oracle_registry_is_independently_consistent


class MutationCompositionTests(TestCase):
    def test_leaf_hash_mutation_can_preserve_derived_manifest_invariant(self):
        schema = _strengthen_artifact_schema("ASSET_PLAN", {"type": "object", "properties": {}})
        target = "/assets/0/asset_sha256"
        steps = canonical_recomputations(schema, target)
        self.assertEqual(steps, [{"algorithm": "CANONICAL_JSON_VALUE_HASH_V1",
                                 "source_ref": "/assets", "target_ref": "/asset_manifest_sha256"}])
        document = {"assets": [{"asset_sha256": "0" * 64}], "asset_manifest_sha256": "stale"}
        mutated = prepare_mutated_document(document, target, steps)
        independently_expected = sha256(json.dumps(mutated["assets"], sort_keys=True,
                                                   separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(mutated["asset_manifest_sha256"], independently_expected)
        self.assertNotEqual(mutated["assets"][0]["asset_sha256"], sha256(b"asset").hexdigest())
        self.assertEqual(document["asset_manifest_sha256"], "stale")

    def test_errors_or_collateral_failures_are_not_success(self):
        for status in ("TIMEOUT", "RUNNER_ERROR", "NOT_RUN"):
            self.assertEqual(classify_mutation_result("target", schema_passed=True,
                failed_invariants=["target"], execution_status=status), "INCONCLUSIVE")
        self.assertEqual(classify_mutation_result("target", schema_passed=True,
            failed_invariants=["target", "other"], execution_status="COMPLETED"),
            "NON_TARGET_INVARIANT_FAILURE")
        self.assertEqual(classify_mutation_result("target", schema_passed=True,
            failed_invariants=["target"], execution_status="COMPLETED"),
            "EXPECTED_INVARIANT_REJECTION")

    def test_recipe_cannot_repair_the_mutation_target(self):
        with self.assertRaises(ValueError):
            prepare_mutated_document({}, "/digest", [{"algorithm": "CANONICAL_JSON_VALUE_HASH_V1",
                "source_ref": "/assets", "target_ref": "/digest"}])

    def test_registry_emits_recomputation_and_independent_validator_rejects_removal(self):
        schema = _strengthen_artifact_schema("ASSET_PLAN", {"type": "object", "properties": {}})
        artifact = {"artifact_kind": "ASSET_PLAN", "schema": schema}
        registry = oracle_evaluator_registry({"ASSET_PLAN"}, [artifact])
        self.assertTrue(_oracle_registry_is_independently_consistent(registry, {"asset": artifact}))
        case = next(case for case in registry["invariant_negative_case_matrix"]
                    if case["invariant_id"] == "EVERY_MATERIALIZED_ASSET_REF_HASH_MATCHES_ASSET_SHA256")
        steps = case["mutation"]["derivation_recipe"]["derived_field_recomputations"]
        self.assertEqual(steps[0]["target_ref"], "/asset_manifest_sha256")
        case["mutation"]["derivation_recipe"]["derived_field_recomputations"] = []
        self.assertFalse(_oracle_registry_is_independently_consistent(registry, {"asset": artifact}))
