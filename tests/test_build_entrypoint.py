"""Public CLI and host decisions, all with temporary fixtures and no model calls."""

from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from harness_foundry_factory.build_entrypoint import apply_build_request
from harness_foundry_factory.cli import main
from harness_foundry_factory.models import RequestValidationError
import test_build_runtime as support


ROOT = Path(__file__).resolve().parents[1]


class BuildEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.fixture = support.BuildRuntimeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f = self.fixture
        self.f.scope["expires_at"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        # Public tests start with no controller, rather than inheriting setup DDL.
        self.database = self.f.root / "public-control.sqlite3"
        self.revision = 0
        self.key = 0

    def cli(self, command, request=None, *, expected=0):
        args = [command, "--control-db", str(self.database), "--json"]
        if request is None:
            args += ["--program-id", self.f.program]
        else:
            args += ["--request", "-"]
        output = StringIO()
        with patch("sys.stdin", StringIO(json.dumps(request))), redirect_stdout(output):
            code = main(args)
        result = json.loads(output.getvalue())
        self.assertEqual(code, expected, result)
        if "stream_revision" in result:
            self.revision = result["stream_revision"]
        return result

    def mutation(self, command, payload, *, expected=0):
        self.key += 1
        return self.cli(command, {**payload, "expected_revision": self.revision, "idempotency_key": f"REQUEST-{self.key}"}, expected=expected)

    def prepare(self):
        proposal = self.mutation("record-build-plan", self.f.request)
        source = self.mutation("capture-build-sources", {
            "program_id": self.f.program, "proposal_event_id": proposal["event_id"], "source_root": str(self.f.source),
            "manifest": [{"source_id": "PROJECT-BRIEF", "path": "brief.md"}],
        })
        self.prepared = self.mutation("prepare-build-authorization", {
            "program_id": self.f.program, "proposal_event_id": proposal["event_id"], "source_event_id": source["event_id"],
            "scope": self.f.scope,
        })
        return self.prepared

    @staticmethod
    def decision(action="APPROVE_BUILD", actor="HUMAN_VIA_CODEX_CHAT"):
        return {"action": action, "actor": {"type": actor, "chat_thread_id": "TEST-THREAD", "turn_id": "TEST-HUMAN-TURN"},
                "user_message": "TEST FIXTURE ONLY: approve the displayed scope, not a real user grant"}

    def approve(self, actor="HUMAN_VIA_CODEX_CHAT", expected=0):
        return self.mutation("approve-build-authorization", {"program_id": self.f.program,
            "prepared_event_id": self.prepared["event_id"], "decision": self.decision(actor=actor)}, expected=expected)

    def advance(self, expected=0, revision=None):
        return self.cli("advance-build", {"program_id": self.f.program,
            "prepared_event_id": self.prepared["event_id"], "expected_revision": self.revision if revision is None else revision}, expected=expected)

    def test_public_prepare_read_approve_do_not_dispatch_or_create_target(self):
        (self.f.workspace / "src").rmdir()
        (self.f.workspace / "outputs").rmdir()
        self.f.workspace.rmdir()
        with patch("subprocess.Popen", side_effect=AssertionError("no dispatch")):
            result = self.prepare()
            self.assertEqual(result["status"], "BUILD_SCOPE_APPROVAL_REQUIRED")
            normalized = {**self.f.scope, "source_read_roots": [str(Path(root).resolve())
                          for root in self.f.scope["source_read_roots"]]}
            self.assertEqual(result["readback"]["scope"], normalized)
            self.assertEqual(result["readback"]["requirement_ir"], self.f.ir)
            self.assertEqual(result["readback"]["source_binding"]["sources"][0]["line_count"], 3)
            self.assertEqual(result["readback"]["verification_files"], ["check.py"])
            self.assertEqual(self.advance(expected=6)["status"], "BUILD_STOPPED")
            approved = self.approve()
            self.assertEqual(approved["status"], "BUILD_APPROVED_EXECUTION_NOT_STARTED")
            view = self.cli("read-build")
            self.assertEqual(view["authorizations"][0]["state"], "APPROVED")
            self.assertFalse(view["writes_performed"])
        self.assertFalse(self.f.workspace.exists())

    def test_public_commands_run_real_local_fixture_verify_and_resume_without_replay(self):
        self.prepare()
        self.approve()
        with patch("harness_foundry_factory.build_runtime.NativeBuildRunner", return_value=self.f.runner):
            result = self.advance()
            self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED")
            self.assertFalse(result["harness_e2e_verified"])
            self.assertEqual(self.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(self.f.runner.invocations), 5)
        self.assertEqual(json.loads((self.f.workspace / "outputs/summary.json").read_text()), {"rows": 3, "invalid": 2})
        view = self.cli("read-build")
        self.assertEqual([row["status"] for row in view["attempts"]], ["ACCEPTED", "ACCEPTED"])

    def test_public_model_self_approval_and_legacy_actor_are_rejected(self):
        self.prepare()
        for actor in ("CODEX_DELEGATED_AGENT", "ASSISTANT", "HUMAN"):
            self.approve(actor=actor, expected=2)
        self.assertEqual(self.cli("read-build")["authorizations"][0]["state"], "APPROVAL_REQUIRED")

    def test_public_revocation_has_auditable_decision_and_blocks_execution(self):
        self.prepare()
        self.approve()
        self.mutation("revoke-build-authorization", {"program_id": self.f.program, "prepared_event_id": self.prepared["event_id"],
            "decision": self.decision("REVOKE_BUILD"), "reason": "TEST: user changed scope"})
        with patch("subprocess.Popen", side_effect=AssertionError("revoked")):
            self.assertEqual(self.advance(expected=6)["status"], "BUILD_STOPPED")
        self.assertEqual(self.cli("read-build")["authorizations"][0]["state"], "REVOKED")

    def test_effect_resolution_requires_human_decision_and_does_not_execute(self):
        self.prepare()
        self.approve()
        def unknown(invocation, before_dispatch):
            result = self.f.runner(invocation, before_dispatch)
            return {**result, "status": "UNKNOWN_SIDE_EFFECT", "reason_code": "TEST_LOST_PROTOCOL"}
        with patch("harness_foundry_factory.build_runtime.NativeBuildRunner", return_value=unknown):
            self.advance(expected=6)
        attempt = self.cli("read-build")["attempts"][0]
        request = {"program_id": self.f.program, "prepared_event_id": self.prepared["event_id"],
                   "attempt_id": attempt["attempt_id"], "reason": "TEST inspected finite effects; permit bounded retry",
                   "decision": self.decision("RESOLVE_BUILD_ATTEMPT", "ASSISTANT")}
        self.mutation("resolve-build-attempt", request, expected=2)
        request["decision"] = self.decision("RESOLVE_BUILD_ATTEMPT")
        result = self.mutation("resolve-build-attempt", request)
        self.assertFalse(result["execution_started"])
        self.assertFalse(result["target_write"])
        resolved = self.cli("read-build")["attempts"][0]
        self.assertEqual(resolved["status"], "RETRY_ALLOWED")
        self.assertEqual(resolved["original_status"], "UNKNOWN_SIDE_EFFECT")
        self.assertEqual(len(self.f.runner.invocations), 1)

    def test_stale_advance_and_unapproved_plan_never_dispatch(self):
        self.prepare()
        old = self.revision
        self.approve()
        with patch("subprocess.Popen", side_effect=AssertionError("stale request")):
            response = self.advance(expected=4, revision=old)
        self.assertEqual(response["error"]["code"], "STATE_REVISION_CONFLICT")

    def test_invalid_first_plan_read_and_mutation_do_not_create_database(self):
        self.cli("read-build", expected=2)
        self.assertFalse(self.database.exists())
        invalid = {**self.f.request, "unexpected_authority": True}
        self.mutation("record-build-plan", invalid, expected=2)
        self.assertFalse(self.database.exists())
        invalid_revision = deepcopy(self.f.request)
        invalid_revision["requirement_ir"]["revision"] = 2
        invalid_revision["plan"]["revision"] = 2
        invalid_revision["plan"]["requirement_revision"] = 2
        self.mutation("record-build-plan", invalid_revision, expected=2)
        self.assertFalse(self.database.exists())
        self.mutation("capture-build-sources", {"program_id": self.f.program, "proposal_event_id": "missing",
                      "source_root": str(self.f.source), "manifest": []}, expected=2)
        self.assertFalse(self.database.exists())

    def test_idempotent_record_replay_does_not_add_a_second_event(self):
        request = {**self.f.request, "expected_revision": 0, "idempotency_key": "stable-key"}
        first = self.cli("record-build-plan", request)
        second = self.cli("record-build-plan", request)
        self.assertEqual(first, second)
        self.assertEqual(self.cli("read-build")["stream_revision"], 1)

    def test_generic_cli_does_not_load_legacy_production_service(self):
        original_import = __import__

        def guarded(name, *args, **kwargs):
            if name in {"harness_foundry_factory.service", "harness_foundry_factory.compiler"}:
                raise AssertionError("generic route loaded legacy producer")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=guarded):
            self.prepare()
            self.cli("read-build")

    def test_historical_controller_cannot_be_reinterpreted_or_mutated(self):
        from harness_foundry_factory.store import ControlEventStore
        ControlEventStore(self.database)
        before = self.database.read_bytes()
        with self.assertRaises(RequestValidationError):
            apply_build_request("record-build-plan", {**self.f.request, "expected_revision": 0, "idempotency_key": "invalid"}, self.database)
        self.assertEqual(self.database.read_bytes(), before)

    def test_real_cli_process_roundtrip_from_outside_checkout(self):
        request = {**self.f.request, "expected_revision": 0, "idempotency_key": "subprocess"}
        result = subprocess.run([sys.executable, str(ROOT / "tools/hffactory.py"), "record-build-plan",
                                 "--request", "-", "--control-db", str(self.database), "--json"],
            cwd=self.f.root, input=json.dumps(request), text=True, capture_output=True, check=False,
            env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"})
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)["status"], "BUILD_PLAN_RECORDED_NOT_AUTHORIZED")
        view = self.cli("read-build")
        self.assertEqual(view["stream_revision"], 1)


if __name__ == "__main__":
    unittest.main()
