"""S1 fixture/S2 helper integration; no model, network or Harness acceptance.

Reference candidates are test oracles, not historical accepted projects. All
mutations take place in an isolated TemporaryDirectory, not in shipped inputs.
"""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


EXAMPLE = Path(__file__).resolve().parents[1] / "examples/harness-composition-upgrade"


def json_read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def tree_bytes(path):
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()}


class CompositionUpgradeIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="r3-integration-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        # Move the fixtures away from the checkout before exercising relative
        # references; source-tree availability cannot conceal a missing input.
        self.inputs = self.root / "readonly"
        shutil.copytree(EXAMPLE, self.inputs)
        self.original = tree_bytes(self.inputs)
        self.target = self.root / "target"

    def command(self, helper, *args, expected=0):
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(self.inputs / "helpers" / helper), *map(str, args)],
            cwd=self.root, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def apply_scenario(self, base, scenario):
        return self.command("apply.py", "--manifest", base / "scenarios" / scenario / "apply.json",
                            "--target", self.target, "--result", "outputs/apply-result.json")

    def assert_reference(self, reference):
        for relative, expected in tree_bytes(reference).items():
            self.assertEqual((self.target / relative).read_bytes(), expected, relative)
        self.assertEqual((self.target / "unrelated.txt").read_bytes(), b"user-owned\x00bytes\n")

    def independent_check(self, name, expected):
        completed = subprocess.run(
            [sys.executable, "-I", "-B", str(self.inputs / "verifier/check_mechanisms.py"),
             "--kind", name, "--target", str(self.target), "--expected",
             str(self.inputs / "verifier/expectations" / (expected + ".json"))],
            cwd=self.root, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["result"], "PASS")

    def exercise_two_upgrades(self, name):
        base = self.inputs / "mechanisms" / name
        shutil.copytree(base / "custom/current", self.target)
        (self.target / "unrelated.txt").write_bytes(b"user-owned\x00bytes\n")
        for number, version in ((1, 2), (2, 3)):
            scenario = "upgrade-" + str(number)
            output = self.root / ("candidate-" + str(number))
            self.command("merge.py", "--inputs", base / "scenarios" / scenario / "inputs.json",
                         "--output", output, expected=2)
            candidate = json_read(output / "candidate.json")
            config = next(row for row in candidate["files"] if row["path"] == "config.json")
            self.assertEqual(config["status"], "CONFLICT")
            self.assertIsNone(config["resolved"])
            # Intentional conflict resolution comes from the fixed independent
            # reference, not the merger silently dropping user configuration.
            self.apply_scenario(base, scenario)
            self.assert_reference(base / "expected" / ("after-v" + str(version)))
            self.independent_check(name, name + "-v" + str(version))
        self.assertEqual(tree_bytes(self.inputs), self.original)
        return base

    def test_doc_two_upgrades_then_no_baseline_incremental(self):
        base = self.exercise_two_upgrades("doc")
        old_notes = (self.target / "USER_NOTES.md").read_bytes()
        output = self.root / "incremental-candidate"
        self.command("merge.py", "--inputs", base / "scenarios/incremental/inputs.json",
                     "--output", output, expected=2)
        report = json_read(output / "candidate.json")
        self.assertEqual(report["status"], "PROJECT_INCREMENTAL_REQUIRED")
        self.apply_scenario(base, "incremental")
        self.assert_reference(base / "expected/after-incremental")
        self.independent_check("doc", "doc-incremental")
        self.assertEqual((self.target / "USER_NOTES.md").read_bytes(), old_notes)
        self.assertEqual(tree_bytes(self.inputs), self.original)

    def test_api_two_upgrades_keep_timeout_and_true_component_baseline(self):
        base = self.exercise_two_upgrades("api")
        self.assertEqual(json_read(self.target / "config.json")["timeout"], 20)
        second = json_read(base / "scenarios/upgrade-2/inputs.json")
        config = next(row for row in second["files"] if row["path"] == "config.json")
        manifest_root = base / "scenarios/upgrade-2"
        self.assertEqual(json_read(manifest_root / config["G"]["file"])["timeout"], 15)
        self.assertEqual(json_read(manifest_root / config["C"]["file"])["timeout"], 20)

    def test_resume_reuses_finished_file_and_new_user_edit_requires_integration(self):
        base = self.inputs / "mechanisms/api"
        shutil.copytree(base / "custom/current", self.target)
        source = base / "scenarios/upgrade-1/apply.json"
        plan = json_read(source)
        first, second = plan["files"][:2]
        # Simulate a stopped process after one replacement, without asserting
        # that a Harness command capture exists or granting replay authority.
        desired = source.parent / first["desired"]["file"]
        shutil.copyfile(desired, self.target / first["path"])
        changed = self.target / second["path"]
        changed.write_bytes(changed.read_bytes() + b"\n# later user modification\n")
        before = tree_bytes(self.target)
        self.command("apply.py", "--manifest", source, "--target", self.target,
                     "--result", "outputs/apply-result.json", expected=1)
        self.assertEqual(tree_bytes(self.target), before)
        # An explicit revised candidate accounts for the user's later change.
        revised = deepcopy(plan)
        revision = self.root / "revised"
        revision.mkdir()
        for index, row in enumerate(revised["files"]):
            for key in ("expected", "desired"):
                if "file" in row[key]:
                    payload = revision / (str(index) + "-" + key)
                    payload.write_bytes((source.parent / row[key]["file"]).read_bytes())
                    row[key]["file"] = payload.name
        (revision / "1-expected").write_bytes(changed.read_bytes())
        (revision / "1-desired").write_bytes((revision / "1-desired").read_bytes() + b"\n# later user modification\n")
        updated = revision / "apply.json"
        updated.write_text(json.dumps(revised), encoding="utf-8")
        self.command("apply.py", "--manifest", updated, "--target", self.target,
                     "--result", "outputs/apply-result.json")
        report = json_read(self.target / "outputs/apply-result.json")
        self.assertEqual(report["files"][0]["status"], "ALREADY_DESIRED")
        self.assertTrue(changed.read_bytes().endswith(b"# later user modification\n"))
        before = tree_bytes(self.target)
        self.command("apply.py", "--manifest", updated, "--target", self.target,
                     "--result", "outputs/apply-result.json")
        after = tree_bytes(self.target)
        before.pop("outputs/apply-result.json")
        after.pop("outputs/apply-result.json")
        self.assertEqual(before, after)
        self.assertEqual(tree_bytes(self.inputs), self.original)


if __name__ == "__main__":
    unittest.main()
