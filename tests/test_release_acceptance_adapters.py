"""Source-owned acceptance adapters: synthetic fixtures, no real model approval."""
import contextlib
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from devtools.release_acceptance import exercise, prepare, recovery_probe, verify
from harness_foundry_factory import test_execution
from harness_foundry_factory.build_runtime import classify_verification_result
from harness_foundry_factory.build_plan import compile_build_plan
from harness_foundry_factory.build_types import RequestValidationError
from test_build_plan import request_fixture


ROOT = Path(__file__).resolve().parents[1]


class ReleaseAcceptanceAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def report(self):
        return {"protected_source_unchanged": True,
                "tests": {"status": "CHECKS_PASS", "tests_run": 2},
                "harness_check": {"exit_code": 0, "stdout": '{"status":"CHECKS_PASS"}', "stderr": ""}}

    def quality_module(self):
        path = ROOT / "devtools/release_acceptance/quality_report.py"
        self.assertTrue(path.is_file(), "WP4 requires a descriptive initial/final/reuse report")
        spec = importlib.util.spec_from_file_location("quality_report", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_factorial_report_keeps_unrun_and_unknown_costs_unknown(self):
        quality = self.quality_module()
        self.assertEqual(quality.factorial_summary()["status"], "NOT_RUN")
        conditions = {key: "fixed" for key in quality.COMPARISON_FIELDS}
        conditions["executor"] = {"requested_model": "fixture", "effective_model": "fixture",
                                  "client_version": "fixture", "service_revision": None}
        runs = [{"run_id": f"{foundry}-{document}", "task_id": "TASK-CLI", "foundry": foundry,
                 "document": document, "outcome": "PASS", "conditions": deepcopy(conditions),
                 "evidence_refs": ["external-check.json"], "attempts": 2, "tokens": None}
                for foundry in ("baseline", "upgraded") for document in ("original", "clarified")]
        result = quality.factorial_summary(runs)
        self.assertEqual(result["status"], "MATCHED_OBSERVABLE_CONDITIONS")
        self.assertIsNone(result["cells"]["baseline/original"]["mean"]["tokens"])
        self.assertFalse(result["improvement_demonstrated"])
        self.assertIn("SERVICE_REVISION_UNKNOWN", result["limitations"])
        second_task = deepcopy(runs)
        for row in second_task:
            row["run_id"] += "-csv"
            row["task_id"] = "CSV"
            row["conditions"]["inputs"] = "csv-input"
            row["conditions"]["contract"] = "csv-obligations"
        self.assertEqual(quality.factorial_summary(runs + second_task)["status"], "MATCHED_OBSERVABLE_CONDITIONS")
        second_task[-1]["conditions"]["contract"] = "weaker-obligations"
        mismatch = quality.factorial_summary(runs + second_task)
        self.assertEqual(mismatch["status"], "NOT_COMPARABLE")
        self.assertIn("CSV:contract", mismatch["differing_or_missing"])
        invalid = deepcopy(runs)
        invalid[-1]["conditions"]["executor"].pop("effective_model")
        self.assertEqual(quality.factorial_summary(invalid)["status"], "NOT_COMPARABLE")
        runs[-1]["conditions"]["budget"] = "larger"
        self.assertEqual(quality.factorial_summary(runs)["status"], "NOT_COMPARABLE")
        self.assertEqual(quality.factorial_summary(runs[:-1])["status"], "INCOMPLETE")

    def test_event_window_subscribes_before_short_lived_action(self):
        from devtools.release_acceptance.observation_window import observe_window
        callbacks = []
        def subscribe(callback):
            callbacks.append(callback)
            return lambda: callbacks.remove(callback)
        result = observe_window(ready=lambda: True, subscribe=subscribe,
            trigger=lambda: callbacks[0]({"state": "saved"}), matches=lambda event: event["state"] == "saved",
            timeout_seconds=1)
        self.assertEqual(result["status"], "OBSERVED")
        self.assertFalse(result["accepted"])
        self.assertEqual(callbacks, [])
        result = observe_window(ready=lambda: False, subscribe=subscribe,
            trigger=lambda: self.fail("not ready"), matches=lambda event: True, timeout_seconds=1)
        self.assertFalse(result["triggered"])
        result = observe_window(ready=lambda: True, subscribe=subscribe, trigger=lambda: None,
                                matches=lambda event: True, timeout_seconds=0.001)
        self.assertEqual(result["status"], "OBSERVATION_INCOMPLETE")
        self.assertEqual(callbacks, [])
        self.assertFalse(result["accepted"])

    def test_authored_plan_is_preserved_without_fixed_stages_or_authority(self):
        proposed = getattr(prepare, "authored_proposal", None)
        self.assertTrue(callable(proposed), "Run Test must accept the Agent's actual Plan")
        request = request_fixture()
        original = deepcopy(request)
        scope = {"workspace_root": str(self.root / "not-created"),
                 "task_write_roots": {"IMPLEMENT-READER": ["src"], "MAKE-REPORT": ["outputs"]}}
        with patch("subprocess.Popen", side_effect=AssertionError("proposal cannot execute")):
            result = proposed(request, scope)
        self.assertEqual(result["request"], original)
        self.assertEqual(result["scope"], scope)
        self.assertFalse(result["authority_granted"])
        self.assertFalse(result["scope_validated"])
        self.assertFalse((self.root / "not-created").exists())
        result["request"]["plan"]["workpacks"][0]["goal"] = "changed copy"
        self.assertEqual(request, original)
        request["plan"]["workpacks"][1]["depends_on"] = []
        with self.assertRaises(RequestValidationError):
            proposed(request, scope)

    def evaluation(self, ref, result, harness="H1", package="P1"):
        return {"evaluation_ref": ref, "package_ref": package, "harness_ref": harness,
                "results": {"B02": result}, "evidence_refs": [ref + ".json"],
                "usage": None, "failure_origin": "NATURAL"}

    def test_quality_report_preserves_initial_failure_and_missing_final_coverage(self):
        quality = self.quality_module()
        rows = [self.evaluation("first", "FAIL"), self.evaluation("repaired", "PASS", "H2")]
        original = deepcopy(rows)
        result = quality.summarize(rows, ["B02", "B09"])
        self.assertEqual(result["initial"]["results"]["B02"], "FAIL")
        self.assertEqual(result["final"]["results"]["B02"], "PASS")
        self.assertEqual(result["final"]["results"]["B09"], "NOT_RUN")
        self.assertIsNone(result["initial"]["usage"])
        self.assertFalse(result["release_accepted"])
        self.assertFalse(result["harness_e2e_verified"])
        self.assertEqual(rows, original)
        result["history"][0]["results"]["B02"] = "PASS"
        self.assertEqual(rows, original)

    def use(self, task, kind, session, snapshot):
        return {"task_id": task, "task_kind": kind, "session_ref": session,
                "package_ref": "P1", "harness_ref": "H1", "result": "PASS",
                "evidence_refs": [task + ".json"], "harness_before": snapshot,
                "harness_after": deepcopy(snapshot)}

    def test_unready_build_is_not_dropped_and_old_passes_do_not_fill_new_version(self):
        quality = self.quality_module()
        first = self.evaluation("not-ready", "NOT_READY", harness=None)
        partial = self.evaluation("old-package", "PASS", package="P0")
        last = self.evaluation("new-package", "BLOCKED", harness="H2")
        last["results"] = {"B03": "BLOCKED"}
        result = quality.summarize([first, partial, last], ["B02", "B03"])
        self.assertIsNone(result["initial"]["harness_ref"])
        self.assertEqual(result["initial"]["results"]["B02"], "NOT_READY")
        self.assertEqual(result["final"]["results"]["B02"], "NOT_RUN")
        self.assertEqual(result["final"]["results"]["B03"], "BLOCKED")
        self.assertEqual(len(result["history"]), 3)
        self.assertEqual(result["comparison"]["status"], "NOT_REQUESTED")

    def test_reuse_compares_declared_harness_bytes_not_only_version_labels(self):
        quality = self.quality_module()
        harness = self.root / "harness"; harness.mkdir()
        entry = harness / "check.py"; entry.write_text("print('check')\n")
        snapshot = quality.capture_harness(harness, ["check.py"])
        uses = [self.use("implement", "IMPLEMENT", "session-1", snapshot),
                self.use("repair", "REPAIR", "session-2", snapshot)]
        args = dict(package_ref="P1", harness_ref="H1")
        self.assertEqual(quality.reuse_summary(uses, **args)["status"], "OBSERVED")
        (harness / "runtime-data").write_text("legit changing state")
        self.assertEqual(quality.capture_harness(harness, ["check.py"]), snapshot)
        entry.write_text("print('different check')\n")
        uses[1]["harness_after"] = quality.capture_harness(harness, ["check.py"])
        self.assertEqual(quality.reuse_summary(uses, **args)["status"], "NOT_DEMONSTRATED")
        for field, value in (("harness_before", {}), ("task_kind", "IMPLEMENT"),
                             ("session_ref", "session-1"), ("harness_ref", "H2"),
                             ("package_ref", "P2"), ("result", "BLOCKED"), ("evidence_refs", [])):
            changed = deepcopy(uses)
            changed[1] = self.use("repair", "REPAIR", "session-2", snapshot)
            changed[1][field] = value
            with self.subTest(field=field):
                self.assertEqual(quality.reuse_summary(changed, **args)["status"], "NOT_DEMONSTRATED")

    def test_comparison_needs_actual_conditions_and_never_claims_improvement(self):
        quality = self.quality_module()
        conditions = {key: "same" for key in quality.COMPARISON_FIELDS}
        conditions["executor"] = {"requested_model": "model", "effective_model": "model",
                                  "client_version": "client", "service_revision": None}
        old = {"conditions": conditions, "evidence_refs": ["old.json"]}
        new = deepcopy(old); new["evidence_refs"] = ["new.json"]
        result = quality.comparison_summary(old, new)
        self.assertEqual(result["status"], "MATCHED_OBSERVABLE_CONDITIONS")
        self.assertFalse(result["improvement_demonstrated"])
        self.assertIn("SERVICE_REVISION_UNKNOWN", result["limitations"])
        new["conditions"]["executor"]["effective_model"] = None
        self.assertEqual(quality.comparison_summary(old, new)["status"], "NOT_COMPARABLE")
        for key in quality.COMPARISON_FIELDS:
            changed = deepcopy(new); changed["conditions"].pop(key)
            self.assertEqual(quality.comparison_summary(old, changed)["status"], "NOT_COMPARABLE")

    def test_nested_unexpected_error_is_not_flattened_by_failed_harness(self):
        report = self.report()
        report["tests"] = {"status":"CHECKS_FAILED", "failure_kind":"INFRASTRUCTURE",
                           "errors":[{"phase":"setUp", "exception_type":"PermissionError"}]}
        report["harness_check"] = {"exit_code":1,"stdout":"", "stderr":"untyped tests failed"}
        with self.assertRaises(verify.CheckFailure) as caught:
            verify.environment_report(report, "csv")
        verdict = caught.exception.verdict
        self.assertEqual(verdict["evidence"], report["tests"])
        raw = {"status":"VALIDATION_FAILED", "exit_code":1, "stdout":json.dumps(verdict)}
        self.assertFalse(classify_verification_result(raw)["automatic_retry_allowed"])
        self.assertNotIn("repair_artifact_ids", verdict)

    def test_normal_pass_and_assertion_maps_to_upstream_not_observer(self):
        report = self.report()
        verify.environment_report(report, "task")
        report["tests"] = {"status":"CHECKS_FAILED", "failure_kind":"ASSERTION", "tests_run":2,
                           "failures":[{"test":"wrong result"}]}
        with self.assertRaises(verify.CheckFailure) as caught:
            verify.environment_report(report, "task")
        self.assertEqual(caught.exception.verdict["repair_artifact_ids"], ["U-0", "U-1"])

    def test_failure_protocol_preserves_category_not_reason(self):
        for kind in ("ASSERTION", "INFRASTRUCTURE", "CONTRACT_GAP"):
            report = self.report()
            verdict = {"status": "CHECKS_FAILED", "failure_kind": kind, "reason": "explanation"}
            report["harness_check"] = {"exit_code": 1, "stdout": json.dumps(verdict), "stderr": ""}
            with self.subTest(kind=kind), self.assertRaises(verify.CheckFailure) as caught:
                verify.environment_report(report, "task")
            result = caught.exception.verdict
            self.assertEqual(result["failure_kind"], kind)
            self.assertEqual(result["evidence"], verdict)
            routed = classify_verification_result({"status": "VALIDATION_FAILED", "exit_code": 1,
                                                   "stdout": json.dumps(result)})
            self.assertEqual(routed["automatic_retry_allowed"], kind == "ASSERTION")
        for verdict in ({"status": "CHECKS_FAILED", "reason": "ASSERTION"},
                        {"status": "CHECKS_FAILED", "failure_kind": "unknown"}):
            with self.subTest(verdict=verdict), self.assertRaises(verify.CheckFailure) as caught:
                verify.nested_result(verdict, "checker failed")
            self.assertEqual(caught.exception.verdict["failure_kind"], "INFRASTRUCTURE")

    def test_real_test_adapter_failure_kind_survives_wrapper_and_controller(self):
        # Ordinary local unittest fixtures, not a generated/modified Harness or model run.
        fixtures = (
            ("def test_one(self): self.assertEqual(1, 2)", "ASSERTION"),
            ("def test_one(self): raise PermissionError('fixture unavailable')", "INFRASTRUCTURE"),
            ("@unittest.skip('not run')\n def test_one(self): pass", "INFRASTRUCTURE"),
            ("pass", "INFRASTRUCTURE"),
        )
        for index, (body, kind) in enumerate(fixtures):
            app, scratch = self.root / f"app-{index}", self.root / f"scratch-{index}"
            app.mkdir(); scratch.mkdir()
            (app / "test_subject.py").write_text("import unittest\nclass Subject(unittest.TestCase):\n " + body + "\n")
            result = test_execution.run_tests(app, scratch, sys.executable)
            report = self.report()
            report["tests"] = result
            with self.subTest(body=body):
                with self.assertRaises(verify.CheckFailure) as caught:
                    verify.environment_report(report, "task")
                verdict = caught.exception.verdict
                self.assertEqual(verdict["failure_kind"], kind)
                self.assertEqual(verdict["evidence"], result)
                routed = classify_verification_result({"status": "VALIDATION_FAILED", "exit_code": 1,
                                                       "stdout": json.dumps(verdict)})
                self.assertEqual(routed["automatic_retry_allowed"], kind == "ASSERTION")
                if kind == "ASSERTION":
                    self.assertEqual(routed["repair_artifact_ids"], ["U-0", "U-1"])
                else:
                    self.assertNotIn("repair_artifact_ids", routed)

    def test_incomplete_or_contradictory_json_test_results_do_not_pass_or_trigger_repair(self):
        for status in ("CHECKS_PASS", "CHECKS_FAILED"):
            for details in ({"errors": [{"phase": "setUp"}]}, {"discovery_errors": ["import"]},
                            {"skipped": ["not run"]}, {"expected_failures": ["known"]},
                            {"tests_run": 0}, {"tests_run": True}, {"tests_run": "2"}):
                verdict = {"status": status, "failure_kind": None if status == "CHECKS_PASS" else "ASSERTION",
                           "tests_run": 2, **details}
                for origin in ("tests", "harness_check"):
                    report = self.report()
                    report[origin] = verdict if origin == "tests" else {
                        "exit_code": 0 if status == "CHECKS_PASS" else 1,
                        "stdout": json.dumps(verdict), "stderr": ""}
                    with self.subTest(status=status, details=details, origin=origin):
                        with self.assertRaises(verify.CheckFailure) as caught:
                            verify.environment_report(report, "task")
                        self.assertEqual(caught.exception.verdict["failure_kind"], "INFRASTRUCTURE")
                        self.assertNotIn("repair_artifact_ids", caught.exception.verdict)
                        self.assertEqual(caught.exception.verdict["evidence"], verdict)
        for verdict in (None, [], {"status": "CHECKS_PASS", "failure_kind": "ASSERTION"},
                        {"status": "CHECKS_PASS", "failures": ["wrong result"]},
                        {"status": "CHECKS_PASS", "unexpected_successes": ["unexpected"]}):
            with self.subTest(verdict=verdict), self.assertRaises(verify.CheckFailure) as caught:
                verify.nested_result(verdict, "invalid report")
            self.assertEqual(caught.exception.verdict["failure_kind"], "INFRASTRUCTURE")
        report = self.report()
        report["tests"].pop("tests_run")
        with self.assertRaises(verify.CheckFailure) as caught:
            verify.environment_report(report, "task")
        self.assertEqual(caught.exception.verdict["failure_kind"], "INFRASTRUCTURE")

    def test_incomplete_json_negative_observation_is_not_successful_rejection(self):
        for details in ({"errors": ["unexpected"]}, {"skipped": ["not run"]}, {"tests_run": 0}):
            verdict = {"status": "CHECKS_FAILED", "failure_kind": "ASSERTION", **details}
            report = {"negative_source_unchanged": True, "negative_harness_check": {
                "exit_code": 1, "stdout": json.dumps(verdict), "stderr": ""}}
            with self.subTest(details=details), self.assertRaises(verify.CheckFailure) as caught:
                verify.negative_harness_report(report)
            self.assertEqual(caught.exception.verdict["failure_kind"], "INFRASTRUCTURE")

    def test_checker_contract_mismatch_returns_its_producer(self):
        report = self.report()
        report["harness_check"]["stdout"] = '{"status":"PASS"}'
        with self.assertRaises(verify.CheckFailure) as caught:
            verify.environment_report(report, "csv")
        self.assertEqual(caught.exception.verdict["repair_artifact_ids"], ["H-2"])

    def test_always_pass_checker_is_rejected_but_crash_is_not_negative_success(self):
        report = {"negative_source_unchanged":True, "negative_harness_check":self.report()["harness_check"]}
        with self.assertRaises(verify.CheckFailure) as caught:
            verify.negative_harness_report(report)
        self.assertEqual(caught.exception.verdict["repair_artifact_ids"],["H-2"])
        for kind in ("ASSERTION","INFRASTRUCTURE"):
            report["negative_harness_check"] = {"exit_code":1,"stderr":"",
                "stdout":json.dumps({"status":"CHECKS_FAILED","failure_kind":kind})}
            if kind == "ASSERTION":
                verify.negative_harness_report(report)
            else:
                with self.assertRaises(verify.CheckFailure): verify.negative_harness_report(report)

    def test_negative_copy_preserves_import_api_and_real_source(self):
        app = self.root / "app"; app.mkdir()
        entry = app / "tasks.py"
        original = ('from __future__ import annotations\nfrom dataclasses import dataclass\n'
                    '@dataclass\nclass Value:\n number: int = 42\n'
                    'def answer(): return Value().number\nif __name__ == "__main__": print("ORIGINAL")\n')
        entry.write_text(original)
        wrong = exercise.negative_copy("task",app,self.root / "negative")
        result = exercise.observe(sys.executable,wrong / "tasks.py",["add","task"],self.root)
        self.assertEqual(json.loads(result["stdout"]),{"tasks":[]})
        result = subprocess.run([sys.executable,"-B","-c","import tasks; print(tasks.answer())"],
                                cwd=wrong,capture_output=True,text=True)
        self.assertEqual(result.stdout.strip(),"42")
        self.assertEqual(entry.read_text(),original)

    def test_disclosed_fault_and_real_business_error_take_distinct_routes(self):
        # Preserve the business oracle; an incorrect result is still rejected.
        report = {"observations": {"summary":{"argv":[],"exit_code":0,"stdout":"{}","stderr":""}}}
        with self.assertRaises(AssertionError):
            verify.csv_report(report)
        scenario = self.root / "scenario"; scenario.mkdir()
        for injected in (True, False):
            (scenario / "report.json").write_text(json.dumps({"kind":"task", "fault_injected":injected}))
            with patch.object(verify,"task_report",side_effect=AssertionError("bad business result")), \
                    self.assertRaises(verify.CheckFailure) as caught:
                verify.check("task","scenario",self.root,self.root)
            self.assertEqual(caught.exception.verdict["failure_kind"],"ASSERTION")
            self.assertEqual(caught.exception.verdict.get("repair_artifact_ids",[]),[] if injected else ["U-0"])

    def test_same_entrypoint_and_children_in_both_legal_workdirs(self):
        app, harness = self.root / "app", self.root / "harness"
        app.mkdir(); harness.mkdir()
        (app / "test_bound.py").write_text('''import os, subprocess, tempfile, unittest
from pathlib import Path
class TestBinding(unittest.TestCase):
 def test_child(self):
  with tempfile.TemporaryDirectory() as tmp:
   self.assertTrue(Path(tmp).is_relative_to(Path(os.environ["FOUNDRY_TEST_WORKDIR"])))
   subprocess.run([os.environ["BOUND_PYTHON"], "-B", "-c", "print('ok')"], check=True)
''')
        (harness / "check.py").write_text('''import argparse, json, os, subprocess
from pathlib import Path
p=argparse.ArgumentParser()
for flag in ('project','workdir','python'): p.add_argument('--'+flag, required=True)
a=p.parse_args()
assert Path(a.workdir).resolve() == Path(os.environ['FOUNDRY_TEST_WORKDIR']).resolve()
assert a.python == os.environ['BOUND_PYTHON']
subprocess.run([a.python,'-B','-c',"from pathlib import Path; Path('bound-child').write_text('ok')"],cwd=a.workdir,check=True)
print(json.dumps({'status':'CHECKS_PASS'}))
''')
        for work in (app / "scratch", self.root / "scenario"):
            work.mkdir()
            report = exercise.check_environment(str(Path(sys.executable).absolute()), harness, app, work, test_execution)
            verify.environment_report(report, "task")
            self.assertTrue((work / "bound-child").is_file())

    def test_harness_interface_probe_uses_explicit_interpreter_alias(self):
        harness = self.root / "harness"; harness.mkdir()
        for name in ("AGENTS.md","BUILD.md"): (harness / name).write_text("Public fixture")
        (harness / "check.py").write_text('''import argparse
p=argparse.ArgumentParser()
for flag in ('project','workdir','python'): p.add_argument('--'+flag, required=True)
p.parse_args()
''')
        alias = self.root / "bound-python"; alias.symlink_to(sys.executable)
        with patch.object(verify.subprocess,"run",wraps=subprocess.run) as child:
            verify.check("task","harness",self.root,self.root,str(alias))
        self.assertEqual(child.call_args.args[0][0],str(alias))
        with self.assertRaisesRegex(ValueError,"explicit bound Python"):
            verify.check("task","harness",self.root,self.root)

    def test_proposal_is_stateless_portable_and_preserves_business_sources(self):
        inputs = self.root / "inputs"; inputs.mkdir()
        for name in prepare.SOURCES.values():
            (inputs / name).write_text("Public fixture contract.\n")
        runtime = {"source_read_roots": [], "executables": {"python":sys.executable},
                   "codex_executable":"/test-only/codex", "model":"test-model",
                   "allow_model_service":True, "max_attempts":8, "max_task_attempts":3,
                   "command_timeout_seconds":15, "expires_at":"2030-01-01T00:00:00Z"}
        for kind in ("task", "csv"):
            request, scope = prepare.proposal(kind, root=self.root, bundle=ROOT, inputs=inputs,
                                             program_id="TEST-"+kind, runtime=runtime)
            result = compile_build_plan(**request)
            self.assertTrue(result, result)
            tasks = request["plan"]["workpacks"]
            self.assertIn("--test-adapter", tasks[2]["local_argv"])
            self.assertTrue(all(task["verification"][0]["argv"][-1] == "executable://python" for task in tasks))
            self.assertIn("FOUNDRY_TEST_WORKDIR", tasks[1]["goal"])
            self.assertEqual(scope["model"], "test-model")
            self.assertFalse(Path(scope["workspace_root"]).exists())
            self.assertEqual(tasks[2]["artifacts"], [{"artifact_id":"E-0", "path":"scenario/report.json"}])

    def test_preparation_selects_only_case_sources_and_goal_without_changing_write_budget(self):
        inputs = self.root / "inputs"; inputs.mkdir()
        for name in prepare.SOURCES.values():
            (inputs / name).write_text("Public fixture contract.\n")
        runtime = {"source_read_roots": [], "executables": {"python": sys.executable},
                   "codex_executable": "/test-only/codex", "model": "test-model",
                   "allow_model_service": True, "max_attempts": 8, "max_task_attempts": 3,
                   "command_timeout_seconds": 15, "expires_at": "2030-01-01T00:00:00Z"}
        for kind, other in (("task", "CSV"), ("csv", "Task")):
            request, scope = prepare.proposal(kind, root=self.root, bundle=ROOT, inputs=inputs,
                                             program_id="TEST-" + kind, runtime=runtime)
            sources = {row["source_id"] for row in request["requirement_ir"]["sources"]}
            self.assertNotIn("TASK-CLI-PRD" if kind == "csv" else "CSV-PROJECT-BRIEF", sources)
            for task in request["plan"]["workpacks"]:
                self.assertNotIn(other, task["goal"])
                self.assertNotIn("Ledger", task["goal"])
                self.assertNotIn("Config", task["goal"])
                self.assertEqual({row["id"] for row in task["inputs"] if row["kind"] == "SOURCE"}, sources)
            goals = [row["goal"] for row in request["plan"]["workpacks"]]
            self.assertIn("failure_kind", goals[0])
            self.assertIn("app/scratch", goals[0])
            self.assertIn("app/scratch", goals[1])
            self.assertEqual(scope["task_write_roots"], {"H": ["harness"], "U": ["app"], "E": ["scenario"],
                                                       **({"F": ["completion"]} if kind == "task" else {})})
            self.assertEqual(scope["max_attempts"], runtime["max_attempts"])
            self.assertFalse(Path(scope["workspace_root"]).exists())

    def test_probe_real_success_shape_exits_86_before_successor(self):
        script = '''import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from devtools.release_acceptance.recovery_probe import after_observation_runner
root=Path(sys.argv[2])
def native(invocation, before):
 before()
 (root/'durable.json').write_text('{"status":"MODEL_TURN_COMPLETED","exit_code":0}')
 return {"status":"MODEL_TURN_COMPLETED","exit_code":0}
after_observation_runner(native, 'H')({'phase':'IMPLEMENTATION','executor':'CODEX','workpack_id':'H'}, lambda:None)
(root/'successor').write_text('must never occur')
'''
        result = subprocess.run([sys.executable,"-B","-c",script,str(ROOT),str(self.root)],capture_output=True,text=True)
        self.assertEqual(result.returncode, 86, result)
        self.assertTrue((self.root / "durable.json").exists())
        self.assertFalse((self.root / "successor").exists())

    def test_probe_does_not_turn_failure_or_ordinary_completion_into_success(self):
        invocation = {"phase":"IMPLEMENTATION","executor":"CODEX","workpack_id":"H"}
        for status in ("PASS", "MODEL_PROCESS_FAILED", "UNKNOWN_SIDE_EFFECT"):
            result = {"status":status,"exit_code":0}
            run = recovery_probe.after_observation_runner(lambda *_:result,"H",terminate=lambda _:self.fail("unexpected interrupt"))
            self.assertEqual(run(invocation,lambda:None),result)
        class Finished:
            runner = None
            def advance(self, _): return {"status":"TASK_REPAIR_BUDGET_EXHAUSTED"}
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            code = recovery_probe.advance_with_probe(Finished(),"TEST","H")
        self.assertNotEqual(code,0)
        self.assertEqual(json.loads(stream.getvalue())["status"],"TASK_REPAIR_BUDGET_EXHAUSTED")
