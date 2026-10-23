#!/usr/bin/env python3
"""Prepare or read RSI review handoff; dispatch remains with generic Build."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from harness_foundry_factory.python_startup import require_supported_python
require_supported_python(launcher=str(Path(__file__).absolute()))
import argparse
import json
from harness_foundry_factory.rsi_cases import write_case
from harness_foundry_factory.rsi_review import load,prepare_review,review_build_request,retrieve_review


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('prepare');p.add_argument('--manifest',type=Path,required=True)
    p=sub.add_parser('plan');p.add_argument('--request',type=Path,required=True);p.add_argument('--program-id',required=True)
    p=sub.add_parser('retrieve')
    for flag in ('request','report','database'):p.add_argument('--'+flag,type=Path,required=True)
    for flag in ('program-id','prepared-id','attempt-id'):p.add_argument('--'+flag,required=True)
    p.add_argument('--objective-status',choices=['PASS','FAIL','ERROR','UNKNOWN','NOT_RUN'],required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        if args.action=='prepare':
            path=args.manifest.resolve(strict=True);result=prepare_review(load(path),path.parent)
        elif args.action=='plan':result=review_build_request(load(args.request),program_id=args.program_id)
        else:
            from harness_foundry_factory.revision_store import RevisionControlEventStore
            store=RevisionControlEventStore(args.database,read_only=True,storage_format='REVISION_V1')
            result=retrieve_review(store,args.program_id,args.prepared_id,args.attempt_id,load(args.request),args.report,objective_status=args.objective_status)
        write_case(result,args.output)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(json.dumps({'status':'ERROR','reason':str(exc)},ensure_ascii=False),file=sys.stderr);return 2
    print(json.dumps({'status':'RSI_HANDOFF_SAVED','runtime_authorized':False,'product_accepted':False}));return 0


if __name__=='__main__':raise SystemExit(main())
