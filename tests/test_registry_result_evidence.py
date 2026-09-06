"""Finite evidence-consumer witnesses, not target Lab execution evidence."""

from copy import deepcopy
import json
from hashlib import sha256
import subprocess
import sys
import unittest
from jsonschema import Draft202012Validator

from harness_foundry_factory.invariant_contracts import evaluate_predicate_ast_v1
from harness_foundry_factory.semantic_contracts import _strengthen_artifact_schema, _bind_invariant_evaluation_contracts
from harness_foundry_factory.semantic_operator_catalog import semantic_projection_errors
from harness_foundry_factory.mutation_contracts import invariant_failure_closure
from harness_foundry_factory.registry_evidence import (
    observe_registry_process_v1, registry_execution_evidence_is_valid,
    REGISTRY_CASE_RESULT_SCHEMA, REGISTRY_CASE_EXECUTION_RECEIPT_SCHEMA,
)


KINDS = {
    "INVARIANT": "EVERY_INVARIANT_MUTATION_PRESERVES_JSON_SCHEMA_AND_FAILS_DECLARED_INVARIANT",
    "SCHEMA_NATIVE": "EVERY_SCHEMA_NATIVE_MUTATION_FAILS_SCHEMA_WITHOUT_ORACLE_OR_SIDE_EFFECTS",
}


MANIFEST_REF = "harness-resource://candidate/validation/CASE_EXECUTION_MANIFEST.json"


def sample(kind, *, with_evidence=True):
    identity_field = "invariant_id" if kind == "INVARIANT" else "constraint_id"
    matrix_field = "invariant_negative_case_matrix" if kind == "INVARIANT" else "schema_native_negative_case_matrix"
    root = "/invariant_negative_case_results" if kind == "INVARIANT" else "/schema_native_negative_case_results"
    registry_ref = "harness-resource://candidate/validation/ORACLE_EVALUATOR_REGISTRY.json"
    matrix, rows, contents, invocations = [], [], {}, []
    for name in ("alpha", "beta"):
        case = dict(case_id=name, artifact_kind="GENERIC_RECORD", evaluator_id="records", **{identity_field: name},
                    applicable_schema_sha256s=["1" * 64, "2" * 64],
                    expected_failure="ARTIFACT_INVARIANT_REJECTED" if kind == "INVARIANT" else "ARTIFACT_SCHEMA_REJECTED")
        case["mutation"] = {"post_mutation_allowed_failed_invariant_ids": [name, "dependent"]}
        matrix.append(case)
        row = {key: case[key] for key in ("case_id", "artifact_kind", identity_field)}
        if kind == "INVARIANT": row["evaluator_id"] = case["evaluator_id"]
        instances = []
        for digest in case["applicable_schema_sha256s"]:
            ref = f"harness-resource://execution/evidence/cases/registry/{name}/{digest}.result.json"
            fields = dict(schema_sha256=digest, base_schema_pass=True, mutated_schema_pass=kind == "INVARIANT",
                          observed_failure_code=case["expected_failure"], side_effects_started=False, status="PASS")
            if kind == "INVARIANT": fields.update(base_oracle_pass=True, failed_invariant_ids=[name, "dependent"])
            else: fields["oracle_started"] = False
            payload = {**fields, **row, "case_kind": kind}
            baseline = ref.removesuffix(".result.json") + "/inputs"
            command_ref = ref.removesuffix(".result.json") + ".command.json"
            invocation = dict(case_id=name, case_kind=kind, schema_sha256=digest,
                fixture_ref=registry_ref+f"#/{matrix_field}/{len(matrix)-1}",
                read_plan_ref=MANIFEST_REF+f"#/registry_case_invocations/{len(invocations)}/read_plan",
                baseline_root_ref=baseline, result_ref=ref, command_receipt_ref=command_ref,
                executor_command_id="LAB-RUN-REGISTRY-CASE", executor_argv=["python", "-m", "external_lab", "run-registry-case"])
            invocations.append(invocation)
            if with_evidence:
                payload["evidence_context"] = "REGISTRY_CASE_EXECUTION_RESULT"
                bound = {key: invocation[key] for key in ("case_id", "case_kind", "schema_sha256", "fixture_ref", "read_plan_ref", "baseline_root_ref", "result_ref")}
                receipt = dict(receipt_kind="REGISTRY_CASE_PROCESS_OBSERVATION", command_id="LAB-RUN-REGISTRY-CASE",
                    invocation=bound, argv=invocation["executor_argv"], process_argv=invocation["executor_argv"],
                    argv_binding="EXISTING_RUNTIME_URI_BINDING", execution_started=True, exit_code=0,
                    stdout="Case completed", stderr="", input_context="ISOLATED_CONTRACT_FIXTURE",
                    outcome={k:v for k,v in fields.items() if k != "schema_sha256"})
                for label, file_ref, data in (
                    ("command_receipt", command_ref, json.dumps(receipt).encode()),
                    ("base_input", baseline+"/base.json", b'{"value":1}'),
                    ("mutated_input", baseline+"/mutated.json", b'{"value":2}')):
                    contents[file_ref] = data
                    payload[label+"_ref"] = file_ref
                    payload[label+"_sha256"] = sha256(data).hexdigest()
            contents[ref] = json.dumps(payload).encode()
            instances.append({**fields, "result_ref": ref, "result_sha256": sha256(contents[ref]).hexdigest()})
        rows.append({**row, "schema_instance_results": instances})
    contents[registry_ref] = json.dumps({matrix_field: matrix}).encode()
    contents[MANIFEST_REF] = json.dumps({"registry_case_invocations": invocations}).encode()
    # Constructed records are only unit-test inputs, not actual Lab receipts.
    document = {root[1:]: rows, "oracle_evaluator_registry_ref": registry_ref}
    return document, contents


