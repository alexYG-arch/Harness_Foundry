"""Complete, explicit local-source intake. Documents are data, never instructions.

Only UTF-8 Markdown, plain text and JSON are supported. This module neither
discovers linked documents nor writes storage, executes commands or calls a
model. Its snapshot can be recorded by the existing proposal controller.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping

from .models import RequestValidationError, SAFE_ID_RE


_FORMATS = {".md": "MARKDOWN", ".markdown": "MARKDOWN", ".txt": "TEXT", ".json": "JSON"}
_LOCATOR = re.compile(r"L([1-9][0-9]*)(?:-L([1-9][0-9]*))?")
_SOURCE_FIELDS = {"source_id", "path_or_uri", "loaded_completely", "format", "text", "line_count"}
_SNAPSHOT_FIELDS = {"schema_version", "sources", "semantic_completeness_verified", "instructions_executed"}


def _require(condition: bool, code: str, message: str, **details: Any) -> None:
    if not condition:
        raise RequestValidationError(message, details={"reason_code": code, **details})


def _source_id(value: Any) -> None:
    _require(isinstance(value, str) and SAFE_ID_RE.fullmatch(value) is not None,
             "SOURCE_ID_INVALID", "source_id must be a path-safe identifier")


def _portable_path(value: Any) -> PurePosixPath:
    _require(isinstance(value, str) and bool(value), "SOURCE_PATH_INVALID", "source path must be nonempty text")
    path = PurePosixPath(value)
    _require(not path.is_absolute() and path.as_posix() == value and value != "."
             and ".." not in path.parts and "\\" not in value and ":" not in value
             and not any(ord(character) < 32 for character in value),
             "SOURCE_PATH_INVALID", "source path must be a canonical relative file path", path=value)
    return path


def _validate_json(text: str, path: str) -> None:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-JSON numeric value: {value}")

    try:
        json.loads(text, parse_constant=reject_constant)
    except (ValueError, RecursionError) as exc:
        raise RequestValidationError("source is not valid JSON", details={
            "reason_code": "SOURCE_PARSE_ERROR", "path": path, "diagnostic": str(exc),
        }) from exc


def load_local_sources(source_root: Path, manifest: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Read every manifest entry, without truncation or implicit link following.

    Each entry has exactly ``source_id`` and ``path``. An attachment must be its
    own entry. All paths are relative to ``source_root`` and must resolve inside
    it. Returned text preserves decoded bytes, including line endings.
    """
    _require(isinstance(manifest, list) and bool(manifest), "SOURCE_MANIFEST_INVALID",
             "source manifest must be a nonempty list")
    try:
        root = Path(source_root).resolve(strict=True)
    except (OSError, RuntimeError, TypeError) as exc:
        raise RequestValidationError("source root is unavailable", details={
            "reason_code": "SOURCE_ROOT_UNAVAILABLE", "diagnostic": str(exc),
        }) from exc
    _require(root.is_dir(), "SOURCE_ROOT_UNAVAILABLE", "source root must be a directory")
    sources = []
    source_ids: set[str] = set()
    for entry in manifest:
        _require(isinstance(entry, Mapping) and set(entry) == {"source_id", "path"},
                 "SOURCE_MANIFEST_INVALID", "source entries require exactly source_id and path")
        source_id = entry["source_id"]
        _source_id(source_id)
        _require(source_id not in source_ids, "SOURCE_ID_DUPLICATE", "duplicate source_id", source_id=source_id)
        source_ids.add(source_id)
        path = _portable_path(entry["path"])
        source_format = _FORMATS.get(path.suffix.lower())
        _require(source_format is not None, "SOURCE_FORMAT_UNSUPPORTED",
                 "supported source formats are Markdown, plain text and JSON", path=str(path), source_id=source_id)
        try:
            resolved = (root / path).resolve(strict=True)
            _require(resolved.is_relative_to(root), "SOURCE_OUTSIDE_ROOT",
                     "source resolves outside the declared source root", path=str(path), source_id=source_id)
            _require(resolved.is_file(), "SOURCE_NOT_FILE", "source must be a regular file",
                     path=str(path), source_id=source_id)
            text = resolved.read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RequestValidationError("source is not valid UTF-8", details={
                "reason_code": "SOURCE_ENCODING_UNSUPPORTED", "source_id": source_id, "path": str(path),
            }) from exc
        except (OSError, RuntimeError) as exc:
            raise RequestValidationError("source or explicit attachment cannot be read", details={
                "reason_code": "SOURCE_UNAVAILABLE", "source_id": source_id, "path": str(path),
                "diagnostic": str(exc),
            }) from exc
        if source_format == "JSON":
            _validate_json(text, str(path))
        sources.append({"source_id": source_id, "path_or_uri": str(path), "loaded_completely": True,
                        "format": source_format, "text": text, "line_count": len(text.splitlines())})
    return {"schema_version": "1.0", "sources": sources,
            "semantic_completeness_verified": False, "instructions_executed": False}


