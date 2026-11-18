"""Versioned per-stage selection for the optional external connection adapter."""
from copy import deepcopy
from pathlib import Path
import re


def key_of(value):
    if not isinstance(value, str):
        raise ValueError('expected a fully qualified connection key')
    scope, _, name = value.partition('.')
    if scope not in ('instance', 'project') or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', name):
        raise ValueError('expected instance.<id> or project.<id>: ' + value)
    return value


def strings(values, label):
    if not isinstance(values, list) or not all(isinstance(v, str) and v for v in values):
        raise ValueError(label + ' must be a list of names')
    if len(values) != len(set(values)):
        raise ValueError('duplicate ' + label)
    return values


def contract(config):
    if config is None:
        return None
    if not isinstance(config, dict):
        raise ValueError('connections must be an object')
    if not {'selection_version', 'build', 'target'}.intersection(config):
        return None
    if type(config.get('selection_version')) is not int or config['selection_version'] != 1:
        raise ValueError('unsupported or absent connection selection_version')
    for stage in ('build', 'target'):
        rows = config.get(stage)
        if not isinstance(rows, list):
            raise ValueError('explicit connection list required for ' + stage)
        keys = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('expected connection entry for ' + stage)
            key = key_of(row.get('key'))
            if key in keys:
                raise ValueError('duplicate connection in ' + stage + ': ' + key)
            keys.add(key)
            allowed = {'key', 'skills'}
            if stage == 'target':
                allowed.update(('mode', 'files', 'native', 'feature_selection'))
                if row.get('mode') not in ('CATALOG_ONLY', 'METHODS', 'ALL', 'NATIVE'):
                    raise ValueError('explicit target mode required: ' + key)
                if row['mode'] == 'NATIVE' and not (row.get('native') and row.get('feature_selection')):
                    raise ValueError('native target requires its operation and feature selection: ' + key)
                if 'native' in row and row['mode'] != 'NATIVE':
                    raise ValueError('native binding outside native target: ' + key)
                if 'feature_selection' in row and row['mode'] != 'NATIVE':
                    raise ValueError('select material target entries by name: ' + key)
                for field in ('feature_selection', 'native'):
                    if field in row and (not isinstance(row[field], dict) or row[field].get('key') != key):
                        raise ValueError('target reference outside selection: ' + key)
                if row['mode'] == 'CATALOG_ONLY' and row.get('files'):
                    raise ValueError('metadata selection cannot include files')
                if row['mode'] == 'NATIVE':
                    if not re.fullmatch('[0-9a-f]{64}', str(row['feature_selection'].get('mapping_sha256', ''))):
                        raise ValueError('target mapping needs a pinned SHA-256: ' + key)
                    strings(row['native'].get('operations'), 'operations')
                strings(row.get('files', []), 'files')
            if set(row) - allowed:
                raise ValueError('unknown ' + stage + ' connection field: ' + key)
            strings(row.get('skills', []), 'skills')
    build_keys = {row['key'] for row in config['build']}
    for field in ('feature_selections', 'native'):
        refs = config.get(field, [])
        if not isinstance(refs, list) or any(not isinstance(ref, dict) or ref.get('key') not in build_keys for ref in refs):
            raise ValueError(field + ' references a connection outside build selection')
    for identity in strings(config.get('skills', []), 'skills'):
        if identity.partition(':')[0] not in build_keys or ':' not in identity:
            raise ValueError('Skill outside build selection: ' + identity)
    return {key: deepcopy(config[key]) for key in ('selection_version', 'build', 'target')}


def bindings(reader, conf, project, entries):
    """Resolve revision and identity from registry metadata only."""
    requested = {row['key'] for row in entries}
    found = {}
    for scope, path in [('instance', conf['instance_root']), ('project', project)]:
        root = Path(path).resolve(strict=True)
        for key, (registry, record) in reader.registry_entries(root, scope, requested).items():
            if not record['enabled'] or record['scope_root'] != str(root):
                raise ValueError('disabled or wrong registry scope: ' + key)
            found[key] = {**deepcopy(record), 'key': key, 'registry': str(registry)}
    if requested != set(found):
        raise ValueError('missing selected connection: ' + ', '.join(sorted(requested - set(found))))
    if len(found) != len({record['catalog']['provider'] for record in found.values()}):
        raise ValueError('conflicting selected providers: ' + ', '.join(sorted(found)))
    for row in entries:
        catalog = found[row['key']]['catalog']
        absent = set(row.get('skills', [])) - {s['name'] for s in catalog['skills']}
        if absent:
            raise ValueError('unknown entry for ' + row['key'] + ': ' + ', '.join(sorted(absent)))
    return found


def project_base(base):
    prep = base.get('preparation', {})
    if (any(prep.get(key) for key in ('external_connections', 'external_features', 'feature_mappings', 'connection_selection'))
            or base.get('native_bindings') or any(r['path'].startswith('external/') for r in base.get('source_manifest', []))):
        raise ValueError('scoped selection requires a project base without previously expanded external materials')


