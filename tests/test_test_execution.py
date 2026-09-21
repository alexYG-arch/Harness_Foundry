"""Synthetic subprocess evidence; no model or historical target invocation."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from harness_foundry_factory.test_execution import run_tests, execution_paths
from harness_foundry_factory.build_runtime import classify_verification_result


class TestExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "app"
        self.project.mkdir()

    def run_fixture(self, body, *, inside=False):
        (self.project / "test_subject.py").write_text(body)
        work = (self.project if inside else self.root) / "scratch"
        work.mkdir(exist_ok=True)
        return run_tests(self.project, work, Path(sys.executable).absolute())

    def test_same_tests_accept_both_stage_paths_and_explicit_interpreter(self):
        body = '''import os, subprocess, tempfile, unittest
from pathlib import Path
class Subject(unittest.TestCase):
 def test_bound_child(self):
  with tempfile.TemporaryDirectory() as p:
   self.assertTrue(Path(p).is_relative_to(Path(os.environ["FOUNDRY_TEST_WORKDIR"])))
   subprocess.run([os.environ["BOUND_PYTHON"], "-B", "-c",
       "from pathlib import Path; Path('child.txt').write_text('ok')"], cwd=p, check=True)
'''
        for inside in (True, False):
            with self.subTest(inside=inside):
                result = self.run_fixture(body, inside=inside)
                self.assertEqual(result["status"], "CHECKS_PASS", result)
                self.assertTrue(result["protected_source_unchanged"])

    def test_unexpected_setup_error_stays_typed_and_is_not_automatic_business_repair(self):
        result = self.run_fixture('''import unittest
class Subject(unittest.TestCase):
 def setUp(self): raise PermissionError("test fixture permission failure")
 def test_one(self): pass
''')
        self.assertEqual(result["failure_kind"], "INFRASTRUCTURE")
        self.assertEqual(result["errors"][0]["exception_type"], "PermissionError")
        self.assertEqual(result["errors"][0]["phase"], "setUp")
        raw = {"status":"VALIDATION_FAILED", "exit_code":1, "stdout":json.dumps(result)}
        self.assertFalse(classify_verification_result(raw)["automatic_retry_allowed"])

    def test_real_assertion_is_rejected_but_expected_exception_is_success(self):
        bad = self.run_fixture('''import unittest
class Subject(unittest.TestCase):
 def test_wrong(self): self.assertEqual(1, 2)
''')
        self.assertEqual(bad["failure_kind"], "ASSERTION")
        good = self.run_fixture('''import unittest
class Subject(unittest.TestCase):
 def test_expected(self):
  with self.assertRaises(PermissionError): raise PermissionError("expected")
''')
        self.assertEqual(good["status"], "CHECKS_PASS")

    def test_mutable_subtree_does_not_hide_source_mutation(self):
        result = self.run_fixture('''import unittest
from pathlib import Path
class Subject(unittest.TestCase):
 def test_bad(self): Path(__file__).with_name("unexpected.py").write_text("changed")
''', inside=True)
        self.assertEqual(result["phase"], "SOURCE_PROTECTION")
        self.assertEqual(result["failure_kind"], "ASSERTION")

    def test_empty_suite_never_passes(self):
        result = self.run_fixture("# no tests\n")
        self.assertEqual(result["failure_kind"], "INFRASTRUCTURE")
        self.assertEqual(result["tests_run"], 0)

    def test_project_itself_is_not_a_scratch_exclusion(self):
        with self.assertRaises(ValueError):
            execution_paths(self.project, self.project, sys.executable)

    def test_subtest_error_retains_exception_details(self):
        result = self.run_fixture('''import unittest
class Subject(unittest.TestCase):
 def test_subtest(self):
  with self.subTest(item=1): raise PermissionError("unexpected")
''')
        self.assertEqual(result["failure_kind"], "INFRASTRUCTURE")
        self.assertEqual(result["errors"][0]["exception_type"], "PermissionError")
