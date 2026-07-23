#!/usr/bin/env python3
"""Validate the repo-local Codex Skill without third-party dependencies."""

from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / ".agents" / "skills" / "harness-foundry-start-author"
SKILL_PATH = SKILL_ROOT / "SKILL.md"
AGENT_PATH = SKILL_ROOT / "agents" / "openai.yaml"
ALLOWED_KEYS = {"name", "description", "license", "allowed-tools", "metadata"}


def _flat_frontmatter(content: str) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---(?:\n|$)", content, re.DOTALL)
    if not match:
        raise ValueError("SKILL.md must start with YAML frontmatter")
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        if line[:1].isspace() or ":" not in line:
            raise ValueError("SKILL.md frontmatter must contain flat key-value fields")
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip("\"'")
    return fields


def validate() -> dict[str, object]:
    content = SKILL_PATH.read_text(encoding="utf-8")
    fields = _flat_frontmatter(content)
    unexpected = sorted(set(fields).difference(ALLOWED_KEYS))
    if unexpected:
        raise ValueError(f"unsupported SKILL.md frontmatter fields: {unexpected}")
    name = fields.get("name", "")
    description = fields.get("description", "")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
        raise ValueError("Skill name must be hyphen-case and at most 64 characters")
    if not description or len(description) > 1024 or "<" in description or ">" in description:
        raise ValueError("Skill description is missing or invalid")

    missing_references = []
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", content):
        if "://" not in target and not (SKILL_ROOT / target).is_file():
            missing_references.append(target)
    if missing_references:
        raise ValueError(f"missing Skill references: {sorted(missing_references)}")

    agent = AGENT_PATH.read_text(encoding="utf-8")
    required_agent_fields = ("interface:", "display_name:", "short_description:", "default_prompt:")
    missing_agent_fields = [field for field in required_agent_fields if field not in agent]
    if missing_agent_fields:
        raise ValueError(f"missing agents/openai.yaml fields: {missing_agent_fields}")

    return {
        "schema_version": "1.0",
        "status": "PASS",
        "skill_name": name,
        "checked_references": len(re.findall(r"\[[^\]]+\]\(([^)]+)\)", content)),
        "writes_performed": False,
    }


def main() -> int:
    try:
        result = validate()
    except (OSError, UnicodeError, ValueError) as exc:
        result = {
            "schema_version": "1.0",
            "status": "FAIL",
            "error": str(exc),
            "writes_performed": False,
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
