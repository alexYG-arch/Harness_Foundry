"""Minimal selected-tool example; only reads the explicit input file."""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('input', type=Path)
args = parser.parse_args()
text = args.input.read_text(encoding='utf-8')
print(json.dumps({'characters': len(text), 'nonempty_lines': sum(bool(line.strip()) for line in text.splitlines())}))
