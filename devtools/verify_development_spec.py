#!/usr/bin/env python3
"""Read-only verification of the source checkout's pinned historical test input."""

from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harness_foundry_factory.spec_lock import SpecLockError, load_spec_lock, verify_spec_lock


def main() -> int:
    try:
        report = verify_spec_lock(load_spec_lock())
    except (OSError, SpecLockError) as exc:
        report = {"status": "FAIL", "valid": False, "error": str(exc)}
    report["scope"] = "HISTORICAL_SOURCE_REGRESSION_DEPENDENCY_ONLY"
    report["runtime_dependency"] = False
    report["authoring_reactivated"] = False
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
