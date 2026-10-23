#!/usr/bin/env python3
"""Record optional RSI candidate evidence and adoption; never execute a repair."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from harness_foundry_factory.python_startup import require_supported_python
require_supported_python(launcher=str(Path(__file__).absolute()))
import argparse
import json
from harness_foundry_factory.rsi_cases import read_json, write_case
from harness_foundry_factory.rsi_adoption import snapshot, report_adoption


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='operation', required=True)
    s = sub.add_parser('snapshot')
    s.add_argument('--root', type=Path, required=True)
    s.add_argument('--files', type=Path, required=True, help='JSON list of explicit relative file paths')
    s.add_argument('--version', required=True)
    r = sub.add_parser('report')
    r.add_argument('--manifest', type=Path, required=True)
    for command in (s, r):
        command.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    try:
        result = snapshot(args.root, read_json(args.files.read_text()), args.version) if args.operation == 'snapshot' else report_adoption(
            read_json(args.manifest.read_text()), args.manifest.parent)
        write_case(result, args.output)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'status': 'ERROR', 'reason': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({'output': str(args.output), 'association_status': result.get('association_status')}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
