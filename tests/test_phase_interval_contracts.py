"""Independent phase/timing witnesses; not media or Lab execution receipts."""

from copy import deepcopy
import unittest

from jsonschema import Draft202012Validator
from harness_foundry_factory.invariant_contracts import evaluate_predicate_ast_v1, validate_invariant_contract_v1
from harness_foundry_factory.semantic_contracts import _strengthen_artifact_schema, _bind_invariant_evaluation_contracts, oracle_evaluator_registry
from harness_foundry_factory.mutation_contracts import invariant_failure_closure, classify_mutation_result
from harness_foundry_factory.validator import _independent_invariant_contract_findings, _oracle_registry_is_independently_consistent

PHASE = "ENTER_HOLD_EXIT_SEGMENTS_ARE_CONTIGUOUS_AND_MATCH_DECLARED_INTERVALS"
SYNC = "EVERY_OBJECT_WORD_TO_MOTION_ERROR_DOES_NOT_EXCEED_0_1_SECONDS"


def schema():
    return _strengthen_artifact_schema("OBJECT_MOTION_IR", {"type": "object", "properties": {}})


def witness():
    state = lambda x: dict(x=x, y=0, scale=1, rotation_degrees=0, opacity=1)
    shots = []
    for si in range(3):
        objects = []
        for oi in range(3):
            start = si * 18
            segments = [dict(segment_id=f"s-{si}-{oi}-{i}", curve_id=f"c-{si}-{oi}-{i}",
                phase=phase, start_seconds=start+i, end_seconds=start+i+1,
                kind="TRANSLATE", easing="LINEAR", loop_count=1,
                from_state=state(i), to_state=state(i+1))
                for i, phase in enumerate(("ENTER", "HOLD", "EXIT"))]
            objects.append(dict(object_id=f"o-{si}-{oi}", asset_id=f"asset-{si}-{oi}",
                sentence_ids=["sentence"], claim_ids=["claim"], visual_intent_id="visual",
                semantic_role="illustration", source_type="LOCAL_PY_DETERMINISTIC",
                geometry=dict(x=0, y=0, width=1, height=1, unit="NORMALIZED"), z_order=oi,
                enter_time=start, hold_interval=dict(start_seconds=start+1, end_seconds=start+2),
                exit_time=start+3, motion_segments=segments, audio_anchor_id=f"a-{si}",
                invariants=["deterministic"], prohibited_changes=["identity"]))
        shots.append({"objects": objects})
    return {"shots": shots}


