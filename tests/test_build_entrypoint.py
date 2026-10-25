"""Public CLI and host decisions, all with temporary fixtures and no model calls."""

from contextlib import redirect_stderr, redirect_stdout
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

from harness_foundry_factory.build_entrypoint import apply_build_request, read_build
from harness_foundry_factory.build_display import render_build_readback
from harness_foundry_factory.build_types import canonical_json
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
        budget = view["authorizations"][0]["budget"]
        self.assertEqual(budget["attempts_consumed"], 2)
        self.assertEqual(budget["attempts_remaining"], self.f.scope["max_attempts"] - 2)
        self.assertFalse(budget["reset"])
        revision = view["stream_revision"]
        for row in view["attempts"]:
            self.assertEqual(row["phase"], "VERIFICATION")
            self.assertEqual(row["recovery"]["minimum_return_path"], "NO_REPLAY")
            self.assertEqual(row["recovery"]["evidence_attempt_id"], row["attempt_id"])
        self.assertEqual(self.cli("read-build")["stream_revision"], revision)

    def test_one_attempt_returns_control_without_claiming_plan_completion(self):
        self.prepare()
        self.approve()
        request = {"program_id": self.f.program, "prepared_event_id": self.prepared["event_id"],
                   "expected_revision": self.revision, "advance_mode": "ONE_ATTEMPT"}
        with patch("harness_foundry_factory.build_runtime.NativeBuildRunner", return_value=self.f.runner):
            first = self.cli("advance-build", request)
        self.assertEqual(first["status"], "BUILD_CONTROL_RETURNED")
        self.assertTrue(first["control_returned"])
        self.assertEqual(first["attempt_status"], "ACCEPTED")
        self.assertFalse(first["harness_e2e_verified"])
        self.assertEqual(len(self.cli("read-build")["attempts"]), 1)
        with patch("harness_foundry_factory.build_runtime.NativeBuildRunner", return_value=self.f.runner):
            self.assertEqual(self.advance()["status"], "PLAN_CHECKS_ACCEPTED")

    def test_invalid_optional_advance_fields_fail_without_mutation(self):
        self.prepare()
        self.approve()
        request = {"program_id": self.f.program, "prepared_event_id": self.prepared["event_id"],
                   "expected_revision": self.revision}
        handoff = {"workpack_id": "BUILD-READER", "basis_attempt_ids": [], "summary": "fixture"}
        before = self.database.read_bytes()
        invalid = [
            {"advance_mode": "NEXT_TASK"}, {"advance_mode": []},
            {"codex_handoff": handoff}, {"advance_mode": "ONE_ATTEMPT", "codex_handoff": None},
            {"advance_mode": "ONE_ATTEMPT", "codex_handoff": {**handoff, "authority": "override"}},
            {"advance_mode": "ONE_ATTEMPT", "codex_handoff": {**handoff, "basis_attempt_ids": ["a", "a"]}},
            {"advance_mode": "ONE_ATTEMPT", "codex_handoff": {**handoff, "summary": " "}},
            {"advance_mode": "ONE_ATTEMPT", "max_attempts": 100},
        ]
        with patch("subprocess.Popen", side_effect=AssertionError("invalid request cannot dispatch")):
            for fields in invalid:
                with self.subTest(fields=fields):
                    result = self.cli("advance-build", {**request, **fields}, expected=2)
                    self.assertEqual(result["status"], "ERROR")
        self.assertEqual(before, self.database.read_bytes())

    def test_readback_keeps_implementation_message_after_verification(self):
        self.prepare()
        self.approve()
        def reported(invocation, before_dispatch):
            return {**self.f.runner(invocation, before_dispatch),
                    "final_message": "implementation report" if invocation["phase"] == "IMPLEMENTATION" else "verification"}
        with patch("harness_foundry_factory.build_runtime.NativeBuildRunner", return_value=reported):
            self.advance()
        before = self.database.read_bytes()
        with patch("harness_foundry_factory.build_runtime.BuildController.advance", side_effect=AssertionError("read only")), \
                patch("harness_foundry_factory.process_observation.CommandObservation.recover", side_effect=AssertionError("read only")):
            view = self.cli("read-build")
        for attempt in view["attempts"]:
            self.assertEqual(attempt["last_command"]["phase"], "VERIFICATION")
            self.assertEqual(attempt["implementation_observation_status"], "OBSERVED")
            self.assertEqual(attempt["missing_implementation_command_ids"], [])
            self.assertEqual(len(attempt["implementation_commands"]), 1)
            report = attempt["implementation_commands"][0]
            self.assertEqual(report["final_message"], "implementation report")
            self.assertEqual(report["phase"], "IMPLEMENTATION")
            self.assertEqual(report["executor"], "LOCAL")
            self.assertTrue(report["event_id"] and report["command_id"])
            self.assertTrue(Path(report["observation_root"]).is_absolute())
            self.assertTrue(attempt["verification"])
        self.assertEqual(before, self.database.read_bytes())

    def test_readback_missing_implementation_observation_does_not_infer_not_dispatched(self):
        self.prepare()
        self.approve()
        def interrupted(invocation, before_dispatch):
            raise support.InjectedControllerCrash()
        with patch("harness_foundry_factory.build_runtime.NativeBuildRunner", return_value=interrupted), \
                self.assertRaises(support.InjectedControllerCrash):
            self.advance()
        before = self.database.read_bytes()
        with patch("harness_foundry_factory.process_observation.CommandObservation.recover", side_effect=AssertionError("read only")):
            attempt = self.cli("read-build")["attempts"][0]
        self.assertEqual(attempt["status"], "IN_FLIGHT")
        self.assertEqual(attempt["implementation_observation_status"], "MISSING_OBSERVATION")
        self.assertEqual(attempt["implementation_commands"], [])
        self.assertEqual(attempt["missing_implementation_command_ids"], [attempt["last_command"]["command_id"]])
        self.assertEqual(before, self.database.read_bytes())

    def test_public_confirmed_repair_replays_then_rebuilds_through_original_tasks(self):
        producer = self.f.plan["workpacks"][0]
        producer["executor"] = "CODEX"
        producer.pop("local_argv")
        self.f.scope.update(allow_model_service=True, model="TEST-NOT-A-MODEL-CALL")
        self.prepare()
        self.approve()
        def synthetic_codex(invocation, before_dispatch):
            if invocation["executor"] == "CODEX":
                invocation = {**invocation, "executor": "LOCAL",
                              "argv": [sys.executable, "-I", "-B", "-c", self.f.write_reader(support.GOOD_READER)]}
            return self.f.runner(invocation, before_dispatch)
        with patch("harness_foundry_factory.build_runtime.NativeBuildRunner", return_value=synthetic_codex):
            self.advance()
        original = self.cli("read-build")
        attempt = original["attempts"][0]
        request = {"program_id": self.f.program, "prepared_event_id": self.prepared["event_id"],
                   "expected_revision": self.revision, "idempotency_key": "CONFIRMED-FIXTURE-DEFECT",
                   "targets": [{"artifact_id": producer["artifacts"][0]["artifact_id"],
                                "accepted_attempt_id": attempt["attempt_id"]}],
                   "finding": {"requirement_refs": ["PROJECT-BRIEF:L1"], "reason": "synthetic extra case",
                               "evidence_refs": ["fixture counterexample"], "repair_goal": "repair the bounded case"}}
        before_bytes = (self.f.workspace / "src/reader.py").read_bytes()
        before_calls = len(self.f.runner.invocations)
        with patch("subprocess.Popen", side_effect=AssertionError("repair request must not dispatch")):
            first = self.cli("request-build-repair", request)
            self.assertEqual(self.cli("request-build-repair", request), first)
        self.assertEqual(first["status"], "BUILD_REPAIR_REQUESTED")
        self.assertFalse(first["execution_started"] or first["target_write"] or first["budget_reset"])
        self.assertEqual(set(first["workpack_ids"]), {task["workpack_id"] for task in self.f.plan["workpacks"]})
        invalidated = self.cli("read-build")
        self.assertEqual(len(invalidated["attempts"]), len(original["attempts"]))
        self.assertTrue(all(row["status"] == "INVALIDATED" for row in invalidated["attempts"]))
        self.assertEqual(invalidated["repair_requests"][0]["finding"], request["finding"])
        self.assertEqual(invalidated["authorizations"][0]["budget"], original["authorizations"][0]["budget"])
        self.assertEqual(before_bytes, (self.f.workspace / "src/reader.py").read_bytes())
        self.assertEqual(before_calls, len(self.f.runner.invocations))
        human = render_build_readback(invalidated)
        self.assertIn("synthetic extra case", human)
        self.assertIn("登记不等于已修复", human)
        with patch("harness_foundry_factory.build_runtime.NativeBuildRunner", return_value=synthetic_codex):
            returned = self.cli("advance-build", {
                "program_id": self.f.program, "prepared_event_id": self.prepared["event_id"],
                "expected_revision": self.revision, "advance_mode": "ONE_ATTEMPT"})
            self.assertEqual(returned["workpack_id"], producer["workpack_id"])
            self.assertEqual(returned["status"], "BUILD_CONTROL_RETURNED")
            self.advance()
        rebuilt = self.cli("read-build")
        self.assertEqual(len(rebuilt["attempts"]), 4)
        self.assertEqual([row["status"] for row in rebuilt["attempts"]],
                         ["INVALIDATED", "INVALIDATED", "ACCEPTED", "ACCEPTED"])
        self.assertEqual(rebuilt["authorizations"][0]["budget"]["attempts_consumed"], 4)

    def test_repair_request_rejects_authority_override_before_mutation(self):
        self.prepare()
        self.approve()
        before = self.database.read_bytes()
        result = self.mutation("request-build-repair", {
            "program_id": self.f.program, "prepared_event_id": self.prepared["event_id"],
            "targets": [{"artifact_id": "READER", "accepted_attempt_id": "attempt"}],
            "finding": {"requirement_refs": ["R1"], "reason": "counterexample", "evidence_refs": ["fixture"],
                        "repair_goal": "fix case"}, "write_roots": ["/"]}, expected=2)
        self.assertEqual(result["status"], "ERROR")
        self.assertEqual(before, self.database.read_bytes())

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

    def read_output(self, *options):
        output = StringIO()
        with redirect_stdout(output):
            code = main(["read-build", "--control-db", str(self.database),
                         "--program-id", self.f.program, *options])
        return code, output.getvalue()

    def test_human_readback_is_readonly_and_json_formats_are_unchanged(self):
        self.prepare()
        before = self.database.read_bytes()
        original = read_build(self.database, self.f.program)
        with patch("subprocess.Popen", side_effect=AssertionError("readback must not dispatch")):
            code, canonical = self.read_output("--json")
            result = json.loads(canonical)
            self.assertEqual(code, 0)
            self.assertEqual(result, original)
            self.assertEqual(canonical, canonical_json(original) + "\n")
            self.assertEqual(self.read_output(), (0, json.dumps(original, ensure_ascii=False, indent=2) + "\n"))
            code, human = self.read_output("--human")
        self.assertEqual(code, 0)
        self.assertIn("尚无任务执行记录", human)
        self.assertIn("APPROVAL_REQUIRED", human)
        self.assertIn("本次未重新核对文档文件", human)
        self.assertIn("未验证", human)
        self.assertIn("不会自动推进任务", human)
        self.assertEqual(before, self.database.read_bytes())

    def test_human_missing_database_preserves_error_and_does_not_create_it(self):
        json_code, raw = self.read_output("--json")
        human_code, human = self.read_output("--human")
        self.assertNotEqual(json_code, 0)
        self.assertEqual(human_code, json_code)
        self.assertIn(json.loads(raw)["error"]["code"], human)
        self.assertEqual(json.loads(human[human.index("{"):]), json.loads(raw))
        self.assertNotIn("已读取建设记录", human)
        self.assertFalse(self.database.exists())

    def test_human_option_is_read_build_only_and_mutually_exclusive(self):
        for argv in (["read-build", "--control-db", str(self.database), "--program-id", self.f.program,
                      "--json", "--human"], ["version", "--human"],
                     ["advance-build", "--control-db", str(self.database), "--request", "-", "--human"]):
            with self.subTest(argv=argv), redirect_stdout(StringIO()) as stream, redirect_stderr(StringIO()) as err:
                self.assertEqual(main(argv), 2)
            result = json.loads(stream.getvalue())
            self.assertEqual(result["error"]["code"], "REQUEST_VALIDATION_ERROR")
            self.assertEqual(result["error"]["details"]["reason_code"], "CLI_ARGUMENT_ERROR")
            self.assertFalse(result["writes_performed"])
            self.assertFalse(result["execution_started"])
            self.assertEqual(err.getvalue(), "")
        self.assertFalse(self.database.exists())

    def test_human_render_keeps_history_recovery_and_failure_evidence(self):
        self.prepare()
        result = self.cli("read-build")
        grant = result["authorizations"][0]
        for index, state in enumerate(("APPROVED", "EXPIRED", "REVOKED")):
            historical = deepcopy(grant)
            historical.update(prepared_event_id=f"OLD-{index}", proposal_event_id="OLD-PLAN", state=state)
            result["authorizations"].append(historical)
        for status, action, phrase in (
                ("ACCEPTED", "NO_REPLAY", "不代表整个项目完成"),
                ("REJECTED", "REPAIR_WITHIN_BUDGET", "未通过检查"),
                ("BLOCKED", "ALIGN_PUBLIC_CONTRACT_AND_VERIFIER", "不自动重试"),
                ("UNKNOWN_SIDE_EFFECT", "RECONCILE_EFFECTS", "不能视为成功或未执行"),
                ("IN_FLIGHT", "RECONCILE_COMMAND_OBSERVATIONS", "不证明进程仍在运行"),
                ("INVALIDATED", "REBUILD_AFFECTED_BRANCH_WITHIN_BUDGET", "此前接受结果已失效"),
                ("RETRY_ALLOWED", "ADVANCE_WITH_CURRENT_SCOPE_AND_BUDGET", "尚未因此重新执行"),
                ("NOT_DISPATCHED", "ADVANCE_WITH_CURRENT_SCOPE_AND_BUDGET", "已用预算仍保留"),
                ("FUTURE_STATUS", "FUTURE_ACTION", "未识别状态")):
            with self.subTest(status=status):
                result["attempts"] = [{"attempt_id": "ATTEMPT-1", "workpack_id": "WORK-1", "status": status,
                    "prepared_event_id": "OLD-0", "phase": "VERIFICATION", "reason": "条件未满足，不可扩大权限",
                    "last_command": {"result": {"error_code": "EXAMPLE_ERROR", "stderr": "details"}},
                    "verification": [{"case_id": "CASE-1", "result": {"failure_kind": "CONTRACT_GAP"}}],
                    "recovery": {"next_action": action, "owner": "LOCAL_OPERATOR",
                                 "evidence_attempt_id": "ATTEMPT-1", "minimum_return_path": action}}]
                before = deepcopy(result)
                human = render_build_readback(result)
                self.assertEqual(result, before)
                for token in (status, action, phrase, "ATTEMPT-1", "WORK-1", "LOCAL_OPERATOR",
                              "历史计划", "APPROVAL_REQUIRED", "APPROVED", "EXPIRED", "REVOKED",
                              grant["scope"]["expires_at"], "不是新的授权或验收决定"):
                    self.assertIn(token, human)
                if status != "ACCEPTED":
                    for token in ("条件未满足，不可扩大权限", "EXAMPLE_ERROR", "CONTRACT_GAP", "CASE-1"):
                        self.assertIn(token, human)

    def test_real_accepted_attempts_render_without_replaying_or_claiming_e2e(self):
        self.prepare()
        self.approve()
        with patch("harness_foundry_factory.build_runtime.NativeBuildRunner", return_value=self.f.runner):
            self.advance()
        before = self.database.read_bytes()
        count = len(self.f.runner.invocations)
        with patch("subprocess.Popen", side_effect=AssertionError("readback must not dispatch")):
            code, human = self.read_output("--human")
        self.assertEqual(code, 0)
        self.assertIn("该次任务的声明检查已通过并记录", human)
        self.assertIn("不代表整个项目完成", human)
        self.assertIn("本返回未确认 Harness 端到端可用", human)
        self.assertEqual(len(self.f.runner.invocations), count)
        self.assertEqual(before, self.database.read_bytes())

    def test_human_unprepared_readback_reports_no_authority(self):
        self.mutation("record-build-plan", self.f.request)
        code, human = self.read_output("--human")
        self.assertEqual(code, 0)
        self.assertIn("尚无准备好的运行范围", human)
        self.assertIn("尚无任务执行记录", human)


if __name__ == "__main__":
    unittest.main()
