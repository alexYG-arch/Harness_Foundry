"""Explicit Requirement Atom production contracts for v2.9 candidates."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Mapping


EXPLICIT_PRODUCTION_MODE = "EXPLICIT_ARTIFACT_OBLIGATIONS"
ARTIFACT_MANIFEST_REF = (
    "harness-resource://candidate/canonical_sources/"
    "ARTIFACT_OBLIGATION_MANIFEST.json"
)


def explicit_production_enabled(requirement_ir: Mapping[str, Any]) -> bool:
    target = requirement_ir.get("target")
    return isinstance(target, Mapping) and (
        target.get("production_semantics_mode") == EXPLICIT_PRODUCTION_MODE
    )


def validate_explicit_production_contracts(
    requirement_ir: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return closed findings for an enabled explicit production contract."""

    if not explicit_production_enabled(requirement_ir):
        return []
    findings: list[dict[str, Any]] = []
    edge_by_atom = {
        str(item.get("atom_id")): item
        for item in requirement_ir.get("coverage_edges", [])
        if isinstance(item, Mapping) and item.get("atom_id")
    }
    contract_ids: set[str] = set()
    artifact_ids: set[str] = set()
    artifact_refs: set[str] = set()
    for atom in requirement_ir.get("atoms", []):
        if not isinstance(atom, Mapping) or not atom.get("atom_id"):
            continue
        atom_id = str(atom["atom_id"])
        contract = atom.get("production_contract")
        if not isinstance(contract, Mapping):
            findings.append(_finding("PRODUCTION_CONTRACT_MISSING", atom_id))
            continue
        contract_id = contract.get("contract_id")
        if not isinstance(contract_id, str) or not contract_id:
            findings.append(_finding("PRODUCTION_CONTRACT_ID_MISSING", atom_id))
        elif contract_id in contract_ids:
            findings.append(_finding("PRODUCTION_CONTRACT_ID_DUPLICATE", contract_id))
        else:
            contract_ids.add(contract_id)
        obligations = contract.get("workpack_obligations")
        if not isinstance(obligations, list) or not obligations:
            findings.append(_finding("WORKPACK_OBLIGATIONS_MISSING", atom_id))
            continue
        expected_workpacks = set(edge_by_atom.get(atom_id, {}).get("workpack_ids", []))
        actual_workpacks = [
            str(item.get("workpack_id"))
            for item in obligations
            if isinstance(item, Mapping) and item.get("workpack_id")
        ]
        if (
            len(actual_workpacks) != len(obligations)
            or len(set(actual_workpacks)) != len(actual_workpacks)
            or set(actual_workpacks) != expected_workpacks
        ):
            findings.append(
                _finding(
                    "WORKPACK_OBLIGATION_COVERAGE_MISMATCH",
                    f"{atom_id}: expected={sorted(expected_workpacks)} actual={sorted(actual_workpacks)}",
                )
            )
        for obligation in obligations:
            if not isinstance(obligation, Mapping):
                continue
            workpack_id = str(obligation.get("workpack_id") or "")
            _validate_task_guidance(findings, atom_id, workpack_id, obligation)
            artifacts = obligation.get("artifact_obligations")
            if not isinstance(artifacts, list) or not artifacts:
                findings.append(
                    _finding(
                        "ARTIFACT_OBLIGATIONS_MISSING",
                        f"{atom_id}:{workpack_id}",
                    )
                )
                continue
            for artifact in artifacts:
                _validate_artifact_obligation(
                    findings,
                    atom_id,
                    workpack_id,
                    artifact,
                    artifact_ids,
                    artifact_refs,
                )
    return findings


