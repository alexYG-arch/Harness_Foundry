"""Directory-entry observations and local fixture execution; no Qt SDK claim."""

from copy import deepcopy
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from harness_foundry_factory.build_effects import effect_path, snapshot_effects, compare_effects
from harness_foundry_factory.build_runtime import _validate_scope
from harness_foundry_factory.build_types import RequestValidationError
import test_build_runtime as runtime_fixture


def contract(allowed=(), required=(), preserve=()):
    return {"allowed": list(allowed), "required": list(required), "must_preserve": list(preserve)}


FRAMEWORK_SCRIPT = """from pathlib import Path
bundle = Path('build/QtCore.framework')
version = bundle / 'Versions/A'
(version / 'Resources').mkdir(parents=True)
(version / 'QtCore').write_bytes(b'fixture-not-Qt-SDK')
(version / 'Resources/Info.plist').write_text('fixture')
(bundle / 'Versions/Current').symlink_to('A', target_is_directory=True)
(bundle / 'QtCore').symlink_to('Versions/Current/QtCore')
(bundle / 'Resources').symlink_to('Versions/Current/Resources', target_is_directory=True)
"""
FRAMEWORK_FILES = [
    "build/QtCore.framework/Versions/A/QtCore",
    "build/QtCore.framework/Versions/A/Resources/Info.plist",
    "build/QtCore.framework/Versions/Current",
    "build/QtCore.framework/QtCore",
    "build/QtCore.framework/Resources",
]


class BuildEffectsLinksTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.workspace = self.root / "workspace"
        (self.workspace / "build").mkdir(parents=True)

    def fixture(self):
        obj = runtime_fixture.BuildRuntimeTests(methodName="runTest")
        obj.setUp()
        self.addCleanup(obj.doCleanups)
        obj.plan["schema_version"] = "1.1"
        task = obj.plan["workpacks"][0]
        obj.scope["task_write_roots"][task["workpack_id"]].append("build")
        task["effects"] = contract(["src/reader.py"], ["src/reader.py"])
        return obj, task

    def scan(self, rules=None, roots=("build",)):
        return snapshot_effects(self.workspace, roots, rules or contract())

    def framework(self):
        # Execute only the fixture's local construction, with its paths rooted
        # in the isolated workspace; real Qt/CMake is separately qualified.
        code = FRAMEWORK_SCRIPT.replace("Path('build/QtCore.framework')", "Path(" + repr(str(self.workspace / "build/QtCore.framework")) + ")")
        exec(code, {})

    def test_existing_framework_records_entries_and_real_version_files(self):
        self.framework()
        before = self.scan()
        self.assertEqual(before["build/QtCore.framework/Versions/Current"], {"kind": "symlink", "target": "A"})
        self.assertEqual(before["build/QtCore.framework/QtCore"], {"kind": "symlink", "target": "Versions/Current/QtCore"})
        self.assertEqual(before["build/QtCore.framework/Versions/A/QtCore"]["kind"], "file")
        self.assertNotIn("build/QtCore.framework/Versions/Current/QtCore", before)
        self.assertNotIn("build/QtCore.framework/Resources/Info.plist", before)
        self.assertEqual(compare_effects(before, self.scan(), contract())["status"], "PASS")

    def test_first_framework_build_completes_declared_local_task_and_checks(self):
        obj, task = self.fixture()
        task["effects"]["allowed"] += FRAMEWORK_FILES
        task["effects"]["required"].append(FRAMEWORK_FILES[0])
        task["local_argv"][-1] += "\n" + FRAMEWORK_SCRIPT
        obj.prepare()
        self.assertEqual(obj.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        result = obj.events("BUILD_ATTEMPT_FINISHED")[0]["payload"]
        self.assertEqual(result["effects"]["status"], "PASS")
        self.assertTrue((obj.workspace / "build/QtCore.framework/Versions/Current").is_symlink())
        self.assertEqual([row["phase"] for row in obj.runner.invocations],
                         ["IMPLEMENTATION", "VERIFICATION", "VERIFICATION", "IMPLEMENTATION", "VERIFICATION"])

    def test_dangling_cyclic_and_external_links_never_read_target_contents(self):
        outside = self.root / "outside.txt"
        outside.write_text("not an effect input")
        targets = {"missing": "no-such-target", "cycle": "cycle", "external": str(outside),
                   "directory": str(self.root)}
        for name, target in targets.items():
            (self.workspace / "build" / name).symlink_to(target)
        with patch.object(Path, "open", side_effect=AssertionError("link targets must not be opened")):
            rows = self.scan()
        for name, target in targets.items():
            self.assertEqual(rows["build/" + name], {"kind": "symlink", "target": target})
        self.assertEqual(set(rows), {"build", *("build/" + name for name in targets)})
        self.assertEqual(outside.read_text(), "not an effect input")

    def test_link_create_delete_redirect_and_file_replacement_keep_exact_permissions(self):
        entry = self.workspace / "build/link"
        allowed = contract(["build/link"])
        def check_change(action):
            before = self.scan()
            action()
            after = self.scan()
            self.assertEqual(compare_effects(before, after, allowed)["status"], "PASS")
            denied = compare_effects(before, after, contract())
            self.assertEqual(denied["status"], "VIOLATION")
            self.assertEqual(denied["violations"], [{"path": "build/link", "reason": "UNDECLARED_FILE_EFFECT"}])
        check_change(lambda: entry.symlink_to("first"))
        check_change(lambda: (entry.unlink(), entry.symlink_to("second")))
        check_change(lambda: (entry.unlink(), entry.write_text("ordinary")))
        check_change(lambda: (entry.unlink(), entry.symlink_to("first")))
        check_change(entry.unlink)

    def test_required_ordinary_file_cannot_be_fulfilled_by_link(self):
        obj, task = self.fixture()
        task["effects"]["allowed"].append("src/alias")
        task["effects"]["required"].append("src/alias")
        task["local_argv"][-1] += "; Path('src/alias').symlink_to('reader.py')"
        obj.prepare()
        self.assertNotEqual(obj.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        finished = obj.events("BUILD_ATTEMPT_FINISHED")[0]["payload"]
        self.assertEqual(finished["effects"]["status"], "MISSING_REQUIRED")
        self.assertEqual(finished["effects"]["missing_required"], ["src/alias"])
        self.assertFalse((obj.workspace / "outputs/summary.json").exists())

    def test_preserved_link_is_not_an_ordinary_file_and_never_dispatches(self):
        obj, task = self.fixture()
        (obj.workspace / "src/user.txt").symlink_to("missing")
        task["effects"]["must_preserve"] = ["src/user.txt"]
        obj.prepare()
        self.assertNotEqual(obj.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(obj.runner.invocations, [])
        baseline = snapshot_effects(obj.workspace, ["src"], task["effects"])
        self.assertEqual(baseline["src/user.txt"]["kind"], "symlink")
        self.assertFalse(obj.events("BUILD_EFFECTS_BASELINE"))

    def test_preserved_ordinary_file_change_is_still_detected(self):
        path = self.workspace / "keep.txt"
        path.write_text("original")
        rules = contract(preserve=["keep.txt"])
        before = self.scan(rules)
        self.assertEqual(compare_effects(before, self.scan(rules), rules)["status"], "PASS")
        path.write_text("changed")
        self.assertEqual(compare_effects(before, self.scan(rules), rules)["violations"],
                         [{"path": "keep.txt", "reason": "PRESERVED_FILE_CHANGED"}])

    def test_allowed_is_not_an_observation_filter(self):
        path = self.workspace / "build/unlisted.txt"
        path.write_text("before")
        rules = contract(["build/permitted.txt"])
        before = self.scan(rules)
        path.write_text("after")
        self.assertEqual(compare_effects(before, self.scan(rules), rules)["status"], "VIOLATION")

    def test_unrelated_root_is_omitted_only_by_actual_write_root_selection(self):
        self.framework()
        (self.workspace / "src").mkdir()
        rules = contract(["src/new.txt"], ["src/new.txt"])
        before = self.scan(rules, ["src"])
        (self.workspace / "src/new.txt").write_text("legitimate")
        after = self.scan(rules, ["src"])
        self.assertFalse(any(name.startswith("build") for name in after))
        self.assertEqual(compare_effects(before, after, rules)["status"], "PASS")

    def test_final_external_link_scope_records_entry_without_expanding_permissions(self):
        obj, task = self.fixture()
        (obj.workspace / "build").mkdir()
        target = obj.root / "outside-sdk"
        target.mkdir()
        (obj.workspace / "build/SDK").symlink_to(target, target_is_directory=True)
        task["effects"]["allowed"].append("build/SDK")
        expected = deepcopy(obj.scope)
        _validate_scope(obj.store, obj.plan, obj.scope)
        self.assertEqual(obj.scope, expected)
        obj.prepare()
        self.assertEqual(obj.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertTrue((obj.workspace / "build/SDK").is_symlink())

    def test_link_ancestor_is_rejected_by_scope_and_observation(self):
        obj, task = self.fixture()
        (obj.workspace / "build/real").mkdir(parents=True)
        (obj.workspace / "build/alias").symlink_to("real", target_is_directory=True)
        task["effects"]["allowed"].append("build/alias/child.txt")
        with self.assertRaisesRegex(RequestValidationError, "symlink ancestor"):
            _validate_scope(obj.store, obj.plan, obj.scope)
        with self.assertRaisesRegex(RequestValidationError, "symlink ancestor"):
            snapshot_effects(obj.workspace, ["build/alias/child.txt"], contract())

    def test_effect_paths_keep_canonical_and_ancestor_directory_requirements(self):
        for name in ("../outside", "/outside", "build//name", "build/./name", "build\\name"):
            with self.subTest(name=name), self.assertRaises(RequestValidationError):
                effect_path(self.workspace, name)
        (self.workspace / "build/file").write_text("ordinary")
        with self.assertRaisesRegex(RequestValidationError, "ancestor must be a directory"):
            effect_path(self.workspace, "build/file/child")
        self.assertEqual(effect_path(self.workspace, "build/new/parent/file"),
                         self.workspace / "build/new/parent/file")

    def test_owned_tree_cleanup_keeps_external_link_target(self):
        target = self.root / "external-sdk"
        target.mkdir()
        (target / "keep.txt").write_text("unchanged")
        (self.workspace / "build/SDK").symlink_to(target, target_is_directory=True)
        self.scan()
        shutil.rmtree(self.workspace / "build")
        self.assertEqual((target / "keep.txt").read_text(), "unchanged")
