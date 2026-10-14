"""Small standard-library product; output paths are explicit CLI arguments."""

import argparse
import json
from pathlib import Path
import sys


def summarize(value):
    if not isinstance(value, dict) or not isinstance(value.get("values"), list):
        raise ValueError("expected an object with a values array")
    rows = value["values"]
    numbers = [row for row in rows if type(row) is int]
    return {"rows": len(rows), "total": sum(numbers), "invalid": len(rows) - len(numbers)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="fixtures/rows.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--cache")
    args = parser.parse_args()
    try:
        result = summarize(json.loads(Path(args.input).read_text(encoding="utf-8")))
    except (ValueError, OSError) as exc:
        print(f"INVALID_INPUT: {exc}", file=sys.stderr)
        return 2
    # Foundry creates the declared output directories. The product does not
    # create other directories or choose an undeclared fallback location.
    Path(args.output).write_text(json.dumps(result) + "\n", encoding="utf-8")
    if args.cache:
        Path(args.cache).write_text(json.dumps({"input": args.input, "result": result}) + "\n",
                                    encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
