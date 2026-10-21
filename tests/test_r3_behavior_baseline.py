"""The A0 diagnostic invokes fixed real public/control paths, never a model."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("r3_behavior_baseline", ROOT / "devtools/r3_behavior_baseline.py")
BASELINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASELINE)


class R3BehaviorBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report.json"
            run = subprocess.run([sys.executable, "-B", str(ROOT / "devtools/r3_behavior_baseline.py"),
                "--source-root", str(ROOT), "--fixture-root", str(ROOT), "--output", str(output)],
                text=True, capture_output=True, timeout=60, check=False)
            if run.returncode:
                raise AssertionError(run.stdout + run.stderr)
            cls.report = json.loads(output.read_text())

    def test_real_scenarios_preserve_failure_recovery_and_budget_distinctions(self):
        states = {row["name"]: row["signature"][0] for row in self.report["scenarios"]}
        self.assertEqual(len(states), 17)
        expected = {
            "public_normal": ["ACCEPTED", "ACCEPTED"],
            "assertion_repair": ["REJECTED", "ACCEPTED", "ACCEPTED"],
            "infrastructure_failure": ["BLOCKED"],
            "not_dispatched": ["NOT_DISPATCHED", "ACCEPTED"],
            "unknown_capture": ["IN_FLIGHT"],
            "partial_resource": ["BLOCKED"],
            "budget": ["ACCEPTED"],
        }
        for name, statuses in expected.items():
            self.assertEqual([row["status"] for row in states[name]["attempts"]], statuses)
        self.assertEqual(states["not_dispatched"]["authorizations"][0]["budget"]["attempts_consumed"], 2)
        self.assertEqual(states["budget"]["authorizations"][0]["budget"]["attempts_remaining"], 0)
        self.assertEqual(states["resource_capture"]["authorizations"][0]["state"], "EXPIRED")
        self.assertTrue(all(not state["writes_performed"] for state in states.values()))
        self.assertEqual(BASELINE.compare(self.report, self.report)["status"], "MATCH")

    def test_comparison_rejects_lost_events_changed_budget_and_changed_fixture(self):
        for field in ("event", "budget", "fixture"):
            changed = deepcopy(self.report)
            if field == "fixture":
                changed["fixture_files"]["tests/test_build_runtime.py"] = "changed"
            elif field == "event":
                changed["scenarios"][0]["signature"][0]["event_types"].pop()
            else:
                changed["scenarios"][0]["signature"][0]["authorizations"][0]["budget"]["attempts_consumed"] += 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                BASELINE.compare(self.report, changed)
