"""Independent behavioral witnesses for generated operator families, not target execution."""

from copy import deepcopy
from hashlib import sha256
import json
from unittest import TestCase

from jsonschema import Draft202012Validator, ValidationError

from harness_foundry_factory.invariant_contracts import evaluate_predicate_ast_v1
from harness_foundry_factory.media_evidence_contracts import evaluate_media_evidence_contract
from harness_foundry_factory.semantic_contracts import (
    _strengthen_artifact_schema, _bind_invariant_evaluation_contracts,
    _invariant_algorithm_family, oracle_evaluator_registry,
)
from harness_foundry_factory.validator import (
    _independent_invariant_contract_findings, _oracle_registry_is_independently_consistent,
)
from harness_foundry_factory.mutation_contracts import classify_mutation_result


def schema(kind):
    return _strengthen_artifact_schema(kind, {"type": "object", "properties": {}})


def raw(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


BINDING = "LOCAL_DETERMINISTIC_RECIPE_OUTPUT_REF_EQUALS_ASSET_REF"
COLLECTIONS = (
    ("FUNCTION_SCENARIO_EFFECT_MATRIX", "CLAIM_IDS_ARE_UNIQUE", "claims", "claim_id"),
    ("NARRATION_SCRIPT", "NARRATION_VISUAL_INTENT_IDS_ARE_UNIQUE", "sentences", "visual_intent_id"),
)


def asset_fixture():
    data = {name: name.encode() for name in ("implementation", "input_manifest", "command_receipt", "output", "other")}
    recipe = {f"{name}_{suffix}": name if suffix == "ref" else sha256(data[name]).hexdigest()
              for name in ("implementation", "input_manifest", "command_receipt", "output")
              for suffix in ("ref", "sha256")}
    recipe.update(deterministic_seed=0, network_accessed=False, status="PASS")
    assets = []
    for i in range(3):
        assets.append({"asset_id": f"a{i}", "object_id": f"o{i}", "sentence_ids": [f"s{i}"],
            "claim_ids": [f"c{i}"], "visual_intent_id": f"v{i}", "route": "LOCAL_PY_DETERMINISTIC",
            "materialization_state": "LOCAL_DETERMINISTIC_VERIFIED", "asset_ref": "output",
            "asset_sha256": sha256(data["output"]).hexdigest(), "local_build_recipe": deepcopy(recipe),
            "provenance_refs": ["input_manifest"], "provenance_sha256s": [sha256(data["input_manifest"]).hexdigest()],
            "generation_authorization_ref": None, "generation_receipt_ref": None, "generation_receipt_sha256": None})
    doc = {"job_id": "job", "assets": assets, "asset_object_ids": [f"o{i}" for i in range(3)],
           "motion_object_ids": [f"o{i}" for i in range(3)], "status": "PASS"}
    doc["asset_manifest_sha256"] = sha256(raw(assets)).hexdigest()
    return doc, data


class SemanticOperatorFamilyTests(TestCase):
    def test_declared_failure_closure_is_not_an_arbitrary_failure_allowlist(self):
        peer = "LOCAL_DETERMINISTIC_ASSET_RECIPE_AND_OUTPUT_ARE_HASH_BOUND"
        for failures, expected in (([BINDING], "EXPECTED_INVARIANT_REJECTION"),
                                   ([BINDING, peer], "EXPECTED_INVARIANT_REJECTION"),
                                   ([peer], "TARGET_INVARIANT_NOT_REJECTED"),
                                   ([BINDING, "unrelated"], "NON_TARGET_INVARIANT_FAILURE")):
            self.assertEqual(classify_mutation_result(BINDING, schema_passed=True,
                failed_invariants=failures, execution_status="COMPLETED", allowed_failure_ids=[BINDING, peer]), expected)
        for status in ("NOT_RUN", "TIMEOUT", "RUNNER_ERROR"):
            self.assertEqual(classify_mutation_result(BINDING, schema_passed=True,
                failed_invariants=[BINDING, peer], execution_status=status,
                allowed_failure_ids=[BINDING, peer]), "INCONCLUSIVE")

    def test_registry_binds_failure_closure_before_execution(self):
        s = schema("ASSET_PLAN")
        artifact = {"artifact_kind": "ASSET_PLAN", "schema": s}
        registry = oracle_evaluator_registry({"ASSET_PLAN"}, [artifact])
        case = next(row for row in registry["invariant_negative_case_matrix"] if row["invariant_id"] == BINDING)
        self.assertEqual(case["mutation"]["post_mutation_allowed_failed_invariant_ids"], sorted([
            BINDING, "LOCAL_DETERMINISTIC_ASSET_RECIPE_AND_OUTPUT_ARE_HASH_BOUND"]))
        self.assertTrue(_oracle_registry_is_independently_consistent(registry, {"asset": artifact}))
        for changed in ([BINDING], [BINDING, "unrelated"]):
            bad = deepcopy(registry)
            row = next(row for row in bad["invariant_negative_case_matrix"] if row["invariant_id"] == BINDING)
            row["mutation"]["post_mutation_allowed_failed_invariant_ids"] = changed
            self.assertFalse(_oracle_registry_is_independently_consistent(bad, {"asset": artifact}))

    def test_actual_local_output_mutation_has_the_declared_peer_failure(self):
        s = schema("ASSET_PLAN")
        doc, data = asset_fixture()
        for c in s["x-invariant-contracts"].values():
            if c["evaluation_contract_kind"] == "TYPED_KERNEL_V1":
                self.assertTrue(evaluate_predicate_ast_v1(c, doc, resolver=data.__getitem__)["passed"])
        doc["assets"][0]["local_build_recipe"]["output_ref"] = "other"
        doc["asset_manifest_sha256"] = sha256(raw(doc["assets"])).hexdigest()
        Draft202012Validator(s).validate(doc)
        failures = sorted(name for name, c in s["x-invariant-contracts"].items()
                          if c["evaluation_contract_kind"] == "TYPED_KERNEL_V1"
                          and not evaluate_predicate_ast_v1(c, doc, resolver=data.__getitem__)["passed"])
        expected = sorted([BINDING, "LOCAL_DETERMINISTIC_ASSET_RECIPE_AND_OUTPUT_ARE_HASH_BOUND"])
        self.assertEqual(failures, expected)
        self.assertEqual(classify_mutation_result(BINDING, schema_passed=True,
            failed_invariants=failures, execution_status="COMPLETED", allowed_failure_ids=expected),
            "EXPECTED_INVARIANT_REJECTION")
        self.assertEqual(classify_mutation_result(BINDING, schema_passed=True,
            failed_invariants=[BINDING, "unrelated"], execution_status="COMPLETED",
            allowed_failure_ids=[BINDING, "unrelated"]), "INCONCLUSIVE")

    def test_schema_rejection_is_not_invariant_evidence(self):
        s = schema("ASSET_PLAN")
        doc, _ = asset_fixture()
        doc["assets"][0]["local_build_recipe"] = None
        with self.assertRaises(ValidationError):
            Draft202012Validator(s).validate(doc)
        self.assertEqual(classify_mutation_result(BINDING, schema_passed=False,
            failed_invariants=[BINDING], execution_status="COMPLETED"), "SCHEMA_REJECTED_NOT_INVARIANT_EVIDENCE")

    def test_recipe_requires_applicable_seed_and_validator_rejects_omission(self):
        s = schema("ASSET_PLAN")
        artifact = {"artifact_kind": "ASSET_PLAN", "schema": s}
        registry = oracle_evaluator_registry({"ASSET_PLAN"}, [artifact])
        case = next(c for c in registry["invariant_negative_case_matrix"] if c["invariant_id"] == BINDING)
        recipe = case["mutation"]["derivation_recipe"]
        self.assertEqual(recipe["required_base_subject_branch"], {
            "discriminator_ref": "/assets/0/materialization_state", "values": ["LOCAL_DETERMINISTIC_VERIFIED"]})
        del recipe["required_base_subject_branch"]
        self.assertFalse(_oracle_registry_is_independently_consistent(registry, {"asset": artifact}))

    def test_validator_rejects_missing_output_relation(self):
        s = schema("ASSET_PLAN")
        s["x-invariants"].remove(BINDING)
        del s["x-invariant-contracts"][BINDING]
        self.assertIn("INVARIANT_LOCAL_OUTPUT_BINDING_MISSING", {
            f["code"] for f in _independent_invariant_contract_findings(s, "asset")})

    def test_mutation_evidence_schema_carries_failure_set_and_recompile_updates_rule(self):
        s = schema("FIXTURE_ACCEPTANCE_RECEIPT")
        item = s["properties"]["invariant_negative_case_results"]["items"]["properties"]["schema_instance_results"]["items"]
        self.assertIn("failed_invariant_ids", item["required"])
        witness = {"schema_sha256": sha256(b"schema").hexdigest(), "result_ref": "test-result",
                   "result_sha256": sha256(b"test").hexdigest(), "base_schema_pass": True,
                   "base_oracle_pass": True, "mutated_schema_pass": True,
                   "failed_invariant_ids": [BINDING], "observed_failure_code": "ARTIFACT_INVARIANT_REJECTED",
                   "side_effects_started": False, "status": "PASS"}
        Draft202012Validator(item).validate(witness)
        del witness["failed_invariant_ids"]
        with self.assertRaises(ValidationError):
            Draft202012Validator(item).validate(witness)
        missing = deepcopy(s)
        missing["properties"]["invariant_negative_case_results"]["items"]["properties"]["schema_instance_results"]["items"]["required"].remove("failed_invariant_ids")
        self.assertIn("INVARIANT_FAILURE_SET_EVIDENCE_MISSING", {
            f["code"] for f in _independent_invariant_contract_findings(missing, "fixture")})
        name = "EVERY_INVARIANT_MUTATION_PRESERVES_JSON_SCHEMA_AND_FAILS_DECLARED_INVARIANT"
        s["x-invariant-contracts"][name]["decision_rule"] = "Schema PASS, exactly the declared invariant FAIL, all other invariants PASS."
        _bind_invariant_evaluation_contracts(s)
        self.assertEqual(s, schema("FIXTURE_ACCEPTANCE_RECEIPT"))

    def test_uniqueness_covers_every_member_and_legal_reordering(self):
        for kind, name, collection, key in COLLECTIONS:
            c = schema(kind)["x-invariant-contracts"][name]
            for size in (1, 2, 3, 5):
                members = [{key: f"id{i}"} for i in range(size)]
                for order in (members, members[::-1]):
                    self.assertTrue(evaluate_predicate_ast_v1(c["predicate_ast"], {collection: order})["passed"], (kind, size))
                if size > 1:
                    for index in range(size):
                        bad = deepcopy(members)
                        bad[index][key] = members[(index + 1) % size][key]
                        result = evaluate_predicate_ast_v1(c["predicate_ast"], {collection: bad})
                        self.assertFalse(result["passed"], (kind, size, index))
                        self.assertEqual(result["failure_code"], "INVARIANT_PREDICATE_FALSE")

    def test_motion_uniqueness_is_global_across_shots_and_objects(self):
        c = schema("OBJECT_MOTION_IR")["x-invariant-contracts"]["MOTION_SEGMENT_IDS_ARE_UNIQUE"]
        doc = {"shots": [{"objects": [{"motion_segments": [{"segment_id": f"s{s}-o{o}-m{m}"}
               for m in range(3)]} for o in range(2)]} for s in range(2)]}
        self.assertTrue(evaluate_predicate_ast_v1(c, doc)["passed"])
        for shot in range(2):
            for obj in range(2):
                for segment in range(3):
                    bad = deepcopy(doc)
                    bad["shots"][shot]["objects"][obj]["motion_segments"][segment]["segment_id"] = (
                        doc["shots"][1-shot]["objects"][1-obj]["motion_segments"][0]["segment_id"])
                    self.assertFalse(evaluate_predicate_ast_v1(c, bad)["passed"], (shot, obj, segment))

    def test_scalar_projection_cannot_be_hidden_by_external_label(self):
        for kind, name, collection, key in COLLECTIONS:
            s = schema(kind)
            c = s["x-invariant-contracts"][name]
            for contract in (c, c["predicate_ast"]):
                contract["operand_refs"] = [f"/{collection}/0/{key}"]
                contract["operand_types"] = ["scalar"]
            c["evaluation_contract_kind"] = "EXTERNAL_EXACT_ALGORITHM_V1"
            self.assertTrue(_independent_invariant_contract_findings(s, kind))

    def test_unknown_invariant_requires_registration_not_name_guessing(self):
        for name in ("NEW_IDS_ARE_UNIQUE", "NEW_HASH_MATCHES", "NEW_VALUE_LESS_THAN_LIMIT"):
            with self.assertRaises(ValueError):
                _invariant_algorithm_family(name)

    def test_complete_asset_schema_witness_catches_disconnected_output(self):
        s = schema("ASSET_PLAN")
        validator = Draft202012Validator(s)
        doc, data = asset_fixture()
        validator.validate(doc)
        self.assertIn(BINDING, s["x-invariant-contracts"])
        for index in range(3):
            bad = deepcopy(doc)
            bad["assets"][index]["asset_ref"] = "other"
            bad["assets"][index]["asset_sha256"] = sha256(data["other"]).hexdigest()
            bad["asset_manifest_sha256"] = sha256(raw(bad["assets"])).hexdigest()
            validator.validate(bad)
            for name, c in s["x-invariant-contracts"].items():
                if c["evaluation_contract_kind"] == "TYPED_KERNEL_V1":
                    result = evaluate_predicate_ast_v1(c["predicate_ast"], bad, resolver=data.__getitem__)
                    self.assertEqual(result["passed"], name != BINDING, (name, result))
            self.assertEqual(sha256(raw(bad["assets"])).hexdigest(), bad["asset_manifest_sha256"])

    def test_local_binding_does_not_apply_to_source_or_planned_image(self):
        s = schema("ASSET_PLAN")
        c = s["x-invariant-contracts"][BINDING]
        doc, data = asset_fixture()
        for index, state in enumerate(("SOURCE_VERIFIED", "CODEX_IMAGEGEN_PLANNED_NOT_AUTHORIZED")):
            a = doc["assets"][index]
            a.update(materialization_state=state, local_build_recipe=None,
                     route="SOURCE_EVIDENCE" if index == 0 else "CODEX_IMAGEGEN")
            if index:
                a.update(asset_ref=None, asset_sha256=None)
        doc["asset_manifest_sha256"] = sha256(raw(doc["assets"])).hexdigest()
        Draft202012Validator(s).validate(doc)
        result = evaluate_predicate_ast_v1(c, doc, resolver=data.__getitem__)
        self.assertTrue(result["passed"])
        self.assertEqual(result["evaluated_subject_count"], 1)

    def test_same_asset_reused_by_distinct_objects_is_a_valid_set(self):
        s = schema("LOCAL_RENDER_RECEIPT")
        c = s["x-invariant-contracts"]["RENDER_INPUT_MANIFEST_BINDS_EXACT_ASSET_REFS_AND_SHA256S"]
        plan, _ = asset_fixture()
        Draft202012Validator(schema("ASSET_PLAN")).validate(plan)
        member = {k: plan["assets"][0][k] for k in ("asset_ref", "asset_sha256")}
        for items in ([member], [member, member]):
            data = {"plan": raw(plan), "manifest": raw({"assets": items})}
            result = evaluate_media_evidence_contract(c, {"asset_plan_ref": "plan", "render_input_manifest_ref": "manifest"}, data.__getitem__)
            self.assertTrue(result["passed"], result)
        data["manifest"] = raw({"assets": [member, {**member, "asset_sha256": sha256(b"conflict").hexdigest()}]})
        self.assertFalse(evaluate_media_evidence_contract(c, {"asset_plan_ref": "plan", "render_input_manifest_ref": "manifest"}, data.__getitem__)["passed"])

    def test_recompile_removes_known_bad_collection_projection_and_adds_binding(self):
        for kind, name, collection, key in COLLECTIONS:
            old = schema(kind)
            c = old["x-invariant-contracts"][name]
            c.update(algorithm="CANONICAL_MEMBER_UNIQUENESS_V1", input_refs=[f"/{collection}/0/{key}"],
                     operand_refs=[f"/{collection}/0/{key}"], operand_types=["scalar"])
            _bind_invariant_evaluation_contracts(old)
            self.assertEqual(old, schema(kind))
        old = schema("ASSET_PLAN")
        old["x-invariants"].remove(BINDING)
        del old["x-invariant-contracts"][BINDING]
        refreshed = _strengthen_artifact_schema("ASSET_PLAN", old)
        self.assertEqual(refreshed, schema("ASSET_PLAN"))
        self.assertEqual(_strengthen_artifact_schema("ASSET_PLAN", refreshed), refreshed)

    def test_registry_and_validator_require_complete_collection_binding(self):
        for kind, name, collection, key in COLLECTIONS:
            s = schema(kind)
            artifact = {"artifact_kind": kind, "schema": s}
            registry = oracle_evaluator_registry({kind}, [artifact])
            self.assertTrue(_oracle_registry_is_independently_consistent(registry, {kind: artifact}))
            self.assertFalse(_independent_invariant_contract_findings(s, kind))
