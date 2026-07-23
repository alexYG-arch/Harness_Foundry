#!/usr/bin/env python3
"""Repository-local entrypoint for the controlled Driver."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harness_foundry_runtime.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
