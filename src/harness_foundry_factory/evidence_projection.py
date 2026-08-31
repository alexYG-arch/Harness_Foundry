"""Authority-neutral evidence index and deterministic scoped projection."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping


RETENTION_CLASSES = (
    "ACTIVE_BASELINE",
    "HISTORICAL_REGRESSION",
    "SUPERSEDED",
    "ARCHIVED",
)


class ProjectionConflictError(ValueError):
    pass


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def rebuild_projection(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Rebuild facts by scope and fail closed on same-revision conflicts."""

    ordered = sorted(
        (dict(event) for event in events),
        key=lambda event: (
            str(event.get("authority_scope")),
            str(event.get("instance_id")),
            str(event.get("fact_key")),
            int(event.get("revision", -1)),
            str(event.get("event_sha256")),
        ),
    )
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    index: list[dict[str, Any]] = []
    for event in ordered:
        required = {
            "authority_scope",
            "instance_id",
            "fact_key",
            "fact_value",
            "revision",
            "event_sha256",
            "retention_class",
        }
        missing = sorted(required - set(event))
        if missing:
            raise ProjectionConflictError(f"missing event fields: {missing}")
        if event["retention_class"] not in RETENTION_CLASSES:
            raise ProjectionConflictError("unknown retention class")
        revision = event["revision"]
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ProjectionConflictError("revision must be a non-negative integer")
        key = (
            str(event["authority_scope"]),
            str(event["instance_id"]),
            str(event["fact_key"]),
        )
        previous = latest.get(key)
        if previous is not None:
            if revision < previous["revision"]:
                raise ProjectionConflictError("event order regressed")
            if revision == previous["revision"] and event["fact_value"] != previous[
                "fact_value"
            ]:
                raise ProjectionConflictError("PROJECTION_CONFLICT")
        latest[key] = event
        index.append(
            {
                "authority_scope": key[0],
                "instance_id": key[1],
                "fact_key": key[2],
                "event_sha256": event["event_sha256"],
                "retention_class": event["retention_class"],
                "creates_authority": False,
            }
        )

    facts = [
        {
            "authority_scope": key[0],
            "instance_id": key[1],
            "fact_key": key[2],
            "fact_value": value["fact_value"],
            "revision": value["revision"],
            "source_event_sha256": value["event_sha256"],
        }
        for key, value in sorted(latest.items())
    ]
    body = {
        "schema_version": "2.9",
        "projection_id": "V29_SCOPED_EVIDENCE_PROJECTION_V1",
        "event_count": len(ordered),
        "evidence_index": index,
        "facts": facts,
        "evidence_index_creates_authority": False,
        "projection_rebuildable": True,
        "conflict_behavior": "FAIL_CLOSED_WITH_PROJECTION_CONFLICT",
    }
    return {**body, "projection_sha256": _hash(body)}


__all__ = [
    "RETENTION_CLASSES",
    "ProjectionConflictError",
    "rebuild_projection",
]
