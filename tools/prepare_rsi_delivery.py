#!/usr/bin/env python3
"""Prepare selected RSI handoff materials without authorizing or executing a task."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from harness_foundry_factory.python_startup import require_supported_python
require_supported_python(launcher=str(Path(__file__).absolute()))
import argparse
import json
from harness_foundry_factory.rsi_cases import read_json
from harness_foundry_factory.rsi_delivery import prepare_delivery


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    try:
        manifest = args.manifest.resolve(strict=True)
        result = prepare_delivery(Path(__file__).resolve().parents[1], read_json(manifest.read_text()),
                                  manifest.parent, args.output)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'ERROR', 'reason': str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
