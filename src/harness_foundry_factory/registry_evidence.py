"""Registry result wire contracts and finite process/input evidence checking.

No signing, execution authority, filesystem, subprocess launch, or test replay.
The supervisor supplies the observed CompletedProcess, not a child's PASS claim.
"""

from copy import deepcopy
from hashlib import sha256
import json


EXECUTION_MANIFEST_REF = "harness-resource://candidate/validation/CASE_EXECUTION_MANIFEST.json"
RESULT_SCHEMA_REF = "harness-resource://candidate/validation/schemas/REGISTRY_CASE_RESULT.schema.json"
RECEIPT_SCHEMA_REF = "harness-resource://candidate/validation/schemas/REGISTRY_CASE_EXECUTION_RECEIPT.schema.json"
TEXT = {"type": "string", "minLength": 1}
DIGEST = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
BINDING_FIELDS = ("case_id", "case_kind", "schema_sha256", "fixture_ref", "read_plan_ref", "baseline_root_ref", "result_ref")
OUTCOME_FIELDS = ("base_schema_pass", "mutated_schema_pass", "observed_failure_code", "side_effects_started", "status")
INVARIANT_FIELDS = ("base_oracle_pass", "failed_invariant_ids")
SCHEMA_FIELDS = ("oracle_started",)


REGISTRY_CASE_RESULT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": RESULT_SCHEMA_REF,
    "type": "object", "additionalProperties": False,
    "required": ["case_id", "case_kind", "artifact_kind", "schema_sha256", "status"],
    "properties": {
        **{name: deepcopy(TEXT) for name in ("case_id", "artifact_kind", "invariant_id", "constraint_id", "evaluator_id", "diagnostic")},
        "case_kind": {"enum": ["INVARIANT", "SCHEMA_NATIVE"]}, "schema_sha256": deepcopy(DIGEST),
        "status": {"enum": ["PASS", "FAIL", "INCONCLUSIVE"]},
        "evidence_context": {"const": "REGISTRY_CASE_EXECUTION_RESULT"},
        **{name: {"type": "boolean"} for name in ("base_schema_pass", "base_oracle_pass", "mutated_schema_pass", "side_effects_started", "oracle_started")},
        "observed_failure_code": deepcopy(TEXT),
        "failed_invariant_ids": {"type": "array", "minItems": 1, "uniqueItems": True, "items": deepcopy(TEXT)},
        **{f"{name}_ref": deepcopy(TEXT) for name in ("command_receipt", "base_input", "mutated_input")},
        **{f"{name}_sha256": deepcopy(DIGEST) for name in ("command_receipt", "base_input", "mutated_input")},
    },
    "allOf": [
        {"if": {"properties": {"status": {"const": "PASS"}}},
         "then": {"required": ["evidence_context", *OUTCOME_FIELDS,
                                *[f"{name}_{suffix}" for name in ("command_receipt", "base_input", "mutated_input") for suffix in ("ref", "sha256")]]},
         "else": {"required": ["diagnostic"]}},
        {"if": {"properties": {"case_kind": {"const": "INVARIANT"}, "status": {"const": "PASS"}}},
         "then": {"required": ["invariant_id", "evaluator_id", *INVARIANT_FIELDS]}},
        {"if": {"properties": {"case_kind": {"const": "SCHEMA_NATIVE"}, "status": {"const": "PASS"}}},
         "then": {"required": ["constraint_id", *SCHEMA_FIELDS]}},
    ],
}

REGISTRY_CASE_EXECUTION_RECEIPT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": RECEIPT_SCHEMA_REF,
    "type": "object", "additionalProperties": False,
    "required": ["receipt_kind", "command_id", "invocation", "argv", "process_argv", "argv_binding", "execution_started", "exit_code", "stdout", "stderr", "input_context", "outcome"],
    "properties": {
        "receipt_kind": {"const": "REGISTRY_CASE_PROCESS_OBSERVATION"},
        "command_id": {"const": "LAB-RUN-REGISTRY-CASE"},
        "invocation": {"type": "object", "additionalProperties": False,
                       "required": list(BINDING_FIELDS), "properties": {name: deepcopy(TEXT) for name in BINDING_FIELDS}},
        "argv": {"type": "array", "minItems": 1, "items": deepcopy(TEXT)},
        "process_argv": {"type": "array", "minItems": 1, "items": deepcopy(TEXT)},
        "argv_binding": {"const": "EXISTING_RUNTIME_URI_BINDING"},
        "execution_started": {"type": "boolean"}, "exit_code": {"type": ["integer", "null"]},
        "stdout": {"type": "string"}, "stderr": {"type": "string"},
        "input_context": {"const": "ISOLATED_CONTRACT_FIXTURE"},
        "outcome": {"type": "object", "additionalProperties": False,
                    "required": list(OUTCOME_FIELDS),
                    "properties": {name: deepcopy(REGISTRY_CASE_RESULT_SCHEMA["properties"][name])
                                   for name in (*OUTCOME_FIELDS, *INVARIANT_FIELDS, *SCHEMA_FIELDS)}},
    },
}

