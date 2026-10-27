#!/usr/bin/env python3
"""Selected host material handoffs, never dispatch, repair or budget authority.

One outer owner calls this at existing return points. Receipts are recoverable
material references, not a second issue/state database or exactly-once service.
"""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from harness_foundry_factory.python_startup import require_supported_python
require_supported_python(launcher=str(Path(__file__).absolute()))
from harness_foundry_factory import rsi_cases, rsi_tdd, rsi_wiki, rsi_review, build_types


def encoded(value):
    return (build_types.canonical_json(value) + '\n').encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def local(root, name):
    return rsi_wiki._local(root, name)


def observe(root, names):
    rows = []
    for name in sorted(set(names)):
        path = local(root, name)
        try:
            raw = path.read_bytes()
            rows.append({'path': name, 'status': 'READ', 'sha256': sha(raw)})
        except OSError:
            rows.append({'path': name, 'status': 'UNAVAILABLE'})
    return rows


def versions():
    return {name: sha(Path(path).read_bytes()) for name, path in [
        ('rsi_handoff', __file__), *[(m.__name__.rsplit('.', 1)[-1], m.__file__)
        for m in (rsi_cases, rsi_tdd, rsi_wiki, rsi_review, build_types)]]}


def identity(request):
    value = request.get('identity', {})
    rsi_cases.require(isinstance(value, dict) and all(isinstance(value.get(k), str) and value[k].strip()
                     for k in ('project', 'task', 'issue')), 'explicit project/task/issue identity required')
    rsi_cases.require(isinstance(request.get('phase'), str) and request['phase'].strip(), 'phase required')


def _stored(directory, binding):
    try:
        receipt = rsi_cases.read_json((directory / 'completion.json').read_text())
        if receipt['input'] != binding:
            return None
        hashes = receipt['files']
        if not isinstance(hashes, dict) or not hashes or any(
                sha(local(directory, n).read_bytes()) != h for n, h in hashes.items()):
            return None
        return receipt
    except (OSError, ValueError, KeyError, TypeError):
        return None


