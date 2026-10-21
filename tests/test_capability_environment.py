"""Static local binding checks; no selected tool, sandbox or business is run."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "examples/capability-adapters/environment.py"
spec = importlib.util.spec_from_file_location("capability_environment", ENTRY)
environment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(environment)


class CapabilityEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="foundry-environment-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.tool = self.root / "bin" / "selected-tool"
        self.tool.parent.mkdir()
        self.tool.write_text("#!/bin/sh\ntouch 'must-not-be-executed'\n", encoding="utf-8")
        self.tool.chmod(0o755)

    def resolve(self, requirements=None, bindings=None, root=None):
        return environment.resolve_environment(
            requirements if requirements is not None else [{"id": "tool", "kind": "executable"}],
            bindings if bindings is not None else {"tool": {"path": "./bin/selected-tool"}},
            project_root=self.root if root is None else root)

    def codes(self, result):
        return {row["code"] for row in result["diagnostics"]}

    def test_only_selected_dependencies_are_resolved_without_execution_or_mutation(self):
        requirements = [{"id": "tool", "kind": "executable"}, {"id": "input", "kind": "file"}]
        source = self.root / "data.txt"
        source.write_text("project input", encoding="utf-8")
        bindings = {"tool": {"path": str(self.tool), "observed_version": "1.2"},
                    "input": {"path": "data.txt"}, "unselected": {"path": "/missing", "secret": "ignored"}}
        before = deepcopy((requirements, bindings))
        files = sorted(self.root.rglob("*"))
        with patch("subprocess.run", side_effect=AssertionError("dependency must not run")):
            result = self.resolve(requirements, bindings)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(set(result["bindings"]), {"tool", "input"})
        self.assertNotIn("ignored", json.dumps(result))
        self.assertEqual(result["scope_fragment"], {"executables": {"tool": str(self.tool)},
                                                   "source_read_roots": [str(source)]})
        self.assertEqual((requirements, bindings), before)
        self.assertEqual(sorted(self.root.rglob("*")), files)
        self.assertFalse(result["probes_executed"])
        self.assertFalse(result["receiver_verified"])

    def test_relative_path_uses_explicit_project_root(self):
        with patch("os.getcwd", return_value="/"):
            result = self.resolve()
        self.assertEqual(result["scope_fragment"]["executables"]["tool"], str(self.tool))

    def test_selected_path_name_and_relative_path_entries_use_project_root(self):
        with patch.dict(os.environ, {"PATH": "bin"}):
            result = self.resolve(bindings={"tool": {"path": "selected-tool"}})
        self.assertEqual(result["bindings"]["tool"]["resolution"], "PATH_NAME")
        self.assertEqual(result["scope_fragment"]["executables"]["tool"], str(self.tool))

    def test_missing_path_name_has_specific_diagnostic(self):
        with patch.dict(os.environ, {"PATH": str(self.root / "absent")}):
            result = self.resolve(bindings={"tool": {"path": "selected-tool"}})
        self.assertIn("EXECUTABLE_NOT_FOUND", self.codes(result))
        self.assertEqual(result["scope_fragment"]["executables"], {})

    def test_executable_alias_is_preserved_for_venv_semantics(self):
        alias = self.root / "venv" / "bin" / "python"
        alias.parent.mkdir(parents=True)
        alias.symlink_to(self.tool)
        result = self.resolve(bindings={"tool": {"path": str(alias)}})
        self.assertEqual(result["scope_fragment"]["executables"]["tool"], str(alias))
        self.assertEqual(result["bindings"]["tool"]["resolved_path"], str(self.tool))
        self.assertTrue(alias.is_symlink())

    def test_parent_reference_after_directory_alias_preserves_filesystem_meaning(self):
        actual = self.root / "external" / "sdk"
        actual.mkdir(parents=True)
        (self.root / "sdk-alias").symlink_to(actual, target_is_directory=True)
        tool = actual.parent / "compiler"
        tool.write_text("#!/bin/sh\nexit 9\n", encoding="utf-8")
        tool.chmod(0o755)
        result = self.resolve(bindings={"tool": {"path": "sdk-alias/../compiler"}})
        self.assertEqual(result["scope_fragment"]["executables"]["tool"], str(tool))

    def test_normal_framework_links_are_read_dependencies_not_copied_or_executed(self):
        versions = self.root / "QtCore.framework" / "Versions"
        actual = versions / "A"
        actual.mkdir(parents=True)
        (versions / "Current").symlink_to("A", target_is_directory=True)
        bindings = {"sdk": {"path": "QtCore.framework/Versions/Current", "observed_version": "6.11.1"}}
        result = self.resolve([{"id": "sdk", "kind": "directory", "version_min": "6.11"}], bindings)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["scope_fragment"]["source_read_roots"], [str(actual)])
        self.assertEqual(result["bindings"]["sdk"]["version_source"], "SUPPLIED_BINDING")
        self.assertFalse(result["bindings"]["sdk"]["receiver_verified"])
        self.assertTrue((versions / "Current").is_symlink())

    def test_missing_and_broken_paths_do_not_enter_scope(self):
        (self.root / "broken").symlink_to("absent")
        for path, code in (("missing/file", "PATH_MISSING"), ("./broken", "BROKEN_SYMLINK"),
                           ("broken/file", "BROKEN_SYMLINK")):
            with self.subTest(path=path):
                result = self.resolve(bindings={"tool": {"path": path}})
                self.assertEqual(result["status"], "INCOMPLETE")
                self.assertIn(code, self.codes(result))
                self.assertEqual(result["scope_fragment"]["executables"], {})

    def test_symlink_cycle_is_a_diagnostic(self):
        (self.root / "cycle").symlink_to("cycle")
        result = self.resolve(bindings={"tool": {"path": "./cycle"}})
        self.assertIn("PATH_UNRESOLVABLE", self.codes(result))

    def test_wrong_kind_and_missing_execute_permission(self):
        self.tool.chmod(0o644)
        result = self.resolve()
        self.assertIn("NOT_EXECUTABLE", self.codes(result))
        self.assertEqual(result["scope_fragment"]["executables"], {})
        for kind, path in (("executable", "."), ("directory", str(self.tool)), ("file", ".")):
            with self.subTest(kind=kind):
                result = self.resolve([{"id": "tool", "kind": kind}], {"tool": {"path": path}})
                self.assertIn("PATH_KIND_MISMATCH", self.codes(result))

    def test_unreadable_declared_file_is_not_a_read_root(self):
        with patch.object(environment.os, "access", return_value=False):
            result = self.resolve([{"id": "tool", "kind": "file"}])
        self.assertIn("NOT_READABLE", self.codes(result))
        self.assertEqual(result["scope_fragment"]["source_read_roots"], [])

    def test_numeric_versions_have_inclusive_minimum_and_exclusive_maximum(self):
        requirement = [{"id": "tool", "kind": "executable", "version_min": "6.11", "version_max_exclusive": "6.12"}]
        for version, expected in (("6.11", "READY"), ("6.11.0", "READY"), ("6.11.23", "READY"),
                                  ("6.12", "INCOMPLETE"), ("6.12.0", "INCOMPLETE"), ("6.9.99", "INCOMPLETE")):
            with self.subTest(version=version):
                result = self.resolve(requirement, {"tool": {"path": str(self.tool), "observed_version": version}})
                self.assertEqual(result["status"], expected)
                if expected != "READY":
                    self.assertIn("VERSION_INCOMPATIBLE", self.codes(result))

    def test_pre_release_and_vendor_versions_are_not_treated_as_final_numeric_versions(self):
        requirement = [{"id": "tool", "kind": "executable", "version_min": "6.12"}]
        for version in ("6.12.0-rc1", "6.12.0rc1", "6.12.0.dev0", "Qt 6.12.0", "6.12.0+vendor"):
            with self.subTest(version=version):
                binding = {"tool": {"path": str(self.tool), "observed_version": version}}
                result = self.resolve(requirement, binding)
                self.assertEqual(result["status"], "INCOMPLETE")
                self.assertIn("VERSION_NOT_COMPARABLE", self.codes(result))
                self.assertEqual(result["scope_fragment"]["executables"], {})
                self.assertEqual(self.resolve(bindings=binding)["status"], "READY")

    def test_unknown_version_blocks_only_a_declared_version_requirement(self):
        result = self.resolve()
        self.assertEqual(result["status"], "READY")
        self.assertIn("VERSION_UNKNOWN", self.codes(result))
        result = self.resolve([{"id": "tool", "kind": "executable", "version_min": "1"}])
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertEqual(result["scope_fragment"]["executables"], {})

    def test_invalid_numeric_range_is_not_silently_ignored(self):
        for bounds in ({"version_min": "1rc1"}, {"version_min": 1},
                       {"version_min": "2", "version_max_exclusive": "1"},
                       {"version_min": "1.0", "version_max_exclusive": "1"}):
            with self.subTest(bounds=bounds):
                result = self.resolve([{"id": "tool", "kind": "executable", **bounds}])
                self.assertIn("INVALID_VERSION_RANGE", self.codes(result))
                self.assertEqual(result["status"], "INCOMPLETE")

    def test_missing_conflicting_or_malformed_selected_bindings_report_errors(self):
        for requirements, bindings, code in (
            ([{"id": "tool", "kind": "executable"}], {}, "BINDING_MISSING"),
            ([{"id": "tool", "kind": "executable"}] * 2, {}, "DUPLICATE_REQUIREMENT"),
            ([{"id": "tool", "kind": "unknown"}], {}, "INVALID_REQUIREMENT"),
            ([None], {}, "INVALID_REQUIREMENT"),
            ([{"id": "tool", "kind": "executable", "version_mix": "2"}], {}, "INVALID_REQUIREMENT"),
            ([{"id": "tool", "kind": "executable"}], {"tool": {"path": "\x00"}}, "INVALID_PATH"),
            ([{"id": "tool", "kind": "executable"}], {"tool": {"path": str(self.tool), "observed_version": True}}, "INVALID_VERSION_REPORT"),
        ):
            with self.subTest(code=code):
                result = self.resolve(requirements, bindings)
                self.assertEqual(result["status"], "INCOMPLETE")
                self.assertIn(code, self.codes(result))
                self.assertEqual(result["scope_fragment"]["executables"], {})

    def test_project_root_must_be_explicit_existing_directory(self):
        for root in (".", self.root / "missing", self.tool):
            with self.subTest(root=root):
                result = self.resolve(root=root)
                self.assertIn("PROJECT_ROOT_INVALID", self.codes(result))

    def test_cli_outputs_only_materials_and_does_not_run_the_selected_tool(self):
        required = self.root / "requirements.json"
        bindings = self.root / "bindings.json"
        required.write_text(json.dumps([{"id": "tool", "kind": "executable"}]), encoding="utf-8")
        bindings.write_text(json.dumps({"tool": {"path": str(self.tool)}}), encoding="utf-8")
        result = subprocess.run([sys.executable, "-I", "-B", str(ENTRY), "--requirements", str(required),
                                 "--bindings", str(bindings), "--project-root", str(self.root)],
                                cwd=self.root, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "READY")
        self.assertFalse((self.root / "must-not-be-executed").exists())
        required.write_text("invalid JSON", encoding="utf-8")
        failed = subprocess.run(result.args, cwd=self.root, capture_output=True, text=True, timeout=15)
        self.assertEqual(failed.returncode, 1)
        self.assertIn("INPUT_UNREADABLE", {row["code"] for row in json.loads(failed.stdout)["diagnostics"]})
        self.assertNotIn("Traceback", failed.stderr)


if __name__ == "__main__":
    unittest.main()