def observe_registry_process_v1(invocation, completed, outcome, *, resolved_argv):
    """Project an already finished process observed by the local supervisor.

    Logs are stored inline once. This performs no execution and does not turn
    exit 2, timeout, missing process, or setup failure into a passing receipt.
    """
    if list(completed.args) != list(resolved_argv):
        raise ValueError("REGISTRY_PROCESS_ARGV_DIFFERS_FROM_RUNTIME_BINDING")
    return {
        "receipt_kind": "REGISTRY_CASE_PROCESS_OBSERVATION", "command_id": "LAB-RUN-REGISTRY-CASE",
        "invocation": {name: invocation[name] for name in BINDING_FIELDS},
        "argv": list(invocation["executor_argv"]), "process_argv": list(completed.args),
        "argv_binding": "EXISTING_RUNTIME_URI_BINDING",
        "execution_started": True, "exit_code": completed.returncode,
        "stdout": completed.stdout, "stderr": completed.stderr,
        "input_context": "ISOLATED_CONTRACT_FIXTURE", "outcome": deepcopy(outcome),
    }


def registry_execution_evidence_is_valid(result, invocation, resolver):
    """Verify one result's process observation and actual before/after bytes.

    The caller has already matched the aggregate's outcome projection and the
    frozen Case. Result/Registry hashes have their existing separate consumers.
    Here each of the three previously unbound referenced files is read/hashed
    once; no self-hash, extra signature, or recursive baseline validation.
    """
    try:
        if (not isinstance(result, dict) or set(result) - set(REGISTRY_CASE_RESULT_SCHEMA["properties"])
                or result.get("case_kind") not in {"INVARIANT", "SCHEMA_NATIVE"}):
            return False
        if result["evidence_context"] != "REGISTRY_CASE_EXECUTION_RESULT" or result["status"] != "PASS":
            return False
        if any(result[name] != invocation[name] for name in ("case_id", "case_kind", "schema_sha256")):
            return False
        expected_refs = {
            "command_receipt": invocation["command_receipt_ref"],
            "base_input": invocation["baseline_root_ref"] + "/base.json",
            "mutated_input": invocation["baseline_root_ref"] + "/mutated.json",
        }
        contents = {}
        for name, ref in expected_refs.items():
            if result[f"{name}_ref"] != ref:
                return False
            value = resolver(ref)
            if not isinstance(value, bytes) or sha256(value).hexdigest() != result[f"{name}_sha256"]:
                return False
            contents[name] = value
        if contents["base_input"] == contents["mutated_input"]:
            return False
        receipt = json.loads(contents["command_receipt"])
        if not isinstance(receipt, dict) or set(receipt) != set(REGISTRY_CASE_EXECUTION_RECEIPT_SCHEMA["required"]):
            return False
        fields = OUTCOME_FIELDS + (INVARIANT_FIELDS if result["case_kind"] == "INVARIANT" else SCHEMA_FIELDS)
        expected_outcome = {name: result[name] for name in fields}
        return (
            receipt["receipt_kind"] == "REGISTRY_CASE_PROCESS_OBSERVATION"
            and receipt["command_id"] == invocation["executor_command_id"] == "LAB-RUN-REGISTRY-CASE"
            and receipt["invocation"] == {name: invocation[name] for name in BINDING_FIELDS}
            and receipt["argv"] == invocation["executor_argv"]
            and receipt["argv_binding"] == "EXISTING_RUNTIME_URI_BINDING"
            and isinstance(receipt["process_argv"], list) and bool(receipt["process_argv"])
            and all(isinstance(arg, str) and bool(arg) for arg in receipt["process_argv"])
            and receipt["execution_started"] is True
            and type(receipt["exit_code"]) is int and receipt["exit_code"] == 0
            and isinstance(receipt["stdout"], str) and isinstance(receipt["stderr"], str)
            and receipt["input_context"] == "ISOLATED_CONTRACT_FIXTURE"
            and json.dumps(receipt["outcome"], sort_keys=True) == json.dumps(expected_outcome, sort_keys=True)
        )
    except (KeyError, TypeError, ValueError):
        return False
