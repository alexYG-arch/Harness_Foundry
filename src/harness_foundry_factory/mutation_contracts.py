"""Bounded mutation preparation; a test error is never a killed invariant."""

from copy import deepcopy
from hashlib import sha256
import json
import re

from .contract_references import pointer_values
from .semantic_operator_catalog import MUTATION_FAILURE_DEPENDENCIES, MUTATION_FAILURE_DEPENDENCIES_BY_KIND


def invariant_failure_closure(invariant_id, *, artifact_kind=None):
    """Resolve the predeclared invariant dependency relation, not observed output."""
    closure, pending = set(), [invariant_id]
    while pending:
        current = pending.pop()
        if current not in closure:
            closure.add(current)
            pending.extend(MUTATION_FAILURE_DEPENDENCIES.get(current, ()))
            pending.extend(MUTATION_FAILURE_DEPENDENCIES_BY_KIND.get(artifact_kind, {}).get(current, ()))
    return sorted(closure)


def canonical_recomputations(schema, mutation_target):
    """Find non-target derived digests affected by a member edit."""
    result = []
    for contract in schema.get("x-invariant-contracts", {}).values():
        source = contract.get("parameters", {}).get("canonical_value_ref")
        target = contract.get("target_ref")
        if (contract.get("algorithm") == "CANONICAL_JSON_VALUE_HASH_V1"
                and isinstance(source, str) and isinstance(target, str)
                and mutation_target.startswith(source.rstrip("/") + "/")
                and target != mutation_target):
            result.append({"algorithm": "CANONICAL_JSON_VALUE_HASH_V1",
                           "source_ref": source, "target_ref": target})
    return sorted(result, key=lambda item: item["target_ref"])


def prepare_mutated_document(document, mutation_target, recomputations):
    """Rebuild only declared derived fields, never the field under test."""
    result = deepcopy(document)
    for step in recomputations:
        if step["target_ref"] == mutation_target or step["algorithm"] != "CANONICAL_JSON_VALUE_HASH_V1":
            raise ValueError("mutation target cannot be repaired by its own recipe")
        values = pointer_values(result, step["source_ref"])
        if len(values) != 1:
            raise ValueError("canonical derivation requires exactly one input value")
        digest = sha256(json.dumps(values[0], ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")).encode("utf-8")).hexdigest()
        parent_ref, _, field = step["target_ref"].rpartition("/")
        parents = pointer_values(result, parent_ref)
        if len(parents) != 1 or not isinstance(parents[0], dict):
            raise ValueError("derived field parent is not a single object")
        parents[0][field.replace("~1", "/").replace("~0", "~")] = digest
    return result


def classify_mutation_result(target_id, *, schema_passed, failed_invariants, execution_status,
                             allowed_failure_ids=None, artifact_kind=None):
    if execution_status != "COMPLETED":
        return "INCONCLUSIVE"
    if not schema_passed:
        return "SCHEMA_REJECTED_NOT_INVARIANT_EVIDENCE"
    allowed = {target_id} if allowed_failure_ids is None else set(allowed_failure_ids)
    if target_id not in allowed:
        return "INCONCLUSIVE"
    if allowed_failure_ids is not None and sorted(allowed) != invariant_failure_closure(target_id, artifact_kind=artifact_kind):
        return "INCONCLUSIVE"
    if target_id not in failed_invariants:
        return "TARGET_INVARIANT_NOT_REJECTED"
    if set(failed_invariants).issubset(allowed):
        return "EXPECTED_INVARIANT_REJECTION"
    return "NON_TARGET_INVARIANT_FAILURE"


def prepare_referenced_document_mutation(document, recipe, resolver):
    """Mutate referenced content in memory and rebind only its file digest.

    This separates manifest membership from manifest byte integrity. It does not
    claim a full-artifact counterexample; the caller must run all peer oracles.
    """
    bindings = {
        "MUTATE_REFERENCED_ASSET_DIGEST_AND_REBIND_MANIFEST": {
            "ref_pointer": "/render_input_manifest_ref", "sha256_pointer": "/render_input_manifest_sha256",
            "value_pointer": "/assets/0/asset_sha256", "replacement_rule": "DIFFERENT_VALID_SHA256"},
        "MUTATE_REFERENCED_FFPROBE_INPUT_AND_REBIND_RECEIPT": {
            "ref_pointer": "/ffprobe_receipt_ref", "sha256_pointer": "/ffprobe_receipt_sha256",
            "value_pointer": "/input_sha256", "replacement_rule": "DIFFERENT_VALID_SHA256"},
    }
    if recipe.get("strategy") not in bindings:
        raise ValueError("unsupported referenced-document mutation")
    step = recipe["referenced_document_mutation"]
    if step != bindings[recipe["strategy"]]:
        raise ValueError("unexpected referenced-document mutation binding")
    result = deepcopy(document)
    ref = pointer_values(result, step["ref_pointer"])[0]
    content = json.loads(resolver(ref))
    original = pointer_values(content, step["value_pointer"])[0]
    if not isinstance(original, str) or re.fullmatch(r"[0-9a-f]{64}", original) is None:
        raise ValueError("base asset digest is invalid")
    parent_ref, _, field = step["value_pointer"].rpartition("/")
    parent = pointer_values(content, parent_ref)[0] if parent_ref else content
    parent[field] = ("1" if original[0] == "0" else "0") + original[1:]
    mutated = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    result[step["sha256_pointer"].removeprefix("/")] = sha256(mutated).hexdigest()
    return result, {ref: mutated}
