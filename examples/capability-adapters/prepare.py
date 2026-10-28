"""Optional external capability materials; never installs, authorizes or runs a task.

The manifest is an example-layer convention, not a Plan or protocol extension.
Only explicitly selected ordinary files are read. Existing contracts remain the
caller's responsibility; fragments do not provide an independent verdict.
"""

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re


_spec = importlib.util.spec_from_file_location('capability_environment', Path(__file__).with_name('environment.py'))
_environment = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_environment)
resolve_environment = _environment.resolve_environment
_spec = importlib.util.spec_from_file_location('capability_connections', Path(__file__).with_name('connections.py'))
_connections = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_connections)
_spec = importlib.util.spec_from_file_location('capability_native', Path(__file__).with_name('native.py'))
_native = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_native)
_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')
_TEXT = {'.md', '.markdown', '.txt', '.json'}


def _id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError('expected a path-safe identifier: ' + repr(value))
    return value


def _relative(value):
    if not isinstance(value, str):
        raise ValueError('file references must be relative strings')
    path = PurePosixPath(value)
    if (path.is_absolute() or path.as_posix() != value or value == '.' or '..' in path.parts
            or '\\' in value or ':' in value or any(ord(c) < 32 for c in value)):
        raise ValueError('expected a canonical relative file: ' + value)
    return path


def _file(root, relative):
    path = (root / _relative(relative)).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('reference is not a file inside its declared root: ' + relative)
    return path


