"""Explicit collection domains and a pure relational reference interpreter.

Declarations are shared specification, not expected test results. Neither the
interpreter nor the shape checker imports the Producer or selects by rule ID.
Resolvers return documents/bytes and own IO and Job lease enforcement.
"""

from dataclasses import asdict, dataclass
import json
import re

from .contract_references import pointer_values


ALGORITHM = "COLLECTION_RELATION_V1"
SELF = "artifact://self"
CASE_MANIFEST = "candidate://validation/CASE_EXECUTION_MANIFEST.json"
REGISTRY = "candidate://validation/ORACLE_EVALUATOR_REGISTRY.json"
CASE_KEYS = ("/case_id",)


@dataclass(frozen=True)
class CollectionQuery:
    source: str
    rows: str
    values: str = ""
    group_by: tuple[str, ...] = ()
    row_key: tuple[str, ...] = ()
    where: tuple[tuple[str, str], ...] = ()
    same_job: bool = False
    value_fields: tuple[str, ...] = ()

    def record(self):
        return json.loads(json.dumps(asdict(self)))

    def operand_ref(self):
        pointer = self.rows + ("/*" + self.values if self.values else "")
        if self.source == SELF:
            return pointer
        return self.source + ("#" if self.source.startswith("candidate://") else "") + pointer


def local(rows, values="", *, grouped=False):
    return CollectionQuery(SELF, rows, values,
                           CASE_KEYS if grouped else (), CASE_KEYS if grouped else ())


def cases(file, rows, values, *, grouped=False):
    return CollectionQuery("candidate://validation/" + file, rows, values,
                           CASE_KEYS if grouped else (), CASE_KEYS if grouped else ())


def dependency(kind, rows, values=""):
    return CollectionQuery("dependency://" + kind, rows, values, same_job=True)


