"""Risk-scoped assurance profiles for Start Package negative cases.

This module is deliberately independent from the Candidate producer.  It owns
only applicability: it does not generate cases, mutate Requirement IR, or
change the repository-wide release profile constants.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar


AUTHORING_LOCAL = "AUTHORING_LOCAL"
LOCAL_EXEC_UNTRUSTED_INPUT = "LOCAL_EXEC_UNTRUSTED_INPUT"
DISTRIBUTED_RELEASE_ADVERSARIAL = "DISTRIBUTED_RELEASE_ADVERSARIAL"

# Existing v2.9 core records use this value.  It describes a trusted operator,
# not trusted repository input, so its closest bounded execution profile is the
# local-execution profile below.
LEGACY_SELF_USE_LOCAL_TRUSTED_OPERATOR = "SELF_USE_LOCAL_TRUSTED_OPERATOR"


class UnknownAssuranceProfileError(ValueError):
    """Raised when assurance applicability cannot be resolved safely."""


class UnknownHF28NegativeCaseError(ValueError):
    """Raised rather than silently enabling or disabling an unknown HF28 case."""


@dataclass(frozen=True, slots=True)
class AssuranceProfile:
    """Resolved cumulative controls for one Start Package assurance profile."""

    profile_id: str
    level: int
    description: str
    controls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NegativeCaseRoute:
    """Minimum assurance level and auditable reason for one HF28 case."""

    case_id: str
    minimum_profile: str
    control_id: str
    rationale: str
    failure_action: str


_AUTHORING_CONTROLS = (
    "REQUIREMENT_AND_PHASE_TRANSITION_INTEGRITY",
    "SOURCE_PIN_AND_BYTE_INTEGRITY",
    "OUTPUT_ROOT_CONFINEMENT",
    "CANDIDATE_ATOMIC_PUBLICATION_IMMUTABILITY",
    "EXACT_SCOPE_AUTHORIZATION",
)

_LOCAL_EXECUTION_CONTROLS = (
    "PUBLIC_REPOSITORY_INPUT_TREATED_AS_UNTRUSTED",
    "TARGET_SKILL_EXECUTION_DENY_BY_DEFAULT",
    "NETWORK_EGRESS_DENY_BY_DEFAULT",
    "AUTOMATIC_INSTALL_DENIED",
    "ONE_JOB_READ_WRITE_LEASE",
    "SIDE_EFFECT_IDEMPOTENCY_AND_RECONCILIATION",
    "STAGE_EVIDENCE_COMPLETENESS",
    "EXECUTOR_AND_OUTPUT_PROVENANCE",
)

_DISTRIBUTED_RELEASE_CONTROLS = (
    "ATTESTATION_REPLAY_PROTECTION",
    "CERTIFICATE_INVALIDATION",
    "THREE_PROJECT_RELEASE_ORDER",
    "TOOL_DISTRIBUTION_INTEGRITY",
    "SINGLE_ACTIVE_WORKPACK_ACROSS_PROJECTS",
    "RELEASE_ARTIFACT_AND_ENVIRONMENT_BINDING",
    "CROSS_PROJECT_AUTHORITY_SEPARATION",
)


def _cumulative(*groups: tuple[str, ...]) -> tuple[str, ...]:
    """Return stable, duplicate-free cumulative controls."""

    return tuple(dict.fromkeys(control for group in groups for control in group))


_PROFILES = {
    AUTHORING_LOCAL: AssuranceProfile(
        profile_id=AUTHORING_LOCAL,
        level=1,
        description=(
            "Local Candidate authoring with frozen-source, root-confinement, "
            "immutability, phase-integrity, and authorization controls only."
        ),
        controls=_AUTHORING_CONTROLS,
    ),
    LOCAL_EXEC_UNTRUSTED_INPUT: AssuranceProfile(
        profile_id=LOCAL_EXEC_UNTRUSTED_INPUT,
        level=2,
        description=(
            "Trusted local operator executing against untrusted repository "
            "input with bounded network, installation, lease, side-effect, "
            "stage-evidence, and provenance controls."
        ),
        controls=_cumulative(_AUTHORING_CONTROLS, _LOCAL_EXECUTION_CONTROLS),
    ),
    DISTRIBUTED_RELEASE_ADVERSARIAL: AssuranceProfile(
        profile_id=DISTRIBUTED_RELEASE_ADVERSARIAL,
        level=3,
        description=(
            "Distributed release and certification under an adversarial "
            "threat model, including replay, certificate, multi-project, "
            "tool-distribution, and authority-separation controls."
        ),
        controls=_cumulative(
            _AUTHORING_CONTROLS,
            _LOCAL_EXECUTION_CONTROLS,
            _DISTRIBUTED_RELEASE_CONTROLS,
        ),
    ),
}

_PROFILE_ALIASES = {
    LEGACY_SELF_USE_LOCAL_TRUSTED_OPERATOR: LOCAL_EXEC_UNTRUSTED_INPUT,
}


def normalize_assurance_profile(value: object) -> str:
    """Return a canonical profile ID or fail closed for an unknown value."""

    if not isinstance(value, str) or not value.strip():
        raise UnknownAssuranceProfileError(
            "assurance profile must be a non-empty string"
        )
    normalized = value.strip().upper().replace("-", "_")
    normalized = _PROFILE_ALIASES.get(normalized, normalized)
    if normalized not in _PROFILES:
        raise UnknownAssuranceProfileError(
            f"unknown assurance profile: {value!r}"
        )
    return normalized


def resolve_assurance_profile(value: object) -> AssuranceProfile:
    """Resolve a canonical or supported legacy profile to immutable policy."""

    return _PROFILES[normalize_assurance_profile(value)]


def assurance_profile_for_start_package(
    requirement_ir: Mapping[str, Any],
) -> AssuranceProfile:
    """Resolve Start Package assurance without changing global core profiles.

    An explicit Start Package profile wins. A personal-local permission policy
    selects the local execution profile because public repository content is
    still untrusted input even when the operator is trusted. Older or
    unspecified requirements retain the distributed profile, preserving the
    previous fail-closed behavior.
    """

    target = requirement_ir.get("target")
    target = target if isinstance(target, Mapping) else {}
    explicit = target.get("start_package_assurance_profile")
    if explicit is not None:
        return resolve_assurance_profile(explicit)
    permission_policy = target.get("start_package_immutability_policy")
    permission_policy = (
        permission_policy if isinstance(permission_policy, Mapping) else {}
    )
    if (
        permission_policy.get("physical_permission_enforcement")
        == "BEST_EFFORT_PERSONAL_LOCAL"
    ):
        return resolve_assurance_profile(LOCAL_EXEC_UNTRUSTED_INPUT)
    return resolve_assurance_profile(DISTRIBUTED_RELEASE_ADVERSARIAL)


def _route(
    case_id: str,
    minimum_profile: str,
    control_id: str,
    rationale: str,
    failure_action: str,
) -> NegativeCaseRoute:
    return NegativeCaseRoute(
        case_id=case_id,
        minimum_profile=minimum_profile,
        control_id=control_id,
        rationale=rationale,
        failure_action=failure_action,
    )


_HF28_NEGATIVE_CASE_ROUTES = {
    route.case_id: route
    for route in (
        _route(
            "NEG-HF28-CODEX-SELF-REPORT",
            LOCAL_EXEC_UNTRUSTED_INPUT,
            "EXECUTOR_AND_OUTPUT_PROVENANCE",
            "A local run must not accept an executor's uncorroborated invocation claim.",
            "INVOCATION_UNVERIFIED",
        ),
        _route(
            "NEG-HF28-ATTESTATION-REPLAY",
            DISTRIBUTED_RELEASE_ADVERSARIAL,
            "ATTESTATION_REPLAY_PROTECTION",
            "Replay protection is required when attestations cross release trust domains.",
            "ATTESTATION_REPLAY_REJECTED",
        ),
        _route(
            "NEG-HF28-OUTPUT-SUBSTITUTION",
            LOCAL_EXEC_UNTRUSTED_INPUT,
            "EXECUTOR_AND_OUTPUT_PROVENANCE",
            "Bytes returned by an untrusted-input execution must remain bound to its receipt.",
            "OUTPUT_SUBSTITUTION_DETECTED",
        ),
        _route(
            "NEG-HF28-STUB-EXECUTOR",
            LOCAL_EXEC_UNTRUSTED_INPUT,
            "EXECUTOR_AND_OUTPUT_PROVENANCE",
            "A local execution must distinguish the configured executor from a stub or fake.",
            "EXECUTOR_IDENTITY_UNTRUSTED",
        ),
        _route(
            "NEG-HF28-P3-SKIP",
            DISTRIBUTED_RELEASE_ADVERSARIAL,
            "THREE_PROJECT_RELEASE_ORDER",
            "Cross-project release certification depends on the complete phase-lock sequence.",
            "ILLEGAL_PHASE_TRANSITION",
        ),
        _route(
            "NEG-HF28-STALE-HASH",
            AUTHORING_LOCAL,
            "REQUIREMENT_AND_PHASE_TRANSITION_INTEGRITY",
            "Local authoring must reject a stale predecessor binding before publication.",
            "STALE_PREDECESSOR_HASH",
        ),
        _route(
            "NEG-HF28-MISSING-STAGE-RECEIPT",
            LOCAL_EXEC_UNTRUSTED_INPUT,
            "STAGE_EVIDENCE_COMPLETENESS",
            "A final runtime artifact cannot replace the required resumable stage evidence.",
            "STAGE_RECEIPT_MISSING",
        ),
        _route(
            "NEG-HF28-SOURCE-DRIVER-FALLBACK",
            LOCAL_EXEC_UNTRUSTED_INPUT,
            "EXECUTOR_AND_OUTPUT_PROVENANCE",
            "Local execution must use the frozen runtime entrypoint rather "
            "than mutable source fallback.",
            "RUNTIME_ENTRYPOINT_FALLBACK_REJECTED",
        ),
        _route(
            "NEG-HF28-CERTIFICATE-REUSE",
            DISTRIBUTED_RELEASE_ADVERSARIAL,
            "CERTIFICATE_INVALIDATION",
            "A distributed certificate must not survive changes to its "
            "checker or scenario binding.",
            "CERTIFICATE_INVALIDATED",
        ),
        _route(
            "NEG-HF28-AUTH-SCOPE",
            AUTHORING_LOCAL,
            "EXACT_SCOPE_AUTHORIZATION",
            "Local authoring and later execution must reject absent, expired, "
            "or mismatched authority.",
            "AUTHORIZATION_INVALID",
        ),
        _route(
            "NEG-HF28-MULTIPLE-NEXT-LEASE",
            LOCAL_EXEC_UNTRUSTED_INPUT,
            "ONE_JOB_READ_WRITE_LEASE",
            "Local execution requires one unambiguous next action and one current job lease.",
            "STATE_CONFLICT",
        ),
        _route(
            "NEG-HF28-RELEASE-SKIP",
            DISTRIBUTED_RELEASE_ADVERSARIAL,
            "THREE_PROJECT_RELEASE_ORDER",
            "Distributed release certification must retain all declared predecessor stages.",
            "RELEASE_PREDECESSOR_MISSING",
        ),
        _route(
            "NEG-HF28-LOOP-OSCILLATION",
            LOCAL_EXEC_UNTRUSTED_INPUT,
            "SIDE_EFFECT_IDEMPOTENCY_AND_RECONCILIATION",
            "A running local control loop must stop rather than repeat non-progressing actions.",
            "LOOP_ESCALATION_REQUIRED",
        ),
        _route(
            "NEG-HF28-CRASH-DUPLICATE",
            LOCAL_EXEC_UNTRUSTED_INPUT,
            "SIDE_EFFECT_IDEMPOTENCY_AND_RECONCILIATION",
            "A crash boundary must not cause an already-issued side effect to be repeated.",
            "DUPLICATE_SIDE_EFFECT_REJECTED",
        ),
        _route(
            "NEG-HF28-UPSTREAM-INVALIDATION",
            DISTRIBUTED_RELEASE_ADVERSARIAL,
            "RELEASE_ARTIFACT_AND_ENVIRONMENT_BINDING",
            "A distributed release must invalidate dependants when an upstream binding changes.",
            "DEPENDENT_STATE_INVALIDATED",
        ),
        _route(
            "NEG-HF28-AUTO-REAL-INSTALL",
            LOCAL_EXEC_UNTRUSTED_INPUT,
            "AUTOMATIC_INSTALL_DENIED",
            "Untrusted input must never trigger an installation without explicit authority.",
            "REAL_TARGET_INSTALL_AUTHORIZATION_REQUIRED",
        ),
        _route(
            "NEG-HF28-THREE-PROJECT-ORDER",
            DISTRIBUTED_RELEASE_ADVERSARIAL,
            "THREE_PROJECT_RELEASE_ORDER",
            "Only the distributed release profile owns Lab, Linkage, and Main ordering risk.",
            "ENGINEERING_PREDECESSOR_MISSING",
        ),
        _route(
            "NEG-HF28-DUAL-ACTIVE-WORKPACK",
            DISTRIBUTED_RELEASE_ADVERSARIAL,
            "SINGLE_ACTIVE_WORKPACK_ACROSS_PROJECTS",
            "Concurrent active Workpacks are a cross-project release coordination threat.",
            "STATE_CONFLICT_HARD_STOP",
        ),
        _route(
            "NEG-HF28-CANDIDATE-ENV-MISMATCH",
            DISTRIBUTED_RELEASE_ADVERSARIAL,
            "RELEASE_ARTIFACT_AND_ENVIRONMENT_BINDING",
            "Installability and Lab certification must use the same "
            "distributed release Candidate.",
            "CANDIDATE_HASH_MISMATCH",
        ),
        _route(
            "NEG-HF28-TOOL-DISTRIBUTION-DRIFT",
            DISTRIBUTED_RELEASE_ADVERSARIAL,
            "TOOL_DISTRIBUTION_INTEGRITY",
            "Distributed certification must invalidate results after tool distribution changes.",
            "TOOL_DISTRIBUTION_HASH_CHANGED",
        ),
        _route(
            "NEG-HF28-B0-B1-ORDER",
            DISTRIBUTED_RELEASE_ADVERSARIAL,
            "THREE_PROJECT_RELEASE_ORDER",
            "B0 and B1 ordering protects the distributed immutable release handoff.",
            "RELEASE_PREDECESSOR_MISSING",
        ),
        _route(
            "NEG-HF28-LINKAGE-AUTHORITY",
            DISTRIBUTED_RELEASE_ADVERSARIAL,
            "CROSS_PROJECT_AUTHORITY_SEPARATION",
            "Linkage authority separation is meaningful only in the multi-project release path.",
            "AUTHORITY_MISMATCH",
        ),
    )
}


def resolve_hf28_negative_case_route(case_id: object) -> NegativeCaseRoute:
    """Resolve one known HF28 route; unknown case IDs fail closed."""

    if not isinstance(case_id, str) or not case_id.strip():
        raise UnknownHF28NegativeCaseError(
            "HF28 negative case ID must be a non-empty string"
        )
    normalized = case_id.strip().upper()
    try:
        return _HF28_NEGATIVE_CASE_ROUTES[normalized]
    except KeyError as exc:
        raise UnknownHF28NegativeCaseError(
            f"unknown HF28 negative case: {case_id!r}"
        ) from exc


def hf28_negative_case_routes() -> tuple[NegativeCaseRoute, ...]:
    """Return all routes in their stable policy order."""

    return tuple(_HF28_NEGATIVE_CASE_ROUTES.values())


def is_hf28_negative_case_applicable(case_id: object, profile: object) -> bool:
    """Return whether a known case applies to the resolved cumulative profile."""

    route = resolve_hf28_negative_case_route(case_id)
    selected = resolve_assurance_profile(profile)
    minimum = resolve_assurance_profile(route.minimum_profile)
    return selected.level >= minimum.level


def filter_hf28_negative_case_ids(
    case_ids: Iterable[object], profile: object
) -> tuple[str, ...]:
    """Filter known case IDs without silently accepting unknown policy input."""

    selected = resolve_assurance_profile(profile)
    result: list[str] = []
    for case_id in case_ids:
        route = resolve_hf28_negative_case_route(case_id)
        minimum = resolve_assurance_profile(route.minimum_profile)
        if selected.level >= minimum.level:
            result.append(route.case_id)
    return tuple(result)


_Spec = TypeVar("_Spec")


def _case_id_from_spec(spec: Any) -> object:
    if isinstance(spec, Mapping):
        return spec.get("case_id")
    if isinstance(spec, Sequence) and not isinstance(spec, (str, bytes)) and spec:
        return spec[0]
    raise UnknownHF28NegativeCaseError(
        "HF28 negative case spec must expose case_id or use case ID as item zero"
    )


def filter_hf28_negative_case_specs(
    specs: Iterable[_Spec], profile: object
) -> tuple[_Spec, ...]:
    """Filter tuple- or mapping-shaped HF28 specs while preserving item identity."""

    selected = resolve_assurance_profile(profile)
    result: list[_Spec] = []
    for spec in specs:
        route = resolve_hf28_negative_case_route(_case_id_from_spec(spec))
        minimum = resolve_assurance_profile(route.minimum_profile)
        if selected.level >= minimum.level:
            result.append(spec)
    return tuple(result)