def _json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def _text(raw, name):
    text = raw.decode('utf-8')
    if Path(name).suffix.lower() not in _TEXT or not text.strip():
        raise ValueError('source must be nonempty Markdown, text or JSON: ' + name)
    if Path(name).suffix.lower() == '.json':
        json.loads(text, parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
    return raw


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _merge(mapping, key, value, label):
    if key in mapping and mapping[key] != value:
        raise ValueError(label + ' conflict: ' + key)
    mapping[key] = value


def _call_path(value):
    # Resolve parent aliases, not the final executable link: different venvs
    # can invoke the same binary with different environments.
    path = Path(value)
    return path.parent.resolve() / path.name


def _call_locations(value):
    # Inspect names before following links, including names inside a link's
    # target. This follows only the declared call chain, never a directory tree.
    pending, seen = [Path(value)], set()
    while pending:
        path = pending.pop()
        for prefix in (path, *path.parents):
            location = prefix.parent.resolve() / prefix.name
            if location in seen:
                continue
            seen.add(location)
            yield location
            if location.is_symlink():
                target = location.readlink()
                pending.append(target if target.is_absolute() else location.parent / target)


def _merge_executable(mapping, key, value):
    if key not in mapping:
        mapping[key] = value
    elif _call_path(mapping[key]) != _call_path(value):
        raise ValueError('scope executable conflict: ' + key)


def _merge_environment(previous, current):
    if not previous:
        return current
    result = deepcopy(current)
    result['bindings'] = deepcopy(previous['bindings'])
    for key, facts in current['bindings'].items():
        if key not in result['bindings']:
            result['bindings'][key] = deepcopy(facts)
            continue
        old = result['bindings'][key]
        paths = [row.get('absolute_path') for row in (old, facts)]
        resolve = _call_path if facts['kind'] == 'executable' else lambda p: Path(p).resolve()
        if (old['kind'] != facts['kind'] or all(paths) and resolve(paths[0]) != resolve(paths[1])
                or all(row.get('resolved_path') for row in (old, facts))
                and old['resolved_path'] != facts['resolved_path']):
            raise ValueError('environment binding conflict: ' + key)
        versions = [row.get('observed_version') for row in (old, facts)]
        if all(value is not None for value in versions):
            comparable = [_environment._numeric_version(value) for value in versions]
            if (comparable[0] != comparable[1] if all(v is not None for v in comparable) else versions[0] != versions[1]):
                raise ValueError('environment version observation conflict: ' + key)
        for field in ('absolute_path', 'resolved_path', 'observed_version'):
            if old.get(field) is None:
                old[field] = facts.get(field)
        if old.get('observed_version') is not None:
            old['version_source'] = 'SUPPLIED_BINDING'
    result['diagnostics'] = deepcopy(previous.get('diagnostics', []))
    for row in current['diagnostics']:
        if row not in result['diagnostics']:
            result['diagnostics'].append(row)
    fragment = deepcopy(previous['scope_fragment'])
    for key, value in current['scope_fragment']['executables'].items():
        _merge_executable(fragment['executables'], key, value)
    fragment['source_read_roots'] = list(dict.fromkeys([
        *fragment['source_read_roots'], *current['scope_fragment']['source_read_roots']]))
    result['scope_fragment'] = fragment
    if previous['status'] != 'READY':
        result['status'] = 'INCOMPLETE'
    return result


def _insert_file(files, relative, raw):
    path = _relative(relative)
    for previous in files:
        other = PurePosixPath(previous)
        if path != other and (path in other.parents or other in path.parents):
            raise ValueError('file/directory destination conflict: ' + relative)
    _merge(files, relative, raw, 'file destination')


def _version_key(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)*', value):
        raise ValueError('cannot combine nonnumeric version range: ' + repr(value))
    result = tuple(int(v) for v in value.split('.'))
    while len(result) > 1 and result[-1] == 0:
        result = result[:-1]
    return result


def _merge_requirement(requirements, dependency):
    key = _id(dependency['id'])
    if key not in requirements:
        requirements[key] = deepcopy(dependency)
        return
    old = requirements[key]
    bounds = ('version_min', 'version_max_exclusive')
    if {k: v for k, v in old.items() if k not in bounds} != {k: v for k, v in dependency.items() if k not in bounds}:
        raise ValueError('environment requirement conflict: ' + key)
    for bound, choose in zip(bounds, (max, min)):
        values = [row[bound] for row in (old, dependency) if bound in row]
        if values:
            old[bound] = choose(values, key=_version_key)
    if all(bound in old for bound in bounds) and _version_key(old[bounds[0]]) >= _version_key(old[bounds[1]]):
        raise ValueError('environment version ranges do not intersect: ' + key)


def check_selection(materials):
    """Recheck exactly declared package files before consuming a prepared binding.

    This read-only check is not a lock, sandbox, acceptance or dispatch. Host SDK
    observations are separate. WP03 consumers must call it at their handoff.
    """
    changes = []
    for package in materials['preparation']['selections']:
        root = Path(package['directory'])
        feature_scope = package.get('feature_scope')
        if feature_scope is not None and _digest(_json(feature_scope)) != package.get('feature_scope_sha256'):
            changes.append({'name': package['name'], 'version': package['version'], 'path': 'feature_scope'})
        for item in package['files']:
            try:
                path = _file(root, item['path'])
                matched = str(path) == item['resolved_path'] and _digest(path.read_bytes()) == item['sha256']
            except (OSError, RuntimeError, ValueError):
                matched = False
            if not matched:
                changes.append({'name': package['name'], 'version': package['version'], 'path': item['path']})
    for binding in materials['preparation'].get('external_connections', []):
        try:
            matched = _connections.check_binding(binding)
        except (OSError, ValueError, KeyError, TypeError, _connections.zipfile.BadZipFile):
            matched = False
        if not matched:
            changes.append({'name': binding['key'], 'version': binding['catalog']['version'], 'path': binding['source']})
    for key, binding in materials.get('native_bindings', {}).items():
        try:
            _native.check_native(binding)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            changes.append({'name': key, 'version': binding['connection']['catalog']['version'], 'path': binding['root']})
    prep = materials['preparation']
    if prep.get('external_features') and _digest(_json(prep['external_features'])) != prep.get('external_features_sha256'):
        changes.append({'name': 'external', 'version': '', 'path': 'feature_scope'})
    # Decisions can reference public runtime files outside a Skill catalog,
    # including when the chosen representation has no native binding.
    connections = {b['key']: b for b in prep.get('external_connections', [])}
    for key, projection in prep.get('external_features', {}).items():
        refs = {r['path']: r['sha256'] for request in projection['decision_requests']
                for r in request.get('source_identity', {}).get('files', [])}
        if not refs:
            continue
        try:
            with _connections.source_files(connections[key]['source']) as (read, _):
                matched = all(_digest(read(name)) == digest for name, digest in refs.items())
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, _connections.zipfile.BadZipFile):
            matched = False
        if not matched:
            changes.append({'name': key, 'version': projection['version'], 'path': 'decision_sources'})
    for mapping in prep.get('feature_mappings', []):
        try:
            matched = _digest(Path(mapping['path']).read_bytes()) == mapping['sha256']
        except OSError:
            matched = False
        if not matched: changes.append({'name': mapping['key'], 'version': '', 'path': mapping['path']})
    for row in materials['preparation'].get('stack_profiles', []):
        try:
            path = Path(row['source'])
            matched = str(path.resolve(strict=True)) == row['resolved_path'] and _digest(path.read_bytes()) == row['sha256']
        except (OSError, RuntimeError, ValueError):
            matched = False
        if not matched:
            changes.append({'name': row['package'], 'version': row['version'], 'path': row['source']})
    return {'status': 'MATCH' if not changes else 'CHANGED', 'changes': changes,
            'commands_executed': False, 'acceptance_granted': False}


