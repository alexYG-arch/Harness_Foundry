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


if __name__ == "__main__":
    unittest.main()
