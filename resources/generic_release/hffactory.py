#!/usr/bin/env python3
"""Run the packaged generic CLI without installation or an author workspace."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from harness_foundry_factory.build_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
