"""Generic plan Producer -> control transaction -> task-context consumer."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness_foundry_factory.build_authoring import (
    read_build_plan_proposal, read_build_task_context, record_build_plan_proposal,
)
from harness_foundry_factory.models import IdempotencyConflictError, RequestValidationError, StateConflictError
from harness_foundry_factory.store import ControlEventStore
from test_build_plan import request_fixture
from tests.build_review_fixture import reviewed_document


NOW = "2026-09-18T00:00:00Z"


class BuildAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "control.sqlite3"
        self.store = ControlEventStore(self.path, storage_format="REVISION_V1")
        self.request = request_fixture()
        self.ir, self.plan = self.request["requirement_ir"], self.request["plan"]
        self.review = reviewed_document(self.path.parent)

    def record(self, revision=0, key="first"):
        return record_build_plan_proposal(self.store, self.ir, self.plan, expected_revision=revision,
                                          idempotency_key=key, created_at=NOW, document_review=self.review)

    def test_real_sqlite_roundtrip_produces_generic_context_without_executing_or_granting(self):
        with patch("harness_foundry_factory.store.content_sha256", side_effect=AssertionError("no hashes")), \
                patch("subprocess.Popen", side_effect=AssertionError("no commands")):
            event = self.record()
            readonly = ControlEventStore(self.path, read_only=True, storage_format="REVISION_V1")
            readback = read_build_plan_proposal(readonly, self.ir["program_id"])
            self.assertEqual(readback["proposal_binding"]["proposal_event_id"], event["event_id"])
            self.assertEqual(readback["compiled_plan"]["plan"], self.plan)
            context = read_build_task_context(readonly, self.ir["program_id"], "MAKE-REPORT", event_id=event["event_id"])
        self.assertEqual(context["status"], "TASK_CONTEXT_NOT_AUTHORIZED")
        self.assertEqual(context["requirements"], [self.ir["atoms"][1]])
        self.assertEqual(context["sources"], self.ir["sources"])
        self.assertEqual(context["requirement_context"]["target"], self.ir["target"])
        self.assertEqual(context["artifact_inputs"], {"READER-SOURCE": {
            "workpack_id": "IMPLEMENT-READER", "job_id": "READER", "path": "src/reader.py"}})
        self.assertEqual(context["cases"], [{"kind": "acceptance_cases", "declaration": self.ir["acceptance_cases"][1],
                                           "verification": self.plan["workpacks"][1]["verification"][0]}])
        for key in ("authority_validated", "behavior_verified", "execution_started"):
            self.assertIs(context[key], False)
        self.assertNotIn("sha256", json.dumps(context))
        self.assertEqual(self.store.list_events(self.ir["program_id"]), [event])
        self.assertFalse((self.path.parent / "outputs").exists())

    def test_replanning_does_not_mutate_requirements_or_require_new_requirement_revision(self):
        first = self.record()
        self.plan["revision"] = 2
        self.plan["workpacks"][0]["goal"] = "Implement a streaming parser and retain the same acceptance."
        second = self.record(1, "second")
        latest = read_build_plan_proposal(self.store, self.ir["program_id"])
        self.assertEqual(latest["proposal_binding"]["requirement_revision"], 1)
        self.assertEqual(latest["proposal_binding"]["plan_revision"], 2)
        old = read_build_task_context(self.store, self.ir["program_id"], "IMPLEMENT-READER", event_id=first["event_id"])
        self.assertNotEqual(old["workpack"]["goal"], self.plan["workpacks"][0]["goal"])
        self.assertEqual(self.store.list_events(self.ir["program_id"]), [first, second])

    def test_requirement_change_requires_a_new_revision_but_does_not_approve_it(self):
        self.record()
        self.plan["revision"] = 2
        self.ir["target"]["scope"].append("Process TSV files too")
        with self.assertRaises(StateConflictError):
            self.record(1, "changed")
        self.ir["revision"] = self.plan["requirement_revision"] = 2
        self.record(1, "changed")
        latest = read_build_plan_proposal(self.store, self.ir["program_id"])
        self.assertEqual(latest["proposal_binding"]["requirement_revision"], 2)
        self.assertFalse(latest["compiled_plan"]["authority_validated"])

    def test_idempotent_proposal_retry_after_further_progress_returns_original_event(self):
        original = deepcopy(self.request)
        first = self.record()
        self.plan["revision"] = 2
        self.record(1, "second")
        self.ir, self.plan = original["requirement_ir"], original["plan"]
        self.assertEqual(self.record(), first)
        self.plan["workpacks"][0]["goal"] = "Different content"
        with self.assertRaises(IdempotencyConflictError):
            self.record()
        self.assertEqual(len(self.store.list_events(self.ir["program_id"])), 2)

    def test_stale_writer_or_same_plan_revision_cannot_silently_replace_proposal(self):
        self.record()
        with self.assertRaises(StateConflictError):
            self.record(1, "same-revision")
        self.plan["revision"] = 2
        with self.assertRaises(StateConflictError):
            self.record(0, "stale")
        with self.assertRaises(StateConflictError):
            self.record(2, "future")
        self.plan["plan_id"] = "ANOTHER-ID"
        with self.assertRaises(StateConflictError):
            self.record(1, "new-id")

    def test_invalid_plan_rejected_before_any_persistence(self):
        self.plan["workpacks"][1]["depends_on"] = []
        with self.assertRaises(RequestValidationError):
            self.record()
        self.assertEqual(self.store.list_program_ids(), [])

    def test_wrong_program_task_or_event_cannot_receive_context(self):
        event = self.record()
        for program, task, ref in (("OTHER", "MAKE-REPORT", event["event_id"]),
                                   (self.ir["program_id"], "MISSING", event["event_id"]),
                                   (self.ir["program_id"], "MAKE-REPORT", "MISSING"),
                                   (self.ir["program_id"], "MAKE-REPORT", None)):
            with self.subTest(program=program, task=task), self.assertRaises(RequestValidationError):
                read_build_task_context(self.store, program, task, event_id=ref)

    def test_context_keeps_global_constraints_and_all_owned_case_kinds(self):
        self.ir["constraints"] = ["No network access"]
        event = self.record()
        context = read_build_task_context(self.store, self.ir["program_id"], "IMPLEMENT-READER", event_id=event["event_id"])
        self.assertEqual(context["requirement_context"]["constraints"], ["No network access"])
        self.assertEqual([case["kind"] for case in context["cases"]], ["acceptance_cases", "negative_cases"])
        context["workpack"]["job_id"] = "OTHER"
        fresh = read_build_task_context(self.store, self.ir["program_id"], "IMPLEMENT-READER", event_id=event["event_id"])
        self.assertEqual(fresh["workpack"]["job_id"], "READER")

    def test_legacy_streams_are_not_mutated_or_reinterpreted_as_new_authority(self):
        self.store = ControlEventStore(self.path.parent / "legacy.sqlite3")
        with self.assertRaises(RequestValidationError):
            self.record()
        self.assertEqual(self.store.list_program_ids(), [])


if __name__ == "__main__":
    unittest.main()
