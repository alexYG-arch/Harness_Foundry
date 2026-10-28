"""Deterministic feature selection; host reasoning and runtime authority stay outside."""
from copy import deepcopy
import importlib.util
import json
import hashlib
from pathlib import Path, PurePosixPath
import re

_spec = importlib.util.spec_from_file_location('capability_feature_decisions', Path(__file__).with_name('decisions.py'))
D = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(D)


def enabled(package, selection, config):
    return package.get('descriptor_version') == 2 or any(k in obj for obj in (selection, config)
                for k in ('integration_mode', 'feature_pins'))


def relative(value):
    if not isinstance(value, str):
        raise ValueError('feature file must be a canonical relative path')
    p = PurePosixPath(value)
    if not isinstance(value, str) or p.is_absolute() or p.as_posix() != value or '..' in p.parts or value == '.' or '\\' in value:
        raise ValueError('feature file must be a canonical relative path')
    return value


def validate(package):
    tools = package.get('tools', [])
    tool_map = {t['id']: t for t in tools}
    if len(tool_map) != len(tools):
        raise ValueError('duplicate tool id within descriptor')
    env = {e['id'] for e in package.get('environment', [])}
    public = {'capability.json', *package.get('materials', []), *package.get('runtime_files', []), *(t['path'] for t in tools)}
    for path in public:
        relative(path)
    if package.get('descriptor_version', 1) == 1:
        return [{'id': 'package', 'summary': package['name'], 'kind': 'tool' if tools else 'material',
                 'usage': package['usage'], 'files': sorted(public), 'default_form': 'AS_IS',
                 'requires': [], 'tool_refs': list(tool_map), 'conflict_tags': [], 'checks': []}]
    if package['descriptor_version'] != 2:
        raise ValueError('unsupported descriptor_version')
    features = deepcopy(package['features'])
    ids = [f['id'] for f in features]
    if not ids or len(ids) != len(set(ids)) or any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', x) for x in ids):
        raise ValueError('features require unique path-safe ids')
    snippet = package.get('delivery', {}).get('instruction_snippet')
    if package['usage'] != 'build' and snippet not in package.get('materials', []):
        raise ValueError('delivery instruction_snippet must reference public materials')
    owners = set()
    for f in features:
        usage = f.setdefault('usage', package['usage'])
        if usage not in ('build', 'runtime', 'both') or (package['usage'] != 'both' and usage != package['usage']):
            raise ValueError('feature usage exceeds package usage: ' + f['id'])
        if f['default_form'] not in D.FORMS or not f.get('summary') or f['kind'] not in ('tool', 'material', 'config', 'workflow', 'service', 'integration'):
            raise ValueError('invalid feature description: ' + f['id'])
        for key in ('files', 'requires', 'tool_refs', 'environment_refs', 'conflict_tags'):
            if key in f and (not isinstance(f[key], list) or not all(isinstance(v, str) for v in f[key])):
                raise ValueError('invalid feature list: ' + key)
        if not set(f['files']) <= public:
            raise ValueError('feature references undeclared or private file: ' + f['id'])
        owners.update(f['files'])
        if not set(f.get('requires', [])) <= set(ids):
            raise ValueError('feature dependency is absent: ' + f['id'])
        refs = set(f.get('tool_refs', [])) | ({f['entry']['tool']} if f.get('entry', {}).get('tool') else set())
        if not refs <= tool_map.keys() or not set(f.get('environment_refs', env)) <= env:
            raise ValueError('feature tool/environment reference is absent: ' + f['id'])
        if not set(f.get('conflict_tags', [])) <= D.TAGS:
            raise ValueError('unknown conflict tag')
        if 'EXTERNAL_BINARY' in f.get('conflict_tags', []) and not package.get('delivery', {}).get('doctor'):
            raise ValueError('external binary requires a declared doctor')
    if not (set(package.get('runtime_files', [])) | {t['path'] for t in tools}) <= owners:
        raise ValueError('FEATURE_FILE_UNOWNED')
    doctor = package.get('delivery', {}).get('doctor')
    if doctor and doctor.get('tool') not in tool_map:
        raise ValueError('doctor tool is absent')
    return features


def records(config):
    value = config.get('decision_records', [])
    if isinstance(value, str):
        value = json.loads(Path(value).read_text())
    if not isinstance(value, list):
        raise ValueError('decision_records must be a list or JSON list path')
    ids = [r['decision_id'] for r in value]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate decision_id')
    return deepcopy(value)


