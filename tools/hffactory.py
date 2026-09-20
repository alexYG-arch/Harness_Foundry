#!/usr/bin/env python3
"""Run the Factory CLI from a clean checkout without an editable install."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from harness_foundry_factory.entrypoint import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