# Every member of the existing collection-equality family is declared here.
# Mutation edit locations are intentionally not inputs to these definitions.
COLLECTION_RELATIONS = {
    "MOTION_OBJECT_IDS_EQUAL_ASSET_OBJECT_IDS": (
        local("/motion_object_ids"), local("/asset_object_ids")),
    "SENTENCE_IDS_EQUAL_NARRATION_SCRIPT_SENTENCE_IDS": (
        local("/sentence_ids"), dependency("NARRATION_SCRIPT", "/sentences", "/sentence_id")),
    "AUDIO_ANCHOR_IDS_EQUAL_REFERENCED_ALIGNMENT_ANCHOR_IDS": (
        local("/audio_anchor_ids"), dependency("AUDIO_ALIGNMENT_RECEIPT", "/word_anchors", "/anchor_id")),
    "MOTION_CURVE_IDS_EQUAL_OBJECT_MOTION_SEGMENT_CURVE_IDS": (
        local("/motion_curve_ids"), local("/shots", "/objects/*/motion_segments/*/curve_id")),
    "RENDERED_SHOT_IDS_EQUAL_MOTION_IR_SHOT_IDS": (
        local("/rendered_shot_ids"), dependency("OBJECT_MOTION_IR", "/shots", "/shot_id")),
    "RENDERED_OBJECT_IDS_EQUAL_MOTION_IR_OBJECT_IDS": (
        local("/rendered_object_ids"), dependency("OBJECT_MOTION_IR", "/shots", "/objects/*/object_id")),
    "RENDERED_MOTION_CURVE_IDS_EQUAL_MOTION_IR_CURVE_IDS": (
        local("/rendered_motion_curve_ids"), dependency("OBJECT_MOTION_IR", "/motion_curve_ids")),
    "OBSERVED_MOTION_CURVE_IDS_EQUAL_MOTION_IR_CURVE_IDS": (
        local("/observed_motion_objects", "/motion_curve_ids/*"), dependency("OBJECT_MOTION_IR", "/motion_curve_ids")),
    "OBSERVED_MOTION_OBJECT_IDS_EQUAL_MOTION_IR_OBJECT_IDS": (
        local("/observed_motion_objects", "/object_id"), dependency("OBJECT_MOTION_IR", "/shots", "/objects/*/object_id")),
    "SHOT_SENTENCE_ID_UNION_EQUALS_TOP_LEVEL_SENTENCE_IDS": (
        local("/sentence_ids"), local("/shots", "/sentence_ids/*")),
    "SHOT_AUDIO_ANCHOR_ID_UNION_EQUALS_TOP_LEVEL_AUDIO_ANCHOR_IDS": (
        local("/audio_anchor_ids"), local("/shots", "/audio_anchor_ids/*")),
    "FIXTURE_RESULT_JOB_IDS_EQUAL_FROZEN_REPOSITORY_JOB_IDS": (
        local("/fixture_results", "/job_id"),
        cases("PUBLIC_SKILL_JOB_INTERFACE.json", "/frozen_certification_fixtures", "/job_id")),
    "FIXTURE_RESULT_SOURCE_IDS_EQUAL_FROZEN_REPOSITORY_SOURCE_IDS": (
        CollectionQuery(SELF, "/fixture_results", "/source_id", ("/job_id",), ("/job_id",)),
        CollectionQuery("candidate://validation/PUBLIC_SKILL_JOB_INTERFACE.json",
                        "/frozen_certification_fixtures", "/source_id", ("/job_id",), ("/job_id",))),
    "ACCEPTANCE_CASE_RESULT_IDS_EQUAL_FROZEN_ACCEPTANCE_CASE_IDS": (
        local("/acceptance_case_results", "/case_id"), cases("ACCEPTANCE_CASES.json", "/cases", "/case_id")),
    "ACCEPTANCE_CASE_RESULT_REFS_EQUAL_FROZEN_CASE_RESULT_REFS": (
        local("/acceptance_case_results", "/result_ref", grouped=True),
        cases("ACCEPTANCE_CASES.json", "/cases", "/result_ref", grouped=True)),
    "NEGATIVE_CASE_RESULT_IDS_EQUAL_COMPLETE_NEGATIVE_CASE_IDS": (
        local("/negative_case_results", "/case_id"), cases("NEGATIVE_CASES.json", "/cases", "/case_id")),
    "NEGATIVE_CASE_RESULT_REFS_EQUAL_FROZEN_CASE_RESULT_REFS": (
        local("/negative_case_results", "/result_ref", grouped=True),
        cases("NEGATIVE_CASES.json", "/cases", "/result_ref", grouped=True)),
    "NEGATIVE_MUTATION_VARIANT_RESULT_IDS_EQUAL_DECLARED_VARIANT_IDS": (
        local("/negative_case_results", "/mutation_variant_results/*/variant_id", grouped=True),
        cases("NEGATIVE_CASES.json", "/cases", "/input_fixture/mutation_variants/*/variant_id", grouped=True)),
    "INVARIANT_NEGATIVE_CASE_RESULT_IDS_EQUAL_REGISTRY_CASE_IDS": (
        local("/invariant_negative_case_results", "/case_id"), cases("ORACLE_EVALUATOR_REGISTRY.json", "/invariant_negative_case_matrix", "/case_id")),
    "SCHEMA_NATIVE_NEGATIVE_CASE_RESULT_IDS_EQUAL_REGISTRY_CASE_IDS": (
        local("/schema_native_negative_case_results", "/case_id"), cases("ORACLE_EVALUATOR_REGISTRY.json", "/schema_native_negative_case_matrix", "/case_id")),
    "EVERY_INVARIANT_RESULT_COVERS_EXACT_APPLICABLE_SCHEMA_SHA256S": (
        local("/invariant_negative_case_results", "/schema_instance_results/*/schema_sha256", grouped=True),
        cases("ORACLE_EVALUATOR_REGISTRY.json", "/invariant_negative_case_matrix", "/applicable_schema_sha256s/*", grouped=True)),
    "INVARIANT_NEGATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS": (
        CollectionQuery(SELF, "/invariant_negative_case_results", "/schema_instance_results/*",
                        CASE_KEYS, CASE_KEYS, value_fields=("/schema_sha256", "/result_ref")),
        CollectionQuery(CASE_MANIFEST, "/registry_case_invocations", "", CASE_KEYS,
                        ("/case_id", "/schema_sha256"), (("/case_kind", "INVARIANT"),),
                        value_fields=("/schema_sha256", "/result_ref"))),
    "SCHEMA_NATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS": (
        CollectionQuery(SELF, "/schema_native_negative_case_results", "/schema_instance_results/*",
                        CASE_KEYS, CASE_KEYS, value_fields=("/schema_sha256", "/result_ref")),
        CollectionQuery(CASE_MANIFEST, "/registry_case_invocations", "", CASE_KEYS,
                        ("/case_id", "/schema_sha256"), (("/case_kind", "SCHEMA_NATIVE"),),
                        value_fields=("/schema_sha256", "/result_ref"))),
}


def collection_contract_fields(name):
    left, right = COLLECTION_RELATIONS[name]
    return {
        "algorithm": ALGORITHM, "operand_refs": [left.operand_ref(), right.operand_ref()],
        "operand_types": ["array", "array"], "quantifier": "SINGLE",
        "subject_selector": left.rows, "cardinality": {"mode": "EXACT", "operand_count": 2, "subject": "ONE"},
        "branch_selector": {"mode": "ANY_JSON_SCHEMA_VALID_BRANCH"}, "join_keys": [],
        "parameters": {"comparison": "GROUPED_SET_EQUALITY" if left.group_by else "SET_EQUALITY",
                       "queries": [left.record(), right.record()], "operand_scopes": ["GLOBAL", "GLOBAL"]},
    }