def select(package, selection, config, source_bytes, descriptor_sha256, *, feature_source_identity=None):
    features = validate(package)
    by_id = {f['id']: f for f in features}
    mode = selection.get('integration_mode', config.get('integration_mode', 'ON_DEMAND'))
    if mode not in ('ALL', 'ON_DEMAND'):
        raise ValueError('integration_mode must be ALL or ON_DEMAND')
    pins_list = selection.get('feature_pins', [])
    pins = {p['feature']: p for p in pins_list}
    if len(pins) != len(pins_list) or not pins.keys() <= by_id.keys():
        raise ValueError('feature pins must reference unique declared features')
    for p in pins.values():
        if p['form'] not in D.FORMS:
            raise ValueError('invalid pinned delivery form')
    links, basis = {}, {}
    for link in config.get('requirement_links', []):
        if link['capability'] != package['name']:
            continue
        if link['feature'] not in by_id:
            raise ValueError('requirement links unknown feature')
        raw = source_bytes.get(link['source_id'])
        match = re.fullmatch(r'L([1-9][0-9]*)(?:-L?([1-9][0-9]*))?', link['source_locator'])
        if raw is None or not match:
            raise ValueError('requirement source/locator is unavailable')
        start, end = int(match[1]), int(match[2] or match[1])
        if not start <= end <= len(raw.decode('utf-8').splitlines()):
            raise ValueError('requirement locator outside source')
        item = {**link, 'source_sha256': hashlib.sha256(raw).hexdigest()}
        links.setdefault(link['feature'], []).append(item)
        basis.setdefault(link['feature'], []).append({'kind': 'REQUIREMENT', **item})
    for fid, f in by_id.items():
        if mode == 'ALL' or fid in pins:
            basis.setdefault(fid, []).append({'kind': 'ALL_MODE' if mode == 'ALL' else 'EXPLICIT_PIN'})
    decisions = records(config)
    rows, requests, diagnostics = [], [], []
    active_tools, active_env, public_files, delivery_files = set(), set(), set(), set()
    tool_map = {t['id']: t for t in package.get('tools', [])}
    env_map = {e['id']: e for e in package.get('environment', [])}
    visited = set()
    roots = list(basis)
    def visit(fid):
        if fid in visited: return
        visited.add(fid)
        f = by_id[fid]
        selected = True
        form = pins.get(fid, {}).get('form', 'BUILD_ONLY' if f['usage'] == 'build' else f['default_form'])
        if f['usage'] == 'build' and form != 'BUILD_ONLY':
            raise ValueError('build-only feature cannot become a runtime feature')
        row = {'capability': package['name'], 'version': package['version'], 'feature': fid, 'usage': f['usage'],
               'mode': mode, 'kind': f['kind'], 'proposed_form': f['default_form'], 'final_form': form,
               'basis': basis.get(fid, []), 'status': 'PROPOSED' if selected else 'NOT_SELECTED_ON_DEMAND',
               'files': sorted(f['files']), 'entry': deepcopy(f.get('entry')), 'tool_refs': f.get('tool_refs', []), 'requires': f.get('requires', []),
               'conflict_tags': f.get('conflict_tags', []), 'checks': f.get('checks', []),
               'post_delivery': f.get('post_delivery', []), 'replacement': f.get('replacement'), 'decision_ids': []}
        conditions = [c for c in config.get('capability_conditions', [])
                      if c.get('capability') == package['name'] and c.get('feature') == fid and c.get('unresolved') is True]
        pin = pins.get(fid)
        if selected and (pin or form == 'EXCLUDED'):
            conditions.append({'category': 'DELIVERY_FORM', 'question': 'Confirm the explicit feature delivery choice.',
                               'evidence': [{'feature': fid, 'requested_form': form}],
                               'options': [{'id': x} for x in (['BUILD_ONLY'] if f['usage'] == 'build' else sorted(D.FORMS))]})
        for condition in conditions if selected else []:
            req = D.request({k: row[k] for k in ('capability', 'version', 'feature')}, descriptor_sha256=descriptor_sha256,
                            mode=mode, requirements=links.get(fid, []), dependencies=f.get('requires', []), condition=condition,
                            source_identity=feature_source_identity(fid) if feature_source_identity else None)
            requests.append(req)
            chosen, error = D.resolve(req, decisions)
            if chosen and pin and chosen['decision_id'] != pin.get('decision_id'):
                chosen, error = None, 'DECISION_REQUIRED'
            if error:
                diagnostics.append({'id': fid, 'code': error, 'severity': 'ERROR', 'request_id': req['request_id']})
                row['status'] = 'DECISION_REQUIRED'
            else:
                row['decision_ids'].append(chosen['decision_id'])
                row['status'] = 'DECIDED'
                if chosen['choice'] in D.FORMS:
                    if pin and chosen['choice'] != pin['form']:
                        raise ValueError('pin differs from bound decision')
                    if f['usage'] == 'build' and chosen['choice'] != 'BUILD_ONLY':
                        raise ValueError('build-only feature cannot become a runtime feature')
                    row['final_form'] = chosen['choice']
        rows.append(row)
        if row['final_form'] in ('AS_IS', 'BRIDGED', 'BUILD_ONLY'):
            for dep in f.get('requires', []):
                marker = {'kind': 'DEPENDENCY', 'feature': fid}
                if marker not in basis.setdefault(dep, []): basis[dep].append(marker)
                visit(dep)
    for fid in roots: visit(fid)
    for fid, f in by_id.items():
        if fid not in visited:
            rows.append({'capability': package['name'], 'version': package['version'], 'feature': fid,
                         'usage': f['usage'], 'mode': mode, 'kind': f['kind'], 'proposed_form': f['default_form'],
                         'final_form': None, 'status': 'NOT_SELECTED_ON_DEMAND', 'basis': [],
                         'files': sorted(f['files']), 'entry': deepcopy(f.get('entry')), 'requires': f.get('requires', []),
                         'tool_refs': f.get('tool_refs', []), 'decision_ids': []})
    rows.sort(key=lambda r: list(by_id).index(r['feature']))
    by_row = {r['feature']: r for r in rows}
    for row in rows:
        form = row['final_form']
        if form not in ('AS_IS', 'BRIDGED', 'BUILD_ONLY'):
            continue
        for dep in row['requires']:
            target = by_row[dep]
            if target['final_form'] not in ('AS_IS', 'BRIDGED', 'BUILD_ONLY') or (form != 'BUILD_ONLY' and target['final_form'] == 'BUILD_ONLY'):
                diagnostics.append({'id': row['feature'], 'code': 'DEPENDENCY_DELIVERY_CONFLICT', 'severity': 'ERROR', 'dependency': dep})
        f = by_id[row['feature']]
        refs = set(f.get('tool_refs', [])) | ({f['entry']['tool']} if f.get('entry', {}).get('tool') else set())
        if 'EXTERNAL_BINARY' in f.get('conflict_tags', []):
            # The declared doctor is a delivery prerequisite, not selection of
            # every function sharing its file or owning feature.
            doctor = package['delivery']['doctor']['tool']
            refs.add(doctor)
            row['required_doctor'] = deepcopy(package['delivery']['doctor'])
            row['tool_refs'] = sorted(set(row['tool_refs']) | {doctor})
        active_tools.update(refs)
        active_env.update(f.get('environment_refs', env_map))
        for tool in refs:
            interpreter = tool_map[tool].get('interpreter')
            if interpreter: active_env.add(interpreter)
        required_files = set(row['files']) | {tool_map[t]['path'] for t in refs}
        public_files.update(required_files)
        if form != 'BUILD_ONLY': delivery_files.update(required_files)
    snippet = package.get('delivery', {}).get('instruction_snippet')
    if delivery_files:
        delivery_files.add('capability.json')
        if snippet: delivery_files.add(snippet)
    # Existing entry preparation still diagnoses a missing interpreter; no implicit PATH lookup.
    requirements = [env_map[k] if k in env_map else {'id': k, 'kind': 'executable'} for k in sorted(active_env)]
    return {'format_version': 2, 'capability': package['name'], 'version': package['version'],
            'descriptor_sha256': descriptor_sha256, 'mode': mode, 'features': rows,
            'active_tools': sorted(active_tools), 'environment': requirements,
            'public_files': sorted(public_files), 'delivery_files': sorted(delivery_files),
            'build_materials': sorted(set(package.get('materials', [])) - {n for f in features for n in f['files']} - ({snippet} if snippet else set())),
            'instruction_snippet': snippet, 'decision_requests': requests,
            'decision_records': [d for d in decisions if any(d['decision_id'] in r['decision_ids'] for r in rows)],
            'diagnostics': diagnostics, 'commands_executed': False, 'acceptance_granted': False}


def markdown(inventories):
    lines = ['# Capability inventory', '', '| Capability | Feature | Mode | Form | State |', '|---|---|---|---|---|']
    for inv in inventories:
        for r in inv['features']:
            lines.append('| ' + ' | '.join(str(v or '—').replace('|', '\\|') for v in (
                r['capability']+'@'+r['version'], r['feature'], r['mode'], r['final_form'], r['status'])) + ' |')
    return '\n'.join(lines)+'\n'


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--materials', type=Path, required=True)
    parser.add_argument('--markdown', action='store_true')
    args = parser.parse_args()
    prep = json.loads(args.materials.read_text())['preparation']
    inventories = [r['feature_scope'] for r in prep.get('selections', []) if 'feature_scope' in r]
    inventories += list(prep.get('external_features', {}).values())
    print(markdown(inventories) if args.markdown else json.dumps(inventories, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
