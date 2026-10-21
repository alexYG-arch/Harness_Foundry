"""Optional actual old-Python entry checks, never simulated as native PASS.

Full discovery includes this module. The required portable source gate does not;
when no usable unsupported interpreter exists, retain an explicit SKIP reason.
"""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import test_python_startup as support

ENTRY, MODULE, ROOT = support.ENTRY, support.MODULE, support.ROOT


class OldPythonStartupTests(unittest.TestCase):
    # Share only fixtures/helpers, not test-case inheritance or duplicate runs.
    run_cli = support.PythonStartupTests.run_cli
    source_bundle = support.PythonStartupTests.source_bundle
    assert_unsupported = support.PythonStartupTests.assert_unsupported

    @classmethod
    def setUpClass(cls):
        cls.old_python = None
        candidate = Path("/usr/bin/python3")
        cls.old_reason = "optional old-Python candidate is absent: " + str(candidate)
        try:
            if not candidate.is_file():
                return
            probe = subprocess.run([str(candidate), "-I", "-S", "-B", "-c",
                                    "import json,sys;print(json.dumps(list(sys.version_info[:3])))"],
                                   text=True, capture_output=True, timeout=15)
            if probe.returncode != 0:
                cls.old_reason = "optional old-Python probe exited with code " + str(probe.returncode)
                return
            value = json.loads(probe.stdout)
            if not isinstance(value, list) or len(value) != 3 or not all(isinstance(x, int) for x in value):
                raise ValueError("invalid version record")
            if tuple(value) >= (3, 11):
                cls.old_reason = "optional system interpreter is not older than Python 3.11: " + ".".join(map(str, value))
                return
            cls.old_python = str(candidate)
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError) as exc:
            cls.old_reason = "optional old-Python probe unavailable (" + type(exc).__name__ + "): " + str(candidate)

    def old(self):
        if self.old_python is None:
            self.skipTest(self.old_reason)
        return self.old_python

    def test_wrong_source_entry_reports_actual_interpreter_and_restart(self):
        value = self.assert_unsupported(self.run_cli(self.old(), [str(ENTRY), "version", "--json"]))
        argv = value["error"]["details"]["suggested_argv"]
        self.assertEqual(argv[2:], [str(ENTRY), "version", "--json"])
        self.assertEqual(argv[0], str(ROOT / ".venv/bin/python") if (ROOT / ".venv/bin/python").is_file()
                         else "<configured-python-3.11-or-newer>")


    def test_wrong_source_human_error_is_actionable(self):
        result = self.run_cli(self.old(), [str(ENTRY), "--help"])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("Python >=3.11", result.stderr)
        self.assertIn("--help", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


    def test_wrong_existing_module_entry_preserves_module_launch(self):
        value = self.assert_unsupported(self.run_cli(self.old(), ["-m", MODULE, "version", "--json"], cwd=ROOT / "src"))
        self.assertEqual(value["error"]["details"]["suggested_argv"][2:4], ["-m", MODULE])


    def test_wrong_console_entry_main_checks_before_core_import(self):
        code = """import importlib.abc,sys
class BlockCore(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname in ('harness_foundry_factory.build_cli','harness_foundry_factory.cli'):
            raise AssertionError('core imported before Python diagnosis')
sys.meta_path.insert(0,BlockCore())
from harness_foundry_factory.entrypoint import main
raise SystemExit(main(['version','--json']))
"""
        self.assert_unsupported(self.run_cli(self.old(), ["-c", code], cwd=ROOT / "src"))


    def test_wrong_module_checks_before_core_types_import(self):
        code = """import importlib.abc,runpy,sys
class BlockCore(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname=='harness_foundry_factory.build_types':
            raise AssertionError('core imported before Python diagnosis')
sys.meta_path.insert(0,BlockCore())
sys.argv=['harness_foundry_factory.build_cli','version','--json']
runpy.run_module('harness_foundry_factory.build_cli',run_name='__main__')
"""
        self.assert_unsupported(self.run_cli(self.old(), ["-c", code], cwd=ROOT / "src"))


    def test_relocated_current_source_template_wrong_python(self):
        old = self.old()
        with tempfile.TemporaryDirectory(prefix="foundry old python 中文 ") as directory:
            root = Path(directory)
            entry = self.source_bundle(root)
            value = self.assert_unsupported(self.run_cli(old, [str(entry), "version", "--json"], cwd=root))
            self.assertEqual(value["error"]["details"]["suggested_argv"][0], "<configured-python-3.11-or-newer>")



if __name__ == "__main__":
    unittest.main()
