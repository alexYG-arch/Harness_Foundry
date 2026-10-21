"""Version 3 display contract and DOM checks; not native PiP or human acceptance."""
from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_foundry_dashboard_host as foundry_fixture
from harness_foundry_factory.revision_store import RevisionControlEventStore

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "examples/capability-adapters/packages/local-dashboard/3"


def load(version):
    spec = importlib.util.spec_from_file_location("workflow_dashboard_" + version, PACKAGE.with_name(version) / "dashboard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


D = load("3")
OLD = load("2")


def projection():
    return {"selection": {"kind": "foundry_build", "project_id": "fixture", "project_version": "1",
                           "run_id": "run", "program_id": "program", "prepared_event_id": "prepared-1"},
            "business": {"title": "显示夹具", "current": "等待复核", "items": [],
                         "completion": {"completed": 0, "total": 2, "label": "当前有效检查"},
                         "steps": [{"step_id": "legacy", "state": "PENDING", "label": "旧步骤"}],
                         "current_step_id": "legacy", "pending": ["复核结果"], "budget": {"attempts_consumed": 3}},
            "observation": {"activity": {"last_output_at": None}, "gaps": ["原记录缺口"]}}


def extended():
    raw = projection()
    raw["business"]["work_progress"] = {"completed": 1, "total": 2, "label": "已记录工作"}
    raw["business"]["workflow"] = {"steps": [
        {"step_id": "past", "label": "需求理解", "state": "PASS", "detail": "已记录结果",
         "evidence_refs": ["receipt-1"], "history": [
             {"label": "首次检查", "state": "FAILED", "detail": "原失败保留", "evidence_refs": ["failure-1"]},
             {"label": "修复后检查", "state": "PASS", "detail": "历史通过仍保留"}]},
        {"step_id": "current", "label": "当前复核", "state": "PENDING"},
        {"step_id": "future", "label": "整理交付", "state": "NOT_STARTED"}], "current_step_id": "current"}
    return raw


class DashboardWorkflowUiTests(unittest.TestCase):
    def test_version_and_optional_contract_preserve_legacy_business(self):
        self.assertTrue(D.SUPPORTS_WORK_PROGRESS)
        self.assertEqual(json.loads((PACKAGE / "capability.json").read_text())["version"], "3")
        raw = projection()
        self.assertEqual(D.normalize_projection(raw, raw["selection"]), OLD.normalize_projection(raw, raw["selection"]))
        raw = extended()
        normalized = D.normalize_projection(raw, raw["selection"])
        business = normalized["business"]
        self.assertEqual(business["work_progress"]["completed"] / business["work_progress"]["total"], .5)
        self.assertEqual(business["completion"]["completed"], 0)
        for key, value in OLD.normalize_projection(raw, raw["selection"])["business"].items():
            self.assertEqual(business[key], value)
        business["workflow"]["steps"][0]["history"][0]["label"] = "changed copy"
        self.assertEqual(raw["business"]["workflow"]["steps"][0]["history"][0]["label"], "首次检查")

    def test_new_projection_filters_unrecognized_fields_at_every_level(self):
        raw = extended()
        raw["business"]["work_progress"]["raw_log"] = "must not pass"
        workflow = raw["business"]["workflow"]
        workflow["command"] = "must not pass"
        workflow["steps"][0]["private_path"] = "must not pass"
        workflow["steps"][0]["history"][0]["raw_source"] = "must not pass"
        result = D.normalize_projection(raw, raw["selection"])
        self.assertNotIn("must not pass", json.dumps(result))
        self.assertEqual(result["business"]["workflow"]["steps"][0]["evidence_refs"], ["receipt-1"])

    def test_work_progress_uses_completion_numeric_validation(self):
        invalid = [None, [], {}, {"completed": True, "total": 2, "label": "x"},
                   {"completed": -1, "total": 2, "label": "x"},
                   {"completed": 3, "total": 2, "label": "x"},
                   {"completed": 0, "total": 0, "label": "x"},
                   {"completed": 0, "total": math.inf, "label": "x"},
                   {"completed": math.nan, "total": 2, "label": "x"},
                   {"completed": 0, "total": 2, "label": " "}]
        for value in invalid:
            with self.subTest(value=value):
                raw = projection(); raw["business"]["work_progress"] = value
                with self.assertRaises(ValueError): D.normalize_projection(raw, raw["selection"])
        raw = projection(); raw["business"]["work_progress"] = {"completed": .5, "total": 2, "label": "有效比例"}
        self.assertEqual(D.normalize_projection(raw, raw["selection"])["business"]["work_progress"]["completed"], .5)

    def test_workflow_identity_state_history_and_references_are_validated(self):
        invalid = [None, [], {}, {"steps": {}}, {"steps": [None]},
                   {"steps": [{"step_id": "x", "state": "invented"}]},
                   {"steps": [{"step_id": "x", "state": "PASS"}] * 2},
                   {"steps": [], "current_step_id": "absent"},
                   {"steps": [], "current_step_id": None},
                   {"steps": [{"step_id": "x", "state": "PASS", "history": {}}]},
                   {"steps": [{"step_id": "x", "state": "PASS", "history": [{"state": "invented"}]}]},
                   {"steps": [{"step_id": "x", "state": "PASS", "evidence_refs": [42]}]}]
        for value in invalid:
            with self.subTest(value=value):
                raw = projection(); raw["business"]["workflow"] = value
                with self.assertRaises(ValueError): D.normalize_projection(raw, raw["selection"])
        raw = projection(); raw["business"]["workflow"] = {"steps": [{"step_id": state, "state": state} for state in sorted(D._WORKFLOW_STATES)]}
        self.assertEqual(len(D.normalize_projection(raw, raw["selection"])["business"]["workflow"]["steps"]), len(D._WORKFLOW_STATES))

    def test_cache_failure_keeps_complete_history_and_gap_without_source_mutation(self):
        raw = extended(); before = deepcopy(raw)
        source = {"value": raw}
        observer = D.Observer({"one": {"selection": raw["selection"], "reader": lambda: source["value"]}}, theme="dark")
        observer._collect("one")
        first = observer.snapshot("one")
        self.assertEqual(first["presentation"]["theme"], "dark")
        self.assertEqual(first["component"]["version"], "3")
        source["value"] = {"selection": raw["selection"], "business": {"workflow": []}}
        observer._collect("one")
        failed = observer.snapshot("one")
        self.assertEqual(failed["business"], first["business"])
        self.assertIn("SOURCE_UNAVAILABLE", failed["observation"]["gaps"])
        self.assertIn("原记录缺口", failed["observation"]["gaps"])
        self.assertEqual(raw, before)

    def test_selected_foundry_host_materials_opt_in_only_version_three(self):
        fixture = foundry_fixture.FoundryDashboardHostTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        host = foundry_fixture.HOST
        consume = host._load(ROOT / "examples/capability-adapters/consume.py", "workflow_host_consume")
        before = fixture.f.store.database_path.read_bytes()
        real_reader = host.read_foundry_projection
        legacy_business = None
        for version in ("1", "2", "3"):
            with self.subTest(version=version):
                selected = fixture.f.root / ("workflow-dashboard-" + version)
                shutil.copytree(PACKAGE.with_name(version), selected)
                materials, _ = consume._prepare.build_materials({
                    "project_root": str(fixture.f.workspace),
                    "selections": [{"directory": str(selected), "version": version}],
                    "environment_bindings": {"python": {"path": sys.executable,
                        "observed_version": ".".join(map(str, sys.version_info[:3]))}},
                }, fixture.f.root / ("workflow-materials-" + version))
                (fixture.f.root / "materials.json").write_text(json.dumps(materials))
                with patch.object(host, "read_foundry_projection", wraps=real_reader) as reader, \
                        patch.object(RevisionControlEventStore, "append_batch", side_effect=AssertionError("observer writes")), \
                        patch("subprocess.Popen", side_effect=AssertionError("observer dispatch")):
                    with host.observer_from_config(fixture.config, poll_seconds=60) as observer:
                        snapshot = observer.snapshot("one")
                        self.assertEqual(snapshot["component"]["version"], version)
                        self.assertEqual(snapshot["selection"], fixture.selection)
                        self.assertFalse(snapshot["observation"]["gaps"])
                        self.assertEqual(reader.call_count, 1)
                        business = snapshot["business"]
                        if version == "3":
                            self.assertEqual(reader.call_args.kwargs, {"include_workflow": True})
                            self.assertEqual(business["work_progress"]["completed"], 0)
                            self.assertEqual(business["work_progress"]["total"], 2)
                            self.assertTrue(business["workflow"]["steps"])
                            self.assertIn(business["workflow"]["current_step_id"],
                                          {step["step_id"] for step in business["workflow"]["steps"]})
                            self.assertEqual({key: value for key, value in business.items()
                                              if key not in ("workflow", "work_progress")}, legacy_business)
                        else:
                            self.assertEqual(reader.call_args.kwargs, {})
                            self.assertNotIn("workflow", business)
                            self.assertNotIn("work_progress", business)
                            if legacy_business is None:
                                legacy_business = business
                            else:
                                self.assertEqual(business, legacy_business)
        self.assertEqual(fixture.f.store.database_path.read_bytes(), before)
        self.assertFalse(fixture.f.runner.invocations)

    def test_frontend_workflow_and_retained_theme_dom_fixtures(self):
        node = shutil.which("node")
        if node is None: self.skipTest("Node unavailable; DOM checks not run")
        for fixture in ("dashboard_workflow_dom.js", "dashboard_theme_dom.js"):
            with self.subTest(fixture=fixture):
                run = subprocess.run([node, str(ROOT / "tests/fixtures" / fixture), str(PACKAGE / "web/app.js")],
                                     capture_output=True, text=True, timeout=10)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__": unittest.main()
