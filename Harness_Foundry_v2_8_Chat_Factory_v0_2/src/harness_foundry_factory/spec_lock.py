"""Hash-lock and verify the sibling Harness Foundry v2.8 specification."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from .constants import (
    HF28_PACKAGE_ID,
    HF28_SCHEMA_VERSION,
    default_spec_lock_path,
    default_spec_root,
)


SPEC_PACKAGE_VERSION = "2.8.0"
SPEC_LOCK_VERSION = "1.0"
IGNORED_NAMES = {".DS_Store"}


class SpecLockError(RuntimeError):
    """Raised when the normative sibling specification cannot be locked."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_hashes(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if (
            not path.is_file()
            or path.name in IGNORED_NAMES
            or path.suffix == ".pyc"
            or "__pycache__" in path.parts
        ):
            continue
        result[path.relative_to(root).as_posix()] = _sha256(path)
    return result


def _file_snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    snapshot: dict[str, tuple[int, int, str]] = {}
    for relative, sha256 in _file_hashes(root).items():
        stat = (root / relative).stat()
        snapshot[relative] = (stat.st_size, stat.st_mtime_ns, sha256)
    return snapshot


def _content_hash(files: Mapping[str, str]) -> str:
    encoded = json.dumps(
        dict(files), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_manifest(spec_root: Path) -> dict[str, Any]:
    path = spec_root / "PACKAGE_MANIFEST.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SpecLockError(f"invalid sibling PACKAGE_MANIFEST.json: {exc}") from exc
    if data.get("package_id") != HF28_PACKAGE_ID:
        raise SpecLockError("sibling package_id is not Harness Foundry v2.8")
    if data.get("version") != SPEC_PACKAGE_VERSION:
        raise SpecLockError(f"sibling version must be {SPEC_PACKAGE_VERSION}")
    return data


def _run_spec_validator(spec_root: Path) -> dict[str, Any]:
    validator = spec_root / "tools" / "validate_package.py"
    if not validator.is_file():
        raise SpecLockError("sibling tools/validate_package.py is missing")
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-B", str(validator), str(spec_root), "--json"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SpecLockError("sibling validator did not emit JSON") from exc
    if completed.returncode != 0 or report.get("status") != "PASS":
        raise SpecLockError("sibling Harness Foundry v2.8 validation failed")
    if report.get("writes_performed") is not False:
        raise SpecLockError("sibling validator did not attest read-only execution")
    return report


def _require_sibling_path(spec_root: Path) -> Path:
    expected = default_spec_root().resolve()
    actual = spec_root.resolve()
    if actual != expected:
        raise SpecLockError(f"spec root must be the sibling path {expected}")
    return actual


def load_spec_lock(lock_path: Path | None = None) -> dict[str, Any]:
    """Load the committed v2.8 lock without rebuilding trusted state."""

    path = lock_path or default_spec_lock_path()
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SpecLockError(f"invalid committed spec lock {path}: {exc}") from exc
    if not isinstance(lock, dict):
        raise SpecLockError(f"committed spec lock {path} must contain one object")
    return lock


def build_spec_lock(spec_root: Path | None = None) -> dict[str, Any]:
    """Return a deterministic lock for the validated, read-only sibling spec."""

    root = _require_sibling_path(spec_root or default_spec_root())
    manifest = _load_manifest(root)
    before_snapshot = _file_snapshot(root)
    before = {path: value[2] for path, value in before_snapshot.items()}
    report = _run_spec_validator(root)
    after_snapshot = _file_snapshot(root)
    if before_snapshot != after_snapshot:
        raise SpecLockError("sibling validator changed the specification tree")
    validator_ref = "tools/validate_package.py"
    return {
        "schema_version": SPEC_LOCK_VERSION,
        "lock_kind": "HARNESS_FOUNDRY_V2_8_SIBLING_SPEC_LOCK",
        "spec_root_abs": str(root),
        "spec_root_name": root.name,
        "package_id": manifest["package_id"],
        "package_version": manifest["version"],
        "hf28_schema_version": HF28_SCHEMA_VERSION,
        "package_manifest_sha256": before["PACKAGE_MANIFEST.json"],
        "validator_ref": validator_ref,
        "validator_sha256": before[validator_ref],
        "validator_id": report.get("validator_id"),
        "file_count": len(before),
        "content_sha256": _content_hash(before),
        "files": before,
    }


def verify_spec_lock(
    lock: Mapping[str, Any], spec_root: Path | None = None
) -> dict[str, Any]:
    """Verify identity, exact files, hashes, path, and current spec validation."""

    findings: list[dict[str, str]] = []

    def fail(code: str, message: str) -> None:
        findings.append({"code": code, "message": message})

    try:
        root = _require_sibling_path(spec_root or default_spec_root())
    except SpecLockError as exc:
        return {"status": "FAIL", "valid": False, "findings": [{"code": "SPEC_PATH_MISMATCH", "message": str(exc)}]}

    if lock.get("spec_root_abs") != str(root):
        fail("SPEC_PATH_MISMATCH", "lock does not bind the current sibling path")
    if lock.get("schema_version") != SPEC_LOCK_VERSION or lock.get("lock_kind") != "HARNESS_FOUNDRY_V2_8_SIBLING_SPEC_LOCK":
        fail("SPEC_LOCK_SCHEMA_INVALID", "lock schema_version or lock_kind is invalid")
    if lock.get("package_id") != HF28_PACKAGE_ID:
        fail("SPEC_IDENTITY_MISMATCH", "lock package_id is not Harness Foundry v2.8")
    if lock.get("package_version") != SPEC_PACKAGE_VERSION:
        fail("SPEC_VERSION_MISMATCH", f"lock version must be {SPEC_PACKAGE_VERSION}")
    if lock.get("hf28_schema_version") != HF28_SCHEMA_VERSION:
        fail("SPEC_SCHEMA_VERSION_MISMATCH", "lock hf28_schema_version is invalid")

    try:
        manifest = _load_manifest(root)
    except SpecLockError as exc:
        fail("SPEC_MANIFEST_INVALID", str(exc))
        manifest = {}
    if manifest and manifest.get("version") != lock.get("package_version"):
        fail("SPEC_VERSION_MISMATCH", "current sibling version differs from the lock")

    current = _file_hashes(root)
    locked_files = lock.get("files")
    if not isinstance(locked_files, dict):
        fail("SPEC_LOCK_FILES_INVALID", "lock files must be an object")
        locked_files = {}
    if lock.get("file_count") != len(locked_files):
        fail("SPEC_FILE_COUNT_MISMATCH", "lock file_count differs from locked files")
    if lock.get("content_sha256") != _content_hash(locked_files):
        fail("SPEC_CONTENT_HASH_MISMATCH", "lock aggregate content hash is invalid")
    if lock.get("package_manifest_sha256") != locked_files.get("PACKAGE_MANIFEST.json"):
        fail("SPEC_MANIFEST_HASH_MISMATCH", "lock manifest hash is invalid")
    missing = sorted(set(locked_files).difference(current))
    added = sorted(set(current).difference(locked_files))
    changed = sorted(
        path for path in set(current).intersection(locked_files) if current[path] != locked_files[path]
    )
    if missing:
        fail("SPEC_FILES_MISSING", ", ".join(missing))
    if added:
        fail("SPEC_FILES_ADDED", ", ".join(added))
    if changed:
        fail("SPEC_FILES_CHANGED", ", ".join(changed))

    validator_ref = lock.get("validator_ref")
    if validator_ref != "tools/validate_package.py":
        fail("SPEC_VALIDATOR_REF_INVALID", "lock validator_ref is not canonical")
    elif current.get(validator_ref) != lock.get("validator_sha256"):
        fail("SPEC_VALIDATOR_HASH_MISMATCH", "current 2.8 validator hash differs from the lock")

    try:
        before = _file_snapshot(root)
        report = _run_spec_validator(root)
        after = _file_snapshot(root)
        if before != after:
            fail("SPEC_VALIDATOR_SIDE_EFFECT", "2.8 validator changed the specification tree")
        if report.get("validator_id") != lock.get("validator_id"):
            fail("SPEC_VALIDATOR_ID_MISMATCH", "validator identity differs from the lock")
    except SpecLockError as exc:
        fail("SPEC_VALIDATION_FAILED", str(exc))

    return {
        "status": "PASS" if not findings else "FAIL",
        "valid": not findings,
        "spec_root": str(root),
        "checked_files": len(current),
        "findings": findings,
    }


def load_verified_spec_lock(
    spec_root: Path | None = None,
    lock_path: Path | None = None,
) -> dict[str, Any]:
    """Load the committed lock and verify the current sibling against it."""

    lock = load_spec_lock(lock_path)
    report = verify_spec_lock(lock, spec_root)
    if report.get("status") != "PASS":
        findings = json.dumps(
            report.get("findings", []),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        raise SpecLockError(f"committed v2.8 spec lock does not verify: {findings}")
    return lock


create_spec_lock = build_spec_lock
verify_spec = verify_spec_lock
