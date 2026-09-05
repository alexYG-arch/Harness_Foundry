from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import unittest

from harness_foundry_factory.invariant_contracts import (
    evaluate_predicate_ast_v1,
    validate_invariant_contract_v1,
)


def contract(
    algorithm: str,
    operand_refs: list[str],
    operand_types: list[str],
    *,
    quantifier: str = "SINGLE",
    subject_selector: str = "/record",
    subject: str = "ONE",
    parameters: dict | None = None,
    join_keys: list[dict[str, str]] | None = None,
) -> dict:
    return {
        "algorithm": algorithm,
        "operand_refs": operand_refs,
        "operand_types": operand_types,
        "cardinality": {
            "mode": "EXACT",
            "operand_count": len(operand_refs),
            "subject": subject,
        },
        "quantifier": quantifier,
        "subject_selector": subject_selector,
        "branch_selector": {"mode": "ANY_JSON_SCHEMA_VALID_BRANCH"},
        "join_keys": join_keys or [],
        "parameters": parameters or {},
    }


class TypedInvariantContractTests(unittest.TestCase):
    def test_contract_semantics_do_not_depend_on_invariant_name(self) -> None:
        value = contract(
            "EXACT_EQUALITY_V1", ["/left", "/right"], ["scalar", "scalar"]
        )
        self.assertEqual(validate_invariant_contract_v1(value), [])
        mutated = deepcopy(value)
        mutated["algorithm"] = "HASH_AND_BYTE_LINEAGE_V1"
        codes = {
            item["failure_code"] for item in validate_invariant_contract_v1(mutated)
        }
        self.assertIn("INVARIANT_ALGORITHM_TYPE_MISMATCH", codes)

    def test_schema_types_and_unresolved_refs_are_checked(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"value": {"type": "number"}},
                    },
                }
            },
        }
        value = contract(
            "EXACT_EQUALITY_V1",
            ["/items/*/value", "/items/*/missing"],
            ["scalar", "scalar"],
            quantifier="FOR_ALL",
            subject_selector="/items/*",
            subject="MANY",
        )
        codes = {
            item["failure_code"]
            for item in validate_invariant_contract_v1(value, schema=schema)
        }
        self.assertIn("INVARIANT_OPERAND_REF_UNRESOLVED", codes)

    def test_quantifier_and_selector_are_explicitly_compatible(self) -> None:
        value = contract(
            "EXACT_EQUALITY_V1", ["/left", "/right"], ["scalar", "scalar"]
        )
        value["quantifier"] = "FOR_ALL"
        codes = {
            item["failure_code"] for item in validate_invariant_contract_v1(value)
        }
        self.assertIn("INVARIANT_QUANTIFIER_SELECTOR_MISMATCH", codes)
        self.assertIn("INVARIANT_CARDINALITY_INVALID", codes)

    def test_exists_and_pairwise_contracts_are_supported(self) -> None:
        exists = contract(
            "EXACT_EQUALITY_V1",
            ["/items/*/actual", "/items/*/expected"],
            ["scalar", "scalar"],
            quantifier="EXISTS",
            subject_selector="/items/*",
            subject="MANY",
        )
        pairwise = contract(
            "EXACT_EQUALITY_V1",
            ["/items/*/group", "/items/*/group"],
            ["scalar", "scalar"],
            quantifier="PAIRWISE",
            subject_selector="/items/*",
            subject="MANY",
        )
        self.assertEqual(validate_invariant_contract_v1(exists), [])
        self.assertEqual(validate_invariant_contract_v1(pairwise), [])
        document = {
            "items": [
                {"actual": "wrong", "expected": "ok", "group": "A"},
                {"actual": "ok", "expected": "ok", "group": "A"},
                {"actual": "wrong", "expected": "ok", "group": "A"},
            ]
        }
        self.assertTrue(evaluate_predicate_ast_v1(exists, document)["passed"])
        pairwise_result = evaluate_predicate_ast_v1(pairwise, document)
        self.assertTrue(pairwise_result["passed"])
        self.assertEqual(pairwise_result["evaluated_subject_count"], 3)

    def test_branch_selector_skips_non_selected_branch(self) -> None:
        value = contract(
            "EXACT_EQUALITY_V1", ["/left", "/right"], ["scalar", "scalar"]
        )
        value["branch_selector"] = {
            "mode": "REQUIRE_DISCRIMINATOR_CONST",
            "discriminator_ref": "/mode",
            "const": "ACTIVE",
        }
        result = evaluate_predicate_ast_v1(
            value, {"record": {}, "mode": "INACTIVE", "left": 1, "right": 2}
        )
        self.assertTrue(result["passed"])
        self.assertTrue(result["skipped"])

    def test_first_middle_and_last_collection_mutations_are_detected(self) -> None:
        value = contract(
            "EXACT_EQUALITY_V1",
            ["/items/*/actual", "/items/*/expected"],
            ["scalar", "scalar"],
            quantifier="FOR_ALL",
            subject_selector="/items/*",
            subject="MANY",
        )
        baseline = {
            "items": [
                {"actual": "A", "expected": "A"},
                {"actual": "B", "expected": "B"},
                {"actual": "C", "expected": "C"},
            ]
        }
        self.assertTrue(evaluate_predicate_ast_v1(value, baseline)["passed"])
        for position in (0, 1, 2):
            with self.subTest(position=position):
                mutation = deepcopy(baseline)
                mutation["items"][position]["actual"] = "MUTATED"
                result = evaluate_predicate_ast_v1(value, mutation)
                self.assertFalse(result["passed"])
                self.assertEqual(result["failure_code"], "INVARIANT_PREDICATE_FALSE")
                self.assertEqual(result["failed_subjects"], [f"/items/{position}"])

    def test_set_equality_uses_explicit_join_key(self) -> None:
        value = contract(
            "SET_EQUALITY_V1",
            ["/left", "/right"],
            ["array", "array"],
            parameters={"member_type": "object"},
            join_keys=[{"left_ref": "/id", "right_ref": "/id"}],
        )
        document = {
            "record": {},
            "left": [{"id": "A", "value": 1}, {"id": "B", "value": 2}],
            "right": [
                {"foreign_id": "B", "value": 99},
                {"foreign_id": "A", "value": 88},
            ],
        }
        value["join_keys"] = [{"left_ref": "/id", "right_ref": "/foreign_id"}]
        self.assertTrue(evaluate_predicate_ast_v1(value, document)["passed"])
        no_join = deepcopy(value)
        no_join["join_keys"] = []
        codes = {
            item["failure_code"] for item in validate_invariant_contract_v1(no_join)
        }
        self.assertIn("INVARIANT_JOIN_KEY_REQUIRED", codes)

    def test_object_operands_are_supported(self) -> None:
        value = contract(
            "EXACT_EQUALITY_V1", ["/left", "/right"], ["object", "object"]
        )
        document = {
            "record": {},
            "left": {"name": "same", "nested": {"value": 1}},
            "right": {"nested": {"value": 1}, "name": "same"},
        }
        self.assertEqual(validate_invariant_contract_v1(value), [])
        self.assertTrue(evaluate_predicate_ast_v1(value, document)["passed"])

    def test_numeric_threshold_is_statically_validated(self) -> None:
        value = contract(
            "ORDERED_NUMERIC_PREDICATE_V1",
            ["/duration"],
            ["scalar"],
            parameters={"relation": "LTE", "unit": "seconds", "threshold": "not-a-number"},
        )
        codes = {
            item["failure_code"] for item in validate_invariant_contract_v1(value)
        }
        self.assertIn("INVARIANT_NUMERIC_PARAMETERS_INCOMPLETE", codes)

    def test_hash_and_byte_lineage_hashes_resolved_bytes(self) -> None:
        payload = b"independent bytes"
        value = contract(
            "HASH_AND_BYTE_LINEAGE_V1",
            ["/artifact_ref", "/artifact_sha256"],
            ["ref", "sha256"],
        )
        document = {
            "record": {},
            "artifact_ref": "memory://artifact",
            "artifact_sha256": sha256(payload).hexdigest(),
        }
        result = evaluate_predicate_ast_v1(
            value,
            document,
            resolver=lambda reference: payload if reference == "memory://artifact" else None,
        )
        self.assertTrue(result["passed"])
        document["artifact_sha256"] = "0" * 64
        self.assertFalse(
            evaluate_predicate_ast_v1(
                value, document, resolver=lambda _reference: payload
            )["passed"]
        )

    def test_runtime_operand_type_mismatch_fails_closed(self) -> None:
        value = contract(
            "EXACT_ARRAY_CARDINALITY_COMPARISON_V1",
            ["/left", "/right"],
            ["array", "array"],
        )
        result = evaluate_predicate_ast_v1(
            value, {"record": {}, "left": "three", "right": "three"}
        )
        self.assertFalse(result["passed"])
        self.assertEqual(
            result["failure_code"], "INVARIANT_RUNTIME_OPERAND_TYPE_MISMATCH"
        )

    def test_cardinality_numeric_and_reference_algorithms_execute(self) -> None:
        cardinality = contract(
            "EXACT_ARRAY_CARDINALITY_COMPARISON_V1",
            ["/left", "/right"],
            ["array", "array"],
        )
        numeric = contract(
            "ORDERED_NUMERIC_PREDICATE_V1",
            ["/duration"],
            ["scalar"],
            parameters={"relation": "LTE", "unit": "seconds", "threshold": "180"},
        )
        reference = contract(
            "DECLARED_REFERENCE_RESOLUTION_V1", ["/artifact_ref"], ["ref"]
        )
        document = {
            "record": {},
            "left": [1, 2, 3],
            "right": ["a", "b", "c"],
            "duration": 179.5,
            "artifact_ref": "memory://artifact",
        }
        self.assertTrue(evaluate_predicate_ast_v1(cardinality, document)["passed"])
        self.assertTrue(evaluate_predicate_ast_v1(numeric, document)["passed"])
        self.assertTrue(
            evaluate_predicate_ast_v1(
                reference, document, resolver=lambda _reference: b"present"
            )["passed"]
        )

    def test_empty_quantified_subject_set_fails_closed(self) -> None:
        value = contract(
            "EXACT_EQUALITY_V1",
            ["/items/*/actual", "/items/*/expected"],
            ["scalar", "scalar"],
            quantifier="FOR_ALL",
            subject_selector="/items/*",
            subject="MANY",
        )
        result = evaluate_predicate_ast_v1(value, {"items": []})
        self.assertFalse(result["passed"])
        self.assertEqual(result["failure_code"], "INVARIANT_SUBJECT_SET_EMPTY")


if __name__ == "__main__":
    unittest.main()
