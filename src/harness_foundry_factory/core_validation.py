"""Read-only official core behavior validation and evidence projection."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

from .constants import FACTORY_ID, TARGET_PROTOCOL_VERSION, project_root
from .models import content_sha256


OPTIONAL_SECURITY_HARDENING_STATUS = "NOT_RUN"
OPTIONAL_COMPATIBILITY_VALIDATION_STATUS = "NOT_RUN"
OPTIONAL_COMPATIBILITY_CAPABILITIES = (
    "profile-aware-candidate-generation-preflight",
    "core-release-ready-local-gate",
    "default-delivery-route-selection",
    "optional-security-route-exclusion",
    "control-plane-registration-executable-closure",
    "program-driver-runtime-verification-executable-closure",
    "controlled-runtime-workpack-executable-closure",
    "main-execution-package-validation-executable-closure",
)

_IDENTITY_POSITIVE = (
    "tests.test_product_identity.ProductIdentityTests."
    "test_version_command_is_path_independent_and_machine_readable"
)
_LOCK_POSITIVE = (
    "tests.test_requirement_architecture_cli.RequirementArchitectureCliTests."
    "test_dual_lock_readbacks_and_compile_are_real_and_read_only"
)
_GRAPH_POSITIVE = (
    "tests.test_control_kernel.ControlKernelTests."
    "test_profile_graph_and_advance_until_real_gate_are_data_driven"
)
_AUTHORING_POSITIVE = (
    "tests.test_advance_authoring_cli.AdvanceAuthoringCliTests."
    "test_cli_advances_all_internal_checks_in_one_factory_cas"
)
_RUNTIME_POSITIVE = (
    "tests.test_runtime_advance_cli.RuntimeAdvanceCliTests."
    "test_cli_advances_three_nodes_retries_once_and_emits_complete_trace"
)
_RECOVERY_POSITIVE = (
    "tests.test_checkpoint_resume_cli.CheckpointResumeCliTests."
    "test_resume_revalidates_and_never_replays_completed_transition"
)
_PORTABLE_POSITIVE = (
    "tests.test_portable_local_cli.PortableLocalCliTests."
    "test_package_relocates_and_official_startup_smoke_passes_without_install"
)
_CORE_FAILURE_PATHS = (
    (
        "INCOMPLETE_ARCHITECTURE_OR_MIXED_EPOCH",
        "tests.test_requirement_architecture_cli.RequirementArchitectureCliTests."
        "test_incomplete_architecture_and_mixed_epoch_fail_closed",
    ),
    (
        "STALE_LOCK_BINDING",
        "tests.test_requirement_architecture_cli.RequirementArchitectureCliTests."
        "test_stale_requirement_or_architecture_binding_is_rejected",
    ),
    (
        "POLICY_CONFLICT_OR_UNKNOWN",
        "tests.test_control_kernel.ControlKernelTests."
        "test_rule_conflict_and_unknown_fail_closed",
    ),
    (
        "PARENT_SCOPE_EXPANSION",
        "tests.test_control_kernel.ControlKernelTests."
        "test_child_grant_cannot_expand_parent_scope",
    ),
    (
        "PROFILE_STALE_OR_MIXED_EPOCH",
        "tests.test_control_kernel.ControlKernelTests."
        "test_profile_graph_rejects_mixed_epoch_and_stale_lock_binding",
    ),
    (
        "BLOCKING_REQUIREMENT_GAP",
        "tests.test_advance_authoring_cli.AdvanceAuthoringCliTests."
        "test_blocking_requirement_gap_returns_typed_blocker",
    ),
    (
        "AUTHORING_POLICY_CONFLICT_OR_UNKNOWN",
        "tests.test_advance_authoring_cli.AdvanceAuthoringCliTests."
        "test_policy_conflict_and_unknown_fail_closed_without_mutation",
    ),
    (
        "AUTHORING_STATE_CAS_MISMATCH",
        "tests.test_advance_authoring_cli.AdvanceAuthoringCliTests."
        "test_stale_state_cas_fails_before_authoring_transition",
    ),
    (
        "RUNTIME_STALE_BINDING_OR_UNKNOWN_ADAPTER",
        "tests.test_runtime_advance_cli.RuntimeAdvanceCliTests."
        "test_binding_state_and_unknown_adapter_fail_closed_without_event",
    ),
    (
        "RUNTIME_BUDGET_AUTHORITY_OR_IRREVERSIBLE_STOP",
        "tests.test_runtime_advance_cli.RuntimeAdvanceCliTests."
        "test_budget_authority_irreversible_and_policy_stops_are_typed",
    ),
    (
        "EXPIRED_OR_REVOKED_PARENT",
        "tests.test_runtime_advance_cli.RuntimeAdvanceCliTests."
        "test_expired_revoked_and_disabled_test_adapter_modes_fail_closed",
    ),
    (
        "UNKNOWN_SIDE_EFFECT",
        "tests.test_runtime_advance_cli.RuntimeAdvanceCliTests."
        "test_unknown_side_effect_stops_without_retry",
    ),
    (
        "RESUME_BINDING_OR_ENVIRONMENT_DRIFT",
        "tests.test_checkpoint_resume_cli.CheckpointResumeCliTests."
        "test_resume_drift_checks_fail_closed_before_adapter",
    ),
    (
        "EVENT_TIP_DRIFT_OR_UNKNOWN_SIDE_EFFECT",
        "tests.test_checkpoint_resume_cli.CheckpointResumeCliTests."
        "test_event_tip_drift_and_unknown_side_effect_require_hard_stop",
    ),
    (
        "PORTABLE_FILE_HASH_MISMATCH",
        "tests.test_portable_local_cli.PortableLocalCliTests."
        "test_self_check_hash_failure_is_diagnostic_and_read_only",
    ),
    (
        "PATH_TRAVERSAL_OR_EXTERNAL_SYMLINK",
        "tests.test_portable_local_cli.PortableLocalCliTests."
        "test_logical_root_rejects_traversal_encoding_and_external_symlink",
    ),
    (
        "UNDECLARED_DEPENDENCY_CREDENTIAL_OR_LOCAL_IDENTITY",
        "tests.test_portable_local_cli.PortableLocalCliTests."
        "test_preflight_rejects_undeclared_dependency_credential_and_identity_without_output",
    ),
)

_CORE_GROUPS = (
    (
        ("version",),
        "src/harness_foundry_factory/constants.py",
        "cli:version",
        _IDENTITY_POSITIVE,
    ),
    (
        ("requirement-readback", "requirement-lock"),
        "src/harness_foundry_factory/service.py",
        "cli:requirement-readback",
        _LOCK_POSITIVE,
    ),
    (
        ("architecture-readback", "architecture-lock"),
        "src/harness_foundry_factory/service.py",
        "cli:architecture-readback",
        _LOCK_POSITIVE,
    ),
    (
        ("compile",),
        "src/harness_foundry_factory/service.py",
        "cli:compile",
        _LOCK_POSITIVE,
    ),
    (
        ("assurance-profile-program-graph",),
        "src/harness_foundry_factory/control_kernel.py",
        "instantiate_program_graph",
        _GRAPH_POSITIVE,
    ),
    (
        ("generic-transition-engine",),
        "src/harness_foundry_factory/control_kernel.py",
        "GenericTransitionEngine.advance_until_gate",
        _GRAPH_POSITIVE,
    ),
    (
        ("rule-evaluator", "decision-policy", "decision-receipt"),
        "src/harness_foundry_factory/control_kernel.py",
        "evaluate_decision_policy",
        _GRAPH_POSITIVE,
    ),
    (
        (
            "requirement-classification",
            "charter-clause-disposition",
            "policy-coverage",
            "architecture-candidate",
            "run-contract",
            "evidence-applicability",
            "authoring-readback",
            "auto-advance-to-real-gate",
        ),
        "src/harness_foundry_factory/service.py",
        "cli:advance-authoring-until-gate",
        _AUTHORING_POSITIVE,
    ),
    (
        ("parent-authorization-challenge",),
        "src/harness_foundry_factory/control_kernel.py",
        "prepare_parent_authorization_challenge",
        _RUNTIME_POSITIVE,
    ),
    (
        (
            "machine-derived-attempt-grant",
            "runtime-advance-until-gate",
            "bounded-retry",
            "budget-accounting",
            "advance-trace",
        ),
        "src/harness_foundry_factory/control_kernel.py",
        "cli:advance-until-gate",
        _RUNTIME_POSITIVE,
    ),
    (
        ("checkpoint-bundle",),
        "src/harness_foundry_factory/control_kernel.py",
        "cli:checkpoint",
        "tests.test_checkpoint_resume_cli.CheckpointResumeCliTests."
        "test_checkpoint_is_event_bound_and_idempotent",
    ),
    (
        ("resume-capsule", "resume-revalidation", "side-effect-reconciliation"),
        "src/harness_foundry_factory/control_kernel.py",
        "cli:resume",
        _RECOVERY_POSITIVE,
    ),
    (
        ("explain-stop",),
        "src/harness_foundry_factory/control_kernel.py",
        "cli:explain-stop",
        "tests.test_checkpoint_resume_cli.CheckpointResumeCliTests."
        "test_explain_stop_is_read_only",
    ),
    (
        (
            "portable-local-package",
            "dependency-discovery",
            "local-startup-smoke",
        ),
        "src/harness_foundry_factory/portable.py",
        "cli:package-local",
        _PORTABLE_POSITIVE,
    ),
    (
        ("logical-root-resolution", "path-containment"),
        "src/harness_foundry_factory/portable.py",
        "resolve_logical_resource_uri",
        "tests.test_portable_local_cli.PortableLocalCliTests."
        "test_logical_root_rejects_traversal_encoding_and_external_symlink",
    ),
    (
        ("self-check-diagnostic",),
        "src/harness_foundry_factory/portable.py",
        "cli:self-check-diagnostic",
        _PORTABLE_POSITIVE,
    ),
)

_VALIDATION_LAYER = (
    "product-implementation-manifest",
    "official-core-validator",
    "capability-behavior-matrix",
    "major-failure-path-matrix",
    "implementation-evidence-projection",
)
_VALIDATION_LAYER_SELECTORS = (
    "tests.test_core_validation_cli.CoreValidationCliTests."
    "test_validate_core_executes_bound_behavior_and_failure_selectors_read_only",
    "tests.test_core_validation_cli.CoreValidationCliTests."
    "test_core_evidence_projection_is_deterministic_and_not_a_receipt",
    "tests.test_core_validation_cli.CoreValidationCliTests."
    "test_manifest_gap_fails_before_any_test_program_executes",
    "tests.test_core_validation_cli.CoreValidationCliTests."
    "test_optional_compatibility_scope_mismatch_fails_without_execution",
    "tests.test_core_validation_cli.CoreValidationCliTests."
    "test_projection_rejects_candidate_style_pass_self_report",
)


class CoreValidationError(RuntimeError):
    """Fail-closed core validation boundary error."""

    def __init__(
        self, code: str, message: str, *, details: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


def validate_core(
    source_root: str | Path | None = None, *, execute_tests: bool = True
) -> dict[str, Any]:
    """Validate real core entrypoints and behavior without mutating product state."""

    root = Path(source_root or project_root()).expanduser().resolve(strict=True)
    findings: list[dict[str, Any]] = []
    manifest_path = root / "FACTORY_MANIFEST.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CoreValidationError(
            "PRODUCT_IMPLEMENTATION_MANIFEST_INVALID",
            "FACTORY_MANIFEST.json is not readable canonical product metadata",
            details={"error": str(exc)},
        ) from exc
    if not isinstance(manifest, dict):
        raise CoreValidationError(
            "PRODUCT_IMPLEMENTATION_MANIFEST_INVALID",
            "FACTORY_MANIFEST.json must contain one JSON object",
        )

    manifest_sha256 = _file_sha256(manifest_path)
    expected_capabilities = [
        capability for group in _CORE_GROUPS for capability in group[0]
    ] + list(_VALIDATION_LAYER)
    declared_capabilities = manifest.get("implemented_core_capabilities")
    if (
        not isinstance(declared_capabilities, list)
        or len(declared_capabilities) != len(set(declared_capabilities))
        or set(declared_capabilities) != set(expected_capabilities)
    ):
        findings.append(
            {
                "code": "IMPLEMENTATION_MANIFEST_CAPABILITY_MISMATCH",
                "expected": expected_capabilities,
                "actual": declared_capabilities,
            }
        )
    declared_optional_capabilities = manifest.get(
        "implemented_optional_compatibility_capabilities"
    )
    if (
        not isinstance(declared_optional_capabilities, list)
        or len(declared_optional_capabilities)
        != len(set(declared_optional_capabilities))
        or set(declared_optional_capabilities)
        != set(OPTIONAL_COMPATIBILITY_CAPABILITIES)
    ):
        findings.append(
            {
                "code": "OPTIONAL_COMPATIBILITY_MANIFEST_CAPABILITY_MISMATCH",
                "expected": list(OPTIONAL_COMPATIBILITY_CAPABILITIES),
                "actual": declared_optional_capabilities,
            }
        )
    if (
        manifest.get("manifest_kind") != "PRODUCT_IMPLEMENTATION_MANIFEST"
        or manifest.get("assurance_profile")
        != "SELF_USE_LOCAL_TRUSTED_OPERATOR"
        or manifest.get("external_certification_claimed") is not False
        or manifest.get("optional_security_hardening")
        != OPTIONAL_SECURITY_HARDENING_STATUS
        or manifest.get("optional_compatibility_default_route") is not False
        or manifest.get("optional_compatibility_core_release_blocking") is not False
    ):
        findings.append(
            {
                "code": "IMPLEMENTATION_MANIFEST_BOUNDARY_INVALID",
                "message": "Product manifest assurance and certification boundary is invalid",
            }
        )

    bindings: list[dict[str, Any]] = []
    for capabilities, module, entrypoint, positive_selector in _CORE_GROUPS:
        module_path = root / module
        module_sha256 = _file_sha256(module_path) if module_path.is_file() else None
        if module_sha256 is None:
            findings.append({"code": "IMPLEMENTATION_MODULE_MISSING", "module": module})
        elif not _entrypoint_exists(root, module, entrypoint):
            findings.append(
                {
                    "code": "PUBLIC_ENTRYPOINT_MISSING",
                    "module": module,
                    "public_entrypoint": entrypoint,
                }
            )
        for capability in capabilities:
            bindings.append(
                {
                    "capability": capability,
                    "implementation_module": module,
                    "implementation_module_sha256": module_sha256,
                    "public_entrypoint": entrypoint,
                    "product_manifest_sha256": manifest_sha256,
                    "exact_test_selectors": [positive_selector],
                    "selector_execution": "OFFICIAL_CORE_VALIDATOR",
                }
            )

    validation_module = "src/harness_foundry_factory/core_validation.py"
    validation_path = root / validation_module
    validation_sha256 = (
        _file_sha256(validation_path) if validation_path.is_file() else None
    )
    if validation_sha256 is None:
        findings.append(
            {"code": "IMPLEMENTATION_MODULE_MISSING", "module": validation_module}
        )
    for entrypoint in ("cli:validate-core", "cli:project-core-evidence"):
        if not _entrypoint_exists(root, validation_module, entrypoint):
            findings.append(
                {
                    "code": "PUBLIC_ENTRYPOINT_MISSING",
                    "module": validation_module,
                    "public_entrypoint": entrypoint,
                }
            )
    for capability in _VALIDATION_LAYER:
        bindings.append(
            {
                "capability": capability,
                "implementation_module": validation_module,
                "implementation_module_sha256": validation_sha256,
                "public_entrypoint": (
                    "cli:project-core-evidence"
                    if capability == "implementation-evidence-projection"
                    else "cli:validate-core"
                ),
                "product_manifest_sha256": manifest_sha256,
                "exact_test_selectors": list(_VALIDATION_LAYER_SELECTORS),
                "selector_execution": "OUTER_OFFICIAL_REGRESSION_NO_RECURSION",
            }
        )

    selectors = sorted(
        {
            binding["exact_test_selectors"][0]
            for binding in bindings
            if binding["selector_execution"] == "OFFICIAL_CORE_VALIDATOR"
        }
        | {selector for _, selector in _CORE_FAILURE_PATHS}
    )
    for selector in (*selectors, *_VALIDATION_LAYER_SELECTORS):
        if not _test_selector_exists(root, selector):
            findings.append(
                {"code": "EXACT_TEST_SELECTOR_MISSING", "selector": selector}
            )

    tests_executed = bool(execute_tests and not findings)
    test_status = "NOT_RUN"
    if tests_executed:
        completed = _run_selectors(root, selectors)
        test_status = "PASS" if completed.returncode == 0 else "FAIL"
        if completed.returncode != 0:
            findings.append(
                {
                    "code": "OFFICIAL_CORE_REGRESSION_FAILED",
                    "returncode": completed.returncode,
                    "stdout_sha256": _text_sha256(completed.stdout),
                    "stderr_sha256": _text_sha256(completed.stderr),
                }
            )

    selector_results = [
        {
            "selector": selector,
            "status": test_status,
            "failure_output_embedded": False,
        }
        for selector in selectors
    ]
    result: dict[str, Any] = {
        "schema_version": "2.9",
        "status": "PASS" if not findings and test_status == "PASS" else "FAIL",
        "validation_kind": "OFFICIAL_CORE_VALIDATION",
        "factory_id": FACTORY_ID,
        "target_protocol_version": TARGET_PROTOCOL_VERSION,
        "product_manifest": {
            "path": "FACTORY_MANIFEST.json",
            "sha256": manifest_sha256,
            "manifest_is_metadata_not_implementation_proof": True,
        },
        "product_implementation_manifest": {
            "kind": "RUNTIME_COMPUTED_IMPLEMENTATION_BINDING",
            "product_manifest_sha256": manifest_sha256,
            "capability_count": len(bindings),
            "capability_bindings_sha256": content_sha256(bindings),
            "implementation_proven_by_behavior_not_manifest_alone": True,
        },
        "capability_behavior_matrix": bindings,
        "major_failure_path_matrix": [
            {
                "failure_path": failure_path,
                "exact_test_selector": selector,
                "status": test_status,
            }
            for failure_path, selector in _CORE_FAILURE_PATHS
        ],
        "selector_results": selector_results,
        "core_regression": {
            "status": test_status,
            "tests_executed": tests_executed,
            "exact_selector_count": len(selectors),
            "validation_layer_selectors": list(_VALIDATION_LAYER_SELECTORS),
            "validation_layer_execution": "OUTER_OFFICIAL_REGRESSION_NO_RECURSION",
        },
        "findings": findings,
        "writes_performed": False,
        "candidate_or_execution_root_created": False,
        "release_receipt_created": False,
        "external_certification_claimed": False,
        "optional_security_hardening": OPTIONAL_SECURITY_HARDENING_STATUS,
        "optional_compatibility": {
            "validation_status": OPTIONAL_COMPATIBILITY_VALIDATION_STATUS,
            "capability_count": len(OPTIONAL_COMPATIBILITY_CAPABILITIES),
            "capabilities": list(OPTIONAL_COMPATIBILITY_CAPABILITIES),
            "default_route": False,
            "core_release_blocking": False,
        },
        "self_report_accepted_as_implementation_proof": False,
    }
    result["validation_sha256"] = content_sha256(result)
    return result


def project_core_evidence() -> dict[str, Any]:
    """Run official validation and project its result without accepting self-report."""

    return _project_validated_core_evidence(validate_core())


def _project_validated_core_evidence(
    validation: Mapping[str, Any],
) -> dict[str, Any]:
    """Project one internally obtained complete official validation result."""

    required = {
        "validation_kind",
        "validation_sha256",
        "product_manifest",
        "capability_behavior_matrix",
        "major_failure_path_matrix",
        "core_regression",
        "writes_performed",
        "external_certification_claimed",
        "optional_security_hardening",
        "optional_compatibility",
    }
    if required - set(validation):
        raise CoreValidationError(
            "VALIDATION_RESULT_INCOMPLETE",
            "Evidence projection requires a complete official Validator result",
            details={"missing": sorted(required - set(validation))},
        )
    if validation.get("validation_kind") != "OFFICIAL_CORE_VALIDATION":
        raise CoreValidationError(
            "VALIDATION_RESULT_UNTRUSTED_KIND",
            "Evidence projection rejects non-official validation self-reports",
        )
    material = dict(validation)
    claimed_sha256 = material.pop("validation_sha256", None)
    if claimed_sha256 != content_sha256(material):
        raise CoreValidationError(
            "VALIDATION_RESULT_HASH_MISMATCH",
            "Official validation result Hash does not verify",
        )
    if validation.get("status") != "PASS" or validation["core_regression"].get(
        "status"
    ) != "PASS":
        raise CoreValidationError(
            "CORE_VALIDATION_NOT_PASS",
            "Evidence cannot project an incomplete or failed core validation",
        )
    if validation.get("external_certification_claimed") is not False:
        raise CoreValidationError(
            "EXTERNAL_CERTIFICATION_CLAIM_FORBIDDEN",
            "SELF_USE_LOCAL core evidence cannot claim external certification",
        )

    projection: dict[str, Any] = {
        "schema_version": "2.9",
        "status": "PASS",
        "projection_kind": "IMPLEMENTATION_EVIDENCE_PROJECTION_NOT_RECEIPT",
        "factory_id": FACTORY_ID,
        "source_validation_sha256": claimed_sha256,
        "product_manifest_sha256": validation["product_manifest"]["sha256"],
        "capability_count": len(validation["capability_behavior_matrix"]),
        "major_failure_path_count": len(validation["major_failure_path_matrix"]),
        "core_regression_status": validation["core_regression"]["status"],
        "exact_selector_count": validation["core_regression"][
            "exact_selector_count"
        ],
        "validation_layer_execution": validation["core_regression"][
            "validation_layer_execution"
        ],
        "implementation_evidence": [
            {
                "capability": binding["capability"],
                "implementation_module": binding["implementation_module"],
                "implementation_module_sha256": binding[
                    "implementation_module_sha256"
                ],
                "public_entrypoint": binding["public_entrypoint"],
                "exact_test_selectors": binding["exact_test_selectors"],
                "selector_execution": binding["selector_execution"],
            }
            for binding in validation["capability_behavior_matrix"]
        ],
        "creates_authority": False,
        "release_receipt_created": False,
        "external_certification_claimed": False,
        "optional_security_hardening": validation[
            "optional_security_hardening"
        ],
        "optional_compatibility": dict(validation["optional_compatibility"]),
        "schema_manifest_or_self_report_alone_is_proof": False,
        "writes_performed": False,
    }
    projection["projection_sha256"] = content_sha256(projection)
    return projection


def _entrypoint_exists(root: Path, module: str, entrypoint: str) -> bool:
    if entrypoint.startswith("cli:"):
        command = entrypoint.removeprefix("cli:")
        cli_tree = ast.parse(
            (root / "src/harness_foundry_factory/cli.py").read_text(encoding="utf-8")
        )
        return any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_parser"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == command
            for node in ast.walk(cli_tree)
        )
    tree = ast.parse((root / module).read_text(encoding="utf-8"))
    parts = entrypoint.split(".")
    if len(parts) == 1:
        return any(
            isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == parts[0]
            for node in tree.body
        )
    class_name, method_name = parts
    return any(
        isinstance(node, ast.ClassDef)
        and node.name == class_name
        and any(
            isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
            and member.name == method_name
            for member in node.body
        )
        for node in tree.body
    )


def _test_selector_exists(root: Path, selector: str) -> bool:
    module_name, class_name, method_name = selector.rsplit(".", 2)
    module_path = root.joinpath(*module_name.split(".")).with_suffix(".py")
    if not module_path.is_file():
        return False
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    return any(
        isinstance(node, ast.ClassDef)
        and node.name == class_name
        and any(
            isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
            and member.name == method_name
            for member in node.body
        )
        for node in tree.body
    )


def _run_selectors(root: Path, selectors: list[str]) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-B", "-m", "unittest", *selectors],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = ["CoreValidationError", "project_core_evidence", "validate_core"]
