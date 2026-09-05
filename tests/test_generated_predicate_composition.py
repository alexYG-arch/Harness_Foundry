"""Behavioral regression: execute Producer output, not a hand-written lookalike."""

from copy import deepcopy
from hashlib import sha256
import unittest

from harness_foundry_factory.invariant_contracts import (
    evaluate_predicate_ast_v1,
    validate_invariant_contract_v1,
)
from harness_foundry_factory.semantic_contracts import _strengthen_artifact_schema


def generated_schema(kind):
    return _strengthen_artifact_schema(kind, {"type": "object", "properties": {}})


class GeneratedPredicateCompositionTests(unittest.TestCase):
    def setUp(self):
        self.schema = generated_schema("ASSET_PLAN")
        self.contracts = self.schema["x-invariant-contracts"]

    def test_generated_asset_predicate_detects_each_member(self):
        contract = self.contracts["EVERY_MATERIALIZED_ASSET_REF_HASH_MATCHES_ASSET_SHA256"]
        for bad_index in (None, 0, 1, 2):
            with self.subTest(bad_index=bad_index):
                document = {"assets": [
                    {"asset_ref": "bytes://asset", "asset_sha256": sha256(b"asset").hexdigest(),
                     "materialization_state": "SOURCE_VERIFIED"}
                    for _ in range(3)
                ]}
                if bad_index is not None:
                    document["assets"][bad_index]["asset_sha256"] = "0" * 64
                result = evaluate_predicate_ast_v1(contract, document, resolver=lambda _: b"asset")
                self.assertEqual(result["passed"], bad_index is None)
                self.assertEqual(result["failed_subjects"], [] if bad_index is None else
                                 [f"/assets/{bad_index}/asset_sha256"])

    def test_generated_ast_is_the_actual_kernel_input(self):
        for contract in self.contracts.values():
            if contract["evaluation_contract_kind"] == "TYPED_KERNEL_V1":
                with self.subTest(algorithm=contract["algorithm"]):
                    self.assertEqual(validate_invariant_contract_v1(contract["predicate_ast"]), [])

    def test_source_assets_do_not_require_imagegen_or_local_receipts(self):
        document = {"assets": [{
            "materialization_state": "SOURCE_VERIFIED",
            "generation_receipt_ref": None, "generation_receipt_sha256": None,
            "generation_authorization_ref": None, "local_build_recipe": None,
        }]}
        for name in (
            "IMAGEGEN_RECEIPT_HASH_MATCHES_REFERENCED_BYTES_WHEN_MATERIALIZED",
            "CODEX_IMAGEGEN_MATERIALIZATION_REQUIRES_SEPARATE_CURRENT_AUTHORIZATION",
            "LOCAL_DETERMINISTIC_ASSET_RECIPE_AND_OUTPUT_ARE_HASH_BOUND",
        ):
            with self.subTest(invariant=name):
                result = evaluate_predicate_ast_v1(self.contracts[name], document)
                self.assertTrue(result["passed"], result)
                self.assertTrue(result["skipped"], result)

    def test_mixed_routes_still_check_applicable_nonfirst_member(self):
        contract = self.contracts["IMAGEGEN_RECEIPT_HASH_MATCHES_REFERENCED_BYTES_WHEN_MATERIALIZED"]
        document = {"assets": [
            {"materialization_state": "SOURCE_VERIFIED", "generation_receipt_ref": None,
             "generation_receipt_sha256": None},
            {"materialization_state": "CODEX_IMAGEGEN_AUTHORIZED_MATERIALIZED",
             "generation_receipt_ref": "bytes://receipt", "generation_receipt_sha256": "0" * 64},
        ]}
        result = evaluate_predicate_ast_v1(contract, document, resolver=lambda _: b"receipt")
        self.assertFalse(result["passed"])
        self.assertEqual(result["evaluated_subject_count"], 1)
        self.assertEqual(result["failed_subjects"], ["/assets/1"])

    def test_nested_motion_predicate_pairs_same_object(self):
        contract = generated_schema("OBJECT_MOTION_IR")["x-invariant-contracts"][
            "ENTER_TIME_LESS_THAN_OR_EQUAL_TO_HOLD_START"]
        document = {"shots": [{"objects": [
            {"enter_time": 0, "hold_interval": {"start_seconds": 1}},
            {"enter_time": 2, "hold_interval": {"start_seconds": 3}},
        ]} for _ in range(2)]}
        self.assertTrue(evaluate_predicate_ast_v1(contract, document)["passed"])
        document["shots"][1]["objects"][1]["enter_time"] = 4
        result = evaluate_predicate_ast_v1(contract, document)
        self.assertFalse(result["passed"])
        self.assertEqual(result["failed_subjects"], ["/shots/1/objects/1/enter_time"])

    def test_known_bad_fixed_seed_contract_is_rejected(self):
        contract = deepcopy(self.contracts["EVERY_MATERIALIZED_ASSET_REF_HASH_MATCHES_ASSET_SHA256"])
        contract["operand_refs"] = ["/assets/0/asset_sha256", "/assets/0/asset_ref"]
        self.assertIn("INVARIANT_SUBJECT_OPERAND_UNBOUND", {
            finding["failure_code"] for finding in validate_invariant_contract_v1(contract)
        })

    def test_recompilation_upgrades_old_ast_without_renesting_asset_shape(self):
        old = deepcopy(self.schema)
        for contract in old["x-invariant-contracts"].values():
            contract["predicate_ast"]["operator"] = contract["predicate_ast"].pop("algorithm")
            contract["operand_refs"] = [ref.replace("*", "0") for ref in contract["operand_refs"]]
        regenerated = _strengthen_artifact_schema("ASSET_PLAN", old)
        self.assertEqual(regenerated["properties"], self.schema["properties"])
        self.assertEqual(regenerated["x-invariant-contracts"], self.schema["x-invariant-contracts"])

    def test_parallel_provenance_arrays_pair_same_nested_index(self):
        contract = self.contracts["EVERY_ASSET_PROVENANCE_HASH_MATCHES_REFERENCED_BYTES"]
        data = {f"bytes://{i}": str(i).encode() for i in range(4)}
        document = {"assets": [{"provenance_refs": [f"bytes://{i}", f"bytes://{i+1}"],
            "provenance_sha256s": [sha256(data[f"bytes://{i}"]).hexdigest(), sha256(data[f"bytes://{i+1}"]).hexdigest()]}
            for i in (0, 2)]}
        self.assertTrue(evaluate_predicate_ast_v1(contract["predicate_ast"], document, resolver=data.__getitem__)["passed"])
        document["assets"][1]["provenance_refs"].reverse()
        result = evaluate_predicate_ast_v1(contract["predicate_ast"], document, resolver=data.__getitem__)
        self.assertFalse(result["passed"])
        self.assertEqual(result["failed_subjects"], ["/assets/1/provenance_sha256s/0", "/assets/1/provenance_sha256s/1"])

    def test_local_recipe_checks_all_four_pairs_and_reordering_remains_valid(self):
        contract = self.contracts["LOCAL_DETERMINISTIC_ASSET_RECIPE_AND_OUTPUT_ARE_HASH_BOUND"]
        fields = ("implementation", "input_manifest", "command_receipt", "output")
        data = {f"bytes://{field}": field.encode() for field in fields}
        recipe = {f"{field}_{suffix}": (sha256(data[f"bytes://{field}"]).hexdigest() if suffix == "sha256" else f"bytes://{field}")
                  for field in fields for suffix in ("ref", "sha256")}
        document = {"assets": [{"materialization_state": "LOCAL_DETERMINISTIC_VERIFIED", "local_build_recipe": recipe}]}
        self.assertTrue(evaluate_predicate_ast_v1(contract["predicate_ast"], document, resolver=data.__getitem__)["passed"])
        for field in fields:
            mutated = deepcopy(document)
            mutated["assets"][0]["local_build_recipe"][field + "_sha256"] = "0" * 64
            with self.subTest(field=field):
                self.assertFalse(evaluate_predicate_ast_v1(contract["predicate_ast"], mutated, resolver=data.__getitem__)["passed"])
        hash_contract = self.contracts["EVERY_MATERIALIZED_ASSET_REF_HASH_MATCHES_ASSET_SHA256"]
        assets = [{"materialization_state": "SOURCE_VERIFIED", "asset_ref": ref, "asset_sha256": sha256(raw).hexdigest()}
                  for ref, raw in data.items()]
        for order in (assets, assets[::-1]):
            self.assertTrue(evaluate_predicate_ast_v1(hash_contract["predicate_ast"], {"assets": order}, resolver=data.__getitem__)["passed"])
        empty = evaluate_predicate_ast_v1(hash_contract["predicate_ast"], {"assets": []}, resolver=data.__getitem__)
        self.assertEqual(empty["failure_code"], "INVARIANT_SUBJECT_SET_EMPTY")
