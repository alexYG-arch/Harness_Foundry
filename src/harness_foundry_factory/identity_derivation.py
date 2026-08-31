"""Exact three-layer identity derivation with live-state freshness binding."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from .authority_adapter import (
    AuthorityAdapterError,
    SQLiteEventStoreAuthorityAdapter,
)


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CHANGE_CLASSES = (
    "NO_REBIND_REQUIRED",
    "MACHINE_GRANT_REBIND_REQUIRED",
    "HUMAN_REAUTHORIZATION_REQUIRED",
)
SEMANTIC_CONTRACT_FIELDS = {
    "contract_id",
    "contract_version",
    "normative_behavior_sha256",
    "input_schema_sha256",
    "output_schema_sha256",
    "invariants_sha256",
}
IMPLEMENTATION_RELEASE_FIELDS = {
    "release_id",
    "exact_executor_bytes_sha256",
    "artifact_bytes_sha256",
    "sbom_sha256",
    "provenance_sha256",
    "toolchain_sha256",
}
AUTHORIZATION_RISK_FIELDS = {
    "risk_profile_id",
    "scope_sha256",
    "permissions_sha256",
    "write_roots_sha256",
    "network_policy_sha256",
    "secret_access_policy_sha256",
    "external_effect_class",
    "budget_sha256",
    "stop_gates_sha256",
}
CURRENT_STATE_FIELDS = {
    "authority_scope",
    "instance_id",
    "state_revision",
    "current_state_sha256",
    "event_store_tip_sha256",
}
IDENTITY_BUNDLE_FIELDS = {
    "schema_version",
    "identity_derivation_id",
    "input_sha256",
    "semantic_contract_identity_sha256",
    "implementation_release_identity_sha256",
    "authorization_risk_identity_sha256",
    *CURRENT_STATE_FIELDS,
    "creates_authority",
    "identity_bundle_sha256",
}


class IdentityDerivationError(ValueError):
    pass


def _hash(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise IdentityDerivationError("identity input is not canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def _require_sha256(name: str, value: Any) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise IdentityDerivationError(f"{name} must be a lowercase SHA-256")
    return value


def _require_exact_mapping(
    name: str,
    value: Mapping[str, Any],
    expected_fields: set[str],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected_fields:
        raise IdentityDerivationError(f"{name} fields are not exact")
    projected = dict(value)
    for field, field_value in projected.items():
        if field.endswith("sha256"):
            _require_sha256(f"{name}.{field}", field_value)
        elif field == "state_revision":
            if (
                isinstance(field_value, bool)
                or not isinstance(field_value, int)
                or field_value < 0
            ):
                raise IdentityDerivationError(
                    f"{name}.state_revision must be a non-negative integer"
                )
        elif not isinstance(field_value, str) or not field_value:
            raise IdentityDerivationError(f"{name}.{field} must be a non-empty string")
    _hash(projected)
    return projected


def _identity(identity_id: str, value: Mapping[str, Any]) -> str:
    return _hash({"identity_id": identity_id, "normative_fields": dict(value)})


def derive_identity_bundle(
    *,
    semantic_contract: Mapping[str, Any],
    implementation_release: Mapping[str, Any],
    authorization_risk: Mapping[str, Any],
    authority_adapter: SQLiteEventStoreAuthorityAdapter,
) -> dict[str, Any]:
    """Derive identities using live state read internally by the exact adapter."""

    semantic = _require_exact_mapping(
        "semantic_contract", semantic_contract, SEMANTIC_CONTRACT_FIELDS
    )
    implementation = _require_exact_mapping(
        "implementation_release",
        implementation_release,
        IMPLEMENTATION_RELEASE_FIELDS,
    )
    risk = _require_exact_mapping(
        "authorization_risk", authorization_risk, AUTHORIZATION_RISK_FIELDS
    )
    if type(authority_adapter) is not SQLiteEventStoreAuthorityAdapter:
        raise IdentityDerivationError(
            "exact Hash-bound authority adapter type is required"
        )
    try:
        state = _require_exact_mapping(
            "current_state",
            authority_adapter.read_current_state(),
            CURRENT_STATE_FIELDS,
        )
        release_context = authority_adapter.read_release_context()
    except AuthorityAdapterError as exc:
        raise IdentityDerivationError("Event Store authority read failed closed") from exc
    inputs = {
        "semantic_contract": semantic,
        "implementation_release": implementation,
        "authorization_risk": risk,
        "authority_adapter_binding_sha256": authority_adapter.binding_sha256,
        "adapter_derived_current_state": state,
    }
    semantic_identity = _identity("SEMANTIC_CONTRACT_IDENTITY", semantic)
    risk_identity = _identity("AUTHORIZATION_RISK_IDENTITY", risk)
    if (
        release_context.get("semantic_contract_identity_sha256")
        != semantic_identity
        or release_context.get("authorization_risk_identity_sha256")
        != risk_identity
    ):
        raise IdentityDerivationError(
            "identity inputs do not match Event Store authority identities"
        )
    body = {
        "schema_version": "2.9",
        "identity_derivation_id": "V29_THREE_LAYER_IDENTITY_DERIVATION_V2",
        "input_sha256": _hash(inputs),
        "semantic_contract_identity_sha256": semantic_identity,
        "implementation_release_identity_sha256": _identity(
            "IMPLEMENTATION_RELEASE_IDENTITY", implementation
        ),
        "authorization_risk_identity_sha256": risk_identity,
        **state,
        "creates_authority": False,
    }
    return {**body, "identity_bundle_sha256": _hash(body)}


def _validate_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(bundle, Mapping) or set(bundle) != IDENTITY_BUNDLE_FIELDS:
        raise IdentityDerivationError("identity bundle fields are not exact")
    projected = dict(bundle)
    supplied_hash = projected.pop("identity_bundle_sha256")
    for field in (
        "input_sha256",
        "semantic_contract_identity_sha256",
        "implementation_release_identity_sha256",
        "authorization_risk_identity_sha256",
        "current_state_sha256",
        "event_store_tip_sha256",
        "identity_bundle_sha256",
    ):
        _require_sha256(field, bundle.get(field))
    _require_exact_mapping(
        "bundle.current_state",
        {field: bundle[field] for field in CURRENT_STATE_FIELDS},
        CURRENT_STATE_FIELDS,
    )
    if (
        bundle.get("schema_version") != "2.9"
        or bundle.get("identity_derivation_id")
        != "V29_THREE_LAYER_IDENTITY_DERIVATION_V2"
        or bundle.get("creates_authority") is not False
        or supplied_hash != _hash(projected)
    ):
        raise IdentityDerivationError("identity bundle hash or semantics are invalid")
    return dict(bundle)


def classify_identity_change(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
) -> dict[str, Any]:
    """Route semantic or risk changes to humans and fresh byte/state changes to rebind."""

    before = _validate_bundle(previous)
    after = _validate_bundle(current)
    semantic_changed = (
        before["semantic_contract_identity_sha256"]
        != after["semantic_contract_identity_sha256"]
    )
    risk_changed = (
        before["authorization_risk_identity_sha256"]
        != after["authorization_risk_identity_sha256"]
    )
    implementation_changed = (
        before["implementation_release_identity_sha256"]
        != after["implementation_release_identity_sha256"]
    )
    state_changed = any(before[field] != after[field] for field in CURRENT_STATE_FIELDS)
    if semantic_changed or risk_changed:
        change_class = "HUMAN_REAUTHORIZATION_REQUIRED"
    elif implementation_changed or state_changed:
        change_class = "MACHINE_GRANT_REBIND_REQUIRED"
    else:
        change_class = "NO_REBIND_REQUIRED"
    body = {
        "schema_version": "2.9",
        "classification_id": "V29_IDENTITY_CHANGE_CLASSIFICATION_V2",
        "previous_identity_bundle_sha256": before["identity_bundle_sha256"],
        "current_identity_bundle_sha256": after["identity_bundle_sha256"],
        "semantic_contract_changed": semantic_changed,
        "implementation_release_changed": implementation_changed,
        "authorization_risk_changed": risk_changed,
        "current_state_changed": state_changed,
        "change_class": change_class,
        "human_gate_required": change_class == "HUMAN_REAUTHORIZATION_REQUIRED",
        "machine_grant_rebind_required": change_class
        == "MACHINE_GRANT_REBIND_REQUIRED",
        "creates_authority": False,
    }
    return {**body, "classification_sha256": _hash(body)}


def build_machine_grant_binding(
    identity_bundle: Mapping[str, Any],
    *,
    authority_adapter: SQLiteEventStoreAuthorityAdapter,
    exact_executor_release_sha256: str,
    exact_artifact_release_sha256: str,
) -> dict[str, Any]:
    """Re-read live state internally, then build an authority-neutral proposal."""

    bundle = _validate_bundle(identity_bundle)
    if type(authority_adapter) is not SQLiteEventStoreAuthorityAdapter:
        raise IdentityDerivationError(
            "exact Hash-bound authority adapter type is required"
        )
    try:
        live_state = _require_exact_mapping(
            "authoritative_current_state",
            authority_adapter.read_current_state(),
            CURRENT_STATE_FIELDS,
        )
    except AuthorityAdapterError as exc:
        raise IdentityDerivationError("Event Store authority read failed closed") from exc
    if any(bundle[field] != live_state[field] for field in CURRENT_STATE_FIELDS):
        raise IdentityDerivationError(
            "identity bundle does not match authoritative current state"
        )
    executor_hash = _require_sha256(
        "exact_executor_release_sha256", exact_executor_release_sha256
    )
    artifact_hash = _require_sha256(
        "exact_artifact_release_sha256", exact_artifact_release_sha256
    )
    body = {
        "schema_version": "2.9",
        "binding_id": "V29_MACHINE_GRANT_BINDING_V2",
        "binding_status": "PLANNED_NOT_GRANTED",
        "authorization_risk_identity_sha256": bundle[
            "authorization_risk_identity_sha256"
        ],
        "semantic_contract_identity_sha256": bundle[
            "semantic_contract_identity_sha256"
        ],
        "implementation_release_identity_sha256": bundle[
            "implementation_release_identity_sha256"
        ],
        "exact_executor_release_sha256": executor_hash,
        "exact_artifact_release_sha256": artifact_hash,
        **live_state,
        "authoritative_adapter_checked": True,
        "authority_adapter_binding_sha256": authority_adapter.binding_sha256,
        "human_authorization_granted": False,
        "machine_grant_issued": False,
        "creates_authority": False,
    }
    return {**body, "binding_sha256": _hash(body)}


__all__ = [
    "AUTHORIZATION_RISK_FIELDS",
    "CHANGE_CLASSES",
    "CURRENT_STATE_FIELDS",
    "IMPLEMENTATION_RELEASE_FIELDS",
    "SEMANTIC_CONTRACT_FIELDS",
    "IdentityDerivationError",
    "build_machine_grant_binding",
    "classify_identity_change",
    "derive_identity_bundle",
]
