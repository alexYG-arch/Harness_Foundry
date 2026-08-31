"""Trusted Product, Safety and Release closure-lane evaluation.

Receipts are evidence, never authority.  This module accepts only the exact
Hash-bound Event Store authority adapter and asks it to construct the Release
Context directly from the native append-only store.  A caller-supplied mapping
can therefore never become trusted merely by carrying a valid self-Hash.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable, Mapping

from .authority_adapter import (
    AuthorityAdapterError,
    SQLiteEventStoreAuthorityAdapter,
)


LANE_IDS = ("PRODUCT", "SAFETY", "RELEASE")
LINKAGE_ID = "COMPATIBILITY_LINKAGE"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BINDING_FIELDS = (
    "authority_scope",
    "instance_id",
    "requirement_epoch",
    "semantic_contract_identity_sha256",
    "authorization_risk_identity_sha256",
)
CURRENT_STATE_FIELDS = (
    "state_revision",
    "current_state_sha256",
    "event_store_tip_sha256",
)
RELEASE_ARTIFACT_HASH_FIELDS = (
    "candidate_content_sha256",
    "requirement_ir_sha256",
    "executor_release_sha256",
    "human_gate_receipt_sha256",
)
ISSUER_ANCHOR_FIELDS = {
    "issuer_control_domain_id",
    "issuance_event_id",
    "issuance_event_revision",
    "issuance_event_sha256",
}
RELEASE_CONTEXT_BODY_FIELDS = {
    "schema_version",
    *BINDING_FIELDS,
    *CURRENT_STATE_FIELDS,
    *RELEASE_ARTIFACT_HASH_FIELDS,
    "authorized_issuers",
    "consumed_receipt_ids",
}
RELEASE_CONTEXT_FIELDS = RELEASE_CONTEXT_BODY_FIELDS | {"release_context_sha256"}
AUTHORITY_PROOF_FIELDS = {
    "receipt_id",
    *ISSUER_ANCHOR_FIELDS,
    "release_context_sha256",
    "anti_replay_token",
}
LANE_RECEIPT_FIELDS = {
    "schema_version",
    "lane_id",
    "status",
    *BINDING_FIELDS,
    *AUTHORITY_PROOF_FIELDS,
    "creates_authority",
    "receipt_sha256",
}
LINKAGE_RECEIPT_FIELDS = LANE_RECEIPT_FIELDS - {"lane_id"}


class ClosureLaneError(ValueError):
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
        raise ClosureLaneError("value is not canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def _require_non_empty_string(label: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ClosureLaneError(f"{label} must be a non-empty string")
    return value


def _require_sha256(label: str, value: Any) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ClosureLaneError(f"{label} must be a lowercase SHA-256")
    return value


def _require_revision(label: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ClosureLaneError(f"{label} must be a non-negative integer")
    return value


def seal_receipt(receipt_body: Mapping[str, Any]) -> dict[str, Any]:
    """Integrity-seal receipt evidence; this helper does not issue a receipt."""

    if not isinstance(receipt_body, Mapping) or "receipt_sha256" in receipt_body:
        raise ClosureLaneError("receipt body must omit receipt_sha256")
    body = dict(receipt_body)
    return {**body, "receipt_sha256": _hash(body)}


def derive_anti_replay_token(receipt_body: Mapping[str, Any]) -> str:
    """Derive the one-time token bound to receipt, context and issuer event."""

    required = (
        "receipt_id",
        "release_context_sha256",
        "issuer_control_domain_id",
        "issuance_event_id",
        "issuance_event_revision",
        "issuance_event_sha256",
    )
    missing = [field for field in required if field not in receipt_body]
    if missing:
        raise ClosureLaneError(f"anti-replay input is missing: {missing}")
    return _hash({field: receipt_body[field] for field in required})


def _validate_issuer_anchor(label: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != ISSUER_ANCHOR_FIELDS:
        raise ClosureLaneError(f"{label} issuer anchor fields are not exact")
    anchor = dict(value)
    _require_non_empty_string(
        f"{label}.issuer_control_domain_id", anchor["issuer_control_domain_id"]
    )
    _require_non_empty_string(f"{label}.issuance_event_id", anchor["issuance_event_id"])
    _require_revision(
        f"{label}.issuance_event_revision", anchor["issuance_event_revision"]
    )
    _require_sha256(
        f"{label}.issuance_event_sha256", anchor["issuance_event_sha256"]
    )
    return anchor


def _validate_release_context(context: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(context, Mapping) or set(context) != RELEASE_CONTEXT_FIELDS:
        raise ClosureLaneError("trusted Release Context fields are not exact")
    trusted = dict(context)
    supplied_hash = trusted.pop("release_context_sha256")
    _require_sha256("release_context_sha256", supplied_hash)
    if supplied_hash != _hash(trusted):
        raise ClosureLaneError("Release Context hash does not bind adapter output")
    if context.get("schema_version") != "2.9":
        raise ClosureLaneError("Release Context schema_version is invalid")
    for field in ("authority_scope", "instance_id"):
        _require_non_empty_string(field, context.get(field))
    _require_revision("requirement_epoch", context.get("requirement_epoch"))
    _require_revision("state_revision", context.get("state_revision"))
    for field in (
        "semantic_contract_identity_sha256",
        "authorization_risk_identity_sha256",
        "current_state_sha256",
        "event_store_tip_sha256",
    ):
        _require_sha256(field, context.get(field))
    issuers = context.get("authorized_issuers")
    expected_issuer_keys = {*LANE_IDS, LINKAGE_ID}
    if not isinstance(issuers, Mapping) or set(issuers) != expected_issuer_keys:
        raise ClosureLaneError("trusted issuer map is incomplete or has extra issuers")
    for key in sorted(expected_issuer_keys):
        anchor = _validate_issuer_anchor(f"authorized_issuers.{key}", issuers[key])
        if anchor["issuance_event_revision"] > context["state_revision"]:
            raise ClosureLaneError("issuer event is newer than trusted current state")
    consumed = context.get("consumed_receipt_ids")
    if (
        not isinstance(consumed, list)
        or any(not isinstance(item, str) or not item for item in consumed)
        or len(consumed) != len(set(consumed))
    ):
        raise ClosureLaneError("consumed_receipt_ids must be unique strings")
    return dict(context)


def _validate_receipt(
    receipt: Mapping[str, Any],
    *,
    expected_fields: set[str],
    expected_status: str,
    receipt_kind: str,
    trusted_context: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(receipt, Mapping) or set(receipt) != expected_fields:
        raise ClosureLaneError("receipt fields are not exact")
    projected = dict(receipt)
    supplied_hash = projected.pop("receipt_sha256")
    _require_sha256("receipt_sha256", supplied_hash)
    if supplied_hash != _hash(projected):
        raise ClosureLaneError("receipt_sha256 does not bind the receipt body")
    if (
        receipt.get("schema_version") != "2.9"
        or receipt.get("status") != expected_status
        or receipt.get("creates_authority") is not False
    ):
        raise ClosureLaneError("receipt lifecycle or authority semantics are invalid")
    for field in ("authority_scope", "instance_id", "receipt_id"):
        _require_non_empty_string(field, receipt.get(field))
    _require_revision("requirement_epoch", receipt.get("requirement_epoch"))
    _require_revision("issuance_event_revision", receipt.get("issuance_event_revision"))
    for field in (
        "semantic_contract_identity_sha256",
        "authorization_risk_identity_sha256",
        "issuance_event_sha256",
        "release_context_sha256",
        "anti_replay_token",
    ):
        _require_sha256(field, receipt.get(field))
    for field in BINDING_FIELDS:
        if receipt[field] != trusted_context[field]:
            raise ClosureLaneError(f"receipt {field} does not match trusted context")
    if receipt["release_context_sha256"] != trusted_context["release_context_sha256"]:
        raise ClosureLaneError("receipt is not bound to trusted Release Context")
    expected_anchor = trusted_context["authorized_issuers"][receipt_kind]
    for field in ISSUER_ANCHOR_FIELDS:
        if receipt[field] != expected_anchor[field]:
            raise ClosureLaneError("receipt issuer or authoritative event is not trusted")
    if receipt["receipt_id"] in trusted_context["consumed_receipt_ids"]:
        raise ClosureLaneError("receipt_id was already consumed")
    if receipt["anti_replay_token"] != derive_anti_replay_token(receipt):
        raise ClosureLaneError("anti_replay_token does not bind receipt authority proof")
    return dict(receipt)


def evaluate_final_release(
    receipts: Iterable[Mapping[str, Any]],
    *,
    compatibility_linkage_receipt: Mapping[str, Any],
    authority_adapter: SQLiteEventStoreAuthorityAdapter,
) -> dict[str, Any]:
    """Return a proposal after an internal, exact-adapter authority read."""

    if type(authority_adapter) is not SQLiteEventStoreAuthorityAdapter:
        raise ClosureLaneError("exact Hash-bound authority adapter type is required")
    try:
        trusted = _validate_release_context(
            authority_adapter.read_release_context()
        )
    except AuthorityAdapterError as exc:
        raise ClosureLaneError("Event Store authority read failed closed") from exc

    by_lane: dict[str, dict[str, Any]] = {}
    receipt_ids: set[str] = set()
    anti_replay_tokens: set[str] = set()
    for raw_receipt in receipts:
        if not isinstance(raw_receipt, Mapping):
            raise ClosureLaneError("lane receipt must be an object")
        lane_id = raw_receipt.get("lane_id")
        if lane_id not in LANE_IDS:
            raise ClosureLaneError(f"unknown lane_id: {lane_id}")
        if lane_id in by_lane:
            raise ClosureLaneError(f"duplicate lane receipt: {lane_id}")
        receipt = _validate_receipt(
            raw_receipt,
            expected_fields=LANE_RECEIPT_FIELDS,
            expected_status="CLOSED",
            receipt_kind=str(lane_id),
            trusted_context=trusted,
        )
        try:
            authority_adapter.assert_receipt_issued(
                str(lane_id),
                receipt["receipt_id"],
                {field: receipt[field] for field in ISSUER_ANCHOR_FIELDS},
            )
        except AuthorityAdapterError as exc:
            raise ClosureLaneError("lane receipt lacks Event Store authority") from exc
        by_lane[str(lane_id)] = receipt
        if receipt["receipt_id"] in receipt_ids:
            raise ClosureLaneError("duplicate receipt_id in release receipt set")
        if receipt["anti_replay_token"] in anti_replay_tokens:
            raise ClosureLaneError("duplicate anti_replay_token in release receipt set")
        receipt_ids.add(receipt["receipt_id"])
        anti_replay_tokens.add(receipt["anti_replay_token"])

    missing = [lane for lane in LANE_IDS if lane not in by_lane]
    if missing:
        raise ClosureLaneError(f"missing lane receipts: {missing}")

    linkage = _validate_receipt(
        compatibility_linkage_receipt,
        expected_fields=LINKAGE_RECEIPT_FIELDS,
        expected_status="PASS",
        receipt_kind=LINKAGE_ID,
        trusted_context=trusted,
    )
    try:
        authority_adapter.assert_receipt_issued(
            LINKAGE_ID,
            linkage["receipt_id"],
            {field: linkage[field] for field in ISSUER_ANCHOR_FIELDS},
        )
    except AuthorityAdapterError as exc:
        raise ClosureLaneError("linkage receipt lacks Event Store authority") from exc
    if linkage["receipt_id"] in receipt_ids:
        raise ClosureLaneError("duplicate receipt_id in release receipt set")
    if linkage["anti_replay_token"] in anti_replay_tokens:
        raise ClosureLaneError("duplicate anti_replay_token in release receipt set")

    body = {
        "schema_version": "2.9",
        "decision_id": "V29_FINAL_RELEASE_DECISION_V3",
        "decision": "RELEASE_ELIGIBILITY_PROPOSAL_NOT_AUTHORITY",
        "release_context_sha256": trusted["release_context_sha256"],
        "expected_event_store_tip_sha256": trusted["event_store_tip_sha256"],
        "lane_receipt_ids": {lane: by_lane[lane]["receipt_id"] for lane in LANE_IDS},
        "lane_receipt_sha256": {
            lane: by_lane[lane]["receipt_sha256"] for lane in LANE_IDS
        },
        "compatibility_linkage_receipt_id": linkage["receipt_id"],
        "compatibility_linkage_receipt_sha256": linkage["receipt_sha256"],
        "atomic_event_store_commit_required": True,
        "receipt_set_consumed": False,
        "release_ready_committed": False,
        "creates_authority": False,
    }
    return {**body, "decision_sha256": _hash(body)}


__all__ = [
    "AUTHORITY_PROOF_FIELDS",
    "BINDING_FIELDS",
    "LANE_IDS",
    "LINKAGE_ID",
    "ClosureLaneError",
    "derive_anti_replay_token",
    "evaluate_final_release",
    "seal_receipt",
]