def build_artifact_obligation_manifest(
    requirement_ir: Mapping[str, Any],
    *,
    target_id: str,
    program_id: str,
    requirement_ir_sha256: str,
    atom_catalog_sha256: str,
    coverage_matrix_sha256: str,
) -> dict[str, Any] | None:
    """Compile frozen Atom contracts into one portable production manifest."""

    if not explicit_production_enabled(requirement_ir):
        return None
    findings = validate_explicit_production_contracts(requirement_ir)
    if findings:
        codes = [item["code"] for item in findings]
        raise ValueError(f"explicit production contracts invalid: {codes}")
    contracts: list[dict[str, Any]] = []
    reverse_workpack_index: dict[str, list[dict[str, Any]]] = {}
    artifact_index: dict[str, dict[str, Any]] = {}
    for atom in requirement_ir.get("atoms", []):
        if not isinstance(atom, Mapping):
            continue
        atom_id = str(atom["atom_id"])
        contract = deepcopy(dict(atom["production_contract"]))
        compiled_contract = {
            "contract_id": str(contract["contract_id"]),
            "atom_id": atom_id,
            "source_id": atom.get("source_id"),
            "verification_mode": atom.get("verification_mode"),
            "status": "FROZEN_NOT_EXECUTED",
            "workpack_obligations": contract["workpack_obligations"],
        }
        contracts.append(compiled_contract)
        for obligation in compiled_contract["workpack_obligations"]:
            workpack_id = str(obligation["workpack_id"])
            artifact_ids = [
                str(item["artifact_id"])
                for item in obligation["artifact_obligations"]
            ]
            reverse_workpack_index.setdefault(workpack_id, []).append(
                {
                    "contract_id": compiled_contract["contract_id"],
                    "atom_id": atom_id,
                    "artifact_ids": artifact_ids,
                }
            )
            for artifact in obligation["artifact_obligations"]:
                artifact_index[str(artifact["artifact_id"])] = {
                    "atom_id": atom_id,
                    "contract_id": compiled_contract["contract_id"],
                    "workpack_id": workpack_id,
                    "artifact_ref": artifact["artifact_ref"],
                    "artifact_kind": artifact["artifact_kind"],
                }
    manifest = {
        "schema_version": "2.9",
        "manifest_id": f"ARTIFACT-OBLIGATIONS-{target_id}",
        "program_id": program_id,
        "target_id": target_id,
        "production_semantics_mode": EXPLICIT_PRODUCTION_MODE,
        "requirement_ir_sha256": requirement_ir_sha256,
        "normative_atom_catalog_sha256": atom_catalog_sha256,
        "atom_coverage_matrix_sha256": coverage_matrix_sha256,
        "contracts": contracts,
        "reverse_workpack_index": reverse_workpack_index,
        "artifact_index": artifact_index,
        "completion_rule": (
            "EVERY_ROUTED_ATOM_HAS_A_FROZEN_TASK_BUNDLE_AND_EVERY_REQUIRED_"
            "ARTIFACT_PASSES_ITS_DECLARED_VALIDATION_AND_ORACLE_RULE"
        ),
        "execution_started": False,
        "status": "FROZEN_NOT_EXECUTED",
    }
    manifest["manifest_sha256"] = _hash_without_field(manifest, "manifest_sha256")
    return manifest


def task_bundle_for_workpack(
    manifest: Mapping[str, Any] | None,
    *,
    workpack_id: str,
    project_id: str,
    program_id: str,
    target_id: str,
) -> dict[str, Any] | None:
    """Return the exact semantic task bundle routed to one Workpack."""

    if not isinstance(manifest, Mapping):
        return None
    expected = manifest.get("reverse_workpack_index", {}).get(workpack_id, [])
    if not expected:
        return None
    expected_contract_ids = {
        str(item["contract_id"]) for item in expected if isinstance(item, Mapping)
    }
    task_contracts: list[dict[str, Any]] = []
    for contract in manifest.get("contracts", []):
        if (
            not isinstance(contract, Mapping)
            or contract.get("contract_id") not in expected_contract_ids
        ):
            continue
        obligation = next(
            item
            for item in contract["workpack_obligations"]
            if item["workpack_id"] == workpack_id
        )
        task_contracts.append(
            {
                "contract_id": contract["contract_id"],
                "atom_id": contract["atom_id"],
                **deepcopy(dict(obligation)),
            }
        )
    artifacts = [
        deepcopy(dict(artifact))
        for contract in task_contracts
        for artifact in contract["artifact_obligations"]
    ]
    bundle = {
        "schema_version": "2.9",
        "task_bundle_id": f"TASK-BUNDLE-{workpack_id}",
        "program_id": program_id,
        "target_id": target_id,
        "project_id": project_id,
        "workpack_id": workpack_id,
        "artifact_obligation_manifest_ref": ARTIFACT_MANIFEST_REF,
        "artifact_obligation_manifest_sha256": manifest.get("manifest_sha256"),
        "intent_atom_ids": [str(item["atom_id"]) for item in task_contracts],
        "production_contract_ids": [
            str(item["contract_id"]) for item in task_contracts
        ],
        "task_contracts": task_contracts,
        "required_artifact_ids": [str(item["artifact_id"]) for item in artifacts],
        "required_artifact_refs": [str(item["artifact_ref"]) for item in artifacts],
        "semantic_hydration_complete": True,
        "runtime_binding_complete": False,
        "execution_authorization_ref": None,
        "execution_started": False,
        "completion_rule": (
            "ALL_DECLARED_ARTIFACTS_EXIST_AT_THEIR_LOGICAL_REFS_AND_PASS_"
            "THEIR_SCHEMA_VALIDATION_ORACLE_AND_FAILURE_RETURN_CONTRACTS"
        ),
        "status": "SEMANTIC_CONTRACT_FROZEN_RUNTIME_NOT_BOUND",
    }
    bundle["task_bundle_sha256"] = _hash_without_field(
        bundle, "task_bundle_sha256"
    )
    return bundle


