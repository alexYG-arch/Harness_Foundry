"""Paired review-gate tests. All decisions are synthetic, never real grants."""

from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from harness_foundry_factory.build_authoring import record_build_plan_proposal
from harness_foundry_factory.build_entrypoint import read_build
from harness_foundry_factory.build_plan import compile_build_plan
from harness_foundry_factory.build_review import validate_build_review
from harness_foundry_factory.build_runtime import record_source_snapshot
from harness_foundry_factory.cli import main
from harness_foundry_factory.models import RequestValidationError, ProgramNotFoundError
import test_build_entrypoint as public_support
import test_prebuild_delegation as compatibility_support


class GenericDocumentReviewTests(unittest.TestCase):
    def setUp(self):
        self.public = public_support.BuildEntrypointTests()
        self.public.setUp()
        self.addCleanup(self.public.doCleanups)
        self.f = self.public.f

    def change_document(self):
        Path(self.f.review["documents"][0]["path"]).write_text("Changed external contract\n")

    def test_compiler_pass_and_each_raw_input_kind_do_not_replace_confirmation(self):
        for kind in ("natural-language", "answered-questions", "prd", "project-brief", "existing-project"):
            with self.subTest(kind=kind):
                request = deepcopy(self.f.request)
                request.pop("document_review")
                request["requirement_ir"]["input_kind"] = kind
                compiled = compile_build_plan(request["requirement_ir"], request["plan"])
                self.assertEqual(compiled["status"], "PLAN_COMPILED_NOT_AUTHORIZED")
                self.public.mutation("record-build-plan", request, expected=2)
                self.assertFalse(self.public.database.exists())

    def test_nonhuman_self_approval_runtime_grant_and_same_turn_are_rejected(self):
        changes = (
            lambda r: r["decision"]["actor"].update(type="ASSISTANT"),
            lambda r: r["decision"]["actor"].update(type="CODEX_DELEGATED_AGENT"),
            lambda r: r["decision"].update(action="APPROVE_BUILD"),
            lambda r: r["decision"]["actor"].update(turn_id=r["presentation"]["turn_id"]),
            lambda r: r.update(approved=True),
        )
        for change in changes:
            review = deepcopy(self.f.review)
            change(review)
            with self.assertRaises(RequestValidationError):
                validate_build_review(review)
        self.assertFalse(self.public.database.exists())

    def test_changed_document_rejected_before_first_database_creation(self):
        self.change_document()
        self.public.mutation("record-build-plan", self.f.request, expected=2)
        self.assertFalse(self.public.database.exists())

    def test_same_confirmation_cannot_be_rebound_to_new_version(self):
        self.public.mutation("record-build-plan", self.f.request)
        request = deepcopy(self.f.request)
        request["plan"]["revision"] = 2
        request["document_review"]["version"] = "substituted-version"
        self.public.mutation("record-build-plan", request, expected=2)
        self.assertEqual(self.public.cli("read-build")["stream_revision"], 1)

    def test_review_source_identity_and_full_body_must_match_capture(self):
        proposal = record_build_plan_proposal(self.f.store, self.f.ir, self.f.plan,
            document_review=self.f.review, **self.f.kwargs("proposal"))
        # Identical bytes from another path do not rebind the displayed document.
        other = self.f.root / "other-source"
        other.mkdir()
        (other / "brief.md").write_text(self.f.source_text)
        with self.assertRaisesRegex(RequestValidationError, "captured build input"):
            record_source_snapshot(self.f.store, self.f.program, proposal["event_id"], other,
                [{"source_id": "PROJECT-BRIEF", "path": "brief.md"}], **self.f.kwargs("sources"))
        self.assertEqual(len(self.f.events()), 1)

    def test_reviewed_document_cannot_be_omitted_from_requirement_sources(self):
        request = deepcopy(self.f.request)
        request["document_review"]["documents"][0]["source_id"] = "UNDECLARED-BUILD-DOCUMENT"
        self.public.mutation("record-build-plan", request, expected=2)
        self.assertFalse(self.public.database.exists())

    def test_drift_between_scope_preparation_and_approval_stops_without_dispatch(self):
        self.public.prepare()
        self.change_document()
        self.public.approve(expected=2)
        self.assertEqual(self.public.cli("read-build")["authorizations"][0]["state"], "APPROVAL_REQUIRED")
        self.assertEqual(self.f.runner.invocations, [])

    def test_drift_after_approval_stops_but_history_remains_readable(self):
        self.f.prepare()
        self.change_document()
        self.assertEqual(self.f.advance()["status"], "BUILD_STOPPED")
        self.assertEqual(self.f.runner.invocations, [])
        view = read_build(self.f.store.database_path, self.f.program)
        self.assertEqual(view["document_review"]["status"], "HUMAN_DOCUMENT_CONFIRMATION_RECORDED")
        self.assertFalse(view["document_review"]["current_files_checked"])

    def test_historical_proposal_is_readable_not_automatically_reviewed(self):
        historical = self.f.store.append_batch(self.f.program, [{"event_type": "BUILD_PLAN_PROPOSED",
            "payload": {"requirement_ir": self.f.ir, "plan": self.f.plan}}],
            **self.f.kwargs("historical-fixture"))[0]
        view = read_build(self.f.store.database_path, self.f.program)
        self.assertEqual(view["document_review"]["status"], "BUILD_DOCUMENT_REVIEW_REQUIRED")
        with self.assertRaises(RequestValidationError):
            record_source_snapshot(self.f.store, self.f.program, historical["event_id"], self.f.source,
                [{"source_id": "PROJECT-BRIEF", "path": "brief.md"}], **self.f.kwargs("sources"))
        self.assertEqual(len(self.f.events()), 1)

    def test_valid_confirmation_retains_original_text_but_does_not_grant_runtime(self):
        (self.f.workspace / "src").rmdir()
        (self.f.workspace / "outputs").rmdir()
        self.f.workspace.rmdir()
        self.public.prepare()
        view = self.public.cli("read-build")
        self.assertEqual(view["document_review"]["decision"], self.f.review["decision"])
        self.assertFalse(view["document_review"]["runtime_authorized"])
        self.public.advance(expected=6)
        self.assertFalse(self.f.workspace.exists())
        self.assertEqual(self.f.runner.invocations, [])