def build_config(config, selection):
    result = deepcopy(config)
    names = [r['key'] + ':' + skill for r in selection['build'] for skill in r.get('skills', [])]
    result['skills'] = list(dict.fromkeys([*config.get('skills', []), *names]))
    return result


def limited(materials, keys):
    """Project binding checks without opening a source or following a path."""
    prep = materials['preparation']
    features = {k: v for k, v in prep.get('external_features', {}).items() if k in keys}
    selected = {'selections': prep.get('selections', []), 'stack_profiles': prep.get('stack_profiles', []),
                'external_connections': [r for r in prep.get('external_connections', []) if r['key'] in keys],
                'external_features': features, 'feature_mappings': [r for r in prep.get('feature_mappings', []) if r['key'] in keys]}
    return {'preparation': selected,
            'native_bindings': {k: v for k, v in materials.get('native_bindings', {}).items() if k in keys}}


def public_binding(reader, binding, entry):
    catalog = binding['catalog']
    key = entry['key']
    hashes = {r['path']: r['sha256'] for r in catalog['files']}
    names = set(entry.get('skills', []))
    chosen = [s for s in catalog['skills'] if entry['mode'] == 'ALL' or s['name'] in names]
    if names - {s['name'] for s in chosen}:
        raise ValueError('unknown target method: ' + key)
    public = set(entry.get('files', []))
    if entry['mode'] == 'ALL':
        public.update(catalog['base_materials'])
    if entry['mode'] != 'CATALOG_ONLY':
        for item in chosen:
            public.add(item['path'])
            public.update(item.get('requires', []))
    if set(entry.get('files', [])) - set(catalog['base_materials']):
        raise ValueError('extra public files must be registered base materials: ' + key)
    if public.intersection(reader.DESCRIPTORS):
        raise ValueError('passive methods cannot install plugin descriptors: ' + key)
    checked = {name: hashes[name] for name in sorted(public | {catalog['descriptor']})}
    with reader.source_files(binding['source']) as (read, _):
        for name in ('LICENSE', 'LICENSE.md', 'COPYING'):
            try:
                license_bytes = read(name)
            except (FileNotFoundError, KeyError):
                continue
            checked[name] = reader.digest(license_bytes)
            public.add(name)
    return {**binding, 'selected_files': checked, 'public_paths': sorted(public),
            'public_catalog': {'provider': catalog['provider'], 'version': catalog['version'],
                               'source_catalog_sha256': reader.digest(reader.encoded(catalog)),
                               'mode': entry['mode'], 'skills': [
                    {k: s[k] for k in ('name', 'description', 'kind') if k in s}
                    if entry['mode'] == 'CATALOG_ONLY' else deepcopy(s) for s in chosen]}}


def target_view(materials, prepare, features):
    saved = materials['preparation'].get('connection_selection')
    if 'connection_selection' not in materials['preparation']:
        return materials
    if not isinstance(saved, dict):
        raise ValueError('invalid saved connection selection')
    selection = contract(saved)
    if selection is None:
        raise ValueError('missing saved connection protocol')
    rows = selection['target']
    pins = saved['target_bindings']
    if {r['key'] for r in rows} != set(pins):
        raise ValueError('saved target selection and bindings differ')
    result = limited(materials, set())
    prep = result['preparation']
    reader = prepare._connections
    for row in rows:
        key = row['key']
        binding = pins[key]
        if binding['key'] != key:
            raise ValueError('saved target key mismatch: ' + key)
        if row['mode'] != 'NATIVE':
            prep['external_connections'].append(public_binding(reader, binding, row))
            continue
        config = {'native': [row['native']], 'feature_selections': [row['feature_selection']]}
        context = saved.get('feature_context', {})
        needed = {r['source_id'] for r in context.get('requirement_links', []) if r['capability'] == key}
        sources = {}
        for item in materials['source_manifest']:
            if item['source_id'] in needed and not item['path'].startswith('external/'):
                sources[item['source_id']] = prepare._file(Path(materials['preparation']['source_root']), item['path']).read_bytes()
        adjusted, projections, mappings = features.prepare(config, {'connections': [binding]}, context, sources)
        projection = projections[key]
        if (row['feature_selection'].get('mapping_sha256') != projection['mapping_sha256']
                or any(r.get('severity') == 'ERROR' for r in projection['diagnostics'])):
            raise ValueError('target feature mapping changed or incomplete: ' + key)
        selected = [f for f in projection['features'] if f['final_form'] in ('AS_IS', 'BRIDGED')]
        operations = sorted({op for f in selected for op in f.get('operations', [])})
        if not operations or set(operations) != set(row['native'].get('operations', [])):
            raise ValueError('target operations must match selected runnable features: ' + key)
        opts = {**adjusted['native'][0], 'operations': operations}
        result['native_bindings'][key] = prepare._native.bind_native(binding, opts, project_root=Path(saved['project_root']))
        prep['external_connections'].append(binding)
        prep['external_features'][key] = projection
        prep['feature_mappings'].extend(mappings)
    if prep['external_features']:
        prep['external_features_sha256'] = prepare._digest(prepare._json(prep['external_features']))
    return result
