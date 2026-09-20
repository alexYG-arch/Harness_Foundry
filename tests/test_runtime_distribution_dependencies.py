"""Shared-module extraction must not break existing portable runtime producers."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from harness_foundry_factory.compiler import _write_epoch4_runtime_store_dependency_closure
from harness_foundry_factory.validator import _check_portable_runtime_dependency_closure


class RuntimeDistributionDependenciesTests(unittest.TestCase):
    def test_retained_control_and_coding_bundles_are_closed_and_relocated_importable(self):
        for coding in (False, True):
            with self.subTest(coding=coding), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                _write_epoch4_runtime_store_dependency_closure(root, include_workpack_runtime=coding,
                                                               include_package_validation_runtime=coding)
                inventory = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}
                self.assertEqual(_check_portable_runtime_dependency_closure(root, inventory), [])
                names = ["store", "models", "constants", "control_kernel"]
                if coding:
                    names += ["coding_protocol", "coding_process", "coding_runtime", "workpack_runtime"]
                program = (f"import sys, importlib; sys.path.insert(0, {str(root / 'tools')!r}); "
                           f"[importlib.import_module('harness_foundry_runtime.' + name) for name in {names!r}]")
                result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", program],
                                        cwd=root, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                # Removing a new direct dependency still fails the independent
                # validator; this repair did not weaken missing-module handling.
                (root / "tools/harness_foundry_runtime/build_types.py").unlink()
                findings = _check_portable_runtime_dependency_closure(root, inventory)
                self.assertIn("PORTABLE_RUNTIME_DEPENDENCY_MISSING", {row["code"] for row in findings})


if __name__ == "__main__":
    unittest.main()
