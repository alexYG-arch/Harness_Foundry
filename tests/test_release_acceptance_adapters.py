"""Source-owned acceptance adapters: synthetic fixtures, no real model approval."""
import contextlib
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
