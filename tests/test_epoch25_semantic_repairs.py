"""Producer-to-reference-model regressions; no target or media execution."""

from copy import deepcopy
from hashlib import sha256
import json
import unittest

from harness_foundry_factory.invariant_contracts import evaluate_predicate_ast_v1, registered_operator_findings
from harness_foundry_factory.semantic_contracts import _strengthen_artifact_schema, oracle_evaluator_registry, JOB_SCOPED_ARTIFACT_KINDS, _bind_invariant_evaluation_contracts
from harness_foundry_factory.validator import _independent_invariant_contract_findings, _oracle_registry_is_independently_consistent


def schema(kind):
    return _strengthen_artifact_schema(kind, {"type": "object", "properties": {}})


def contract(kind, name):
    return schema(kind)["x-invariant-contracts"][name]


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


class Epoch25SemanticRepairsTests(unittest.TestCase):
    def test_demo_hash_pairs_execute_and_each_pair_can_fail(self):
        c = contract("BEFORE_AFTER_DEMO_CONTRACT", "BEFORE_AND_AFTER_HASHES_MATCH_REFERENCED_BYTES")
        data = {"before": b"before", "after": b"after"}
        doc = {f"{name}_{suffix}": (ref if suffix == "ref" else sha256(data[ref]).hexdigest())
               for name, ref in (("input_before", "before"), ("output_after", "after"))
               for suffix in ("ref", "sha256")}
        self.assertEqual(len(c["operand_refs"]), 4)
        self.assertTrue(evaluate_predicate_ast_v1(c["predicate_ast"], doc, resolver=data.__getitem__)["passed"])
        for field in ("input_before_sha256", "output_after_sha256"):
            bad = {**doc, field: "0" * 64}
            self.assertFalse(evaluate_predicate_ast_v1(c["predicate_ast"], bad, resolver=data.__getitem__)["passed"])

    def test_external_label_cannot_hide_malformed_registered_algorithm(self):
        s = schema("BEFORE_AFTER_DEMO_CONTRACT")
        c = s["x-invariant-contracts"]["BEFORE_AND_AFTER_HASHES_MATCH_REFERENCED_BYTES"]
        c["evaluation_contract_kind"] = "EXTERNAL_EXACT_ALGORITHM_V1"
        for obj in (c, c["predicate_ast"]):
            obj["operand_refs"].insert(0, "/output_after_sha256")
            obj["operand_types"].insert(0, "sha256")
            obj["parameters"]["operand_scopes"].insert(0, "GLOBAL")
            obj["cardinality"]["operand_count"] = 5
        codes = {f["code"] for f in _independent_invariant_contract_findings(s, "demo")}
        self.assertIn("INVARIANT_OPERAND_ARITY_INVALID", codes)

    def test_render_and_observed_bindings_cover_all_objects_and_fields(self):
        from harness_foundry_factory.media_evidence_contracts import evaluate_media_evidence_contract
        objects = [{"object_id": f"o{i}", "asset_id": f"a{i}", "sentence_ids": [f"s{i}"],
                    "claim_ids": [f"c{i}"], "visual_intent_id": f"v{i}", "audio_anchor_id": f"w{i}",
                    "motion_segments": [{"segment_id": f"seg{i}-{j}", "curve_id": f"curve{i}-{j}"} for j in range(3)]}
                   for i in range(2)]
        bindings = [{**{k: v for k, v in o.items() if k != "motion_segments"},
                     "motion_segment_ids": [segment["segment_id"] for segment in o["motion_segments"]],
                     "motion_curve_ids": [segment["curve_id"] for segment in o["motion_segments"]]} for o in objects]
        data = {"motion": raw({"shots": [{"objects": objects}]}),
                "render": raw({"rendered_semantic_bindings": bindings, "motion_ir_ref": "motion"})}
        for kind, name, field in (
            ("LOCAL_RENDER_RECEIPT", "RENDERED_SEMANTIC_BINDINGS_EQUAL_MOTION_IR_OBJECT_BINDINGS", "rendered_semantic_bindings"),
            ("MEDIA_ACCEPTANCE_RECEIPT", "OBSERVED_MOTION_SEMANTIC_BINDINGS_EQUAL_RENDERED_AND_MOTION_BINDINGS", "observed_motion_objects"),
        ):
            c = contract(kind, name)
            doc = {field: deepcopy(bindings), "motion_ir_ref": "motion", "render_receipt_ref": "render"}
            check = lambda d: evaluate_media_evidence_contract(c, d, data.__getitem__)["passed"]
            self.assertTrue(check(doc), name)
            self.assertTrue(check({**doc, field: bindings[::-1]}), name)
            for index in (0, 1):
                for key, value in bindings[index].items():
                    bad = deepcopy(doc); bad[field][index][key] = ["wrong"] if isinstance(value, list) else "wrong"
                    with self.subTest(kind=kind, index=index, key=key):
                        self.assertFalse(check(bad))
            for rows in ([], bindings[:1], [bindings[0], bindings[0]]):
                self.assertFalse(check({**doc, field: rows}))

    def test_ffprobe_mutation_does_not_change_shared_video_identity(self):
        from harness_foundry_factory.media_evidence_contracts import evaluate_media_evidence_contract
        from harness_foundry_factory.mutation_contracts import prepare_referenced_document_mutation
        s = schema("MEDIA_ACCEPTANCE_RECEIPT")
        artifacts = {"media": {"artifact_kind": "MEDIA_ACCEPTANCE_RECEIPT", "schema": s}}
        registry = oracle_evaluator_registry({"MEDIA_ACCEPTANCE_RECEIPT"}, list(artifacts.values()))
        name = "FFPROBE_INPUT_SHA256_EQUALS_VIDEO_SHA256"
        case = next(c for c in registry["invariant_negative_case_matrix"] if c["invariant_id"] == name)
        digest = sha256(b"video").hexdigest()
        data = {"probe": raw({"input_sha256": digest})}
        doc = {"video_sha256": digest, "ffprobe_receipt_ref": "probe", "ffprobe_receipt_sha256": sha256(data["probe"]).hexdigest()}
        mutated, overlay = prepare_referenced_document_mutation(doc, case["mutation"]["derivation_recipe"], data.__getitem__)
        resolver = {**data, **overlay}.__getitem__
        self.assertFalse(evaluate_media_evidence_contract(case["invariant_contract"], mutated, resolver)["passed"])
        peer = s["x-invariant-contracts"]["FFPROBE_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES"]
        self.assertTrue(evaluate_predicate_ast_v1(peer["predicate_ast"], mutated, resolver=resolver)["passed"])
        self.assertEqual(mutated["video_sha256"], digest)  # Render and Motion bindings remain unchanged.
        self.assertTrue(_oracle_registry_is_independently_consistent(registry, artifacts))
        case["mutation"]["derivation_recipe"].pop("referenced_document_mutation")
        self.assertFalse(_oracle_registry_is_independently_consistent(registry, artifacts))

    def test_imagegen_authorization_is_not_reference_existence(self):
        c = contract("ASSET_PLAN", "CODEX_IMAGEGEN_MATERIALIZATION_REQUIRES_SEPARATE_CURRENT_AUTHORIZATION")
        doc = {"job_id": "job", "assets": [{"materialization_state": "CODEX_IMAGEGEN_AUTHORIZED_MATERIALIZED",
               "generation_authorization_ref": "auth", "generation_receipt_ref": "receipt"}]}
        for body in ({}, {"status": "NOT_GRANTED"}, {"status": "REVOKED"}):
            self.assertFalse(evaluate_predicate_ast_v1(c["predicate_ast"], doc, resolver=lambda _: raw(body))["passed"])

    def test_valid_imagegen_receipt_binds_scope_time_output_and_single_consumption(self):
        c = contract("ASSET_PLAN", "CODEX_IMAGEGEN_MATERIALIZATION_REQUIRES_SEPARATE_CURRENT_AUTHORIZATION")
        scope = {field: field for field in ("target_skill_id", "job_id", "commit_sha", "input_manifest_sha256",
            "environment_id", "environment_manifest_ref", "environment_manifest_sha256", "output_root_ref", "output_manifest_sha256")}
        authorization = {"status": "GRANTED", "authorization_class": "CODEX_IMAGE_GENERATION_AUTHORIZATION",
                         "issuer_role": "HUMAN", "authorization_id": "authorization-1", "one_time_use": True,
                         "exact_scope": scope, "issued_at": "2026-09-05T10:00:00Z", "expires_at": "2026-09-05T11:00:00Z"}
        receipt = {"status": "PASS", "authorization_id": "authorization-1", "authorization_consumption_count": 1,
                   "exact_scope": scope, "executed_at": "2026-09-05T10:30:00Z", "output_ref": "asset", "output_sha256": "a" * 64}
        doc = {"job_id": "job_id", "assets": [{"materialization_state": "SOURCE_VERIFIED"},
            {"materialization_state": "CODEX_IMAGEGEN_AUTHORIZED_MATERIALIZED", "generation_authorization_ref": "auth",
             "generation_receipt_ref": "receipt", "asset_ref": "asset", "asset_sha256": "a" * 64}]}
        def check(auth, proof, document=doc):
            data = {"auth": raw(auth), "receipt": raw(proof)}
            return evaluate_predicate_ast_v1(c["predicate_ast"], document, resolver=data.__getitem__)
        self.assertTrue(check(authorization, receipt)["passed"])
        self.assertEqual(check(authorization, receipt)["evaluated_subject_count"], 1)
        for key, value in (("status", "NOT_GRANTED"), ("status", "REVOKED"), ("issuer_role", "AGENT"),
                           ("one_time_use", False), ("authorization_id", "another"),
                           ("issued_at", "2026-09-05T10:31:00Z"), ("expires_at", "2026-09-05T10:30:00Z")):
            with self.subTest(authorization_field=key, value=value):
                self.assertFalse(check({**authorization, key: value}, receipt)["passed"])
        for key in scope:
            wrong = deepcopy(receipt); wrong["exact_scope"][key] = "different"
            self.assertFalse(check(authorization, wrong)["passed"], key)
        for key, value in (("authorization_consumption_count", 2), ("authorization_consumption_count", True),
                           ("output_ref", "wrong"), ("output_sha256", "b" * 64)):
            self.assertFalse(check(authorization, {**receipt, key: value})["passed"], key)
        self.assertFalse(check(authorization, receipt, {**doc, "job_id": "other-job"})["passed"])
        planned = {"assets": [{"materialization_state": "CODEX_IMAGEGEN_PLANNED_NOT_AUTHORIZED"}]}
        self.assertTrue(evaluate_predicate_ast_v1(c["predicate_ast"], planned)["skipped"])

    def test_all_produced_registered_operators_validate_without_external_exemptions(self):
        for kind in JOB_SCOPED_ARTIFACT_KINDS | {"FIXTURE_ACCEPTANCE_RECEIPT", "AUTHORING_STOP_RECEIPT"}:
            with self.subTest(kind=kind):
                s = schema(kind)
                self.assertFalse(_independent_invariant_contract_findings(s, kind))
                for name, c in s["x-invariant-contracts"].items():
                    self.assertFalse(registered_operator_findings(c["predicate_ast"]), name)

    def test_producer_rejects_invalid_explicit_operator_instead_of_demoting(self):
        s = schema("BEFORE_AFTER_DEMO_CONTRACT")
        c = s["x-invariant-contracts"]["BEFORE_AND_AFTER_HASHES_MATCH_REFERENCED_BYTES"]
        c["input_refs"] += ["/input_before_ref"]
        with self.assertRaisesRegex(ValueError, "INVARIANT_REGISTERED_OPERATOR_INVALID"):
            _bind_invariant_evaluation_contracts(s)

    def test_independent_validator_rejects_reference_existence_and_first_item_regressions(self):
        for kind, name, legacy in (
            ("ASSET_PLAN", "CODEX_IMAGEGEN_MATERIALIZATION_REQUIRES_SEPARATE_CURRENT_AUTHORIZATION", "DECLARED_REFERENCE_RESOLUTION_V1"),
            ("LOCAL_RENDER_RECEIPT", "RENDERED_SEMANTIC_BINDINGS_EQUAL_MOTION_IR_OBJECT_BINDINGS", "CANONICAL_VALUE_OR_SET_EQUALITY_V1"),
            ("MEDIA_ACCEPTANCE_RECEIPT", "OBSERVED_MOTION_SEMANTIC_BINDINGS_EQUAL_RENDERED_AND_MOTION_BINDINGS", "CANONICAL_VALUE_OR_SET_EQUALITY_V1"),
        ):
            s = schema(kind); c = s["x-invariant-contracts"][name]
            c["algorithm"] = c["predicate_ast"]["algorithm"] = legacy
            self.assertTrue(_independent_invariant_contract_findings(s, kind), name)

    def test_old_projection_upgrades_and_is_idempotent(self):
        names = {
            "BEFORE_AFTER_DEMO_CONTRACT": "BEFORE_AND_AFTER_HASHES_MATCH_REFERENCED_BYTES",
            "LOCAL_RENDER_RECEIPT": "RENDERED_SEMANTIC_BINDINGS_EQUAL_MOTION_IR_OBJECT_BINDINGS",
            "MEDIA_ACCEPTANCE_RECEIPT": "OBSERVED_MOTION_SEMANTIC_BINDINGS_EQUAL_RENDERED_AND_MOTION_BINDINGS",
            "ASSET_PLAN": "CODEX_IMAGEGEN_MATERIALIZATION_REQUIRES_SEPARATE_CURRENT_AUTHORIZATION",
        }
        for kind, name in names.items():
            s = schema(kind); old = deepcopy(s); c = old["x-invariant-contracts"][name]
            if kind == "BEFORE_AFTER_DEMO_CONTRACT":
                c["input_refs"].insert(0, "/output_after_sha256")
            else:
                c["algorithm"] = "DECLARED_REFERENCE_RESOLUTION_V1" if kind == "ASSET_PLAN" else "CANONICAL_VALUE_OR_SET_EQUALITY_V1"
                c["input_refs"] = [c["target_ref"]]
            if kind == "ASSET_PLAN":
                old["properties"].pop("job_id"); old["required"].remove("job_id")
            rebuilt = _strengthen_artifact_schema(kind, old)
            self.assertEqual(rebuilt["x-invariant-contracts"], s["x-invariant-contracts"], kind)
            self.assertEqual(_strengthen_artifact_schema(kind, rebuilt), rebuilt, kind)

    def test_nary_audio_equality_and_signed_drift_keep_mathematical_semantics(self):
        c = contract("LOCAL_RENDER_RECEIPT", "TTS_ALIGNMENT_MOTION_AND_RENDER_AUDIO_SHA256_ARE_EQUAL")
        self.assertEqual(c["algorithm"], "ALL_VALUES_EQUAL_V1")
        ast = deepcopy(c["predicate_ast"])
        ast["operand_refs"] = [f"/v{i}" for i in range(4)]
        ast["subject_selector"] = "/v0"
        for wrong in (None, 0, 1, 2, 3):
            doc = {f"v{i}": "b" * 64 if i == wrong else "a" * 64 for i in range(4)}
            self.assertEqual(evaluate_predicate_ast_v1(ast, doc)["passed"], wrong is None)
        drift = contract("MEDIA_ACCEPTANCE_RECEIPT", "ABSOLUTE_FINAL_AV_DRIFT_DOES_NOT_EXCEED_ONE_FRAME")
        for value, expected in ((-2, False), (-1, True), (0, True), (1, True), (2, False)):
            self.assertEqual(evaluate_predicate_ast_v1(drift["predicate_ast"], {drift["target_ref"][1:]: value})["passed"], expected)

    def test_object_collection_contract_cannot_regress_to_scalar_or_first_subject(self):
        name = "RENDERED_SEMANTIC_BINDINGS_EQUAL_MOTION_IR_OBJECT_BINDINGS"
        for field, value in (("operand_types", ["scalar", "ref"]),
                             ("subject_selector", "/rendered_semantic_bindings/0/visual_intent_id")):
            s = schema("LOCAL_RENDER_RECEIPT"); c = s["x-invariant-contracts"][name]
            c[field] = c["predicate_ast"][field] = value
            self.assertIn("MEDIA_OBJECT_COLLECTION_BINDING_INVALID", {
                f["code"] for f in _independent_invariant_contract_findings(s, "render")})


if __name__ == "__main__":
    unittest.main()
