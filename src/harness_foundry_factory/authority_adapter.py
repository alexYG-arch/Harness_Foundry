"""Hash-bound authority reads for the native v2.9 SQLite Event Store.

The adapter is the only supported bridge from persistent control events to
Release Context and Current State values.  Callers cannot substitute a mapping
that merely looks authoritative.  Every read reopens the existing database,
verifies its identity, exact native schema, append-only guards and complete
program Hash chain, then derives the current values inside one read
transaction.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


ADAPTER_ID = "V29_SQLITE_EVENT_STORE_AUTHORITY_ADAPTER_V1"
LOGICAL_DATABASE_REF = (
    "harness-resource://execution/control/control-events.sqlite3"
)
LANE_IDS = ("PRODUCT", "SAFETY", "RELEASE")
LINKAGE_ID = "COMPATIBILITY_LINKAGE"
ISSUER_KEYS = (*LANE_IDS, LINKAGE_ID)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ADAPTER_CONTRACT_REF = "EVENT_STORE_AUTHORITY_ADAPTER_CONTRACT.json"
ARTIFACT_RESOLVER_ID = "V29_RELEASE_ARTIFACT_BYTES_RESOLVER_V1"
ADAPTER_BINDING_FIELDS = {
    "schema_version",
    "adapter_id",
    "program_id",
    "authority_scope",
    "instance_id",
    "requirement_epoch",
    "database_identity_sha256",
    "logical_database_ref",
    "adapter_implementation_sha256",
    "adapter_entrypoint_sha256",
    "adapter_contract_sha256",
    "authority_binding_receipt",
    "binding_sha256",
}
CURRENT_STATE_FIELDS = {
    "authority_scope",
    "instance_id",
    "state_revision",
    "current_state_sha256",
    "event_store_tip_sha256",
}
RELEASE_ARTIFACT_HASH_FIELDS = (
    "candidate_content_sha256",
    "requirement_ir_sha256",
    "executor_release_sha256",
    "human_gate_receipt_sha256",
)
RELEASE_CONTEXT_BODY_FIELDS = {
    "schema_version",
    "authority_scope",
    "instance_id",
    "requirement_epoch",
    "semantic_contract_identity_sha256",
    "authorization_risk_identity_sha256",
    "state_revision",
    "current_state_sha256",
    "event_store_tip_sha256",
    *RELEASE_ARTIFACT_HASH_FIELDS,
    "authorized_issuers",
    "consumed_receipt_ids",
}

_TABLE_COLUMNS: dict[str, tuple[tuple[str, str, int, int], ...]] = {
    "control_events": (
        ("sequence", "INTEGER", 0, 1),
        ("event_id", "TEXT", 1, 0),
        ("program_id", "TEXT", 1, 0),
        ("stream_revision", "INTEGER", 1, 0),
        ("event_type", "TEXT", 1, 0),
        ("payload_json", "TEXT", 1, 0),
        ("previous_event_hash", "TEXT", 0, 0),
        ("event_hash", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "control_idempotency": (
        ("program_id", "TEXT", 1, 1),
        ("idempotency_key", "TEXT", 1, 2),
        ("request_sha256", "TEXT", 1, 0),
        ("events_json", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
}
_TRIGGERS = {
    "control_events_reject_update": (
        "CREATE TRIGGER control_events_reject_update "
        "BEFORE UPDATE ON control_events BEGIN "
        "SELECT RAISE(ABORT, 'control_events is append-only'); END"
    ),
    "control_events_reject_delete": (
        "CREATE TRIGGER control_events_reject_delete "
        "BEFORE DELETE ON control_events BEGIN "
        "SELECT RAISE(ABORT, 'control_events is append-only'); END"
    ),
}
_ENTRYPOINT_DESCRIPTOR = {
    "module": "tools.harness_foundry_runtime.authority_adapter",
    "class": "SQLiteEventStoreAuthorityAdapter",
    "required_methods": [
        "read_current_state",
        "read_release_context",
        "assert_receipt_issued",
        "validate_precommit",
        "atomic_commit_release_ready",
    ],
}
_ACTIVATION_FIELDS = {"database_identity_sha256", "logical_database_ref"}
_STATE_EVENT_FIELDS = {
    "authority_scope",
    "instance_id",
    "requirement_epoch",
    "semantic_contract_identity_sha256",
    "authorization_risk_identity_sha256",
    "current_state_sha256",
    *RELEASE_ARTIFACT_HASH_FIELDS,
}
_ISSUANCE_FIELDS = {
    "receipt_kind",
    "receipt_id",
    "issuer_control_domain_id",
    "authority_scope",
    "instance_id",
    "requirement_epoch",
    "semantic_contract_identity_sha256",
    "authorization_risk_identity_sha256",
}
_CONSUMPTION_FIELDS = {"receipt_ids", "decision_sha256"}
_BINDING_AUTHORIZATION_FIELDS = {
    "schema_version",
    "receipt_kind",
    "receipt_id",
    "issuer_role",
    "trust_root_id",
    "issued_at",
    "not_before",
    "expires_at",
    "revoked",
    "one_shot",
    "authorization_purpose",
    "program_id",
    "authority_scope",
    "instance_id",
    "requirement_epoch",
    "database_identity_sha256",
    "logical_database_ref",
    "adapter_implementation_sha256",
    "adapter_entrypoint_sha256",
    "adapter_contract_sha256",
    "signature_base64",
}
_COMMIT_AUTHORIZATION_FIELDS = {
    "schema_version",
    "authorization_id",
    "authorization_purpose",
    "issuer_role",
    "trust_root_id",
    "issued_at",
    "not_before",
    "expires_at",
    "revoked",
    "one_shot",
    "program_id",
    "authority_scope",
    "instance_id",
    "requirement_epoch",
    "semantic_contract_identity_sha256",
    "authorization_risk_identity_sha256",
    "candidate_content_sha256",
    "requirement_ir_sha256",
    "executor_release_sha256",
    "human_gate_receipt_sha256",
    "expected_control_state_sha256",
    "authorized_event_store_tip_sha256",
    "proposal_decision_sha256",
    "lease_id",
    "lease_expires_at",
    "fencing_token",
    "idempotency_key",
    "status",
    "signature_base64",
}
_AUTHORIZATION_CONSUMPTION_FIELDS = {
    "authorization_id",
    "authorization_event_sha256",
    "decision_sha256",
    "fencing_token",
    "idempotency_key",
}


class AuthorityAdapterError(ValueError):
    """Closed failure raised before an unverified value crosses the adapter."""


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise AuthorityAdapterError("value is not canonical JSON") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_sha256(label: str, value: Any) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise AuthorityAdapterError(f"{label} must be a lowercase SHA-256")
    return value


def _parse_time(label: str, value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise AuthorityAdapterError(f"{label} must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuthorityAdapterError(f"{label} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise AuthorityAdapterError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _candidate_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_exact_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthorityAdapterError(f"{label} is unavailable or invalid") from exc
    if not isinstance(value, dict):
        raise AuthorityAdapterError(f"{label} must be an object")
    return value


def _receiver_trust_anchor(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate trust material supplied by the receiving control plane.

    The Candidate never selects this value.  Keeping the trust anchor outside
    the shareable package prevents an attacker from replacing both a public key
    and the artifacts that the key is meant to authenticate.
    """

    if not isinstance(value, Mapping):
        raise AuthorityAdapterError("receiver trust anchor must be an object")
    root = dict(value)
    expected = {
        "schema_version", "trust_root_id", "algorithm", "public_key_base64",
        "public_key_sha256", "purpose", "private_key_packaged",
        "creates_authority", "status", "trust_root_sha256",
    }
    if set(root) != expected:
        raise AuthorityAdapterError("authority trust-root fields are not exact")
    claimed = _require_sha256("trust_root_sha256", root["trust_root_sha256"])
    body = {key: value for key, value in root.items() if key != "trust_root_sha256"}
    if _hash(body) != claimed:
        raise AuthorityAdapterError("authority trust-root Hash is invalid")
    if (
        root["schema_version"] != "2.9"
        or root["algorithm"] != "ED25519"
        or root["purpose"]
        != "VERIFY_EVENT_STORE_BINDING_AND_RELEASE_COMMIT_AUTHORIZATION"
        or root["private_key_packaged"] is not False
        or root["creates_authority"] is not False
        or root["status"] != "PINNED_VERIFICATION_ROOT_NOT_AUTHORIZATION"
    ):
        raise AuthorityAdapterError("authority trust-root policy is invalid")
    try:
        public_bytes = base64.b64decode(root["public_key_base64"], validate=True)
    except (TypeError, ValueError) as exc:
        raise AuthorityAdapterError("authority public key encoding is invalid") from exc
    if len(public_bytes) != 32 or hashlib.sha256(public_bytes).hexdigest() != root[
        "public_key_sha256"
    ]:
        raise AuthorityAdapterError("authority public key identity is invalid")
    return root


