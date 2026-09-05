"""Typed invariant contracts and a small independent reference evaluator.

This module deliberately does not import the Foundry Producer or Validator.
An invariant's behavior is declared by its contract fields; the invariant ID is
only an identity and is never inspected to choose an algorithm or quantifier.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Callable, Mapping, Sequence


SUPPORTED_OPERAND_TYPES = frozenset(
    {"scalar", "array", "object", "ref", "sha256"}
)
SUPPORTED_QUANTIFIERS = frozenset(
    {"SINGLE", "FOR_ALL", "EXISTS", "PAIRWISE"}
)
SUPPORTED_ALGORITHMS = frozenset(
    {
        "EXACT_EQUALITY_V1",
        "CANONICAL_VALUE_OR_SET_EQUALITY_V1",
        "SET_EQUALITY_V1",
        "HASH_AND_BYTE_LINEAGE_V1",
        "PAIRED_BYTE_HASH_LINEAGE_V1",
        "EXACT_ARRAY_CARDINALITY_COMPARISON_V1",
        "ORDERED_NUMERIC_PREDICATE_V1",
        "DECLARED_REFERENCE_RESOLUTION_V1",
        "MATERIALIZED_ASSET_AUTHORIZATION_V1",
        "ALL_VALUES_EQUAL_V1",
    }
)
SUPPORTED_NUMERIC_RELATIONS = frozenset({"LT", "LTE", "EQ", "NE", "GTE", "GT", "ABS_LTE"})

REQUIRED_CONTRACT_FIELDS = frozenset(
    {
        "algorithm",
        "operand_refs",
        "operand_types",
        "cardinality",
        "quantifier",
        "subject_selector",
        "branch_selector",
        "join_keys",
        "parameters",
    }
)

Resolver = Callable[[str], Any]


def registered_operator_findings(contract, *, location="invariant_contract"):
    """Operator signatures apply even when input resolution belongs to the Lab.

    External URI resolution is not implemented by the local JSON-pointer kernel;
    it must not suppress arity, type, or numeric-relation errors of that kernel's
    registered operators.
    """
    if contract.get("algorithm") not in SUPPORTED_ALGORITHMS:
        return []
    codes = {"INVARIANT_OPERAND_ARITY_INVALID", "INVARIANT_ALGORITHM_TYPE_MISMATCH",
             "INVARIANT_NUMERIC_PARAMETERS_INCOMPLETE", "INVARIANT_THRESHOLD_OPERAND_CONFLICT"}
    return [finding for finding in validate_invariant_contract_v1(contract, location=location)
            if finding["failure_code"] in codes]


def _finding(code: str, location: str, message: str) -> dict[str, str]:
    return {"failure_code": code, "location": location, "message": message}


def _is_json_pointer(value: Any, *, allow_wildcard: bool = False) -> bool:
    if not isinstance(value, str) or not value.startswith("/"):
        return False
    for segment in value.split("/")[1:]:
        if segment == "*" and allow_wildcard:
            continue
        index = 0
        while index < len(segment):
            if segment[index] != "~":
                index += 1
                continue
            if index + 1 >= len(segment) or segment[index + 1] not in "01":
                return False
            index += 2
    return True


def _decode_segment(segment: str) -> str:
    return segment.replace("~1", "/").replace("~0", "~")


def _schema_at_pointer(
    schema: Mapping[str, Any], pointer: str
) -> Mapping[str, Any] | None:
    current: Any = schema
    for raw_segment in pointer.split("/")[1:]:
        segment = _decode_segment(raw_segment)
        if not isinstance(current, Mapping):
            return None
        if segment in {"*", "-1"} or segment.isdigit():
            current = current.get("items")
        else:
            properties = current.get("properties")
            current = properties.get(segment) if isinstance(properties, Mapping) else None
        if current is None:
            return None
    return current if isinstance(current, Mapping) else None


def _declared_type_matches(
    declared_type: str, schema_node: Mapping[str, Any]
) -> bool:
    schema_type = schema_node.get("type")
    if isinstance(schema_type, list):
        schema_types = set(schema_type)
    elif isinstance(schema_type, str):
        schema_types = {schema_type}
    else:
        schema_types = set()
    if not schema_types and "const" in schema_node:
        const_value = schema_node["const"]
        if isinstance(const_value, bool):
            schema_types = {"boolean"}
        elif isinstance(const_value, str):
            schema_types = {"string"}
        elif isinstance(const_value, int):
            schema_types = {"integer", "number"}
        elif isinstance(const_value, float):
            schema_types = {"number"}
        elif isinstance(const_value, list):
            schema_types = {"array"}
        elif isinstance(const_value, Mapping):
            schema_types = {"object"}
        elif const_value is None:
            schema_types = {"null"}
    if declared_type == "array":
        return "array" in schema_types
    if declared_type == "object":
        return "object" in schema_types
    if declared_type in {"ref", "sha256"}:
        return "string" in schema_types
    return bool(schema_types.intersection({"string", "number", "integer", "boolean", "null"}))


def _validate_branch_selector(
    selector: Any, *, location: str
) -> list[dict[str, str]]:
    if not isinstance(selector, Mapping):
        return [
            _finding(
                "INVARIANT_BRANCH_SELECTOR_INVALID",
                location,
                "branch_selector must be an object",
            )
        ]
    mode = selector.get("mode")
    if mode == "ANY_JSON_SCHEMA_VALID_BRANCH":
        return [] if set(selector) == {"mode"} else [
            _finding(
                "INVARIANT_BRANCH_SELECTOR_INVALID",
                location,
                "ANY branch selector may contain only mode",
            )
        ]
    if mode == "REQUIRE_DISCRIMINATOR_IN":
        if (_is_json_pointer(selector.get("discriminator_ref"), allow_wildcard=True)
                and isinstance(selector.get("values"), list) and selector["values"]
                and all(isinstance(value, str) for value in selector["values"])):
            return []
        return [_finding("INVARIANT_BRANCH_SELECTOR_INVALID", location,
                         "branch membership requires a pointer and nonempty string values")]
    if mode != "REQUIRE_DISCRIMINATOR_CONST":
        return [
            _finding(
                "INVARIANT_BRANCH_SELECTOR_INVALID",
                location,
                "unsupported branch selector mode",
            )
        ]
    discriminator_ref = selector.get("discriminator_ref")
    if (
        not _is_json_pointer(discriminator_ref)
        or "const" not in selector
        or isinstance(selector.get("const"), (Mapping, list))
    ):
        return [
            _finding(
                "INVARIANT_BRANCH_SELECTOR_INVALID",
                location,
                "discriminator branch requires a JSON Pointer and scalar const",
            )
        ]
    return []


def _validate_join_keys(
    join_keys: Any, *, location: str
) -> list[dict[str, str]]:
    if not isinstance(join_keys, list):
        return [
            _finding(
                "INVARIANT_JOIN_KEY_INVALID",
                location,
                "join_keys must be a list",
            )
        ]
    findings: list[dict[str, str]] = []
    for index, item in enumerate(join_keys):
        item_location = f"{location}/{index}"
        if not isinstance(item, Mapping) or set(item) != {"left_ref", "right_ref"}:
            findings.append(
                _finding(
                    "INVARIANT_JOIN_KEY_INVALID",
                    item_location,
                    "join key must contain exactly left_ref and right_ref",
                )
            )
            continue
        if not all(_is_json_pointer(item.get(field)) for field in ("left_ref", "right_ref")):
            findings.append(
                _finding(
                    "INVARIANT_JOIN_KEY_INVALID",
                    item_location,
                    "join key references must be relative JSON Pointers",
                )
            )
    return findings


def validate_invariant_contract_v1(
    contract: Any,
    *,
    schema: Mapping[str, Any] | None = None,
    location: str = "invariant_contract",
) -> list[dict[str, str]]:
    """Statically validate one explicit typed invariant contract.

    The function is pure and intentionally accepts no invariant ID.  It cannot
    infer semantic behavior from an identifier's spelling.
    """

    if not isinstance(contract, Mapping):
        return [
            _finding(
                "INVARIANT_CONTRACT_INVALID",
                location,
                "contract must be an object",
            )
        ]
    findings: list[dict[str, str]] = []
    missing = sorted(REQUIRED_CONTRACT_FIELDS.difference(contract))
    for field in missing:
        findings.append(
            _finding(
                "INVARIANT_CONTRACT_REQUIRED_FIELD_MISSING",
                f"{location}/{field}",
                f"required field is missing: {field}",
            )
        )
    if missing:
        return findings

    algorithm = contract.get("algorithm")
    if algorithm not in SUPPORTED_ALGORITHMS:
        findings.append(
            _finding(
                "INVARIANT_ALGORITHM_UNSUPPORTED",
                f"{location}/algorithm",
                f"unsupported algorithm: {algorithm}",
            )
        )

    operand_refs = contract.get("operand_refs")
    operand_types = contract.get("operand_types")
    if not isinstance(operand_refs, list) or not operand_refs:
        findings.append(
            _finding(
                "INVARIANT_OPERAND_REF_INVALID",
                f"{location}/operand_refs",
                "operand_refs must be a non-empty list",
            )
        )
        operand_refs = []
    if not isinstance(operand_types, list) or len(operand_types) != len(operand_refs):
        findings.append(
            _finding(
                "INVARIANT_OPERAND_TYPE_INVALID",
                f"{location}/operand_types",
                "operand_types must align one-to-one with operand_refs",
            )
        )
        operand_types = []
    for index, operand_ref in enumerate(operand_refs):
        if not _is_json_pointer(operand_ref, allow_wildcard=True):
            findings.append(
                _finding(
                    "INVARIANT_OPERAND_REF_INVALID",
                    f"{location}/operand_refs/{index}",
                    "operand reference must be a JSON Pointer",
                )
            )
            continue
        if schema is not None:
            node = _schema_at_pointer(schema, operand_ref)
            if node is None:
                findings.append(
                    _finding(
                        "INVARIANT_OPERAND_REF_UNRESOLVED",
                        f"{location}/operand_refs/{index}",
                        f"schema does not declare {operand_ref}",
                    )
                )
            elif (
                index < len(operand_types)
                and not (
                    operand_types[index] == "array" and "*" in operand_ref
                )
                and not _declared_type_matches(operand_types[index], node)
            ):
                findings.append(
                    _finding(
                        "INVARIANT_OPERAND_TYPE_MISMATCH",
                        f"{location}/operand_types/{index}",
                        f"declared type {operand_types[index]} is incompatible with schema",
                    )
                )
    for index, operand_type in enumerate(operand_types):
        if operand_type not in SUPPORTED_OPERAND_TYPES:
            findings.append(
                _finding(
                    "INVARIANT_OPERAND_TYPE_INVALID",
                    f"{location}/operand_types/{index}",
                    f"unsupported operand type: {operand_type}",
                )
            )

    cardinality = contract.get("cardinality")
    if (
        not isinstance(cardinality, Mapping)
        or cardinality.get("mode") != "EXACT"
        or not isinstance(cardinality.get("operand_count"), int)
        or isinstance(cardinality.get("operand_count"), bool)
        or cardinality.get("operand_count") < 1
        or cardinality.get("subject") not in {"ONE", "MANY"}
    ):
        findings.append(
            _finding(
                "INVARIANT_CARDINALITY_INVALID",
                f"{location}/cardinality",
                "cardinality requires mode=EXACT, positive operand_count, and subject ONE or MANY",
            )
        )
    elif cardinality["operand_count"] != len(operand_refs):
        findings.append(
            _finding(
                "INVARIANT_OPERAND_ARITY_INVALID",
                f"{location}/cardinality/operand_count",
                "declared operand_count does not equal operand_refs length",
            )
        )

    quantifier = contract.get("quantifier")
    selector = contract.get("subject_selector")
    scopes = contract.get("parameters", {}).get("operand_scopes") if isinstance(
        contract.get("parameters"), Mapping) else None
    if scopes is not None and (
        not isinstance(scopes, list) or len(scopes) != len(operand_refs)
        or any(scope not in {"SUBJECT", "GLOBAL"} for scope in scopes)
    ):
        findings.append(_finding("INVARIANT_OPERAND_SCOPE_INVALID", location,
                                 "scopes must align with operand references"))
        scopes = None
    if quantifier not in SUPPORTED_QUANTIFIERS:
        findings.append(
            _finding(
                "INVARIANT_QUANTIFIER_INVALID",
                f"{location}/quantifier",
                f"unsupported quantifier: {quantifier}",
            )
        )
    if not _is_json_pointer(selector, allow_wildcard=True):
        findings.append(
            _finding(
                "INVARIANT_QUANTIFIER_SELECTOR_MISMATCH",
                f"{location}/subject_selector",
                "subject_selector must be a JSON Pointer",
            )
        )
    else:
        many = quantifier in {"FOR_ALL", "EXISTS", "PAIRWISE"}
        if many and "*" in selector:
            prefix = selector[:selector.rfind("*") + 1]
            subject_refs = [ref for index, ref in enumerate(operand_refs)
                            if isinstance(ref, str) and
                            (scopes[index] == "SUBJECT" if scopes else "*" in ref)]
            if contract.get("algorithm") in {"HASH_AND_BYTE_LINEAGE_V1", "PAIRED_BYTE_HASH_LINEAGE_V1"}:
                # A ref/hash vector is explicitly positional. Its companion
                # cardinality predicate checks equal lengths; retain indices.
                subject_refs = ["/".join(part[:-5] + "_sha256s" if part.endswith("_refs") else part
                                         for part in ref.split("/")) for ref in subject_refs]
            if not subject_refs or any(
                not (ref == prefix or ref.startswith(prefix + "/"))
                for ref in subject_refs
            ):
                findings.append(_finding("INVARIANT_SUBJECT_OPERAND_UNBOUND", location,
                                         "quantified operands must bind the selected member"))
        if many != ("*" in selector):
            findings.append(
                _finding(
                    "INVARIANT_QUANTIFIER_SELECTOR_MISMATCH",
                    f"{location}/subject_selector",
                    "collection quantifiers require a wildcard; SINGLE forbids it",
                )
            )
        if isinstance(cardinality, Mapping) and cardinality.get("subject") != (
            "MANY" if many else "ONE"
        ):
            findings.append(
                _finding(
                    "INVARIANT_CARDINALITY_INVALID",
                    f"{location}/cardinality/subject",
                    "subject cardinality does not match quantifier",
                )
            )
        if schema is not None and _schema_at_pointer(schema, selector) is None:
            findings.append(
                _finding(
                    "INVARIANT_SUBJECT_SELECTOR_UNRESOLVED",
                    f"{location}/subject_selector",
                    f"schema does not declare {selector}",
                )
            )

    findings.extend(
        _validate_branch_selector(
            contract.get("branch_selector"), location=f"{location}/branch_selector"
        )
    )
    branch_selector = contract.get("branch_selector")
    if (
        schema is not None
        and isinstance(branch_selector, Mapping)
        and branch_selector.get("mode") in {"REQUIRE_DISCRIMINATOR_CONST", "REQUIRE_DISCRIMINATOR_IN"}
        and _is_json_pointer(branch_selector.get("discriminator_ref"), allow_wildcard=True)
        and _schema_at_pointer(schema, str(branch_selector["discriminator_ref"])) is None
    ):
        findings.append(
            _finding(
                "INVARIANT_BRANCH_SELECTOR_UNRESOLVED",
                f"{location}/branch_selector/discriminator_ref",
                "schema does not declare the branch discriminator",
            )
        )
    findings.extend(
        _validate_join_keys(contract.get("join_keys"), location=f"{location}/join_keys")
    )

    parameters = contract.get("parameters")
    if not isinstance(parameters, Mapping):
        findings.append(
            _finding(
                "INVARIANT_PARAMETERS_INVALID",
                f"{location}/parameters",
                "parameters must be an object",
            )
        )
        parameters = {}

    arity_by_algorithm = {
        "EXACT_EQUALITY_V1": {2},
        "CANONICAL_VALUE_OR_SET_EQUALITY_V1": {2},
        "SET_EQUALITY_V1": {2},
        "HASH_AND_BYTE_LINEAGE_V1": {2},
        "PAIRED_BYTE_HASH_LINEAGE_V1": {4, 6, 8},
        "EXACT_ARRAY_CARDINALITY_COMPARISON_V1": {2},
        "ORDERED_NUMERIC_PREDICATE_V1": {1, 2},
        "DECLARED_REFERENCE_RESOLUTION_V1": {1},
        "MATERIALIZED_ASSET_AUTHORIZATION_V1": {2},
        "ALL_VALUES_EQUAL_V1": {3, 4},
    }
    if algorithm in arity_by_algorithm and len(operand_refs) not in arity_by_algorithm[algorithm]:
        findings.append(
            _finding(
                "INVARIANT_OPERAND_ARITY_INVALID",
                f"{location}/operand_refs",
                f"{algorithm} does not accept {len(operand_refs)} operands",
            )
        )

    types = tuple(operand_types)
    type_mismatch = False
    if algorithm == "EXACT_EQUALITY_V1" and len(types) == 2:
        type_mismatch = types[0] != types[1]
    elif algorithm == "CANONICAL_VALUE_OR_SET_EQUALITY_V1" and len(types) == 2:
        type_mismatch = types[0] != types[1]
    elif algorithm == "SET_EQUALITY_V1" and len(types) == 2:
        type_mismatch = types != ("array", "array")
    elif algorithm == "HASH_AND_BYTE_LINEAGE_V1" and len(types) == 2:
        type_mismatch = set(types) != {"ref", "sha256"}
    elif algorithm == "PAIRED_BYTE_HASH_LINEAGE_V1":
        type_mismatch = len(types) % 2 != 0 or any(
            set(types[i:i+2]) != {"ref", "sha256"} for i in range(0, len(types), 2)
        )
    elif algorithm == "EXACT_ARRAY_CARDINALITY_COMPARISON_V1" and len(types) == 2:
        type_mismatch = types != ("array", "array")
    elif algorithm == "ORDERED_NUMERIC_PREDICATE_V1":
        type_mismatch = bool(types) and any(value != "scalar" for value in types)
    elif algorithm == "DECLARED_REFERENCE_RESOLUTION_V1" and len(types) == 1:
        type_mismatch = types != ("ref",)
    elif algorithm == "MATERIALIZED_ASSET_AUTHORIZATION_V1":
        type_mismatch = types != ("object", "scalar")
    elif algorithm == "ALL_VALUES_EQUAL_V1":
        type_mismatch = len(set(types)) != 1
    if type_mismatch:
        findings.append(
            _finding(
                "INVARIANT_ALGORITHM_TYPE_MISMATCH",
                f"{location}/operand_types",
                "operand types are incompatible with the declared algorithm",
            )
        )

    if algorithm == "ORDERED_NUMERIC_PREDICATE_V1":
        if len(operand_refs) != 1 and "threshold" in parameters:
            findings.append(_finding(
                "INVARIANT_THRESHOLD_OPERAND_CONFLICT", f"{location}/operand_refs",
                "a threshold predicate must have one operand; two operands would ignore the threshold",
            ))
        relation = parameters.get("relation")
        threshold_invalid = False
        if len(operand_refs) == 1:
            try:
                threshold = _decimal(parameters["threshold"])
                threshold_invalid = not threshold.is_finite()
            except (InvalidOperation, KeyError, ValueError):
                threshold_invalid = True
        try:
            tolerance = _decimal(parameters.get("absolute_tolerance", 0))
            tolerance_invalid = not tolerance.is_finite() or tolerance < 0
        except (InvalidOperation, ValueError):
            tolerance_invalid = True
        if (
            relation not in SUPPORTED_NUMERIC_RELATIONS
            or not isinstance(parameters.get("unit"), str)
            or not parameters.get("unit")
            or threshold_invalid
            or tolerance_invalid
        ):
            findings.append(
                _finding(
                    "INVARIANT_NUMERIC_PARAMETERS_INCOMPLETE",
                    f"{location}/parameters",
                    "numeric predicate requires relation, unit, and a threshold for one operand",
                )
            )
    if (
        algorithm in {"SET_EQUALITY_V1", "CANONICAL_VALUE_OR_SET_EQUALITY_V1"}
        and parameters.get("member_type") == "object"
        and not contract.get("join_keys")
    ):
        findings.append(
            _finding(
                "INVARIANT_JOIN_KEY_REQUIRED",
                f"{location}/join_keys",
                "object collection equality requires explicit join keys",
            )
        )
    if quantifier == "PAIRWISE" and len(operand_refs) != 2:
        findings.append(
            _finding(
                "INVARIANT_OPERAND_ARITY_INVALID",
                f"{location}/operand_refs",
                "PAIRWISE evaluation requires exactly two operands",
            )
        )
    return findings


def _resolve_pointer(document: Any, pointer: str) -> Any:
    current = document
    for raw_segment in pointer.split("/")[1:]:
        segment = _decode_segment(raw_segment)
        if isinstance(current, list):
            try:
                current = current[int(segment)]
            except (ValueError, IndexError) as exc:
                raise KeyError(pointer) from exc
        elif isinstance(current, Mapping) and segment in current:
            current = current[segment]
        else:
            raise KeyError(pointer)
    return current


def _expand_pointer(document: Any, pointer: str) -> list[tuple[str, Any]]:
    results: list[tuple[list[str], Any]] = [([], document)]
    for raw_segment in pointer.split("/")[1:]:
        segment = _decode_segment(raw_segment)
        next_results: list[tuple[list[str], Any]] = []
        for concrete, current in results:
            if segment == "*":
                if isinstance(current, list):
                    next_results.extend(
                        (concrete + [str(index)], value)
                        for index, value in enumerate(current)
                    )
                elif isinstance(current, Mapping):
                    next_results.extend(
                        (concrete + [str(key)], current[key])
                        for key in sorted(current, key=str)
                    )
                continue
            if isinstance(current, list):
                try:
                    next_results.append((concrete + [segment], current[int(segment)]))
                except (ValueError, IndexError):
                    continue
            elif isinstance(current, Mapping) and segment in current:
                next_results.append((concrete + [segment], current[segment]))
        results = next_results
    return [("/" + "/".join(path), value) for path, value in results]


def _wildcard_values(template: str, concrete: str) -> list[str]:
    template_segments = template.split("/")[1:]
    concrete_segments = concrete.split("/")[1:]
    return [
        concrete_segments[index]
        for index, segment in enumerate(template_segments)
        if segment == "*"
    ]


def _substitute_wildcards(pointer: str, values: Sequence[str]) -> str:
    segments = pointer.split("/")
    value_index = 0
    for index, segment in enumerate(segments):
        if segment != "*":
            continue
        if value_index >= len(values):
            raise KeyError(pointer)
        segments[index] = values[value_index]
        value_index += 1
    return "/".join(segments)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _materialized_asset_authorization(asset, job_id, resolver):
    """Check authorization at the recorded execution time, not review wall time.

    This validates evidence only; it never grants or consumes authorization.
    Generation-receipt byte integrity has its own existing invariant.
    """
    if resolver is None:
        return False, "INVARIANT_REFERENCE_RESOLVER_REQUIRED"
    try:
        authorization = json.loads(resolver(asset["generation_authorization_ref"]))
        receipt = json.loads(resolver(asset["generation_receipt_ref"]))
        scope = authorization["exact_scope"]
        fields = ("target_skill_id", "job_id", "commit_sha", "input_manifest_sha256", "environment_id",
                  "environment_manifest_ref", "environment_manifest_sha256", "output_root_ref", "output_manifest_sha256")
        issued, executed, expires = [datetime.fromisoformat(value.replace("Z", "+00:00")) for value in (
            authorization["issued_at"], receipt["executed_at"], authorization["expires_at"])]
        passed = (
            authorization["status"] == "GRANTED"
            and authorization["authorization_class"] == "CODEX_IMAGE_GENERATION_AUTHORIZATION"
            and authorization["issuer_role"] == "HUMAN"
            and authorization["one_time_use"] is True
            and isinstance(authorization["authorization_id"], str) and bool(authorization["authorization_id"])
            and receipt["authorization_id"] == authorization["authorization_id"]
            and type(receipt["authorization_consumption_count"]) is int
            and receipt["authorization_consumption_count"] == 1
            and receipt["status"] == "PASS"
            and isinstance(scope, dict) and set(scope) == set(fields)
            and all(isinstance(scope[field], str) and bool(scope[field]) for field in fields)
            and scope == receipt["exact_scope"] and scope["job_id"] == job_id
            and all(value.tzinfo is not None for value in (issued, executed, expires))
            and issued <= executed < expires
            and receipt["output_ref"] == asset["asset_ref"]
            and receipt["output_sha256"] == asset["asset_sha256"]
        )
        return passed, None
    except (KeyError, TypeError, ValueError, AttributeError):
        return False, "INVARIANT_AUTHORIZATION_EVIDENCE_INVALID"


def _canonical_set(
    value: Any,
    join_keys: Sequence[Mapping[str, str]],
    *,
    side: str,
) -> set[str]:
    if not isinstance(value, list):
        raise TypeError("set operand must be an array")
    if not join_keys:
        return {_canonical_json(item) for item in value}
    projected: set[str] = set()
    for item in value:
        key_values = []
        for pair in join_keys:
            key_ref = str(pair[f"{side}_ref"])
            key_values.append(_resolve_pointer(item, key_ref))
        projected.add(_canonical_json(key_values))
    return projected


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise InvalidOperation
    return Decimal(str(value))


def _runtime_type_matches(value: Any, declared_type: str) -> bool:
    if declared_type == "array":
        return isinstance(value, list)
    if declared_type == "object":
        return isinstance(value, Mapping)
    if declared_type == "ref":
        return isinstance(value, str) and bool(value)
    if declared_type == "sha256":
        return bool(
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )
    return not isinstance(value, (list, Mapping))


def _evaluate_values(
    algorithm: str,
    values: Sequence[Any],
    types: Sequence[str],
    parameters: Mapping[str, Any],
    join_keys: Sequence[Mapping[str, str]],
    resolver: Resolver | None,
) -> tuple[bool, str | None]:
    if len(values) != len(types) or any(
        not _runtime_type_matches(value, declared_type)
        for value, declared_type in zip(values, types)
    ):
        return False, "INVARIANT_RUNTIME_OPERAND_TYPE_MISMATCH"
    if algorithm == "EXACT_EQUALITY_V1":
        return _canonical_json(values[0]) == _canonical_json(values[1]), None
    if algorithm == "CANONICAL_VALUE_OR_SET_EQUALITY_V1":
        if types[0] == "array":
            return _canonical_set(values[0], join_keys, side="left") == _canonical_set(
                values[1], join_keys, side="right"
            ), None
        return _canonical_json(values[0]) == _canonical_json(values[1]), None
    if algorithm == "SET_EQUALITY_V1":
        return _canonical_set(values[0], join_keys, side="left") == _canonical_set(
            values[1], join_keys, side="right"
        ), None
    if algorithm == "HASH_AND_BYTE_LINEAGE_V1":
        if resolver is None:
            return False, "INVARIANT_BYTE_RESOLVER_REQUIRED"
        digest_index = types.index("sha256")
        ref_index = types.index("ref")
        try:
            content = resolver(str(values[ref_index]))
        except Exception:
            return False, "INVARIANT_BYTE_RESOLUTION_FAILED"
        if not isinstance(content, (bytes, bytearray, memoryview)):
            return False, "INVARIANT_BYTE_RESOLUTION_FAILED"
        actual = sha256(bytes(content)).hexdigest()
        return actual == str(values[digest_index]).lower(), None
    if algorithm == "ALL_VALUES_EQUAL_V1":
        return all(_canonical_json(value) == _canonical_json(values[0]) for value in values[1:]), None
    if algorithm == "PAIRED_BYTE_HASH_LINEAGE_V1":
        for index in range(0, len(values), 2):
            passed, error = _evaluate_values(
                "HASH_AND_BYTE_LINEAGE_V1", values[index:index+2], types[index:index+2],
                parameters, join_keys, resolver,
            )
            if not passed:
                return False, error
        return True, None
    if algorithm == "EXACT_ARRAY_CARDINALITY_COMPARISON_V1":
        if not isinstance(values[0], list) or not isinstance(values[1], list):
            return False, "INVARIANT_RUNTIME_OPERAND_TYPE_MISMATCH"
        return len(values[0]) == len(values[1]), None
    if algorithm == "ORDERED_NUMERIC_PREDICATE_V1":
        try:
            left = _decimal(values[0])
            right = _decimal(values[1] if len(values) == 2 else parameters["threshold"])
            tolerance = _decimal(parameters.get("absolute_tolerance", 0))
        except (InvalidOperation, KeyError, ValueError):
            return False, "INVARIANT_RUNTIME_OPERAND_TYPE_MISMATCH"
        if not all(value.is_finite() for value in (left, right, tolerance)):
            return False, "INVARIANT_RUNTIME_OPERAND_TYPE_MISMATCH"
        relation = parameters["relation"]
        relations = {
            "LT": left < right,
            "LTE": left <= right,
            "EQ": abs(left - right) <= tolerance,
            "NE": abs(left - right) > tolerance,
            "GTE": left >= right,
            "GT": left > right,
            "ABS_LTE": abs(left) <= right,
        }
        return relations[relation], None
    if algorithm == "DECLARED_REFERENCE_RESOLUTION_V1":
        if resolver is None:
            return False, "INVARIANT_REFERENCE_RESOLVER_REQUIRED"
        try:
            resolved = resolver(str(values[0]))
        except Exception:
            return False, "INVARIANT_REFERENCE_RESOLUTION_FAILED"
        return resolved is not None, None
    if algorithm == "MATERIALIZED_ASSET_AUTHORIZATION_V1":
        return _materialized_asset_authorization(values[0], values[1], resolver)
    return False, "INVARIANT_ALGORITHM_UNSUPPORTED"


def _evaluation_result(
    passed: bool,
    *,
    failure_code: str | None = None,
    evaluated_subject_count: int = 0,
    failed_subjects: Sequence[str] = (),
    skipped: bool = False,
) -> dict[str, Any]:
    return {
        "passed": passed,
        "failure_code": failure_code,
        "evaluated_subject_count": evaluated_subject_count,
        "failed_subjects": list(failed_subjects),
        "skipped": skipped,
    }


def evaluate_predicate_ast_v1(
    predicate_ast: Any,
    document: Any,
    *,
    resolver: Resolver | None = None,
) -> dict[str, Any]:
    """Execute a typed predicate against one JSON-compatible document.

    ``resolver`` is an independent callback from a reference string to bytes or
    another concrete resolved object.  Hash-lineage evaluation always hashes
    the returned bytes itself; it never accepts a producer-reported PASS flag.
    """

    findings = validate_invariant_contract_v1(predicate_ast)
    if findings:
        return _evaluation_result(
            False,
            failure_code=findings[0]["failure_code"],
        )

    branch_selector = predicate_ast["branch_selector"]
    if branch_selector["mode"] == "REQUIRE_DISCRIMINATOR_CONST":
        try:
            discriminator = _resolve_pointer(
                document, branch_selector["discriminator_ref"]
            )
        except KeyError:
            return _evaluation_result(
                False, failure_code="INVARIANT_BRANCH_SELECTOR_UNRESOLVED"
            )
        if discriminator != branch_selector["const"]:
            return _evaluation_result(True, skipped=True)

    selector = predicate_ast["subject_selector"]
    quantifier = predicate_ast["quantifier"]
    selected = _expand_pointer(document, selector)
    if not selected:
        return _evaluation_result(
            False, failure_code="INVARIANT_SUBJECT_SET_EMPTY"
        )

    operand_refs = predicate_ast["operand_refs"]
    operand_types = predicate_ast["operand_types"]
    algorithm = predicate_ast["algorithm"]
    parameters = predicate_ast["parameters"]
    scopes = parameters.get("operand_scopes", [
        "SUBJECT" if "*" in ref else "GLOBAL" for ref in operand_refs
    ])
    join_keys = predicate_ast["join_keys"]
    evaluations: list[tuple[str, bool]] = []

    try:
        if quantifier == "PAIRWISE":
            for left_index in range(len(selected)):
                for right_index in range(left_index + 1, len(selected)):
                    left_path = selected[left_index][0]
                    right_path = selected[right_index][0]
                    left_wildcards = _wildcard_values(selector, left_path)
                    right_wildcards = _wildcard_values(selector, right_path)
                    refs = (
                        _substitute_wildcards(operand_refs[0], left_wildcards),
                        _substitute_wildcards(operand_refs[1], right_wildcards),
                    )
                    values = [_resolve_pointer(document, ref) for ref in refs]
                    passed, error = _evaluate_values(
                        algorithm, values, operand_types, parameters, join_keys, resolver
                    )
                    if error:
                        return _evaluation_result(False, failure_code=error)
                    evaluations.append((f"{left_path}|{right_path}", passed))
        else:
            for subject_path, _subject in selected:
                wildcard_values = _wildcard_values(selector, subject_path)
                if branch_selector["mode"] == "REQUIRE_DISCRIMINATOR_IN":
                    branch_ref = _substitute_wildcards(
                        branch_selector["discriminator_ref"], wildcard_values
                    )
                    if _resolve_pointer(document, branch_ref) not in branch_selector["values"]:
                        continue
                values = []
                for operand_ref, scope in zip(operand_refs, scopes):
                    if scope == "SUBJECT":
                        operand_ref = _substitute_wildcards(operand_ref, wildcard_values)
                    if "*" in operand_ref:
                        values.append([value for _, value in _expand_pointer(document, operand_ref)])
                    else:
                        values.append(_resolve_pointer(document, operand_ref))
                passed, error = _evaluate_values(
                    algorithm, values, operand_types, parameters, join_keys, resolver
                )
                if error:
                    return _evaluation_result(False, failure_code=error)
                evaluations.append((subject_path, passed))
    except (KeyError, IndexError, TypeError, ValueError):
        return _evaluation_result(
            False, failure_code="INVARIANT_RUNTIME_OPERAND_RESOLUTION_FAILED"
        )

    if not evaluations:
        if branch_selector["mode"] == "REQUIRE_DISCRIMINATOR_IN":
            return _evaluation_result(True, skipped=True)
        return _evaluation_result(
            False, failure_code="INVARIANT_SUBJECT_SET_EMPTY"
        )
    if quantifier == "EXISTS":
        passed = any(value for _, value in evaluations)
    else:
        passed = all(value for _, value in evaluations)
    failed_subjects = [path for path, value in evaluations if not value]
    return _evaluation_result(
        passed,
        failure_code=None if passed else "INVARIANT_PREDICATE_FALSE",
        evaluated_subject_count=len(evaluations),
        failed_subjects=failed_subjects,
    )


# Concise alias for callers that already bind the v1 module contract.
validate_invariant_contract = validate_invariant_contract_v1