def _validate_task_guidance(
    findings: list[dict[str, Any]],
    atom_id: str,
    workpack_id: str,
    obligation: Mapping[str, Any],
) -> None:
    label = f"{atom_id}:{workpack_id}"
    if not obligation.get("task_objective"):
        findings.append(_finding("TASK_OBJECTIVE_MISSING", label))
    for field in (
        "required_inputs",
        "design_questions",
        "deterministic_steps",
        "forbidden_inferences",
    ):
        value = obligation.get(field)
        if not isinstance(value, list) or (
            field != "design_questions" and not value
        ):
            findings.append(_finding("TASK_GUIDANCE_INCOMPLETE", f"{label}:{field}"))
    if not obligation.get("completion_rule"):
        findings.append(_finding("TASK_COMPLETION_RULE_MISSING", label))


def _validate_artifact_obligation(
    findings: list[dict[str, Any]],
    atom_id: str,
    workpack_id: str,
    artifact: Any,
    artifact_ids: set[str],
    artifact_refs: set[str],
) -> None:
    label = f"{atom_id}:{workpack_id}"
    if not isinstance(artifact, Mapping):
        findings.append(_finding("ARTIFACT_OBLIGATION_INVALID", label))
        return
    artifact_id = artifact.get("artifact_id")
    artifact_ref = artifact.get("artifact_ref")
    if not isinstance(artifact_id, str) or not artifact_id:
        findings.append(_finding("ARTIFACT_ID_MISSING", label))
    elif artifact_id in artifact_ids:
        findings.append(_finding("ARTIFACT_ID_DUPLICATE", artifact_id))
    else:
        artifact_ids.add(artifact_id)
    if not artifact.get("artifact_kind"):
        findings.append(_finding("ARTIFACT_KIND_MISSING", str(artifact_id)))
    if (
        not isinstance(artifact_ref, str)
        or not artifact_ref.startswith("harness-resource://execution/")
        or ".." in artifact_ref
    ):
        findings.append(_finding("ARTIFACT_REF_NOT_PORTABLE", str(artifact_ref)))
    elif artifact_ref in artifact_refs:
        findings.append(_finding("ARTIFACT_REF_DUPLICATE", artifact_ref))
    else:
        artifact_refs.add(artifact_ref)
    schema = artifact.get("schema")
    if not isinstance(schema, Mapping):
        findings.append(_finding("ARTIFACT_SCHEMA_MISSING", str(artifact_id)))
    else:
        required = schema.get("required")
        properties = schema.get("properties")
        if (
            schema.get("type") != "object"
            or not isinstance(required, list)
            or not required
            or not isinstance(properties, Mapping)
            or not set(required).issubset(properties)
        ):
            findings.append(_finding("ARTIFACT_SCHEMA_INCOMPLETE", str(artifact_id)))
    if not artifact.get("production_rule"):
        findings.append(_finding("ARTIFACT_PRODUCTION_RULE_MISSING", str(artifact_id)))
    validation_rule = artifact.get("validation_rule")
    if not isinstance(validation_rule, Mapping) or any(
        not validation_rule.get(field)
        for field in ("validator_owner", "decision_rule", "evidence_required")
    ):
        findings.append(_finding("ARTIFACT_VALIDATION_RULE_INCOMPLETE", str(artifact_id)))
    oracle = artifact.get("oracle")
    if not isinstance(oracle, Mapping) or any(
        not oracle.get(field)
        for field in ("oracle_id", "independence_level", "decision_rule")
    ) or not isinstance(oracle.get("common_mode_exclusions"), list):
        findings.append(_finding("ARTIFACT_ORACLE_INCOMPLETE", str(artifact_id)))
    failure_return = artifact.get("failure_return")
    if not isinstance(failure_return, Mapping) or any(
        not failure_return.get(field)
        for field in ("error_code", "control_node_id", "invalidates")
    ):
        findings.append(_finding("ARTIFACT_FAILURE_RETURN_INCOMPLETE", str(artifact_id)))


def _finding(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "message": message}


def _hash_without_field(value: Mapping[str, Any], field: str) -> str:
    document = deepcopy(dict(value))
    document.pop(field, None)
    payload = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
