"""Revision-based persistence uses the existing control store, without hashes."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch

from harness_foundry_factory.control_kernel import ControlKernelError, GenericTransitionEngine
from harness_foundry_factory.models import IdempotencyConflictError, RequestValidationError, StateConflictError
from harness_foundry_factory.store import ControlEventStore


NOW = "2026-09-18T00:00:00Z"


class RevisionControlStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "control.sqlite3"
        self.store = ControlEventStore(self.path, storage_format="REVISION_V1")

    def append(self, revision=0, key="request-1", payload=None, **kwargs):
        return self.store.append_batch("DATA", [{"event_type": "PROPOSED", "payload": payload or {"value": 1}}],
                                       idempotency_key=key, created_at=NOW, expected_revision=revision, **kwargs)

    def test_persists_and_rebuilds_events_without_hash_calls_or_columns(self):
        with patch("harness_foundry_factory.store.content_sha256", side_effect=AssertionError("no hashes")):
            first = self.append()
            second = self.append(1, "request-2", {"value": 2})
            reloaded = ControlEventStore(self.path, storage_format="REVISION_V1", read_only=True)
            self.assertEqual(reloaded.list_events("DATA"), first + second)
            self.assertEqual(reloaded.list_program_ids(), ["DATA"])
            report = reloaded.verify_stream("DATA")
            self.assertEqual(report["last_revision"], 2)
            self.assertEqual(report["status"], "PASS")
            self.assertFalse(report["content_integrity_verified"])
        with sqlite3.connect(self.path) as db:
            for table in ("control_events", "control_idempotency"):
                columns = [row[1] for row in db.execute(f"PRAGMA table_info({table})")]
                self.assertFalse(any("hash" in name or "sha256" in name for name in columns))
            self.assertEqual({row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")},
                             {"control_events", "control_idempotency", "sqlite_sequence"})

    def test_exact_replay_is_stable_but_does_not_reserve_a_second_effect(self):
        first = self.append()
        self.append(1, "request-2")
        self.assertEqual(self.append(), first)
        with self.assertRaises(StateConflictError):
            self.append(require_new=True)
        self.assertEqual(len(self.store.list_events("DATA")), 2)

    def test_idempotency_preserves_content_and_json_types(self):
        self.append()
        for changed in ({"value": 2}, {"value": True}, {"value": 1.0}):
            with self.subTest(changed=changed), self.assertRaises(IdempotencyConflictError):
                self.append(payload=changed)
        with self.assertRaises(IdempotencyConflictError):
            self.append(revision=1)

    def test_racing_writers_get_one_commit_without_lost_updates(self):
        barrier = Barrier(2)

        def writer(key):
            barrier.wait()
            try:
                return self.append(key=key)
            except StateConflictError:
                return "CONFLICT"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(writer, ["a", "b"]))
        self.assertEqual(results.count("CONFLICT"), 1)
        self.assertEqual(len(self.store.list_events("DATA")), 1)

    def test_failed_batch_has_no_partial_event_or_idempotency_record(self):
        entries = [{"event_type": "A", "payload": {}}, {"event_type": "B", "payload": {}}]
        with patch("harness_foundry_factory.store.uuid.uuid4") as uuid:
            uuid.return_value.hex = "same-id"
            with self.assertRaises(sqlite3.IntegrityError):
                self.store.append_batch("DATA", entries, idempotency_key="batch", created_at=NOW, expected_revision=0)
        self.assertEqual(self.store.list_events("DATA"), [])
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM control_idempotency").fetchone()[0], 0)
        self.assertEqual(len(self.store.append_batch("DATA", entries, idempotency_key="batch", created_at=NOW,
                                                     expected_revision=0)), 2)

    def test_format_mismatch_never_rewrites_existing_schema_or_history(self):
        self.append()
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA journal_mode=DELETE")
        before = self.path.read_bytes()
        with self.assertRaises(RequestValidationError):
            ControlEventStore(self.path)
        self.assertEqual(self.path.read_bytes(), before)
        legacy_path = self.path.parent / "legacy.sqlite3"
        legacy = ControlEventStore(legacy_path)
        legacy.append_batch("OLD", [{"event_type": "LEGACY", "payload": {}}], idempotency_key="old", created_at=NOW)
        with sqlite3.connect(legacy_path) as db:
            db.execute("PRAGMA journal_mode=DELETE")
        before = legacy_path.read_bytes()
        for readonly in (False, True):
            with self.assertRaises(RequestValidationError):
                ControlEventStore(legacy_path, storage_format="REVISION_V1", read_only=readonly)
            self.assertEqual(legacy_path.read_bytes(), before)
        self.assertEqual(legacy.verify_stream("OLD")["status"], "PASS")

    def test_read_only_and_append_only_boundaries_still_apply(self):
        self.append()
        readonly = ControlEventStore(self.path, storage_format="REVISION_V1", read_only=True)
        with self.assertRaises(RequestValidationError):
            readonly.append_batch("DATA", [{"event_type": "A", "payload": {}}],
                                  idempotency_key="next", created_at=NOW, expected_revision=1)
        with sqlite3.connect(self.path) as db:
            for command in ("DELETE FROM control_events", "UPDATE control_events SET event_type='OTHER'"):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(command)
        missing = self.path.parent / "absent" / "missing.sqlite3"
        with self.assertRaises(RequestValidationError):
            ControlEventStore(missing, storage_format="REVISION_V1", read_only=True)
        self.assertFalse(missing.parent.exists())

    def test_wrong_concurrency_contract_or_invalid_json_fails_before_commit(self):
        for revision in (None, True, -1, 0.0):
            with self.subTest(revision=revision), self.assertRaises(RequestValidationError):
                self.append(revision=revision)
        with self.assertRaises(RequestValidationError):
            self.append(expected_previous_event_hash="old")
        for value in (float("nan"), float("inf"), {1, 2}):
            with self.assertRaises(RequestValidationError):
                self.append(payload={"value": value})
        self.assertEqual(self.store.list_events("DATA"), [])

    def test_exclusive_program_and_stale_revision_are_checked_transactionally(self):
        self.append()
        with self.assertRaises(StateConflictError):
            self.append(key="other")
        with self.assertRaises(StateConflictError):
            self.store.append_batch("OTHER", [{"event_type": "A", "payload": {}}], idempotency_key="new",
                                    created_at=NOW, expected_revision=0, exclusive_program=True)
        self.assertEqual(self.store.list_program_ids(), ["DATA"])

    def test_legacy_runtime_does_not_treat_proposal_store_as_runtime_authority(self):
        with self.assertRaises(ControlKernelError) as caught:
            GenericTransitionEngine(self.store, {})
        self.assertEqual(caught.exception.code, "CONTROL_STORE_FORMAT_UNSUPPORTED")
        self.assertEqual(self.store.list_program_ids(), [])


if __name__ == "__main__":
    unittest.main()
