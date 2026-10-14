"""Generic control with real temporary local processes, never real Codex calls.

The fixture runner deliberately does NOT claim OS sandbox qualification. Native
receiver contracts have their own tests. Temporary approvals are test data, not
authority for a user Program, target installation or model service.
"""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from harness_foundry_factory.build_authoring import record_build_plan_proposal
from harness_foundry_factory.build_runtime import (
    BuildController, NativeBuildRunner, approve_build_authorization,
    prepare_build_authorization, record_source_snapshot, revoke_build_authorization,
    classify_verification_result,
    resolve_build_attempt,
    _COMMUNICATION_POLICY,
)
from harness_foundry_factory.local_process import CodexSandboxRunner
from harness_foundry_factory.models import RequestValidationError
from harness_foundry_factory.store import ControlEventStore
from test_build_plan import request_fixture
from tests.build_review_fixture import reviewed_document


NOW = "2026-09-18T00:00:00+00:00"
CLOCK = lambda: datetime.fromisoformat(NOW)
GOOD_READER = '''def inspect_rows(rows):
    if not isinstance(rows, list):
        raise ValueError("expected rows")
    return {"rows": len(rows), "invalid": sum(not row.isdigit() for row in rows)}
'''
BAD_READER = 'def inspect_rows(rows):\n    return {"rows": 0, "invalid": 0}\n'
VERIFIER = '''import importlib.util, json, sys
from pathlib import Path
case = sys.argv[1]
if case == "report":
    assert json.loads(Path("outputs/summary.json").read_text()) == {"rows": 3, "invalid": 2}
else:
    spec = importlib.util.spec_from_file_location("subject", Path("src/reader.py"))
    subject = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(subject)
    if case == "rows":
        assert subject.inspect_rows(["1", "bad", ""])["rows"] == 3
    else:
        try:
            subject.inspect_rows(None)
        except ValueError:
            pass
        else:
            raise AssertionError("malformed input accepted")
print("CHECKED", case)
'''


class FixtureProcessRunner:
    def __init__(self):
        self.invocations = []
        self.after_run = None
        self.before_run = None

    def __call__(self, invocation, before_dispatch):
        before_dispatch()
        if self.before_run:
            self.before_run(invocation)
        self.invocations.append(deepcopy(invocation))
        assert invocation["executor"] == "LOCAL", "test fixture cannot call a model"
        raw = CodexSandboxRunner("/usr/bin/true")._capture(
            invocation["argv"], Path(invocation["cwd"]), invocation["timeout_seconds"])
        result = {**raw, "status": "UNKNOWN_SIDE_EFFECT" if raw["timed_out"] else
                  "PASS" if raw["exit_code"] == 0 else "VALIDATION_FAILED",
                  "receiver": "TEST_ONLY_LOCAL_PROCESS_NOT_SANDBOX_QUALIFICATION"}
        if self.after_run:
            self.after_run(invocation, result)
        return result


class InjectedControllerCrash(BaseException):
    pass


