"""Transactional SQLite event store for Factory programs."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, Iterator, Mapping, Sequence
import uuid

from .constants import SCHEMA_VERSION
from .models import (
    ChatRequest,
    IdempotencyConflictError,
    ProgramNotFoundError,
    ProgramRecord,
    RequestValidationError,
    RevisionConflictError,
    StateConflictError,
    TransitionOutcome,
    canonical_json,
    content_sha256,
)


Mutator = Callable[[dict[str, Any] | None, str, str], TransitionOutcome]


CONTROL_EVENT_STORE_TABLE_COLUMNS: dict[str, tuple[tuple[str, str, int, int], ...]] = {
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

# New generic streams use revisions for concurrency and literal JSON for
# idempotency. This is an alternate format of the same authoritative store,
# never a second database or an in-place rewrite of a historical hash chain.
REVISION_CONTROL_EVENT_STORE_TABLE_COLUMNS = {
    "control_events": tuple(column for column in CONTROL_EVENT_STORE_TABLE_COLUMNS["control_events"]
                            if column[0] not in {"previous_event_hash", "event_hash"}),
    "control_idempotency": tuple(("request_json", *column[1:]) if column[0] == "request_sha256" else column
                                 for column in CONTROL_EVENT_STORE_TABLE_COLUMNS["control_idempotency"]),
}

CONTROL_EVENT_STORE_TRIGGER_SQL: dict[str, str] = {
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


def control_event_store_schema_contract() -> dict[str, Any]:
    """Return the portable, Hash-bound native ControlEventStore schema."""

    contract: dict[str, Any] = {
        "schema_version": "2.9",
        "authority_model": "SINGLE_APPEND_ONLY_SQLITE_CONTROL_EVENT_STORE",
        "tables": {
            table: [
                {
                    "name": name,
                    "type": column_type,
                    "not_null": bool(not_null),
                    "primary_key_position": primary_key_position,
                }
                for name, column_type, not_null, primary_key_position in columns
            ]
            for table, columns in CONTROL_EVENT_STORE_TABLE_COLUMNS.items()
        },
        "append_only_triggers": dict(CONTROL_EVENT_STORE_TRIGGER_SQL),
        "preexisting_store_policy": (
            "REJECT_BEFORE_SCHEMA_OR_JOURNAL_MUTATION"
        ),
    }
    contract["schema_contract_sha256"] = content_sha256(contract)
    return contract


class SQLiteEventStore:
    """Persist snapshots, append-only events, and idempotent responses.

    Every mutation runs under ``BEGIN IMMEDIATE`` and compares the caller's
    expected state hash.  The append-only event chain is authoritative; the
    program row is a current read model.
    """

    def __init__(
        self,
        database_path: str | Path,
        *,
        read_only: bool = False,
    ) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.read_only = read_only
        if read_only:
            if not self.database_path.is_file():
                raise ProgramNotFoundError(
                    "program database does not exist",
                    details={"database_path": str(self.database_path)},
                )
            return
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        if self.read_only:
            read_only_uri = self.database_path.as_uri() + "?mode=ro"
            wal_path = Path(str(self.database_path) + "-wal")
            shm_path = Path(str(self.database_path) + "-shm")
            if not wal_path.exists() and not shm_path.exists():
                read_only_uri += "&immutable=1"
            connection = sqlite3.connect(
                read_only_uri,
                timeout=30.0,
                uri=True,
            )
        else:
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

        if self.read_only:
            raise RequestValidationError("read-only Event Store cannot apply mutations")
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


class ControlEventStore:
    """Append-only control authority with rebuildable projections.

    The runtime control plane owns one database containing only immutable
    events plus an idempotency index.  Grant, transition, requirement and
    human-cost state are rebuilt by consumers; this store never persists a
    second authoritative snapshot. LEGACY_HASH_V1 retains the old runtime
    contract. REVISION_V1 is explicitly selected for new generic streams;
    opening an existing database in the other format fails without migration.
    """

    def __init__(
        self, database_path: str | Path, *, read_only: bool = False,
        storage_format: str = "LEGACY_HASH_V1",
    ) -> None:
        if storage_format not in {"LEGACY_HASH_V1", "REVISION_V1"}:
            raise RequestValidationError("unsupported control event storage format")
        self.storage_format = storage_format
        self.database_path = Path(database_path).expanduser().resolve()
        self.read_only = read_only
        database_existed = self.database_path.exists()
        if read_only and not database_existed:
            raise RequestValidationError(
                "read-only control event store does not exist",
                details={"database_path": str(self.database_path)},
            )
        if read_only:
            with self._connection() as connection:
                self._require_exact_existing_schema(connection, self._table_columns)
            return
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize(database_existed=database_existed)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        if self.read_only:
            connection = sqlite3.connect(
                self.database_path.as_uri() + "?mode=ro",
                timeout=30.0,
                uri=True,
            )
        else:
            connection = sqlite3.connect(str(self.database_path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self, *, database_existed: bool) -> None:
        with self._connection() as connection:
            if database_existed:
                self._require_exact_existing_schema(connection, self._table_columns)
            connection.execute("PRAGMA journal_mode = WAL")
            if self.storage_format == "REVISION_V1":
                self._initialize_revision_schema(connection)
                return
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS control_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    program_id TEXT NOT NULL,
                    stream_revision INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_event_hash TEXT,
                    event_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    UNIQUE(program_id, stream_revision)
                );

                CREATE TABLE IF NOT EXISTS control_idempotency (
                    program_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    events_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(program_id, idempotency_key)
                );

                CREATE INDEX IF NOT EXISTS control_events_program_revision
                    ON control_events(program_id, stream_revision);

                CREATE TRIGGER IF NOT EXISTS control_events_reject_update
                BEFORE UPDATE ON control_events
                BEGIN
                    SELECT RAISE(ABORT, 'control_events is append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS control_events_reject_delete
                BEFORE DELETE ON control_events
                BEGIN
                    SELECT RAISE(ABORT, 'control_events is append-only');
                END;
                """
            )
            connection.commit()

    @staticmethod
    def _require_exact_existing_schema(connection: sqlite3.Connection, columns=None) -> None:
        """Fail before WAL, DDL, or event mutation for a non-native database."""

        table_names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        columns = CONTROL_EVENT_STORE_TABLE_COLUMNS if columns is None else columns
        expected_tables = set(columns)
        if not expected_tables.issubset(table_names):
            raise RequestValidationError(
                "existing control event store does not match the native schema",
                details={
                    "expected_tables": sorted(expected_tables),
                    "actual_tables": sorted(table_names),
                    "policy": "REJECT_BEFORE_SCHEMA_OR_JOURNAL_MUTATION",
                },
            )
        for table, expected_columns in columns.items():
            actual_columns = tuple(
                (
                    str(row[1]),
                    str(row[2]).upper(),
                    int(row[3]),
                    int(row[5]),
                )
                for row in connection.execute(f"PRAGMA table_info({table})")
            )
            if actual_columns != expected_columns:
                raise RequestValidationError(
                    "existing control event store does not match the native schema",
                    details={
                        "table": table,
                        "expected_columns": expected_columns,
                        "actual_columns": actual_columns,
                        "policy": "REJECT_BEFORE_SCHEMA_OR_JOURNAL_MUTATION",
                    },
                )
        triggers = {
            str(row[0]): " ".join(str(row[1] or "").split())
            for row in connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'trigger'"
            )
        }
        for trigger_name, expected_sql in CONTROL_EVENT_STORE_TRIGGER_SQL.items():
            if triggers.get(trigger_name) != " ".join(expected_sql.split()):
                raise RequestValidationError(
                    "existing control event store lacks an exact append-only guard",
                    details={
                        "trigger": trigger_name,
                        "policy": "REJECT_BEFORE_SCHEMA_OR_JOURNAL_MUTATION",
                    },
                )

    def append_batch(
        self,
        program_id: str,
        entries: Sequence[Mapping[str, Any]],
        *,
        idempotency_key: str,
        created_at: str,
        expected_previous_event_hash: str | None = None,
        require_new: bool = False,
        exclusive_program: bool = False,
        expected_revision: int | None = None,
    ) -> list[dict[str, Any]]:
        """Atomically append an idempotent batch using the selected format.

        ``require_new`` is for reserving a side effect: an idempotent replay is
        not another caller's permission to perform the reserved command.
        REVISION_V1 requires expected_revision; the legacy format retains its
        expected_previous_event_hash contract. Neither provides external
        exactly-once execution or validates the payload's claimed authority.
        """

        if self.storage_format == "REVISION_V1":
            if expected_previous_event_hash is not None:
                raise RequestValidationError("revision streams do not accept event hashes")
            return self._append_revision_batch(program_id, entries, idempotency_key=idempotency_key,
                                               created_at=created_at, expected_revision=expected_revision,
                                               require_new=require_new, exclusive_program=exclusive_program)
        if expected_revision is not None:
            raise RequestValidationError("legacy streams require their existing hash concurrency contract")
        if self.read_only:
            raise RequestValidationError(
                "read-only Control Event Store cannot append events"
            )

        if not program_id or not idempotency_key or not entries:
            raise RequestValidationError(
                "control event batch requires program_id, idempotency_key and entries"
            )
        normalized: list[dict[str, Any]] = []
        for entry in entries:
            event_type = entry.get("event_type")
            payload = entry.get("payload")
            if not isinstance(event_type, str) or not event_type:
                raise RequestValidationError("control event_type must be non-empty")
            if not isinstance(payload, Mapping):
                raise RequestValidationError("control event payload must be an object")
            normalized.append(
                {"event_type": event_type, "payload": dict(payload)}
            )
        request_sha256 = content_sha256(normalized)

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if exclusive_program and connection.execute(
                "SELECT 1 FROM control_events WHERE program_id != ? LIMIT 1", (program_id,)
            ).fetchone() is not None:
                raise StateConflictError("local controller already belongs to a different Program")
            replay = connection.execute(
                """
                SELECT request_sha256, events_json
                FROM control_idempotency
                WHERE program_id = ? AND idempotency_key = ?
                """,
                (program_id, idempotency_key),
            ).fetchone()
            if replay is not None:
                if require_new:
                    raise StateConflictError(
                        "control batch was already reserved; re-read before taking action"
                    )
                if str(replay["request_sha256"]) != request_sha256:
                    raise IdempotencyConflictError(
                        "control idempotency key was reused with different content",
                        details={
                            "program_id": program_id,
                            "idempotency_key": idempotency_key,
                        },
                    )
                connection.rollback()
                return json.loads(str(replay["events_json"]))

            previous = connection.execute(
                """
                SELECT stream_revision, event_hash
                FROM control_events
                WHERE program_id = ?
                ORDER BY stream_revision DESC LIMIT 1
                """,
                (program_id,),
            ).fetchone()
            previous_hash = (
                str(previous["event_hash"]) if previous is not None else None
            )
            if expected_previous_event_hash != previous_hash:
                raise StateConflictError(
                    "control event stream changed before append",
                    details={
                        "program_id": program_id,
                        "expected_previous_event_hash": expected_previous_event_hash,
                        "actual_previous_event_hash": previous_hash,
                    },
                )
            revision = int(previous["stream_revision"]) if previous else 0
            appended: list[dict[str, Any]] = []
            for entry in normalized:
                revision += 1
                event = self.preview_event(
                    program_id,
                    revision,
                    entry["event_type"],
                    entry["payload"],
                    previous_event_hash=previous_hash,
                    created_at=created_at,
                )
                event_id = event["event_id"]
                event_hash = event["event_hash"]
                connection.execute(
                    """
                    INSERT INTO control_events(
                        event_id, program_id, stream_revision, event_type,
                        payload_json, previous_event_hash, event_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        program_id,
                        revision,
                        entry["event_type"],
                        canonical_json(entry["payload"]),
                        previous_hash,
                        event_hash,
                        created_at,
                    ),
                )
                appended.append(event)
                previous_hash = event_hash

            connection.execute(
                """
                INSERT INTO control_idempotency(
                    program_id, idempotency_key, request_sha256,
                    events_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    program_id,
                    idempotency_key,
                    request_sha256,
                    canonical_json(appended),
                    created_at,
                ),
            )
            connection.commit()
            return appended

    @staticmethod
    def preview_event(
        program_id: str,
        stream_revision: int,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        previous_event_hash: str | None,
        created_at: str,
    ) -> dict[str, Any]:
        """Derive the exact immutable event identity without writing it."""

        identity = {
            "program_id": program_id,
            "stream_revision": stream_revision,
            "event_type": event_type,
            "payload": dict(payload),
            "previous_event_hash": previous_event_hash,
            "created_at": created_at,
        }
        event_id = f"CEVT-{content_sha256(identity)[:32].upper()}"
        event = {
            "schema_version": "2.9",
            "event_id": event_id,
            **identity,
        }
        event["event_hash"] = content_sha256(event)
        return event

    def list_events(self, program_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM control_events
                WHERE program_id = ? ORDER BY stream_revision
                """,
                (program_id,),
            ).fetchall()
        if self.storage_format == "REVISION_V1":
            return [{"schema_version": "REVISION_V1", "event_id": str(row["event_id"]),
                     "program_id": str(row["program_id"]), "stream_revision": int(row["stream_revision"]),
                     "event_type": str(row["event_type"]), "payload": json.loads(str(row["payload_json"])),
                     "created_at": str(row["created_at"])} for row in rows]
        return [
            {
                "schema_version": "2.9",
                "event_id": str(row["event_id"]),
                "program_id": str(row["program_id"]),
                "stream_revision": int(row["stream_revision"]),
                "event_type": str(row["event_type"]),
                "payload": json.loads(str(row["payload_json"])),
                "previous_event_hash": row["previous_event_hash"],
                "created_at": str(row["created_at"]),
                "event_hash": str(row["event_hash"]),
            }
            for row in rows
        ]

    def list_program_ids(self) -> list[str]:
        """Read controller ownership without creating a new Program stream."""
        with self._connection() as connection:
            return [str(row[0]) for row in connection.execute(
                "SELECT DISTINCT program_id FROM control_events ORDER BY program_id")]

    def verify_stream(self, program_id: str) -> dict[str, Any]:
        events = self.list_events(program_id)
        if self.storage_format == "REVISION_V1":
            errors = [{"code": "CONTROL_EVENT_REVISION_GAP"} for revision, event in enumerate(events, 1)
                      if event["stream_revision"] != revision]
            return {"schema_version": "REVISION_V1", "status": "FAIL" if errors else "PASS",
                    "program_id": program_id, "event_count": len(events), "errors": errors,
                    "last_revision": events[-1]["stream_revision"] if events else 0,
                    "content_integrity_verified": False}
        errors: list[dict[str, Any]] = []
        previous_hash: str | None = None
        for expected_revision, event in enumerate(events, 1):
            if event["stream_revision"] != expected_revision:
                errors.append({"code": "CONTROL_EVENT_REVISION_GAP"})
            if event["previous_event_hash"] != previous_hash:
                errors.append({"code": "CONTROL_EVENT_HASH_CHAIN_MISMATCH"})
            claimed_hash = event.pop("event_hash")
            if content_sha256(event) != claimed_hash:
                errors.append({"code": "CONTROL_EVENT_CONTENT_HASH_MISMATCH"})
            event["event_hash"] = claimed_hash
            previous_hash = claimed_hash
        return {
            "schema_version": "2.9",
            "status": "PASS" if not errors else "FAIL",
            "program_id": program_id,
            "event_count": len(events),
            "last_event_hash": previous_hash,
            "errors": errors,
        }

    @property
    def _table_columns(self):
        return (REVISION_CONTROL_EVENT_STORE_TABLE_COLUMNS if self.storage_format == "REVISION_V1"
                else CONTROL_EVENT_STORE_TABLE_COLUMNS)

    @staticmethod
    def _initialize_revision_schema(connection: sqlite3.Connection) -> None:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS control_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                program_id TEXT NOT NULL,
                stream_revision INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(program_id, stream_revision)
            );
            CREATE TABLE IF NOT EXISTS control_idempotency (
                program_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                request_json TEXT NOT NULL,
                events_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(program_id, idempotency_key)
            );
            CREATE INDEX IF NOT EXISTS control_events_program_revision
                ON control_events(program_id, stream_revision);
        """)
        for sql in CONTROL_EVENT_STORE_TRIGGER_SQL.values():
            connection.execute(sql.replace("CREATE TRIGGER ", "CREATE TRIGGER IF NOT EXISTS ", 1))
        connection.commit()

    def _append_revision_batch(self, program_id, entries, *, idempotency_key, created_at,
                               expected_revision, require_new, exclusive_program):
        if self.read_only:
            raise RequestValidationError("read-only Control Event Store cannot append events")
        if type(expected_revision) is not int or expected_revision < 0:
            raise RequestValidationError("revision streams require a nonnegative expected_revision")
        if (not isinstance(program_id, str) or not program_id or not isinstance(idempotency_key, str)
                or not idempotency_key or not isinstance(created_at, str) or not created_at
                or not isinstance(entries, (list, tuple)) or not entries):
            raise RequestValidationError("control event batch requires program_id, idempotency_key, time and entries")
        normalized = []
        for entry in entries:
            if (not isinstance(entry, Mapping) or set(entry) != {"event_type", "payload"}
                    or not isinstance(entry["event_type"], str) or not entry["event_type"]
                    or not isinstance(entry["payload"], Mapping)):
                raise RequestValidationError("control entries require event_type and an object payload")
            normalized.append({"event_type": entry["event_type"], "payload": dict(entry["payload"])})
        try:
            # Store the request, not a hash of it. JSON types remain significant.
            request_json = json.dumps({"expected_revision": expected_revision, "entries": normalized},
                                      ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise RequestValidationError("control payload must contain finite JSON values") from exc
        normalized = json.loads(request_json)["entries"]
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if exclusive_program and connection.execute(
                    "SELECT 1 FROM control_events WHERE program_id != ? LIMIT 1", (program_id,)).fetchone():
                raise RevisionConflictError("local controller already belongs to a different Program")
            replay = connection.execute(
                "SELECT request_json, events_json FROM control_idempotency WHERE program_id = ? AND idempotency_key = ?",
                (program_id, idempotency_key)).fetchone()
            if replay is not None:
                if require_new:
                    raise RevisionConflictError("control batch was already reserved; re-read before taking action")
                if replay["request_json"] != request_json:
                    raise IdempotencyConflictError("control idempotency key was reused with different content")
                return json.loads(replay["events_json"])
            revision = connection.execute(
                "SELECT COALESCE(MAX(stream_revision), 0) FROM control_events WHERE program_id = ?", (program_id,)).fetchone()[0]
            if expected_revision != revision:
                raise RevisionConflictError("control event stream changed before append",
                                         details={"expected_revision": expected_revision, "actual_revision": revision})
            appended = []
            for entry in normalized:
                revision += 1
                event = {"schema_version": "REVISION_V1", "event_id": f"CEVT-{uuid.uuid4().hex.upper()}",
                         "program_id": program_id, "stream_revision": revision, **entry, "created_at": created_at}
                connection.execute("""INSERT INTO control_events(event_id, program_id, stream_revision,
                    event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)""",
                    (event["event_id"], program_id, revision, entry["event_type"], canonical_json(entry["payload"]), created_at))
                appended.append(event)
            connection.execute("""INSERT INTO control_idempotency(program_id, idempotency_key, request_json,
                events_json, created_at) VALUES (?, ?, ?, ?, ?)""",
                (program_id, idempotency_key, request_json, canonical_json(appended), created_at))
            connection.commit()
            return appended
