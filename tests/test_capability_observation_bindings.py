"""Additive target observation bindings; synthetic records, not business acceptance."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_capability_data as data_fixture
import test_capability_host_review as host_fixture


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_checker(path):
    spec = importlib.util.spec_from_file_location("observation_checker", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CapabilityObservationBindingTests(unittest.TestCase):
    def data(self):
        fixture = data_fixture.CapabilityDataTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.actual()
        checker = load_checker(fixture.package / "check_summary.py")
        args = argparse.Namespace(input=fixture.source, config=fixture.config_path,
                                  actual=fixture.output, expected=fixture.expected)
        return fixture, checker, args

    def host(self, mixed=False):
        fixture = host_fixture.CapabilityHostReviewTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        if mixed:
            fixture.review["observations"][0].update(result="FAIL", reason="Confirmed synthetic defect")
            fixture.review["observations"].append({"id": "layout", "result": "NOT_RUN",
                "reason": "Not yet observed", "evidence_refs": []})
            fixture.expected["required_observations"].append("layout")
            fixture.write_json(fixture.review_path, fixture.review)
            fixture.write_json(fixture.expected_path, fixture.expected)
        fixture.capture()
        checker = load_checker(fixture.package / "check_review.py")
        args = argparse.Namespace(task=fixture.task_path, expectation=fixture.expected_path,
                                  snapshot=fixture.snapshot / "snapshot.json", outputs=fixture.outputs)
        return fixture, checker, args

    def host_files(self, fixture):
        paths = {"task": fixture.task_path, "workflow": fixture.project / "workflow.md",
                 "input:brief": fixture.project / "brief.md",
                 "output:prototype/index.html": fixture.outputs / "prototype/index.html",
                 "snapshot": fixture.snapshot / "snapshot.json", "expectation": fixture.expected_path}
        for name in ("task/task.json", "task/workflow", "inputs/0",
                     "outputs/prototype/index.html", "evidence/observation.txt"):
            paths["snapshot:" + name] = fixture.snapshot / name
        return paths

    def test_data_pass_binds_all_checked_files_without_paths_or_contents(self):
        fixture, checker, args = self.data()
        report = checker.check(args)
        self.assertEqual(report["status"], "CHECKS_PASS")
        self.assertEqual(report["observation_binding"], {"format": "data-summary", "files": {
            key: digest(getattr(args, key)) for key in ("input", "config", "actual", "expected")}})
        self.assertNotIn(str(fixture.root), json.dumps(report["observation_binding"]))
        self.assertEqual(checker.read_json(fixture.expected), fixture.oracle)

    def test_data_changed_files_do_not_rebind_old_report(self):
        fixture, checker, args = self.data()
        old_report = checker.check(args)
        old_binding = dict(old_report["observation_binding"]["files"])
        for key in ("input", "config", "actual", "expected"):
            path = getattr(args, key)
            original = path.read_bytes()
            with self.subTest(key=key):
                path.write_bytes(original + b"\n")
                self.assertNotEqual(old_binding[key], digest(path))
                current = checker.check(args)
                self.assertEqual(current["observation_binding"]["files"][key], digest(path))
                # Whitespace changes to actual/expected preserve JSON meaning;
                # input/config changes still invalidate the producer's hashes.
                self.assertEqual(current["status"], "CHECKS_FAILED" if key in ("input", "config") else "CHECKS_PASS")
                if key in ("input", "config"):
                    self.assertEqual(current["failure_kind"], "ASSERTION")
                path.write_bytes(original)
        self.assertEqual(old_report["observation_binding"]["files"], old_binding)

    def test_data_failure_and_error_keep_available_bindings(self):
        fixture, checker, args = self.data()
        fixture.output.unlink()
        missing = checker.check(args)
        self.assertEqual(missing["checks"], [{"id": "data-summary", "status": "FAIL"}])
        self.assertEqual(missing["failure_kind"], "ASSERTION")
        self.assertIsNone(missing["observation_binding"]["files"]["actual"])
        self.assertEqual(missing["observation_binding"]["files"]["expected"], digest(fixture.expected))
        fixture.output.write_text("broken json")
        malformed = checker.check(args)
        self.assertEqual(malformed["failure_kind"], "ASSERTION")
        self.assertEqual(malformed["observation_binding"]["files"]["actual"], digest(fixture.output))
        fixture.expected.write_text("broken expectation")
        error = checker.check(args)
        self.assertEqual(error["checks"], [{"id": "data-summary", "status": "ERROR"}])
        self.assertNotIn("failure_kind", error)
        self.assertEqual(error["observation_binding"]["files"], {
            "input": None, "config": None, "actual": None, "expected": digest(fixture.expected)})

    def test_data_hashes_the_bytes_used_for_checks_not_a_later_recapture(self):
        fixture, checker, args = self.data()
        original = {getattr(args, key): getattr(args, key).read_bytes()
                    for key in ("input", "config", "actual", "expected")}
        read_bytes, reads = Path.read_bytes, {}
        def changing_read(path):
            data = read_bytes(path)
            if path in original:
                reads[path] = reads.get(path, 0) + 1
                path.write_bytes(data + b"\n")
            return data
        with patch.object(Path, "read_bytes", changing_read):
            report = checker.check(args)
        self.assertEqual(report["status"], "CHECKS_PASS")
        self.assertEqual(reads, dict.fromkeys(original, 1))
        for key, value in report["observation_binding"]["files"].items():
            self.assertEqual(value, hashlib.sha256(original[getattr(args, key)]).hexdigest())
            self.assertNotEqual(value, digest(getattr(args, key)))

    def test_host_pass_binds_task_inputs_outputs_expectation_and_consumed_snapshot(self):
        fixture, checker, args = self.host()
        report = checker.check(args)
        self.assertEqual(report["status"], "CHECKS_PASS")
        self.assertEqual(report["observation_binding"], {"format": "host-review", "files": {
            key: digest(path) for key, path in self.host_files(fixture).items()}})
        self.assertNotIn(str(fixture.root), json.dumps(report["observation_binding"]))
        self.assertEqual(checker.inspect(args), [])
        self.assertEqual(checker.read_json(args.task), fixture.task)

    def test_host_changed_inputs_and_outputs_keep_old_binding_and_error_classification(self):
        fixture, checker, args = self.host()
        old = checker.check(args)
        for key, path in self.host_files(fixture).items():
            original = path.read_bytes()
            with self.subTest(key=key):
                path.write_bytes(original + b"\n")
                self.assertNotEqual(old["observation_binding"]["files"][key], digest(path))
                current = checker.check(args)
                self.assertEqual(current["observation_binding"]["files"][key], digest(path))
                # JSON whitespace in expectation/snapshot and nonempty evidence
                # remain valid; all other changes break snapshot equality.
                if key not in ("expectation", "snapshot", "snapshot:evidence/observation.txt"):
                    self.assertEqual(current["checks"], [{"id": "host-review", "status": "ERROR"}])
                    self.assertNotIn("failure_kind", current)
                path.write_bytes(original)

    def test_host_incomplete_review_retains_findings_and_consumed_bindings(self):
        fixture, checker, args = self.host(mixed=True)
        report = checker.check(args)
        self.assertEqual(report["checks"], [{"id": "host-review", "status": "ERROR"}])
        self.assertEqual(report["findings"], ["input-retention: Confirmed synthetic defect"])
        self.assertIn("layout", "; ".join(report["errors"]))
        self.assertEqual(report["observation_binding"]["files"], {
            key: digest(path) for key, path in self.host_files(fixture).items()})

    def test_host_consumes_repeated_task_and_evidence_bytes_once(self):
        fixture, checker, args = self.host()
        captured = json.loads(args.snapshot.read_text())
        captured["observations"].append({**captured["observations"][0], "id": "additional-observation"})
        fixture.write_json(args.snapshot, captured)
        paths = self.host_files(fixture)
        original = {path: path.read_bytes() for path in paths.values()}
        read_bytes, reads = Path.read_bytes, {}
        def changing_read(path):
            data = read_bytes(path)
            if path in original:
                reads[path] = reads.get(path, 0) + 1
                path.write_bytes(data + b"\n")
            return data
        with patch.object(Path, "read_bytes", changing_read):
            report = checker.check(args)
        self.assertEqual(report["status"], "CHECKS_PASS", report)
        self.assertEqual(reads, dict.fromkeys(original, 1))
        for key, value in report["observation_binding"]["files"].items():
            self.assertEqual(value, hashlib.sha256(original[paths[key]]).hexdigest())
            self.assertNotEqual(value, digest(paths[key]))


if __name__ == "__main__":
    unittest.main()