def collection_query_pointers(query):
    """All fields read by a query, including keys, filters and Job ownership."""
    refs = [query["rows"]]
    refs += [query["rows"] + "/*" + ref for ref in (
        query["group_by"] + query["row_key"] + [w[0] for w in query["where"]]
        + ([query["values"]] if query["values"] else []))]
    refs += [query["rows"] + "/*" + query["values"] + ref for ref in query["value_fields"]]
    if query["same_job"]:
        refs.append("/job_id")
    return sorted(set(refs))


def collection_read_refs(contract):
    refs = set()
    for q in contract["parameters"]["queries"]:
        prefix = "" if q["source"] == SELF else q["source"] + ("#" if q["source"].startswith("candidate://") else "")
        refs.update(prefix + p for p in collection_query_pointers(q))
        if q["same_job"]:
            refs.add("/job_id")
    return sorted(refs)


def _pointer(value, *, empty=False, wildcard=True):
    return isinstance(value, str) and ((empty and value == "") or (
        value.startswith("/") and not re.search(r"~(?![01])", value)
        and (wildcard or "*" not in value)))


def collection_contract_errors(contract):
    """Validate the relational language, not its Producer or invariant ID."""
    if not isinstance(contract, dict):
        return ["COLLECTION_CONTRACT_INVALID"]
    p = contract.get("parameters")
    if not isinstance(p, dict) or set(p) != {"comparison", "queries", "operand_scopes"}:
        return ["COLLECTION_PARAMETERS_INVALID"]
    queries = p.get("queries")
    if not isinstance(queries, list) or len(queries) != 2:
        return ["COLLECTION_QUERY_INVALID"]
    # Preserve the public signature diagnostic when a legacy operator is
    # migrated to this language; domain/projection errors remain distinct.
    if isinstance(contract.get("operand_refs"), list) and len(contract["operand_refs"]) != 2:
        return ["INVARIANT_OPERATOR_ARITY_INVALID"]
    expected_fields = set(CollectionQuery.__dataclass_fields__)
    for q in queries:
        if not isinstance(q, dict) or set(q) != expected_fields:
            return ["COLLECTION_QUERY_INVALID"]
        source = q["source"]
        if (not isinstance(source, str) or not (source == SELF or source.startswith(("candidate://", "dependency://")))
                or "#" in source or not _pointer(q["rows"], wildcard=False)
                or not _pointer(q["values"], empty=True) or type(q["same_job"]) is not bool):
            return ["COLLECTION_QUERY_INVALID"]
        if q["same_job"] != source.startswith("dependency://"):
            return ["COLLECTION_JOB_SCOPE_INVALID"]
        for field in ("group_by", "row_key", "value_fields"):
            if (not isinstance(q[field], list) or any(not _pointer(k, wildcard=False) for k in q[field])
                    or len(set(q[field])) != len(q[field])):
                return ["COLLECTION_KEY_INVALID"]
        if (not isinstance(q["where"], list) or any(not isinstance(w, list) or len(w) != 2
                or not _pointer(w[0], wildcard=False) or not isinstance(w[1], str) for w in q["where"])):
            return ["COLLECTION_FILTER_INVALID"]
    grouped = bool(queries[0]["group_by"])
    if (grouped != bool(queries[1]["group_by"])
            or len(queries[0]["group_by"]) != len(queries[1]["group_by"])
            or len(queries[0]["value_fields"]) != len(queries[1]["value_fields"])
            or p["comparison"] != ("GROUPED_SET_EQUALITY" if grouped else "SET_EQUALITY")):
        return ["COLLECTION_GROUPING_INVALID"]
    expected_refs = [CollectionQuery(**q).operand_ref() for q in queries]
    if (contract.get("algorithm") != ALGORITHM or contract.get("operand_refs") != expected_refs
            or contract.get("operand_types") != ["array", "array"] or contract.get("quantifier") != "SINGLE"
            or contract.get("subject_selector") != queries[0]["rows"] or queries[0]["source"] != SELF
            or contract.get("cardinality") != {"mode": "EXACT", "operand_count": 2, "subject": "ONE"}
            or contract.get("branch_selector") != {"mode": "ANY_JSON_SCHEMA_VALID_BRANCH"}
            or contract.get("join_keys") != [] or p["operand_scopes"] != ["GLOBAL", "GLOBAL"]):
        return ["COLLECTION_PROJECTION_INVALID"]
    return []


