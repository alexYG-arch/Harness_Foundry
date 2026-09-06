"""Independent mixed-Case witnesses for the actual generated collection family.

These are contract tests, not Lab execution or media receipts.
"""

from copy import deepcopy
import json
from hashlib import sha256
from itertools import permutations
import unittest

from jsonschema import Draft202012Validator
from harness_foundry_factory.collection_relations import COLLECTION_RELATIONS, LEGACY_COLLECTION_FIELDS, ALGORITHM
from harness_foundry_factory.contract_references import pointer_values
from harness_foundry_factory.mutation_contracts import invariant_failure_closure, classify_mutation_result

from harness_foundry_factory.invariant_contracts import evaluate_predicate_ast_v1
from harness_foundry_factory.semantic_contracts import (
    _strengthen_artifact_schema, _bind_invariant_evaluation_contracts,
    schema_invariant_contracts_are_complete, oracle_evaluator_registry,
)
from harness_foundry_factory.validator import _independent_invariant_contract_findings, _oracle_registry_is_independently_consistent


def generated(kind="FIXTURE_ACCEPTANCE_RECEIPT"):
    return _strengthen_artifact_schema(kind, {"type": "object", "properties": {}})


def mixed_cases():
    """Hand-authored domains; no imports from the declaration/Producer for expected data."""
    inv = [
        {"case_id": "i-one", "schema_instance_results": [
            {"schema_sha256": "s1", "result_ref": "i-one-s1"},
            {"schema_sha256": "s2", "result_ref": "i-one-s2"}]},
        {"case_id": "i-two", "schema_instance_results": [
            {"schema_sha256": "s2", "result_ref": "i-two-s2"}]},
    ]
    native = [{"case_id": "n-one", "schema_instance_results": [
        {"schema_sha256": "s1", "result_ref": "n-one-s1"}]}]
    doc = {
        "fixture_results": [{"job_id": "j1", "source_id": "source1"},
                            {"job_id": "j2", "source_id": "source2"},
                            {"job_id": "j3", "source_id": "source3"}],
        "acceptance_case_results": [{"case_id": "a1", "result_ref": "a1-result"},
                                    {"case_id": "a2", "result_ref": "a2-result"}],
        "negative_case_results": [
            {"case_id": "bad1", "result_ref": "bad1-result", "mutation_variant_results": [
                {"variant_id": "common"}, {"variant_id": "only-bad1"}]},
            {"case_id": "bad2", "result_ref": "bad2-result", "mutation_variant_results": [
                {"variant_id": "common"}, {"variant_id": "only-bad2"}]},
        ],
        "invariant_negative_case_results": inv,
        "schema_native_negative_case_results": native,
    }
    resources = {
        "candidate://validation/PUBLIC_SKILL_JOB_INTERFACE.json": {
            "frozen_certification_fixtures": deepcopy(doc["fixture_results"])},
        "candidate://validation/ACCEPTANCE_CASES.json": {"cases": [
            {"case_id": "a1", "result_ref": "a1-result"},
            {"case_id": "a2", "result_ref": "a2-result"}]},
        "candidate://validation/NEGATIVE_CASES.json": {"cases": [
            {"case_id": "bad1", "result_ref": "bad1-result", "input_fixture": {
                "mutation_variants": [{"variant_id": "common"}, {"variant_id": "only-bad1"}]}},
            {"case_id": "bad2", "result_ref": "bad2-result", "input_fixture": {
                "mutation_variants": [{"variant_id": "common"}, {"variant_id": "only-bad2"}]}}]},
        "candidate://validation/ORACLE_EVALUATOR_REGISTRY.json": {
            "invariant_negative_case_matrix": [
                {"case_id": "i-one", "applicable_schema_sha256s": ["s1", "s2"]},
                {"case_id": "i-two", "applicable_schema_sha256s": ["s2"]}],
            "schema_native_negative_case_matrix": [{"case_id": "n-one"}]},
        "candidate://validation/CASE_EXECUTION_MANIFEST.json": {"registry_case_invocations": [
            {"case_kind": "INVARIANT", "case_id": "i-one", "schema_sha256": "s1", "result_ref": "i-one-s1"},
            {"case_kind": "INVARIANT", "case_id": "i-one", "schema_sha256": "s2", "result_ref": "i-one-s2"},
            {"case_kind": "INVARIANT", "case_id": "i-two", "schema_sha256": "s2", "result_ref": "i-two-s2"},
            {"case_kind": "SCHEMA_NATIVE", "case_id": "n-one", "schema_sha256": "s1", "result_ref": "n-one-s1"}]},
    }
    return doc, resources