class PhaseIntervalContractTests(unittest.TestCase):
    def test_generated_contract_covers_every_object_and_every_phase(self):
        s = schema()
        contract = s["x-invariant-contracts"][PHASE]
        ast = contract["predicate_ast"]
        doc = witness()
        self.assertEqual(contract["evaluation_contract_kind"], "TYPED_KERNEL_V1")
        self.assertTrue(evaluate_predicate_ast_v1(ast, doc)["passed"])
        object_schema = s["properties"]["shots"]["items"]["properties"]["objects"]["items"]
        for si in range(3):
            for oi in range(3):
                for pi in range(3):
                    with self.subTest(shot=si, object=oi, phase=pi):
                        changed = deepcopy(doc)
                        obj = changed["shots"][si]["objects"][oi]
                        obj["motion_segments"][pi]["phase"] = "EXIT" if pi != 2 else "ENTER"
                        Draft202012Validator(object_schema).validate(obj)
                        result = evaluate_predicate_ast_v1(ast, changed)
                        self.assertFalse(result["passed"])
                        self.assertEqual(result["failed_subjects"], [f"/shots/{si}/objects/{oi}"])

    def test_each_interval_endpoint_is_bound_to_its_own_object(self):
        ast = schema()["x-invariant-contracts"][PHASE]["predicate_ast"]
        for pi in range(3):
            for endpoint in ("start_seconds", "end_seconds"):
                doc = witness()
                doc["shots"][2]["objects"][2]["motion_segments"][pi][endpoint] += 0.001
                result = evaluate_predicate_ast_v1(ast, doc)
                self.assertFalse(result["passed"])
                self.assertEqual(result["failed_subjects"], ["/shots/2/objects/2"])

    def test_operator_is_not_selected_by_video_invariant_name(self):
        ast = dict(algorithm="ORDERED_PHASE_INTERVAL_PARTITION_V1", quantifier="SINGLE",
            subject_selector="/steps", operand_refs=["/steps", "/begin", "/split", "/end"],
            operand_types=["array", "scalar", "scalar", "scalar"],
            cardinality=dict(mode="EXACT", operand_count=4, subject="ONE"),
            branch_selector={"mode": "ANY_JSON_SCHEMA_VALID_BRANCH"}, join_keys=[],
            parameters={"phases": ["PREPARE", "COMMIT"], "unit": "seconds",
                        "operand_scopes": ["GLOBAL"]*4})
        doc = dict(begin=4, split=5, end=7, steps=[
            dict(phase="PREPARE", start_seconds=4, end_seconds=5),
            dict(phase="COMMIT", start_seconds=5, end_seconds=7)])
        self.assertEqual(validate_invariant_contract_v1(ast), [])
        self.assertTrue(evaluate_predicate_ast_v1(ast, doc)["passed"])
        doc["steps"].reverse()
        self.assertFalse(evaluate_predicate_ast_v1(ast, doc)["passed"])
        ast["parameters"]["phases"] = ["PREPARE"]
        self.assertTrue(validate_invariant_contract_v1(ast))

    def test_independent_validator_rejects_first_object_only_projection(self):
        s = schema()
        c = s["x-invariant-contracts"][PHASE]
        c["input_refs"] = ["/shots/0/objects/0/motion_segments/1/phase"]
        findings = _independent_invariant_contract_findings(s, "motion")
        self.assertTrue(findings)

    def test_timing_mutation_declares_its_necessary_phase_failure(self):
        s = schema()
        registry = oracle_evaluator_registry({"OBJECT_MOTION_IR"}, [{"artifact_kind": "OBJECT_MOTION_IR", "schema": s}])
        case = next(c for c in registry["invariant_negative_case_matrix"] if c["invariant_id"] == SYNC)
        allowed = case["mutation"]["post_mutation_allowed_failed_invariant_ids"]
        self.assertIn(PHASE, allowed)
        doc = witness()
        doc["shots"][0]["objects"][0]["enter_time"] = 0.101
        # Independent arithmetic, not a failed-ID list copied from the catalog.
        observed = [SYNC] if abs(doc["shots"][0]["objects"][0]["enter_time"]) > 0.1 else []
        if not evaluate_predicate_ast_v1(s["x-invariant-contracts"][PHASE]["predicate_ast"], doc)["passed"]:
            observed.append(PHASE)
        self.assertEqual(set(observed), {SYNC, PHASE})
        self.assertEqual(classify_mutation_result(SYNC, schema_passed=True,
            failed_invariants=observed, execution_status="COMPLETED", allowed_failure_ids=allowed,
            artifact_kind="OBJECT_MOTION_IR"), "EXPECTED_INVARIANT_REJECTION")
        self.assertEqual(invariant_failure_closure(SYNC, artifact_kind="AUDIO_ALIGNMENT_RECEIPT"), [SYNC])
        case["mutation"]["post_mutation_allowed_failed_invariant_ids"] = [SYNC]
        self.assertFalse(_oracle_registry_is_independently_consistent(registry, {"m": {"artifact_kind": "OBJECT_MOTION_IR", "schema": s}}))

    def test_generated_projection_is_idempotent(self):
        s = schema()
        expected = deepcopy(s)
        _bind_invariant_evaluation_contracts(s)
        self.assertEqual(s, expected)

    def test_known_legacy_phase_projection_migrates_but_unknown_semantics_do_not(self):
        s = schema()
        expected = deepcopy(s)
        c = s["x-invariant-contracts"][PHASE]
        c.update(algorithm="OBJECT_PHASE_INTERVAL_CONTIGUITY_V1", input_refs=[
            "/shots/0/objects/0/motion_segments/1/phase",
            "/shots/*/objects/*/motion_segments/*/start_seconds",
            "/shots/*/objects/*/motion_segments/*/end_seconds",
            "/shots/*/objects/*/enter_time", "/shots/*/objects/*/hold_interval/start_seconds",
            "/shots/*/objects/*/hold_interval/end_seconds", "/shots/*/objects/*/exit_time"],
            parameters={"relation": "ENTER_HOLD_EXIT_EXACT_CONTIGUITY", "unit": "seconds",
                        "operand_scopes": ["GLOBAL"]*7})
        unknown = deepcopy(s)
        unknown["x-invariant-contracts"][PHASE]["parameters"]["unit"] = "frames"
        with self.assertRaisesRegex(ValueError, "PHASE_SEMANTIC_OVERRIDE"):
            _bind_invariant_evaluation_contracts(unknown)
        _bind_invariant_evaluation_contracts(s)
        self.assertEqual(s, expected)

    def test_short_hold_boundary_is_in_predeclared_timing_closure(self):
        s = schema()
        doc = witness()
        obj = doc["shots"][0]["objects"][0]
        obj["hold_interval"]["start_seconds"] = 0.05
        obj["motion_segments"][0]["end_seconds"] = 0.05
        obj["motion_segments"][1]["start_seconds"] = 0.05
        self.assertTrue(evaluate_predicate_ast_v1(s["x-invariant-contracts"][PHASE]["predicate_ast"], doc)["passed"])
        obj["enter_time"] = 0.101
        timing_ids = [PHASE, "ENTER_TIME_LESS_THAN_OR_EQUAL_TO_HOLD_START",
                      "HOLD_START_LESS_THAN_HOLD_END", "HOLD_END_LESS_THAN_OR_EQUAL_TO_EXIT_TIME"]
        observed = [SYNC] + [i for i in timing_ids if not evaluate_predicate_ast_v1(
            s["x-invariant-contracts"][i]["predicate_ast"], doc)["passed"]]
        self.assertEqual(set(observed), {SYNC, PHASE, "ENTER_TIME_LESS_THAN_OR_EQUAL_TO_HOLD_START"})
        self.assertEqual(set(invariant_failure_closure(SYNC, artifact_kind="OBJECT_MOTION_IR")), set(observed))