def collection_definition_errors(name, contract):
    """Output-to-definition check; no regeneration/repair of the supplied output."""
    expected = collection_contract_fields(name)
    if (any(contract.get(key) != value for key, value in expected.items())
            or contract.get("branch_precondition", "ANY_JSON_SCHEMA_VALID_BRANCH") != "ANY_JSON_SCHEMA_VALID_BRANCH"):
        return ["COLLECTION_SEMANTIC_DEFINITION_MISMATCH"]
    return collection_contract_errors(contract)


def _one(doc, pointer):
    values = pointer_values(doc, pointer)
    if len(values) != 1:
        raise ValueError("expected one field")
    return values[0]


def _key(row, pointers):
    values = tuple(_one(row, p) for p in pointers)
    if any(not isinstance(v, str) or not v for v in values):
        raise ValueError("collection identifiers must be nonempty strings")
    return values


def _query(q, document, resolver):
    source = document if q["source"] == SELF else resolver(q["source"])
    if isinstance(source, bytes):
        source = json.loads(source)
    if not isinstance(source, dict):
        raise ValueError("expected a resolved JSON object")
    if q["same_job"] and (not isinstance(document.get("job_id"), str) or not document["job_id"]
                          or source.get("job_id") != document["job_id"]):
        raise ValueError("dependency does not belong to this Job")
    rows = _one(source, q["rows"])
    if not isinstance(rows, list):
        raise ValueError("row domain must be an array")
    result = {} if q["group_by"] else {(): set()}
    seen_rows = set()
    for row in rows:
        if any(_one(row, path) != value for path, value in q["where"]):
            continue
        group = _key(row, q["group_by"])
        if q["row_key"]:
            row_key = _key(row, q["row_key"])
            if row_key in seen_rows:
                raise ValueError("duplicate row identity")
            seen_rows.add(row_key)
        values = pointer_values(row, q["values"])
        if q["value_fields"]:
            values = [_key(v, q["value_fields"]) for v in values]
        elif any(not isinstance(v, str) or not v for v in values):
            raise ValueError("collection values must be nonempty identifiers")
        result.setdefault(group, set()).update(values)
    return result


def evaluate_collection_relation(contract, document, resolver=None):
    errors = collection_contract_errors(contract)
    failure = errors[0] if errors else None
    count = 0
    if not failure:
        try:
            left, right = [_query(q, document, resolver) for q in contract["parameters"]["queries"]]
            count = len(set(left) | set(right))
            if left != right:
                failure = "INVARIANT_PREDICATE_FALSE"
        except (KeyError, TypeError, ValueError, IndexError):
            failure = "INVARIANT_RUNTIME_OPERAND_RESOLUTION_FAILED"
    return {"passed": failure is None, "failure_code": failure, "evaluated_subject_count": count,
            "failed_subjects": [], "skipped": False}


