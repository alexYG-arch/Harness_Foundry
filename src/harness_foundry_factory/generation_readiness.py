"""Epoch 38-origin profile-aware Candidate generation readiness gate."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .models import content_sha256


SELF_USE_LOCAL_PROFILE = "SELF_USE_LOCAL_TRUSTED_OPERATOR"
CORE_READY_CLAIM = "CORE_RELEASE_READY_LOCAL"
OPTIONAL_SECURITY_STATUSES = {"NOT_APPLICABLE", "NOT_RUN"}
REQUIRED_CORE_ROUTES = {
    "MB-G0",
    "MB-P1",
    "MB-P2",
    "MB-P3",
    "MB-P4",
    "MB-RELEASE-CANDIDATE",
}
OPTIONAL_SECURITY_ROUTES = {
    "LINK-PROTOCOL",
    "LINK-CLI",
    "LINK-SELFTEST",
    "LINK-PREFLIGHT",
    "LINK-D",
    "LAB-PROTOCOL",
    "LAB-CLI",
    "LAB-FIXTURES",
    "LAB-SELFTEST",
    "LAB-CERTIFICATION",
}
OPTIONAL_CERTIFICATION_ATOM_ROUTES = {
    "LINK-PROTOCOL",
    "LINK-CLI",
    "LINK-SELFTEST",
    "LINK-PREFLIGHT",
    "LINK-D",
}
EXCLUDED_RELEASE_STEPS = {
    "P4_CERTIFIED_RELEASE_LOCK",
    "LAB_INSTALLED_POSITIVE_NEGATIVE_TAMPER_TESTS",
    "LINKAGE_A_INTERFACE_COMPLETENESS",
    "LINKAGE_D_INSTALLED_HANDSHAKE",
}


class GenerationReadinessError(RuntimeError):
    """A frozen Program is not eligible for local-profile Candidate generation."""

    def __init__(
        self, code: str, message: str, *, details: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


def evaluate_generation_readiness(
    snapshot: Mapping[str, Any],
    *,
    requirement_lock: Mapping[str, Any],
    architecture_readback: Mapping[str, Any],
    architecture_lock: Mapping[str, Any],
    compiled_contract: Mapping[str, Any],
    core_validation: Mapping[str, Any],
    core_evidence_projection: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate active locks, Epoch 38 profile policy, and core evidence read-only."""

    ir = snapshot.get("requirement_ir")
    freeze = snapshot.get("freeze")
    target = ir.get("target") if isinstance(ir, Mapping) else None
    if (
        snapshot.get("factory_state") != "REQUIREMENTS_FROZEN"
        or not isinstance(ir, Mapping)
        or not isinstance(freeze, Mapping)
        or not isinstance(target, Mapping)
    ):
        _fail(
            "GENERATION_REQUIREMENTS_NOT_FROZEN",
            "Candidate generation requires one complete frozen Program snapshot",
        )
    ir_sha256 = content_sha256(ir)
    active_requirement_epoch = snapshot.get("requirement_epoch")
    if (
        isinstance(active_requirement_epoch, bool)
        or not isinstance(active_requirement_epoch, int)
        or active_requirement_epoch < 38
        or freeze.get("status") != "FROZEN"
        or freeze.get("requirement_epoch") != active_requirement_epoch
        or freeze.get("requirement_ir_sha256") != ir_sha256
    ):
        _fail(
            "GENERATION_REQUIREMENT_BINDING_STALE_OR_MIXED_EPOCH",
            "The active snapshot, freeze, and Requirement IR must be one Hash-bound identity",
        )
    expected_requirement_lock_sha256 = _hash_without(
        requirement_lock, "requirement_lock_sha256"
    )
    if (
        requirement_lock.get("status") != "LOCKED"
        or requirement_lock.get("requirement_epoch") != active_requirement_epoch
        or requirement_lock.get("requirement_ir_sha256") != ir_sha256
        or requirement_lock.get("requirement_lock_sha256")
        != expected_requirement_lock_sha256
    ):
        _fail(
            "GENERATION_REQUIREMENT_LOCK_STALE",
            "Candidate generation requires the current independently recomputed Requirement Lock",
        )

    architecture_readback_sha256 = content_sha256(architecture_readback)
    architecture_lock_sha256 = _hash_without(
        architecture_lock, "architecture_lock_sha256"
    )
    if (
        architecture_readback.get("requirement_epoch")
        != active_requirement_epoch
        or architecture_readback.get("architecture_epoch") != 4
        or architecture_readback.get("control_plane_epoch") != 4
        or architecture_readback.get("unresolved_decisions") != []
        or architecture_lock.get("status") != "LOCKED"
        or architecture_lock.get("requirement_epoch")
        != active_requirement_epoch
        or architecture_lock.get("architecture_epoch") != 4
        or architecture_lock.get("control_plane_epoch") != 4
        or architecture_lock.get("requirement_lock_sha256")
        != expected_requirement_lock_sha256
        or architecture_lock.get("architecture_readback_sha256")
        != architecture_readback_sha256
        or architecture_lock.get("architecture_lock_sha256")
        != architecture_lock_sha256
    ):
        _fail(
            "GENERATION_ARCHITECTURE_LOCK_STALE_OR_MIXED_EPOCH",
            "Candidate generation requires the active Architecture 4 and Control Plane 4 Lock",
        )
    if (
        compiled_contract.get("status") != "PASS"
        or compiled_contract.get("compilation_kind")
        != "REQUIREMENT_ARCHITECTURE_CORE_CONTRACT"
        or compiled_contract.get("requirement_epoch")
        != active_requirement_epoch
        or compiled_contract.get("architecture_epoch") != 4
        or compiled_contract.get("control_plane_epoch") != 4
        or compiled_contract.get("bindings")
        != {
            "requirement_ir_sha256": ir_sha256,
            "requirement_lock_sha256": expected_requirement_lock_sha256,
            "architecture_readback_sha256": architecture_readback_sha256,
            "architecture_lock_sha256": architecture_lock_sha256,
        }
        or compiled_contract.get("compiled_contract_sha256")
        != _hash_without(compiled_contract, "compiled_contract_sha256")
        or compiled_contract.get("writes_performed") is not False
        or compiled_contract.get("execution_started") is not False
    ):
        _fail(
            "GENERATION_COMPILED_CONTRACT_STALE",
            "Candidate generation requires the current read-only dual-Lock compilation",
        )

    epoch4 = target.get("epoch4_architecture_control_plane_contract")
    epoch38 = target.get("v2_9_charter_architecture_correction_epoch38")
    routes = (
        epoch38.get("active_delivery_route_projection")
        if isinstance(epoch38, Mapping)
        else None
    )
    claims = epoch38.get("claim_vocabulary") if isinstance(epoch38, Mapping) else None
    threat = epoch38.get("threat_model") if isinstance(epoch38, Mapping) else None
    tiers = epoch38.get("atom_delivery_tiers") if isinstance(epoch38, Mapping) else None
    if (
        target.get("assurance_profile_id") != SELF_USE_LOCAL_PROFILE
        or target.get("operating_assurance_profile") != SELF_USE_LOCAL_PROFILE
        or target.get("delivery_priority_mode")
        != "IMPLEMENTATION_PRIORITY_TIERED_ASSURANCE"
        or not isinstance(epoch4, Mapping)
        or epoch4.get("contract_status") != "NORMATIVE_REQUIREMENT"
        or epoch4.get("requirement_epoch") != 38
        or epoch4.get("architecture_epoch") != 4
        or epoch4.get("control_plane_epoch") != 4
        or epoch4.get("assurance_profile_id") != SELF_USE_LOCAL_PROFILE
        or epoch4.get("unsupported_or_mixed_route_result")
        != "FAIL_BEFORE_CANDIDATE_WRITE"
    ):
        _fail(
            "GENERATION_ASSURANCE_PROFILE_INVALID",
            "Epoch 38 generation is limited to SELF_USE_LOCAL_TRUSTED_OPERATOR",
        )
    if (
        not isinstance(routes, Mapping)
        or set(routes.get("core_routes") or []) != REQUIRED_CORE_ROUTES
        or set(routes.get("optional_security_routes") or [])
        != OPTIONAL_SECURITY_ROUTES
        or routes.get("default_generation_release_steps")
        != ["P4_RELEASE_CANDIDATE_LOCK"]
        or set(routes.get("excluded_default_release_steps") or [])
        != EXCLUDED_RELEASE_STEPS
        or routes.get("post_implementation_validation_route")
        != ["MB-RELEASE-CANDIDATE"]
    ):
        _fail(
            "GENERATION_DELIVERY_ROUTE_INVALID",
            "Epoch 38 default generation routes are missing, expanded, or conflicting",
        )
    atom_tiers = {
        str(item.get("atom_id")): item.get("delivery_tier")
        for item in ir.get("atoms", [])
        if isinstance(item, Mapping) and item.get("atom_id")
    }
    coverage_by_atom = {
        str(item.get("atom_id")): item
        for item in ir.get("coverage_edges", [])
        if isinstance(item, Mapping) and item.get("atom_id")
    }
    if (
        not isinstance(claims, Mapping)
        or claims.get("local_engineering_completion") != CORE_READY_CLAIM
        or claims.get("external_certification") != "NOT_CLAIMED"
        or claims.get("optional_security_hardening")
        != "NOT_RUN_OR_NOT_APPLICABLE"
        or not isinstance(threat, Mapping)
        or threat.get("external_trust_anchor") != "NOT_APPLICABLE"
        or threat.get("independent_control_domain") != "NOT_APPLICABLE"
        or threat.get("dynamic_adversarial_reproduction") != "NOT_APPLICABLE"
        or threat.get("external_certification_offered") is not False
        or threat.get("accepts_third_party_candidate") is not False
        or not isinstance(tiers, Mapping)
        or tiers.get("ATOM-V29-P0-08") != "POST_IMPLEMENTATION_VALIDATION"
        or tiers.get("ATOM-V29-P0-09") != "OPTIONAL_SECURITY_HARDENING"
        or atom_tiers != dict(tiers)
        or set(coverage_by_atom.get("ATOM-V29-P0-09", {}).get("workpack_ids") or [])
        != OPTIONAL_CERTIFICATION_ATOM_ROUTES
        or set(
            coverage_by_atom.get("ATOM-V29-P0-09", {}).get("release_step_ids")
            or []
        )
        != {
            "LINKAGE_A_INTERFACE_COMPLETENESS",
            "LINKAGE_D_INSTALLED_HANDSHAKE",
        }
        or any(
            OPTIONAL_SECURITY_ROUTES & set(edge.get("workpack_ids") or [])
            for atom_id, edge in coverage_by_atom.items()
            if atom_id != "ATOM-V29-P0-09"
        )
    ):
        _fail(
            "GENERATION_SECURITY_BOUNDARY_INVALID",
            "Optional hardening or external certification leaked into the default profile",
        )

    validation_material = dict(core_validation)
    validation_sha256 = validation_material.pop("validation_sha256", None)
    projection_material = dict(core_evidence_projection)
    projection_sha256 = projection_material.pop("projection_sha256", None)
    optional_status = core_validation.get("optional_security_hardening")
    if (
        validation_sha256 != content_sha256(validation_material)
        or core_validation.get("status") != "PASS"
        or core_validation.get("validation_kind") != "OFFICIAL_CORE_VALIDATION"
        or core_validation.get("core_regression", {}).get("status") != "PASS"
        or core_validation.get("core_regression", {}).get("tests_executed") is not True
        or core_validation.get("writes_performed") is not False
        or core_validation.get("candidate_or_execution_root_created") is not False
        or core_validation.get("external_certification_claimed") is not False
        or optional_status not in OPTIONAL_SECURITY_STATUSES
        or core_validation.get("self_report_accepted_as_implementation_proof")
        is not False
    ):
        _fail(
            "GENERATION_CORE_VALIDATION_NOT_PASS",
            "Fresh official core behavior and major failure-path validation is required",
        )
    if (
        projection_sha256 != content_sha256(projection_material)
        or core_evidence_projection.get("status") != "PASS"
        or core_evidence_projection.get("projection_kind")
        != "IMPLEMENTATION_EVIDENCE_PROJECTION_NOT_RECEIPT"
        or core_evidence_projection.get("source_validation_sha256")
        != validation_sha256
        or core_evidence_projection.get("core_regression_status") != "PASS"
        or core_evidence_projection.get("product_manifest_sha256")
        != core_validation.get("product_manifest", {}).get("sha256")
        or core_evidence_projection.get("creates_authority") is not False
        or core_evidence_projection.get("release_receipt_created") is not False
        or core_evidence_projection.get("external_certification_claimed") is not False
        or core_evidence_projection.get("optional_security_hardening")
        != optional_status
        or core_evidence_projection.get("writes_performed") is not False
    ):
        _fail(
            "GENERATION_CORE_EVIDENCE_STALE_OR_UNTRUSTED",
            "Core evidence must be freshly projected from the same official validation result",
        )

    route_selection = {
        "assurance_profile": SELF_USE_LOCAL_PROFILE,
        "local_engineering_completion": CORE_READY_CLAIM,
        "core_routes": sorted(REQUIRED_CORE_ROUTES),
        "default_generation_release_steps": ["P4_RELEASE_CANDIDATE_LOCK"],
        "excluded_default_release_steps": sorted(EXCLUDED_RELEASE_STEPS),
        "optional_security_routes": sorted(OPTIONAL_SECURITY_ROUTES),
        "optional_security_hardening": optional_status,
        "external_certification_claimed": False,
    }
    bindings = {
        "requirement_ir_sha256": ir_sha256,
        "requirement_lock_sha256": expected_requirement_lock_sha256,
        "architecture_readback_sha256": architecture_readback_sha256,
        "architecture_lock_sha256": architecture_lock_sha256,
        "compiled_contract_sha256": compiled_contract["compiled_contract_sha256"],
        "product_manifest_sha256": core_validation["product_manifest"]["sha256"],
        "core_validation_sha256": validation_sha256,
        "core_evidence_projection_sha256": projection_sha256,
    }
    result = {
        "schema_version": "2.9",
        "status": "PASS",
        "readiness_kind": "EPOCH38_PROFILE_AWARE_CANDIDATE_GENERATION_PREFLIGHT",
        "program_id": snapshot.get("program_id") or ir.get("program_id"),
        "requirement_epoch": active_requirement_epoch,
        "architecture_epoch": 4,
        "control_plane_epoch": 4,
        "route_selection": route_selection,
        "route_selection_sha256": content_sha256(route_selection),
        "bindings": bindings,
        "writes_performed": False,
        "candidate_or_execution_root_created": False,
        "execution_started": False,
    }
    result["generation_readiness_sha256"] = content_sha256(result)
    return result


def _hash_without(value: Mapping[str, Any], field: str) -> str:
    material = deepcopy(dict(value))
    material.pop(field, None)
    return content_sha256(material)


def _fail(code: str, message: str) -> None:
    raise GenerationReadinessError(code, message)


__all__ = [
    "GenerationReadinessError",
    "evaluate_generation_readiness",
]
