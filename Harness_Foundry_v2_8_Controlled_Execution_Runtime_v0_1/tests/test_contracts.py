"""Schema, generic-core, and read-only command contracts."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from harness_foundry_runtime.engine import plan_next, status, verify_run
from harness_foundry_runtime.util import tree_sha256

from support import SyntheticRuntime


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def test_shipped_schemas_are_valid_json_objects(self) -> None:
        manifest = json.loads(
            (REPOSITORY_ROOT / "RUNTIME_MANIFEST.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["version"], "0.1.1")
        self.assertEqual(manifest["default_mode"], "A1_PLAN_ONLY")
        self.assertTrue(manifest["real_target_install_excluded"])
        for path in sorted((REPOSITORY_ROOT / "schemas").glob("*.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsInstance(value, dict)
            self.assertEqual(
                value["$schema"],
                "https://json-schema.org/draft/2020-12/schema",
            )

    def test_generic_runtime_core_has_no_legacy_target_literals(self) -> None:
        forbidden = (
            "V-SCDSL",
            "AUTH-VSCDSL",
            "CODEX_VIDEO_EDITOR",
            "CODEX-VIDEO-EDITOR",
        )
        for path in sorted(
            (REPOSITORY_ROOT / "src/harness_foundry_runtime").glob("*.py")
        ):
            text = path.read_text(encoding="utf-8").upper()
            for literal in forbidden:
                self.assertNotIn(literal, text, f"{literal} leaked into {path}")

    def test_status_plan_and_verify_are_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            before = tree_sha256(fixture.execution)
            status(fixture.execution)
            plan_next(fixture.execution)
            verify_run(fixture.execution)
            after = tree_sha256(fixture.execution)
            self.assertEqual(after, before)