def media_relations():
    """Independent three-shot witness with legitimate shared IDs across shots."""
    shots = [{"shot_id": f"shot{i}", "sentence_ids": [f"s{i}", "shared"],
              "audio_anchor_ids": [f"a{i}"], "objects": [{"object_id": f"o{i}",
              "motion_segments": [{"curve_id": f"c{i}"}]}]} for i in range(3)]
    motion = {"job_id": "job", "shots": shots, "motion_curve_ids": ["c0", "c1", "c2"],
              "sentence_ids": ["s0", "s1", "s2", "shared"], "audio_anchor_ids": ["a0", "a1", "a2"]}
    doc = {**deepcopy(motion), "asset_object_ids": ["o0", "o1", "o2"], "motion_object_ids": ["o0", "o1", "o2"],
           "rendered_shot_ids": ["shot0", "shot1", "shot2"], "rendered_object_ids": ["o0", "o1", "o2"],
           "rendered_motion_curve_ids": ["c0", "c1", "c2"], "observed_motion_objects": [
               {"object_id": f"o{i}", "motion_curve_ids": [f"c{i}"]} for i in range(3)]}
    resources = {"dependency://OBJECT_MOTION_IR": motion,
        "dependency://NARRATION_SCRIPT": {"job_id": "job", "sentences": [
            {"sentence_id": s} for s in ("shared", "s2", "s0", "s1")]},
        "dependency://AUDIO_ALIGNMENT_RECEIPT": {"job_id": "job", "word_anchors": [
            {"anchor_id": a} for a in ("a2", "a0", "a1")]}}
    return doc, resources


def schema_valid_case_witness():
    """Synthetic contract witness, never exported as a real Lab execution receipt."""
    doc, resources = mixed_cases()
    digest = lambda text: sha256(text.encode()).hexdigest()
    def pairs(row, fields):
        for field in fields:
            row[field + "_ref"] = row.get(field + "_ref", "unit-test/" + field)
            row[field + "_sha256"] = digest(row[field + "_ref"])
    for row in doc["fixture_results"]:
        row.update(fixture_id=row["job_id"], repository_url="https://example.invalid/fixture",
            commit_sha="1234567890" * 4, input_skill_count=1, output_count=1,
            expected_function="function", expected_scenario="scenario", expected_effect="effect",
            demo_contract_ref="unit-test/demo", oracle_decision="PASS", status="PASS")
        pairs(row, ["case_result", "video"])
    for row in doc["acceptance_case_results"]:
        pairs(row, ["result"])
        row.update(oracle_decision="PASS", status="PASS")
    for row in doc["negative_case_results"]:
        pairs(row, ["result", "mutation_manifest", "side_effect_receipt"])
        row.update(expected_failure_observed=True, observed_failure_code="TEST_REJECTION",
                   side_effects_started=False, oracle_decision="PASS", status="PASS")
        for variant in row["mutation_variant_results"]:
            pairs(variant, ["base_input", "mutated_input", "mutation_receipt", "command_receipt",
                            "validator_finding", "side_effect_receipt"])
            variant.update(expected_failure_observed=True, observed_failure_code="TEST_REJECTION",
                           side_effects_started=False, status="PASS")
    for field, native in (("invariant_negative_case_results", False), ("schema_native_negative_case_results", True)):
        for row in doc[field]:
            row.update(artifact_kind="UNIT_TEST_ARTIFACT")
            row.update({"constraint_id": "native"} if native else {"evaluator_id": "unit-evaluator", "invariant_id": "unit-invariant"})
            for child in row["schema_instance_results"]:
                child["schema_sha256"] = digest(child["schema_sha256"])
                pairs(child, ["result"])
                child.update(base_schema_pass=True, mutated_schema_pass=not native,
                    observed_failure_code="TEST_REJECTION", side_effects_started=False, status="PASS")
                child.update({"oracle_started": False} if native else {
                    "base_oracle_pass": True, "failed_invariant_ids": ["unit-invariant"]})
    for row in resources["candidate://validation/CASE_EXECUTION_MANIFEST.json"]["registry_case_invocations"]:
        row["schema_sha256"] = digest(row["schema_sha256"])
    for row in resources["candidate://validation/ORACLE_EVALUATOR_REGISTRY.json"]["invariant_negative_case_matrix"]:
        row["applicable_schema_sha256s"] = [digest(s) for s in row["applicable_schema_sha256s"]]
    for prefix, filename in (("acceptance_case_manifest", "ACCEPTANCE_CASES.json"),
                             ("negative_case_manifest", "NEGATIVE_CASES.json"),
                             ("oracle_evaluator_registry", "ORACLE_EVALUATOR_REGISTRY.json")):
        doc[prefix + "_ref"] = "harness-resource://candidate/validation/" + filename
        doc[prefix + "_sha256"] = digest(json.dumps(resources["candidate://validation/" + filename]))
    doc.update(isolation_policy="ONE_REPOSITORY_ONE_JOB_ONE_VIDEO", execution_started=True, status="PASS")
    return doc, resources


