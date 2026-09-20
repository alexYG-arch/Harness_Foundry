"""Read stored legacy authoring facts without loading a producer or evaluating it."""

import json
from pathlib import Path
import sqlite3

from .build_types import RequestValidationError


def read_history(database, program_id):
    path = Path(database).expanduser().resolve()
    if not path.is_file():
        raise RequestValidationError("historical database does not exist")
    wal = Path(str(path) + "-wal")
    # A stopped, checkpointed authoring database can be read without creating
    # journals/SHM. Do not ignore live WAL bytes or mutate a database to open it.
    if wal.exists() and wal.stat().st_size:
        raise RequestValidationError("historical database has a live WAL; close its owner and checkpoint it before history inspection")
    connection = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        record = connection.execute(
            "SELECT program_id, revision, factory_state, state_hash, snapshot_json FROM programs WHERE program_id=?",
            (program_id,),
        ).fetchone()
        if record is None:
            raise RequestValidationError("program is absent from historical authoring database")
        snapshot = json.loads(record["snapshot_json"])
    except (sqlite3.DatabaseError, ValueError) as exc:
        raise RequestValidationError("not a readable legacy authoring database", details={"error": str(exc)}) from exc
    finally:
        connection.close()
    return {"status": "HISTORICAL_READBACK", "program_id": record["program_id"],
            "revision": record["revision"], "recorded_factory_state": record["factory_state"],
            "recorded_state_hash": record["state_hash"], "recorded_snapshot": snapshot,
            "snapshot_is_historical_data_not_current_authority": True,
            "next_allowed_intents": [], "writes_performed": False,
            "execution_authorized": False, "migration_performed": False}
