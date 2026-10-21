"""Portable startup checks; current Python subprocesses and explicit simulations.

Real unsupported-interpreter probes live in test_python_startup_native so the
required source gate has no dependency on an optional second Python install.
"""

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from harness_foundry_factory import python_startup


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "tools/hffactory.py"
MODULE = "harness_foundry_factory.build_cli"


class PythonStartupTests(unittest.TestCase):

    def run_cli(self, python, argv, *, cwd=None):
        env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run([python, "-S", "-B", *argv], cwd=cwd or ROOT,
                              env=env, text=True, capture_output=True, timeout=30)


    def assert_unsupported(self, result):
        self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
        value = json.loads(result.stdout)
        self.assertEqual(value["error"]["code"], "UNSUPPORTED_PYTHON_VERSION")
        detail = value["error"]["details"]
        self.assertEqual(detail["requires_python"], ">=3.11")
        self.assertLess(tuple(map(int, detail["python_version"].split("."))), (3, 11))
        self.assertTrue(Path(detail["python_executable"]).is_absolute())
        self.assertFalse(value["execution_started"])
        self.assertFalse(value["writes_performed"])
        self.assertFalse(detail["suggested_interpreter_verified"])
        self.assertNotIn("Traceback", result.stderr + result.stdout)
        return value

    def test_correct_source_entry_uses_actual_project_python(self):
        result = self.run_cli(sys.executable, [str(ENTRY), "version", "--json"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["target_protocol_version"], "2.9")

    def test_correct_existing_module_entry(self):
        result = self.run_cli(sys.executable, ["-m", MODULE, "version", "--json"], cwd=ROOT / "src")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "PASS")

    def test_correct_console_entry_main(self):
        code = "from harness_foundry_factory.entrypoint import main;raise SystemExit(main(['version','--json']))"
        result = self.run_cli(sys.executable, ["-c", code], cwd=ROOT / "src")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "PASS")




    def test_simulated_low_version_console_stops_before_core_import(self):
        # Portable deterministic coverage; actual old-Python proof is separate.
        code = """import importlib.abc,sys
class BlockCore(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname in ('harness_foundry_factory.build_cli','harness_foundry_factory.cli'):
            raise AssertionError('core imported before Python diagnosis')
sys.meta_path.insert(0,BlockCore())
sys.version_info=(3,10,16)
from harness_foundry_factory.entrypoint import main
raise SystemExit(main(['version','--json']))
"""
        self.assert_unsupported(self.run_cli(sys.executable, ["-c", code], cwd=ROOT / "src"))

    def test_simulated_low_version_module_stops_before_core_types_import(self):
        code = """import importlib.abc,runpy,sys
class BlockCore(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname=='harness_foundry_factory.build_types':
            raise AssertionError('core imported before Python diagnosis')
sys.meta_path.insert(0,BlockCore())
sys.version_info=(3,10,16)
sys.argv=['harness_foundry_factory.build_cli','version','--json']
runpy.run_module('harness_foundry_factory.build_cli',run_name='__main__')
"""
        self.assert_unsupported(self.run_cli(sys.executable, ["-c", code], cwd=ROOT / "src"))

    def source_bundle(self, root):
        spec = importlib.util.spec_from_file_location("startup_generic_packager", ROOT / "devtools/package_generic_release.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        files = module.collect_files(ROOT)
        for name, raw in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        return root / "tools/hffactory.py"

    def test_relocated_current_source_template_and_module_correct_python(self):
        with tempfile.TemporaryDirectory(prefix="foundry python 中文 ") as directory:
            root = Path(directory)
            entry = self.source_bundle(root)
            self.assertTrue((root / "src/harness_foundry_factory/python_startup.py").is_file())
            for argv, cwd in (([str(entry), "version", "--json"], root),
                              (["-m", MODULE, "version", "--json"], root / "src")):
                result = self.run_cli(sys.executable, argv, cwd=cwd)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["status"], "PASS")


    def test_supported_minimum_and_newer_do_not_change_environment_or_spawn(self):
        before = dict(os.environ)
        with patch("subprocess.Popen", side_effect=AssertionError("diagnostic must not dispatch")):
            for version in ((3, 11, 0), (3, 14, 0)):
                with patch.object(python_startup.sys, "version_info", version):
                    self.assertIsNone(python_startup.require_supported_python(["version"]))
        self.assertEqual(dict(os.environ), before)

    def test_diagnostic_preserves_venv_call_path_and_does_not_dispatch(self):
        output, errors = StringIO(), StringIO()
        call_path = "/declared environment/.venv/bin/python"
        with patch.object(python_startup.sys, "version_info", (3, 10, 16)), \
                patch.object(python_startup.sys, "executable", call_path), \
                patch("subprocess.Popen", side_effect=AssertionError("diagnostic must not dispatch")), \
                redirect_stdout(output), redirect_stderr(errors), self.assertRaises(SystemExit):
            python_startup.require_supported_python(["version", "--json"], launcher=str(ENTRY))
        self.assertEqual(json.loads(output.getvalue())["error"]["details"]["python_executable"], call_path)
        self.assertEqual(errors.getvalue(), "")


class BoundPythonContinuationTests(unittest.TestCase):
    def test_existing_one_attempt_continuation_keeps_declared_python_alias(self):
        # Reuse the existing synthetic controller fixture; no real model or
        # historical Program is created, resumed or changed.
        import test_build_runtime as support
        fixture = support.BuildRuntimeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        alias = fixture.root / "declared python"
        alias.symlink_to(sys.executable)
        fixture.scope["executables"]["python"] = str(alias)
        for task in fixture.plan["workpacks"]:
            task["local_argv"] += ["executable://python"]
            for check in task["verification"]:
                check["argv"] += ["--python-executable", "executable://python"]
        fixture.prepare()
        first = fixture.controller().advance(fixture.prepared_id, advance_mode="ONE_ATTEMPT")
        self.assertEqual(first["status"], "BUILD_CONTROL_RETURNED")
        first_calls = len(fixture.runner.invocations)
        second = fixture.controller().advance(fixture.prepared_id, advance_mode="ONE_ATTEMPT")
        self.assertIn(second["status"], {"BUILD_CONTROL_RETURNED", "PLAN_CHECKS_ACCEPTED"})
        self.assertGreater(len(fixture.runner.invocations), first_calls)
        for invocation in fixture.runner.invocations:
            self.assertEqual(invocation["argv"][0], str(alias))
            self.assertEqual(invocation["argv"][-1], str(alias))
            context = json.loads(invocation["prompt"].split("\n", 1)[1])
            self.assertEqual(context["task"]["tool_bindings"]["python"], str(alias))
        before = len(fixture.runner.invocations)
        self.assertEqual(fixture.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(fixture.runner.invocations), before)


if __name__ == "__main__":
    unittest.main()