MEDIA_KINDS = ("ASSET_BINDING_RECEIPT", "OBJECT_MOTION_IR", "AUDIO_ALIGNMENT_RECEIPT",
               "LOCAL_RENDER_RECEIPT", "MEDIA_ACCEPTANCE_RECEIPT")


class CollectionRelationTests(unittest.TestCase):
    def evaluate(self, name, doc, resources, kind="FIXTURE_ACCEPTANCE_RECEIPT"):
        c = generated(kind)["x-invariant-contracts"][name]
        return evaluate_predicate_ast_v1(c["predicate_ast"], doc,
            resolver=lambda ref: json.dumps(resources[ref]).encode())

    def test_mixed_case_partitions_accept_correct_results(self):
        doc, resources = mixed_cases()
        for prefix in ("INVARIANT_NEGATIVE", "SCHEMA_NATIVE"):
            name = prefix + "_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS"
            self.assertTrue(self.evaluate(name, doc, resources)["passed"], name)

    def test_result_refs_are_bound_per_case_not_only_global_union(self):
        doc, resources = mixed_cases()
        name = "INVARIANT_NEGATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS"
        self.assertTrue(self.evaluate(name, doc, resources)["passed"])
        a, b = doc["invariant_negative_case_results"]
        a["schema_instance_results"][0]["result_ref"], b["schema_instance_results"][0]["result_ref"] = (
            b["schema_instance_results"][0]["result_ref"], a["schema_instance_results"][0]["result_ref"])
        self.assertFalse(self.evaluate(name, doc, resources)["passed"])

    def test_per_case_variants_and_schema_coverage(self):
        for name, field, children in (
            ("NEGATIVE_MUTATION_VARIANT_RESULT_IDS_EQUAL_DECLARED_VARIANT_IDS", "negative_case_results", "mutation_variant_results"),
            ("EVERY_INVARIANT_RESULT_COVERS_EXACT_APPLICABLE_SCHEMA_SHA256S", "invariant_negative_case_results", "schema_instance_results"),
        ):
            doc, resources = mixed_cases()
            self.assertTrue(self.evaluate(name, doc, resources)["passed"], name)
            a, b = doc[field]
            a[children], b[children] = b[children], a[children]
            self.assertFalse(self.evaluate(name, doc, resources)["passed"], name)

    def test_validator_rejects_old_unpartitioned_projection(self):
        s = generated()
        c = s["x-invariant-contracts"]["INVARIANT_NEGATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS"]
        for node in (c, c["predicate_ast"]):
            node["algorithm"] = "CANONICAL_VALUE_OR_SET_EQUALITY_V1"
            node["parameters"] = {"operand_scopes": ["GLOBAL", "GLOBAL"]}
        self.assertTrue(_independent_invariant_contract_findings(s, "fixture"))

    def test_family_is_complete_for_registry_consumers(self):
        s = generated()
        self.assertTrue(schema_invariant_contracts_are_complete(s))
        oracle_evaluator_registry({"FIXTURE_ACCEPTANCE_RECEIPT"}, [
            {"artifact_kind": "FIXTURE_ACCEPTANCE_RECEIPT", "schema": s}])

    def test_result_refs_are_bound_to_schema_instance_within_case(self):
        doc, resources = mixed_cases()
        children = doc["invariant_negative_case_results"][0]["schema_instance_results"]
        children[0]["result_ref"], children[1]["result_ref"] = children[1]["result_ref"], children[0]["result_ref"]
        name = "INVARIANT_NEGATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS"
        self.assertFalse(self.evaluate(name, doc, resources)["passed"])

    def test_fixture_source_ids_are_bound_to_job(self):
        doc, resources = mixed_cases()
        a, b = doc["fixture_results"][:2]
        a["source_id"], b["source_id"] = b["source_id"], a["source_id"]
        self.assertFalse(self.evaluate("FIXTURE_RESULT_SOURCE_IDS_EQUAL_FROZEN_REPOSITORY_SOURCE_IDS", doc, resources)["passed"])

    def test_every_family_member_has_a_generated_positive_witness(self):
        seen = set()
        for kind in (*MEDIA_KINDS, "FIXTURE_ACCEPTANCE_RECEIPT"):
            doc, resources = mixed_cases() if kind == "FIXTURE_ACCEPTANCE_RECEIPT" else media_relations()
            s = generated(kind)
            for n, c in s["x-invariant-contracts"].items():
                if n not in COLLECTION_RELATIONS:
                    continue
                seen.add(n)
                self.assertEqual(c["algorithm"], ALGORITHM)
                self.assertTrue(self.evaluate(n, doc, resources, kind)["passed"], (kind, n))
            self.assertTrue(schema_invariant_contracts_are_complete(s), kind)
        self.assertEqual(seen, set(COLLECTION_RELATIONS))

    def test_every_family_member_rejects_first_middle_last_missing_values(self):
        for kind in (*MEDIA_KINDS, "FIXTURE_ACCEPTANCE_RECEIPT"):
            base, resources = mixed_cases() if kind == "FIXTURE_ACCEPTANCE_RECEIPT" else media_relations()
            for n, c in generated(kind)["x-invariant-contracts"].items():
                if n not in COLLECTION_RELATIONS:
                    continue
                # Mutation follows the emitted row domain; expected rejection is independent:
                # removing any unique row loses at least one identity in these witnesses.
                field = c["parameters"]["queries"][0]["rows"][1:]
                for i in {0, len(base[field]) // 2, len(base[field]) - 1}:
                    doc = deepcopy(base)
                    del doc[field][i]
                    self.assertFalse(self.evaluate(n, doc, resources, kind)["passed"], (n, i))

    def test_legal_reordering_preserves_set_and_group_relations(self):
        doc, resources = mixed_cases()
        for order in permutations(range(4)):
            r = deepcopy(resources)
            rows = resources["candidate://validation/CASE_EXECUTION_MANIFEST.json"]["registry_case_invocations"]
            r["candidate://validation/CASE_EXECUTION_MANIFEST.json"]["registry_case_invocations"] = [rows[i] for i in order]
            for prefix in ("INVARIANT_NEGATIVE", "SCHEMA_NATIVE"):
                self.assertTrue(self.evaluate(prefix + "_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS", doc, r)["passed"])
        doc, resources = media_relations()
        doc["shots"].reverse()
        for n in ("SHOT_SENTENCE_ID_UNION_EQUALS_TOP_LEVEL_SENTENCE_IDS", "SHOT_AUDIO_ANCHOR_ID_UNION_EQUALS_TOP_LEVEL_AUDIO_ANCHOR_IDS"):
            self.assertTrue(self.evaluate(n, doc, resources, "OBJECT_MOTION_IR")["passed"])

    def test_foreign_partition_does_not_change_result_but_missing_kind_rejects(self):
        doc, resources = mixed_cases()
        name = "INVARIANT_NEGATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS"
        rows = resources["candidate://validation/CASE_EXECUTION_MANIFEST.json"]["registry_case_invocations"]
        rows.append({"case_kind": "SCHEMA_NATIVE", "case_id": "i-one", "schema_sha256": "s9", "result_ref": "foreign"})
        self.assertTrue(self.evaluate(name, doc, resources)["passed"])
        del rows[-1]["case_kind"]
        self.assertFalse(self.evaluate(name, doc, resources)["passed"])

    def test_dependency_job_identity_is_required(self):
        for kind in MEDIA_KINDS:
            for n, c in generated(kind)["x-invariant-contracts"].items():
                if n not in COLLECTION_RELATIONS:
                    continue
                for q in c["parameters"]["queries"]:
                    if not q["same_job"]:
                        continue
                    for job in (None, "other-job"):
                        doc, resources = media_relations()
                        resources[q["source"]]["job_id"] = job
                        self.assertFalse(self.evaluate(n, doc, resources, kind)["passed"], n)

    def test_unspecialized_job_schema_already_declares_ownership(self):
        from harness_foundry_factory.semantic_contracts import JOB_SCOPED_ARTIFACT_KINDS
        for kind in JOB_SCOPED_ARTIFACT_KINDS:
            s = generated(kind)
            self.assertIn("job_id", s["required"], kind)
            self.assertEqual(s["properties"]["job_id"], {"type": "string", "minLength": 1}, kind)

    def test_empty_set_is_not_missing_and_duplicate_group_rows_reject(self):
        name = "MOTION_OBJECT_IDS_EQUAL_ASSET_OBJECT_IDS"
        doc = {"motion_object_ids": [], "asset_object_ids": []}
        self.assertTrue(self.evaluate(name, doc, {}, "ASSET_BINDING_RECEIPT")["passed"])
        del doc["asset_object_ids"]
        self.assertFalse(self.evaluate(name, doc, {}, "ASSET_BINDING_RECEIPT")["passed"])
        doc, resources = mixed_cases()
        doc["invariant_negative_case_results"].append(deepcopy(doc["invariant_negative_case_results"][0]))
        self.assertFalse(self.evaluate("INVARIANT_NEGATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS", doc, resources)["passed"])

    def test_validator_rejects_joint_ast_and_contract_drift_and_missing_read_columns(self):
        for field, value in (("where", []), ("group_by", []), ("value_fields", [])):
            s = generated()
            c = s["x-invariant-contracts"]["INVARIANT_NEGATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS"]
            for node in (c, c["predicate_ast"]):
                node["parameters"]["queries"][1][field] = value
            self.assertTrue(_independent_invariant_contract_findings(s, "fixture"), field)
        s = generated()
        c = s["x-invariant-contracts"]["INVARIANT_NEGATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS"]
        c["input_refs"] = c["operand_refs"]
        codes = {f["code"] for f in _independent_invariant_contract_findings(s, "fixture")}
        self.assertIn("COLLECTION_READ_DOMAIN_INCOMPLETE", codes)

    def test_migration_is_explicit_and_idempotent_not_an_override_eraser(self):
        for kind in (*MEDIA_KINDS, "FIXTURE_ACCEPTANCE_RECEIPT"):
            expected = generated(kind)
            migrated = deepcopy(expected)
            for n, c in migrated["x-invariant-contracts"].items():
                if n in LEGACY_COLLECTION_FIELDS:
                    c.update(deepcopy(LEGACY_COLLECTION_FIELDS[n]))
            _bind_invariant_evaluation_contracts(migrated)
            self.assertEqual(migrated, expected)
            _bind_invariant_evaluation_contracts(migrated)
            self.assertEqual(migrated, expected)
        s = generated()
        c = s["x-invariant-contracts"]["INVARIANT_NEGATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS"]
        c.update(deepcopy(LEGACY_COLLECTION_FIELDS["INVARIANT_NEGATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS"]))
        c["input_refs"] = ["/unrecognized-user-override"]
        with self.assertRaisesRegex(ValueError, "COLLECTION_SEMANTIC_OVERRIDE_REQUIRES_DEFINITION"):
            _bind_invariant_evaluation_contracts(s)

    def test_migration_does_not_erase_unknown_legacy_precondition(self):
        n = "INVARIANT_NEGATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS"
        s = generated()
        c = s["x-invariant-contracts"][n]
        c.update(deepcopy(LEGACY_COLLECTION_FIELDS[n]))
        c["branch_precondition"] = "USER_DEFINED_UNKNOWN_BRANCH"
        with self.assertRaisesRegex(ValueError, "COLLECTION_SEMANTIC_OVERRIDE_REQUIRES_DEFINITION"):
            _bind_invariant_evaluation_contracts(s)

    def test_complete_schema_valid_witness_and_schema_preserving_bad_join(self):
        doc, resources = schema_valid_case_witness()
        s = generated()
        Draft202012Validator(s).validate(doc)
        for n, c in s["x-invariant-contracts"].items():
            if n in COLLECTION_RELATIONS:
                self.assertTrue(self.evaluate(n, doc, resources)["passed"], n)
        a, b = doc["invariant_negative_case_results"][0]["schema_instance_results"]
        for field in ("result_ref", "result_sha256"):
            a[field], b[field] = b[field], a[field]
        Draft202012Validator(s).validate(doc)
        self.assertFalse(self.evaluate("INVARIANT_NEGATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS", doc, resources)["passed"])

    def test_case_key_mutation_has_predeclared_consumer_scoped_failure_set(self):
        # Expectations are written from the domain relation, not copied from the graph.
        expected_peers = {
            "FIXTURE_RESULT_JOB_IDS_EQUAL_FROZEN_REPOSITORY_JOB_IDS": ["FIXTURE_RESULT_SOURCE_IDS_EQUAL_FROZEN_REPOSITORY_SOURCE_IDS"],
            "ACCEPTANCE_CASE_RESULT_IDS_EQUAL_FROZEN_ACCEPTANCE_CASE_IDS": ["ACCEPTANCE_CASE_RESULT_REFS_EQUAL_FROZEN_CASE_RESULT_REFS"],
            "NEGATIVE_CASE_RESULT_IDS_EQUAL_COMPLETE_NEGATIVE_CASE_IDS": ["NEGATIVE_CASE_RESULT_REFS_EQUAL_FROZEN_CASE_RESULT_REFS", "NEGATIVE_MUTATION_VARIANT_RESULT_IDS_EQUAL_DECLARED_VARIANT_IDS"],
            "INVARIANT_NEGATIVE_CASE_RESULT_IDS_EQUAL_REGISTRY_CASE_IDS": ["EVERY_INVARIANT_RESULT_COVERS_EXACT_APPLICABLE_SCHEMA_SHA256S", "INVARIANT_NEGATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS"],
            "EVERY_INVARIANT_RESULT_COVERS_EXACT_APPLICABLE_SCHEMA_SHA256S": ["INVARIANT_NEGATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS"],
            "SCHEMA_NATIVE_NEGATIVE_CASE_RESULT_IDS_EQUAL_REGISTRY_CASE_IDS": ["SCHEMA_NATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS"],
        }
        # These finite evidence consumers now also join the changed Case/schema
        # identities. Their byte-backed execution is covered in
        # test_registry_result_evidence, separately from this relation witness.
        evidence_peers = {
            "INVARIANT_NEGATIVE_CASE_RESULT_IDS_EQUAL_REGISTRY_CASE_IDS": "EVERY_INVARIANT_MUTATION_PRESERVES_JSON_SCHEMA_AND_FAILS_DECLARED_INVARIANT",
            "EVERY_INVARIANT_RESULT_COVERS_EXACT_APPLICABLE_SCHEMA_SHA256S": "EVERY_INVARIANT_MUTATION_PRESERVES_JSON_SCHEMA_AND_FAILS_DECLARED_INVARIANT",
            "SCHEMA_NATIVE_NEGATIVE_CASE_RESULT_IDS_EQUAL_REGISTRY_CASE_IDS": "EVERY_SCHEMA_NATIVE_MUTATION_FAILS_SCHEMA_WITHOUT_ORACLE_OR_SIDE_EFFECTS",
        }
        s = generated()
        artifact = {"artifact_kind": "FIXTURE_ACCEPTANCE_RECEIPT", "schema": s}
        registry = oracle_evaluator_registry({artifact["artifact_kind"]}, [artifact])
        self.assertTrue(_oracle_registry_is_independently_consistent(registry, {"fixture": artifact}))
        for target, peers in expected_peers.items():
            doc, resources = schema_valid_case_witness()
            ref = s["x-invariant-contracts"][target]["target_ref"]
            parent, _, field = ref.rpartition("/")
            pointer_values(doc, parent)[0][field] = sha256(b"different-instance").hexdigest() if field == "schema_sha256" else "different-identity"
            Draft202012Validator(s).validate(doc)
            # All relational predicates run; external Lab predicates remain NOT_RUN.
            failed = sorted(n for n in s["x-invariants"] if n in COLLECTION_RELATIONS
                            and not self.evaluate(n, doc, resources)["passed"])
            expected = sorted([target, *peers])
            self.assertEqual(failed, expected)
            if target in evidence_peers:
                expected = sorted([*expected, evidence_peers[target]])
            case = next(r for r in registry["invariant_negative_case_matrix"] if r["invariant_id"] == target)
            self.assertEqual(case["mutation"]["post_mutation_allowed_failed_invariant_ids"], expected)
            self.assertEqual(classify_mutation_result(target, schema_passed=True, failed_invariants=failed,
                execution_status="COMPLETED", allowed_failure_ids=expected, artifact_kind=artifact["artifact_kind"]), "EXPECTED_INVARIANT_REJECTION")
        name = "SENTENCE_IDS_EQUAL_NARRATION_SCRIPT_SENTENCE_IDS"
        self.assertEqual(invariant_failure_closure(name, artifact_kind="AUDIO_ALIGNMENT_RECEIPT"), [name])
        self.assertEqual(invariant_failure_closure(name, artifact_kind="OBJECT_MOTION_IR"), sorted([
            name, "SHOT_SENTENCE_ID_UNION_EQUALS_TOP_LEVEL_SENTENCE_IDS"]))