class BuildRuntimeTests(unittest.TestCase):
    def test_verifier_crash_and_explicit_assertion_have_different_repair_routes(self):
        base = {"status": "VALIDATION_FAILED", "exit_code": 1, "stderr": "TEST traceback"}
        for output in ("", "not json", '{"status":"CHECKS_FAILED"}'):
            result = classify_verification_result({**base, "stdout": output})
            self.assertFalse(result["automatic_retry_allowed"])
            self.assertEqual(BuildController._failure_status(result), "BLOCKED")
        result = classify_verification_result({**base, "stdout": json.dumps({
            "status": "CHECKS_FAILED", "failure_kind": "ASSERTION", "reason": "wrong row count"})})
        self.assertTrue(result["automatic_retry_allowed"])
        self.assertEqual(BuildController._failure_status(result), "REJECTED")
        noisy = classify_verification_result({**base, "stdout": json.dumps({
            "status": "CHECKS_FAILED", "failure_kind": "ASSERTION"}), "output_truncated": True,
            "stdout_truncated": False, "stderr_truncated": True})
        self.assertTrue(noisy["automatic_retry_allowed"], "stderr preview clipping does not lose the verdict")
        clipped = classify_verification_result({**noisy, "stdout_truncated": True})
        self.assertFalse(clipped["automatic_retry_allowed"])

    def test_failure_category_is_not_reason_and_incomplete_tests_never_request_business_repair(self):
        verdicts = [{"status": "CHECKS_FAILED", "reason": "ASSERTION"}]
        for details in ({"errors": [{"exception_type": "PermissionError"}]},
                        {"discovery_errors": ["import failed"]}, {"skipped": ["not run"]},
                        {"expected_failures": ["known failure"]}, {"tests_run": 0},
                        {"tests_run": True}, {"tests_run": "2"}):
            verdicts.append({"status": "CHECKS_FAILED", "failure_kind": "ASSERTION", **details})
        for verdict in verdicts:
            with self.subTest(verdict=verdict):
                result = classify_verification_result({"status": "VALIDATION_FAILED", "exit_code": 1,
                                                       "stdout": json.dumps(verdict)})
                self.assertFalse(result["automatic_retry_allowed"])
                self.assertEqual(BuildController._failure_status(result), "BLOCKED")
                self.assertEqual(json.loads(result["stdout"]), verdict, "retain the original observation")
        # Ordinary independently executed checks do not acquire a new JSON requirement.
        passed = {"status": "PASS", "exit_code": 0, "stdout": "CHECKED"}
        self.assertEqual(classify_verification_result(passed), passed)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.workspace = self.root / "workspace"
        self.source = self.root / "requirements"
        self.verifier = self.root / "verifier"
        for path in (self.workspace / "src", self.workspace / "outputs", self.source, self.verifier):
            path.mkdir(parents=True)
        self.source_text = "Read every row and reject malformed input.\nReport invalid rows.\nGlobal constraint: offline only.\n"
        (self.source / "brief.md").write_text(self.source_text)
        (self.verifier / "check.py").write_text(VERIFIER)
        self.request = request_fixture()
        self.ir, self.plan = self.request["requirement_ir"], self.request["plan"]
        self.ir["sources"][0]["path_or_uri"] = "brief.md"
        for case in self.ir["acceptance_cases"] + self.ir["negative_cases"]:
            case["acceptance_contract"] = {"source_id": "PROJECT-BRIEF", "source_locator": "L1-L2"}
        self.review = reviewed_document(self.source, path=self.source / "brief.md")
        self.request["document_review"] = self.review
        for index, atom in enumerate(self.ir["atoms"]):
            atom["source_locator"] = f"L{index + 1}"
        first, second = self.plan["workpacks"]
        first["executor"] = "LOCAL"
        first["local_argv"] = ["python", "-I", "-B", "-c", self.write_reader(GOOD_READER)]
        second["local_argv"] = ["python", "-I", "-B", "-c",
            "import json, runpy; from pathlib import Path; "
            "reader = runpy.run_path('src/reader.py'); "
            "Path('outputs/summary.json').write_text(json.dumps(reader['inspect_rows'](['1', 'bad', ''])))"]
        for check, case in zip(first["verification"], ("rows", "malformed")):
            check["argv"] = ["python", "-I", "-B", "verifier://check.py", case]
        second["verification"][0]["argv"] = ["python", "-I", "-B", "verifier://check.py", "report"]
        self.store = ControlEventStore(self.root / "controller.sqlite3", storage_format="REVISION_V1")
        self.program = self.ir["program_id"]
        self.scope = {
            "workspace_root": str(self.workspace), "source_read_roots": [sys.prefix, sys.base_prefix],
            "verification_root": str(self.verifier),
            "task_write_roots": {first["workpack_id"]: ["src"], second["workpack_id"]: ["outputs"]},
            "executables": {"python": sys.executable}, "codex_executable": "/usr/bin/true",
            "model": None, "allow_model_service": False, "max_attempts": 5, "max_task_attempts": 3,
            "command_timeout_seconds": 5, "expires_at": "2026-09-18T01:00:00Z",
        }
        self.runner = FixtureProcessRunner()

    @staticmethod
    def write_reader(text):
        return "from pathlib import Path; Path('src/reader.py').write_text(" + repr(text) + ")"

    def events(self, kind=None):
        rows = self.store.list_events(self.program)
        return rows if kind is None else [row for row in rows if row["event_type"] == kind]

    def kwargs(self, key):
        return dict(expected_revision=len(self.events()), idempotency_key=key, created_at=NOW)

    def prepare(self, approve=True):
        proposal = record_build_plan_proposal(self.store, self.ir, self.plan,
                                              document_review=self.review, **self.kwargs("proposal"))
        self.proposal_id = proposal["event_id"]
        source = record_source_snapshot(self.store, self.program, self.proposal_id, self.source,
            [{"source_id": "PROJECT-BRIEF", "path": "brief.md"}], **self.kwargs("sources"))
        self.source_id = source["event_id"]
        prepared = prepare_build_authorization(self.store, self.program, self.proposal_id, self.source_id,
            self.scope, **self.kwargs("prepare"))
        self.prepared_id = prepared["event_id"]
        if approve:
            self.approve()
        return self.prepared_id

    def test_shared_tmp_verifier_cannot_be_prepared_as_readonly_on_macos(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as shared:
            verifier = Path(shared).resolve()
            (verifier / "check.py").write_text(VERIFIER)
            self.scope["verification_root"] = str(verifier)
            with patch("sys.platform", "darwin"), \
                    self.assertRaisesRegex(RequestValidationError, "SHARED_TEMP_ISOLATION_UNSUPPORTED"):
                self.prepare(approve=False)
        self.assertFalse(self.events("BUILD_AUTHORIZATION_PREPARED"))

    def test_shared_tmp_controller_cannot_be_prepared_on_macos(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as shared:
            self.store = ControlEventStore(Path(shared) / "control.sqlite3", storage_format="REVISION_V1")
            with patch("sys.platform", "darwin"), \
                    self.assertRaisesRegex(RequestValidationError, "SHARED_TEMP_ISOLATION_UNSUPPORTED"):
                self.prepare(approve=False)
            self.assertFalse(self.events("BUILD_AUTHORIZATION_PREPARED"))

    def approve(self):
        return approve_build_authorization(self.store, self.program, self.prepared_id,
            human_message_ref="TEST-FIXTURE-HUMAN-APPROVAL-NOT-A-REAL-GRANT", **self.kwargs("approval"))

    def controller(self, **kwargs):
        return BuildController(self.store, self.program, runner=self.runner, clock=CLOCK, **kwargs)

    def advance(self):
        return self.controller().advance(self.prepared_id)

    def test_two_local_tasks_real_outputs_checks_and_successor_progression(self):
        self.prepare()
        result = self.advance()
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        self.assertFalse(result["harness_e2e_verified"])
        self.assertEqual(json.loads((self.workspace / "outputs/summary.json").read_text()), {"rows": 3, "invalid": 2})
        rows = self.events()
        finished = self.events("BUILD_ATTEMPT_FINISHED")
        starts = self.events("BUILD_ATTEMPT_STARTED")
        self.assertLess(rows.index(finished[0]), rows.index(starts[1]))
        self.assertEqual([row["payload"]["status"] for row in finished], ["ACCEPTED", "ACCEPTED"])
        observations = self.events("BUILD_COMMAND_OBSERVED")
        self.assertEqual([(row["payload"]["job_id"], row["payload"]["case_id"]) for row in observations],
                         [("READER", None), ("READER", "READ-ROWS"), ("READER", "REJECT-MALFORMED"),
                          ("REPORT", None), ("REPORT", "REPORT-COUNT")])
        self.assertTrue(all(row["payload"]["result"]["exit_code"] == 0 for row in observations))
        for invocation in self.runner.invocations:
            if invocation["phase"] == "VERIFICATION":
                self.assertEqual(invocation["write_roots"], [])
            context = json.loads(invocation["prompt"].split("\n", 1)[1])
            self.assertEqual(context["task"]["tool_bindings"], self.scope["executables"])
            source = context["task"]["source_delivery"]["sources"][0]
            self.assertEqual(Path(source["absolute_path"]).read_text(), self.source_text)
            self.assertIn(source["absolute_path"], invocation["read_roots"])
            self.assertNotIn("text", source)
            self.assertFalse(context["task"]["source_delivery"]["semantic_review_complete"])
        self.assertNotIn("event_hash", json.dumps(rows))
        self.assertEqual(self.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(self.runner.invocations), 5, "accepted work must not be repeated")

    def test_producer_prompt_delivers_checker_protocol_without_new_scope(self):
        self.prepare()
        controller = self.controller()
        _, prepared, _ = controller._current(self.prepared_id)
        task = self.plan["workpacks"][0]
        invocation = controller._invocation(prepared, task, task["local_argv"])
        prompt = invocation["prompt"].split("\n", 1)[0]
        for required in ("failure_kind", "reason", "CHECKS_FAILED", "INFRASTRUCTURE", "CONTRACT_GAP",
                         "zero tests", "skipped", "inside the project", "outside the project",
                         "current case only"):
            self.assertIn(required, prompt)
        self.assertEqual(invocation["write_roots"], [str(self.workspace / "src")])
        self.assertEqual(invocation["scope"], prepared["scope"])
        for key in ("executables", "task_write_roots", "max_attempts", "max_task_attempts"):
            self.assertEqual(invocation["scope"][key], self.scope[key])
        self.assertEqual(self.runner.invocations, [], "prompt assembly must not execute")

    def test_communication_projection_changes_only_prompt_text_not_scope_or_json(self):
        self.prepare()
        controller = self.controller()
        _, prepared, plan = controller._current(self.prepared_id)
        task = plan["workpacks"][0]
        before = self.store.database_path.read_bytes()
        files = {str(path.relative_to(self.workspace)): path.read_bytes()
                 for path in self.workspace.rglob("*") if path.is_file()}
        feedback = {"reason": "原错误：必须保留范围，不能追加权限", "failure_kind": "ASSERTION"}
        for options in ({}, {"feedback": feedback}, {"case_id": "READ-ROWS"}):
            with self.subTest(options=options):
                # A text-only baseline proves that no authority/context fields
                # depend on the policy. No altered CLI or workload is executed.
                with patch("harness_foundry_factory.build_runtime._COMMUNICATION_POLICY", ""):
                    baseline = controller._invocation(prepared, task, task["local_argv"], **options)
                invocation = controller._invocation(prepared, task, task["local_argv"], **options)
                self.assertEqual(invocation["prompt"].count(_COMMUNICATION_POLICY), 1)
                self.assertEqual({**invocation, "prompt": invocation["prompt"].replace(_COMMUNICATION_POLICY, "", 1)},
                                 baseline)
                message, data = invocation["prompt"].split("\n", 1)
                payload = json.loads(data)
                self.assertEqual(set(payload), {"task", "feedback"})
                self.assertEqual(payload["feedback"], options.get("feedback"))
                self.assertEqual(payload["task"]["workpack"], task)
                for preserved in ("user's language", "evidence limits", "negations", "budgets",
                                  "Machine-output contracts take precedence", "foundry_blocker",
                                  "single JSON object without prose", "as declared artifacts",
                                  "self-contained instructions", "do not add files, tasks or permissions",
                                  "adds no approval gate", "Do not block a task solely for wording"):
                    self.assertIn(preserved, message)
                self.assertNotIn(str(Path(__file__).resolve().parents[1]), _COMMUNICATION_POLICY)
                self.assertEqual(invocation["write_roots"], [] if "case_id" in options else [str(self.workspace / "src")])
        self.assertEqual(before, self.store.database_path.read_bytes())
        self.assertEqual(files, {str(path.relative_to(self.workspace)): path.read_bytes()
                                 for path in self.workspace.rglob("*") if path.is_file()})
        self.assertEqual(self.runner.invocations, [])

    def test_codex_receiver_gets_inline_communication_without_extra_authority(self):
        task = self.plan["workpacks"][0]
        task["executor"] = "CODEX"
        task.pop("local_argv")
        self.scope.update(model="TEST-MODEL-NOT-CALLED", allow_model_service=True)
        self.prepare()
        controller = self.controller()
        _, prepared, plan = controller._current(self.prepared_id)
        invocation = controller._invocation(prepared, plan["workpacks"][0], [])
        before = self.store.database_path.read_bytes()
        # Intercept the native receiver boundary; never start a model/process.
        with patch("harness_foundry_factory.coding_process.CodexCodingRunner.run",
                   return_value={"status": "MODEL_TURN_COMPLETED", "exit_code": 0}) as receiver, \
                patch("subprocess.Popen", side_effect=AssertionError("no real model in regression")):
            NativeBuildRunner()(invocation, lambda: None)
        command = receiver.call_args.args[0]
        self.assertEqual(command.prompt, invocation["prompt"])
        self.assertIn(_COMMUNICATION_POLICY, command.prompt)
        self.assertEqual(command.model, self.scope["model"])
        self.assertEqual(invocation["scope"], prepared["scope"])
        self.assertEqual(invocation["argv"], [prepared["scope"]["codex_executable"]])
        for key in ("allow_model_service", "max_attempts", "max_task_attempts", "command_timeout_seconds"):
            self.assertEqual(invocation["scope"][key], self.scope[key])
        self.assertEqual(before, self.store.database_path.read_bytes())
        self.assertEqual(self.events("BUILD_ATTEMPT_STARTED"), [])
        self.assertFalse((self.workspace / "src/reader.py").exists())

    def test_downstream_gets_current_accepted_input_and_acceptance_event(self):
        self.prepare()
        self.assertEqual(self.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        invocation = next(row for row in self.runner.invocations if row["job_id"] == "REPORT")
        context = json.loads(invocation["prompt"].split("\n", 1)[1])["task"]
        packet = context["accepted_inputs"]
        self.assertEqual(len(packet), 1)
        self.assertEqual(packet[0]["artifact_id"], "READER-SOURCE")
        self.assertEqual(packet[0]["acceptance_event_id"], self.events("BUILD_ATTEMPT_FINISHED")[0]["event_id"])
        self.assertEqual(packet[0]["identity"]["sha256"], self.events("BUILD_ATTEMPT_FINISHED")[0]["payload"]["artifacts"]["READER-SOURCE"]["sha256"])
        self.assertEqual(context["requirement_context"]["target"], self.ir["target"])

    def test_effect_contract_keeps_protected_file_even_when_checkers_pass(self):
        self.plan["schema_version"] = "1.1"
        first = self.plan["workpacks"][0]
        first["effects"] = {"required": ["src/reader.py"], "allowed": ["src/reader.py"],
                            "must_preserve": ["src/existing.txt"]}
        (self.workspace / "src/existing.txt").write_text("user content")
        first["local_argv"][-1] += "; Path('src/existing.txt').unlink()"
        self.prepare()
        result = self.advance()
        self.assertNotEqual(result["status"], "PLAN_CHECKS_ACCEPTED")
        finished = self.events("BUILD_ATTEMPT_FINISHED")[-1]["payload"]
        self.assertEqual(finished["status"], "UNKNOWN_SIDE_EFFECT")
        self.assertEqual(finished["effects"]["violations"][0]["path"], "src/existing.txt")
        self.assertFalse((self.workspace / "src/existing.txt").exists(), "rejection must not claim rollback")
        count = len(self.runner.invocations)
        self.advance()
        self.assertEqual(len(self.runner.invocations), count)

    def test_environment_preflight_missing_module_never_dispatches_implementation(self):
        self.plan["schema_version"] = "1.1"
        self.plan["workpacks"][0]["environment"] = {"python": "python", "modules": ["foundry_missing_test_dependency"],
                                                   "paths": []}
        self.prepare()
        result = self.advance()
        self.assertNotEqual(result["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual([row["phase"] for row in self.runner.invocations], ["PREFLIGHT"])
        self.assertEqual(self.events("BUILD_ATTEMPT_FINISHED")[-1]["payload"]["status"], "BLOCKED")
        self.assertFalse((self.workspace / "src/reader.py").exists())
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 1, "no budget reset")

    def _quality_contract(self):
        self.plan["schema_version"] = "1.1"
        task = self.plan["workpacks"][0]
        task["effects"] = {"required": ["src/reader.py"], "allowed": ["src/reader.py"], "must_preserve": ["src/user.txt"]}
        task["environment"] = {"python": "python", "modules": ["json"], "paths": ["src/user.txt"]}
        (self.workspace / "src/user.txt").write_text("preserve")
        return task

    def test_quality_contract_normal_route_uses_readonly_preflight_and_host_effects(self):
        self._quality_contract()
        self.prepare()
        self.assertEqual(self.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        probe = self.runner.invocations[0]
        self.assertEqual(probe["phase"], "PREFLIGHT")
        self.assertEqual(probe["argv"][0], self.scope["executables"]["python"])
        self.assertEqual(probe["cwd"], str(self.workspace))
        self.assertEqual(probe["write_roots"], [])
        result = self.events("BUILD_ATTEMPT_FINISHED")[0]["payload"]
        self.assertEqual(result["effects"]["status"], "PASS")
        self.assertEqual(result["effects"]["changed_paths"], ["src/reader.py"])
        self.assertFalse(result["effects"]["external_effects_verified"])

    def test_unexpected_extra_file_inside_write_scope_is_not_effect_contract_pass(self):
        task = self._quality_contract()
        task["local_argv"][-1] += "; Path('src/unrequested.txt').write_text('extra')"
        self.prepare()
        self.assertEqual(self.advance()["status"], "HELD_UNRESOLVED_ATTEMPT")
        result = self.events("BUILD_ATTEMPT_FINISHED")[0]["payload"]
        self.assertEqual(result["effects"]["violations"], [{"path": "src/unrequested.txt", "reason": "UNDECLARED_FILE_EFFECT"}])
        self.assertFalse((self.workspace / "outputs/summary.json").exists())

    def test_effect_baseline_is_reused_after_controller_interruption(self):
        self._quality_contract()
        self.prepare()
        controller = self.controller()
        append = controller._append
        def crash_before_acceptance(kind, *args):
            if kind == "BUILD_ATTEMPT_FINISHED":
                raise InjectedControllerCrash()
            return append(kind, *args)
        with patch.object(controller, "_append", side_effect=crash_before_acceptance), self.assertRaises(InjectedControllerCrash):
            controller.advance(self.prepared_id)
        old_count = len(self.runner.invocations)
        result = self.advance()
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        self.assertEqual(len(self.runner.invocations) - old_count, 2, "only successor implementation/check may run")
        recovered = self.events("BUILD_ATTEMPT_FINISHED")[0]["payload"]
        self.assertTrue(recovered["recovered_from_observation"])
        self.assertEqual(recovered["effects"]["status"], "PASS")

    def test_recovery_cannot_accept_postcheck_preserved_file_drift(self):
        self._quality_contract()
        self.prepare()
        controller = self.controller()
        append = controller._append
        def crash_before_acceptance(kind, *args):
            if kind == "BUILD_ATTEMPT_FINISHED":
                raise InjectedControllerCrash()
            return append(kind, *args)
        with patch.object(controller, "_append", side_effect=crash_before_acceptance), self.assertRaises(InjectedControllerCrash):
            controller.advance(self.prepared_id)
        (self.workspace / "src/user.txt").write_text("external change")
        count = len(self.runner.invocations)
        self.assertEqual(self.advance()["status"], "HELD_UNRESOLVED_ATTEMPT")
        self.assertEqual(len(self.runner.invocations), count)
        self.assertEqual((self.workspace / "src/user.txt").read_text(), "external change")

    def test_pending_replan_cannot_remove_effect_or_environment_contract(self):
        from harness_foundry_factory.build_replan import adapt_build_plan
        self._quality_contract()
        for field in ("effects", "environment"):
            revised = deepcopy(self.plan)
            revised["workpacks"][0].pop(field)
            with self.assertRaisesRegex(RequestValidationError, "approved " + field):
                adapt_build_plan(self.plan, revised, self.scope)

    def test_effect_contract_outside_scope_fails_before_preparation(self):
        task = self._quality_contract()
        task["effects"]["allowed"].append("outputs/unapproved.json")
        with self.assertRaisesRegex(RequestValidationError, "expand approved"):
            self.prepare()
        self.assertFalse(self.events("BUILD_AUTHORIZATION_PREPARED"))

    def _upstream_repair_fixture(self, target="READER-SOURCE"):
        # Reader's stage checks are deliberately partial; the consumer finds
        # the real bad value and returns its declared input, not a guessed path.
        (self.verifier / "check.py").write_text('''import ast, json, sys
from pathlib import Path
if sys.argv[1] != "report":
    ast.parse(Path("src/reader.py").read_text())
elif json.loads(Path("outputs/summary.json").read_text()) != {"rows":3,"invalid":2}:
    print(json.dumps({"status":"CHECKS_FAILED","failure_kind":"ASSERTION",
        "reason":"reader produced the wrong count","repair_artifact_ids":TARGET}))
    raise SystemExit(1)
'''.replace("TARGET", repr([target])))
        self.plan["workpacks"][0]["local_argv"][-1] = (
            "from pathlib import Path; p=Path('src/reader.py'); "
            "p.write_text(" + repr(GOOD_READER) + " if p.exists() else " + repr(BAD_READER) + ")")
        original = self.runner.after_run
        def classify(invocation, result):
            if invocation["phase"] == "VERIFICATION":
                result.update(classify_verification_result(result))
            if original:
                original(invocation, result)
        self.runner.after_run = classify

    def test_independent_input_verdict_repairs_producer_without_editing_accepted_bytes(self):
        self._upstream_repair_fixture()
        self.prepare()
        self.assertEqual(self.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        attempts = self.events("BUILD_ATTEMPT_STARTED")
        self.assertEqual([row["payload"]["workpack_id"] for row in attempts],
                         ["IMPLEMENT-READER", "MAKE-REPORT", "IMPLEMENT-READER", "MAKE-REPORT"])
        invalidation = self.events("BUILD_ACCEPTANCE_INVALIDATED")[0]["payload"]
        self.assertEqual(invalidation["reason"], "INDEPENDENT_ARTIFACT_REPAIR_REQUIRED")
        self.assertFalse(invalidation["budget_reset"])
        self.assertEqual(invalidation["workpack_ids"], ["IMPLEMENT-READER", "MAKE-REPORT"])
        repair = [item for item in self.runner.invocations if item["phase"] == "IMPLEMENTATION"][2]
        self.assertIn("reader produced the wrong count", repair["prompt"])
        self.assertEqual(repair["write_roots"], [str(self.workspace / "src")])
        self.assertEqual(self.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 4)
        self.assertEqual(len(self.events("BUILD_AUTHORIZATION_APPROVED")), 1)

    def test_input_repair_cannot_name_undeclared_artifact(self):
        self._upstream_repair_fixture("UNKNOWN-INPUT")
        self.prepare()
        self.assertEqual(self.advance()["status"], "HELD_REPAIR_SCOPE")
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 2)
        self.assertFalse(self.events("BUILD_ACCEPTANCE_INVALIDATED"))

    def test_upstream_repair_keeps_consumer_budget_and_stops_without_useless_dispatch(self):
        self._upstream_repair_fixture()
        self.scope["max_task_attempts"] = 1
        self.prepare()
        self.assertEqual(self.advance()["status"], "TASK_REPAIR_BUDGET_EXHAUSTED")
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 2)
        self.assertFalse(self.events("BUILD_ACCEPTANCE_INVALIDATED"))

    def test_restart_after_repair_route_does_not_duplicate_invalidation_or_reset_budget(self):
        self._upstream_repair_fixture()
        self.prepare()
        controller = self.controller()
        append = controller._append
        def crash(kind, *args):
            result = append(kind, *args)
            if kind == "BUILD_ACCEPTANCE_INVALIDATED":
                raise InjectedControllerCrash()
            return result
        with patch.object(controller, "_append", side_effect=crash), self.assertRaises(InjectedControllerCrash):
            controller.advance(self.prepared_id)
        self.assertEqual(self.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(self.events("BUILD_ACCEPTANCE_INVALIDATED")), 1)
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 4)

    def test_malformed_repair_target_is_not_ordinary_retry(self):
        for targets in ([], "READER-SOURCE", [1], ["A", "A"]):
            result = classify_verification_result({"status":"VALIDATION_FAILED", "exit_code":1,
                "stdout":json.dumps({"status":"CHECKS_FAILED", "failure_kind":"ASSERTION",
                                    "repair_artifact_ids":targets})})
            self.assertFalse(result["automatic_retry_allowed"])

    def test_repair_route_does_not_bypass_revocation_or_total_budget(self):
        self._upstream_repair_fixture()
        self.scope["max_attempts"] = 3
        self.prepare()
        self.assertEqual(self.advance()["status"], "ATTEMPT_BUDGET_EXHAUSTED")
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 2)
        revoke_build_authorization(self.store, self.program, self.prepared_id, **self.kwargs("revoke"))
        result = self.advance()
        self.assertEqual(result["status"], "BUILD_STOPPED")
        self.assertIn("revoked", result["reason"])
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 2)

    def test_native_model_shaped_observation_recovers_without_reimplementation(self):
        from devtools.release_acceptance.recovery_probe import after_observation_runner
        first = self.plan["workpacks"][0]
        first["executor"] = "CODEX"
        first.pop("local_argv")
        self.scope.update(model="test-only-no-model-call", allow_model_service=True)
        self.prepare()
        calls = []
        def model_fixture(command, **kwargs):
            kwargs["before_dispatch"]()
            calls.append(command)
            (self.workspace / "src/reader.py").write_text(GOOD_READER)
            return {"status":"MODEL_TURN_COMPLETED", "exit_code":0}
        def terminate(code):
            self.assertEqual(code,86)
            raise InjectedControllerCrash()
        runner = after_observation_runner(NativeBuildRunner(), "IMPLEMENT-READER", terminate=terminate)
        with patch("harness_foundry_factory.coding_process.CodexCodingRunner.run", side_effect=model_fixture), \
                self.assertRaises(InjectedControllerCrash):
            BuildController(self.store,self.program,runner=runner,clock=CLOCK).advance(self.prepared_id)
        self.assertEqual(len(calls),1)
        self.assertEqual(self.events("BUILD_COMMAND_OBSERVED"),[])
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")),1)
        self.assertFalse((self.workspace / "outputs/summary.json").exists())
        # Real CommandObservation/BuildController recovery, synthetic model output.
        result = self.advance()
        self.assertEqual(result["status"],"PLAN_CHECKS_ACCEPTED",result)
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")),2)
        self.assertTrue(all(row["executor"] == "LOCAL" for row in self.runner.invocations))
        self.assertEqual(len(self.events("BUILD_COMMAND_PLANNED")),5)

    def test_model_contract_blocker_precedes_missing_outputs_and_stays_stopped_on_resume(self):
        from harness_foundry_factory.coding_events import observe_coding_process
        from harness_foundry_factory.build_entrypoint import read_build
        from test_coding_protocol import blocker_capture, CONTRACT_BLOCKER
        self.prepare()
        invocations = []
        def runner(invocation, before_dispatch):
            before_dispatch()
            invocations.append(invocation)
            return observe_coding_process(blocker_capture(), exit_code=0)
        controller = self.controller()
        controller.runner = runner
        result = controller.advance(self.prepared_id)
        self.assertEqual(result["status"], "HELD_ACCEPTANCE_CONTRACT", result)
        self.assertEqual(len(invocations), 1)
        self.assertFalse((self.workspace / "src/reader.py").exists())
        self.assertEqual(result["diagnostics"][0]["result"]["model_blocker"], CONTRACT_BLOCKER)
        self.assertNotIn("DECLARED_OUTPUT_MISSING", json.dumps(result))
        context = json.loads(invocations[0]["prompt"].split("\n", 1)[1])["task"]
        self.assertEqual(context["downstream_obligations"][0]["workpack_id"], "MAKE-REPORT")
        self.assertEqual(invocations[0]["write_roots"], [str(self.workspace / "src")])
        before = self.events()
        self.assertEqual(controller.advance(self.prepared_id)["status"], "HELD_ACCEPTANCE_CONTRACT")
        self.assertEqual(self.events(), before)
        self.assertEqual(len(invocations), 1)
        readback = read_build(self.root / "controller.sqlite3", self.program)
        self.assertEqual(readback["attempts"][0]["recovery"]["next_action"], "ALIGN_PUBLIC_CONTRACT_AND_VERIFIER")

    def test_durable_model_blocker_recovers_without_redispatch_or_missing_output_retry(self):
        from harness_foundry_factory.coding_events import observe_coding_process
        from test_coding_protocol import blocker_capture
        first = self.plan["workpacks"][0]
        first["executor"] = "CODEX"
        first.pop("local_argv")
        self.scope.update(model="test-only-no-model-call", allow_model_service=True)
        self.prepare()
        def model_fixture(command, **kwargs):
            kwargs["before_dispatch"]()
            return observe_coding_process(blocker_capture(), exit_code=0)
        def runner(invocation, before_dispatch):
            NativeBuildRunner()(invocation, before_dispatch)
            raise InjectedControllerCrash()
        with patch("harness_foundry_factory.coding_process.CodexCodingRunner.run", side_effect=model_fixture) as model, \
                self.assertRaises(InjectedControllerCrash):
            BuildController(self.store, self.program, runner=runner, clock=CLOCK).advance(self.prepared_id)
        self.assertEqual(model.call_count, 1)
        self.assertEqual(self.events("BUILD_COMMAND_OBSERVED"), [])
        self.assertEqual(self.advance()["status"], "HELD_ACCEPTANCE_CONTRACT")
        self.assertEqual(self.runner.invocations, [])
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 1)
        self.assertEqual(len(self.events("BUILD_COMMAND_PLANNED")), 1)

    def test_nested_executable_binding_uses_exact_approved_alias_without_new_reads(self):
        alias = self.root / "bound python"
        alias.symlink_to(sys.executable)
        self.scope["executables"]["python"] = str(alias)
        for task in self.plan["workpacks"]:
            task["local_argv"] += ["executable://python"]
            for check in task["verification"]:
                check["argv"] += ["--python-executable", "executable://python"]
        self.prepare()
        self.assertEqual(self.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        for invocation in self.runner.invocations:
            self.assertEqual(invocation["argv"][0], str(alias))
            self.assertEqual(invocation["argv"][-1], str(alias))
            self.assertNotIn(str(alias.parent), invocation["read_roots"])
            if invocation["phase"] == "VERIFICATION":
                self.assertEqual(invocation["write_roots"], [])

    def assert_unknown_nested_executable_rejected(self, argv):
        argv.append("executable://not-declared")
        with self.assertRaisesRegex(RequestValidationError, "executable"):
            self.prepare(approve=False)
        self.assertEqual(self.events("BUILD_AUTHORIZATION_PREPARED"), [])
        self.assertEqual(self.runner.invocations, [])

    def test_unknown_nested_executable_fails_during_local_scope_preparation(self):
        self.assert_unknown_nested_executable_rejected(self.plan["workpacks"][0]["local_argv"])

    def test_unknown_nested_executable_fails_during_verifier_scope_preparation(self):
        self.assert_unknown_nested_executable_rejected(self.plan["workpacks"][0]["verification"][0]["argv"])

    def test_replanned_nested_executable_cannot_escape_binding(self):
        self.prepare()
        self.plan["revision"] += 1
        self.plan["workpacks"][0]["local_argv"].append("executable://not-declared")
        record_build_plan_proposal(self.store, self.ir, self.plan,
                                  document_review=self.review, **self.kwargs("bad-replan"))
        result = self.advance()
        self.assertEqual(result["status"], "BUILD_STOPPED")
        self.assertIn("executable", result["reason"])
        self.assertEqual(self.events("BUILD_ATTEMPT_STARTED"), [])
        self.assertEqual(self.runner.invocations, [])

    def test_actual_failed_checks_repair_then_accept_before_next_task(self):
        self.plan["workpacks"][0]["local_argv"][-1] = (
            "from pathlib import Path; marker=Path('src/attempts'); "
            "n=int(marker.read_text())+1 if marker.exists() else 1; marker.write_text(str(n)); "
            f"Path('src/reader.py').write_text({GOOD_READER!r} if n>1 else {BAD_READER!r})")
        self.prepare()
        result = self.advance()
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        finishes = [row["payload"] for row in self.events("BUILD_ATTEMPT_FINISHED")]
        self.assertEqual([row["status"] for row in finishes], ["REJECTED", "ACCEPTED", "ACCEPTED"])
        self.assertNotEqual(finishes[0]["verification"][0]["result"]["exit_code"], 0)
        self.assertIn("AssertionError", finishes[0]["verification"][0]["result"]["stderr"])
        repaired = self.runner.invocations[3]
        self.assertIn("VALIDATION_FAILED", repaired["prompt"])
        self.assertIn(finishes[0]["attempt_id"], repaired["prompt"])
        self.assertIn(self.events("BUILD_COMMAND_PLANNED")[0]["event_id"], repaired["prompt"])
        self.assertIn("declared_method", repaired["prompt"])
        self.assertIn(_COMMUNICATION_POLICY, self.runner.invocations[0]["prompt"])
        self.assertIn(_COMMUNICATION_POLICY, repaired["prompt"])
        self.assertEqual(len(self.events("BUILD_AUTHORIZATION_APPROVED")), 1)

    def test_model_turn_completion_is_not_independent_acceptance(self):
        self.plan["workpacks"][0].pop("local_argv")
        self.plan["workpacks"][0]["executor"] = "CODEX"
        self.scope.update(model="TEST-MODEL-NOT-CALLED", allow_model_service=True, max_task_attempts=1)
        self.prepare()
        local_runner = self.runner

        def synthetic_model(invocation, before_dispatch):
            if invocation["executor"] == "CODEX":
                before_dispatch()
                (self.workspace / "src/reader.py").write_text(BAD_READER)
                return {"status": "MODEL_TURN_COMPLETED", "receiver": "TEST_ONLY_PROTOCOL_FIXTURE"}
            return local_runner(invocation, before_dispatch)

        result = BuildController(self.store, self.program, runner=synthetic_model, clock=CLOCK).advance(self.prepared_id)
        self.assertEqual(result["status"], "TASK_REPAIR_BUDGET_EXHAUSTED")
        self.assertEqual(self.events("BUILD_ATTEMPT_FINISHED")[0]["payload"]["status"], "REJECTED")
        self.assertFalse((self.workspace / "outputs/summary.json").exists())

    def test_model_startup_failure_is_held_once_and_restart_does_not_redispatch(self):
        self.plan["workpacks"][0].pop("local_argv")
        self.plan["workpacks"][0]["executor"] = "CODEX"
        self.scope.update(model="TEST-MODEL-NOT-CALLED", allow_model_service=True)
        self.prepare()
        calls = []

        def failed_start(invocation, before_dispatch):
            before_dispatch()
            calls.append(invocation)
            return {"status": "MODEL_PROCESS_FAILED", "reason_code": "CODEX_PROCESS_OR_TURN_FAILED",
                    "automatic_retry_allowed": False, "event_count": 0, "thread_id": None,
                    "capture": {"exit_code": 1, "stdout": "", "stderr":
                        "Failed to initialize session: failed to load AGENTS.md instructions "
                        "for environment `local`: Operation not permitted (os error 1)"}}

        for _ in range(2):
            result = BuildController(self.store, self.program, runner=failed_start, clock=CLOCK).advance(self.prepared_id)
            self.assertEqual(result["status"], "HELD_COMMAND_FAILURE", result)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 1)
        self.assertEqual(self.events("BUILD_ATTEMPT_FINISHED")[0]["payload"]["status"], "BLOCKED")
        self.assertFalse((self.workspace / "outputs/summary.json").exists())

    def test_verifier_environment_failure_does_not_trigger_implementation_repair(self):
        self.prepare()
        runner = self.runner
        calls = []

        def unavailable(invocation, before_dispatch):
            calls.append(invocation)
            if invocation["phase"] == "VERIFICATION":
                return {"status": "VALIDATION_FAILED", "reason_code": "SANDBOX_UNAVAILABLE",
                        "workload_started": False}
            return runner(invocation, before_dispatch)

        for _ in range(2):
            result = BuildController(self.store, self.program, runner=unavailable, clock=CLOCK).advance(self.prepared_id)
            self.assertEqual(result["status"], "HELD_COMMAND_FAILURE", result)
        self.assertEqual(len(calls), 2, "no second verifier or repair after infrastructure failure")
        self.assertTrue((self.workspace / "src/reader.py").exists())

    def test_model_turn_status_cannot_substitute_for_local_verifier_success(self):
        self.prepare()
        runner = self.runner
        calls = []

        def wrong_protocol(invocation, before_dispatch):
            calls.append(invocation)
            if invocation["phase"] == "VERIFICATION":
                return {"status": "MODEL_TURN_COMPLETED", "automatic_retry_allowed": False}
            return runner(invocation, before_dispatch)

        for _ in range(2):
            result = BuildController(self.store, self.program, runner=wrong_protocol, clock=CLOCK).advance(self.prepared_id)
            self.assertEqual(result["status"], "HELD_UNRESOLVED_ATTEMPT")
        self.assertEqual(len(calls), 2)

    def test_instruction_requirements_are_visible_during_scope_preparation(self):
        self.plan["workpacks"][0].pop("local_argv")
        self.plan["workpacks"][0]["executor"] = "CODEX"
        self.scope.update(model="TEST-MODEL-NOT-CALLED", allow_model_service=True)
        (self.root / ".git").mkdir()
        ancestor = self.root / "AGENTS.md"
        ancestor.write_text("test repository guidance")
        self.prepare(approve=False)
        preflight = self.events("BUILD_AUTHORIZATION_PREPARED")[-1]["payload"]["coding_instruction_preflight"]
        self.assertIn(str(ancestor), preflight["missing_read_paths"])
        self.assertFalse(preflight["permissions_added"])
        self.assertFalse(preflight["session_readiness_verified"])
        self.assertEqual(self.events("BUILD_ATTEMPT_STARTED"), [])

    def test_historical_rejected_process_failure_is_not_retried_or_rewritten(self):
        self.prepare()
        binding = {"prepared_event_id": self.prepared_id, "attempt_id": "TEST-HISTORICAL-ATTEMPT",
                   "proposal_event_id": self.proposal_id, "workpack_id": self.plan["workpacks"][0]["workpack_id"],
                   "job_id": self.plan["workpacks"][0]["job_id"]}
        self.store.append_batch(self.program, [
            {"event_type": "BUILD_ATTEMPT_STARTED", "payload": binding},
            {"event_type": "BUILD_ATTEMPT_FINISHED", "payload": {**binding, "status": "REJECTED", "artifacts": {},
             "verification": [{"phase": "IMPLEMENTATION", "result": {"status": "MODEL_PROCESS_FAILED",
                                "automatic_retry_allowed": False}}]}},
        ], **self.kwargs("historical-failure"))
        before = self.events()
        self.assertEqual(self.advance()["status"], "HELD_COMMAND_FAILURE")
        self.assertEqual(self.events(), before)
        self.assertEqual(self.runner.invocations, [])

        # Simulate work already completed by the pre-fix controller after its
        # mistaken retry. Use a real fixture implementation/check, not a forged
        # acceptance. Upgrading must not revive the superseded failure.
        controller = self.controller()
        events, prepared, plan = controller._current(self.prepared_id)
        controller._attempt(self.prepared_id, plan["workpacks"][0], prepared, events, None)
        self.assertEqual(self.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(self.runner.invocations), 5)
        self.assertEqual(self.events("BUILD_ATTEMPT_FINISHED")[0]["payload"]["status"], "REJECTED")

    def test_scope_can_bind_an_exact_read_file_without_its_parent_directory(self):
        dependency = self.source / "AGENTS.md"
        dependency.write_text("instructions")
        self.scope["source_read_roots"].append(str(dependency))
        self.prepare()
        controller = self.controller()
        _, prepared, plan = controller._current(self.prepared_id)
        invocation = controller._invocation(prepared, plan["workpacks"][0], plan["workpacks"][0]["local_argv"])
        self.assertIn(str(dependency), invocation["read_roots"])
        self.assertNotIn(str(dependency.parent), invocation["read_roots"])

    def test_prepared_scope_and_proposal_without_approval_never_dispatch(self):
        self.prepare(approve=False)
        self.assertEqual(self.advance()["status"], "BUILD_STOPPED")
        self.assertEqual(self.runner.invocations, [])
        self.assertEqual(self.events("BUILD_ATTEMPT_STARTED"), [])

    def test_declared_source_or_verifier_change_stops_before_dispatch(self):
        self.prepare()
        for path in (self.source / "brief.md", self.verifier / "check.py"):
            with self.subTest(path=path):
                original = path.read_text()
                path.write_text(original + "\nCHANGED")
                self.assertEqual(self.advance()["status"], "BUILD_STOPPED")
                path.write_text(original)
        self.assertEqual(self.runner.invocations, [])

    def test_revocation_and_expiration_stop_without_workload(self):
        self.prepare()
        future = lambda: datetime(2026, 9, 19, tzinfo=timezone.utc)
        expired = BuildController(self.store, self.program, runner=self.runner, clock=future).advance(self.prepared_id)
        self.assertEqual(expired["status"], "BUILD_STOPPED")
        revoke_build_authorization(self.store, self.program, self.prepared_id, **self.kwargs("revoke"))
        self.assertEqual(self.advance()["status"], "BUILD_STOPPED")
        self.assertEqual(self.runner.invocations, [])

    def test_in_scope_implementation_replan_needs_no_new_human_approval(self):
        self.plan["workpacks"][0]["local_argv"][-1] = self.write_reader(BAD_READER)
        self.prepare()
        self.plan["revision"] = 2
        self.plan["workpacks"][0]["local_argv"][-1] = self.write_reader(GOOD_READER)
        self.plan["workpacks"][0]["goal"] = "Implement a simpler design with identical acceptance."
        revised = record_build_plan_proposal(self.store, self.ir, self.plan, document_review=self.review, **self.kwargs("replan"))
        result = self.advance()
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        self.assertEqual(len(self.events("BUILD_AUTHORIZATION_APPROVED")), 1)
        self.assertTrue(all(row["payload"]["proposal_event_id"] == revised["event_id"]
                            for row in self.events("BUILD_ATTEMPT_STARTED")))

    def test_requirement_or_verifier_command_replan_cannot_reuse_approval(self):
        self.prepare()
        self.plan["revision"] = 2
        self.plan["workpacks"][0]["verification"][0]["argv"][-1] = "weaker-check"
        record_build_plan_proposal(self.store, self.ir, self.plan, document_review=self.review, **self.kwargs("replan"))
        self.assertEqual(self.advance()["status"], "BUILD_STOPPED")
        self.assertEqual(self.runner.invocations, [])

    def test_rejected_output_missing_is_repairable_but_never_accepted(self):
        self.plan["workpacks"][0]["local_argv"][-1] = "pass"
        self.scope["max_task_attempts"] = 2
        self.prepare()
        self.assertEqual(self.advance()["status"], "TASK_REPAIR_BUDGET_EXHAUSTED")
        finishes = self.events("BUILD_ATTEMPT_FINISHED")
        self.assertEqual(len(finishes), 2)
        self.assertTrue(all(row["payload"]["status"] == "REJECTED" for row in finishes))
        self.assertFalse((self.workspace / "outputs/summary.json").exists())

    def test_observation_survives_revocation_during_completed_process(self):
        self.prepare()

        def revoke(invocation, result):
            revoke_build_authorization(self.store, self.program, self.prepared_id, **self.kwargs("revoke"))

        self.runner.after_run = revoke
        self.assertEqual(self.advance()["status"], "BUILD_STOPPED")
        self.assertEqual(len(self.runner.invocations), 1)
        self.assertEqual(self.events("BUILD_COMMAND_OBSERVED")[0]["payload"]["result"]["exit_code"], 0)
        self.assertEqual(self.events("BUILD_ATTEMPT_FINISHED")[0]["payload"]["status"], "UNKNOWN_SIDE_EFFECT")

    def test_timeout_retains_partial_output_and_restart_never_replays(self):
        self.plan["workpacks"][0]["local_argv"][-1] = (
            "from pathlib import Path; import time; Path('src/partial').write_text('started'); time.sleep(5)")
        self.scope["command_timeout_seconds"] = 1
        self.prepare()
        self.assertEqual(self.advance()["status"], "HELD_UNRESOLVED_ATTEMPT")
        self.assertEqual((self.workspace / "src/partial").read_text(), "started")
        self.assertEqual(self.advance()["status"], "HELD_UNRESOLVED_ATTEMPT")
        self.assertEqual(len(self.runner.invocations), 1)

    def test_crash_after_complete_checks_recovers_acceptance_without_reexecution(self):
        self.prepare()
        controller = self.controller()
        append = controller._append

        def crash(kind, *args):
            if kind == "BUILD_ATTEMPT_FINISHED":
                raise InjectedControllerCrash()
            return append(kind, *args)

        with patch.object(controller, "_append", side_effect=crash), self.assertRaises(InjectedControllerCrash):
            controller.advance(self.prepared_id)
        self.assertEqual(len(self.runner.invocations), 3)
        self.assertEqual(self.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(self.runner.invocations), 5)
        self.assertTrue(self.events("BUILD_ATTEMPT_FINISHED")[0]["payload"]["recovered_from_observation"])

    def test_reserved_attempt_without_command_intent_recovers_without_new_approval(self):
        self.prepare()
        controller = self.controller()
        with patch.object(controller, "_execute_command", side_effect=InjectedControllerCrash()), \
                self.assertRaises(InjectedControllerCrash):
            controller.advance(self.prepared_id)
        self.assertFalse(self.events("BUILD_COMMAND_PLANNED"))
        self.assertFalse(self.runner.invocations)
        self.assertEqual(self.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 3, "reserved attempt still counts")
        self.assertEqual(len(self.runner.invocations), 5)
        recovered = self.events("BUILD_ATTEMPT_FINISHED")[0]["payload"]
        self.assertEqual(recovered["status"], "NOT_DISPATCHED")
        self.assertEqual(recovered["reason"], "NO_COMMAND_INTENT_COMMITTED")
        self.assertEqual(len(self.events("BUILD_AUTHORIZATION_APPROVED")), 1)

    def test_unstarted_recovery_neither_refunds_budget_nor_bypasses_revocation(self):
        self.scope["max_attempts"] = 1
        self.prepare()
        controller = self.controller()
        with patch.object(controller, "_execute_command", side_effect=InjectedControllerCrash()), \
                self.assertRaises(InjectedControllerCrash):
            controller.advance(self.prepared_id)
        revoke_build_authorization(self.store, self.program, self.prepared_id, **self.kwargs("revoke"))
        self.assertEqual(self.advance()["status"], "BUILD_STOPPED")
        self.assertFalse(self.events("BUILD_ATTEMPT_FINISHED"))
        self.assertFalse(self.runner.invocations)

    def test_unstarted_recovery_respects_original_total_budget(self):
        self.scope["max_attempts"] = 1
        self.prepare()
        controller = self.controller()
        with patch.object(controller, "_execute_command", side_effect=InjectedControllerCrash()), \
                self.assertRaises(InjectedControllerCrash):
            controller.advance(self.prepared_id)
        self.assertEqual(self.advance()["status"], "ATTEMPT_BUDGET_EXHAUSTED")
        self.assertFalse(self.runner.invocations)
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 1)

    def test_delayed_original_dispatcher_cannot_overwrite_reconciled_attempt(self):
        self.prepare()
        original = self.controller()
        append = original._append
        resumed = []

        def interleave(kind, *args):
            event = append(kind, *args)
            if kind == "BUILD_ATTEMPT_STARTED":
                resumed.append(self.advance())
            return event

        with patch.object(original, "_append", side_effect=interleave):
            result = original.advance(self.prepared_id)
        self.assertEqual(resumed[0]["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(self.runner.invocations), 5, "late dispatcher must never dispatch")
        states = [row["payload"]["status"] for row in self.events("BUILD_ATTEMPT_FINISHED")]
        self.assertEqual(states, ["NOT_DISPATCHED", "ACCEPTED", "ACCEPTED"])

    def test_recovered_missing_output_is_rejected_then_repaired_like_normal_execution(self):
        self.plan["workpacks"][0]["local_argv"] = ["python", "-c", "pass"]
        self.prepare()
        controller = self.controller()
        append = controller._append

        def crash(kind, *args):
            if kind == "BUILD_ATTEMPT_FINISHED":
                raise InjectedControllerCrash()
            return append(kind, *args)

        with patch.object(controller, "_append", side_effect=crash), self.assertRaises(InjectedControllerCrash):
            controller.advance(self.prepared_id)
        # An in-scope implementation change preserves the existing acceptance contract.
        self.plan["revision"] = 2
        self.plan["workpacks"][0]["local_argv"] = ["python", "-c", self.write_reader(GOOD_READER)]
        # First reconcile the original observation; a changed proposal must not
        # supply a different task while recovering a prior attempt.
        events, prepared, plan = controller._current(self.prepared_id)
        attempts, _ = controller._state(events, self.prepared_id)
        self.assertTrue(controller._recover_completed_observations(self.prepared_id, prepared, plan,
                                                                  events, list(attempts.values())))
        self.assertEqual(self.events("BUILD_ATTEMPT_FINISHED")[0]["payload"]["status"], "REJECTED")
        record_build_plan_proposal(self.store, self.ir, self.plan, document_review=self.review,
                                   **self.kwargs("repair-plan"))
        self.assertEqual(self.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(self.runner.invocations), 6)

    def test_recovery_rechecks_expiry_before_acceptance_commit(self):
        self.prepare()
        controller = self.controller()
        append = controller._append

        def crash(kind, *args):
            if kind == "BUILD_ATTEMPT_FINISHED":
                raise InjectedControllerCrash()
            return append(kind, *args)

        with patch.object(controller, "_append", side_effect=crash), self.assertRaises(InjectedControllerCrash):
            controller.advance(self.prepared_id)
        clock = [CLOCK()]
        resumed = BuildController(self.store, self.program, runner=self.runner, clock=lambda: clock[0])
        artifacts = resumed._artifacts

        def expire(*args):
            value = artifacts(*args)
            clock[0] = datetime.fromisoformat(self.scope["expires_at"].replace("Z", "+00:00"))
            return value

        with patch.object(resumed, "_artifacts", side_effect=expire):
            self.assertEqual(resumed.advance(self.prepared_id)["status"], "BUILD_STOPPED")
        self.assertFalse(self.events("BUILD_ATTEMPT_FINISHED"))
        self.assertEqual(len(self.runner.invocations), 3)

    def test_crash_after_dispatch_without_observation_is_held_not_replayed(self):
        self.prepare()
        self.runner.after_run = lambda *args: (_ for _ in ()).throw(InjectedControllerCrash())
        with self.assertRaises(InjectedControllerCrash):
            self.advance()
        self.assertTrue((self.workspace / "src/reader.py").exists())
        self.runner.after_run = None
        self.assertEqual(self.advance()["status"], "HELD_UNRESOLVED_ATTEMPT")
        self.assertEqual(len(self.runner.invocations), 1)

    def test_crash_after_one_case_resumes_only_remaining_checks(self):
        self.prepare()
        controller = self.controller()
        append = controller._append

        def crash(kind, payload, *args):
            event = append(kind, payload, *args)
            if kind == "BUILD_COMMAND_OBSERVED" and payload["case_id"] == "READ-ROWS":
                raise InjectedControllerCrash()
            return event

        with patch.object(controller, "_append", side_effect=crash), self.assertRaises(InjectedControllerCrash):
            controller.advance(self.prepared_id)
        self.assertEqual(len(self.runner.invocations), 2)
        result = self.advance()
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        self.assertEqual(len(self.runner.invocations), 5, "do not repeat implementation or a completed Case")

    def test_unknown_result_keeps_raw_cause_in_public_readback(self):
        from harness_foundry_factory.build_entrypoint import read_build
        self.prepare()
        def unknown(invocation, before_dispatch):
            before_dispatch()
            return {"status": "UNKNOWN_SIDE_EFFECT", "reason_code": "TEST_CAPTURE_LOSS"}
        controller = BuildController(self.store, self.program, runner=unknown, clock=CLOCK)
        self.assertEqual(controller.advance(self.prepared_id)["status"], "HELD_UNRESOLVED_ATTEMPT")
        row = read_build(str(self.store.database_path), self.program)["attempts"][-1]
        self.assertEqual(row["last_command"]["result"]["reason_code"], "TEST_CAPTURE_LOSS")
        self.assertEqual(row["recovery"]["next_action"], "RECONCILE_EFFECTS")

    def test_new_scope_cannot_evade_unknown_attempt_on_same_workspace(self):
        self.prepare()
        def unknown(invocation, before_dispatch):
            return {"status": "UNKNOWN_SIDE_EFFECT", "exit_code": 0}
        BuildController(self.store, self.program, runner=unknown, clock=CLOCK).advance(self.prepared_id)
        second = prepare_build_authorization(self.store, self.program, self.proposal_id, self.source_id,
            self.scope, **self.kwargs("new-scope"))
        approve_build_authorization(self.store, self.program, second["event_id"], human_message_ref="TEST-ONLY",
                                    **self.kwargs("new-scope-approval"))
        result = self.controller().advance(second["event_id"])
        self.assertEqual(result["status"], "HELD_UNRESOLVED_PRIOR_SCOPE", result)
        self.assertEqual(self.runner.invocations, [])

    def test_explicit_reconciliation_keeps_history_and_does_not_reset_budget(self):
        self.scope["max_task_attempts"] = 1
        self.prepare()
        def unknown(invocation, before_dispatch):
            return {"status": "UNKNOWN_SIDE_EFFECT", "exit_code": 0}
        BuildController(self.store, self.program, runner=unknown, clock=CLOCK).advance(self.prepared_id)
        original = self.events("BUILD_ATTEMPT_FINISHED")[0]
        arguments = dict(reason="TEST effects inspected; user permits a new attempt", human_message_ref="TEST-ONLY",
                         **self.kwargs("resolution"))
        event = resolve_build_attempt(self.store, self.program, self.prepared_id,
                                       original["payload"]["attempt_id"], **arguments)
        self.assertEqual(resolve_build_attempt(self.store, self.program, self.prepared_id,
                                              original["payload"]["attempt_id"], **arguments), event)
        self.assertEqual(self.events("BUILD_ATTEMPT_FINISHED")[0], original)
        self.assertFalse(event["payload"]["old_output_accepted"])
        self.assertEqual(self.advance()["status"], "TASK_REPAIR_BUDGET_EXHAUSTED")
        self.assertEqual(self.runner.invocations, [])

    def test_native_receiver_attachment_recovers_before_controller_observation(self):
        # TEST ONLY sandbox-shaped local receiver. It deliberately provides no
        # OS isolation and cannot call Codex/model services.
        executable = self.root / "test-only-sandbox"
        executable.write_text("#!" + sys.executable + "\n" + '''import subprocess, sys
args = sys.argv[1:]
if args == ["sandbox", "--help"]:
    print("--permission-profile --include-managed-config --cd [COMMAND]")
else:
    assert args[0] == "sandbox"
    sys.exit(subprocess.call(args[args.index("--") + 1:]))
''')
        executable.chmod(0o700)
        self.scope["codex_executable"] = str(executable)
        self.prepare()
        native = NativeBuildRunner()

        def crash_after_native(invocation, before_dispatch):
            native(invocation, before_dispatch)
            raise InjectedControllerCrash()

        controller = BuildController(self.store, self.program, runner=crash_after_native, clock=CLOCK)
        with self.assertRaises(InjectedControllerCrash):
            controller.advance(self.prepared_id)
        self.assertEqual(self.events("BUILD_COMMAND_OBSERVED"), [])
        self.assertEqual(len(self.events("BUILD_COMMAND_STARTED")), 1)
        result = BuildController(self.store, self.program, runner=native, clock=CLOCK).advance(self.prepared_id)
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        commands = self.events("BUILD_COMMAND_PLANNED")
        self.assertEqual(len(commands), 5, "durable implementation must not be executed twice")
        self.assertTrue(all(not Path(row["payload"]["observation_root"]).is_relative_to(self.workspace)
                            for row in commands))

    def _check_live_authority_stop(self, *, revoke):
        # Exercise the real NativeBuildRunner and collector through a local
        # sandbox-shaped fixture. This is not OS isolation or model evidence.
        executable = self.root / "test-only-sandbox"
        executable.write_text("#!" + sys.executable + "\n" + '''import subprocess, sys
args = sys.argv[1:]
if args == ["sandbox", "--help"]:
    print("--permission-profile --include-managed-config --cd [COMMAND]")
else:
    assert args[0] == "sandbox"
    sys.exit(subprocess.call(args[args.index("--") + 1:]))
''')
        executable.chmod(0o700)
        self.scope["codex_executable"] = str(executable)
        self.plan["workpacks"][0]["local_argv"] = ["python", "-B", "-c",
            "import time; from pathlib import Path; Path('src/partial').write_text('retained'); time.sleep(10)"]
        self.prepare()
        clock = [CLOCK()]
        native = NativeBuildRunner()
        changed = []

        def runner(invocation, before_dispatch):
            def monitor():
                if (self.workspace / "src/partial").exists() and not changed:
                    changed.append(True)
                    if revoke:
                        revoke_build_authorization(self.store, self.program, self.prepared_id, **self.kwargs("revoke"))
                    else:
                        clock[0] = datetime.fromisoformat(self.scope["expires_at"].replace("Z", "+00:00"))
                return invocation["cancellation_reason"]()
            return native({**invocation, "cancellation_reason": monitor}, before_dispatch)

        controller = BuildController(self.store, self.program, runner=runner, clock=lambda: clock[0])
        result = controller.advance(self.prepared_id)
        self.assertEqual(result["status"], "BUILD_STOPPED", result)
        observed = self.events("BUILD_COMMAND_OBSERVED")
        self.assertEqual(len(observed), 1)
        capture = observed[0]["payload"]["result"]
        self.assertEqual(capture["status"], "UNKNOWN_SIDE_EFFECT")
        self.assertEqual(capture["cancellation_reason"], "BUILD_AUTHORIZATION_REVOKED" if revoke
                         else "BUILD_AUTHORIZATION_EXPIRED")
        self.assertFalse(capture["timed_out"])
        self.assertEqual((self.workspace / "src/partial").read_text(), "retained")
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 1)
        self.assertEqual(self.events("BUILD_ATTEMPT_FINISHED")[0]["payload"]["status"], "UNKNOWN_SIDE_EFFECT")
        self.assertFalse(controller._state(self.events(), self.prepared_id)[1])
        self.assertEqual(controller.advance(self.prepared_id)["status"], "BUILD_STOPPED")
        self.assertEqual(len(self.events("BUILD_COMMAND_PLANNED")), 1, "no verification, successor or replay")

    def test_revoke_stops_running_native_command_and_preserves_history(self):
        self._check_live_authority_stop(revoke=True)

    def test_expiry_stops_running_native_command_and_preserves_history(self):
        self._check_live_authority_stop(revoke=False)

    def test_accepted_artifact_byte_drift_stops_later_reuse(self):
        self.scope["max_task_attempts"] = 1
        self.prepare()
        self.assertEqual(self.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        (self.workspace / "src/reader.py").write_text(BAD_READER)
        self.assertEqual(self.advance()["status"], "TASK_REPAIR_BUDGET_EXHAUSTED")
        self.assertEqual(len(self.runner.invocations), 5)
        self.assertEqual(self.controller()._state(self.events(), self.prepared_id)[1], {})

    def test_observed_startup_failure_survives_controller_crash_as_blocked(self):
        self.prepare()
        def failed(invocation, before_dispatch):
            before_dispatch()
            return {"status": "VALIDATION_FAILED", "workload_started": False,
                    "reason": "TEST_RECEIVER_UNAVAILABLE"}
        controller = BuildController(self.store, self.program, runner=failed, clock=CLOCK)
        append = controller._append
        def crash(kind, *args):
            if kind == "BUILD_ATTEMPT_FINISHED":
                raise InjectedControllerCrash()
            return append(kind, *args)
        with patch.object(controller, "_append", side_effect=crash), self.assertRaises(InjectedControllerCrash):
            controller.advance(self.prepared_id)
        result = self.advance()
        self.assertEqual(result["status"], "HELD_COMMAND_FAILURE", result)
        self.assertEqual(self.runner.invocations, [])
        self.assertEqual(self.events("BUILD_ATTEMPT_FINISHED")[-1]["payload"]["status"], "BLOCKED")

    def test_observed_verifier_infrastructure_failure_recovers_without_replay(self):
        self.prepare()
        fixture = self.runner
        def failed_check(invocation, before_dispatch):
            if invocation["phase"] == "VERIFICATION":
                before_dispatch()
                return {"status": "VALIDATION_FAILED", "automatic_retry_allowed": False,
                        "exit_code": 1, "reason": "TEST_VERIFIER_CRASH"}
            return fixture(invocation, before_dispatch)
        controller = BuildController(self.store, self.program, runner=failed_check, clock=CLOCK)
        append = controller._append
        def crash(kind, *args):
            if kind == "BUILD_ATTEMPT_FINISHED":
                raise InjectedControllerCrash()
            return append(kind, *args)
        with patch.object(controller, "_append", side_effect=crash), self.assertRaises(InjectedControllerCrash):
            controller.advance(self.prepared_id)
        result = self.advance()
        self.assertEqual(result["status"], "HELD_COMMAND_FAILURE", result)
        self.assertEqual(len(self.runner.invocations), 1)

    def test_in_place_replacement_can_repair_without_reusing_old_version(self):
        task = deepcopy(self.plan["workpacks"][0])
        task.update(workpack_id="READER-V2", job_id="MAINTENANCE", depends_on=["MAKE-REPORT"],
                    inputs=[{"kind": "ARTIFACT", "id": "READER-SOURCE"}],
                    artifacts=[{"artifact_id": "READER-V2", "path": "src/reader.py", "replaces_artifact_id": "READER-SOURCE"}])
        task["local_argv"][-1] = (
            "from pathlib import Path; marker=Path('src/revision-attempts'); "
            "n=int(marker.read_text())+1 if marker.exists() else 1; marker.write_text(str(n)); "
            f"Path('src/reader.py').write_text({GOOD_READER!r} if n>1 else {BAD_READER!r})")
        for check in task["verification"]:
            check["artifact_ids"] = ["READER-V2"]
        self.plan["workpacks"].append(task)
        self.scope["task_write_roots"]["READER-V2"] = ["src"]
        self.prepare()
        result = self.advance()
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        self.assertEqual([row["payload"]["status"] for row in self.events("BUILD_ATTEMPT_FINISHED")],
                         ["ACCEPTED", "ACCEPTED", "REJECTED", "ACCEPTED"])

    def test_scope_cannot_place_independent_verifier_or_controller_in_task_workspace(self):
        self.scope["verification_root"] = str(self.workspace / "src")
        with self.assertRaisesRegex(RequestValidationError, "verifier"):
            self.prepare()

    def test_approval_cannot_add_model_permission_missing_from_prepared_scope(self):
        self.plan["workpacks"][0].pop("local_argv")
        self.plan["workpacks"][0]["executor"] = "CODEX"
        with self.assertRaisesRegex(RequestValidationError, "model"):
            self.prepare()

    def test_native_adapter_calls_existing_receivers_without_fallback(self):
        self.prepare()
        controller = self.controller()
        _, prepared, plan = controller._current(self.prepared_id)
        invocation = controller._invocation(prepared, plan["workpacks"][0], plan["workpacks"][0]["local_argv"])
        callback = lambda: None
        with patch("harness_foundry_factory.build_runtime.CodexSandboxRunner") as receiver:
            receiver.return_value.run.return_value = {"status": "VALIDATION_FAILED", "workload_started": False}
            result = NativeBuildRunner()(invocation, callback)
        self.assertEqual(result["status"], "VALIDATION_FAILED")
        self.assertIs(receiver.return_value.run.call_args.kwargs["before_dispatch"], callback)

    def test_bound_executable_alias_cannot_be_task_writable(self):
        alias = self.workspace / "src/python"
        alias.symlink_to(sys.executable)
        self.scope["executables"]["python"] = str(alias)
        with self.assertRaisesRegex(RequestValidationError, "task-writable"):
            self.prepare()

    def test_workspace_creation_does_not_create_undeclared_parents(self):
        self.scope["workspace_root"] = str(self.workspace / "missing-parent" / "target")
        with self.assertRaisesRegex(RequestValidationError, "parent must already exist"):
            self.prepare()
        self.assertFalse((self.workspace / "missing-parent").exists())

    def test_bound_receiver_cannot_be_task_writable(self):
        receiver = self.workspace / "src/codex"
        receiver.write_text("not an independently owned receiver")
        self.scope["codex_executable"] = str(receiver)
        with self.assertRaisesRegex(RequestValidationError, "task-writable"):
            self.prepare()

    def test_implementation_cannot_replace_verifier_interpreter_with_exit_zero_wrapper(self):
        wrapper = self.workspace / "src/verification-python"
        wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        wrapper.chmod(0o755)
        self.scope["executables"]["verification-python"] = str(wrapper)
        for task in self.plan["workpacks"]:
            for check in task["verification"]:
                check["argv"][0] = "verification-python"
        self.plan["workpacks"][0]["local_argv"][-1] = (
            self.write_reader(BAD_READER) + "; "
            "Path('src/verification-python').write_text('#!/bin/sh\\nexit 0\\n')")
        with self.assertRaisesRegex(RequestValidationError, "task-writable"):
            self.prepare()
        self.assertEqual(self.events("BUILD_AUTHORIZATION_APPROVED"), [])
        self.assertEqual(self.runner.invocations, [])

    def test_source_root_parent_does_not_hide_writable_requirement_file(self):
        self.source = self.workspace / "src"
        (self.source / "brief.md").write_text(self.source_text)
        self.review = reviewed_document(self.source, path=self.source / "brief.md")
        with self.assertRaisesRegex(RequestValidationError, "source.*task-writable"):
            self.prepare()

    def test_write_root_retargeting_does_not_expand_approved_scope(self):
        self.prepare()
        (self.workspace / "src").rmdir()
        (self.workspace / "src").symlink_to(self.workspace / "outputs", target_is_directory=True)
        self.assertEqual(self.advance()["status"], "BUILD_STOPPED")
        self.assertEqual(self.runner.invocations, [])

    def test_total_budget_stops_without_reset_on_new_controller(self):
        self.scope["max_attempts"] = 1
        self.prepare()
        self.assertEqual(self.advance()["status"], "ATTEMPT_BUDGET_EXHAUSTED")
        self.assertEqual(self.advance()["status"], "ATTEMPT_BUDGET_EXHAUSTED")
        self.assertEqual(len(self.runner.invocations), 3)

    def test_changed_accepted_output_rebuilds_only_affected_dependency_branch(self):
        independent = deepcopy(self.plan["workpacks"][0])
        independent.update(workpack_id="INDEPENDENT", job_id="OTHER", depends_on=[],
                           artifacts=[{"artifact_id": "OTHER-SOURCE", "path": "other/reader.py"}])
        independent["local_argv"][-1] = self.write_reader(GOOD_READER).replace("src/reader.py", "other/reader.py")
        (self.verifier / "other.py").write_text(VERIFIER.replace("src/reader.py", "other/reader.py"))
        for check in independent["verification"]:
            check["argv"][-2] = "verifier://other.py"
            check["artifact_ids"] = ["OTHER-SOURCE"]
        self.plan["workpacks"].append(independent)
        self.scope["task_write_roots"]["INDEPENDENT"] = ["other"]
        self.prepare()
        self.assertEqual(self.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        (self.workspace / "src/reader.py").write_text(BAD_READER)
        (self.workspace / "src/unrelated-user-note").write_text("keep me")
        before = len(self.runner.invocations)
        result = self.advance()
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        self.assertEqual([row["workpack_id"] for row in self.runner.invocations[before:]],
                         ["IMPLEMENT-READER"] * 3 + ["MAKE-REPORT"] * 2)
        self.assertEqual((self.workspace / "src/unrelated-user-note").read_text(), "keep me")
        self.assertEqual(len(self.events("BUILD_AUTHORIZATION_APPROVED")), 1)
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 5)
        invalidated = self.events("BUILD_ACCEPTANCE_INVALIDATED")
        self.assertEqual(invalidated[0]["payload"]["workpack_ids"], ["IMPLEMENT-READER", "MAKE-REPORT"])

    def test_missing_accepted_output_invalidates_dependents_without_resetting_budget(self):
        self.scope["max_attempts"] = 2
        self.prepare()
        self.assertEqual(self.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        (self.workspace / "src/reader.py").unlink()
        result = self.advance()
        self.assertEqual(result["status"], "ATTEMPT_BUDGET_EXHAUSTED", result)
        self.assertEqual(result["accepted_workpacks"], [])
        self.assertEqual(len(self.runner.invocations), 5)
        self.assertEqual(len(self.events("BUILD_ACCEPTANCE_INVALIDATED")), 1)
        self.assertEqual(self.advance()["status"], "ATTEMPT_BUDGET_EXHAUSTED")

    def test_new_source_capture_cannot_attach_to_another_proposal(self):
        self.prepare(approve=False)
        self.plan["revision"] = 2
        new = record_build_plan_proposal(self.store, self.ir, self.plan, document_review=self.review, **self.kwargs("replan"))
        with self.assertRaisesRegex(RequestValidationError, "another proposal"):
            prepare_build_authorization(self.store, self.program, new["event_id"], self.source_id,
                                        self.scope, **self.kwargs("second-prepare"))

    def test_changed_outputs_prevent_recovery_of_previously_observed_checks(self):
        self.prepare()
        controller = self.controller()
        append = controller._append

        def crash(kind, *args):
            if kind == "BUILD_ATTEMPT_FINISHED":
                raise InjectedControllerCrash()
            return append(kind, *args)

        with patch.object(controller, "_append", side_effect=crash), self.assertRaises(InjectedControllerCrash):
            controller.advance(self.prepared_id)
        (self.workspace / "src/reader.py").write_text(BAD_READER)
        self.assertEqual(self.advance()["status"], "BUILD_STOPPED")
        self.assertEqual(len(self.runner.invocations), 3)

    def test_verifier_changed_during_implementation_cannot_be_used(self):
        self.prepare()
        self.runner.after_run = lambda *args: (self.verifier / "check.py").write_text("pass\n")
        result = self.advance()
        self.assertEqual(result["status"], "BUILD_STOPPED", result)
        self.assertEqual(len(self.runner.invocations), 1)
        self.assertEqual(self.events("BUILD_ATTEMPT_FINISHED")[0]["payload"]["status"], "UNKNOWN_SIDE_EFFECT")

    def test_absent_workspace_is_not_created_by_prepare_or_approval(self):
        (self.workspace / "src").rmdir()
        (self.workspace / "outputs").rmdir()
        self.workspace.rmdir()
        self.prepare(approve=False)
        self.assertFalse(self.workspace.exists())
        self.assertEqual(self.advance()["status"], "BUILD_STOPPED")
        self.assertFalse(self.workspace.exists())
        self.approve()
        self.assertFalse(self.workspace.exists())
        self.assertEqual(self.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertTrue((self.workspace / "outputs/summary.json").exists())
        self.assertEqual(len(self.events("BUILD_WORKSPACE_PREPARED")), 1)

    def test_large_source_is_available_in_full_without_prompt_inlining(self):
        full_text = self.source_text + ("Additional source detail.\n" * 100000)
        (self.source / "brief.md").write_text(full_text)
        self.review = reviewed_document(self.source, path=self.source / "brief.md")
        self.prepare()
        controller = self.controller()
        _, prepared, plan = controller._current(self.prepared_id)
        invocation = controller._invocation(prepared, plan["workpacks"][0], plan["workpacks"][0]["local_argv"])
        self.assertLess(len(invocation["prompt"]), 20000)
        source = json.loads(invocation["prompt"].split("\n", 1)[1])["task"]["source_delivery"]["sources"][0]
        self.assertEqual(Path(source["absolute_path"]).read_text(), full_text)
        self.assertEqual(self.events("BUILD_SOURCES_CAPTURED")[0]["payload"]["snapshot"]["sources"][0]["text"], full_text)


    def test_one_attempt_returns_each_settlement_and_finishes_plan_on_next_call(self):
        self.prepare()
        controller = self.controller()
        for count, workpack in enumerate(("IMPLEMENT-READER", "MAKE-REPORT"), 1):
            result = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
            self.assertEqual(result["status"], "BUILD_CONTROL_RETURNED", result)
            self.assertTrue(result["control_returned"])
            self.assertEqual(result["attempt_status"], "ACCEPTED")
            self.assertEqual(result["workpack_id"], workpack)
            self.assertEqual(result["budget"]["attempts_consumed"], count)
            self.assertFalse(result["budget"]["reset"])
            self.assertFalse(result["harness_e2e_verified"])
            self.assertEqual(result["stream_revision"], len(self.events()))
            self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), count)
        finished = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
        self.assertEqual(finished["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 2)

    def test_one_attempt_returns_rejection_before_native_repair_route(self):
        self._upstream_repair_fixture()
        self.prepare()
        controller = self.controller()
        controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
        rejected = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
        self.assertEqual(rejected["status"], "BUILD_CONTROL_RETURNED")
        self.assertEqual(rejected["attempt_status"], "REJECTED")
        self.assertFalse(self.events("BUILD_ACCEPTANCE_INVALIDATED"))
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 2)
        repaired = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
        self.assertEqual(repaired["workpack_id"], "IMPLEMENT-READER")
        self.assertEqual(len(self.events("BUILD_ACCEPTANCE_INVALIDATED")), 1)
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 3)

    def test_one_attempt_native_hold_is_not_successful_control_return(self):
        self.plan["schema_version"] = "1.1"
        self.plan["workpacks"][0]["environment"] = {
            "python": "python", "modules": ["test_missing_module_g2"], "paths": []}
        self.prepare()
        result = self.controller().advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
        self.assertEqual(result["status"], "HELD_COMMAND_FAILURE", result)
        self.assertEqual(result["attempt_status"], "BLOCKED")
        self.assertNotIn("control_returned", result)
        self.assertEqual([row["phase"] for row in self.runner.invocations], ["PREFLIGHT"])

    def test_one_attempt_recovery_not_dispatched_preserves_budget_and_ignores_new_handoff(self):
        self.prepare()
        controller = self.controller()
        with patch.object(controller, "_execute_command", side_effect=InjectedControllerCrash()), \
                self.assertRaises(InjectedControllerCrash):
            controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
        saved = self.events("BUILD_ATTEMPT_STARTED")[0]["payload"]
        result = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT", codex_handoff={
            "workpack_id": "IMPLEMENT-READER", "basis_attempt_ids": [saved["attempt_id"]],
            "summary": "New summary must not be attached to an existing attempt."})
        self.assertEqual(result["status"], "BUILD_CONTROL_RETURNED")
        self.assertEqual(result["attempt_status"], "NOT_DISPATCHED")
        self.assertEqual(result["attempt_id"], saved["attempt_id"])
        self.assertFalse(result["codex_handoff_used"])
        self.assertEqual(result["budget"]["attempts_consumed"], 1)
        self.assertEqual(result["budget"]["attempts_remaining"], 4)
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 1)
        self.assertFalse(self.runner.invocations)
        self.assertNotIn("codex_handoff", self.events("BUILD_ATTEMPT_STARTED")[0]["payload"])
        later = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
        self.assertEqual(later["attempt_status"], "ACCEPTED")
        self.assertEqual(later["budget"]["attempts_consumed"], 2)
        self.assertNotEqual(later["attempt_id"], saved["attempt_id"])

    def test_one_attempt_preflight_only_recovery_does_not_start_implementation(self):
        self.plan["schema_version"] = "1.1"
        self.plan["workpacks"][0]["environment"] = {"python": "python", "modules": ["json"], "paths": []}
        self.prepare()
        controller = self.controller()
        execute = controller._execute_command
        def interrupt_implementation(binding, prepared, invocation, revision):
            if invocation["phase"] == "IMPLEMENTATION":
                raise InjectedControllerCrash()
            return execute(binding, prepared, invocation, revision)
        with patch.object(controller, "_execute_command", side_effect=interrupt_implementation), \
                self.assertRaises(InjectedControllerCrash):
            controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
        result = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
        self.assertEqual(result["attempt_status"], "NOT_DISPATCHED")
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 1)
        self.assertEqual([row["phase"] for row in self.runner.invocations], ["PREFLIGHT"])

    def test_one_attempt_missing_observation_remains_unknown_not_not_dispatched(self):
        self.prepare()
        self.runner.after_run = lambda *args: (_ for _ in ()).throw(InjectedControllerCrash())
        controller = self.controller()
        with self.assertRaises(InjectedControllerCrash):
            controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
        self.runner.after_run = None
        result = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
        self.assertEqual(result["status"], "HELD_UNRESOLVED_ATTEMPT")
        self.assertEqual(result["attempt_status"], "IN_FLIGHT")
        self.assertEqual(len(self.runner.invocations), 1)
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 1)
        self.assertFalse(self.events("BUILD_ATTEMPT_FINISHED"))

    def test_one_attempt_recovery_completes_remaining_checks_only(self):
        self.prepare()
        controller = self.controller()
        append = controller._append
        def interrupt_before_inputs(kind, *args):
            if kind == "BUILD_VERIFICATION_INPUTS":
                raise InjectedControllerCrash()
            return append(kind, *args)
        with patch.object(controller, "_append", side_effect=interrupt_before_inputs), \
                self.assertRaises(InjectedControllerCrash):
            controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
        self.assertEqual(len(self.runner.invocations), 1)
        result = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
        self.assertEqual(result["status"], "BUILD_CONTROL_RETURNED")
        self.assertEqual(result["attempt_status"], "ACCEPTED")
        self.assertEqual([row["phase"] for row in self.runner.invocations],
                         ["IMPLEMENTATION", "VERIFICATION", "VERIFICATION"])
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 1)
        self.assertFalse((self.workspace / "outputs/summary.json").exists())

    def _codex_fixture_runner(self, captured, *, first_bad=False):
        self.plan["workpacks"][0]["executor"] = "CODEX"
        self.plan["workpacks"][0].pop("local_argv")
        self.scope.update(model="TEST-ONLY-NO-MODEL-CALL", allow_model_service=True)
        local_runner = self.runner
        def run(invocation, before_dispatch):
            if invocation["executor"] != "CODEX":
                return local_runner(invocation, before_dispatch)
            before_dispatch()
            captured.append(deepcopy(invocation))
            (self.workspace / "src/reader.py").write_text(BAD_READER if first_bad and len(captured) == 1 else GOOD_READER)
            return {"status": "MODEL_TURN_COMPLETED", "final_message": "TEST ONLY repair delta", "exit_code": 0}
        return run

    def test_codex_handoff_is_saved_once_and_only_sent_to_selected_implementation(self):
        captured = []
        runner = self._codex_fixture_runner(captured)
        self.prepare()
        handoff = {"workpack_id": "IMPLEMENT-READER", "basis_attempt_ids": [],
                   "summary": "Issue count is 2; chosen method is a fresh hypothesis; summary sentinel."}
        result = BuildController(self.store, self.program, runner=runner, clock=CLOCK).advance(
            self.prepared_id, advance_mode="ONE_ATTEMPT", codex_handoff=handoff)
        self.assertEqual(result["attempt_status"], "ACCEPTED")
        self.assertEqual(self.events("BUILD_ATTEMPT_STARTED")[0]["payload"]["codex_handoff"], handoff)
        context = json.loads(captured[0]["prompt"].split("\n", 1)[1])["task"]
        self.assertEqual(context["codex_handoff"], handoff)
        self.assertIn("outer Codex owns the cumulative issue record", captured[0]["prompt"])
        self.assertIn("original Plan explicitly declares a valid replacement", captured[0]["prompt"])
        self.assertIn("do not assume the old physical bytes remain available", captured[0]["prompt"])
        for rule in (
            "Use the received history and selected remaining allowance",
            "Return normally after targeted reproduction and related regression",
            "host runs independent acceptance after you return",
            "do not loop on self-tests while waiting or count pending acceptance as success",
            "stop that extra modification and return the gap",
            "Native independent-assertion repair retains its assigned contract and host budget",
        ):
            self.assertIn(rule, captured[0]["prompt"])
        self.assertTrue(all(handoff["summary"] not in item["prompt"] for item in self.runner.invocations))
        for kind in ("BUILD_COMMAND_PLANNED", "BUILD_COMMAND_OBSERVED", "BUILD_VERIFICATION_INPUTS", "BUILD_ATTEMPT_FINISHED"):
            self.assertTrue(all("codex_handoff" not in row["payload"] for row in self.events(kind)), kind)

    def test_codex_handoff_reaches_routed_producer_from_failed_consumer(self):
        self._upstream_repair_fixture()
        captured = []
        runner = self._codex_fixture_runner(captured, first_bad=True)
        self.prepare()
        controller = BuildController(self.store, self.program, runner=runner, clock=CLOCK)
        controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
        failure = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
        handoff = {"workpack_id": "IMPLEMENT-READER", "basis_attempt_ids": [failure["attempt_id"]],
                   "summary": "Consumer failed once; fix reader row counting; this is the same issue."}
        repaired = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT", codex_handoff=handoff)
        self.assertEqual(repaired["attempt_status"], "ACCEPTED", repaired)
        self.assertEqual(repaired["workpack_id"], "IMPLEMENT-READER")
        self.assertIn(handoff["summary"], captured[-1]["prompt"])
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 3)

    def test_codex_handoff_mismatch_keeps_native_invalidation_without_dispatch(self):
        self._upstream_repair_fixture()
        captured = []
        runner = self._codex_fixture_runner(captured, first_bad=True)
        self.prepare()
        controller = BuildController(self.store, self.program, runner=runner, clock=CLOCK)
        controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
        failure = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
        result = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT", codex_handoff={
            "workpack_id": "MAKE-REPORT", "basis_attempt_ids": [failure["attempt_id"]], "summary": "Wrong recipient"})
        self.assertEqual(result["status"], "HELD_CODEX_HANDOFF")
        self.assertEqual(len(self.events("BUILD_ACCEPTANCE_INVALIDATED")), 1)
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 2)
        self.assertEqual(len(captured), 1)

    def test_codex_handoff_rejects_foreign_prepared_basis_and_local_recipient(self):
        captured = []
        runner = self._codex_fixture_runner(captured)
        self.prepare()
        controller = BuildController(self.store, self.program, runner=runner, clock=CLOCK)
        first = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
        local = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT", codex_handoff={
            "workpack_id": "MAKE-REPORT", "basis_attempt_ids": [first["attempt_id"]], "summary": "LOCAL has no model"})
        self.assertEqual(local["status"], "HELD_CODEX_HANDOFF")
        prepared = prepare_build_authorization(self.store, self.program, self.proposal_id, self.source_id,
            self.scope, **self.kwargs("second-prepare"))
        self.prepared_id = prepared["event_id"]
        approve_build_authorization(self.store, self.program, self.prepared_id,
            human_message_ref="TEST-FIXTURE-SECOND-SCOPE", **self.kwargs("second-approval"))
        foreign = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT", codex_handoff={
            "workpack_id": "IMPLEMENT-READER", "basis_attempt_ids": [first["attempt_id"]], "summary": "Wrong prepared"})
        self.assertEqual(foreign["status"], "HELD_CODEX_HANDOFF")
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 1)

    def test_codex_handoff_preflight_failure_is_bound_but_not_delivered_to_model(self):
        self.plan["schema_version"] = "1.1"
        captured = []
        runner = self._codex_fixture_runner(captured)
        self.plan["workpacks"][0]["environment"] = {
            "python": "python", "modules": ["test_missing_module_g2"], "paths": []}
        self.prepare()
        result = BuildController(self.store, self.program, runner=runner, clock=CLOCK).advance(
            self.prepared_id, advance_mode="ONE_ATTEMPT", codex_handoff={
                "workpack_id": "IMPLEMENT-READER", "basis_attempt_ids": [], "summary": "Do not report model delivery"})
        self.assertEqual(result["status"], "HELD_COMMAND_FAILURE")
        self.assertIn("codex_handoff", self.events("BUILD_ATTEMPT_STARTED")[0]["payload"])
        self.assertFalse(captured)
        self.assertTrue(all(row["payload"]["phase"] == "PREFLIGHT" for row in self.events("BUILD_COMMAND_OBSERVED")))

    def test_one_attempt_rechecks_revocation_and_invalid_mode_does_not_dispatch(self):
        self.prepare()
        controller = self.controller()
        self.assertEqual(controller.advance(self.prepared_id, advance_mode="WRONG")["status"], "BUILD_STOPPED")
        self.assertFalse(self.events("BUILD_ATTEMPT_STARTED"))
        first = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
        self.assertEqual(first["attempt_status"], "ACCEPTED")
        revoke_build_authorization(self.store, self.program, self.prepared_id, **self.kwargs("revoke-step"))
        stopped = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
        self.assertEqual(stopped["status"], "BUILD_STOPPED")
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 1)


    def test_codex_handoff_recovery_preserves_saved_context_without_redelivery(self):
        captured = []
        runner = self._codex_fixture_runner(captured)
        self.prepare()
        controller = BuildController(self.store, self.program, runner=runner, clock=CLOCK)
        original = {"workpack_id": "IMPLEMENT-READER", "basis_attempt_ids": [], "summary": "Original repair context"}
        append = controller._append
        def interrupt_before_inputs(kind, *args):
            if kind == "BUILD_VERIFICATION_INPUTS":
                raise InjectedControllerCrash()
            return append(kind, *args)
        with patch.object(controller, "_append", side_effect=interrupt_before_inputs), \
                self.assertRaises(InjectedControllerCrash):
            controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT", codex_handoff=original)
        changed = {**original, "summary": "Later summary must stay unused"}
        result = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT", codex_handoff=changed)
        self.assertEqual(result["attempt_status"], "ACCEPTED")
        self.assertFalse(result["codex_handoff_used"])
        self.assertEqual(len(captured), 1)
        self.assertEqual(len(self.events("BUILD_ATTEMPT_STARTED")), 1)
        self.assertEqual(self.events("BUILD_ATTEMPT_STARTED")[0]["payload"]["codex_handoff"], original)
        self.assertNotIn(changed["summary"], json.dumps(self.events()))
        self.assertTrue(all(original["summary"] not in row["prompt"] for row in self.runner.invocations))


    def test_one_attempt_two_rejections_and_readback_do_not_dispatch_a_third(self):
        from harness_foundry_factory.build_entrypoint import read_build
        self.plan["workpacks"][0]["executor"] = "CODEX"
        self.plan["workpacks"][0].pop("local_argv")
        self.scope.update(model="TEST-ONLY-NO-MODEL-CALL", allow_model_service=True)
        self.prepare()
        captured = []
        local_runner = self.runner
        def no_progress(invocation, before_dispatch):
            if invocation["executor"] != "CODEX":
                return local_runner(invocation, before_dispatch)
            before_dispatch()
            captured.append(deepcopy(invocation))
            if len(captured) == 1:
                (self.workspace / "src/reader.py").write_text(BAD_READER)
            return {"status": "MODEL_TURN_COMPLETED", "exit_code": 0,
                    "final_message": "Round r1 failed; defect remains." if len(captured) == 1 else "Still looking."}
        controller = BuildController(self.store, self.program, runner=no_progress, clock=CLOCK)
        first = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
        original_bytes = (self.workspace / "src/reader.py").read_bytes()
        second = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT", codex_handoff={
            "workpack_id": "IMPLEMENT-READER", "basis_attempt_ids": [first["attempt_id"]],
            "summary": "r1 failed once; retain that round and recheck the same defect by a different method."})
        self.assertEqual(first["attempt_status"], "REJECTED")
        self.assertEqual(second["attempt_status"], "REJECTED")
        self.assertEqual(original_bytes, (self.workspace / "src/reader.py").read_bytes())
        before = self.store.database_path.read_bytes()
        with patch.object(BuildController, "advance", side_effect=AssertionError("readback must not resume")), \
                patch("harness_foundry_factory.process_observation.CommandObservation.recover",
                      side_effect=AssertionError("readback must not recover commands")):
            for _ in range(2):
                view = read_build(self.store.database_path, self.program)
                self.assertEqual(len(view["attempts"]), 2)
                self.assertEqual(view["attempts"][0]["implementation_commands"][0]["final_message"],
                                 "Round r1 failed; defect remains.")
                self.assertEqual(view["attempts"][1]["implementation_commands"][0]["final_message"], "Still looking.")
        self.assertEqual(before, self.store.database_path.read_bytes())
        self.assertEqual(len(captured), 2)
        self.assertEqual(second["budget"]["attempts_remaining"], 3)
        # The fixture caller deliberately makes no third advance. This proves
        # mechanical return/readback, not autonomous Codex judgment or counting.
        self.assertFalse((self.workspace / "outputs/summary.json").exists())

    def test_new_diagnosis_without_change_can_continue_with_bound_handoff(self):
        self.plan["workpacks"][0]["executor"] = "CODEX"
        self.plan["workpacks"][0].pop("local_argv")
        self.scope.update(model="TEST-ONLY-NO-MODEL-CALL", allow_model_service=True)
        self.prepare()
        captured = []
        local_runner = self.runner
        def diagnose_then_fix(invocation, before_dispatch):
            if invocation["executor"] != "CODEX":
                return local_runner(invocation, before_dispatch)
            before_dispatch()
            captured.append(deepcopy(invocation))
            path = self.workspace / "src/reader.py"
            if len(captured) == 1:
                path.write_text(BAD_READER)
            elif len(captured) == 3:
                path.write_text(GOOD_READER)
            return {"status": "MODEL_TURN_COMPLETED", "exit_code": 0,
                    "final_message": "Diagnostic evidence: empty input is not needed; ['1'] still returns zero rows."}
        controller = BuildController(self.store, self.program, runner=diagnose_then_fix, clock=CLOCK)
        initial = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
        original_bytes = (self.workspace / "src/reader.py").read_bytes()
        diagnosed = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT")
        self.assertEqual(diagnosed["attempt_status"], "REJECTED")
        self.assertEqual(original_bytes, (self.workspace / "src/reader.py").read_bytes())
        handoff = {"workpack_id": "IMPLEMENT-READER", "basis_attempt_ids": [initial["attempt_id"], diagnosed["attempt_id"]],
                   "summary": "New diagnostic: ['1'] also gives zero; exclude malformed-input handling. Prior r1 failure retained; diagnosis is not another product repair. Next method: count every row. Use original remaining budget."}
        fixed = controller.advance(self.prepared_id, advance_mode="ONE_ATTEMPT", codex_handoff=handoff)
        self.assertEqual(fixed["attempt_status"], "ACCEPTED", fixed)
        self.assertEqual(fixed["budget"]["attempts_consumed"], 3)
        self.assertEqual(len(captured), 3)
        context = json.loads(captured[-1]["prompt"].split("\n", 1)[1])["task"]
        self.assertEqual(context["codex_handoff"], handoff)
        self.assertFalse((self.workspace / "outputs/summary.json").exists())


