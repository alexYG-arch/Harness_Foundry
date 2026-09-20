"""Repo-local Codex Skill validation tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SkillContractTests(unittest.TestCase):
    def test_repo_skill_is_valid(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "validate_skill.py")],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["writes_performed"])

    def test_chat_surface_uses_generic_build_and_retires_legacy_creation(self) -> None:
        skill = (ROOT / ".agents/skills/harness-foundry-start-author/SKILL.md").read_text(
            encoding="utf-8"
        )
        chat_usage = (ROOT / "docs/CHAT_USAGE.md").read_text(encoding="utf-8")
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        agent_config = (
            ROOT / ".agents/skills/harness-foundry-start-author/agents/openai.yaml"
        ).read_text(encoding="utf-8")

        for content in (skill, chat_usage, agents, agent_config):
            self.assertIn("GENERIC_REVIEWED_BUILD_ONLY", content)
            self.assertNotIn("OPTIONAL_ROUTE_START_PACKAGE_COMPATIBILITY", content)
            self.assertIn("read-history", content)
        for content in (skill, chat_usage):
            self.assertIn("LEGACY_WORKFLOW_RETIRED", content)
            self.assertIn("advance-build", content)
            self.assertIn("TRUE_GATE_ONLY", content)
        self.assertIn("without per-Workpack gates", agent_config)


if __name__ == "__main__":
    unittest.main()
