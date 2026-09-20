"""Public acceptance bases and offline checker examples, not target acceptance.

No domain schema, process dispatch, extra store or digest is introduced here.
Locators establish availability, not semantic completeness of a verifier.
"""

from copy import deepcopy
from collections.abc import Mapping

from .build_types import RequestValidationError
from .source_intake import resolve_source_locator


def validate_acceptance_contracts(requirement_ir, *, snapshot=None, required=False):
    """Keep old proposals readable; require explicit bases for new run scopes."""
    sources = {row["source_id"] for row in requirement_ir["sources"]}
    resolved = {}
    for case in [*requirement_ir.get("acceptance_cases", []), *requirement_ir.get("negative_cases", [])]:
        basis = case.get("acceptance_contract")
        if basis is None and not required:
            continue
        if (not isinstance(basis, Mapping) or set(basis) != {"source_id", "source_locator"}
                or not isinstance(basis["source_id"], str) or basis["source_id"] not in sources
                or not isinstance(basis["source_locator"], str) or not basis["source_locator"].strip()):
            raise RequestValidationError("Case needs an explicit public acceptance_contract: " + case["case_id"])
        if snapshot is not None:
            text = resolve_source_locator(snapshot, basis["source_id"], basis["source_locator"])
            if not text.strip():
                raise RequestValidationError("Case acceptance contract is empty: " + case["case_id"])
            resolved[case["case_id"]] = {**basis, "text": text}
    return resolved


def check_contract_examples(checker, examples):
    """Exercise a checker against public positive/negative examples in memory.

    A checker returns normally to accept, raises AssertionError to reject.
    Crashes remain crashes, never successful negative tests. Call each local
    and independent checker separately with the SAME data, not shared oracle
    code. The caller owns the fixture meaning and any callable side effects;
    this helper itself neither reads files nor executes target commands.
    """
    if not isinstance(examples, list) or not examples:
        raise ValueError("contract examples must be a nonempty list")
    names = set()
    for row in examples:
        if (not isinstance(row, dict) or set(row) != {"name", "input", "accepted"}
                or not isinstance(row["name"], str) or not row["name"].strip()
                or row["name"] in names or type(row["accepted"]) is not bool):
            raise ValueError("contract example needs unique name, input and boolean accepted")
        names.add(row["name"])
    if not any(row["accepted"] for row in examples):
        raise ValueError("contract examples must include a positive witness")
    results = []
    for row in examples:
        diagnostic = None
        try:
            checker(deepcopy(row["input"]))
            accepted = True
        except AssertionError as exc:
            accepted, diagnostic = False, str(exc)
        results.append({"name": row["name"], "expected_accepted": row["accepted"],
                        "actual_accepted": accepted, "matched": accepted == row["accepted"],
                        "diagnostic": diagnostic})
    return {"status": "CONTRACT_EXAMPLES_MATCHED" if all(row["matched"] for row in results)
            else "CONTRACT_EXAMPLES_MISMATCH", "examples": results,
            "semantic_completeness_verified": False, "target_accepted": False}