def _adapter_contract_sha256() -> str:
    contract = _read_exact_json(
        _candidate_root() / ADAPTER_CONTRACT_REF,
        "authority adapter contract",
    )
    claimed = _require_sha256("contract_sha256", contract.get("contract_sha256"))
    if _hash({key: value for key, value in contract.items() if key != "contract_sha256"}) != claimed:
        raise AuthorityAdapterError("authority adapter contract Hash is invalid")
    return claimed


def _verify_signed_authority(
    document: Mapping[str, Any],
    *,
    exact_fields: set[str],
    expected_purpose: str,
    receiver_trust_anchor: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(document, Mapping) or set(document) != exact_fields:
        raise AuthorityAdapterError("signed authority fields are not exact")
    signed = dict(document)
    signature = signed.pop("signature_base64")
    root = _receiver_trust_anchor(receiver_trust_anchor)
    if (
        signed.get("schema_version") != "2.9"
        or signed.get("authorization_purpose") != expected_purpose
        or signed.get("issuer_role") != "CONTROL_PLANE_AUTHORITY"
        or signed.get("trust_root_id") != root["trust_root_id"]
        or signed.get("revoked") is not False
    ):
        raise AuthorityAdapterError("signed authority policy is invalid")
    now = datetime.now(timezone.utc)
    issued = _parse_time("issued_at", signed.get("issued_at"))
    not_before = _parse_time("not_before", signed.get("not_before"))
    expires = _parse_time("expires_at", signed.get("expires_at"))
    if issued > now or not_before > now or expires <= now or issued > expires:
        raise AuthorityAdapterError("signed authority is outside its validity window")
    try:
        signature_bytes = base64.b64decode(signature, validate=True)
        public_bytes = base64.b64decode(root["public_key_base64"], validate=True)
        Ed25519PublicKey.from_public_bytes(public_bytes).verify(
            signature_bytes,
            _canonical_json(signed).encode("utf-8"),
        )
    except (TypeError, ValueError, InvalidSignature) as exc:
        raise AuthorityAdapterError("signed authority signature is invalid") from exc
    return signed


def adapter_entrypoint_sha256() -> str:
    """Return the portable Hash of the closed production entrypoint surface."""

    return _hash(_ENTRYPOINT_DESCRIPTOR)


def build_adapter_binding(
    body: Mapping[str, Any],
    *,
    receiver_trust_anchor: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify external authority, then integrity-seal its exact local binding."""

    expected = ADAPTER_BINDING_FIELDS - {"binding_sha256"}
    if not isinstance(body, Mapping) or set(body) != expected:
        raise AuthorityAdapterError("adapter binding body fields are not exact")
    projected = dict(body)
    if projected.get("schema_version") != "2.9" or projected.get("adapter_id") != ADAPTER_ID:
        raise AuthorityAdapterError("adapter binding identity is invalid")
    if projected.get("logical_database_ref") != LOGICAL_DATABASE_REF:
        raise AuthorityAdapterError("adapter binding logical database ref is invalid")
    for field in (
        "program_id",
        "authority_scope",
        "instance_id",
    ):
        if not isinstance(projected.get(field), str) or not projected[field]:
            raise AuthorityAdapterError(f"{field} must be a non-empty string")
    epoch = projected.get("requirement_epoch")
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
        raise AuthorityAdapterError("requirement_epoch must be non-negative")
    for field in (
        "database_identity_sha256",
        "adapter_implementation_sha256",
        "adapter_entrypoint_sha256",
        "adapter_contract_sha256",
    ):
        _require_sha256(field, projected.get(field))
    if projected["adapter_implementation_sha256"] != _file_hash(Path(__file__).resolve()):
        raise AuthorityAdapterError("adapter implementation Hash is not authorized")
    if projected["adapter_entrypoint_sha256"] != adapter_entrypoint_sha256():
        raise AuthorityAdapterError("adapter entrypoint Hash is not authorized")
    if projected["adapter_contract_sha256"] != _adapter_contract_sha256():
        raise AuthorityAdapterError("actual adapter contract Hash is not authorized")
    receipt = _verify_signed_authority(
        projected["authority_binding_receipt"],
        exact_fields=_BINDING_AUTHORIZATION_FIELDS,
        expected_purpose="EVENT_STORE_ADAPTER_BINDING",
        receiver_trust_anchor=receiver_trust_anchor,
    )
    if receipt.get("receipt_kind") != "AUTHORITY_BINDING_RECEIPT":
        raise AuthorityAdapterError("authority binding receipt kind is invalid")
    if receipt.get("one_shot") is not False:
        raise AuthorityAdapterError("authority binding receipt must be reusable for reads")
    for field in (
        "program_id",
        "authority_scope",
        "instance_id",
        "requirement_epoch",
        "database_identity_sha256",
        "logical_database_ref",
        "adapter_implementation_sha256",
        "adapter_entrypoint_sha256",
        "adapter_contract_sha256",
    ):
        if receipt.get(field) != projected[field]:
            raise AuthorityAdapterError("authority binding receipt does not bind exact runtime")
    return {**projected, "binding_sha256": _hash(projected)}


@dataclass(frozen=True)
class _VerifiedSnapshot:
    current_state: dict[str, Any]
    release_context: dict[str, Any]
    issued_receipt_ids: dict[str, str]


class ReleaseArtifactBytesResolver:
    """Resolve the four authorized release hashes from receiver-side bytes.

    Paths are runtime bindings and are never persisted in the portable
    Candidate.  Files and directories are rejected when they contain symlinks
    or change while being read.  A directory Hash is the canonical Hash of its
    relative file names and individual byte Hashes.
    """

    def __init__(self, artifact_paths: Mapping[str, str | Path]) -> None:
        if not isinstance(artifact_paths, Mapping) or set(artifact_paths) != set(
            RELEASE_ARTIFACT_HASH_FIELDS
        ):
            raise AuthorityAdapterError("release artifact path fields are not exact")
        resolved: dict[str, Path] = {}
        for field, value in artifact_paths.items():
            supplied = Path(value).expanduser()
            absolute = supplied if supplied.is_absolute() else Path.cwd() / supplied
            existing_chain = [absolute, *absolute.parents]
            if any(path.exists() and path.is_symlink() for path in existing_chain):
                raise AuthorityAdapterError("release artifact path contains a symlink")
            resolved[field] = absolute.resolve(strict=True)
        self._paths = resolved

    @staticmethod
    def _stable_file_hash(path: Path) -> str:
        if path.is_symlink() or not path.is_file():
            raise AuthorityAdapterError("release artifact file is invalid")
        before = path.stat()
        content = path.read_bytes()
        after = path.stat()
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise AuthorityAdapterError("release artifact changed while hashing")
        return hashlib.sha256(content).hexdigest()

    @classmethod
    def _stable_artifact_hash(cls, path: Path) -> str:
        if path.is_symlink():
            raise AuthorityAdapterError("release artifact symlink is forbidden")
        if path.is_file():
            return cls._stable_file_hash(path)
        if not path.is_dir():
            raise AuthorityAdapterError("release artifact path is not readable")
        before = path.stat()
        entries: list[dict[str, str]] = []
        for item in sorted(path.rglob("*")):
            if item.is_symlink():
                raise AuthorityAdapterError("release artifact tree contains a symlink")
            if item.is_file():
                entries.append(
                    {
                        "path": item.relative_to(path).as_posix(),
                        "sha256": cls._stable_file_hash(item),
                    }
                )
        after = path.stat()
        if (
            before.st_dev,
            before.st_ino,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_mtime_ns,
        ):
            raise AuthorityAdapterError("release artifact tree changed while hashing")
        return _hash(entries)

    def resolve_hashes(self) -> dict[str, str]:
        return {
            field: self._stable_artifact_hash(self._paths[field])
            for field in RELEASE_ARTIFACT_HASH_FIELDS
        }


class SQLiteEventStoreAuthorityAdapter:
    """Exact, Hash-bound reader and atomic release-commit adapter."""

    def __init__(
        self,
        database_path: str | Path,
        binding: Mapping[str, Any],
        *,
        receiver_trust_anchor: Mapping[str, Any],
        artifact_resolver: ReleaseArtifactBytesResolver,
    ) -> None:
        path = Path(database_path).expanduser().resolve()
        if not path.is_file():
            raise AuthorityAdapterError("authorized Event Store must already exist")
        if not isinstance(binding, Mapping) or set(binding) != ADAPTER_BINDING_FIELDS:
            raise AuthorityAdapterError("adapter binding fields are not exact")
        supplied = dict(binding)
        supplied_hash = supplied.pop("binding_sha256")
        _require_sha256("binding_sha256", supplied_hash)
        trust_anchor = _receiver_trust_anchor(receiver_trust_anchor)
        if type(artifact_resolver) is not ReleaseArtifactBytesResolver:
            raise AuthorityAdapterError("exact production artifact resolver is required")
        if build_adapter_binding(
            supplied,
            receiver_trust_anchor=trust_anchor,
        )["binding_sha256"] != supplied_hash:
            raise AuthorityAdapterError("adapter binding Hash is invalid")
        self._database_path = path
        self._binding = dict(binding)
        self._receiver_trust_anchor = trust_anchor
        self._artifact_resolver = artifact_resolver
        self._read_verified_snapshot()

    @property
    def binding_sha256(self) -> str:
        return str(self._binding["binding_sha256"])

    def _connect(self, *, writable: bool = False) -> sqlite3.Connection:
        mode = "rw" if writable else "ro"
        uri = f"file:{quote(str(self._database_path))}?mode={mode}"
        connection = sqlite3.connect(uri, uri=True, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @staticmethod
    def _require_native_schema(connection: sqlite3.Connection) -> None:
        table_names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if not set(_TABLE_COLUMNS).issubset(table_names):
            raise AuthorityAdapterError("Event Store native tables are missing")
        for table, expected in _TABLE_COLUMNS.items():
            actual = tuple(
                (str(row[1]), str(row[2]).upper(), int(row[3]), int(row[5]))
                for row in connection.execute(f"PRAGMA table_info({table})")
            )
            if actual != expected:
                raise AuthorityAdapterError("Event Store native schema is invalid")
        triggers = {
            str(row[0]): " ".join(str(row[1] or "").split())
            for row in connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'trigger'"
            )
        }
        for name, sql in _TRIGGERS.items():
            if triggers.get(name) != " ".join(sql.split()):
                raise AuthorityAdapterError("Event Store append-only guard is invalid")

    def _events(self, connection: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT event_id, program_id, stream_revision, event_type,
                   payload_json, previous_event_hash, event_hash, created_at
            FROM control_events WHERE program_id = ? ORDER BY stream_revision
            """,
            (self._binding["program_id"],),
        ).fetchall()
        events: list[dict[str, Any]] = []
        previous_hash: str | None = None
        for expected_revision, row in enumerate(rows, 1):
            try:
                payload = json.loads(str(row["payload_json"]))
            except json.JSONDecodeError as exc:
                raise AuthorityAdapterError("Event Store payload JSON is invalid") from exc
            event = {
                "schema_version": "2.9",
                "event_id": str(row["event_id"]),
                "program_id": str(row["program_id"]),
                "stream_revision": int(row["stream_revision"]),
                "event_type": str(row["event_type"]),
                "payload": payload,
                "previous_event_hash": row["previous_event_hash"],
                "created_at": str(row["created_at"]),
            }
            claimed = str(row["event_hash"])
            if (
                event["stream_revision"] != expected_revision
                or event["previous_event_hash"] != previous_hash
                or _hash(event) != claimed
            ):
                raise AuthorityAdapterError("Event Store complete Hash chain is invalid")
            event["event_hash"] = claimed
            events.append(event)
            previous_hash = claimed
        if not events:
            raise AuthorityAdapterError("authorized Event Store stream is empty")
        return events

    def _snapshot_from_connection(
        self, connection: sqlite3.Connection
    ) -> _VerifiedSnapshot:
        self._require_native_schema(connection)
        events = self._events(connection)
        activation = [
            event for event in events
            if event["event_type"] == "CONTROL_EVENT_STORE_ACTIVATED"
        ]
        if len(activation) != 1 or set(activation[0]["payload"]) != _ACTIVATION_FIELDS:
            raise AuthorityAdapterError("Event Store activation identity is ambiguous")
        activation_payload = activation[0]["payload"]
        if (
            activation_payload["database_identity_sha256"]
            != self._binding["database_identity_sha256"]
            or activation_payload["logical_database_ref"]
            != self._binding["logical_database_ref"]
        ):
            raise AuthorityAdapterError("Event Store database identity is not authorized")

        states = [event for event in events if event["event_type"] == "CURRENT_STATE_COMMITTED"]
        if not states:
            raise AuthorityAdapterError("Event Store has no authoritative current state")
        state_event = states[-1]
        state = state_event["payload"]
        if set(state) != _STATE_EVENT_FIELDS:
            raise AuthorityAdapterError("authoritative current-state fields are not exact")
        for field in ("authority_scope", "instance_id", "requirement_epoch"):
            if state[field] != self._binding[field]:
                raise AuthorityAdapterError("authoritative current state is outside binding")
        for field in (
            "semantic_contract_identity_sha256",
            "authorization_risk_identity_sha256",
            "current_state_sha256",
            *RELEASE_ARTIFACT_HASH_FIELDS,
        ):
            _require_sha256(field, state[field])

        issuers: dict[str, dict[str, Any]] = {}
        issued_receipt_ids: dict[str, str] = {}
        for event in events:
            if event["event_type"] != "CLOSURE_RECEIPT_ISSUED":
                continue
            payload = event["payload"]
            if set(payload) != _ISSUANCE_FIELDS:
                raise AuthorityAdapterError("receipt issuer event fields are not exact")
            kind = payload["receipt_kind"]
            if kind not in ISSUER_KEYS:
                raise AuthorityAdapterError("receipt issuer event kind is invalid")
            if any(payload[field] != state[field] for field in (
                "authority_scope",
                "instance_id",
                "requirement_epoch",
                "semantic_contract_identity_sha256",
                "authorization_risk_identity_sha256",
            )):
                continue
            issuers[kind] = {
                "issuer_control_domain_id": payload["issuer_control_domain_id"],
                "issuance_event_id": event["event_id"],
                "issuance_event_revision": event["stream_revision"],
                "issuance_event_sha256": event["event_hash"],
            }
            issued_receipt_ids[kind] = payload["receipt_id"]
        if set(issuers) != set(ISSUER_KEYS):
            raise AuthorityAdapterError("latest authoritative issuer events are incomplete")

        consumed: set[str] = set()
        for event in events:
            if event["event_type"] != "CLOSURE_RECEIPT_SET_CONSUMED":
                continue
            payload = event["payload"]
            if set(payload) != _CONSUMPTION_FIELDS:
                raise AuthorityAdapterError("receipt-consumption event fields are not exact")
            ids = payload["receipt_ids"]
            if not isinstance(ids, list) or any(not isinstance(item, str) or not item for item in ids):
                raise AuthorityAdapterError("consumed receipt IDs are invalid")
            _require_sha256("decision_sha256", payload["decision_sha256"])
            consumed.update(ids)

        tip = events[-1]
        context_body = {
            "schema_version": "2.9",
            **{field: state[field] for field in (
                "authority_scope",
                "instance_id",
                "requirement_epoch",
                "semantic_contract_identity_sha256",
                "authorization_risk_identity_sha256",
            )},
            "state_revision": tip["stream_revision"],
            "current_state_sha256": state["current_state_sha256"],
            "event_store_tip_sha256": tip["event_hash"],
            **{field: state[field] for field in RELEASE_ARTIFACT_HASH_FIELDS},
            "authorized_issuers": issuers,
            "consumed_receipt_ids": sorted(consumed),
        }
        if set(context_body) != RELEASE_CONTEXT_BODY_FIELDS:
            raise AuthorityAdapterError("derived Release Context fields drifted")
        release_context = {
            **context_body,
            "release_context_sha256": _hash(context_body),
        }
        current_state = {
            field: release_context[field] for field in CURRENT_STATE_FIELDS
        }
        return _VerifiedSnapshot(current_state, release_context, issued_receipt_ids)

    def _read_verified_snapshot(self) -> _VerifiedSnapshot:
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            snapshot = self._snapshot_from_connection(connection)
            connection.rollback()
            return snapshot
        finally:
            connection.close()

    def read_current_state(self) -> dict[str, Any]:
        """Re-read and return the exact live state; never accepts caller state."""

        return dict(self._read_verified_snapshot().current_state)

    def read_release_context(self) -> dict[str, Any]:
        """Construct the Release Context only from verified authority events."""

        snapshot = self._read_verified_snapshot()
        context = dict(snapshot.release_context)
        context["authorized_issuers"] = {
            key: dict(value)
            for key, value in context["authorized_issuers"].items()
        }
        context["consumed_receipt_ids"] = list(context["consumed_receipt_ids"])
        return context

    def assert_receipt_issued(
        self,
        receipt_kind: str,
        receipt_id: str,
        anchor: Mapping[str, Any],
    ) -> None:
        """Bind a receipt to its exact latest issuance event and receipt ID."""

        snapshot = self._read_verified_snapshot()
        expected_anchor = snapshot.release_context["authorized_issuers"].get(receipt_kind)
        if (
            snapshot.issued_receipt_ids.get(receipt_kind) != receipt_id
            or not isinstance(anchor, Mapping)
            or dict(anchor) != expected_anchor
        ):
            raise AuthorityAdapterError("receipt is not bound to an authoritative issuer event")

    def validate_precommit(self, proposal: Mapping[str, Any]) -> None:
        """Fail if the tip or receipt-consumption set changed after evaluation."""

        if not isinstance(proposal, Mapping):
            raise AuthorityAdapterError("release proposal must be an object")
        snapshot = self._read_verified_snapshot()
        if proposal.get("expected_event_store_tip_sha256") != snapshot.release_context[
            "event_store_tip_sha256"
        ]:
            raise AuthorityAdapterError("Event Store tip changed before atomic commit")
        receipt_ids = _proposal_receipt_ids(proposal)
        consumed = set(snapshot.release_context["consumed_receipt_ids"])
        if receipt_ids & consumed:
            raise AuthorityAdapterError("a release receipt was consumed before atomic commit")

    def atomic_commit_release_ready(
        self,
        proposal: Mapping[str, Any],
        *,
        created_at: str,
    ) -> list[dict[str, Any]]:
        """Atomically consume receipts and append RELEASE_READY under Event Store CAS.

        This production entrypoint is inert during Candidate authoring.  At an
        authorized runtime it additionally requires a matching
        RELEASE_COMMIT_AUTHORIZED event already present in the verified stream.
        """

        if not isinstance(created_at, str) or not created_at:
            raise AuthorityAdapterError("created_at must be a non-empty string")
        connection = self._connect(writable=True)
        try:
            connection.execute("BEGIN IMMEDIATE")
            snapshot = self._snapshot_from_connection(connection)
            events = self._events(connection)
            if (
                events[-1]["event_type"] != "RELEASE_COMMIT_AUTHORIZED"
                or events[-1]["event_hash"]
                != snapshot.release_context["event_store_tip_sha256"]
                or events[-1]["previous_event_hash"]
                != proposal.get("expected_event_store_tip_sha256")
            ):
                raise AuthorityAdapterError(
                    "Event Store tip is not the authorization successor of the evaluated tip"
                )
            receipt_ids = _proposal_receipt_ids(proposal)
            if receipt_ids & set(snapshot.release_context["consumed_receipt_ids"]):
                raise AuthorityAdapterError("a release receipt was already consumed")
            decision_hash = _require_sha256("decision_sha256", proposal.get("decision_sha256"))
            authorizations = [
                event for event in events
                if event["event_type"] == "RELEASE_COMMIT_AUTHORIZED"
            ]
            if not authorizations:
                raise AuthorityAdapterError("runtime release commit is not authorized")
            authorization_event = authorizations[-1]
            if authorization_event is not events[-1]:
                raise AuthorityAdapterError("release commit authorization is not the live tip")
            authorization = _verify_signed_authority(
                authorization_event["payload"],
                exact_fields=_COMMIT_AUTHORIZATION_FIELDS,
                expected_purpose="RUNTIME_RELEASE_COMMIT",
                receiver_trust_anchor=self._receiver_trust_anchor,
            )
            if authorization.get("one_shot") is not True:
                raise AuthorityAdapterError("release commit authorization must be one-shot")
            context = snapshot.release_context
            if (
                authorization["status"] != "AUTHORIZED"
                or authorization["program_id"] != self._binding["program_id"]
                or any(authorization[field] != context[field] for field in (
                    "authority_scope",
                    "instance_id",
                    "requirement_epoch",
                    "semantic_contract_identity_sha256",
                    "authorization_risk_identity_sha256",
                    *RELEASE_ARTIFACT_HASH_FIELDS,
                ))
            ):
                raise AuthorityAdapterError("release commit authorization is not current")
            actual_artifact_hashes = self._artifact_resolver.resolve_hashes()
            if any(
                actual_artifact_hashes[field] != context[field]
                or actual_artifact_hashes[field] != authorization[field]
                for field in RELEASE_ARTIFACT_HASH_FIELDS
            ):
                raise AuthorityAdapterError(
                    "actual release artifact bytes do not match authority"
                )
            for field in (
                "candidate_content_sha256",
                "requirement_ir_sha256",
                "executor_release_sha256",
                "human_gate_receipt_sha256",
                "expected_control_state_sha256",
                "authorized_event_store_tip_sha256",
                "proposal_decision_sha256",
            ):
                _require_sha256(field, authorization.get(field))
            if (
                authorization["expected_control_state_sha256"]
                != context["current_state_sha256"]
                or authorization["proposal_decision_sha256"] != decision_hash
                or authorization["authorized_event_store_tip_sha256"]
                != proposal.get("expected_event_store_tip_sha256")
                or authorization_event["previous_event_hash"]
                != proposal.get("expected_event_store_tip_sha256")
            ):
                raise AuthorityAdapterError("release commit authorization does not bind proposal state")
            if _parse_time("lease_expires_at", authorization.get("lease_expires_at")) <= datetime.now(timezone.utc):
                raise AuthorityAdapterError("release commit authorization lease expired")
            if not isinstance(authorization.get("lease_id"), str) or not authorization["lease_id"]:
                raise AuthorityAdapterError("release commit authorization lease is invalid")
            if not isinstance(authorization.get("idempotency_key"), str) or not authorization["idempotency_key"]:
                raise AuthorityAdapterError("release commit authorization idempotency key is invalid")
            fencing_token = authorization.get("fencing_token")
            if isinstance(fencing_token, bool) or not isinstance(fencing_token, int) or fencing_token < 1:
                raise AuthorityAdapterError("release commit authorization fencing token is invalid")
            consumptions = [
                event["payload"] for event in events
                if event["event_type"] == "RELEASE_COMMIT_AUTHORIZATION_CONSUMED"
            ]
            for consumed in consumptions:
                if set(consumed) != _AUTHORIZATION_CONSUMPTION_FIELDS:
                    raise AuthorityAdapterError("release authorization consumption fields are not exact")
                if (
                    consumed["authorization_id"] == authorization["authorization_id"]
                    or consumed["idempotency_key"] == authorization["idempotency_key"]
                    or consumed["fencing_token"] >= fencing_token
                ):
                    raise AuthorityAdapterError("release commit authorization was replayed or fenced")
            entries = [
                {
                    "event_type": "RELEASE_COMMIT_AUTHORIZATION_CONSUMED",
                    "payload": {
                        "authorization_id": authorization["authorization_id"],
                        "authorization_event_sha256": authorization_event["event_hash"],
                        "decision_sha256": decision_hash,
                        "fencing_token": fencing_token,
                        "idempotency_key": authorization["idempotency_key"],
                    },
                },
                {
                    "event_type": "CLOSURE_RECEIPT_SET_CONSUMED",
                    "payload": {
                        "receipt_ids": sorted(receipt_ids),
                        "decision_sha256": decision_hash,
                    },
                },
                {
                    "event_type": "RELEASE_READY_COMMITTED",
                    "payload": {
                        "decision_sha256": decision_hash,
                        "authorization_id": authorization["authorization_id"],
                        "authorization_event_sha256": authorization_event["event_hash"],
                        "fencing_token": fencing_token,
                        "authority_scope": context["authority_scope"],
                        "instance_id": context["instance_id"],
                        "requirement_epoch": context["requirement_epoch"],
                        **{
                            field: context[field]
                            for field in RELEASE_ARTIFACT_HASH_FIELDS
                        },
                    },
                },
            ]
            appended = _append_events(
                connection,
                str(self._binding["program_id"]),
                entries,
                created_at,
                str(context["event_store_tip_sha256"]),
            )
            connection.commit()
            return appended
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def _proposal_receipt_ids(proposal: Mapping[str, Any]) -> set[str]:
    lanes = proposal.get("lane_receipt_ids")
    linkage = proposal.get("compatibility_linkage_receipt_id")
    if (
        not isinstance(lanes, Mapping)
        or set(lanes) != set(LANE_IDS)
        or any(not isinstance(value, str) or not value for value in lanes.values())
        or not isinstance(linkage, str)
        or not linkage
    ):
        raise AuthorityAdapterError("release proposal receipt IDs are invalid")
    values = [*lanes.values(), linkage]
    if len(values) != len(set(values)):
        raise AuthorityAdapterError("release proposal receipt IDs are duplicated")
    return set(values)


def _append_events(
    connection: sqlite3.Connection,
    program_id: str,
    entries: Sequence[Mapping[str, Any]],
    created_at: str,
    expected_tip: str,
) -> list[dict[str, Any]]:
    previous = connection.execute(
        """SELECT stream_revision, event_hash FROM control_events
           WHERE program_id = ? ORDER BY stream_revision DESC LIMIT 1""",
        (program_id,),
    ).fetchone()
    if previous is None or str(previous["event_hash"]) != expected_tip:
        raise AuthorityAdapterError("Event Store tip compare-and-swap failed")
    revision = int(previous["stream_revision"])
    previous_hash: str | None = str(previous["event_hash"])
    appended: list[dict[str, Any]] = []
    for entry in entries:
        revision += 1
        identity = {
            "program_id": program_id,
            "stream_revision": revision,
            "event_type": entry["event_type"],
            "payload": dict(entry["payload"]),
            "previous_event_hash": previous_hash,
            "created_at": created_at,
        }
        event_id = f"CEVT-{_hash(identity)[:32].upper()}"
        event = {"schema_version": "2.9", "event_id": event_id, **identity}
        event_hash = _hash(event)
        event["event_hash"] = event_hash
        connection.execute(
            """INSERT INTO control_events(
                   event_id, program_id, stream_revision, event_type,
                   payload_json, previous_event_hash, event_hash, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                program_id,
                revision,
                entry["event_type"],
                _canonical_json(entry["payload"]),
                previous_hash,
                event_hash,
                created_at,
            ),
        )
        appended.append(event)
        previous_hash = event_hash
    return appended


__all__ = [
    "ADAPTER_ID",
    "ADAPTER_BINDING_FIELDS",
    "LOGICAL_DATABASE_REF",
    "AuthorityAdapterError",
    "SQLiteEventStoreAuthorityAdapter",
    "adapter_entrypoint_sha256",
    "build_adapter_binding",
]