def _prepare_verifier_inputs(scope, protected, production, output):
    """Validate project/package checker inputs and merge their declared files.

    Callers own a copied scope; this neither copies files nor creates resources.
    Inspect all original inputs before deduplication so no private origin is lost.
    """
    reads = [Path(p).resolve() for p in [*scope.get('source_read_roots', []),
                                       *scope.get('executables', {}).values()]]
    hidden = [Path(row['source']).resolve(strict=True) for row in protected if not row.get('shared', False)]
    destinations, by_destination = {}, {}
    for row in protected:
        _insert_file(destinations, row['path'], Path(row['source']).read_bytes())
        if row['path'] in by_destination and bool(row.get('shared')) != bool(by_destination[row['path']].get('shared')):
            raise ValueError('verification sharing conflict: ' + row['path'])
        by_destination.setdefault(row['path'], row)
    protected = list(by_destination.values())
    if 'verification_root' in scope:
        hidden.append(Path(scope['verification_root']).resolve())
    for secret in hidden:
        if any(secret == p or secret.is_relative_to(p) or p.is_relative_to(secret) for p in [*reads, *production]):
            raise ValueError('production inputs expose protected verification material')
    workspace = Path(scope['workspace_root']).resolve() if 'workspace_root' in scope else None
    if workspace and any(p == workspace or p.is_relative_to(workspace) or workspace.is_relative_to(p)
                         for p in [output.resolve(), *hidden]):
        raise ValueError('output materials and protected verification material must be separate from the workspace')
    if 'verification_resources' in scope:
        resource = scope['verification_resources']
        resource['checker_files'] = list(dict.fromkeys([*resource.get('checker_files', []),
                                                        *[row['path'] for row in protected]]))
    return protected


