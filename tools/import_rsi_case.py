#!/usr/bin/env python3
"""Import explicit local RSI materials; no execution, repair or state mutation."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from harness_foundry_factory.python_startup import require_supported_python

require_supported_python(launcher=str(Path(__file__).absolute()))

import argparse
import json
from harness_foundry_factory.rsi_cases import import_case, read_json, write_case


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new local JSON file; existing files are never overwritten")
    args = parser.parse_args(argv)
    try:
        manifest = args.manifest.resolve(strict=True)
        case = import_case(read_json(manifest.read_text(encoding="utf-8")), manifest.parent)
        write_case(case, args.output)
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "ERROR", "diagnostic": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"status": case["import_status"], "case_id": case["case_id"],
                      "acceptance_verified": False, "control_state_modified": False}))
    return 0 if case["import_status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
