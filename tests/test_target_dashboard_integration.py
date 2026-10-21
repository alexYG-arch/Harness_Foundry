"""WP08 isolated integration evidence, not real project or browser acceptance.

Native DATA/DOC commands run once on new engineering inputs. The observer then
reads their existing reports; component upgrade uses the existing ordinary-file
C/G/N helpers and never asks a business process to restart.
"""

from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urlsplit

import test_capability_data as data_fixture
import test_capability_doc as doc_fixture
import test_capability_host_review as host_fixture


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "examples/capability-adapters/packages/local-dashboard/1"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TARGET = load("wp08_integration_target", PACKAGE / "target.py")
MERGE = load("wp08_integration_merge", ROOT / "examples/harness-composition-upgrade/helpers/merge.py")
APPLY = load("wp08_integration_apply", ROOT / "examples/harness-composition-upgrade/helpers/apply.py")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file() and "__pycache__" not in path.parts}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def component_binding(package):
    descriptor = json.loads((package / "capability.json").read_text())
    paths = {"capability.json", *descriptor.get("materials", []),
             *descriptor.get("runtime_files", []), *(tool["path"] for tool in descriptor["tools"])}
    return {"name": descriptor["name"], "version": descriptor["version"],
            "files": [{"path": name, "sha256": digest(package / name)} for name in sorted(paths)]}


class TargetDashboardIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="target-dashboard-integration-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.counter = 0

    def fixture(self, cls):
        fixture = cls()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def record(self, root, format_name, report, files, check_id, label="核对结果"):
        selection = {"kind": "harness_run", "project_id": "isolated-project",
                     "project_version": "product-1", "run_id": "new-task-1"}
        record = {"selection": selection, "title": "目标自身检查记录", "scope_ref": "declared-new-task",
                  "scope_complete": True,
                  "items": [{"item_id": "CHECK", "label": label, "format": format_name,
                             "report": os.path.relpath(report, root), "check_ids": [check_id],
                             "files": {key: {"path": os.path.relpath(path, root)} for key, path in files.items()}}],
                  "steps": [{"step_id": "RESULT", "label": "产生结果", "phase": "output", "item_id": "CHECK"},
                            {"step_id": "CHECK", "label": "独立检查", "item_id": "CHECK", "depends_on": ["RESULT"]}]}
        path = root / "display.json"
        save(path, record)
        return path, selection

    def data_run(self):
        fixture = self.fixture(data_fixture.CapabilityDataTests)
        calls = fixture.root / "producer-calls.txt"
        tool = fixture.package / "summarize_csv.py"
        tool.write_text("from pathlib import Path\nwith Path(" + repr(str(calls)) + ").open('a') as f: f.write('called\\n')\n" + tool.read_text())
        produced = fixture.run_tool()
        self.assertEqual(produced.returncode, 0, produced.stderr)
        checked = fixture.run_check()
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(calls.read_text().splitlines(), ["called"])
        files = {"input": fixture.source, "config": fixture.config_path,
                 "actual": fixture.output, "expected": fixture.expected}
        record, selection = self.record(fixture.root, "data-summary", fixture.report, files, "data-summary")
        return fixture, record, selection, calls

    def request(self, url, suffix):
        parts = urlsplit(url)
        connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=3)
        try:
            connection.request("GET", parts.path + suffix)
            response = connection.getresponse()
            body = response.read()
            self.assertEqual(response.status, 200)
            return json.loads(body)
        finally:
            connection.close()

    def test_native_data_report_is_read_by_standalone_delivered_observer_without_business_replay(self):
        fixture, record, selection, calls = self.data_run()
        delivered = fixture.root / "delivered-dashboard"
        shutil.copytree(PACKAGE, delivered)
        config = fixture.root / "dashboard.json"
        save(config, {"component": component_binding(delivered), "runs": [
            {"id": "data", "selection": selection, "record": str(record)}]})
        before = tree(fixture.root)
        # -I starts outside source import paths: the delivered component needs
        # only the selected Python, itself, and the declared target files.
        process = subprocess.Popen([sys.executable, "-I", "-B", str(delivered / "target.py"),
                                    "--config", str(config), "--poll-seconds", "0.02", "--idle-seconds", "0"],
                                   cwd=fixture.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def stop():
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
            process.stdout.close(); process.stderr.close()
        self.addCleanup(stop)
        self.assertTrue(select.select([process.stdout], [], [], 5)[0], "standalone observer did not announce its URL")
        announced = json.loads(process.stdout.readline())
        self.assertIn("url", announced)
        first = self.request(announced["url"], "api/snapshot?run=data")
        second = self.request(announced["url"], "api/snapshot?run=data")
        self.assertEqual(first["selection"], selection)
        self.assertEqual(first["business"]["items"][0]["state"], "PASS")
        self.assertEqual([row["state"] for row in first["business"]["steps"]], ["PASS", "PASS"])
        self.assertEqual(first["business"]["source_revision"], second["business"]["source_revision"])
        stop()
        self.assertEqual(process.returncode, 0)
        self.assertEqual(tree(fixture.root), before)
        self.assertEqual(calls.read_text().splitlines(), ["called"])

    def test_doc_actual_cli_report_survives_scratch_cleanup_and_readonly_refresh(self):
        fixture = self.fixture(doc_fixture.CapabilityDocTests)
        calls = fixture.root / "export-calls.txt"
        fixture.tool.write_text("from pathlib import Path\nwith Path(" + repr(str(calls)) + ").open('a') as f: f.write('called\\n')\n" + fixture.tool.read_text())
        checked, report = fixture.run_check()
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(report["actual_export"], doc_fixture.EXPECTED)
        self.assertEqual(report["execution"]["invocation_attempts"], 1)
        self.assertEqual(list(fixture.scratch.iterdir()), [])
        files = {"tool": fixture.tool, "config": fixture.config, "notes": fixture.notes,
                 "sources": fixture.sources, "expected": fixture.expected}
        record, selection = self.record(fixture.root, "doc-export", fixture.report, files, "document-export")
        before = tree(fixture.root)
        for _ in range(3):
            projection = TARGET.read_target_projection(record, selection)
            self.assertEqual(projection["business"]["items"][0]["state"], "PASS")
        self.assertEqual(tree(fixture.root), before)
        self.assertEqual(calls.read_text().splitlines(), ["called"])
        self.assertEqual(list(fixture.scratch.iterdir()), [])

    def test_synthetic_prd_host_report_is_read_without_claiming_real_host_acceptance(self):
        fixture = self.fixture(host_fixture.CapabilityHostReviewTests)
        fixture.capture()
        checked, report = fixture.run_check()
        self.assertEqual(checked.returncode, 0, checked.stderr)
        files = {"task": fixture.task_path, "workflow": fixture.project / "workflow.md",
                 "snapshot": fixture.snapshot / "snapshot.json", "expectation": fixture.expected_path,
                 "input:brief": fixture.project / "brief.md",
                 "output:prototype/index.html": fixture.outputs / "prototype/index.html"}
        for key in report["observation_binding"]["files"]:
            if key.startswith("snapshot:"):
                files[key] = fixture.snapshot / key[len("snapshot:"):]
        self.assertEqual(set(files), set(report["observation_binding"]["files"]))
        record, selection = self.record(fixture.root, "host-review", fixture.root / "report-1.json",
                                        files, "host-review", "合成 PRD 宿主记录检查")
        before = tree(fixture.root)
        projection = TARGET.read_target_projection(record, selection)
        self.assertEqual(projection["business"]["items"][0]["state"], "PASS")
        self.assertIn("非整个 Harness 验收", projection["business"]["completion"]["label"])
        self.assertEqual(tree(fixture.root), before)

    def delivery(self):
        self.target = self.root / "target"
        self.component = self.target / "components/local-dashboard"
        shutil.copytree(PACKAGE, self.component)
        # This upgrade fixture supplies an explicitly synthetic native report.
        # It exercises component/version presentation, not DATA correctness or
        # real target acceptance (the actual native-command cases are above).
        files = {key: self.target / (key + ".json") for key in ("input", "config", "actual", "expected")}
        for key, path in files.items():
            save(path, {"engineering_fixture": key})
        report_path = self.target / "records/synthetic-data-report.json"
        save(report_path, {"status": "CHECKS_PASS", "checks": [{"id": "data-summary", "status": "PASS"}],
                           "errors": [], "observation_binding": {"format": "data-summary",
                           "files": {key: digest(path) for key, path in files.items()}}})
        self.bound_evidence = {path: path.read_bytes() for path in [report_path, *files.values()]}
        record, selection = self.record(self.target / "records", "data-summary",
                                        report_path, files, "data-summary", "合成组件升级记录")
        self.selection = selection
        self.record_path = record
        self.config = self.target / "dashboard.json"
        save(self.config, {"component": component_binding(self.component), "runs": [
            {"id": "original-task", "selection": selection, "record": "records/display.json"}]})
        (self.target / "business.py").write_text("raise RuntimeError('observation must never start business')\n")
        (self.target / "historical-evidence.txt").write_text("Original accepted evidence bytes.\n")
        (self.target / "shared-dependency.txt").write_text("Used by other target capabilities.\n")
        self.baseline = self.root / "actual-generated-baseline"
        shutil.copytree(self.target, self.baseline)
        self.old_g = tree(self.baseline)
        self.proposed = self.root / "new-generated-candidate"
        shutil.copytree(self.baseline, self.proposed)
        new_component = self.proposed / "components/local-dashboard"
        descriptor = json.loads((new_component / "capability.json").read_text())
        descriptor["version"] = "2"
        save(new_component / "capability.json", descriptor)
        with (new_component / "dashboard.py").open("a") as stream:
            stream.write("\n# Engineering-only component version 2.\n")
        proposed_config = json.loads((self.proposed / "dashboard.json").read_text())
        proposed_config["component"] = component_binding(new_component)
        save(self.proposed / "dashboard.json", proposed_config)
        custom = json.loads(record.read_text())
        custom["title"] = "项目自定义状态标题"
        custom["items"][0]["label"] = "项目保留的计算检查标签"
        custom["steps"][1]["label"] = "项目专用核对步骤"
        save(record, custom)
        self.custom_record = record.read_bytes()

    def merge(self, paths):
        self.counter += 1
        work = self.root / ("merge-" + str(self.counter))
        work.mkdir()
        def state(path):
            if not path.exists():
                return {"missing": True}
            return {"file": os.path.relpath(path, work), "executable": bool(path.stat().st_mode & 0o111)}
        rows = []
        for relative in paths:
            current = self.target / relative
            saved = work / "current" / relative
            if current.exists():
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(current, saved)
            rows.append({"path": relative, "C": state(saved), "G": state(self.baseline / relative),
                         "N": state(self.proposed / relative), "owners": ["local-dashboard"]})
        manifest = work / "inputs.json"
        save(manifest, {"format_version": 1, "files": rows})
        candidate = work / "candidate"
        return MERGE.merge(manifest, candidate), candidate

    def apply(self, report, candidate):
        self.assertEqual(report["status"], "READY")
        rows = []
        for row in report["files"]:
            expected, desired = row["inputs"]["C"], row["resolved"]
            action = "remove" if desired.get("missing") else "create" if expected.get("missing") else "update"
            rows.append({"path": row["path"], "action": action, "expected": expected, "desired": desired})
        manifest = candidate / "apply-intents.json"
        save(manifest, {"format_version": 1, "files": rows})
        with redirect_stdout(io.StringIO()):
            return APPLY.apply(manifest, self.target, "diagnostics/apply.json")

    def test_component_upgrade_restarts_only_observer_keeps_customization_and_old_run_version(self):
        self.delivery()
        old = load("wp08_old_component", self.component / "target.py").observer_from_config(self.config, poll_seconds=60)
        self.addCleanup(old.stop)
        old.start()
        old_snapshot = old.snapshot("original-task")
        self.assertEqual(old_snapshot["component"]["version"], "1")
        self.assertEqual(old_snapshot["business"]["items"][0]["state"], "PASS")
        old.stop()
        self.assertTrue(old.wait(1))
        component_paths = ["components/local-dashboard/" + path for path in sorted(tree(self.component))]
        report, candidate = self.merge(component_paths + ["dashboard.json", "records/display.json"])
        applied = self.apply(report, candidate)
        self.assertTrue(all(row["status"] in ("APPLIED", "ALREADY_DESIRED") for row in applied["files"]))
        new = load("wp08_new_component", self.component / "target.py").observer_from_config(self.config, poll_seconds=60)
        self.addCleanup(new.stop)
        new.start()
        snapshot = new.snapshot("original-task")
        self.assertEqual(snapshot["component"]["version"], "2")
        self.assertNotEqual(old.session_id, new.session_id)
        self.assertEqual(snapshot["selection"], self.selection)
        self.assertEqual(snapshot["selection"]["project_version"], "product-1")
        self.assertEqual(snapshot["business"]["title"], "项目自定义状态标题")
        self.assertEqual(snapshot["business"]["items"][0]["label"], "项目保留的计算检查标签")
        self.assertEqual(snapshot["business"]["steps"][1]["label"], "项目专用核对步骤")
        self.assertEqual(snapshot["business"]["items"][0]["state"], "PASS")
        self.assertEqual(self.record_path.read_bytes(), self.custom_record)
        self.assertEqual({path: path.read_bytes() for path in self.bound_evidence}, self.bound_evidence)
        for relative in ("business.py", "historical-evidence.txt", "shared-dependency.txt"):
            self.assertEqual((self.target / relative).read_bytes(), self.old_g[relative])
        self.assertEqual(tree(self.baseline), self.old_g)
        new.stop()
        self.assertTrue(new.wait(1))

    def test_shared_component_custom_edit_stays_unresolved_without_partial_apply(self):
        self.delivery()
        relative = "components/local-dashboard/dashboard.py"
        with (self.target / relative).open("a") as stream:
            stream.write("\n# Project edited this shared file.\n")
        before = tree(self.target)
        report, _ = self.merge([relative, "records/display.json"])
        self.assertEqual(report["status"], "CONFLICT")
        self.assertIsNone(report["files"][0]["resolved"])
        self.assertEqual(report["files"][1]["selected"], "C")
        self.assertEqual(tree(self.target), before)
        self.assertEqual(tree(self.baseline), self.old_g)

    def test_component_removal_preserves_business_records_customization_and_shared_dependency(self):
        self.delivery()
        paths = ["components/local-dashboard/" + path for path in sorted(tree(self.component))]
        shutil.rmtree(self.proposed / "components/local-dashboard")
        (self.proposed / "dashboard.json").unlink()
        report, candidate = self.merge(paths + ["dashboard.json", "records/display.json", "shared-dependency.txt"])
        self.apply(report, candidate)
        self.assertFalse(any(path.is_file() for path in self.component.rglob("*")))
        self.assertFalse(self.config.exists())
        self.assertEqual(self.record_path.read_bytes(), self.custom_record)
        self.assertEqual({path: path.read_bytes() for path in self.bound_evidence}, self.bound_evidence)
        for relative in ("business.py", "historical-evidence.txt", "shared-dependency.txt"):
            self.assertEqual((self.target / relative).read_bytes(), self.old_g[relative])
        self.assertEqual(tree(self.baseline), self.old_g)


if __name__ == "__main__":
    unittest.main()
