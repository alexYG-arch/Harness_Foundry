"""Small existing CSV summary tool, intentionally without audit yet."""

import argparse
import csv
import json
from pathlib import Path
import sys


def read_rows(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames
        if not columns or any(not item.strip() for item in columns) or len(set(columns)) != len(columns):
            raise ValueError("expected a nonempty unique header")
        return columns, list(reader)


def summary(path):
    columns, rows = read_rows(path)
    return {"columns": columns, "rows": len(rows)}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["summary"])
    parser.add_argument("input")
    args = parser.parse_args(argv)
    try:
        result = summary(args.input)
    except (OSError, UnicodeError, ValueError, csv.Error) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
