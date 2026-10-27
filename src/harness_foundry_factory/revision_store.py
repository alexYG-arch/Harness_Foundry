"""REVISION_V1 logical events with inline or optional same-database bodies.

Existing databases are never migrated implicitly. New physical schemas remain
separate from execution authorization and the unchanged event protocol.
"""

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator, Mapping
import uuid

from .revision_bodies import (COMPACT, INLINE, check_schema as check_body_schema,
    encode_payload, hydrate_payload, initialize_schema as initialize_body_schema,
    require as require_body_storage, store_bodies, verify_body)

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
        storage_format: str = "REVISION_V1", physical_format: str | None = None,
    ) -> None:
        if storage_format != "REVISION_V1":
            raise RequestValidationError("unsupported control event storage format")
        self.storage_format = storage_format
        self.database_path = Path(database_path).expanduser().resolve()
        self.read_only = read_only
        if physical_format not in (None, INLINE, COMPACT):
            raise RequestValidationError("unsupported physical control storage format")
        self.physical_format = physical_format or INLINE
        database_existed = self.database_path.exists()
        if read_only and not database_existed:
            raise RequestValidationError(
                "read-only control event store does not exist",
                details={"database_path": str(self.database_path)},
            )
        if database_existed:
            # Inspect existing format without WAL/DDL or automatic migration.
            with self._connection() as connection:
                names = {row[1] for row in connection.execute("PRAGMA table_info(control_events)")}
                detected = COMPACT if "source_refs_json" in names else INLINE
                if physical_format is not None and physical_format != detected:
                    raise RequestValidationError("existing control storage differs; migration is not automatic")
                self.physical_format = detected
                if detected == INLINE and connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE name = 'control_source_bodies'").fetchone():
                    raise RequestValidationError("incomplete compact control storage")
        self._compact = self.physical_format == COMPACT
        self._table_columns = dict(REVISION_CONTROL_EVENT_STORE_TABLE_COLUMNS)
        if self._compact:
            self._table_columns["control_events"] += (("source_refs_json", "TEXT", 1, 0),)
        if read_only:
            with self._connection() as connection:
                self._require_schema(connection)
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

    def _require_schema(self, connection):
        self._require_exact_existing_schema(connection, self._table_columns)
        if self._compact:
            check_body_schema(connection)

    def _initialize(self, *, database_existed):
        with self._connection() as connection:
            if database_existed:
                self._require_schema(connection)
            connection.execute("PRAGMA journal_mode = WAL")
            if self._compact and not database_existed:
                # Only a newly selected database receives this physical schema.
                self._initialize_revision_schema(connection, compact=True)
            elif not self._compact:
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
    def _initialize_revision_schema(connection: sqlite3.Connection, *, compact=False) -> None:
        schema_sql = """
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
        """
        if compact:
            connection.execute("BEGIN IMMEDIATE")
            for statement in schema_sql.split(";"):
                if statement.strip():
                    connection.execute(statement)
            connection.execute("ALTER TABLE control_events ADD COLUMN source_refs_json TEXT NOT NULL DEFAULT '[]'")
            initialize_body_schema(connection)
        else:
            connection.executescript(schema_sql)
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
        encoded, contents = [], {}
        if self._compact:
            for entry in normalized:
                payload, refs, extracted = encode_payload(entry["event_type"], entry["payload"])
                for identity, content in extracted.items():
                    require_body_storage(identity not in contents or contents[identity] == content, "source body identity collision")
                    contents[identity] = content
                encoded.append({"event_type": entry["event_type"], "payload": payload, "source_refs": refs})
            request_json = canonical_json({"expected_revision": expected_revision, "entries": encoded})
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
                # Hydrate the exact original ordered result, never reserve again.
                result = self._replay_events(connection, program_id, replay["events_json"])
                if self._compact:
                    for identity, content in contents.items():
                        row = connection.execute("SELECT size_bytes, content FROM control_source_bodies WHERE body_id = ?", (identity,)).fetchone()
                        require_body_storage(verify_body(row, identity, len(content)) == content, "source body identity collision")
                return result
            revision = connection.execute(
                "SELECT COALESCE(MAX(stream_revision), 0) FROM control_events WHERE program_id = ?", (program_id,)).fetchone()[0]
            if expected_revision != revision:
                raise RevisionConflictError("control event stream changed before append",
                                         details={"expected_revision": expected_revision, "actual_revision": revision})
            if self._compact:
                store_bodies(connection, contents)
            appended = []
            for index, entry in enumerate(normalized):
                revision += 1
                event = {"schema_version": "REVISION_V1", "event_id": f"CEVT-{uuid.uuid4().hex.upper()}",
                         "program_id": program_id, "stream_revision": revision, **entry, "created_at": created_at}
                values = (event["event_id"], program_id, revision, entry["event_type"],
                          canonical_json(encoded[index]["payload"] if self._compact else entry["payload"]), created_at)
                if self._compact:
                    connection.execute("""INSERT INTO control_events(event_id, program_id, stream_revision,
                        event_type, payload_json, created_at, source_refs_json) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (*values, canonical_json(encoded[index]["source_refs"])))
                else:
                    connection.execute("""INSERT INTO control_events(event_id, program_id, stream_revision,
                        event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)""", values)
                appended.append(event)
            connection.execute("""INSERT INTO control_idempotency(program_id, idempotency_key, request_json,
                events_json, created_at) VALUES (?, ?, ?, ?, ?)""",
                (program_id, idempotency_key, request_json, canonical_json(
                    [e["event_id"] for e in appended] if self._compact else appended), created_at))
            connection.commit()
            return appended


    def idempotent_events(self, program_id, idempotency_key):
        """Read an existing reservation without reserving another effect."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT events_json FROM control_idempotency WHERE program_id = ? AND idempotency_key = ?",
                (program_id, idempotency_key)).fetchone()
            return self._replay_events(connection, program_id, row["events_json"]) if row is not None else None

    def _replay_events(self, connection, program_id, encoded):
        result = json.loads(encoded)
        if not self._compact:
            return result
        require_body_storage(isinstance(result, list) and result and all(isinstance(i, str) for i in result)
                       and len(result) == len(set(result)), "compact idempotent event references are invalid")
        events = []
        for identity in result:
            row = connection.execute("SELECT * FROM control_events WHERE program_id = ? AND event_id = ?",
                                     (program_id, identity)).fetchone()
            require_body_storage(row is not None, "compact idempotent result is missing its original event")
            events.append(self._decode_event(row, connection=connection))
        return events

    _idempotent_events = idempotent_events

    def _decode_event(self, row, *, connection=None, include_text=True):
        payload = json.loads(str(row["payload_json"]))
        if self._compact and include_text:
            if connection is None:
                with self._connection() as current:
                    payload = hydrate_payload(current, payload, row["source_refs_json"])
            else:
                payload = hydrate_payload(connection, payload, row["source_refs_json"])
        return {"schema_version": "REVISION_V1", "event_id": str(row["event_id"]),
                "program_id": str(row["program_id"]), "stream_revision": int(row["stream_revision"]),
                "event_type": str(row["event_type"]), "payload": payload,
                "created_at": str(row["created_at"])}

    def find_event(self, program_id, *, event_type, event_id=None, source_metadata=False):
        """Read one immutable event, never an event from another Program/type."""
        fields = "*"
        if source_metadata:
            if event_type != "BUILD_SOURCES_CAPTURED":
                raise RequestValidationError("source metadata requires a captured source event")
            fields = "*" if self._compact else """event_id, program_id, stream_revision, event_type, created_at,
                json_set(payload_json, '$.snapshot.sources', json((
                    SELECT json_group_array(json_remove(s.value, '$.text'))
                    FROM json_each(control_events.payload_json, '$.snapshot.sources') AS s))) AS payload_json"""
        query = f"SELECT {fields} FROM control_events WHERE program_id = ? AND event_type = ?"
        args = [program_id, event_type]
        if event_id is not None:
            query += " AND event_id = ?"
            args.append(event_id)
        with self._connection() as connection:
            try:
                row = connection.execute(query + " ORDER BY stream_revision DESC LIMIT 1", args).fetchone()
            except sqlite3.OperationalError as exc:
                # JSON SQL is an optimization, not a new runtime prerequisite.
                if not source_metadata or "no such function" not in str(exc).lower():
                    raise
                row = connection.execute(query.replace(fields, "*", 1) +
                                         " ORDER BY stream_revision DESC LIMIT 1", args).fetchone()
            event = self._decode_event(row, connection=connection, include_text=not source_metadata) if row is not None else None
        if event is not None and source_metadata:
            for source in event["payload"]["snapshot"]["sources"]:
                source.pop("text", None)
            event["source_text_omitted"] = True
        return event

    def event_count(self, program_id):
        """Count actual rows; a maximum revision is not a completeness check."""
        with self._connection() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM control_events WHERE program_id = ?",
                                          (program_id,)).fetchone()[0])

    def list_control_events(self, program_id):
        """One statement snapshot, retaining every event identity and ordering.

        Source bodies are omitted explicitly. Full list_events remains unchanged.
        Bound sources can be hydrated later by immutable identity. No view is
        cached across calls or used to cache a previous authorization decision.
        """
        query = """SELECT event_id, program_id, stream_revision, event_type,
            CASE WHEN event_type = 'BUILD_SOURCES_CAPTURED' THEN '{}'
                 ELSE payload_json END AS payload_json, created_at
            FROM control_events WHERE program_id = ? ORDER BY stream_revision"""
        if self._compact:
            query = query.replace("created_at\n", "created_at, source_refs_json\n")
        with self._connection() as connection:
            rows = connection.execute(query, (program_id,)).fetchall()
            events = [self._decode_event(row, connection=connection,
                                         include_text=row["event_type"] != "BUILD_SOURCES_CAPTURED") for row in rows]
        for event in events:
            if event["event_type"] == "BUILD_SOURCES_CAPTURED":
                event["payload_omitted"] = True
        return events

    def hydrate_source_event(self, program_id, events, event_id, *, include_text=True):
        """Load only a source in this view; later appends cannot change its identity."""
        for index, event in enumerate(events):
            if (event["event_id"] == event_id and event["event_type"] == "BUILD_SOURCES_CAPTURED"
                    and event["program_id"] == program_id):
                if event.get("payload_omitted") or include_text and event.get("source_text_omitted"):
                    loaded = self.find_event(program_id, event_type="BUILD_SOURCES_CAPTURED", event_id=event_id,
                                             source_metadata=not include_text)
                    if loaded is None or any(loaded[key] != event[key] for key in
                                             ("program_id", "stream_revision", "event_id", "event_type", "created_at")):
                        raise RequestValidationError("source event does not match the control view")
                    events[index] = loaded
                return events[index]
        raise RequestValidationError("source event does not exist in this Program control view")

    def list_events(self, program_id):
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM control_events WHERE program_id = ? ORDER BY stream_revision",
                (program_id,),
            ).fetchall()
            return [self._decode_event(row, connection=connection) for row in rows]

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
