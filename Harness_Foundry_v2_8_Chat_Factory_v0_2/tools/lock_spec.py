#!/usr/bin/env python3
"""Create or verify the read-only sibling Harness Foundry v2.8 spec lock."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from harness_foundry_factory.spec_lock import (  # noqa: E402
    SpecLockError,
    build_spec_lock,
    verify_spec_lock,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", type=Path, metavar="LOCK_JSON")
    parser.add_argument("--output", type=Path, help="explicitly persist a newly built lock")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            lock = json.loads(args.verify.read_text(encoding="utf-8"))
            result = verify_spec_lock(lock)
        else:
            result = build_spec_lock()
            if args.output:
                args.output.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
    except (OSError, UnicodeError, json.JSONDecodeError, SpecLockError) as exc:
        result = {"status": "FAIL", "valid": False, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("status", "PASS") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
