#!/usr/bin/env python3
"""Propose, query and record use of declared local knowledge; never execute it."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from harness_foundry_factory.python_startup import require_supported_python
require_supported_python(launcher=str(Path(__file__).absolute()))
import argparse
import json
from harness_foundry_factory.rsi_cases import read_json, write_case
from harness_foundry_factory.rsi_wiki import propose, query, record_decision


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command', required=True)
    proposal = commands.add_parser('propose')
    proposal.add_argument('--entry', type=Path, required=True)
    lookup = commands.add_parser('query')
    lookup.add_argument('--config', type=Path, required=True)
    lookup.add_argument('--question', required=True)
    lookup.add_argument('--conditions', default='{}', help='JSON object of task conditions')
    lookup.add_argument('--limit', type=int, default=5)
    decision = commands.add_parser('record')
    decision.add_argument('--query', type=Path, required=True)
    decision.add_argument('--decisions', type=Path, required=True)
    for cmd in (proposal, lookup, decision):
        cmd.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    try:
        if args.command == 'propose':
            propose(read_json(args.entry.read_text()), args.output)
        elif args.command == 'query':
            write_case(query(read_json(args.config.read_text()), args.config.resolve().parent,
                             args.question, read_json(args.conditions), args.limit), args.output)
        else:
            record_decision(read_json(args.query.read_text()), read_json(args.decisions.read_text()), args.output)
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({'status':'ERROR','reason':str(error)},ensure_ascii=False),file=sys.stderr)
        return 2
    print(json.dumps({'status':'RECORDED','commands_executed':False}));return 0


if __name__ == '__main__':
    raise SystemExit(main())
