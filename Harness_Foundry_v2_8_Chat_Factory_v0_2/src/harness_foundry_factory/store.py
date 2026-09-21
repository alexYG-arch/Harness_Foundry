"""Transactional SQLite event store for Factory programs."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, Iterator
import uuid

from .constants import SCHEMA_VERSION
from .models import (
    ChatRequest,
    IdempotencyConflictError,
    ProgramNotFoundError,
    ProgramRecord,
    RequestValidationError,
    StateConflictError,
    TransitionOutcome,
    canonical_json,
    content_sha256,
)


Mutator = Callable[[dict[str, Any] | None, str, str], TransitionOutcome]


class SQLiteEventStore:
    """Persist snapshots, append-only events, and idempotent responses.

    Every mutation runs under ``BEGIN IMMEDIATE`` and compares the caller's
    expected state hash.  The append-only event chain is authoritative; the
    program row is a current read model.
    """

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.database_path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS programs (
                    program_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL,
                    factory_state TEXT NOT NULL,
                    state_hash TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    program_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    request_id TEXT NOT NULL UNIQUE,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    actor_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    resulting_snapshot_json TEXT,
                    previous_state_hash TEXT,
                    new_state_hash TEXT NOT NULL,
                    previous_event_hash TEXT,
                    event_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(program_id) REFERENCES programs(program_id),
                    UNIQUE(program_id, revision)
                );

                CREATE TABLE IF NOT EXISTS idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    request_hash TEXT NOT NULL,
                    program_id TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(program_id) REFERENCES programs(program_id)
                );

                CREATE INDEX IF NOT EXISTS events_program_sequence
                    ON events(program_id, sequence);
                """
            )
            event_columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(events)")
            }
            if "resulting_snapshot_json" not in event_columns:
                connection.execute(
                    "ALTER TABLE events ADD COLUMN resulting_snapshot_json TEXT"
                )
            connection.commit()

    def apply(self, request: ChatRequest, now: str, mutator: Mutator) -> dict[str, Any]:
        """Apply one request exactly once under CAS and append an event."""

        request_hash = content_sha256(request.as_dict())
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_replay(connection, request, request_hash)
            if replay is not None:
                connection.rollback()
                return replay

            if request.intent == "CREATE":
                if request.program_id is not None:
                    existing = connection.execute(
                        "SELECT 1 FROM programs WHERE program_id = ?",
                        (request.program_id,),
                    ).fetchone()
                    if existing is not None:
                        raise RequestValidationError(
                            "CREATE program_id already exists",
                            details={"program_id": request.program_id},
                        )
                    program_id = request.program_id
                else:
                    program_id = f"HF28-{uuid.uuid4().hex[:20].upper()}"
                current: dict[str, Any] | None = None
                old_state_hash: str | None = None
                old_revision = 0
                created_at = now
            else:
                row = connection.execute(
                    "SELECT * FROM programs WHERE program_id = ?",
                    (request.program_id,),
                ).fetchone()
                if row is None:
                    raise ProgramNotFoundError(
                        "program does not exist",
                        details={"program_id": request.program_id},
                    )
                program_id = str(row["program_id"])
                old_state_hash = str(row["state_hash"])
                if request.expected_state_hash is None:
                    raise StateConflictError(
                        "expected_state_hash is required for existing program mutations",
                        details={
                            "program_id": program_id,
                            "actual_state_hash": old_state_hash,
                        },
                    )
                if request.expected_state_hash != old_state_hash:
                    raise StateConflictError(
                        "expected_state_hash does not match current state",
                        details={
                            "program_id": program_id,
                            "expected_state_hash": request.expected_state_hash,
                            "actual_state_hash": old_state_hash,
                        },
                    )
                current = json.loads(str(row["snapshot_json"]))
                old_revision = int(row["revision"])
                created_at = str(row["created_at"])

            outcome = mutator(current, program_id, now)
            snapshot = dict(outcome.snapshot)
            revision = old_revision + 1
            snapshot.update(
                {
                    "schema_version": SCHEMA_VERSION,
                    "program_id": program_id,
                    "revision": revision,
                    "created_at": created_at,
                    "updated_at": now,
                }
            )
            factory_state = snapshot.get("factory_state")
            if not isinstance(factory_state, str) or not factory_state:
                raise RequestValidationError("transition did not produce factory_state")
            new_state_hash = content_sha256(snapshot)
            snapshot_json = canonical_json(snapshot)

            if current is None:
                connection.execute(
                    """
                    INSERT INTO programs(
                        program_id, revision, factory_state, state_hash,
                        snapshot_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        program_id,
                        revision,
                        factory_state,
                        new_state_hash,
                        snapshot_json,
                        created_at,
                        now,
                    ),
                )
            else:
                changed = connection.execute(
                    """
                    UPDATE programs
                    SET revision = ?, factory_state = ?, state_hash = ?,
                        snapshot_json = ?, updated_at = ?
                    WHERE program_id = ? AND state_hash = ?
                    """,
                    (
                        revision,
                        factory_state,
                        new_state_hash,
                        snapshot_json,
                        now,
                        program_id,
                        old_state_hash,
                    ),
                ).rowcount
                if changed != 1:
                    raise StateConflictError(
                        "state changed while committing transition",
                        details={"program_id": program_id},
                    )

            previous_event = connection.execute(
                """
                SELECT event_hash FROM events
                WHERE program_id = ? ORDER BY sequence DESC LIMIT 1
                """,
                (program_id,),
            ).fetchone()
            previous_event_hash = (
                str(previous_event["event_hash"]) if previous_event is not None else None
            )
            event_id = f"EVT-{uuid.uuid4().hex.upper()}"
            event_document = {
                "schema_version": SCHEMA_VERSION,
                "event_id": event_id,
                "program_id": program_id,
                "revision": revision,
                "event_type": outcome.event_type,
                "request_id": request.request_id,
                "idempotency_key": request.idempotency_key,
                "actor": request.actor.as_dict(),
                "payload": request.payload,
                "resulting_snapshot": snapshot,
                "previous_state_hash": old_state_hash,
                "new_state_hash": new_state_hash,
                "previous_event_hash": previous_event_hash,
                "created_at": now,
            }
            event_hash = content_sha256(event_document)
            connection.execute(
                """
                INSERT INTO events(
                    event_id, program_id, revision, event_type, request_id,
                    idempotency_key, actor_json, payload_json,
                    resulting_snapshot_json,
                    previous_state_hash, new_state_hash, previous_event_hash,
                    event_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    program_id,
                    revision,
                    outcome.event_type,
                    request.request_id,
                    request.idempotency_key,
                    canonical_json(request.actor.as_dict()),
                    canonical_json(request.payload),
                    snapshot_json,
                    old_state_hash,
                    new_state_hash,
                    previous_event_hash,
                    event_hash,
                    now,
                ),
            )

            response_defaults = {
                "questions": [],
                "blockers": [],
                "artifact_refs": [],
                "next_allowed_intents": [],
            }
            response_defaults.update(outcome.response)
            response = {
                "schema_version": SCHEMA_VERSION,
                "status": "OK",
                "request_id": request.request_id,
                "idempotency_key": request.idempotency_key,
                "program_id": program_id,
                "old_state_hash": old_state_hash,
                "new_state_hash": new_state_hash,
                "revision": revision,
                "factory_state": factory_state,
                **response_defaults,
            }
            connection.execute(
                """
                INSERT INTO idempotency(
                    idempotency_key, request_id, request_hash, program_id,
                    response_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    request.idempotency_key,
                    request.request_id,
                    request_hash,
                    program_id,
                    canonical_json(response),
                    now,
                ),
            )
            connection.commit()
            return response

    def _idempotent_replay(
        self,
        connection: sqlite3.Connection,
        request: ChatRequest,
        request_hash: str,
    ) -> dict[str, Any] | None:
        by_key = connection.execute(
            "SELECT * FROM idempotency WHERE idempotency_key = ?",
            (request.idempotency_key,),
        ).fetchone()
        by_request = connection.execute(
            "SELECT * FROM idempotency WHERE request_id = ?",
            (request.request_id,),
        ).fetchone()
        rows = [row for row in (by_key, by_request) if row is not None]
        if not rows:
            return None
        first = rows[0]
        if any(row["idempotency_key"] != first["idempotency_key"] for row in rows):
            raise IdempotencyConflictError(
                "request_id and idempotency_key refer to different prior requests"
            )
        if str(first["request_hash"]) != request_hash:
            raise IdempotencyConflictError(
                "idempotency key or request_id was reused with different content",
                details={
                    "request_id": request.request_id,
                    "idempotency_key": request.idempotency_key,
                },
            )
        return json.loads(str(first["response_json"]))

    def get_program(self, program_id: str) -> ProgramRecord:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM programs WHERE program_id = ?",
                (program_id,),
            ).fetchone()
        if row is None:
            raise ProgramNotFoundError(
                "program does not exist", details={"program_id": program_id}
            )
        return self._record_from_row(row)

    def list_events(self, program_id: str) -> list[dict[str, Any]]:
        self.get_program(program_id)
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE program_id = ? ORDER BY sequence",
                (program_id,),
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def verify_run(self, program_id: str) -> dict[str, Any]:
        """Verify snapshot integrity and the complete append-only hash chain."""

        record = self.get_program(program_id)
        events = self.list_events(program_id)
        errors: list[dict[str, Any]] = []
        previous_event_hash: str | None = None
        previous_state_hash: str | None = None
        expected_revision = 1
        for event in events:
            if event["revision"] != expected_revision:
                errors.append(
                    {
                        "code": "EVENT_REVISION_GAP",
                        "expected": expected_revision,
                        "actual": event["revision"],
                    }
                )
            if event["previous_event_hash"] != previous_event_hash:
                errors.append(
                    {"code": "EVENT_HASH_CHAIN_MISMATCH", "event_id": event["event_id"]}
                )
            if event["previous_state_hash"] != previous_state_hash:
                errors.append(
                    {"code": "STATE_HASH_CHAIN_MISMATCH", "event_id": event["event_id"]}
                )
            stored_hash = event.pop("event_hash")
            if content_sha256(event) != stored_hash:
                errors.append(
                    {"code": "EVENT_CONTENT_HASH_MISMATCH", "event_id": event["event_id"]}
                )
            event["event_hash"] = stored_hash
            previous_event_hash = stored_hash
            previous_state_hash = event["new_state_hash"]
            expected_revision += 1

        if content_sha256(record.snapshot) != record.state_hash:
            errors.append({"code": "CURRENT_SNAPSHOT_HASH_MISMATCH"})
        if record.factory_state != record.snapshot.get("factory_state"):
            errors.append({"code": "FACTORY_STATE_READ_MODEL_MISMATCH"})
        if not events:
            errors.append({"code": "EVENT_LEDGER_EMPTY"})
        elif previous_state_hash != record.state_hash:
            errors.append({"code": "LEDGER_CURRENT_STATE_MISMATCH"})
        if events and events[-1].get("resulting_snapshot") != record.snapshot:
            errors.append({"code": "EVENT_SNAPSHOT_READ_MODEL_MISMATCH"})
        if len(events) != record.revision:
            errors.append(
                {
                    "code": "REVISION_EVENT_COUNT_MISMATCH",
                    "revision": record.revision,
                    "event_count": len(events),
                }
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS" if not errors else "FAIL",
            "program_id": program_id,
            "state_hash": record.state_hash,
            "revision": record.revision,
            "event_count": len(events),
            "last_event_hash": previous_event_hash,
            "errors": errors,
        }

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> ProgramRecord:
        return ProgramRecord(
            program_id=str(row["program_id"]),
            revision=int(row["revision"]),
            factory_state=str(row["factory_state"]),
            state_hash=str(row["state_hash"]),
            snapshot=json.loads(str(row["snapshot_json"])),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "event_id": str(row["event_id"]),
            "program_id": str(row["program_id"]),
            "revision": int(row["revision"]),
            "event_type": str(row["event_type"]),
            "request_id": str(row["request_id"]),
            "idempotency_key": str(row["idempotency_key"]),
            "actor": json.loads(str(row["actor_json"])),
            "payload": json.loads(str(row["payload_json"])),
            "resulting_snapshot": json.loads(str(row["resulting_snapshot_json"]))
            if row["resulting_snapshot_json"] is not None
            else None,
            "previous_state_hash": row["previous_state_hash"],
            "new_state_hash": str(row["new_state_hash"]),
            "previous_event_hash": row["previous_event_hash"],
            "created_at": str(row["created_at"]),
            "event_hash": str(row["event_hash"]),
        }


# Small compatibility aliases for callers that prefer role-oriented names.
FactoryStore = SQLiteEventStore
EventStore = SQLiteEventStore
