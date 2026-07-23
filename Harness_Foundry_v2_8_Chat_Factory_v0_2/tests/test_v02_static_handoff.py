"""v0.2 static validation, handoff, and generic-core regression tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from harness_foundry_factory.compiler import compile_candidate
from harness_foundry_factory.validator import (
    export_execution_handoff,
    validate_candidate,
    validate_handoff,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SPEC_ROOT = REPOSITORY_ROOT.parent / "Harness_Foundry_v2_8_Start_Package"
FIXTURE_PATH = REPOSITORY_ROOT / "tests/fixtures/harness_requirement_ir.json"
CREATED_AT = "2026-07-10T00:00:00Z"


class StaticHandoffTests(unittest.TestCase):
    def _compile(
        self, root: Path, target_type: str = "HARNESS"
    ) -> tuple[Path, Path]:
        candidate = root / f"{target_type.lower()}-candidate"
        execution = root / f"{target_type.lower()}-execution"
        ir = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        ir["program_id"] = f"PROGRAM-GENERIC-{target_type}"
        ir["target"].update(
            {
                "id": f"GENERIC-{target_type}",
                "name": f"Generic {target_type.title()}",
                "type": target_type,
                "output_root": str(candidate),
                "execution_root": str(execution),
            }
        )
        compile_candidate(
            ir,
            SPEC_ROOT,
            root / f"{target_type.lower()}-staging",
            candidate,
            CREATED_AT,
        )
        return candidate, execution

    def test_agent_harness_and_hybrid_compile_and_validate_statically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for target_type in ("AGENT", "HARNESS", "HYBRID"):
                candidate, _execution = self._compile(root, target_type)
                report = validate_candidate(candidate)
                self.assertEqual(report["status"], "PASS", report)
                self.assertFalse(report["execution_root_observed"])

    def test_execution_materialization_and_symlink_do_not_change_static_pass(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate, execution = self._compile(Path(temporary))
            before = validate_candidate(candidate)
            planned = execution / "project_start_packages/main_build/.venv/bin"
            planned.mkdir(parents=True)
            (planned / "python").symlink_to("/bin/true")
            (execution / "unrelated-runtime-receipt.json").write_text(
                '{"status":"RUNTIME_ONLY"}\n', encoding="utf-8"
            )
            after = validate_candidate(candidate)

            self.assertEqual(before["status"], "PASS")
            self.assertEqual(after["status"], "PASS")
            self.assertFalse(after["execution_root_observed"])

    def test_handoff_is_hash_bound_and_does_not_create_execution_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate, execution = self._compile(Path(temporary))
            handoff = export_execution_handoff(candidate)
            validation = validate_handoff(candidate)
            body = {
                key: value
                for key, value in handoff.items()
                if key
                not in {
                    "handoff_sha256",
                    "status",
                    "writes_performed",
                    "commands_executed",
                }
            }
            expected = hashlib.sha256(
                json.dumps(
                    body,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()

            self.assertEqual(handoff["handoff_sha256"], expected)
            self.assertEqual(validation["status"], "PASS")
            self.assertFalse(execution.exists())
            self.assertFalse(handoff["execution_authorization_inherited"])

    def test_static_validation_and_handoff_cli_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate, execution = self._compile(Path(temporary))
            for command in (
                "validate-candidate-static",
                "validate-handoff",
                "export-execution-handoff",
            ):
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(REPOSITORY_ROOT / "tools/hffactory.py"),
                        command,
                        str(candidate),
                        "--json",
                    ],
                    cwd=REPOSITORY_ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    f"{command}: {completed.stderr}\n{completed.stdout}",
                )
                result = json.loads(completed.stdout)
                self.assertEqual(result["status"], "PASS")
            self.assertFalse(execution.exists())

    def test_generic_core_has_no_known_legacy_target_literals(self) -> None:
        forbidden = (
            "V-SCDSL",
            "AUTH-VSCDSL",
            "CODEX_VIDEO_EDITOR",
            "CODEX-VIDEO-EDITOR",
        )
        core_files = (
            REPOSITORY_ROOT / "src/harness_foundry_factory/compiler.py",
            REPOSITORY_ROOT / "src/harness_foundry_factory/service.py",
            REPOSITORY_ROOT / "src/harness_foundry_factory/validator.py",
        )
        for path in core_files:
            text = path.read_text(encoding="utf-8").upper()
            for literal in forbidden:
                self.assertNotIn(literal, text, f"{literal} leaked into {path}")

    def test_legacy_runtime_recognizers_are_indexed_outside_static_core(
        self,
    ) -> None:
        legacy_module = (
            REPOSITORY_ROOT
            / "src/harness_foundry_factory"
            / "legacy_execution_evidence_validator_v0_1.py"
        )
        index = json.loads(
            (
                REPOSITORY_ROOT
                / "legacy/fixtures/LEGACY_RUNTIME_SCENARIO_INDEX.json"
            ).read_text(encoding="utf-8")
        )
        names = sorted(
            set(
                re.findall(
                    r"^def (_authorized_[A-Za-z0-9_]+)",
                    legacy_module.read_text(encoding="utf-8"),
                    flags=re.MULTILINE,
                )
            )
        )
        self.assertEqual(index["scenarios"], names)
        self.assertFalse(index["participates_in_v0_2_candidate_pass"])