def _source_catalog(snapshot: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    _require(isinstance(snapshot, Mapping) and set(snapshot) == _SNAPSHOT_FIELDS,
             "SOURCE_SNAPSHOT_INVALID", "invalid source snapshot fields")
    _require(snapshot["schema_version"] == "1.0"
             and snapshot["semantic_completeness_verified"] is False and snapshot["instructions_executed"] is False,
             "SOURCE_SNAPSHOT_INVALID", "source snapshot cannot claim semantic acceptance or instruction execution")
    rows = snapshot["sources"]
    _require(isinstance(rows, list) and bool(rows), "SOURCE_SNAPSHOT_INVALID", "snapshot requires sources")
    catalog = {}
    for source in rows:
        _require(isinstance(source, Mapping) and set(source) == _SOURCE_FIELDS,
                 "SOURCE_SNAPSHOT_INVALID", "invalid source snapshot row")
        _source_id(source["source_id"])
        _require(source["source_id"] not in catalog, "SOURCE_ID_DUPLICATE", "duplicate snapshot source_id")
        path = _portable_path(source["path_or_uri"])
        _require(source["format"] == _FORMATS.get(path.suffix.lower()) and source["format"] is not None
                 and source["loaded_completely"] is True and isinstance(source["text"], str),
                 "SOURCE_SNAPSHOT_INVALID", "snapshot format, complete-read flag or text is invalid")
        _require(type(source["line_count"]) is int and source["line_count"] == len(source["text"].splitlines()),
                 "SOURCE_SNAPSHOT_INVALID", "snapshot line count disagrees with complete text")
        if source["format"] == "JSON":
            _validate_json(source["text"], str(path))
        catalog[source["source_id"]] = source
    return catalog


def _resolve(source: Mapping[str, Any], locator: Any) -> str:
    match = _LOCATOR.fullmatch(locator) if isinstance(locator, str) else None
    _require(match is not None, "SOURCE_LOCATOR_INVALID", "source_locator must be L1 or L1-L3",
             source_id=source["source_id"], locator=locator)
    first, last = int(match[1]), int(match[2] or match[1])
    lines = source["text"].splitlines(keepends=True)
    _require(first <= last <= len(lines), "SOURCE_LOCATOR_UNRESOLVED", "source_locator is outside source lines",
             source_id=source["source_id"], locator=locator, line_count=len(lines))
    return "".join(lines[first - 1:last])


def resolve_source_locator(snapshot: Mapping[str, Any], source_id: str, locator: str) -> str:
    """Resolve a line locator against snapshot text, without rereading live files."""
    catalog = _source_catalog(snapshot)
    _source_id(source_id)
    _require(source_id in catalog, "SOURCE_REFERENCE_UNKNOWN", "source_id is not in the snapshot", source_id=source_id)
    return _resolve(catalog[source_id], locator)


def validate_requirement_source_bindings(requirement_ir: Mapping[str, Any], snapshot: Mapping[str, Any]) -> None:
    """Check full source inventory and Atom locators; not paraphrase/PRD semantics.

    A valid locator does not prove the Atom faithfully represents its source or
    that every requirement has an Atom. Those remain semantic review obligations.
    """
    catalog = _source_catalog(snapshot)
    _require(isinstance(requirement_ir, Mapping), "SOURCE_BINDING_INVALID", "requirements must be an object")
    sources = requirement_ir.get("sources")
    _require(isinstance(sources, list), "SOURCE_BINDING_INVALID", "requirements must declare sources")
    bound = set()
    for source in sources:
        _require(isinstance(source, Mapping), "SOURCE_BINDING_INVALID", "requirement sources must be objects")
        source_id = source.get("source_id")
        _source_id(source_id)
        _require(source_id in catalog and source_id not in bound, "SOURCE_BINDING_INVALID",
                 "requirement source is missing from the snapshot or duplicated", source_id=source_id)
        _require(source.get("path_or_uri") == catalog[source_id]["path_or_uri"] and source.get("loaded_completely") is True,
                 "SOURCE_BINDING_INVALID", "requirement source path or complete-read flag disagrees with snapshot", source_id=source_id)
        bound.add(source_id)
    _require(bound == set(catalog), "SOURCE_INVENTORY_INCOMPLETE", "requirements omit an explicitly loaded source or attachment")
    atoms = requirement_ir.get("atoms")
    _require(isinstance(atoms, list) and bool(atoms), "SOURCE_BINDING_INVALID", "requirements must contain atoms")
    for atom in atoms:
        _require(isinstance(atom, Mapping), "SOURCE_BINDING_INVALID", "requirement atoms must be objects")
        source_id = atom.get("source_id")
        _source_id(source_id)
        _require(source_id in catalog, "SOURCE_REFERENCE_UNKNOWN", "Atom source_id is not in snapshot", source_id=source_id)
        _resolve(catalog[source_id], atom.get("source_locator"))
