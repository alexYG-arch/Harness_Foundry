"""Freeze named host observations and reviewed output bytes for a later check.

Run by the cooperating outer host after actual tool use/review, never by the
product producer. This copies supplied facts; it authenticates no reviewer,
creates no PASS, and does not approve or advance a Foundry Program.
"""
import argparse
import json
from pathlib import Path, PurePosixPath


def relative(value):
    p = PurePosixPath(value)
    if not value or p.is_absolute() or '\\' in value or any(x in ('', '.', '..') for x in value.split('/')):
        raise ValueError('expected a named relative evidence file')
    return p


def ordinary(root, name):
    p = root
    for part in relative(name).parts:
        p /= part
        if p.is_symlink():
            raise ValueError('evidence inputs must be ordinary files')
    if not p.is_file():
        raise ValueError('missing evidence file: ' + name)
    return p


def prepare(group, version, outputs, fixture, evidence_root, review, destination):
    outputs, fixture, evidence_root, destination = map(Path, (outputs, fixture, evidence_root, destination))
    manifest = json.loads((fixture / 'manifest.json').read_text(encoding='utf-8'))
    if group not in ('prd-design', 'data-reasoning', 'market-research', 'market-live') or version not in ('v1', 'v2'):
        raise ValueError('unknown example group or workflow version')
    expected_group = 'market_research' if group == 'market-live' else group.replace('-', '_')
    if manifest['id'] != expected_group:
        raise ValueError('fixture group mismatch')
    names = (manifest['live_outputs'] if group == 'market-live' else
             manifest['outputs'] + (manifest.get('v2_additional_outputs', []) if version == 'v2' else []))
    if not isinstance(review.get('reviewer'), str) or not review['reviewer'].strip():
        raise ValueError('name the actual independent host reviewer')
    observations = review.get('observations')
    if not isinstance(observations, list):
        raise ValueError('supply actual host observations, including incomplete results')
    references = []
    for row in observations:
        for ref in row.get('evidence_refs', []):
            relative(ref)
            if ref not in references:
                references.append(ref)
    # Read all named inputs before creating the result. No task is rerun here.
    payloads = {'reviewed-output/' + name: ordinary(outputs, name).read_bytes() for name in names}
    workflow = ordinary(fixture, manifest['workflows'][version]).read_bytes()
    for ref in references:
        payloads['evidence/' + ref] = ordinary(evidence_root, ref).read_bytes()
    document = {'group': group, 'version': version, 'reviewer': review['reviewer'],
                'reviewed_outputs': 'reviewed-output', 'workflow_file': 'workflow.md',
                'observations': [dict(row, evidence_refs=['evidence/' + ref for ref in row.get('evidence_refs', [])])
                                 for row in observations]}
    payloads['workflow.md'] = workflow
    payloads['review.json'] = (json.dumps(document, ensure_ascii=False, indent=2) + '\n').encode()
    # A new snapshot keeps prior reviewed evidence intact. This is a local
    # example file operation, not a new runtime freshness/approval condition.
    for parent in (destination, *destination.parents):
        if parent.exists() and any(parent.samefile(root) for root in (outputs, fixture)):
            raise ValueError('host evidence must remain outside product and fixture roots')
    destination.mkdir(parents=True, exist_ok=False)
    for name, data in payloads.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('group', 'version', 'outputs', 'fixture', 'evidence-root', 'review', 'destination'):
        parser.add_argument('--' + option, required=True)
    args = parser.parse_args()
    review = json.loads(Path(args.review).read_text(encoding='utf-8'))
    result = prepare(args.group, args.version, args.outputs, args.fixture, args.evidence_root, review, args.destination)
    print(json.dumps({'status': 'HOST_INPUTS_COPIED', 'group': result['group'], 'version': result['version'],
                      'accepted': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
