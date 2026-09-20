"""Committed-source build tests in disposable Git repos, never the real index."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("committed_packager", ROOT / "devtools/package_committed_release.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class CommittedDistributionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repository = self.root / "source"
        for name in ("src", "resources", "docs", "examples", "devtools"):
            shutil.copytree(ROOT / name, self.repository / name, ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("LICENSE", "pyproject.toml", "FACTORY_MANIFEST.json"):
            shutil.copy2(ROOT / name, self.repository / name)
        self.git("init", "--quiet")
        self.git("add", ".")
        self.commit = self.commit_source()
        self.output = self.root / "release.zip"

    def git(self, *args):
        result = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
            "-c", "user.name=Foundry Test Fixture", "-c", "user.email=fixture@example.invalid",
            "-C", str(self.repository), *args], capture_output=True, text=True, check=False, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def commit_source(self):
        self.git("commit", "--quiet", "-m", "TEST ONLY source snapshot")
        return self.git("rev-parse", "HEAD")

    def package(self, revision=None, output=None):
        return builder.package_revision(revision or self.commit, output or self.output, repository=self.repository)

    def test_dirty_and_untracked_inputs_and_worktree_builder_never_enter_archive(self):
        readme = self.repository / "resources/generic_release/README.md"
        expected = readme.read_bytes()
        readme.write_text("UNCOMMITTED CONTENT MUST NOT SHIP")
        (self.repository / "devtools/package_generic_release.py").write_text("raise RuntimeError('dirty assembler used')")
        (self.repository / "resources/generic_release/private.txt").write_text("UNTRACKED MUST NOT SHIP")
        before_status = self.git("status", "--porcelain")
        result = self.package()
        self.assertEqual(result["source_revision"], self.commit)
        self.assertFalse(result["source_worktree_used"])
        self.assertFalse(result["release_accepted"])
        self.assertEqual(len(result["archive_sha256"]), 64)
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.read("README.md"), expected)
            self.assertFalse(any("private.txt" in name or name.startswith(".git/") for name in archive.namelist()))
            manifest = json.loads(archive.read("PACKAGE_MANIFEST.json"))
            self.assertNotIn("sha256", json.dumps(manifest))
            relocated = self.root / "relocated"
            archive.extractall(relocated)
        loaded = subprocess.run([sys.executable, "-I", "-S", "-B", str(relocated / "tools/hffactory.py"),
                                 "version", "--json"], capture_output=True, text=True, check=True, timeout=30)
        self.assertEqual(json.loads(loaded.stdout)["product_route"], "GENERIC_REVIEWED_BUILD")
        self.assertEqual(self.git("rev-parse", "HEAD"), self.commit)
        self.assertEqual(self.git("status", "--porcelain"), before_status)
        self.assertEqual(self.git("tag", "--list"), "")

    def test_explicit_prior_commit_not_current_head_supplies_content(self):
        readme = self.repository / "resources/generic_release/README.md"
        before = readme.read_bytes()
        readme.write_bytes(before + b"\nCOMMITTED LATER\n")
        self.git("add", ".")
        latest = self.commit_source()
        first = self.package()
        second_output = self.root / "latest.zip"
        second = self.package(latest, second_output)
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.read("README.md"), before)
        with zipfile.ZipFile(second_output) as archive:
            self.assertIn(b"COMMITTED LATER", archive.read("README.md"))
        self.assertNotEqual(first["archive_sha256"], second["archive_sha256"])

    def test_same_commit_reproduces_same_archive_and_never_overwrites(self):
        self.package()
        original = self.output.read_bytes()
        second = self.root / "again.zip"
        self.package(output=second)
        self.assertEqual(second.read_bytes(), original)
        with self.assertRaisesRegex(ValueError, "absent absolute"):
            self.package()
        self.assertEqual(self.output.read_bytes(), original)

    def test_unknown_revision_and_missing_committed_builder_fail_without_archive(self):
        with self.assertRaises(ValueError):
            self.package("not-a-real-revision")
        self.assertFalse(self.output.exists())
        self.git("rm", "devtools/package_generic_release.py")
        revision = self.commit_source()
        with self.assertRaisesRegex(ValueError, "does not contain"):
            self.package(revision)
        self.assertFalse(self.output.exists())

    def test_committed_version_drift_or_missing_resource_is_not_patched_from_worktree(self):
        manifest_path = self.repository / "FACTORY_MANIFEST.json"
        original = manifest_path.read_text()
        manifest = json.loads(original)
        manifest["version"] = "9.8.7"
        manifest_path.write_text(json.dumps(manifest))
        self.git("add", ".")
        revision = self.commit_source()
        manifest_path.write_text(original)  # A local repair cannot repair the selected commit.
        with self.assertRaisesRegex(ValueError, "product version differs"):
            self.package(revision)
        self.assertFalse(self.output.exists())
        self.git("add", ".")
        self.git("rm", "LICENSE")
        revision = self.commit_source()
        with self.assertRaisesRegex(ValueError, "committed assembler failed"):
            self.package(revision)
        self.assertFalse(self.output.exists())

    def test_preflight_uses_selected_source_without_persistent_archive_or_git_changes(self):
        status = self.git("status", "--porcelain")
        result = builder.package_revision(self.commit, repository=self.repository)
        self.assertEqual(result["status"], "COMMITTED_SOURCE_PREFLIGHT_PASS")
        self.assertTrue(result["writes_performed"])
        self.assertTrue(result["temporary_source_materialized"])
        self.assertFalse(result["persistent_writes_performed"])
        self.assertNotIn("archive_sha256", result)
        self.assertFalse(self.output.exists())
        self.assertEqual(status, self.git("status", "--porcelain"))


if __name__ == "__main__":
    unittest.main()
