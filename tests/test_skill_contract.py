"""Repo-local Codex Skill validation tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SkillContractTests(unittest.TestCase):
    def test_source_and_distribution_reference_one_communication_policy(self):
        for relative in ("AGENTS.md", "resources/generic_release/AGENTS.md",
                         "resources/generic_release/SKILL.md",
                         ".agents/skills/harness-foundry-start-author/SKILL.md"):
            with self.subTest(relative=relative):
                content = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("docs/CLEAR_COMMUNICATION.md", content)
                self.assertIn("read-build --human", content)
        policy = (ROOT / "docs/CLEAR_COMMUNICATION.md").read_text(encoding="utf-8")
        for preserved in ("不新增审批门禁", "机器 JSON", "不保证", "不调用额外模型", "已确认文档"):
            self.assertIn(preserved, policy)
        self.assertIn("生成 Harness 与运行提示词", policy)
        self.assertIn("没有指导文档产物也不构成阻断", policy)
        for relative in (".agents/skills/harness-foundry-start-author/SKILL.md",
                         "resources/generic_release/SKILL.md"):
            content = (ROOT / relative).read_text(encoding="utf-8")
            for preserved in ("self-contained instructions", "machine-contract precedence",
                              "only declared outputs", "no extra reads or approval"):
                self.assertIn(preserved, content)

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
