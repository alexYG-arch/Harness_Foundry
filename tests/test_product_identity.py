"""Public v2.9 product identity and version CLI contract."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
import unittest

import harness_foundry_factory
from harness_foundry_factory.constants import (
    BASELINE_FACTORY_ID,
    FACTORY_ID,
    FACTORY_VERSION,
    TARGET_PROTOCOL_VERSION,
)


ROOT = Path(__file__).resolve().parents[1]


class ProductIdentityTests(unittest.TestCase):
    def test_public_package_identity_is_v29(self) -> None:
        self.assertEqual(FACTORY_ID, "HARNESS_FOUNDRY_V2_9_CHAT_FACTORY_V0_1")
        self.assertEqual(TARGET_PROTOCOL_VERSION, "2.9")
        self.assertEqual(FACTORY_VERSION, "0.2.0")
        self.assertEqual(harness_foundry_factory.__version__, FACTORY_VERSION)

    def test_product_metadata_matches_canonical_constants(self) -> None:
        manifest = json.loads(
            (ROOT / "FACTORY_MANIFEST.json").read_text(encoding="utf-8")
        )
        pyproject = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )

        self.assertEqual(manifest["factory_id"], FACTORY_ID)
        self.assertEqual(manifest["baseline_factory_id"], BASELINE_FACTORY_ID)
        self.assertEqual(
            manifest["target_protocol_version"], TARGET_PROTOCOL_VERSION
        )
        self.assertEqual(manifest["version"], FACTORY_VERSION)
        self.assertEqual(
            manifest["assurance_profile"], "SELF_USE_LOCAL_TRUSTED_OPERATOR"
        )
        self.assertFalse(manifest["external_certification_claimed"])
        self.assertEqual(manifest["optional_security_hardening"], "NOT_RUN")
        self.assertEqual(pyproject["project"]["version"], FACTORY_VERSION)
        self.assertEqual(
            pyproject["project"]["optional-dependencies"]["security"],
            ["cryptography>=45,<49"],
        )

    def test_version_command_is_path_independent_and_machine_readable(self) -> None:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "harness_foundry_factory.cli",
                "version",
                "--json",
            ],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["factory_id"], FACTORY_ID)
        self.assertEqual(
            result["target_protocol_version"], TARGET_PROTOCOL_VERSION
        )
        self.assertEqual(result["implementation_version"], FACTORY_VERSION)
        self.assertEqual(result["baseline_factory_id"], BASELINE_FACTORY_ID)


if __name__ == "__main__":
    unittest.main()
