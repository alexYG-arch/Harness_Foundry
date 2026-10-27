#!/usr/bin/env python3
"""Query selected report baselines/deltas or retrieve bound original bytes."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from harness_foundry_factory.python_startup import require_supported_python
require_supported_python(launcher=str(Path(__file__).absolute()))
import argparse
import json
from harness_foundry_factory.rsi_cases import read_json, write_case
from harness_foundry_factory.rsi_reports import reconstruct, query, read_source


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    q = sub.add_parser('query')
    q.add_argument('--manifest', type=Path, required=True)
    q.add_argument('--offset', type=int, default=0); q.add_argument('--limit', type=int, default=20)
    q.add_argument('--id', dest='item_id'); q.add_argument('--conditions', default='{}')
    q.add_argument('--field'); q.add_argument('--value', help='JSON value for exact field matching')
    q.add_argument('--source'); q.add_argument('--details', action='store_true'); q.add_argument('--view-id')
    r = sub.add_parser('read-source')
    r.add_argument('--reference', type=Path, required=True, help='Explicit bound file reference JSON')
    r.add_argument('--offset', type=int, default=0); r.add_argument('--length', type=int, default=65536)
    for cmd in (q, r):
        cmd.add_argument('--root', type=Path, help='Declared material root; defaults to manifest/reference parent')
        cmd.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    try:
        path = args.manifest if args.command == 'query' else args.reference
        root = args.root or path.resolve(strict=True).parent
        doc = read_json(path.read_text(encoding='utf-8'))
        if args.command == 'query':
            result = query(reconstruct(doc, root), offset=args.offset, limit=args.limit, item_id=args.item_id,
                conditions=read_json(args.conditions), field=args.field,
                source=args.source, details=args.details, view_id=args.view_id,
                **({'value': read_json(args.value)} if args.value is not None else {}))
        else:
            result = read_source(root, doc, offset=args.offset, length=args.length)
        write_case(result, args.output)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'ERROR', 'reason': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({'status': 'RECORDED', 'acceptance_verified': False, 'commands_executed': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
