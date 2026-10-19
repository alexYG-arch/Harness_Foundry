"""SQLite authoritative Event Store and rebuildable runtime views."""

from __future__ import annotations

from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, Mapping
import uuid

from .util import canonical_json, file_sha256, json_sha256, utc_now, write_json


StateMutator = Callable[[dict[str, Any]], dict[str, Any] | None]


class RuntimeStore:
    """One control-plane store owned by exactly one execution root."""

    def __init__(self, execution_root: str | Path):
        self.execution_root = Path(execution_root).expanduser().resolve()
        self.control_root = self.execution_root / "control_plane"
        self.database_path = self.control_root / "factory.sqlite3"

    def _connect(self, *, writable: bool = False) -> sqlite3.Connection:
        if writable:
            connection = sqlite3.connect(
                self.database_path, timeout=30.0, isolation_level=None
            )
        else:
            connection = sqlite3.connect(
                f"{self.database_path.as_uri()}?mode=ro",
                uri=True,
                timeout=30.0,
                isolation_level=None,
            )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        if writable:
            connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self, initial_state: Mapping[str, Any]) -> dict[str, Any]:
        self.control_root.mkdir(parents=True, exist_ok=True)
        with closing(self._connect(writable=True)) as connection:
            self._create_schema(connection)
            existing = connection.execute(
                "SELECT COUNT(*) AS count FROM runtime_state"
            ).fetchone()["count"]
            if existing:
                raise FileExistsError(
                    f"runtime store is already initialized: {self.database_path}"
                )
            connection.execute("BEGIN IMMEDIATE")
            try:
                state = deepcopy(dict(initial_state))
                state["revision"] = 0
                state["updated_at"] = utc_now()
                connection.execute(
                    """
                    INSERT INTO runtime_state(singleton, revision, state_json, state_sha256)
                    VALUES(1, 0, ?, ?)
                    """,
                    (canonical_json(state), json_sha256(state)),
                )
                connection.execute(
                    "INSERT INTO metadata(key, value) VALUES('fencing_counter', '0')"
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.append(
            "RUNTIME_STORE_INITIALIZED",
            {"runtime_version": state.get("runtime_version")},
        )["state"]

    def append(
        self,
        event_type: str,
        details: Mapping[str, Any],
        *,
        mutate: StateMutator | None = None,
        expected_revision: int | None = None,
        fencing_token: int | None = None,
        evidence_sha256: str | None = None,
    ) -> dict[str, Any]:
        with closing(self._connect(writable=True)) as connection:
            self._create_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT revision, state_json FROM runtime_state WHERE singleton=1"
                ).fetchone()
                if row is None:
                    raise RuntimeError("runtime store is not initialized")
                revision = int(row["revision"])
                if (
                    expected_revision is not None
                    and revision != expected_revision
                ):
                    raise RuntimeError(
                        f"stale runtime revision: expected {expected_revision}, got {revision}"
                    )
                state = json.loads(row["state_json"])
                candidate = deepcopy(state)
                if mutate is not None:
                    replacement = mutate(candidate)
                    if replacement is not None:
                        candidate = replacement
                candidate["revision"] = revision + 1
                candidate["updated_at"] = utc_now()
                state_hash = json_sha256(candidate)
                previous = connection.execute(
                    "SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                previous_hash = previous["event_hash"] if previous else None
                seq_row = connection.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM events"
                ).fetchone()
                seq = int(seq_row["next_seq"])
                payload = {
                    "details": deepcopy(dict(details)),
                    "result_state": candidate,
                    "result_state_sha256": state_hash,
                }
                event_body = {
                    "seq": seq,
                    "event_id": str(uuid.uuid4()),
                    "event_type": event_type,
                    "occurred_at": utc_now(),
                    "payload": payload,
                    "previous_hash": previous_hash,
                    "fencing_token": fencing_token,
                    "evidence_sha256": evidence_sha256,
                }
                event_hash = json_sha256(event_body)
                connection.execute(
                    """
                    INSERT INTO events(
                        seq, event_id, event_type, occurred_at, payload_json,
                        previous_hash, event_hash, fencing_token, evidence_sha256
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        seq,
                        event_body["event_id"],
                        event_type,
                        event_body["occurred_at"],
                        canonical_json(payload),
                        previous_hash,
                        event_hash,
                        fencing_token,
                        evidence_sha256,
                    ),
                )
                connection.execute(
                    """
                    UPDATE runtime_state
                    SET revision=?, state_json=?, state_sha256=?
                    WHERE singleton=1
                    """,
                    (revision + 1, canonical_json(candidate), state_hash),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        self.rebuild_views()
        return {"state": candidate, "event_hash": event_hash, "seq": seq}

    def reserve(
        self,
        node_id: str,
        attempt_id: str,
        *,
        expected_revision: int,
    ) -> tuple[int, dict[str, Any]]:
        token_box: dict[str, int] = {}

        def mutation(state: dict[str, Any]) -> None:
            if state.get("active_attempt") is not None:
                raise RuntimeError("ACTIVE_ATTEMPT_ALREADY_EXISTS")
            token = int(state.get("fencing_counter", 0)) + 1
            state["fencing_counter"] = token
            token_box["value"] = token
            state["active_attempt"] = {
                "attempt_id": attempt_id,
                "node_id": node_id,
                "fencing_token": token,
                "status": "RESERVED",
                "phase": "HYDRATE",
                "command_index": 0,
                "receipts": [],
                "loop_round": 0,
                "started_at": utc_now(),
            }
            state["active_workpack"] = None

        result = self.append(
            "TRANSITION_RESERVED",
            {"attempt_id": attempt_id, "node_id": node_id},
            mutate=mutation,
            expected_revision=expected_revision,
        )
        return token_box["value"], result["state"]

    def load_state(self) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT state_json FROM runtime_state WHERE singleton=1"
            ).fetchone()
        if row is None:
            raise RuntimeError("runtime store is not initialized")
        return json.loads(row["state_json"])

    def events(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT seq, event_id, event_type, occurred_at, payload_json,
                       previous_hash, event_hash, fencing_token, evidence_sha256
                FROM events ORDER BY seq
                """
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def rebuild_views(self) -> None:
        state = self.load_state()
        events = self.events()
        state_path = self.control_root / "state/PROGRAM_DRIVER_STATE.json"
        write_json(state_path, state)
        event_path = self.control_root / "ledger/EVENTS.jsonl"
        event_path.parent.mkdir(parents=True, exist_ok=True)
        event_path.write_text(
            "".join(canonical_json(event) + "\n" for event in events),
            encoding="utf-8",
        )
        transition_events = [
            event
            for event in events
            if event["event_type"]
            in {
                "NODE_PROMOTED",
                "HARD_STOP_RECORDED",
                "HUMAN_GATE_REACHED",
            }
        ]
        transition_path = (
            self.control_root / "ledger/PHASE_TRANSITION_LEDGER.jsonl"
        )
        transition_path.write_text(
            "".join(
                canonical_json(event) + "\n" for event in transition_events
            ),
            encoding="utf-8",
        )
        authorization = state.get("authorization") or {
            "schema_version": "1.0",
            "status": "NOT_GRANTED",
            "execution_authorization_inherited": False,
        }
        write_json(
            self.control_root / "state/EXECUTION_AUTHORIZATION.json",
            authorization,
        )

    def verify(self) -> dict[str, Any]:
        findings: list[dict[str, str]] = []
        with closing(self._connect()) as connection:
            state_row = connection.execute(
                "SELECT revision, state_json, state_sha256 FROM runtime_state WHERE singleton=1"
            ).fetchone()
            rows = connection.execute(
                """
                SELECT seq, event_id, event_type, occurred_at, payload_json,
                       previous_hash, event_hash, fencing_token, evidence_sha256
                FROM events ORDER BY seq
                """
            ).fetchall()
        if state_row is None:
            return {
                "status": "FAIL",
                "blocking_findings": [
                    {"code": "STATE_MISSING", "message": str(self.database_path)}
                ],
            }
        expected_previous = None
        last_payload: dict[str, Any] | None = None
        for expected_seq, row in enumerate(rows, 1):
            event = self._event_from_row(row)
            body = {
                key: event[key]
                for key in (
                    "seq",
                    "event_id",
                    "event_type",
                    "occurred_at",
                    "payload",
                    "previous_hash",
                    "fencing_token",
                    "evidence_sha256",
                )
            }
            if event["seq"] != expected_seq:
                findings.append(
                    {"code": "EVENT_SEQUENCE_GAP", "message": str(event["seq"])}
                )
            if event["previous_hash"] != expected_previous:
                findings.append(
                    {
                        "code": "LEDGER_CHAIN_BROKEN",
                        "message": f"event {event['seq']}",
                    }
                )
            if event["event_hash"] != json_sha256(body):
                findings.append(
                    {
                        "code": "EVENT_HASH_MISMATCH",
                        "message": f"event {event['seq']}",
                    }
                )
            payload = event["payload"]
            if payload.get("result_state_sha256") != json_sha256(
                payload.get("result_state")
            ):
                findings.append(
                    {
                        "code": "EVENT_STATE_HASH_MISMATCH",
                        "message": f"event {event['seq']}",
                    }
                )
            expected_previous = event["event_hash"]
            last_payload = payload
        state = json.loads(state_row["state_json"])
        if state_row["state_sha256"] != json_sha256(state):
            findings.append(
                {"code": "STATE_HASH_MISMATCH", "message": "runtime_state"}
            )
        if (
            last_payload is None
            or last_payload.get("result_state") != state
            or int(state_row["revision"]) != state.get("revision")
        ):
            findings.append(
                {"code": "STATE_EVENT_DIVERGENCE", "message": "latest event"}
            )
        expected_views = self._expected_views(state, [
            self._event_from_row(row) for row in rows
        ])
        for path, content in expected_views.items():
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                findings.append(
                    {
                        "code": "DERIVED_VIEW_MISMATCH",
                        "message": str(path),
                    }
                )
        for relative, expected_hash in state.get(
            "evidence_index", {}
        ).items():
            path = self.execution_root / relative
            if not path.is_file() or file_sha256(path) != expected_hash:
                findings.append(
                    {
                        "code": "EVIDENCE_HASH_MISMATCH",
                        "message": relative,
                    }
                )
        return {
            "schema_version": "1.0",
            "status": "PASS" if not findings else "FAIL",
            "valid": not findings,
            "event_count": len(rows),
            "revision": state.get("revision"),
            "blocking_findings": findings,
            "sqlite_authoritative": True,
            "derived_views_rebuildable": True,
        }

    def _expected_views(
        self, state: Mapping[str, Any], events: list[dict[str, Any]]
    ) -> dict[Path, str]:
        pretty_state = json.dumps(
            state, ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"
        authorization = state.get("authorization") or {
            "schema_version": "1.0",
            "status": "NOT_GRANTED",
            "execution_authorization_inherited": False,
        }
        pretty_authorization = json.dumps(
            authorization, ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"
        transition_events = [
            event
            for event in events
            if event["event_type"]
            in {
                "NODE_PROMOTED",
                "HARD_STOP_RECORDED",
                "HUMAN_GATE_REACHED",
            }
        ]
        return {
            self.control_root
            / "state/PROGRAM_DRIVER_STATE.json": pretty_state,
            self.control_root
            / "state/EXECUTION_AUTHORIZATION.json": pretty_authorization,
            self.control_root
            / "ledger/EVENTS.jsonl": "".join(
                canonical_json(event) + "\n" for event in events
            ),
            self.control_root
            / "ledger/PHASE_TRANSITION_LEDGER.jsonl": "".join(
                canonical_json(event) + "\n" for event in transition_events
            ),
        }

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "seq": int(row["seq"]),
            "event_id": row["event_id"],
            "event_type": row["event_type"],
            "occurred_at": row["occurred_at"],
            "payload": json.loads(row["payload_json"]),
            "previous_hash": row["previous_hash"],
            "event_hash": row["event_hash"],
            "fencing_token": row["fencing_token"],
            "evidence_sha256": row["evidence_sha256"],
        }

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runtime_state(
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                revision INTEGER NOT NULL,
                state_json TEXT NOT NULL,
                state_sha256 TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events(
                seq INTEGER PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                previous_hash TEXT,
                event_hash TEXT NOT NULL UNIQUE,
                fencing_token INTEGER,
                evidence_sha256 TEXT
            );
            """
        )
