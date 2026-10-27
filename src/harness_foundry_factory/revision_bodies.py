"""Optional physical source-body storage, not another event/authority ledger.

Only known captured-source locations are extracted. Public event payloads and
REVISION_V1 request semantics are reconstructed without changing their values.
"""

from copy import deepcopy
import hashlib
import json
import sqlite3

from .build_types import RequestValidationError


INLINE = "REVISION_V1"
COMPACT = "REVISION_BODIES_V1"
BODY_COLUMNS = (("body_id", "TEXT", 1, 1), ("size_bytes", "INTEGER", 1, 0),
                ("content", "BLOB", 1, 0))
BODY_TRIGGERS = {
    f"control_source_bodies_reject_{verb}":
        f"CREATE TRIGGER control_source_bodies_reject_{verb} BEFORE {verb.upper()} ON control_source_bodies "
        "BEGIN SELECT RAISE(ABORT, 'source bodies are immutable'); END"
    for verb in ("update", "delete")
}


def require(condition, message):
    if not condition:
        raise RequestValidationError(message, details={"reason_code": "SOURCE_BODY_STORAGE_INVALID"})


def content_id(content):
    return hashlib.sha256(content).hexdigest()


def encode_payload(kind, payload):
    """References live outside the payload; user keys cannot impersonate them."""
    copied = deepcopy(payload)
    prefix = ({"BUILD_SOURCES_CAPTURED": ["snapshot", "sources"],
               "BUILD_PREVIEW_CONFIRMED": ["preview", "source", "snapshot", "sources"]}).get(kind)
    sources = copied
    for key in prefix or []:
        sources = sources.get(key) if isinstance(sources, dict) else None
    refs, bodies = [], {}
    if prefix is not None and isinstance(sources, list):
        for index, source in enumerate(sources):
            if isinstance(source, dict) and isinstance(source.get("text"), str):
                content = source.pop("text").encode("utf-8")
                identity = content_id(content)
                require(identity not in bodies or bodies[identity] == content, "source body identity collision")
                bodies[identity] = content
                refs.append({"path": [*prefix, index, "text"], "body_id": identity, "size_bytes": len(content)})
    return copied, refs, bodies


def verify_body(row, identity, size):
    require(row is not None, "captured source body is missing; preserve evidence and restore its original bytes")
    content = row["content"]
    require(isinstance(content, bytes) and type(size) is int and size >= 0
            and row["size_bytes"] == size == len(content) and content_id(content) == identity,
            "captured source body is damaged or bound to different content")
    return content


def store_bodies(connection, bodies):
    for identity, content in bodies.items():
        row = connection.execute("SELECT size_bytes, content FROM control_source_bodies WHERE body_id = ?",
                                 (identity,)).fetchone()
        if row is None:
            connection.execute("INSERT INTO control_source_bodies(body_id, size_bytes, content) VALUES (?, ?, ?)",
                               (identity, len(content), sqlite3.Binary(content)))
        else:
            require(verify_body(row, identity, len(content)) == content, "source body identity collision")


def hydrate_payload(connection, payload, refs_json):
    refs = json.loads(refs_json)
    require(isinstance(refs, list), "source body reference list is invalid")
    for ref in refs:
        require(isinstance(ref, dict) and set(ref) == {"path", "body_id", "size_bytes"},
                "source body reference is invalid")
        path = ref["path"]
        require(isinstance(path, list) and path and path[-1] == "text"
                and isinstance(ref["body_id"], str), "source body reference path is invalid")
        parent = payload
        for key in path[:-1]:
            require((isinstance(parent, dict) and isinstance(key, str) and key in parent)
                    or (isinstance(parent, list) and type(key) is int and 0 <= key < len(parent)),
                    "source body reference target is missing")
            parent = parent[key]
        require(isinstance(parent, dict) and "text" not in parent, "source body reference conflicts with payload")
        row = connection.execute("SELECT size_bytes, content FROM control_source_bodies WHERE body_id = ?",
                                 (ref["body_id"],)).fetchone()
        content = verify_body(row, ref["body_id"], ref["size_bytes"])
        try:
            parent["text"] = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RequestValidationError("captured source body is not original UTF-8") from exc
    return payload


def check_schema(connection):
    columns = tuple((str(r[1]), str(r[2]).upper(), int(r[3]), int(r[5]))
                    for r in connection.execute("PRAGMA table_info(control_source_bodies)"))
    require(columns == BODY_COLUMNS, "compact source body table has an incompatible schema")
    triggers = {row[0]: " ".join(row[1].split()) for row in connection.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'trigger'")}
    require(all(triggers.get(name) == " ".join(sql.split()) for name, sql in BODY_TRIGGERS.items()),
            "compact source body table lacks immutable guards")


def initialize_schema(connection):
    connection.execute("CREATE TABLE control_source_bodies (body_id TEXT NOT NULL PRIMARY KEY, "
                       "size_bytes INTEGER NOT NULL, content BLOB NOT NULL)")
    for sql in BODY_TRIGGERS.values():
        connection.execute(sql)
