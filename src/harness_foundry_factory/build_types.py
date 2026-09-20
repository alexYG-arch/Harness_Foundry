"""Shared JSON and errors for generic builds; no authoring or hash-chain dependency."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping


SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def canonical_json(value: Any) -> str:
    """Stable JSON comparison/storage, not a digest or acceptance result."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


class FactoryError(Exception):
    code = "FACTORY_ERROR"
    exit_code = 1

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = dict(details or {})

    def as_response(self) -> dict[str, Any]:
        return {"schema_version": "1.0", "status": "ERROR",
                "error": {"code": self.code, "message": self.message, "details": self.details}}


class RequestValidationError(FactoryError):
    code = "REQUEST_VALIDATION_ERROR"
    exit_code = 2


class StateConflictError(FactoryError):
    code = "STATE_HASH_CONFLICT"  # Historical error spelling, not a new hash operation.
    exit_code = 4


class RevisionConflictError(StateConflictError):
    code = "STATE_REVISION_CONFLICT"


class IdempotencyConflictError(FactoryError):
    code = "IDEMPOTENCY_KEY_CONFLICT"
    exit_code = 4