class RegistryResultEvidenceTests(unittest.TestCase):
    def test_registry_result_without_process_or_input_evidence_cannot_certify(self):
        for kind in KINDS:
            document, contents = sample(kind, with_evidence=False)
            result = evaluate_predicate_ast_v1(self.contract(kind)["predicate_ast"], document,
                                              resolver=contents.__getitem__)
            self.assertFalse(result["passed"], "outcome flags alone are not execution evidence")

    def contract(self, kind):
        schema = _strengthen_artifact_schema("FIXTURE_ACCEPTANCE_RECEIPT", {"type": "object", "properties": {}})
        return schema["x-invariant-contracts"][KINDS[kind]]

    def test_generated_predicates_are_pure_finite_evidence_consumers(self):
        for kind in KINDS:
            contract = self.contract(kind)
            self.assertEqual(contract["algorithm"], "REGISTRY_MUTATION_RESULT_EVIDENCE_V1")
            doc, contents = sample(kind)
            reads = []
            def resolve(ref):
                reads.append(ref)
                return contents[ref]
            result = evaluate_predicate_ast_v1(contract["predicate_ast"], doc, resolver=resolve)
            self.assertTrue(result["passed"], result)
            self.assertEqual(len(reads), 18)  # Registry, manifest, four (result + receipt + two inputs).

    def test_result_and_process_observation_schemas_cover_both_case_kinds(self):
        for kind in KINDS:
            _, contents = sample(kind)
            manifest = json.loads(contents[MANIFEST_REF])
            item = manifest["registry_case_invocations"][0]
            result = json.loads(contents[item["result_ref"]])
            Draft202012Validator(REGISTRY_CASE_RESULT_SCHEMA).validate(result)
            Draft202012Validator(REGISTRY_CASE_EXECUTION_RECEIPT_SCHEMA).validate(json.loads(contents[item["command_receipt_ref"]]))
            for field in ("command_receipt_ref", "base_input_sha256", "mutated_input_ref", "evidence_context"):
                changed = deepcopy(result); del changed[field]
                self.assertFalse(Draft202012Validator(REGISTRY_CASE_RESULT_SCHEMA).is_valid(changed))
            failed = {key: result[key] for key in ("case_id", "case_kind", "artifact_kind", "schema_sha256")}
            failed.update(status="INCONCLUSIVE", diagnostic="setup input is unavailable")
            Draft202012Validator(REGISTRY_CASE_RESULT_SCHEMA).validate(failed)
            self.assertFalse(registry_execution_evidence_is_valid(failed, item, contents.__getitem__))

    def test_completed_process_exit_not_printed_pass_is_observed(self):
        _, contents = sample("INVARIANT")
        invocation = json.loads(contents[MANIFEST_REF])["registry_case_invocations"][0]
        result = json.loads(contents[invocation["result_ref"]])
        outcome = json.loads(contents[invocation["command_receipt_ref"]])["outcome"]
        for code in (0, 2):
            argv = [sys.executable, "-c", f"print('PASS'); raise SystemExit({code})"]
            completed = subprocess.run(argv, capture_output=True, text=True, check=False)
            receipt = observe_registry_process_v1(invocation, completed, outcome, resolved_argv=argv)
            self.assertEqual(receipt["exit_code"], code)
            self.assertEqual(receipt["process_argv"], argv)
            self.assertEqual(receipt["argv"], invocation["executor_argv"])
            data = json.dumps(receipt).encode()
            contents[invocation["command_receipt_ref"]] = data
            result["command_receipt_sha256"] = sha256(data).hexdigest()
            self.assertEqual(registry_execution_evidence_is_valid(result, invocation, contents.__getitem__), code == 0)
            with self.assertRaisesRegex(ValueError, "ARGV_DIFFERS"):
                observe_registry_process_v1(invocation, completed, outcome, resolved_argv=["wrong"])

    def test_missing_rebound_or_unchanged_input_evidence_rejects(self):
        for kind in KINDS:
            for mutation in ("missing_receipt", "wrong_receipt_hash", "wrong_invocation", "setup_only", "wrong_outcome", "same_inputs", "changed_input", "wrong_context"):
                _, contents = sample(kind)
                invocation = json.loads(contents[MANIFEST_REF])["registry_case_invocations"][0]
                result = json.loads(contents[invocation["result_ref"]])
                command_ref = invocation["command_receipt_ref"]
                receipt = json.loads(contents[command_ref])
                if mutation == "missing_receipt": del contents[command_ref]
                elif mutation == "wrong_receipt_hash": result["command_receipt_sha256"] = "0"*64
                elif mutation == "same_inputs":
                    contents[result["mutated_input_ref"]] = contents[result["base_input_ref"]]
                    result["mutated_input_sha256"] = result["base_input_sha256"]
                elif mutation == "changed_input": contents[result["base_input_ref"]] = b'{"other":true}'
                elif mutation == "wrong_context": result["evidence_context"] = "ISOLATED_CONTRACT_FIXTURE"
                else:
                    if mutation == "wrong_invocation": receipt["invocation"]["case_id"] = "other"
                    elif mutation == "setup_only": receipt["execution_started"] = False
                    else: receipt["outcome"]["base_schema_pass"] = False
                    contents[command_ref] = json.dumps(receipt).encode()
                    result["command_receipt_sha256"] = sha256(contents[command_ref]).hexdigest()
                self.assertFalse(registry_execution_evidence_is_valid(result, invocation, contents.__getitem__), (kind, mutation))

    def test_missing_duplicate_or_wrong_schema_result_cannot_pass(self):
        for kind in KINDS:
            ast = self.contract(kind)["predicate_ast"]
            for mutation in ("missing_case", "duplicate_case", "missing_schema", "duplicate_schema", "wrong_schema"):
                doc, contents = sample(kind)
                rows = doc[ast["subject_selector"][1:]]
                if mutation == "missing_case": rows.pop()
                elif mutation == "duplicate_case": rows.append(deepcopy(rows[0]))
                elif mutation == "missing_schema": rows[0]["schema_instance_results"].pop()
                elif mutation == "duplicate_schema": rows[0]["schema_instance_results"].append(deepcopy(rows[0]["schema_instance_results"][0]))
                else: rows[0]["schema_instance_results"][0]["schema_sha256"] = "3" * 64
                self.assertFalse(evaluate_predicate_ast_v1(ast, doc, resolver=contents.__getitem__)["passed"], (kind, mutation))

    def test_flags_failure_closure_and_result_byte_projection_are_all_checked(self):
        for kind in KINDS:
            ast = self.contract(kind)["predicate_ast"]
            for field, value in [("base_schema_pass", False), ("mutated_schema_pass", kind != "INVARIANT"),
                                 ("side_effects_started", True), ("observed_failure_code", "RUNNER_ERROR")]:
                doc, contents = sample(kind)
                item = doc[ast["subject_selector"][1:]][0]["schema_instance_results"][0]
                item[field] = value
                payload = json.loads(contents[item["result_ref"]]); payload[field] = value
                contents[item["result_ref"]] = json.dumps(payload).encode()
                self.assertFalse(evaluate_predicate_ast_v1(ast, doc, resolver=contents.__getitem__)["passed"], (kind, field))
            doc, contents = sample(kind)
            item = doc[ast["subject_selector"][1:]][0]["schema_instance_results"][0]
            payload = json.loads(contents[item["result_ref"]]); payload["case_id"] = "substituted"
            contents[item["result_ref"]] = json.dumps(payload).encode()
            self.assertFalse(evaluate_predicate_ast_v1(ast, doc, resolver=contents.__getitem__)["passed"])
        ast = self.contract("INVARIANT")["predicate_ast"]
        for failed in (["dependent"], ["alpha", "undeclared"], ["alpha", "alpha"]):
            doc, contents = sample("INVARIANT")
            item = doc[ast["subject_selector"][1:]][0]["schema_instance_results"][0]
            item["failed_invariant_ids"] = failed
            self.assertFalse(evaluate_predicate_ast_v1(ast, doc, resolver=contents.__getitem__)["passed"])

    def test_independent_projection_rejects_recursive_algorithm_and_wrong_branch(self):
        for kind in KINDS:
            contract = self.contract(kind)
            for field, value in [("algorithm", "INVARIANT_COUNTEREXAMPLE_REPLAY_V1"),
                                 ("branch_selector", {"mode": "REQUIRE_DISCRIMINATOR_CONST", "discriminator_ref": "/status", "const": "SKIP"})]:
                damaged = deepcopy(contract); damaged[field] = value
                self.assertIn("INVARIANT_RESULT_EVIDENCE_DOMAIN_INVALID", semantic_projection_errors(KINDS[kind], damaged))

    def test_exact_legacy_migration_is_idempotent_and_preserves_unknown_overrides(self):
        schema = _strengthen_artifact_schema("FIXTURE_ACCEPTANCE_RECEIPT", {"type": "object", "properties": {}})
        _bind_invariant_evaluation_contracts(schema)
        stable = deepcopy(schema); _bind_invariant_evaluation_contracts(schema)
        self.assertEqual(schema, stable)
        schema["x-invariant-contracts"][KINDS["INVARIANT"]]["parameters"]["case_kind"] = "SKIP"
        with self.assertRaisesRegex(ValueError, "RESULT_EVIDENCE_SEMANTIC_OVERRIDE"):
            _bind_invariant_evaluation_contracts(schema)

    def test_result_identity_mutations_declare_the_finite_consumer_dependency(self):
        pairs = {
            "INVARIANT_NEGATIVE_CASE_RESULT_IDS_EQUAL_REGISTRY_CASE_IDS": "INVARIANT",
            "EVERY_INVARIANT_RESULT_COVERS_EXACT_APPLICABLE_SCHEMA_SHA256S": "INVARIANT",
            "INVARIANT_NEGATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS": "INVARIANT",
            "SCHEMA_NATIVE_NEGATIVE_CASE_RESULT_IDS_EQUAL_REGISTRY_CASE_IDS": "SCHEMA_NATIVE",
            "SCHEMA_NATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS": "SCHEMA_NATIVE",
        }
        for target, kind in pairs.items():
            doc, contents = sample(kind)
            ast = self.contract(kind)["predicate_ast"]
            row = doc[ast["subject_selector"][1:]][0]
            if "CASE_RESULT_IDS" in target: row["case_id"] = "other"
            elif "APPLICABLE_SCHEMA" in target: row["schema_instance_results"][0]["schema_sha256"] = "3" * 64
            else: row["schema_instance_results"][0]["result_ref"] = "missing"
            self.assertFalse(evaluate_predicate_ast_v1(ast, doc, resolver=contents.__getitem__)["passed"])
            self.assertIn(KINDS[kind], invariant_failure_closure(target, artifact_kind="FIXTURE_ACCEPTANCE_RECEIPT"))

    def test_known_replay_projections_migrate_without_changing_unrelated_contracts(self):
        schema = _strengthen_artifact_schema("FIXTURE_ACCEPTANCE_RECEIPT", {"type": "object", "properties": {}})
        fresh = deepcopy(schema)
        for kind, identity in KINDS.items():
            contract = schema["x-invariant-contracts"][identity]
            root = contract["subject_selector"]
            contract.update(algorithm="INVARIANT_COUNTEREXAMPLE_REPLAY_V1" if kind == "INVARIANT" else "SCHEMA_NATIVE_REJECTION_REPLAY_V1",
                input_refs=[contract["target_ref"], root, "candidate://validation/ORACLE_EVALUATOR_REGISTRY.json"],
                parameters={"operand_scopes": ["SUBJECT", "GLOBAL", "GLOBAL"]})
        _bind_invariant_evaluation_contracts(schema)
        self.assertEqual(schema, fresh)