class CompatibilityDocumentReviewTests(unittest.TestCase):
    def setUp(self):
        self.f = compatibility_support.PrebuildDelegationTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)

    def current_review(self):
        return self.f.store.get_program("PROGRAM-1").snapshot["build_document_review"]

    def change_document(self):
        Path(self.current_review()["documents"][0]["path"]).write_text("Changed test build document\n")

    def test_compatibility_cli_rejects_missing_review_before_service_creation(self):
        request = self.f._request("CREATE", number=1)
        request["payload"].pop("build_document_review")
        output = StringIO()
        with patch("sys.stdin", StringIO(json.dumps(request))), redirect_stdout(output), \
                patch("harness_foundry_factory.cli._service", side_effect=AssertionError("must not create controller")):
            self.assertEqual(main(["chat-turn", "--request", "-", "--json"]), 2)
        with self.assertRaises(ProgramNotFoundError):
            self.f.store.get_program("PROGRAM-1")

    def test_active_delegation_cannot_bypass_changed_document_or_supply_review(self):
        self.f.grant()
        self.change_document()
        before = self.f.store.get_program("PROGRAM-1").state_hash
        with self.assertRaises(RequestValidationError):
            self.f.service.advance_authoring_until_gate("PROGRAM-1")
        with self.assertRaises(RequestValidationError):
            self.f.send("REOPEN", {"reason": "test", "build_document_review": self.current_review()})
        self.assertEqual(self.f.store.get_program("PROGRAM-1").state_hash, before)

    def test_later_human_review_reopens_without_rewriting_old_snapshot_or_starting_target(self):
        self.f.grant()
        old = deepcopy(self.current_review())
        self.change_document()
        fresh = deepcopy(old)
        fresh["version"] = "test-v2"
        fresh["documents"][0]["text"] = Path(fresh["documents"][0]["path"]).read_text()
        fresh["decision"]["actor"]["turn_id"] = "TEST-LATER-HUMAN-CONFIRMATION"
        self.f.send("REOPEN", {"reason": "test new review", "build_document_review": fresh}, delegated=False)
        self.assertEqual(self.current_review(), fresh)
        self.assertEqual(self.f.store.list_events("PROGRAM-1")[0]["resulting_snapshot"]["build_document_review"], old)
        self.assertFalse((self.f.root / "target-output").exists())

    def test_stale_document_does_not_prevent_revoking_old_delegation(self):
        self.f.grant()
        self.change_document()
        result = self.f.send("REVOKE_PREBUILD_DELEGATION", {
            "delegation_id": "DELEGATION-1", "reason": "test stop"}, delegated=False)
        self.assertEqual(result["delegation"]["status"], "REVOKED")


if __name__ == "__main__":
    unittest.main()
