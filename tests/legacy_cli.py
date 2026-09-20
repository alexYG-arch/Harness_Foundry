"""Replay retired CLI behavior in historical regression fixtures only.

Not a product route, installed command, authorization override or release input.
These tests preserve old mechanism evidence; public retirement is tested separately.
"""
from harness_foundry_factory.cli import _baseline_main

if __name__ == "__main__":
    raise SystemExit(_baseline_main())