def store(output, binding, build, reobserve):
    """Reuse complete output, finish a missing receipt, or preserve partial bytes.

    The caller supplies a dedicated selected material directory and owns writes.
    Source reads are rechecked before storing; no subprocess or old command runs.
    """
    # Normalize the chosen root before contained-path comparisons; aliases
    # still refer to the same explicit material directory, not a new write domain.
    output = Path(output).resolve()
    directories = sorted(p for p in output.glob('handoff-*') if p.is_dir() and not p.is_symlink())
    for directory in reversed(directories):
        receipt = _stored(directory, binding)
        if receipt is not None:
            return {**receipt['result'], 'directory': str(directory), 'reused': True,
                    'receipt_recovered': False}
    files, result = build()
    rsi_cases.require(reobserve() == binding, 'declared input changed while preparing handoff')
    files = {'input.json': encoded(binding), **files}
    # A complete write before final receipt registration is recoverable without
    # rewriting outputs. Partial or mismatched directories remain untouched.
    for directory in reversed(directories):
        if (directory / 'completion.json').exists():
            continue
        try:
            actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
            if actual == set(files) and all(local(directory, n).read_bytes() == raw for n, raw in files.items()):
                receipt = {'input': binding, 'files': {n: sha(raw) for n, raw in files.items()}, 'result': result}
                rsi_cases.write_case(receipt, directory / 'completion.json')
                return {**result, 'directory': str(directory), 'reused': True, 'receipt_recovered': True}
        except (OSError, ValueError):
            continue
    output.mkdir(parents=False, exist_ok=True)
    number = 1
    while (output / ('handoff-' + str(number).zfill(4))).exists():
        number += 1
    directory = output / ('handoff-' + str(number).zfill(4))
    directory.mkdir()
    for name, raw in files.items():
        path = local(directory, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(raw)
    receipt = {'input': binding, 'files': {n: sha(raw) for n, raw in files.items()}, 'result': result}
    rsi_cases.write_case(receipt, directory / 'completion.json')
    return {**result, 'directory': str(directory), 'reused': False, 'receipt_recovered': False}


def facts(status):
    return {'status': status, 'commands_executed': False, 'budget_modified': False,
            'acceptance_verified': False, 'business_state_modified': False}


def capture(request, material_root, output):
    """Associate explicit case/TDD inputs and references; keep raw analysis private."""
    if request.get('enabled') is not True:
        return facts('NOT_SELECTED')
    identity(request)
    root = Path(material_root).resolve(strict=True)
    case = request['case']
    names = [s['path'] for s in case['sources']]
    references = request.get('references', [])
    names += [r['path'] for r in references]
    def binding():
        return {'operation': 'capture', 'request': deepcopy(request), 'material_root': str(root),
                'sources': observe(root, names), 'tools': versions()}
    inputs = binding()
    def build():
        parsed = rsi_cases.import_case(case, root)
        files = {'case.json': encoded(parsed)}
        if 'tdd' in request:
            files['tdd.json'] = encoded(rsi_tdd.associate_tdd(parsed, request['tdd']))
        by_path = {r['path']: r for r in inputs['sources']}
        refs = [{**deepcopy(r), 'observation': by_path[r['path']]} for r in references]
        complete = parsed['import_status'] == 'COMPLETE' and all(r['status'] == 'READ' for r in inputs['sources'])
        result = {**facts('COMPLETE' if complete else 'PARTIAL'), 'identity': deepcopy(request['identity']),
                  'phase': request['phase'], 'context': deepcopy(request.get('context', {})),
                  'references': refs, 'artifacts': list(files), 'visibility': 'LOCAL_ANALYSIS',
                  'limitations': ['Source text is not automatically sanitized or deliverable.',
                                 'References do not independently validate Reviewer, adoption or business results.']}
        files['handoff.json'] = encoded(result)
        return files, result
    return store(output, inputs, build, binding)


def collection(request, material_root, output):
    """Assemble only owner-selected material into a new queryable collection.

    No analysis report is automatically promoted/copied. A manifest describes
    already curated bytes; audience/reason are declarations, not redaction proof.
    """
    if request.get('enabled') is not True:
        return facts('NOT_SELECTED')
    identity(request)
    root = Path(material_root).resolve(strict=True)
    meta = request['collection']
    rsi_cases.require(all(isinstance(meta.get(k), str) and meta[k].strip() for k in ('id', 'version'))
                      and meta.get('visibility') in ('PUBLIC', 'PROJECT'), 'collection identity and visibility required')
    entries, updates = request.get('entries', []), request.get('updates', [])
    rsi_cases.require(isinstance(entries, list) and isinstance(updates, list)
                      and len(set(entries)) == len(entries) and len(set(updates)) == len(updates), 'unique collection lists required')
    selections = request['files']
    destinations = [r['path'] for r in selections]
    rsi_cases.require(len(set(destinations)) == len(destinations) and 'collection.json' not in destinations,
                      'unique collection files required')
    rsi_cases.require(set(entries + updates) <= set(destinations), 'declared entry/update file missing')
    for row in selections:
        local(root, row['path']); local(root, row['source'])
        rsi_cases.require(row.get('audience') == meta['visibility'] and isinstance(row.get('reason'), str)
                          and row['reason'].strip(), 'explicit selected audience and reason required')
    names = [r['source'] for r in selections]
    if request.get('previous_config'):
        names.append(request['previous_config'])
    def binding():
        return {'operation': 'collection', 'request': deepcopy(request), 'material_root': str(root),
                'sources': observe(root, names), 'tools': versions()}
    inputs = binding()
    def build():
        if request.get('previous_config'):
            previous = rsi_cases.read_json(local(root, request['previous_config']).read_text())
            for old in previous['collections']:
                if old['id'] == meta['id']:
                    rsi_cases.require(old['version'] != meta['version'], 'select a new collection version')
        files = {'collection/' + r['path']: local(root, r['source']).read_bytes() for r in selections}
        for path in entries:
            rsi_wiki.validate_entry(rsi_cases.read_json(files['collection/' + path].decode('utf-8')))
        files['collection/collection.json'] = encoded({'version': meta['version'], 'entries': entries, 'updates': updates})
        files['wiki.json'] = encoded({'collections': [{**meta, 'path': 'collection'}]})
        result = {**facts('PREPARED'), 'identity': deepcopy(request['identity']), 'phase': request['phase'],
                  'collection': deepcopy(meta), 'artifacts': list(files),
                  'limitations': ['Prepared bytes are not independent semantic or disclosure approval.',
                                 'Input/receipt files stay in the analysis domain; deliver only selected knowledge files.',
                                 'Query the new wiki.json and inspect sources/limits before choosing a method.']}
        return files, result
    return store(output, inputs, build, binding)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('capture', 'collection'))
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        request = rsi_cases.read_json(args.manifest.read_text())
        result = globals()[args.operation](request, args.manifest.resolve().parent, args.output)
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({**facts('HANDOFF_INCOMPLETE'), 'diagnostic': 'Check declared materials and writable output; original business state is unchanged.'}))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result['status'] == 'PARTIAL' else 0


if __name__ == '__main__':
    raise SystemExit(main())
