"""Core data contracts for the chat-native authoring Factory.

The models intentionally use only the Python standard library.  They validate
the boundary between Codex Chat and the persisted state machine; authoritative
state is never inferred from chat history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Mapping

from .constants import SCHEMA_VERSION


SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def canonical_json(value: Any) -> str:
    """Return the stable JSON representation used by hashes and ledgers."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def content_sha256(value: Any) -> str:
    """Hash a JSON-compatible value using the Factory canonical encoding."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class FactoryError(Exception):
    """Base exception with a closed machine-readable error contract."""

    code = "FACTORY_ERROR"
    exit_code = 1

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = dict(details or {})

    def as_response(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "ERROR",
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            },
        }


class RequestValidationError(FactoryError):
    code = "REQUEST_VALIDATION_ERROR"
    exit_code = 2


class ProgramNotFoundError(FactoryError):
    code = "PROGRAM_NOT_FOUND"
    exit_code = 3


class StateConflictError(FactoryError):
    code = "STATE_HASH_CONFLICT"
    exit_code = 4


class RevisionConflictError(StateConflictError):
    code = "STATE_REVISION_CONFLICT"


class InvalidTransitionError(FactoryError):
    code = "INVALID_FACTORY_TRANSITION"
    exit_code = 5


class SpecVerificationError(FactoryError):
    code = "SPEC_VERIFICATION_FAILED"
    exit_code = 6


class SpecDriftError(FactoryError):
    code = "SPEC_DRIFT"
    exit_code = 6


class CandidateValidationError(FactoryError):
    code = "CANDIDATE_VALIDATION_FAILED"
    exit_code = 7


class ContractGateError(FactoryError):
    """A Requirement/Architecture compile precondition failed closed."""

    code = "CONTRACT_GATE_BLOCKED"
    exit_code = 6


class IdempotencyConflictError(FactoryError):
    code = "IDEMPOTENCY_KEY_CONFLICT"
    exit_code = 4


@dataclass(frozen=True)
class Actor:
    """Actor identity recorded with every mutating chat request."""

    type: str
    chat_thread_id: str
    turn_id: str
    delegation_id: str | None = None

    @classmethod
    def from_value(cls, value: Any) -> "Actor":
        if not isinstance(value, Mapping):
            raise RequestValidationError("actor must be a JSON object")
        required = ("type", "chat_thread_id", "turn_id")
        missing = [name for name in required if not _nonempty_string(value.get(name))]
        if missing:
            raise RequestValidationError(
                "actor is missing required fields",
                details={"missing": missing},
            )
        delegated = value.get("type") == "CODEX_DELEGATED_AGENT"
        allowed = {"type", "chat_thread_id", "turn_id"} | ({"delegation_id"} if delegated else set())
        unexpected = sorted(set(value).difference(allowed))
        if unexpected:
            raise RequestValidationError(
                "actor contains unsupported fields", details={"unexpected": unexpected}
            )
        if value.get("type") not in {"HUMAN_VIA_CODEX_CHAT", "CODEX_DELEGATED_AGENT"}:
            raise RequestValidationError(
                "actor.type must be HUMAN_VIA_CODEX_CHAT or CODEX_DELEGATED_AGENT",
                details={"actual": value.get("type")},
            )
        if delegated and (not isinstance(value.get("delegation_id"), str)
                          or not SAFE_ID_RE.fullmatch(value["delegation_id"])):
            raise RequestValidationError("delegated actor requires a path-safe delegation_id")
        return cls(
            type=str(value["type"]),
            chat_thread_id=str(value["chat_thread_id"]),
            turn_id=str(value["turn_id"]),
            delegation_id=value.get("delegation_id"),
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "type": self.type,
            "chat_thread_id": self.chat_thread_id,
            "turn_id": self.turn_id,
            **({"delegation_id": self.delegation_id} if self.delegation_id is not None else {}),
        }


INTENT_ALIASES = {
    "ADD_SOURCE": "ADD_SOURCES",
    "SET_REQUIREMENTS": "UPDATE_REQUIREMENTS",
    "REQUEST_READBACK": "PREPARE_READBACK",
    "PROPOSE_FREEZE": "REQUEST_FREEZE",
    "APPROVE_FREEZE": "CONFIRM_FREEZE",
    "APPROVE_GATE": "CONFIRM_FREEZE",
}

SUPPORTED_INTENTS = {
    "CREATE",
    "ADD_SOURCES",
    "UPDATE_REQUIREMENTS",
    "ANSWER",
    "PREPARE_READBACK",
    "REQUEST_FREEZE",
    "CONFIRM_FREEZE",
    "PREPARE_ARCHITECTURE_READBACK",
    "REQUEST_ARCHITECTURE_LOCK",
    "CONFIRM_ARCHITECTURE_LOCK",
    "ADVANCE_AUTHORING_UNTIL_GATE",
    "GENERATE",
    "REOPEN",
    "GRANT_PREBUILD_DELEGATION",
    "REVOKE_PREBUILD_DELEGATION",
    "BIND_DELEGATED_OUTPUT",
    "DELEGATED_FREEZE",
    "DELEGATED_ARCHITECTURE_LOCK",
    "REVIEW_CANDIDATE",
}


@dataclass(frozen=True)
class ChatRequest:
    """Strict request envelope accepted by ``chat-turn``."""

    request_id: str
    idempotency_key: str
    program_id: str | None
    expected_state_hash: str | None
    actor: Actor
    intent: str
    payload: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    @classmethod
    def from_dict(cls, value: Any) -> "ChatRequest":
        if not isinstance(value, Mapping):
            raise RequestValidationError("chat-turn request must be a JSON object")

        required = (
            "request_id",
            "idempotency_key",
            "program_id",
            "expected_state_hash",
            "actor",
            "intent",
            "payload",
        )
        missing = [name for name in required if name not in value]
        if missing:
            raise RequestValidationError(
                "chat-turn request is missing required fields",
                details={"missing": missing},
            )
        allowed = set(required)
        unexpected = sorted(set(value).difference(allowed))
        if unexpected:
            raise RequestValidationError(
                "chat-turn request contains unsupported fields",
                details={"unexpected": unexpected},
            )

        for name in ("request_id", "idempotency_key", "intent"):
            if not _nonempty_string(value.get(name)):
                raise RequestValidationError(f"{name} must be a non-empty string")

        schema_version = SCHEMA_VERSION

        raw_intent = str(value["intent"]).strip().upper()
        intent = INTENT_ALIASES.get(raw_intent, raw_intent)
        if intent not in SUPPORTED_INTENTS:
            raise RequestValidationError(
                "unsupported chat-turn intent",
                details={"intent": raw_intent, "supported": sorted(SUPPORTED_INTENTS)},
            )

        payload = value.get("payload")
        if not isinstance(payload, Mapping):
            raise RequestValidationError("payload must be a JSON object")

        program_id = value.get("program_id")
        if (
            not _nonempty_string(program_id)
            or not SAFE_ID_RE.fullmatch(str(program_id))
            or ".." in str(program_id)
        ):
            raise RequestValidationError(
                "program_id must be a path-safe identifier",
                details={"pattern": SAFE_ID_RE.pattern},
            )
        expected_hash = value.get("expected_state_hash")
        if expected_hash is not None and not _nonempty_string(expected_hash):
            raise RequestValidationError(
                "expected_state_hash must be null or a non-empty string"
            )
        if intent == "CREATE" and expected_hash is not None:
            raise RequestValidationError(
                "CREATE must not provide expected_state_hash",
                details={"expected_state_hash": expected_hash},
            )

        return cls(
            request_id=str(value["request_id"]),
            idempotency_key=str(value["idempotency_key"]),
            program_id=str(program_id),
            expected_state_hash=(
                str(expected_hash) if expected_hash is not None else None
            ),
            actor=Actor.from_value(value["actor"]),
            intent=intent,
            payload=dict(payload),
            schema_version=str(schema_version),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "idempotency_key": self.idempotency_key,
            "program_id": self.program_id,
            "expected_state_hash": self.expected_state_hash,
            "actor": self.actor.as_dict(),
            "intent": self.intent,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class TransitionOutcome:
    """Pure service transition result persisted atomically by the store."""

    snapshot: dict[str, Any]
    event_type: str
    response: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProgramRecord:
    program_id: str
    revision: int
    factory_state: str
    state_hash: str
    snapshot: dict[str, Any]
    created_at: str
    updated_at: str

    def as_status(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "OK",
            "program_id": self.program_id,
            "revision": self.revision,
            "factory_state": self.factory_state,
            "state_hash": self.state_hash,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
