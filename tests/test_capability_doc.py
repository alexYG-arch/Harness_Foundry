"""DOC package engineering fixtures; not real WCT/new-session acceptance."""

import json
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

from harness_foundry_factory.verification_resources import validate_structured_result


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "examples/capability-adapters/packages/doc-export/1"
EXPECTED = "# 我的报告\n\n## 下一步\n\n- 核对来源。 (high) [s2]\n\n## 要点\n\n- 新材料来自第二轮。 (normal) [s1]\n\n## Sources\n\n- [s1] 第二轮材料 — source://new-01\n- [s2] 核对规则 — source://rule-02\n"


class CapabilityDocTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="capability-doc-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.package = self.root / "delivery"
        shutil.copytree(PACKAGE, self.package)
        self.tool = self.package / "export_doc.py"
        self.config = self.root / "config.json"
        self.notes = self.root / "notes.json"
        self.sources = self.root / "sources.json"
        self.expected = self.root / "expected.md"
        self.output = self.root / "output.md"
        self.report = self.root / "report.json"
        self.scratch = self.root / "scratch"
        self.scratch.mkdir()
        self.save(self.config, {"title": "我的报告", "sections": [{"id": "next", "title": "下一步"}, {"id": "summary", "title": "要点"}], "include_source_titles": True, "show_priority": True})
        self.save(self.notes, [{"section": "summary", "text": "新材料来自第二轮。", "source": "s1", "priority": "normal"}, {"section": "next", "text": "核对来源。", "source": "s2", "priority": "high"}])
        self.save(self.sources, [{"id": "s2", "title": "核对规则", "locator": "source://rule-02"}, {"id": "s1", "title": "第二轮材料", "locator": "source://new-01"}])
        self.expected.write_text(EXPECTED, encoding="utf-8")

    def save(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def arguments(self):
        return ["--config", str(self.config), "--notes", str(self.notes), "--sources", str(self.sources)]

    def run_tool(self, output=None):
        return subprocess.run([sys.executable, "-I", "-B", str(self.tool), *self.arguments(), "--output", str(output or self.output)], cwd=self.root, capture_output=True, text=True, timeout=10)

    def run_check(self, checker=None, expected=None, environment=None, timeout="5"):
        env = {key: value for key, value in os.environ.items() if not key.startswith("FOUNDRY_")}
        env.update(FOUNDRY_SCRATCH_DIR=str(self.scratch), FOUNDRY_CASE_ID="DOC-TEST", FOUNDRY_COMMAND_ID="doc-command")
        env.update(environment or {})
        completed = subprocess.run([sys.executable, "-I", "-B", str(checker or self.package / "check_doc.py"), "--tool", str(self.tool), *self.arguments(), "--expected", str(expected or self.expected), "--report", str(self.report), "--timeout", timeout], cwd=self.root, env=env, capture_output=True, text=True, timeout=10)
        report = json.loads(self.report.read_text()) if self.report.exists() else None
        return completed, report

    def fake_tool(self, source):
        self.tool.write_text(source, encoding="utf-8")

    def test_delivered_export_preserves_inputs_and_package_without_foundry(self):
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.read_text(), EXPECTED)
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_second_input_and_project_customization_are_parameters(self):
        self.save(self.config, {"title": "另一种报告", "sections": [{"id": "decision", "title": "决策"}]})
        self.save(self.notes, [{"section": "decision", "text": "保留旧证据。", "source": "new"}])
        self.save(self.sources, [{"id": "new", "title": "新规则", "locator": "project://new-rule"}])
        self.expected.write_text("# 另一种报告\n## 决策\n- 保留旧证据。 [new]\n## Sources\n- [new] project://new-rule\n")
        completed, report = self.run_check()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(report["status"], "CHECKS_PASS")

    def test_unknown_references_and_duplicate_ids_do_not_silently_drop_notes(self):
        original = {path: path.read_bytes() for path in (self.config, self.notes, self.sources)}
        mutations = [(self.notes, [{"section": "missing", "text": "fact", "source": "s1", "priority": "high"}]), (self.notes, [{"section": "next", "text": "fact", "source": "missing", "priority": "high"}]), (self.config, {"title": "A", "sections": [{"id": "a", "title": "A"}, {"id": "a", "title": "B"}]}), (self.sources, [{"id": "s1", "title": "A", "locator": "a"}, {"id": "s1", "title": "B", "locator": "b"}])]
        for path, value in mutations:
            with self.subTest(path=path.name, value=value):
                for item, content in original.items():
                    item.write_bytes(content)
                self.save(path, value)
                self.assertNotEqual(self.run_tool().returncode, 0)
                self.assertFalse(self.output.exists())

    def test_existing_output_and_input_cannot_be_overwritten(self):
        for path in (self.output, self.config):
            with self.subTest(path=path.name):
                if path == self.output:
                    path.write_text("old accepted output")
                before = path.read_bytes()
                self.assertNotEqual(self.run_tool(path).returncode, 0)
                self.assertEqual(path.read_bytes(), before)

    def test_actual_cli_runs_once_and_owned_scratch_is_cleaned(self):
        marker = self.root / "calls.txt"
        original = self.tool.read_text()
        self.tool.write_text("from pathlib import Path\nwith Path(" + repr(str(marker)) + ").open('a') as stream: stream.write('called\\n')\n" + original)
        completed, report = self.run_check()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(marker.read_text().splitlines(), ["called"])
        self.assertEqual(list(self.scratch.iterdir()), [])
        self.assertEqual(report["execution"]["invocation_attempts"], 1)
        self.assertEqual(report["execution"]["returncode"], 0)
        self.assertEqual(report["actual_export"], EXPECTED)
        self.assertEqual(report["execution"]["argv"][1:4], ["-I", "-B", "-c"])
        self.assertNotIn(str(self.expected), report["execution"]["tool_argv"])

    def test_correct_render_function_does_not_hide_wrong_cli(self):
        self.fake_tool("from pathlib import Path\nimport sys\ndef render(): return " + repr(EXPECTED) + "\nPath(sys.argv[sys.argv.index('--output')+1]).write_text('# wrong CLI\\n')\n")
        _, report = self.run_check()
        self.assertEqual(report["failure_kind"], "ASSERTION")

    def test_full_oracle_rejects_extra_fact_repetition_reference_and_preamble(self):
        variants = [EXPECTED.replace("## 下一步", "unexpected fact\n## 下一步"), EXPECTED.replace("- 核对来源。 (high) [s2]", "- 核对来源。 (high) [s2]\n- 核对来源。 (high) [s2]"), EXPECTED.replace("(high) [s2]", "(high) [s1]"), EXPECTED + "extra fact\n"]
        for index, actual in enumerate(variants):
            with self.subTest(index=index):
                self.fake_tool("from pathlib import Path\nimport sys\nPath(sys.argv[sys.argv.index('--output')+1]).write_text(" + repr(actual) + ", encoding='utf-8')\n")
                self.report = self.root / (str(index) + ".json")
                _, report = self.run_check()
                self.assertEqual(report["failure_kind"], "ASSERTION")

    def test_only_blank_lines_are_ignored(self):
        self.expected.write_text(EXPECTED.replace("\n\n", "\n \n\n"), encoding="utf-8")
        self.assertEqual(self.run_check()[1]["status"], "CHECKS_PASS")
        self.report = self.root / "changed-space.json"
        self.expected.write_text(EXPECTED.replace("核对来源。", " 核对来源。"), encoding="utf-8")
        self.assertEqual(self.run_check()[1]["failure_kind"], "ASSERTION")

    def test_resource_checker_uses_protected_expectation_and_no_hidden_import(self):
        verifier = self.root / "verifier"
        verifier.mkdir()
        protected = verifier / "check_doc.py"
        shutil.copy2(self.package / "check_doc.py", protected)
        expectation = verifier / "expected.md"
        expectation.write_text(EXPECTED)
        self.expected.write_text("wrong unprotected expectation")
        completed, report = self.run_check(protected, expectation, {"FOUNDRY_VERIFIER_ROOT": str(verifier)})
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(report["status"], "CHECKS_PASS")
        self.report = self.root / "outside.json"
        _, report = self.run_check(protected, self.expected, {"FOUNDRY_VERIFIER_ROOT": str(verifier)})
        self.assertEqual(report["checks"][0]["status"], "ERROR")
        self.assertNotIn("execution", report)

    def test_missing_or_malformed_product_inputs_are_assertion(self):
        self.notes.unlink()
        self.assertEqual(self.run_check()[1]["failure_kind"], "ASSERTION")
        self.notes.write_text("invalid json")
        self.report = self.root / "malformed.json"
        self.assertEqual(self.run_check()[1]["failure_kind"], "ASSERTION")

    def test_no_space_and_scratch_faults_are_error(self):
        self.fake_tool("import errno\nraise OSError(errno.ENOSPC, 'synthetic disk full', " + repr(str(self.notes)) + ")\n")
        _, report = self.run_check()
        self.assertEqual(report["checks"][0]["status"], "ERROR")
        self.assertNotIn("failure_kind", report)
        self.report = self.root / "scratch.json"
        _, report = self.run_check(environment={"FOUNDRY_SCRATCH_DIR": str(self.root / "absent-scratch")})
        self.assertEqual(report["checks"][0]["status"], "ERROR")

    def test_process_timeout_is_error_and_does_not_replay(self):
        marker = self.root / "calls.txt"
        self.fake_tool("from pathlib import Path\nimport time\nwith Path(" + repr(str(marker)) + ").open('a') as stream: stream.write('called\\n')\ntime.sleep(5)\n")
        _, report = self.run_check(timeout="0.5")
        self.assertEqual(report["checks"][0]["status"], "ERROR")
        self.assertEqual(marker.read_text().splitlines(), ["called"])
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_process_start_failure_is_error(self):
        spec = importlib.util.spec_from_file_location("delivered_doc_checker", self.package / "check_doc.py")
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        args = SimpleNamespace(tool=self.tool, config=self.config, notes=self.notes,
                               sources=self.sources, expected=self.expected, timeout=5)
        with mock.patch.dict(os.environ, {key: value for key, value in os.environ.items() if not key.startswith("FOUNDRY_")}, clear=True), mock.patch.object(checker.subprocess, "run", side_effect=FileNotFoundError("synthetic Python launch failure")):
            report = checker.check(args)
        self.assertEqual(report["checks"][0]["status"], "ERROR")
        self.assertNotIn("failure_kind", report)

    def test_missing_output_is_assertion_not_function_inspection(self):
        self.fake_tool("print('PASS')\n")
        _, report = self.run_check()
        self.assertEqual(report["failure_kind"], "ASSERTION")

    def test_structured_report_keeps_case_and_command_binding_and_old_report(self):
        _, report = self.run_check()
        self.assertEqual(report["case_id"], "DOC-TEST")
        self.assertEqual(report["command_id"], "doc-command")
        binding = {"case_id": "DOC-TEST", "command_id": "doc-command", "network": {"mode": "NONE"}, "required_checks": ["document-export"]}
        checked = validate_structured_result(report, binding, 0)
        self.assertEqual(checked["status"], "PASS", checked)
        before = self.report.read_bytes()
        marker = self.root / "must-not-run.txt"
        self.fake_tool("from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('replayed')\n")
        completed, _ = self.run_check()
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(self.report.read_bytes(), before)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
