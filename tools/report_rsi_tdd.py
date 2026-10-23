#!/usr/bin/env python3
"""Associate declared TDD evidence without running tests, models or repairs."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from harness_foundry_factory.python_startup import require_supported_python
require_supported_python(launcher=str(Path(__file__).absolute()))
import argparse
import json
from harness_foundry_factory.rsi_cases import read_json,write_case
from harness_foundry_factory.rsi_tdd import associate_tdd


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for flag in ('case','association','output'):p.add_argument('--'+flag,type=Path,required=True)
    args=p.parse_args()
    try:
        result=associate_tdd(read_json(args.case.read_text()),read_json(args.association.read_text()))
        write_case(result,args.output)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(json.dumps({'status':'ERROR','reason':str(exc)},ensure_ascii=False),file=sys.stderr);return 2
    print(json.dumps(result['summary'],ensure_ascii=False));return 0


if __name__=='__main__':raise SystemExit(main())
