"""Synthetic engineering records only, not real browser/search acceptance."""

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "examples/capability-adapters/packages/host-review/1"


class CapabilityHostReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="capability-host-review-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.package = self.root / "delivered-package"
        shutil.copytree(PACKAGE, self.package)
        self.project = self.root / "project"
        self.outputs = self.root / "outputs"
        self.evidence = self.root / "host-records"
        for directory in (self.project, self.outputs, self.evidence):
            directory.mkdir()
        (self.project / "brief.md").write_text("New project input, independent of the historical examples.\n")
        (self.project / "workflow.md").write_bytes((self.package / "prd.md").read_bytes())
        (self.outputs / "prototype").mkdir()
        (self.outputs / "prototype/index.html").write_text("<button>Retain entered text</button>\n")
        (self.evidence / "observation.txt").write_text("SYNTHETIC TEST OBSERVATION, not an actual browser operation.\n")
        self.task = {"task_id": "synthetic-prd-new-task", "workflow": "workflow.md",
                     "inputs": {"brief": "brief.md"}, "outputs": ["prototype/index.html"],
                     "host_tools": ["Synthetic test record for the explicitly declared browser host"]}
        self.review = {"reviewer": "synthetic-independent-test-fixture", "observations": [
            {"id": "input-retention", "result": "PASS", "reason": "Synthetic supplied finding only",
             "evidence_refs": ["observation.txt"]}]}
        self.expected = {"task_id": self.task["task_id"], "required_observations": ["input-retention"]}
        self.task_path = self.project / "task.json"
        self.review_path = self.root / "review.json"
        self.snapshot = self.root / "snapshot"
        self.expected_path = self.root / "expected.json"
        self.write_json(self.task_path, self.task)
        self.write_json(self.review_path, self.review)
        self.write_json(self.expected_path, self.expected)
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("FOUNDRY_")}
        self.report_index = 0

    def write_json(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def run_snapshot(self, destination=None):
        return subprocess.run([sys.executable, "-I", "-B", str(self.package / "snapshot.py"),
                               "--task", str(self.task_path), "--outputs", str(self.outputs),
                               "--evidence-root", str(self.evidence), "--review", str(self.review_path),
                               "--destination", str(destination or self.snapshot)],
                              cwd=self.root, env=self.env, capture_output=True, text=True, timeout=15)

    def capture(self):
        result = self.run_snapshot()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["accepted"])

    def run_check(self, checker=None, task=None, expected=None, snapshot=None, environment=None):
        self.report_index += 1
        report = self.root / ("report-" + str(self.report_index) + ".json")
        result = subprocess.run([sys.executable, "-I", "-B", str(checker or self.package / "check_review.py"),
                                 "--task", str(task or self.task_path), "--expectation", str(expected or self.expected_path),
                                 "--snapshot", str(snapshot or self.snapshot / "snapshot.json"), "--outputs", str(self.outputs),
                                 "--report", str(report)], cwd=self.root, env={**self.env, **(environment or {})},
                                capture_output=True, text=True, timeout=15)
        self.assertTrue(report.is_file(), result.stderr)
        return result, json.loads(report.read_text())

    def assert_error(self, **kwargs):
        result, report = self.run_check(**kwargs)
        self.assertEqual(result.returncode, 1, report)
        self.assertEqual(report["checks"], [{"id": "host-review", "status": "ERROR"}])
        self.assertNotIn("failure_kind", report)
        return report

    def test_delivered_snapshot_and_checker_are_standalone_without_producer_replay(self):
        original = {path: path.read_bytes() for root in (self.package, self.project, self.outputs, self.evidence)
                    for path in root.rglob("*") if path.is_file()}
        self.capture()
        for _ in range(2):
            result, report = self.run_check()
            self.assertEqual(result.returncode, 0, report)
            self.assertEqual(report["status"], "CHECKS_PASS")
            self.assertIn("semantic truth", report["scope"])
        self.assertEqual(original, {path: path.read_bytes() for path in original})
        self.assertEqual((self.snapshot / "task/task.json").read_bytes(), self.task_path.read_bytes())
        self.assertEqual((self.snapshot / "inputs/0").read_bytes(), (self.project / "brief.md").read_bytes())
        self.assertEqual((self.snapshot / "outputs/prototype/index.html").read_bytes(),
                         (self.outputs / "prototype/index.html").read_bytes())

    def test_existing_snapshot_is_preserved_and_never_overwritten(self):
        self.capture()
        before = {path: path.read_bytes() for path in self.snapshot.rglob("*") if path.is_file()}
        result = self.run_snapshot()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_missing_evidence_fails_before_creating_snapshot(self):
        (self.evidence / "observation.txt").unlink()
        result = self.run_snapshot()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.snapshot.exists())

    def test_snapshot_destination_cannot_be_part_of_copied_roots(self):
        for root in (self.project, self.outputs, self.evidence):
            with self.subTest(root=root):
                result = self.run_snapshot(root / "snapshot")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root / "snapshot").exists())

    def test_task_workflow_input_and_output_changes_do_not_reuse_old_review(self):
        self.capture()
        for path in (self.task_path, self.project / "workflow.md", self.project / "brief.md",
                     self.outputs / "prototype/index.html"):
            original = path.read_bytes()
            with self.subTest(path=path):
                path.write_bytes(original + b"\n")
                self.assert_error()
                path.write_bytes(original)
        result, report = self.run_check()
        self.assertEqual(result.returncode, 0, report)

    def test_independent_required_observations_cannot_be_inferred_from_self_report(self):
        self.capture()
        self.expected["required_observations"].append("required-but-not-reviewed")
        self.write_json(self.expected_path, self.expected)
        self.assert_error()

    def test_valid_supplied_fail_is_assertion_and_extra_finding_is_not_lost(self):
        self.review["observations"].append({"id": "extra-defect", "result": "FAIL",
            "reason": "Independent synthetic finding outside the minimum list", "evidence_refs": ["observation.txt"]})
        self.write_json(self.review_path, self.review)
        self.capture()
        result, report = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report["failure_kind"], "ASSERTION")
        self.assertIn("extra-defect", report["diagnostic"])

    def test_unfinished_or_malformed_observation_is_error_even_when_it_says_fail(self):
        self.capture()
        captured_path = self.snapshot / "snapshot.json"
        captured = json.loads(captured_path.read_text())
        variants = []
        for value in ("UNKNOWN", "NOT_RUN", "UNRECOGNIZED"):
            altered = deepcopy(captured)
            altered["observations"][0]["result"] = value
            variants.append(altered)
        for key, value in (("reason", ""), ("evidence_refs", []), ("evidence_refs", ["evidence/missing.txt"])):
            altered = deepcopy(captured)
            altered["observations"][0].update(result="FAIL", **{key: value})
            variants.append(altered)
        altered = deepcopy(captured)
        altered["observations"].append(deepcopy(altered["observations"][0]))
        variants.append(altered)
        for index, value in enumerate(variants):
            with self.subTest(index=index):
                self.write_json(captured_path, value)
                self.assert_error()

    def test_unknown_and_not_run_are_preserved_without_inventing_evidence(self):
        for status in ("UNKNOWN", "NOT_RUN"):
            with self.subTest(status=status):
                self.review["observations"][0].update(result=status, reason="Not observed", evidence_refs=[])
                self.write_json(self.review_path, self.review)
                destination = self.root / status
                result = self.run_snapshot(destination)
                self.assertEqual(result.returncode, 0, result.stderr)
                saved = json.loads((destination / "snapshot.json").read_text())
                self.assertEqual(saved["observations"][0]["result"], status)
                self.assertEqual(saved["observations"][0]["evidence_refs"], [])
                self.assert_error(snapshot=destination / "snapshot.json")

    def test_incomplete_review_retains_confirmed_failure_in_either_row_order(self):
        confirmed = {"id": "input-retention", "result": "FAIL", "reason": "Synthetic confirmed input loss",
                     "evidence_refs": ["observation.txt"]}
        unfinished = {"id": "layout", "result": "NOT_RUN", "reason": "Rendering not yet observed",
                      "evidence_refs": []}
        self.expected["required_observations"].append("layout")
        self.write_json(self.expected_path, self.expected)
        for index, observations in enumerate(([confirmed, unfinished], [unfinished, confirmed])):
            with self.subTest(order=index):
                self.review["observations"] = observations
                self.write_json(self.review_path, self.review)
                destination = self.root / ("mixed-" + str(index))
                result = self.run_snapshot(destination)
                self.assertEqual(result.returncode, 0, result.stderr)
                report = self.assert_error(snapshot=destination / "snapshot.json")
                self.assertEqual(report["findings"], ["input-retention: Synthetic confirmed input loss"])
                self.assertIn("layout", "; ".join(report["errors"]))

    def test_protected_checker_uses_only_protected_dependency_bytes(self):
        self.capture()
        protected = self.root / "protected"
        shutil.copytree(self.project, protected / "project")
        shutil.copytree(self.snapshot, protected / "snapshot")
        shutil.copy2(self.expected_path, protected / "expected.json")
        shutil.copy2(self.package / "check_review.py", protected / "check_review.py")
        arguments = {"checker": protected / "check_review.py", "task": protected / "project/task.json",
                     "expected": protected / "expected.json", "snapshot": protected / "snapshot/snapshot.json",
                     "environment": {"FOUNDRY_VERIFIER_ROOT": str(protected), "FOUNDRY_CASE_ID": "CASE-A",
                                     "FOUNDRY_COMMAND_ID": "COMMAND-A"}}
        # The live public dependency changes after capture. Protected bytes remain authoritative.
        (self.project / "brief.md").write_text("Public input later changed")
        result, report = self.run_check(**arguments)
        self.assertEqual(result.returncode, 0, report)
        self.assertEqual(report["case_id"], "CASE-A")
        self.assertEqual(report["command_id"], "COMMAND-A")
        for key, path in (("checker", self.package / "check_review.py"), ("task", self.task_path),
                          ("expected", self.expected_path), ("snapshot", self.snapshot / "snapshot.json")):
            with self.subTest(key=key):
                self.assert_error(**{**arguments, key: path})
        # A task-file alias resolves dependencies beside the protected task,
        # not beside the unrelated public alias with a changed brief.md.
        alias = self.project / "protected-task-alias.json"
        alias.symlink_to(protected / "project/task.json")
        result, report = self.run_check(**{**arguments, "task": alias})
        self.assertEqual(result.returncode, 0, report)
        (protected / "project/brief.md").write_text("New protected version requires new observation")
        self.assert_error(**arguments)

    def test_unrelated_market_task_has_its_own_inputs_outputs_and_obligations(self):
        self.task.update(task_id="synthetic-market-new-question", inputs={}, outputs=["decision.md"],
                         host_tools=["Synthetic declared search_query/open host record"])
        (self.project / "workflow.md").write_bytes((self.package / "market.md").read_bytes())
        (self.outputs / "decision.md").write_text("Synthetic decision, not actual new research")
        self.review["observations"][0]["id"] = "version-and-claim-support"
        self.expected = {"task_id": self.task["task_id"], "required_observations": ["version-and-claim-support"]}
        for path, value in ((self.task_path, self.task), (self.review_path, self.review), (self.expected_path, self.expected)):
            self.write_json(path, value)
        self.capture()
        result, report = self.run_check()
        self.assertEqual(result.returncode, 0, report)

    def test_declared_paths_do_not_escape_their_roots(self):
        for section, value in (("workflow", "../outside.md"), ("inputs", {"brief": "../outside.md"}),
                               ("outputs", ["../outside.md"])):
            with self.subTest(section=section):
                task = {**self.task, section: value}
                self.write_json(self.task_path, task)
                self.assertNotEqual(self.run_snapshot().returncode, 0)
                self.assertFalse(self.snapshot.exists())
        self.write_json(self.task_path, self.task)
        (self.project / "brief.md").unlink()
        (self.project / "brief.md").symlink_to(self.evidence / "observation.txt")
        self.assertNotEqual(self.run_snapshot().returncode, 0)
        self.assertFalse(self.snapshot.exists())

    def test_duplicate_review_ids_and_json_keys_are_not_silently_collapsed(self):
        self.review["observations"].append(deepcopy(self.review["observations"][0]))
        self.write_json(self.review_path, self.review)
        self.assertNotEqual(self.run_snapshot().returncode, 0)
        self.assertFalse(self.snapshot.exists())
        self.review_path.write_text('{"reviewer":"one","reviewer":"two","observations":[]}')
        self.assertNotEqual(self.run_snapshot().returncode, 0)


if __name__ == "__main__":
    unittest.main()
