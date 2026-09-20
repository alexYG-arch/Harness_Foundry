"""The existing REVISION_V1 control store, isolated from legacy authoring.

The database format and events are unchanged; no migration or second state
store is created by extracting this implementation.
"""

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator, Mapping
import uuid

from .build_types import (RequestValidationError, RevisionConflictError,
                          IdempotencyConflictError, canonical_json)

REVISION_CONTROL_EVENT_STORE_TABLE_COLUMNS = {
    "control_events": (
        ("sequence", "INTEGER", 0, 1), ("event_id", "TEXT", 1, 0),
        ("program_id", "TEXT", 1, 0), ("stream_revision", "INTEGER", 1, 0),
        ("event_type", "TEXT", 1, 0), ("payload_json", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "control_idempotency": (
        ("program_id", "TEXT", 1, 1), ("idempotency_key", "TEXT", 1, 2),
        ("request_json", "TEXT", 1, 0), ("events_json", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
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


class RevisionControlEventStore:
    """Revision CAS and literal request idempotency in one append-only SQLite database."""

    _table_columns = REVISION_CONTROL_EVENT_STORE_TABLE_COLUMNS

    def __init__(
        self, database_path: str | Path, *, read_only: bool = False,
        storage_format: str = "REVISION_V1",
    ) -> None:
        if storage_format != "REVISION_V1":
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

    def _initialize(self, *, database_existed):
        with self._connection() as connection:
            if database_existed:
                self._require_exact_existing_schema(connection, self._table_columns)
            connection.execute("PRAGMA journal_mode = WAL")
            self._initialize_revision_schema(connection)

    @staticmethod
    def _require_exact_existing_schema(connection: sqlite3.Connection, columns=None) -> None:
        """Fail before WAL, DDL, or event mutation for a non-native database."""

        table_names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        columns = REVISION_CONTROL_EVENT_STORE_TABLE_COLUMNS if columns is None else columns
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

    def append_batch(self, program_id, entries, *, idempotency_key, created_at,
                     expected_revision=None, require_new=False, exclusive_program=False,
                     expected_previous_event_hash=None):
        if expected_previous_event_hash is not None:
            raise RequestValidationError("revision streams do not accept event hashes")
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


    def list_events(self, program_id):
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM control_events WHERE program_id = ? ORDER BY stream_revision",
                (program_id,),
            ).fetchall()
        return [{"schema_version": "REVISION_V1", "event_id": str(row["event_id"]),
                 "program_id": str(row["program_id"]), "stream_revision": int(row["stream_revision"]),
                 "event_type": str(row["event_type"]), "payload": json.loads(str(row["payload_json"])),
                 "created_at": str(row["created_at"])} for row in rows]

    def list_program_ids(self):
        with self._connection() as connection:
            return [str(row[0]) for row in connection.execute(
                "SELECT DISTINCT program_id FROM control_events ORDER BY program_id")]

    def verify_stream(self, program_id):
        events = self.list_events(program_id)
        errors = [{"code": "CONTROL_EVENT_REVISION_GAP"} for revision, event in enumerate(events, 1)
                  if event["stream_revision"] != revision]
        return {"schema_version": "REVISION_V1", "status": "FAIL" if errors else "PASS",
                "program_id": program_id, "event_count": len(events), "errors": errors,
                "last_revision": events[-1]["stream_revision"] if events else 0,
                "content_integrity_verified": False}