def build_materials(config, output_root, *, connection_snapshot=None):
    """Return (materials, relative-file -> bytes) without writing or executing.

    output_root names a new host materials directory, never the target workspace.
    Relative package/tool bindings use the explicitly supplied project_root.
    """
    if not Path(config['project_root']).is_absolute():
        raise ValueError('project_root must be explicit and absolute')
    project = Path(config['project_root']).resolve(strict=True)
    if not project.is_dir():
        raise ValueError('project_root must be an existing directory')
    output = Path(output_root).absolute()
    base = deepcopy(config.get('base_materials', {}))
    request = base.get('request')
    scope = base.get('scope', {})
    previous = base.get('preparation', {})
    files, manifest, origins, sources = {}, [], [], {}
    protected = deepcopy(previous.get('verifier_inputs', []))
    selections = deepcopy(previous.get('selections', []))
    production, tool_entries, requirements, runtime_files = [], {}, {}, []
    stack_profiles = deepcopy(previous.get('stack_profiles', []))
    profile_tools, profile_reads = {}, []
    task_inputs, diagnostics = {}, deepcopy(previous.get('diagnostics', []))

    def add_source(source_id, relative, raw, origin):
        _id(source_id)
        if source_id in sources:
            raise ValueError('source_id conflict: ' + source_id)
        _text(raw, relative)
        _insert_file(files, 'sources/' + relative, raw)
        sources[source_id] = {'source_id': source_id, 'path_or_uri': relative, 'loaded_completely': True}
        manifest.append({'source_id': source_id, 'path': relative})
        origins.append({'source_id': source_id, 'origin': origin})

    if base:
        if request is None:
            raise ValueError('base_materials requires its existing request')
        if not Path(config['source_root']).is_absolute():
            raise ValueError('source_root must be explicit and absolute')
        source_root = Path(config['source_root']).resolve(strict=True)
        original = {row['source_id']: row for row in request['requirement_ir']['sources']}
        rows = base['source_manifest']
        if len(original) != len(request['requirement_ir']['sources']) or {r['source_id'] for r in rows} != set(original):
            raise ValueError('base source manifest and requirement sources differ')
        for row in rows:
            if original[row['source_id']]['path_or_uri'] != row['path']:
                raise ValueError('base source path disagrees with requirement: ' + row['source_id'])
            source = _file(source_root, row['path'])
            add_source(row['source_id'], row['path'], source.read_bytes(), str(source))
            production.append(source)

    external = deepcopy(previous.get('external_connections', []))
    connection_config = config.get('connections')
    external_features = deepcopy(previous.get('external_features', {}))
    feature_mappings = deepcopy(previous.get('feature_mappings', []))
    if connection_config is not None:
        # Upgrade routing can pass its one read of this exact connection config.
        loaded = connection_snapshot if connection_snapshot is not None else _connections.load_connections(
            connection_config['instance_root'], project, connection_config.get('skills', []))
        if connection_config.get('feature_selections'):
            spec = importlib.util.spec_from_file_location('capability_feature_connections', Path(__file__).with_name('feature_connections.py'))
            feature_connections = importlib.util.module_from_spec(spec); spec.loader.exec_module(feature_connections)
            original_catalogs = {r['key']: r['catalog'] for r in loaded['connections']}
            connection_config, projections, mappings = feature_connections.prepare(connection_config, loaded, config,
                {r['source_id']: files['sources/' + r['path']] for r in manifest})
            loaded = _connections.load_connections(connection_config['instance_root'], project, connection_config['skills'])
            if original_catalogs != {r['key']: r['catalog'] for r in loaded['connections']}:
                raise ValueError('external catalog changed during feature selection')
            for key, projection in projections.items():
                _merge(external_features, key, projection, 'external feature selection')
                diagnostics.extend(projection['diagnostics'])
            for mapping in mappings:
                if mapping not in feature_mappings: feature_mappings.append(mapping)
        diagnostics.extend(loaded['diagnostics'])
        for binding in loaded['connections']:
            existing = next((b for b in external if b['key'] == binding['key']), None)
            if existing and any(existing[k] != binding[k] for k in ('source', 'resolved_source', 'catalog')):
                raise ValueError('external connection differs from base materials: ' + binding['key'])
            if existing is None:
                external.append(binding)
            key = binding['key']
            entries = [('_connection/catalog.json', _json(binding['catalog']))]
            if key in external_features:
                entries.append(('_connection/feature-scope.json', _json(external_features[key])))
            entries.extend(('materials/' + m['path'], m['text'].encode('utf-8')) for m in loaded['materials'] if m['connection'] == key)
            for relative, raw in entries:
                destination = 'external/' + key + '/' + relative
                prior = next((r for r in manifest if r['path'] == destination), None)
                if prior:
                    if files['sources/' + destination] != raw:
                        raise ValueError('external material differs from captured source: ' + destination)
                    sid = prior['source_id']
                else:
                    index = 1
                    while 'EXT-' + key + '-M' + str(index) in sources:
                        index += 1
                    sid = 'EXT-' + key + '-M' + str(index)
                    add_source(sid, destination, raw, binding['source'])
                for task in connection_config.get('workpack_ids', []):
                    task_inputs.setdefault(_id(task), []).append({'kind': 'SOURCE', 'id': sid})
            source_path = Path(binding['source']).resolve(strict=True)
            production.extend([(source_path / f['path']).resolve(strict=True) for f in binding['catalog']['files']]
                              if source_path.is_dir() else [source_path])
        if request and loaded['connections'] and not connection_config.get('workpack_ids'):
            diagnostics.append({'id': 'external', 'code': 'SOURCE_TASK_BINDING_MISSING', 'severity': 'ERROR',
                                'message': 'choose production Workpack inputs for connected materials'})

    native_bindings = deepcopy(base.get('native_bindings', {}))
    for native_config in (connection_config or {}).get('native', []):
        key = native_config['key']
        rows = [b for b in external if b['key'] == key]
        if len(rows) != 1:
            raise ValueError('native connection is unavailable: ' + key)
        bound = _native.bind_native(rows[0], native_config, project_root=project)
        _merge(native_bindings, key, bound, 'native binding')
    for key, bound in native_bindings.items():
        runtime_files.append(bound['root'])
        production.append(Path(bound['root']))
        for role, invocation in bound['environment']['scope_fragment']['executables'].items():
            identity = key + '.' + role
            _merge_requirement(requirements, {'id': identity, 'kind': 'executable'})
            _merge_executable(profile_tools, identity, invocation)
        diagnostics.extend(bound['environment']['diagnostics'])
        relative = 'external/' + key + '/native-handoff.json'
        public = {'provider': bound['adapter']['provider'], 'adapter_version': bound['adapter']['version'],
                  'version': bound['connection']['catalog']['version'],
                  'native_identity': {'adapter_sha256': bound['adapter_sha256'], 'files_sha256': _digest(_connections.encoded(bound['files']))},
                  'root': bound['root'], 'operations': {n: bound['adapter']['operations'][n] for n in bound['operations']},
                  'skills': bound['adapter'].get('skills', {}), 'external_cli': bound['adapter'].get('external_cli', {}),
                  'environment': bound['environment'], 'commands_executed': False, 'acceptance_granted': False}
        if key in external_features:
            selected_skills = {v for f in external_features[key]['features'] if f['final_form'] in ('AS_IS', 'BRIDGED', 'BUILD_ONLY') for v in f.get('skills', [])}
            public['skills'] = {k: v for k, v in public['skills'].items() if k in selected_skills}
        prior = next((r for r in manifest if r['path'] == relative), None)
        raw = _json(public)
        sid = prior['source_id'] if prior else 'EXT-' + key + '-NATIVE'
        if prior:
            if files['sources/' + relative] != raw:
                raise ValueError('native handoff differs from base: ' + key)
        else:
            add_source(sid, relative, raw, bound['adapter_path'])
        for task in (connection_config or {}).get('workpack_ids', []):
            task_inputs.setdefault(_id(task), []).append({'kind': 'SOURCE', 'id': sid})

    chosen = config.get('selections', [])
    if not chosen and not external:
        raise ValueError('select at least one explicit capability directory')
    names = {row['name'] for row in selections}
    for selection in chosen:
        directory = Path(selection['directory'])
        root = (directory if directory.is_absolute() else project / directory).resolve(strict=True)
        descriptor = _file(root, 'capability.json')
        descriptor_bytes = descriptor.read_bytes()
        package = json.loads(descriptor_bytes)
        name = _id(package['name'])
        if name in names:
            raise ValueError('select one explicit version per capability name: ' + name)
        names.add(name)
        version = package['version']
        if not isinstance(version, str) or not version or selection['version'] != version:
            raise ValueError('selected version differs from capability.json: ' + name)
        if package['usage'] not in ('build', 'runtime', 'both'):
            raise ValueError('usage must be build, runtime or both: ' + name)
        for key in ('inputs', 'outputs'):
            if not isinstance(package[key], list) or not package[key] or not all(isinstance(v, str) and v for v in package[key]):
                raise ValueError('describe applicable ' + key + ': ' + name)
        feature_scope = None
        new_features = package.get('descriptor_version') == 2 or any(
            key in obj for obj in (selection, config) for key in ('integration_mode', 'feature_pins'))
        if new_features:
            spec = importlib.util.spec_from_file_location('capability_inventory', Path(__file__).with_name('inventory.py'))
            inventory = importlib.util.module_from_spec(spec); spec.loader.exec_module(inventory)
            source_bytes = {r['source_id']: files['sources/' + r['path']] for r in manifest}
            feature_scope = inventory.select(package, selection, config, source_bytes, _digest(descriptor_bytes))
            diagnostics.extend(feature_scope['diagnostics'])
        selected_files = {'capability.json': (descriptor, descriptor_bytes)}
        source_ids = []
        public_files = []
        for index, relative in enumerate(package.get('materials', []), 1):
            path = _file(root, relative)
            raw = path.read_bytes()
            selected_files[relative] = (path, raw)
            production.append(path)
            sid = 'CAP-' + name + '-M' + str(index)
            add_source(sid, 'capabilities/' + name + '/' + relative, raw, str(path))
            source_ids.append(sid)
            public_files.append({'path': relative, 'sha256': _digest(raw)})
        for tool in package.get('tools', []):
            key = _id(tool['id'])
            path = _file(root, tool['path'])
            raw = path.read_bytes()
            selected_files[tool['path']] = (path, raw)
            production.append(path)
            entry = {'id': key, 'path': str(path), 'package': name, 'version': version,
                     'interpreter': tool.get('interpreter'), 'interpreter_args': tool.get('interpreter_args', [])}
            if not isinstance(entry['interpreter_args'], list) or not all(isinstance(v, str) for v in entry['interpreter_args']):
                raise ValueError('interpreter_args must be a list of strings: ' + key)
            if feature_scope is None or key in feature_scope['active_tools']:
                _merge(tool_entries, key, entry, 'tool')
            public_files.append({'path': tool['path'], 'sha256': _digest(raw)})
        for relative in package.get('runtime_files', []):
            path = _file(root, relative)
            raw = path.read_bytes()
            selected_files[relative] = (path, raw)
            production.append(path)
            if feature_scope is None or relative in feature_scope['public_files']:
                runtime_files.append(str(path))
            public_files.append({'path': relative, 'sha256': _digest(raw)})
        if not package.get('materials') and not package.get('tools'):
            raise ValueError('capability requires a real material or tool entry: ' + name)
        for entry in package.get('verification_files', []):
            relative = entry if isinstance(entry, str) else entry['path']
            shared = isinstance(entry, dict) and entry.get('shared') is True
            path = _file(root, relative)
            raw = path.read_bytes()
            selected_files[relative] = (path, raw)
            protected.append({'source': str(path), 'path': 'capabilities/' + name + '/' + relative,
                              'sha256': _digest(raw), 'shared': shared})
        for dependency in (package.get('environment', []) if feature_scope is None else feature_scope['environment']):
            _merge_requirement(requirements, dependency)
        if selection.get('environment_profile'):
            spec = importlib.util.spec_from_file_location('stack_profile_prepare', Path(__file__).with_name('stack_runtime.py'))
            runtime = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(runtime)
            path = Path(selection['environment_profile'])
            if not path.is_absolute():
                raise ValueError('environment_profile must be absolute')
            raw = path.read_bytes()
            profile = runtime.validate_profile(json.loads(raw), {'name': name, 'version': version})
            relative = 'capabilities/' + name + '/environment.json'
            sid = 'CAP-' + name + '-ENV'
            add_source(sid, relative, raw, str(path))
            source_ids.append(sid)
            production.append(path)
            runtime_files.append(str(path))
            protected.append({'source': str(path), 'path': relative, 'sha256': _digest(raw), 'shared': True})
            stack_profiles.append({'package': name, 'version': version, 'source': str(path),
                                   'resolved_path': str(path.resolve(strict=True)), 'sha256': _digest(raw),
                                   'source_id': sid, 'target_path': relative})
            for role, invocation in profile['tools'].items():
                _merge_requirement(requirements, {'id': role, 'kind': 'executable'})
                _merge_executable(profile_tools, role, invocation)
            for value in profile.get('read_paths', []):
                if not isinstance(value, str) or not Path(value).is_absolute():
                    raise ValueError('profile read_paths must be absolute')
                profile_reads.append(value)
        identity = {'name': name, 'version': version, 'usage': package['usage'],
                    'inputs': package['inputs'], 'outputs': package['outputs'],
                    'files': public_files, 'tools': package.get('tools', []),
                    'environment': package.get('environment', []), 'support': package.get('support', '')}
        if feature_scope is not None:
            identity['feature_scope'] = feature_scope
        sid = 'CAP-' + name + '-VERSION'
        add_source(sid, 'capabilities/' + name + '/selected-version.json', _json(identity), str(descriptor))
        source_ids.append(sid)
        if request and not selection.get('workpack_ids'):
            diagnostics.append({'id': name, 'code': 'SOURCE_TASK_BINDING_MISSING', 'severity': 'ERROR',
                                'message': 'choose production Workpack inputs for this selected version'})
        for task in selection.get('workpack_ids', []):
            task_inputs.setdefault(_id(task), []).extend({'kind': 'SOURCE', 'id': value} for value in source_ids)
        selections.append({'name': name, 'version': version, 'directory': str(root), 'usage': package['usage'],
                           'files': [{'path': rel, 'resolved_path': str(path), 'sha256': _digest(raw)}
                                     for rel, (path, raw) in selected_files.items()]})
        if feature_scope is not None:
            selections[-1]['feature_scope'] = feature_scope
            selections[-1]['feature_scope_sha256'] = _digest(_json(feature_scope))

    old_environment = previous.get('environment', {})
    bindings = {key: {'path': row.get('absolute_path') or row['path'],
                      'observed_version': row.get('observed_version')}
                for key, row in old_environment.get('bindings', {}).items()}
    for key, value in config.get('environment_bindings', {}).items():
        # A path-only restatement keeps the old observation. The merge below
        # still rejects a changed invocation/resolved object; explicit null is
        # not an omitted observation.
        if isinstance(value, dict) and 'observed_version' not in value and key in bindings:
            value = {**value, 'observed_version': bindings[key]['observed_version']}
        bindings[key] = value
    for role, invocation in profile_tools.items():
        bindings.setdefault(role, {'path': invocation})
    environment = _merge_environment(old_environment, resolve_environment(
        list(requirements.values()), bindings, project_root=project))
    for role, invocation in profile_tools.items():
        actual = environment['bindings'].get(role, {}).get('absolute_path')
        if actual is not None and _call_path(actual) != _call_path(invocation):
            raise ValueError('profile tool differs from environment binding: ' + role)
    fragment = deepcopy(base.get('scope_fragment', {'executables': {}, 'source_read_roots': []}))
    for key, value in environment['scope_fragment']['executables'].items():
        _merge_executable(fragment['executables'], key, value)
    fragment['source_read_roots'] = list(dict.fromkeys([
        *fragment['source_read_roots'], *environment['scope_fragment']['source_read_roots'], *profile_reads]))
    diagnostics.extend(row for row in environment['diagnostics'] if row not in diagnostics)
    calls = deepcopy(base.get('tool_bindings', {}))
    for key, tool in tool_entries.items():
        interpreter = tool['interpreter']
        if interpreter:
            if interpreter not in fragment['executables']:
                diagnostics.append({'id': key, 'code': 'INTERPRETER_UNRESOLVED', 'message': interpreter, 'severity': 'ERROR'})
                continue
            prefix = [interpreter, *tool['interpreter_args'], tool['path']]
        else:
            if not os.access(tool['path'], os.X_OK):
                diagnostics.append({'id': key, 'code': 'TOOL_NOT_EXECUTABLE', 'message': tool['path'], 'severity': 'ERROR'})
                continue
            _merge_executable(fragment['executables'], key, tool['path'])
            prefix = [key]
        _merge(calls, key, {'argv_prefix': prefix, 'package': tool['package'], 'version': tool['version']}, 'tool')
    for key, bound in native_bindings.items():
        for operation in bound['operations']:
            _merge(calls, key + '.' + operation, {'native_connection': key, 'operation': operation}, 'tool')
    fragment['source_read_roots'] = list(dict.fromkeys([*fragment['source_read_roots'], *runtime_files,
                                                     *[t['path'] for t in tool_entries.values()]]))
    merged_scope = deepcopy(scope)
    merged_scope.setdefault('executables', {})
    for key, value in fragment['executables'].items():
        _merge_executable(merged_scope.setdefault('executables', {}), key, value)
    merged_scope['source_read_roots'] = list(dict.fromkeys([*merged_scope.get('source_read_roots', []), *fragment['source_read_roots']]))
    # These roots are scope-wide, not per-Workpack access restrictions.
    reads = [Path(p).resolve() for p in [*merged_scope['source_read_roots'], *merged_scope['executables'].values()]]
    protected = _prepare_verifier_inputs(merged_scope, protected, production, output)
    workspace = Path(scope['workspace_root']).resolve() if 'workspace_root' in scope else None
    # The existing scope owns write-path validation (including the valid '.').
    writes = [(workspace / value).resolve() for roots in scope.get('task_write_roots', {}).values()
              for value in roots] if workspace else []
    # Check each traversed name before following that link. Fully resolving a
    # workspace alias and an SDK link at once would hide a writable middle link.
    # Ancestors are traversal locations, not read roots: an ancestor containing
    # a write root does not itself make an otherwise read-only call writable.
    calls_at = [path for value in [*merged_scope['executables'].values(), *profile_reads,
                                   *(row['source'] for row in stack_profiles)]
                for path in _call_locations(value)]
    if any(p == root or p.is_relative_to(root) or root.is_relative_to(p)
           for p in [*reads, *production] for root in writes) or any(
            p.is_relative_to(root) for p in calls_at for root in writes):
        raise ValueError('ordinary dependencies must be separate from actual task write roots')

    review_removed = []
    if request:
        review_removed = [key for key in request if key not in ('requirement_ir', 'plan')]
        request = {key: request[key] for key in ('requirement_ir', 'plan')}
        request['requirement_ir']['sources'] = list(sources.values())
        tasks = {t['workpack_id']: t for t in request['plan']['workpacks']}
        for task, values in task_inputs.items():
            if task not in tasks:
                raise ValueError('selected Workpack is absent from base plan: ' + task)
            for value in values:
                if value not in tasks[task]['inputs']:
                    tasks[task]['inputs'].append(value)
        if not task_inputs:
            diagnostics.append({'id': 'selection', 'code': 'SOURCE_TASK_BINDING_MISSING',
                                'severity': 'ERROR', 'message': 'choose production Workpack inputs for selected versions'})
    result = {'source_manifest': manifest,
              'scope_fragment': fragment,
              'request_fragment': {'sources': list(sources.values()), 'workpack_inputs': task_inputs},
              'tool_bindings': calls, 'native_bindings': native_bindings,
              'preparation': {**deepcopy(base.get('preparation', {})), 'status': 'MATERIALS_ONLY_NOT_APPROVED',
                  'readiness': 'INCOMPLETE' if environment['status'] != 'READY' or any(d.get('severity') == 'ERROR' for d in diagnostics) else 'READY',
                  'source_root': str(output / 'sources'), 'source_origins': origins,
                  'selections': selections, 'environment': environment, 'diagnostics': diagnostics,
                  'external_connections': external,
                  'stack_profiles': stack_profiles,
                  'retained_diagnostics': deepcopy(previous.get('diagnostics', [])),
                  'verifier_inputs': protected, 'checker_files_fragment': [p['path'] for p in protected],
                  'removed_request_context': review_removed, 'commands_executed': False,
                  'runtime_verified': False, 'protected_copy_created': False}}
    if external_features:
        result['preparation']['external_features'] = external_features
        result['preparation']['external_features_sha256'] = _digest(_json(external_features))
        result['preparation']['feature_mappings'] = feature_mappings
    old_sources = {r['source_id'] for r in base.get('source_manifest', [])}
    # base/request may have been assembled above: compare task inputs to the
    # untouched caller value, never to the output being constructed.
    old_tasks = {t['workpack_id']: t.get('inputs', []) for t in config.get('base_materials', {}).get('request', {}).get('plan', {}).get('workpacks', [])}
    result['preparation']['changes'] = {
        'sources_added': [r['source_id'] for r in manifest if r['source_id'] not in old_sources],
        'workpack_inputs_added': {task: [r for r in values if r not in old_tasks.get(task, [])] for task, values in task_inputs.items()},
        'executables_added': {k: v for k, v in fragment['executables'].items() if k not in scope.get('executables', {})},
        'read_roots_added': [p for p in fragment['source_read_roots'] if p not in scope.get('source_read_roots', [])],
        'checker_files_added': [p['path'] for p in protected if p['path'] not in scope.get('verification_resources', {}).get('checker_files', [])],
    }
    if request:
        result['request'], result['scope'] = request, merged_scope
    return result, files


def write_materials(config, output_root):
    output = Path(output_root).absolute()
    if output.exists():
        raise ValueError('output must be a new materials directory')
    materials, files = build_materials(config, output)
    output.mkdir(parents=True, exist_ok=False)
    for relative, raw in files.items():
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as stream:
            stream.write(raw)
    with (output / 'materials.json').open('x', encoding='utf-8') as stream:
        stream.write(_json(materials).decode('utf-8'))
    return materials


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check-selection', type=Path)
    args = parser.parse_args()
    try:
        if args.check_selection:
            if args.config or args.output:
                parser.error('check-selection does not generate materials')
            result = check_selection(json.loads(args.check_selection.read_text(encoding='utf-8')))
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result['status'] == 'MATCH' else 1
        if not args.config or not args.output:
            parser.error('config and output are required for material preparation')
        result = write_materials(json.loads(args.config.read_text(encoding='utf-8')), args.output)
        print(json.dumps({'status': result['preparation']['status'], 'readiness': result['preparation']['readiness'],
                          'materials': str(args.output.absolute() / 'materials.json')}, ensure_ascii=False))
        return 0 if result['preparation']['readiness'] == 'READY' else 1
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
        print(json.dumps({'status': 'PREPARATION_ERROR', 'message': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