# Read-only migration input for the known pre-relational compiler output.
# Not a second production definition. Unrecognized overrides are not discarded.
LEGACY_COLLECTION_FIELDS = {
    "SHOT_SENTENCE_ID_UNION_EQUALS_TOP_LEVEL_SENTENCE_IDS": {"algorithm":"ARRAY_UNION_SET_EQUALITY_V1","input_refs":["/shots/0/sentence_ids","/shots/*/sentence_ids","/sentence_ids"],"target_ref":"/shots/0/sentence_ids","operand_refs":["/shots/0/sentence_ids","/shots/*/sentence_ids","/sentence_ids"],"operand_types":["array","array","array"],"subject_selector":"/shots/0/sentence_ids","quantifier":"SINGLE","parameters":{"operand_scopes":["GLOBAL","GLOBAL","GLOBAL"]},"branch_selector":{"mode":"ANY_JSON_SCHEMA_VALID_BRANCH"},"join_keys":[]},
    "SHOT_AUDIO_ANCHOR_ID_UNION_EQUALS_TOP_LEVEL_AUDIO_ANCHOR_IDS": {"algorithm":"ARRAY_UNION_SET_EQUALITY_V1","input_refs":["/shots/0/audio_anchor_ids","/shots/*/audio_anchor_ids","/audio_anchor_ids"],"target_ref":"/shots/0/audio_anchor_ids","operand_refs":["/shots/0/audio_anchor_ids","/shots/*/audio_anchor_ids","/audio_anchor_ids"],"operand_types":["array","array","array"],"subject_selector":"/shots/0/audio_anchor_ids","quantifier":"SINGLE","parameters":{"operand_scopes":["GLOBAL","GLOBAL","GLOBAL"]},"branch_selector":{"mode":"ANY_JSON_SCHEMA_VALID_BRANCH"},"join_keys":[]},
    "OBSERVED_MOTION_OBJECT_IDS_EQUAL_MOTION_IR_OBJECT_IDS": {"algorithm":"QUANTIFIED_MOTION_OBJECT_SET_EQUALITY_V1","input_refs":["/observed_motion_objects/0/object_id","/observed_motion_objects/*/object_id","dependency://OBJECT_MOTION_IR/shots/*/objects/*/object_id"],"target_ref":"/observed_motion_objects/0/object_id","operand_refs":["/observed_motion_objects/0/object_id","/observed_motion_objects/*/object_id","dependency://OBJECT_MOTION_IR/shots/*/objects/*/object_id"],"operand_types":["scalar","array","array"],"subject_selector":"/observed_motion_objects/0/object_id","quantifier":"SINGLE","parameters":{"operand_scopes":["GLOBAL","GLOBAL","GLOBAL"]},"branch_selector":{"mode":"ANY_JSON_SCHEMA_VALID_BRANCH"},"join_keys":[]},
    "MOTION_OBJECT_IDS_EQUAL_ASSET_OBJECT_IDS": {"algorithm":"CANONICAL_VALUE_OR_SET_EQUALITY_V1","input_refs":["/motion_object_ids","/asset_object_ids"],"target_ref":"/motion_object_ids","operand_refs":["/motion_object_ids","/asset_object_ids"],"operand_types":["array","array"],"subject_selector":"/motion_object_ids","quantifier":"SINGLE","parameters":{"operand_scopes":["GLOBAL","GLOBAL"]},"branch_selector":{"mode":"ANY_JSON_SCHEMA_VALID_BRANCH"},"join_keys":[]},
    "SENTENCE_IDS_EQUAL_NARRATION_SCRIPT_SENTENCE_IDS": {"algorithm":"CANONICAL_VALUE_OR_SET_EQUALITY_V1","input_refs":["/sentence_ids","dependency://NARRATION_SCRIPT/sentences/*/sentence_id"],"target_ref":"/sentence_ids","operand_refs":["/sentence_ids","dependency://NARRATION_SCRIPT/sentences/*/sentence_id"],"operand_types":["array","array"],"subject_selector":"/sentence_ids","quantifier":"SINGLE","parameters":{"operand_scopes":["GLOBAL","GLOBAL"]},"branch_selector":{"mode":"ANY_JSON_SCHEMA_VALID_BRANCH"},"join_keys":[]},
    "FIXTURE_RESULT_JOB_IDS_EQUAL_FROZEN_REPOSITORY_JOB_IDS": {"algorithm":"CANONICAL_VALUE_OR_SET_EQUALITY_V1","input_refs":["/fixture_results/0/job_id","candidate://validation/PUBLIC_SKILL_JOB_INTERFACE.json#/frozen_certification_fixtures/*/job_id"],"target_ref":"/fixture_results/0/job_id","operand_refs":["/fixture_results/*/job_id","candidate://validation/PUBLIC_SKILL_JOB_INTERFACE.json#/frozen_certification_fixtures/*/job_id"],"operand_types":["array","array"],"subject_selector":"/fixture_results","quantifier":"SINGLE","parameters":{"operand_scopes":["GLOBAL","GLOBAL"]},"branch_selector":{"mode":"ANY_JSON_SCHEMA_VALID_BRANCH"},"join_keys":[]},
    "FIXTURE_RESULT_SOURCE_IDS_EQUAL_FROZEN_REPOSITORY_SOURCE_IDS": {"algorithm":"CANONICAL_VALUE_OR_SET_EQUALITY_V1","input_refs":["/fixture_results/0/source_id","candidate://validation/PUBLIC_SKILL_JOB_INTERFACE.json#/frozen_certification_fixtures/*/source_id"],"target_ref":"/fixture_results/0/source_id","operand_refs":["/fixture_results/*/source_id","candidate://validation/PUBLIC_SKILL_JOB_INTERFACE.json#/frozen_certification_fixtures/*/source_id"],"operand_types":["array","array"],"subject_selector":"/fixture_results","quantifier":"SINGLE","parameters":{"operand_scopes":["GLOBAL","GLOBAL"]},"branch_selector":{"mode":"ANY_JSON_SCHEMA_VALID_BRANCH"},"join_keys":[]},
    "ACCEPTANCE_CASE_RESULT_IDS_EQUAL_FROZEN_ACCEPTANCE_CASE_IDS": {"algorithm":"CANONICAL_VALUE_OR_SET_EQUALITY_V1","input_refs":["/acceptance_case_results/0/case_id","candidate://validation/ACCEPTANCE_CASES.json#/cases/*/case_id"],"target_ref":"/acceptance_case_results/0/case_id","operand_refs":["/acceptance_case_results/*/case_id","candidate://validation/ACCEPTANCE_CASES.json#/cases/*/case_id"],"operand_types":["array","array"],"subject_selector":"/acceptance_case_results","quantifier":"SINGLE","parameters":{"operand_scopes":["GLOBAL","GLOBAL"]},"branch_selector":{"mode":"ANY_JSON_SCHEMA_VALID_BRANCH"},"join_keys":[]},
    "ACCEPTANCE_CASE_RESULT_REFS_EQUAL_FROZEN_CASE_RESULT_REFS": {"algorithm":"CANONICAL_VALUE_OR_SET_EQUALITY_V1","input_refs":["/acceptance_case_results/0/result_ref","candidate://validation/ACCEPTANCE_CASES.json#/cases/*/result_ref"],"target_ref":"/acceptance_case_results/0/result_ref","operand_refs":["/acceptance_case_results/*/result_ref","candidate://validation/ACCEPTANCE_CASES.json#/cases/*/result_ref"],"operand_types":["array","array"],"subject_selector":"/acceptance_case_results","quantifier":"SINGLE","parameters":{"operand_scopes":["GLOBAL","GLOBAL"]},"branch_selector":{"mode":"ANY_JSON_SCHEMA_VALID_BRANCH"},"join_keys":[]},
    "NEGATIVE_CASE_RESULT_IDS_EQUAL_COMPLETE_NEGATIVE_CASE_IDS": {"algorithm":"CANONICAL_VALUE_OR_SET_EQUALITY_V1","input_refs":["/negative_case_results/0/case_id","candidate://validation/NEGATIVE_CASES.json#/cases/*/case_id"],"target_ref":"/negative_case_results/0/case_id","operand_refs":["/negative_case_results/*/case_id","candidate://validation/NEGATIVE_CASES.json#/cases/*/case_id"],"operand_types":["array","array"],"subject_selector":"/negative_case_results","quantifier":"SINGLE","parameters":{"operand_scopes":["GLOBAL","GLOBAL"]},"branch_selector":{"mode":"ANY_JSON_SCHEMA_VALID_BRANCH"},"join_keys":[]},
    "NEGATIVE_CASE_RESULT_REFS_EQUAL_FROZEN_CASE_RESULT_REFS": {"algorithm":"CANONICAL_VALUE_OR_SET_EQUALITY_V1","input_refs":["/negative_case_results/0/result_ref","candidate://validation/NEGATIVE_CASES.json#/cases/*/result_ref"],"target_ref":"/negative_case_results/0/result_ref","operand_refs":["/negative_case_results/*/result_ref","candidate://validation/NEGATIVE_CASES.json#/cases/*/result_ref"],"operand_types":["array","array"],"subject_selector":"/negative_case_results","quantifier":"SINGLE","parameters":{"operand_scopes":["GLOBAL","GLOBAL"]},"branch_selector":{"mode":"ANY_JSON_SCHEMA_VALID_BRANCH"},"join_keys":[]},
    "NEGATIVE_MUTATION_VARIANT_RESULT_IDS_EQUAL_DECLARED_VARIANT_IDS": {"algorithm":"CANONICAL_VALUE_OR_SET_EQUALITY_V1","input_refs":["/negative_case_results/0/mutation_variant_results/0/variant_id","candidate://validation/NEGATIVE_CASES.json#/cases/*/input_fixture/mutation_variants/*/variant_id"],"target_ref":"/negative_case_results/0/mutation_variant_results/0/variant_id","operand_refs":["/negative_case_results/*/mutation_variant_results/*/variant_id","candidate://validation/NEGATIVE_CASES.json#/cases/*/input_fixture/mutation_variants/*/variant_id"],"operand_types":["array","array"],"subject_selector":"/negative_case_results","quantifier":"SINGLE","parameters":{"operand_scopes":["GLOBAL","GLOBAL"]},"branch_selector":{"mode":"ANY_JSON_SCHEMA_VALID_BRANCH"},"join_keys":[]},
    "INVARIANT_NEGATIVE_CASE_RESULT_IDS_EQUAL_REGISTRY_CASE_IDS": {"algorithm":"CANONICAL_VALUE_OR_SET_EQUALITY_V1","input_refs":["/invariant_negative_case_results/0/case_id","candidate://validation/ORACLE_EVALUATOR_REGISTRY.json#/invariant_negative_case_matrix/*/case_id"],"target_ref":"/invariant_negative_case_results/0/case_id","operand_refs":["/invariant_negative_case_results/*/case_id","candidate://validation/ORACLE_EVALUATOR_REGISTRY.json#/invariant_negative_case_matrix/*/case_id"],"operand_types":["array","array"],"subject_selector":"/invariant_negative_case_results","quantifier":"SINGLE","parameters":{"operand_scopes":["GLOBAL","GLOBAL"]},"branch_selector":{"mode":"ANY_JSON_SCHEMA_VALID_BRANCH"},"join_keys":[]},
    "INVARIANT_NEGATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS": {"algorithm":"CANONICAL_VALUE_OR_SET_EQUALITY_V1","input_refs":["/invariant_negative_case_results/0/schema_instance_results/0/result_ref","candidate://validation/CASE_EXECUTION_MANIFEST.json#/registry_case_invocations/*/result_ref"],"target_ref":"/invariant_negative_case_results/0/schema_instance_results/0/result_ref","operand_refs":["/invariant_negative_case_results/*/schema_instance_results/*/result_ref","candidate://validation/CASE_EXECUTION_MANIFEST.json#/registry_case_invocations/*/result_ref"],"operand_types":["array","array"],"subject_selector":"/invariant_negative_case_results","quantifier":"SINGLE","parameters":{"operand_scopes":["GLOBAL","GLOBAL"]},"branch_selector":{"mode":"ANY_JSON_SCHEMA_VALID_BRANCH"},"join_keys":[]},
    "EVERY_INVARIANT_RESULT_COVERS_EXACT_APPLICABLE_SCHEMA_SHA256S": {"algorithm":"PER_CASE_SCHEMA_COVERAGE_V1","input_refs":["/invariant_negative_case_results","candidate://validation/ORACLE_EVALUATOR_REGISTRY.json#/invariant_negative_case_matrix"],"target_ref":"/invariant_negative_case_results/0/schema_instance_results/0/schema_sha256","operand_refs":["/invariant_negative_case_results","candidate://validation/ORACLE_EVALUATOR_REGISTRY.json#/invariant_negative_case_matrix"],"operand_types":["array","scalar"],"subject_selector":"/invariant_negative_case_results/*","quantifier":"FOR_ALL","parameters":{"join_field":"case_id","actual_schema_ids":"schema_instance_results/*/schema_sha256","expected_schema_ids":"applicable_schema_sha256s","operand_scopes":["GLOBAL","GLOBAL"]},"branch_selector":{"mode":"ANY_JSON_SCHEMA_VALID_BRANCH"},"join_keys":[]},
    "SCHEMA_NATIVE_NEGATIVE_CASE_RESULT_IDS_EQUAL_REGISTRY_CASE_IDS": {"algorithm":"CANONICAL_VALUE_OR_SET_EQUALITY_V1","input_refs":["/schema_native_negative_case_results/0/case_id","candidate://validation/ORACLE_EVALUATOR_REGISTRY.json#/schema_native_negative_case_matrix/*/case_id"],"target_ref":"/schema_native_negative_case_results/0/case_id","operand_refs":["/schema_native_negative_case_results/*/case_id","candidate://validation/ORACLE_EVALUATOR_REGISTRY.json#/schema_native_negative_case_matrix/*/case_id"],"operand_types":["array","array"],"subject_selector":"/schema_native_negative_case_results","quantifier":"SINGLE","parameters":{"operand_scopes":["GLOBAL","GLOBAL"]},"branch_selector":{"mode":"ANY_JSON_SCHEMA_VALID_BRANCH"},"join_keys":[]},
    "SCHEMA_NATIVE_RESULT_REFS_EQUAL_FROZEN_REGISTRY_RESULT_REFS": {"algorithm":"CANONICAL_VALUE_OR_SET_EQUALITY_V1","input_refs":["/schema_native_negative_case_results/0/schema_instance_results/0/result_ref","candidate://validation/CASE_EXECUTION_MANIFEST.json#/registry_case_invocations/*/result_ref"],"target_ref":"/schema_native_negative_case_results/0/schema_instance_results/0/result_ref","operand_refs":["/schema_native_negative_case_results/*/schema_instance_results/*/result_ref","candidate://validation/CASE_EXECUTION_MANIFEST.json#/registry_case_invocations/*/result_ref"],"operand_types":["array","array"],"subject_selector":"/schema_native_negative_case_results","quantifier":"SINGLE","parameters":{"operand_scopes":["GLOBAL","GLOBAL"]},"branch_selector":{"mode":"ANY_JSON_SCHEMA_VALID_BRANCH"},"join_keys":[]},
    "RENDERED_SHOT_IDS_EQUAL_MOTION_IR_SHOT_IDS": {"algorithm":"CANONICAL_VALUE_OR_SET_EQUALITY_V1","input_refs":["/rendered_shot_ids","dependency://OBJECT_MOTION_IR/shots/*/shot_id"],"target_ref":"/rendered_shot_ids","operand_refs":["/rendered_shot_ids","dependency://OBJECT_MOTION_IR/shots/*/shot_id"],"operand_types":["array","array"],"subject_selector":"/rendered_shot_ids","quantifier":"SINGLE","parameters":{"operand_scopes":["GLOBAL","GLOBAL"]},"branch_selector":{"mode":"ANY_JSON_SCHEMA_VALID_BRANCH"},"join_keys":[]},
    "RENDERED_OBJECT_IDS_EQUAL_MOTION_IR_OBJECT_IDS": {"algorithm":"CANONICAL_VALUE_OR_SET_EQUALITY_V1","input_refs":["/rendered_object_ids","dependency://OBJECT_MOTION_IR/shots/*/objects/*/object_id"],"target_ref":"/rendered_object_ids","operand_refs":["/rendered_object_ids","dependency://OBJECT_MOTION_IR/shots/*/objects/*/object_id"],"operand_types":["array","array"],"subject_selector":"/rendered_object_ids","quantifier":"SINGLE","parameters":{"operand_scopes":["GLOBAL","GLOBAL"]},"branch_selector":{"mode":"ANY_JSON_SCHEMA_VALID_BRANCH"},"join_keys":[]},
    "RENDERED_MOTION_CURVE_IDS_EQUAL_MOTION_IR_CURVE_IDS": {"algorithm":"CANONICAL_VALUE_OR_SET_EQUALITY_V1","input_refs":["/rendered_motion_curve_ids","dependency://OBJECT_MOTION_IR/motion_curve_ids"],"target_ref":"/rendered_motion_curve_ids","operand_refs":["/rendered_motion_curve_ids","dependency://OBJECT_MOTION_IR/motion_curve_ids"],"operand_types":["array","array"],"subject_selector":"/rendered_motion_curve_ids","quantifier":"SINGLE","parameters":{"operand_scopes":["GLOBAL","GLOBAL"]},"branch_selector":{"mode":"ANY_JSON_SCHEMA_VALID_BRANCH"},"join_keys":[]},
    "OBSERVED_MOTION_CURVE_IDS_EQUAL_MOTION_IR_CURVE_IDS": {"algorithm":"CANONICAL_VALUE_OR_SET_EQUALITY_V1","input_refs":["/observed_motion_objects/0/motion_curve_ids/0","dependency://OBJECT_MOTION_IR/motion_curve_ids"],"target_ref":"/observed_motion_objects/0/motion_curve_ids/0","operand_refs":["/observed_motion_objects/*/motion_curve_ids/*","dependency://OBJECT_MOTION_IR/motion_curve_ids"],"operand_types":["array","array"],"subject_selector":"/observed_motion_objects","quantifier":"SINGLE","parameters":{"operand_scopes":["GLOBAL","GLOBAL"]},"branch_selector":{"mode":"ANY_JSON_SCHEMA_VALID_BRANCH"},"join_keys":[]},
    "AUDIO_ANCHOR_IDS_EQUAL_REFERENCED_ALIGNMENT_ANCHOR_IDS": {"algorithm":"CANONICAL_VALUE_OR_SET_EQUALITY_V1","input_refs":["/audio_anchor_ids","dependency://AUDIO_ALIGNMENT_RECEIPT/word_anchors/*/anchor_id"],"target_ref":"/audio_anchor_ids","operand_refs":["/audio_anchor_ids","dependency://AUDIO_ALIGNMENT_RECEIPT/word_anchors/*/anchor_id"],"operand_types":["array","array"],"subject_selector":"/audio_anchor_ids","quantifier":"SINGLE","parameters":{"operand_scopes":["GLOBAL","GLOBAL"]},"branch_selector":{"mode":"ANY_JSON_SCHEMA_VALID_BRANCH"},"join_keys":[]},
    "MOTION_CURVE_IDS_EQUAL_OBJECT_MOTION_SEGMENT_CURVE_IDS": {"algorithm":"CANONICAL_VALUE_OR_SET_EQUALITY_V1","input_refs":["/motion_curve_ids","/shots/*/objects/*/motion_segments/*/curve_id"],"target_ref":"/motion_curve_ids","operand_refs":["/motion_curve_ids","/shots/*/objects/*/motion_segments/*/curve_id"],"operand_types":["array","array"],"subject_selector":"/motion_curve_ids","quantifier":"SINGLE","parameters":{"operand_scopes":["GLOBAL","GLOBAL"]},"branch_selector":{"mode":"ANY_JSON_SCHEMA_VALID_BRANCH"},"join_keys":[]},
}
