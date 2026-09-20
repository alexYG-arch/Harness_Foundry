"""Slice 07 portable local packaging and startup acceptance tests."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from harness_foundry_factory.models import content_sha256
from harness_foundry_factory.portable import (
    PACKAGE_ROOT_URI,
    PORTABLE_MANIFEST_NAME,
    PortablePackageError,
    package_local,
    resolve_logical_resource_uri,
)


ROOT = Path(__file__).resolve().parents[1]


class PortableLocalCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "harness_foundry_factory.cli",
                *arguments,
                "--json",
            ],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_preflight_is_read_only_and_declares_portable_dependencies(self) -> None:
        before = {path.name for path in self.root.iterdir()}

        completed = self._run_cli("package-local")

        self.assertEqual(completed.returncode, 0, completed.stdout)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "PREFLIGHT_PASS")
        self.assertFalse(result["writes_performed"])
        manifest = result["manifest"]
        self.assertEqual(manifest["logical_roots"], {"package": PACKAGE_ROOT_URI})
        self.assertFalse(manifest["security_authority"])
        self.assertFalse(manifest["certification_claimed"])
        self.assertEqual(
            [item["dependency_id"] for item in manifest["dependencies"]],
            ["python", "cryptography", "jsonschema", "referencing", "HARNESS_FOUNDRY_V2_8_START_PACKAGE"],
        )
        for dependency in manifest["dependencies"]:
            if dependency["dependency_id"] in {"jsonschema", "referencing"}:
                self.assertFalse(dependency["required_for_core_startup"])
                self.assertEqual(dependency["extra"], "runtime-audit")
                self.assertEqual(dependency["required_for_commands"], ["audit-completion", "LAB-PROTOCOL-CHECK"])
        self.assertEqual(manifest["dependency_discovery"]["undeclared_external_imports"], [])
        self.assertFalse(any(path.startswith("runs/") for path in manifest["files"]))
        self.assertFalse(any(path.startswith("tests/") for path in manifest["files"]))
        self.assertIn("docs/ARCHITECTURE.md", manifest["files"])
        self.assertIn("docs/CHAT_USAGE.md", manifest["files"])
        for name in ("GENERIC_BUILD_PLAN", "GENERIC_BUILD_CLI", "GENERIC_BUILD_RUNTIME", "GENERIC_SOURCE_INTAKE"):
            self.assertIn(f"docs/{name}.md", manifest["files"])
        self.assertEqual({path.name for path in self.root.iterdir()}, before)

    def test_core_compiler_module_import_does_not_require_optional_crypto(self) -> None:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        environment["PYTHONDONTWRITEBYTECODE"] = "1"

        completed = subprocess.run(
            [
                sys.executable,
                "-S",
                "-B",
                "-c",
                "import harness_foundry_factory.compiler; import harness_foundry_factory.workpack_acceptance; print('CORE_IMPORT_PASS')",
            ],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "CORE_IMPORT_PASS")

    def test_package_relocates_and_official_startup_smoke_passes_without_install(self) -> None:
        output = self.root / "portable-one"

        completed = self._run_cli(
            "package-local", "--output-root", str(output)
        )

        self.assertEqual(completed.returncode, 0, completed.stdout)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["startup_smoke"]["status"], "PASS")
        self.assertFalse(result["startup_smoke"]["editable_install_used"])
        self.assertFalse(result["startup_smoke"]["network_used"])
        self.assertTrue((output / PORTABLE_MANIFEST_NAME).is_file())
        self.assertFalse((output / "runs").exists())
        self.assertFalse((output / "AUTHORITY_TRUST_ROOT.json").exists())

        relocated = self.root / "different-parent" / "renamed-package"
        relocated.parent.mkdir()
        shutil.copytree(output, relocated)
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        check = subprocess.run(
            [
                sys.executable,
                "-S",  # Real relocated startup without site-packages/optional extras.
                "-B",
                "tools/hffactory.py",
                "self-check-diagnostic",
                "--package-root",
                ".",
                "--json",
            ],
            cwd=relocated,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(check.returncode, 0, check.stdout)
        diagnostic = json.loads(check.stdout)
        self.assertEqual(diagnostic["status"], "PASS")
        self.assertEqual(
            diagnostic["check_kind"],
            "DIAGNOSTIC_ONLY_NOT_SECURITY_AUTHORITY",
        )
        self.assertFalse(diagnostic["security_authority"])
        self.assertFalse(diagnostic["certification_claimed"])
        self.assertFalse(diagnostic["candidate_self_proof_claimed"])
        for dependency in diagnostic["dependencies"]:
            if dependency["dependency_id"] in {"cryptography", "jsonschema", "referencing"}:
                self.assertFalse(dependency["available"])

    def test_portable_optional_imports_require_the_matching_install_extra(self) -> None:
        source = self.root / "source-missing-extra"
        self._copy_source(source)
        metadata = source / "pyproject.toml"
        metadata.write_text(metadata.read_text().replace(
            'runtime-audit = ["jsonschema>=4.18,<5", "referencing>=0.28,<1"]',
            'runtime-audit = []'))
        output = self.root / "missing-extra-output"
        with self.assertRaises(PortablePackageError) as blocked:
            package_local(output, source_root=source)
        self.assertEqual(blocked.exception.code, "OPTIONAL_DEPENDENCY_DECLARATION_INVALID")
        self.assertFalse(output.exists())

    def test_self_check_detects_missing_optional_route_even_with_valid_manifest_digest(self) -> None:
        output = self.root / "missing-audit-route"
        package_local(output)
        path = output / PORTABLE_MANIFEST_NAME
        manifest = json.loads(path.read_text())
        manifest["dependencies"] = [item for item in manifest["dependencies"]
                                    if item["dependency_id"] != "referencing"]
        manifest.pop("manifest_sha256")
        manifest["manifest_sha256"] = content_sha256(manifest)
        path.write_text(json.dumps(manifest))
        completed = self._run_cli("self-check-diagnostic", "--package-root", str(output))
        self.assertEqual(completed.returncode, 6, completed.stdout)
        self.assertIn("DEPENDENCY_DECLARATION_MISMATCH",
                      {item["code"] for item in json.loads(completed.stdout)["findings"]})

    def test_self_check_hash_failure_is_diagnostic_and_read_only(self) -> None:
        output = self.root / "portable-tamper"
        package_local(output)
        manifest_path = output / "FACTORY_MANIFEST.json"
        manifest_path.write_text("{}\n", encoding="utf-8")
        before = sorted(path.relative_to(output) for path in output.rglob("*"))

        completed = self._run_cli(
            "self-check-diagnostic", "--package-root", str(output)
        )

        self.assertEqual(completed.returncode, 6, completed.stdout)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn(
            "PORTABLE_FILE_HASH_MISMATCH",
            {finding["code"] for finding in result["findings"]},
        )
        self.assertFalse(result["writes_performed"])
        self.assertFalse(result["security_authority"])
        self.assertEqual(
            sorted(path.relative_to(output) for path in output.rglob("*")), before
        )

    def test_logical_root_rejects_traversal_encoding_and_external_symlink(self) -> None:
        output = self.root / "portable-paths"
        package_local(output)
        for uri in (
            f"{PACKAGE_ROOT_URI}/../outside",
            f"{PACKAGE_ROOT_URI}/./FACTORY_MANIFEST.json",
            f"{PACKAGE_ROOT_URI}//FACTORY_MANIFEST.json",
            f"{PACKAGE_ROOT_URI}/%2e%2e/outside",
            f"{PACKAGE_ROOT_URI}/folder\\outside",
            "harness-resource://candidate/FACTORY_MANIFEST.json",
        ):
            with self.subTest(uri=uri), self.assertRaises(PortablePackageError):
                resolve_logical_resource_uri(output, uri, require_file=True)

        link = output / "external-link"
        try:
            link.symlink_to(self.root / "outside")
        except OSError as exc:  # pragma: no cover - platform capability
            self.skipTest(f"symlink unavailable: {exc}")
        with self.assertRaises(PortablePackageError) as linked:
            resolve_logical_resource_uri(
                output, f"{PACKAGE_ROOT_URI}/external-link/file.json"
            )
        self.assertEqual(linked.exception.code, "EXTERNAL_SYMLINK")

    def test_preflight_rejects_undeclared_dependency_credential_and_identity_without_output(self) -> None:
        cases = (
            ("dependency", "src/harness_foundry_factory/injected.py", "import requests\n", "UNDECLARED_RUNTIME_DEPENDENCY"),
            ("credential", "src/harness_foundry_factory/injected.py", "VALUE = 'sk-abcdefghijklmnopqrstuvwx'\n", "CREDENTIAL_DISCLOSURE"),
            ("identity", "src/harness_foundry_factory/injected.py", "VALUE = '/Users/example/secret/project'\n", "LOCAL_IDENTITY_EXPORT"),
            ("machine-binding", "src/harness_foundry_factory/injected.py", "VALUE = '/opt/homebrew/bin/python3'\n", "LOCAL_MACHINE_BINDING_EXPORT"),
        )
        for name, relative, content, reason in cases:
            with self.subTest(name=name):
                source = self.root / f"source-{name}"
                self._copy_source(source)
                injected = source / relative
                injected.write_text(content, encoding="utf-8")
                output = self.root / f"output-{name}"
                with self.assertRaises(PortablePackageError) as blocked:
                    package_local(output, source_root=source)
                self.assertEqual(blocked.exception.code, reason)
                self.assertFalse(output.exists())

    def test_collision_and_source_symlink_fail_before_output_mutation(self) -> None:
        collision = self.root / "already-exists"
        collision.mkdir()
        completed = self._run_cli(
            "package-local", "--output-root", str(collision)
        )
        self.assertEqual(completed.returncode, 6, completed.stdout)
        self.assertEqual(
            json.loads(completed.stdout)["error"]["reason_code"],
            "OUTPUT_COLLISION",
        )
        self.assertEqual(list(collision.iterdir()), [])

        source = self.root / "source-symlink"
        self._copy_source(source)
        linked = source / "src/harness_foundry_factory/injected.py"
        try:
            linked.symlink_to(ROOT / "README.md")
        except OSError as exc:  # pragma: no cover - platform capability
            self.skipTest(f"symlink unavailable: {exc}")
        output = self.root / "output-symlink"
        with self.assertRaises(PortablePackageError) as blocked:
            package_local(output, source_root=source)
        self.assertEqual(blocked.exception.code, "EXTERNAL_SYMLINK")
        self.assertFalse(output.exists())

    @staticmethod
    def _copy_source(target: Path) -> None:
        target.mkdir()
        for relative in (
            "AGENTS.md",
            "FACTORY_MANIFEST.json",
            "README.md",
            "pyproject.toml",
            "docs",
            ".agents",
            "schemas",
            "spec_lock",
            "src",
            "tools",
        ):
            source = ROOT / relative
            destination = target / relative
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)


if __name__ == "__main__":
    unittest.main()
