"""Focused ordinary-file helper tests; not live Harness/business acceptance."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


HELPERS = Path(__file__).resolve().parents[1] / "examples/harness-composition-upgrade/helpers"
MISSING = {"missing": True}


def load_helper(name):
    spec = importlib.util.spec_from_file_location("r3_test_" + name, HELPERS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CompositionHelperTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="r3-helper-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.target = self.root / "target"
        self.target.mkdir()
        self.merge = load_helper("merge")
        self.apply = load_helper("apply")

    def payload(self, name, content, executable=False):
        path = self.inputs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return {"file": name, "executable": executable}

    def write_target(self, name, content, executable=False):
        path = self.target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o755 if executable else 0o644)
        return path

    def manifest(self, name, files):
        path = self.inputs / name
        path.write_text(json.dumps({"format_version": 1, "files": files}), encoding="utf-8")
        return path

    def apply_item(self, name="file.txt", old=b"old", new=b"new", action="update"):
        expected = MISSING if old is None else self.payload("old-" + name, old)
        desired = MISSING if new is None else self.payload("new-" + name, new)
        return {"path": name, "action": action, "expected": expected, "desired": desired}

    def run_apply(self, files):
        manifest = self.manifest("apply.json", files)
        with mock.patch("builtins.print"):
            return self.apply.apply(manifest, self.target, "reports/apply.json")

    def test_three_equality_rules_preserve_bytes_and_snapshots(self):
        old = self.payload("old", b"old\x00\xff")
        new = self.payload("new", b"new\r\n", True)
        local = self.payload("local", b"local\n")
        manifest = self.manifest("inputs.json", [
            {"path": "take-new", "C": old, "G": old, "N": new},
            {"path": "keep-local", "C": local, "G": old, "N": old},
            {"path": "same", "C": new, "G": old, "N": new},
        ])
        output = self.root / "candidate"
        report = self.merge.merge(manifest, output)
        self.assertEqual(report["status"], "READY")
        self.assertEqual([row["selected"] for row in report["files"]], ["N", "C", "C"])
        for row, expected in zip(report["files"], [b"new\r\n", b"local\n", b"new\r\n"]):
            self.assertEqual((output / row["resolved"]["file"]).read_bytes(), expected)
        self.assertTrue((output / report["files"][0]["resolved"]["file"]).stat().st_mode & 0o111)
        self.assertEqual((output / report["files"][0]["inputs"]["G"]["file"]).read_bytes(), b"old\x00\xff")

    def test_conflict_and_unknown_baseline_are_inspectable(self):
        current = self.payload("c", b"user")
        baseline = self.payload("g", b"old")
        new = self.payload("n", b"new")
        manifest = self.manifest("inputs.json", [
            {"path": "conflict", "C": current, "G": baseline, "N": new, "owners": ["a", "b"]},
            {"path": "unknown", "C": current, "G": None, "N": new},
        ])
        output = self.root / "candidate"
        report = self.merge.merge(manifest, output)
        self.assertEqual([x["status"] for x in report["files"]], ["CONFLICT", "PROJECT_INCREMENTAL_REQUIRED"])
        self.assertEqual(report["files"][0]["owners"], ["a", "b"])
        self.assertIsNone(report["files"][1]["inputs"]["G"])
        for row in report["files"]:
            self.assertIsNone(row["resolved"])
            self.assertEqual((output / row["inputs"]["C"]["file"]).read_bytes(), b"user")

    def test_missing_empty_and_executable_states_are_distinct(self):
        empty = self.payload("empty", b"")
        executable = self.payload("exe", b"", True)
        manifest = self.manifest("inputs.json", [
            {"path": "create-empty", "C": MISSING, "G": MISSING, "N": empty},
            {"path": "delete", "C": empty, "G": empty, "N": MISSING},
            {"path": "mode-conflict", "C": executable, "G": empty, "N": MISSING},
        ])
        report = self.merge.merge(manifest, self.root / "candidate")
        self.assertEqual(report["files"][0]["resolved"]["executable"], False)
        self.assertEqual(report["files"][1]["resolved"], MISSING)
        self.assertEqual(report["files"][2]["status"], "CONFLICT")

    def test_user_deleted_file_stays_missing_when_component_unchanged(self):
        baseline = self.payload("unchanged", b"component content")
        manifest = self.manifest("inputs.json", [{"path": "deleted-by-user", "C": MISSING, "G": baseline, "N": baseline}])
        report = self.merge.merge(manifest, self.root / "candidate")
        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["files"][0]["selected"], "C")
        self.assertEqual(report["files"][0]["resolved"], MISSING)

    def test_shared_dependency_survives_removed_owner_as_one_explicit_row(self):
        dependency = self.payload("shared", b"still needed by workflow-b")
        manifest = self.manifest("inputs.json", [{"path": "shared.md", "C": dependency, "G": dependency,
                                                    "N": dependency, "owners": ["workflow-b"]}])
        report = self.merge.merge(manifest, self.root / "candidate")
        self.assertEqual(len(report["files"]), 1)
        self.assertEqual(report["files"][0]["owners"], ["workflow-b"])
        self.write_target("shared.md", b"still needed by workflow-b")
        self.write_target("workflow-a.md", b"retired")
        rows = [{"path": "shared.md", "action": "update", "expected": dependency, "desired": dependency},
                self.apply_item("workflow-a.md", b"retired", None, "remove")]
        applied = self.run_apply(rows)
        self.assertEqual(applied["files"][0]["status"], "ALREADY_DESIRED")
        self.assertEqual((self.target / "shared.md").read_bytes(), b"still needed by workflow-b")
        self.assertFalse((self.target / "workflow-a.md").exists())

    def test_merge_reads_all_inputs_before_creating_output(self):
        state = self.payload("old", b"old")
        manifest = self.manifest("inputs.json", [
            {"path": "a", "C": state, "G": state, "N": state},
            {"path": "b", "C": state, "G": state, "N": {"file": "absent", "executable": False}},
        ])
        with self.assertRaises(self.merge.fs.PlanError):
            self.merge.merge(manifest, self.root / "candidate")
        self.assertFalse((self.root / "candidate").exists())

    def test_merge_does_not_overwrite_existing_candidate(self):
        state = self.payload("old", b"old")
        manifest = self.manifest("inputs.json", [{"path": "a", "C": state, "G": state, "N": state}])
        output = self.root / "candidate"
        output.mkdir()
        (output / "keep").write_bytes(b"keep")
        with self.assertRaises(self.merge.fs.PlanError):
            self.merge.merge(manifest, output)
        self.assertEqual((output / "keep").read_bytes(), b"keep")

    def test_parent_relative_read_reference_is_supported(self):
        shared = self.root / "shared"
        shared.mkdir()
        (shared / "old").write_bytes(b"old")
        (shared / "new").write_bytes(b"new")
        expected = {"file": "../shared/old", "executable": False}
        desired = {"file": "../shared/new", "executable": False}
        manifest = self.manifest("inputs.json", [{"path": "a", "C": expected, "G": expected, "N": desired}])
        report = self.merge.merge(manifest, self.root / "candidate")
        self.assertEqual(report["status"], "READY")
        self.write_target("a", b"old")
        self.run_apply([{"path": "a", "action": "update", "expected": expected, "desired": desired}])
        self.assertEqual((self.target / "a").read_bytes(), b"new")

    def test_symlink_payload_and_nonboolean_state_rejected(self):
        source = self.payload("plain", b"plain")
        (self.inputs / "linked").symlink_to(self.inputs / "plain")
        for invalid in ({"file": "linked", "executable": False},
                        {"file": "plain", "executable": 1}, {"missing": 1}):
            with self.subTest(state=invalid):
                manifest = self.manifest("inputs.json", [{"path": "a", "C": source, "G": source, "N": invalid}])
                with self.assertRaises(self.merge.fs.PlanError):
                    self.merge.merge(manifest, self.root / "candidate")
                self.assertFalse((self.root / "candidate").exists())

    def test_apply_create_update_remove_and_leave_unmanaged(self):
        update = self.apply_item()
        create = self.apply_item("created", None, b"created", "create")
        remove = self.apply_item("removed", b"removed", None, "remove")
        unmanaged = self.apply_item("custom", b"older", b"ignored", "leave-unmanaged")
        self.write_target("file.txt", b"old")
        self.write_target("removed", b"removed")
        self.write_target("custom", b"current user bytes")
        self.write_target("unrelated", b"unrelated")
        report = self.run_apply([update, create, remove, unmanaged])
        self.assertEqual(report["status"], "APPLIED")
        self.assertEqual((self.target / "file.txt").read_bytes(), b"new")
        self.assertEqual((self.target / "created").read_bytes(), b"created")
        self.assertFalse((self.target / "removed").exists())
        self.assertEqual((self.target / "custom").read_bytes(), b"current user bytes")
        self.assertEqual((self.target / "unrelated").read_bytes(), b"unrelated")

    def test_preflight_mismatch_makes_no_writes(self):
        first, second = self.apply_item("a"), self.apply_item("b")
        self.write_target("a", b"old")
        self.write_target("b", b"user changed")
        with self.assertRaises(self.apply.fs.PlanError):
            self.run_apply([first, second])
        self.assertEqual((self.target / "a").read_bytes(), b"old")
        self.assertFalse((self.target / "reports").exists())

    def test_preflight_checks_invalid_action_before_any_write(self):
        first, second = self.apply_item("a"), self.apply_item("b", action="create")
        self.write_target("a", b"old")
        with self.assertRaises(self.apply.fs.PlanError):
            self.run_apply([first, second])
        self.assertEqual((self.target / "a").read_bytes(), b"old")

    def test_resume_reuses_desired_files_and_replaces_declared_report(self):
        first, second = self.apply_item("a"), self.apply_item("b")
        self.write_target("a", b"new")
        self.write_target("b", b"old")
        self.write_target("reports/apply.json", b"previous diagnostic")
        report = self.run_apply([first, second])
        self.assertEqual([r["status"] for r in report["files"]], ["ALREADY_DESIRED", "APPLIED"])
        again = self.run_apply([first, second])
        self.assertEqual([r["status"] for r in again["files"]], ["ALREADY_DESIRED", "ALREADY_DESIRED"])
        self.assertEqual(json.loads((self.target / "reports/apply.json").read_text())["kind"], "r3-apply-diagnostic")

    def test_permission_only_update_then_second_upgrade_preserves_user_change(self):
        old = self.payload("old", b"same", False)
        new = self.payload("new", b"same", True)
        self.write_target("run", b"same", False)
        self.run_apply([{"path": "run", "action": "update", "expected": old, "desired": new}])
        self.assertTrue((self.target / "run").stat().st_mode & 0o111)
        self.write_target("run", b"user", True)
        current = self.payload("current", b"user", True)
        manifest = self.manifest("inputs.json", [{"path": "run", "C": current, "G": new, "N": new}])
        candidate = self.merge.merge(manifest, self.root / "second")
        self.assertEqual(candidate["files"][0]["selected"], "C")

    def test_rename_is_explicit_create_then_remove(self):
        self.write_target("old-name", b"same")
        rows = [self.apply_item("new-name", None, b"same", "create"),
                self.apply_item("old-name", b"same", None, "remove")]
        report = self.run_apply(rows)
        self.assertEqual([r["path"] for r in report["files"]], ["new-name", "old-name"])
        self.assertEqual((self.target / "new-name").read_bytes(), b"same")
        self.assertFalse((self.target / "old-name").exists())

    def test_duplicate_and_parent_child_paths_fail_preflight(self):
        for names in [("a", "a"), ("a", "a/b")]:
            with self.subTest(names=names):
                rows = [self.apply_item("payload-" + str(index), None, b"new", "create") for index, name in enumerate(names)]
                for row, name in zip(rows, names):
                    row["path"] = name
                with self.assertRaises(self.apply.fs.PlanError):
                    self.run_apply(rows)
                self.assertFalse((self.target / "a").exists())

    def test_traversal_symlink_and_directory_targets_rejected(self):
        outside = self.root / "outside"
        outside.write_bytes(b"old")
        (self.target / "link").symlink_to(outside)
        (self.target / "directory").mkdir()
        for name in ("../outside", "link", "directory"):
            with self.subTest(name=name):
                row = self.apply_item("input")
                row["path"] = name
                with self.assertRaises(self.apply.fs.PlanError):
                    self.run_apply([row])
        self.assertEqual(outside.read_bytes(), b"old")

    def test_result_cannot_overlap_managed_path(self):
        row = self.apply_item("file.txt")
        self.write_target("file.txt", b"old")
        manifest = self.manifest("apply.json", [row])
        for result in ("file.txt", "file.txt/report", "../outside"):
            with self.subTest(result=result), self.assertRaises(self.apply.fs.PlanError):
                self.apply.apply(manifest, self.target, result)
        self.assertEqual((self.target / "file.txt").read_bytes(), b"old")

    def test_existing_case_aliases_cannot_delete_or_overwrite_managed_file(self):
        path = self.write_target("README.md", b"same")
        if not (self.target / "Readme.md").exists():
            self.skipTest("target filesystem distinguishes filename case")
        rows = [self.apply_item("Readme.md", None, b"same", "create"),
                self.apply_item("README.md", b"same", None, "remove")]
        with mock.patch.object(self.apply.fs, "atomic_write") as write:
            with self.assertRaises(self.apply.fs.PlanError):
                self.run_apply(rows)
            row = self.apply_item("README.md", b"same", b"new")
            manifest = self.manifest("apply.json", [row])
            with self.assertRaises(self.apply.fs.PlanError):
                self.apply.apply(manifest, self.target, "readme.MD")
            write.assert_not_called()
        self.assertEqual(path.read_bytes(), b"same")
        self.assertEqual(list(self.target.iterdir()), [path])

    def test_missing_case_aliases_and_ancestor_aliases_fail_before_writes(self):
        witness = self.write_target("CaseWitness", b"")
        insensitive = (self.target / "casewitness").exists()
        witness.unlink()
        if not insensitive or sys.platform != "darwin":
            self.skipTest("missing-name case semantics are natively queried on macOS")
        scenarios = [
            (["New.md", "new.MD"], "report.json"),
            (["New", "new/child.md"], "report.json"),
            (["New/one.md", "new/ONE.md"], "report.json"),
            (["outputs/config.json"], "OUTPUTS/CONFIG.JSON"),
            (["outputs"], "OUTPUTS/report.json"),
        ]
        for names, result in scenarios:
            with self.subTest(names=names, result=result):
                rows = []
                for index, name in enumerate(names):
                    row = self.apply_item("alias-payload-" + str(index), None, b"new", "create")
                    row["path"] = name
                    rows.append(row)
                manifest = self.manifest("apply.json", rows)
                with mock.patch.object(self.apply.fs, "atomic_write") as write:
                    with self.assertRaises(self.apply.fs.PlanError):
                        self.apply.apply(manifest, self.target, result)
                    write.assert_not_called()
                self.assertEqual(list(self.target.iterdir()), [])
        # The ancestor already exists under a different spelling, while both
        # leaf spellings are still missing.
        (self.target / "Outputs").mkdir()
        rows = [self.apply_item("Outputs/new.md", None, b"new", "create")]
        manifest = self.manifest("apply.json", rows)
        with self.assertRaises(self.apply.fs.PlanError):
            self.apply.apply(manifest, self.target, "outputs/NEW.md")
        self.assertEqual(list((self.target / "Outputs").iterdir()), [])

    def test_unicode_normalization_aliases_fail_before_writes_on_macos(self):
        if sys.platform != "darwin":
            self.skipTest("missing-name Unicode semantics here are macOS-specific")
        pairs = [("caf\u00e9.md", "cafe\u0301.md")]
        if os.pathconf(self.target, 11) == 0:
            pairs.append(("strasse.md", "stra\u00dfe.md"))
        for names in pairs:
            with self.subTest(names=names):
                rows = []
                for index, name in enumerate(names):
                    row = self.apply_item("unicode-payload-" + str(index), None, b"new", "create")
                    row["path"] = name
                    rows.append(row)
                with self.assertRaises(self.apply.fs.PlanError):
                    self.run_apply(rows)
                self.assertEqual(list(self.target.iterdir()), [])

    def test_sensitive_volume_keeps_distinct_missing_names(self):
        # Exercise the read-only Darwin query's sensitive result, even when
        # the test's own volume is insensitive. This is not a second OS run.
        paths = self.apply.fs.validate_paths([{"path": "Config"}, {"path": "config/child"}])
        with mock.patch.object(self.apply.fs.sys, "platform", "darwin"), \
                mock.patch.object(self.apply.fs.os, "pathconf", return_value=1):
            self.apply.fs.validate_target_paths(self.target, paths)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_sources_inside_target_rejected(self):
        row = self.apply_item("file.txt")
        self.write_target("file.txt", b"old")
        # The manifest's own root would make its payloads writable too.
        (self.target / "old-file.txt").write_bytes(b"old")
        (self.target / "new-file.txt").write_bytes(b"new")
        manifest = self.target / "apply.json"
        manifest.write_text(json.dumps({"format_version": 1, "files": [row]}))
        with self.assertRaises(self.apply.fs.PlanError):
            self.apply.apply(manifest, self.target, "report.json")
        self.assertEqual((self.target / "file.txt").read_bytes(), b"old")

    def test_target_case_alias_cannot_hide_manifest_or_payload_inside_target(self):
        alias = self.target.with_name(self.target.name.upper())
        if not alias.exists():
            self.skipTest("target filesystem distinguishes directory case")
        row = self.apply_item("file.txt")
        path = self.write_target("file.txt", b"old")
        # Manifest lives in the target; both payloads genuinely remain outside.
        for key in ("expected", "desired"):
            row[key]["file"] = "../inputs/" + row[key]["file"]
        manifest = self.target / "apply.json"
        original = json.dumps({"format_version": 1, "files": [row]}).encode()
        manifest.write_bytes(original)
        with mock.patch.object(self.apply.fs, "atomic_write") as write:
            with self.assertRaisesRegex(self.apply.fs.PlanError, "manifest must remain outside"):
                self.apply.apply(manifest, alias, "report.json")
            write.assert_not_called()
        self.assertEqual(manifest.read_bytes(), original)
        # Manifest is outside, but its expected payload is inside the target.
        payload = self.write_target("old-payload", b"old")
        row = self.apply_item("file.txt")
        row["expected"]["file"] = "../target/old-payload"
        manifest = self.manifest("apply.json", [row])
        with mock.patch.object(self.apply.fs, "atomic_write") as write:
            with self.assertRaisesRegex(self.apply.fs.PlanError, "payload source must remain outside"):
                self.apply.apply(manifest, alias, "old-payload")
            write.assert_not_called()
        self.assertEqual(payload.read_bytes(), b"old")
        self.assertEqual(path.read_bytes(), b"old")
        self.assertFalse((self.target / "report.json").exists())

    def test_later_user_change_is_not_overwritten(self):
        rows = [self.apply_item("a"), self.apply_item("b")]
        self.write_target("a", b"old")
        self.write_target("b", b"old")
        original = self.apply.fs.atomic_write

        def write_then_change(path, *args, **kwargs):
            original(path, *args, **kwargs)
            if path == self.target / "a":
                (self.target / "b").write_bytes(b"new user change")

        with mock.patch.object(self.apply.fs, "atomic_write", side_effect=write_then_change):
            with self.assertRaises(self.apply.fs.PlanError):
                self.run_apply(rows)
        self.assertEqual((self.target / "a").read_bytes(), b"new")
        self.assertEqual((self.target / "b").read_bytes(), b"new user change")
        self.assertEqual(json.loads((self.target / "reports/apply.json").read_text())["status"], "INCOMPLETE")

    def test_replace_failure_cleans_temp_and_resume_only_changes_remainder(self):
        rows = [self.apply_item("a"), self.apply_item("b")]
        self.write_target("a", b"old")
        self.write_target("b", b"old")
        original = os.replace

        def fail_second(source, destination):
            if Path(destination) == self.target / "b":
                raise OSError("test interruption before second replacement")
            return original(source, destination)

        with mock.patch.object(self.apply.fs.os, "replace", side_effect=fail_second):
            with self.assertRaises(OSError):
                self.run_apply(rows)
        self.assertEqual((self.target / "a").read_bytes(), b"new")
        self.assertEqual((self.target / "b").read_bytes(), b"old")
        self.assertEqual(list(self.target.rglob("*.r3-*")), [])
        report = self.run_apply(rows)
        self.assertEqual([x["status"] for x in report["files"]], ["ALREADY_DESIRED", "APPLIED"])

    def test_unknown_baseline_explicit_incremental_apply(self):
        self.write_target("custom", b"old")
        report = self.run_apply([self.apply_item("custom")])
        self.assertEqual(report["status"], "APPLIED")
        # apply has no G argument: a reviewed explicit expected/desired intent
        # can implement project-only changes without inventing a baseline.
        self.assertEqual((self.target / "custom").read_bytes(), b"new")

    def test_isolated_cli_runs_without_pythonpath(self):
        row = self.apply_item()
        self.write_target("file.txt", b"old")
        manifest = self.manifest("apply.json", [row])
        environment = dict(os.environ, PYTHONPATH="/does/not/exist", PYTHONDONTWRITEBYTECODE="1")
        completed = subprocess.run([sys.executable, "-I", "-B", str(HELPERS / "apply.py"),
                                    "--manifest", str(manifest), "--target", str(self.target),
                                    "--result", "reports/cli.json"],
                                   env=environment, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual((self.target / "file.txt").read_bytes(), b"new")
        state = row["desired"]
        merge_manifest = self.manifest("inputs.json", [{"path": "file.txt", "C": state, "G": None, "N": state}])
        completed = subprocess.run([sys.executable, "-I", "-B", str(HELPERS / "merge.py"),
                                    "--inputs", str(merge_manifest), "--output", str(self.root / "cli-candidate")],
                                   env=environment, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "PROJECT_INCREMENTAL_REQUIRED")
        self.assertFalse((HELPERS / "__pycache__").exists())


if __name__ == "__main__":
    unittest.main()