class BuildRepairTests(unittest.TestCase):
    """Confirmed findings use real control events and synthetic model outcomes."""

    def setUp(self):
        self.f = BuildRuntimeTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.reader_text = GOOD_READER
        self.captured = []
        self.key = 0

    def prepare(self, *, codex=True, total=10, per_task=5):
        if codex:
            first = self.f.plan["workpacks"][0]
            first["executor"] = "CODEX"
            first.pop("local_argv", None)
        if any(task["executor"] == "CODEX" for task in self.f.plan["workpacks"]):
            self.f.scope.update(model="TEST-NO-MODEL-CALL", allow_model_service=True)
        self.f.scope.update(max_attempts=total, max_task_attempts=per_task)
        self.f.prepare()
        self.controller = BuildController(self.f.store, self.f.program, runner=self.runner, clock=CLOCK)
        self.assertEqual(self.controller.advance(self.f.prepared_id)["status"], "PLAN_CHECKS_ACCEPTED")

    def runner(self, invocation, before_dispatch):
        if invocation["executor"] != "CODEX":
            return self.f.runner(invocation, before_dispatch)
        before_dispatch()
        self.captured.append(deepcopy(invocation))
        if invocation["workpack_id"] == "MAKE-REPORT":
            (self.f.workspace / "outputs/summary.json").write_text(json.dumps({"rows": 3, "invalid": 2}))
        else:
            suffix = "# accepted replacement\n" if invocation["workpack_id"] == "READER-V2" else ""
            (self.f.workspace / "src/reader.py").write_text(self.reader_text + suffix)
        return {"status": "MODEL_TURN_COMPLETED", "final_message": "TEST ONLY incremental repair report", "exit_code": 0}

    def state(self):
        return self.controller._state(self.f.events(), self.f.prepared_id)

    def request(self, *, artifacts=("READER-SOURCE",), origin=None):
        self.key += 1
        _, accepted = self.state()
        owners = {artifact["artifact_id"]: task["workpack_id"] for task in self.f.plan["workpacks"]
                  for artifact in task["artifacts"]}
        request = {"program_id": self.f.program, "prepared_event_id": self.f.prepared_id,
                   "expected_revision": len(self.f.events()), "idempotency_key": "G1-REQUEST-" + str(self.key),
                   "targets": [{"artifact_id": artifact, "accepted_attempt_id": accepted[owners[artifact]]["attempt_id"]}
                               for artifact in artifacts],
                   "finding": {"requirement_refs": ["PROJECT-BRIEF:L1-L2"], "reason": "confirmed synthetic extra case",
                               "evidence_refs": ["fixture counterexample"], "repair_goal": "repair and recheck this case"}}
        if origin:
            request["continuation_of"] = origin["event_id"]
        return request

    def repair(self, request=None, *, controller=None):
        from harness_foundry_factory.build_repair import request_build_repair
        return request_build_repair(controller or self.controller, request or self.request())

    def step(self):
        return self.controller.advance(self.f.prepared_id, advance_mode="ONE_ATTEMPT")

    def rejected_without_mutation(self, request, message=None, *, exception=RequestValidationError):
        before = self.f.events()
        before_calls = len(self.captured) + len(self.f.runner.invocations)
        with self.assertRaises(exception) as caught:
            self.repair(request)
        if message:
            self.assertIn(message, str(caught.exception))
        self.assertEqual(self.f.events(), before)
        self.assertEqual(len(self.captured) + len(self.f.runner.invocations), before_calls)

    def test_exact_replay_after_rebuild_and_expiry_never_invalidates_again(self):
        self.prepare()
        request = self.request()
        original = self.repair(request)
        self.assertEqual(self.controller.advance(self.f.prepared_id)["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(self.f.events("BUILD_ATTEMPT_STARTED")), 4)
        expired = BuildController(self.f.store, self.f.program, runner=self.runner,
                                  clock=lambda: datetime.fromisoformat("2026-09-19T00:00:00+00:00"))
        before = self.f.events()
        self.assertEqual(self.repair(request, controller=expired), original)
        self.assertEqual(self.f.events(), before)
        self.assertEqual(len(self.f.events("BUILD_ACCEPTANCE_INVALIDATED")), 1)
        self.assertEqual(len(self.state()[1]), 2)
        from harness_foundry_factory.build_types import IdempotencyConflictError
        changed = deepcopy(request)
        changed["finding"]["reason"] = "a different claim under the same key"
        self.rejected_without_mutation(changed, exception=IdempotencyConflictError)

    def test_stale_revision_target_and_byte_drift_do_not_invalidate(self):
        from harness_foundry_factory.build_types import RevisionConflictError
        self.prepare()
        stale_revision = self.request()
        stale_revision["expected_revision"] -= 1
        self.rejected_without_mutation(stale_revision, exception=RevisionConflictError)
        stale_target = self.request()
        stale_target["targets"][0]["accepted_attempt_id"] = "not-the-current-attempt"
        self.rejected_without_mutation(stale_target, "current accepted version")
        path = self.f.workspace / "src/reader.py"
        path.write_text(GOOD_READER + "# external drift\n")
        self.rejected_without_mutation(self.request(), "bytes differ")
        self.assertFalse(self.f.events("BUILD_ACCEPTANCE_INVALIDATED"))

    def test_local_producer_is_explicit_gap_without_new_attempt(self):
        self.prepare(codex=False)
        self.rejected_without_mutation(self.request(), "LOCAL producer")
        self.assertEqual(len(self.f.events("BUILD_ATTEMPT_STARTED")), 2)
        self.assertEqual(len(self.state()[1]), 2)

    def test_insufficient_total_or_task_budget_preserves_acceptance(self):
        for total, per_task, reason in ((3, 4, "ATTEMPT_BUDGET_EXHAUSTED"),
                                        (10, 1, "TASK_REPAIR_BUDGET_EXHAUSTED")):
            with self.subTest(total=total, per_task=per_task):
                case = BuildRepairTests()
                case.setUp()
                self.addCleanup(case.doCleanups)
                case.prepare(total=total, per_task=per_task)
                case.rejected_without_mutation(case.request(), reason)
                self.assertEqual(len(case.state()[1]), 2)

    def test_cas_conflict_does_not_commit_partial_invalidation(self):
        from harness_foundry_factory.build_types import RevisionConflictError
        self.prepare()
        request = self.request()
        append = self.f.store.append_batch
        def concurrent_revoke(program, records, **kwargs):
            append(program, [{"event_type": "BUILD_AUTHORIZATION_REVOKED",
                              "payload": {"prepared_event_id": self.f.prepared_id}}],
                   expected_revision=request["expected_revision"], idempotency_key="CONCURRENT-REVOKE", created_at=NOW)
            return append(program, records, **kwargs)
        with patch.object(self.f.store, "append_batch", side_effect=concurrent_revoke), \
                self.assertRaises(RevisionConflictError):
            self.repair(request)
        self.assertEqual(len(self.f.events("BUILD_AUTHORIZATION_REVOKED")), 1)
        self.assertFalse(self.f.events("BUILD_ACCEPTANCE_INVALIDATED"))
        self.assertEqual(len(self.state()[1]), 2)
        self.assertEqual(len(self.f.events("BUILD_ATTEMPT_STARTED")), 2)

    def test_continuation_before_consumer_rebuild_counts_union_once(self):
        # Spent=3; producer+consumer require exactly 2 more, not 3 because the
        # invalidated consumer is both pending and in the new dependency closure.
        self.prepare(total=5, per_task=3)
        origin = self.repair()
        self.assertEqual(self.step()["attempt_status"], "ACCEPTED")
        attempts, accepted = self.state()
        self.assertEqual(set(accepted), {"IMPLEMENT-READER"})
        self.assertEqual(list(attempts.values())[1]["status"], "INVALIDATED")
        continuation = self.repair(self.request(origin=origin))
        self.assertEqual(continuation["payload"]["workpack_ids"], ["IMPLEMENT-READER", "MAKE-REPORT"])
        self.assertEqual(len(self.f.events("BUILD_ATTEMPT_STARTED")), 3)
        self.assertEqual(self.controller.advance(self.f.prepared_id)["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(self.f.events("BUILD_ATTEMPT_STARTED")), 5)

    def _recover_undispatched_consumer(self, *, preflight=False, total=6, per_task=3):
        if preflight:
            self.f.plan["schema_version"] = "1.1"
            self.f.plan["workpacks"][1]["environment"] = {"python": "python", "modules": ["json"], "paths": []}
        self.prepare(total=total, per_task=per_task)
        origin = self.repair()
        self.assertEqual(self.step()["workpack_id"], "IMPLEMENT-READER")
        execute = self.controller._execute_command
        def interrupt_implementation(binding, prepared, invocation, revision):
            if invocation["phase"] == "IMPLEMENTATION":
                raise InjectedControllerCrash()
            return execute(binding, prepared, invocation, revision)
        with patch.object(self.controller, "_execute_command", side_effect=interrupt_implementation), \
                self.assertRaises(InjectedControllerCrash):
            self.step()
        # A missing observation alone never grants continuation eligibility.
        self.rejected_without_mutation(self.request(origin=origin), "unresolved attempts")
        recovered = self.step()
        self.assertEqual(recovered["attempt_status"], "NOT_DISPATCHED")
        self.assertEqual(recovered["workpack_id"], "MAKE-REPORT")
        self.assertEqual(recovered["budget"]["attempts_consumed"], 4)
        self.assertEqual(recovered["budget"]["attempts_remaining"], total - 4)
        self.assertEqual(recovered["budget"]["task_attempts_consumed"], {"IMPLEMENT-READER": 2, "MAKE-REPORT": 2})
        self.assertFalse(recovered["budget"]["reset"])
        return origin, recovered

    def _continue_after_undispatched_consumer(self, *, preflight):
        origin, recovered = self._recover_undispatched_consumer(preflight=preflight)
        request = self.request(origin=origin)
        event = self.repair(request)
        before = self.f.events()
        self.assertEqual(self.repair(request), event)
        self.assertEqual(self.f.events(), before)
        self.assertEqual(len(self.f.events("BUILD_ATTEMPT_STARTED")), 4)
        self.assertEqual(self.state()[0][recovered["attempt_id"]]["status"], "NOT_DISPATCHED")
        # Repair A before dispatching B, counting B once despite being both
        # pending and a dependent of A; the interrupted attempt is not refunded.
        repaired = self.step()
        self.assertEqual((repaired["workpack_id"], repaired["attempt_status"]), ("IMPLEMENT-READER", "ACCEPTED"))
        rebuilt = self.step()
        self.assertEqual((rebuilt["workpack_id"], rebuilt["attempt_status"]), ("MAKE-REPORT", "ACCEPTED"))
        self.assertEqual(rebuilt["budget"]["attempts_consumed"], 6)
        self.assertEqual(rebuilt["budget"]["task_attempts_consumed"], {"IMPLEMENT-READER": 3, "MAKE-REPORT": 3})
        self.assertEqual(self.step()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(self.f.events("BUILD_ATTEMPT_STARTED")), 6)

    def test_continuation_after_no_intent_recovery_repairs_producer_first(self):
        self._continue_after_undispatched_consumer(preflight=False)

    def test_continuation_after_preflight_only_recovery_repairs_producer_first(self):
        self._continue_after_undispatched_consumer(preflight=True)

    def test_undispatched_continuation_preserves_total_attempt_consumption(self):
        origin, _ = self._recover_undispatched_consumer(total=5)
        self.rejected_without_mutation(self.request(origin=origin), "ATTEMPT_BUDGET_EXHAUSTED")

    def test_undispatched_continuation_preserves_task_attempt_consumption(self):
        origin, _ = self._recover_undispatched_consumer(per_task=2)
        self.rejected_without_mutation(self.request(origin=origin), "TASK_REPAIR_BUDGET_EXHAUSTED")

    def _independent_producers(self):
        consumer = self.f.plan["workpacks"][1]
        consumer.update(executor="CODEX", depends_on=[], inputs=[{"kind": "SOURCE", "id": "PROJECT-BRIEF"}])
        consumer.pop("local_argv")

    def test_continuation_counts_unrebuilt_original_producer_even_outside_new_closure(self):
        self._independent_producers()
        self.prepare(total=4, per_task=3)
        origin = self.repair(self.request(artifacts=("READER-SOURCE", "SUMMARY")))
        self.assertEqual(self.step()["workpack_id"], "IMPLEMENT-READER")
        self.rejected_without_mutation(self.request(origin=origin), "ATTEMPT_BUDGET_EXHAUSTED")
        # Omitting MAKE-REPORT from the pending budget would incorrectly admit
        # this request at spent 3 / total 4, leaving no budget to rebuild it.
        self.assertEqual(len(self.state()[1]), 1)
        self.assertEqual(len(self.f.events("BUILD_ACCEPTANCE_INVALIDATED")), 1)

    def test_continuation_allows_other_original_producer_with_enough_budget(self):
        self._independent_producers()
        self.prepare(total=5, per_task=3)
        origin = self.repair(self.request(artifacts=("READER-SOURCE", "SUMMARY")))
        self.step()
        event = self.repair(self.request(origin=origin))
        self.assertEqual(event["payload"]["workpack_ids"], ["IMPLEMENT-READER"])
        self.assertEqual(self.controller.advance(self.f.prepared_id)["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(self.f.events("BUILD_ATTEMPT_STARTED")), 5)

    def _consumer_failure(self):
        self.f._upstream_repair_fixture()
        self.prepare(total=12, per_task=6)
        origin = self.repair()
        self.reader_text = BAD_READER
        self.assertEqual(self.step()["attempt_status"], "ACCEPTED")
        failed = self.step()
        self.assertEqual(failed["attempt_status"], "REJECTED")
        self.assertEqual(failed["workpack_id"], "MAKE-REPORT")
        return origin, failed

    def test_unhandled_consumer_failure_cannot_be_overwritten_by_g1(self):
        origin, _ = self._consumer_failure()
        self.rejected_without_mutation(self.request(origin=origin), "latest unaccepted attempt")
        self.assertEqual(len(self.f.events("BUILD_ACCEPTANCE_INVALIDATED")), 1)

    def test_latest_native_routed_rejected_consumer_is_valid_pending_rebuild(self):
        origin, failed = self._consumer_failure()
        self.reader_text = GOOD_READER
        self.assertEqual(self.step()["workpack_id"], "IMPLEMENT-READER")
        attempts, accepted = self.state()
        self.assertEqual(attempts[failed["attempt_id"]]["status"], "REJECTED")
        native = self.f.events("BUILD_ACCEPTANCE_INVALIDATED")[-1]["payload"]
        self.assertEqual(native["failed_attempt_id"], failed["attempt_id"])
        self.assertEqual(native["prepared_event_id"], self.f.prepared_id)
        self.assertEqual(set(accepted), {"IMPLEMENT-READER"})
        self.repair(self.request(origin=origin))
        self.assertEqual(self.controller.advance(self.f.prepared_id)["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(self.f.events("BUILD_ATTEMPT_STARTED")), 7)

    def test_old_handled_failure_does_not_cover_latest_unhandled_failure(self):
        origin, old_failed = self._consumer_failure()
        self.assertEqual(self.step()["workpack_id"], "IMPLEMENT-READER")
        new_failed = self.step()
        self.assertEqual(new_failed["attempt_status"], "REJECTED")
        self.assertNotEqual(old_failed["attempt_id"], new_failed["attempt_id"])
        self.assertEqual(self.f.events("BUILD_ACCEPTANCE_INVALIDATED")[-1]["payload"]["failed_attempt_id"],
                         old_failed["attempt_id"])
        self.rejected_without_mutation(self.request(origin=origin), "latest unaccepted attempt")

    def test_other_prepared_handling_event_does_not_acknowledge_current_failure(self):
        origin, failed = self._consumer_failure()
        other = prepare_build_authorization(self.f.store, self.f.program, self.f.proposal_id, self.f.source_id,
                                           self.f.scope, **self.f.kwargs("OTHER-PREPARED"))
        # Explicit competing-scope fixture event: its failure ID alone must not
        # be used as acknowledgement in this request's prepared stream.
        self.f.store.append_batch(self.f.program, [{"event_type": "BUILD_ACCEPTANCE_INVALIDATED", "payload": {
            "prepared_event_id": other["event_id"], "reason": "INDEPENDENT_ARTIFACT_REPAIR_REQUIRED",
            "failed_attempt_id": failed["attempt_id"], "workpack_ids": ["IMPLEMENT-READER", "MAKE-REPORT"],
            "budget_reset": False, "files_deleted": False}}], **self.f.kwargs("OTHER-HANDLED"))
        self.rejected_without_mutation(self.request(origin=origin), "latest unaccepted attempt")

    def test_unresolved_overlapping_scope_blocks_new_repair(self):
        self.prepare()
        other = prepare_build_authorization(self.f.store, self.f.program, self.f.proposal_id, self.f.source_id,
                                           self.f.scope, **self.f.kwargs("OTHER-PREPARED"))
        approve_build_authorization(self.f.store, self.f.program, other["event_id"], human_message_ref="TEST ONLY",
                                    **self.f.kwargs("OTHER-APPROVED"))
        def unknown(invocation, before_dispatch):
            before_dispatch()
            return {"status": "UNKNOWN_SIDE_EFFECT", "reason_code": "TEST OBSERVATION LOST"}
        controller = BuildController(self.f.store, self.f.program, runner=unknown, clock=CLOCK)
        self.assertEqual(controller.advance(other["event_id"])["status"], "HELD_UNRESOLVED_ATTEMPT")
        self.rejected_without_mutation(self.request(), "unresolved attempts")

    def test_repair_of_replacement_cannot_reuse_consumed_input_version(self):
        replacement = deepcopy(self.f.plan["workpacks"][0])
        replacement.update(workpack_id="READER-V2", job_id="READER-V2", executor="CODEX", depends_on=["MAKE-REPORT"],
                           inputs=[{"kind": "ARTIFACT", "id": "READER-SOURCE"}],
                           artifacts=[{"artifact_id": "READER-V2", "path": "src/reader.py", "replaces_artifact_id": "READER-SOURCE"}])
        replacement.pop("local_argv")
        for check in replacement["verification"]:
            check["artifact_ids"] = ["READER-V2"]
        self.f.plan["workpacks"].append(replacement)
        self.f.scope["task_write_roots"]["READER-V2"] = ["src"]
        self.prepare()
        self.rejected_without_mutation(self.request(artifacts=("READER-V2",)), "consumed artifact version")
        self.assertEqual(len(self.state()[1]), 3)
        self.assertFalse(self.f.events("BUILD_ACCEPTANCE_INVALIDATED"))

if __name__ == "__main__":
    unittest.main()
