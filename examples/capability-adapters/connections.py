"""Optional scoped external catalogs. Reads declared sources; never runs plugins.

This is a preparation convention, not a new Plan field or runtime authority.
"""
import argparse
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import zipfile

REGISTRY = '.foundry/connections.json'
ON_DEMAND_REGISTRY = '.foundry/available-connections.json'
# Prefer the established descriptor when several ecosystems describe one root.
DESCRIPTORS = ('.codex-plugin/plugin.json', 'capability.json', '.cursor-plugin/plugin.json',
               '.claude-plugin/plugin.json', 'plugin.json')
FORMATS = ('codex-plugin', 'capability', 'cursor-plugin', 'claude-plugin', 'agent-plugin')


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', value):
        raise ValueError('expected a provider/connection identifier: ' + repr(value))
    return value


def relative(value):
    if not isinstance(value, str):
        raise ValueError('expected a relative material path')
    value = value.removeprefix('./').rstrip('/')
    path = PurePosixPath(value)
    if not value or path.is_absolute() or '..' in path.parts or path.as_posix() != value or '\\' in value or ':' in value:
        raise ValueError('expected a contained material path: ' + value)
    return value


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


@contextmanager
def source_files(source):
    """Read directory or ZIP members without extracting or importing package code."""
    root = Path(source).resolve(strict=True)
    if root.is_dir():
        def read(name):
            path = (root / relative(name)).resolve(strict=True)
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError('material escapes package: ' + name)
            return path.read_bytes()
        def skills(folder):
            path = (root / relative(folder)).resolve(strict=True)
            if not path.is_relative_to(root) or not path.is_dir():
                raise ValueError('skills directory escapes package')
            return sorted(p.relative_to(root).as_posix() for p in (root / folder).glob('*/SKILL.md'))
        yield read, skills
    else:
        with zipfile.ZipFile(root) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError('ambiguous duplicate ZIP members')
            # Keep existing Codex/capability ZIP precedence. A standalone
            # host descriptor and a root manifest may describe the same package.
            for group in ((DESCRIPTORS[0],), (DESCRIPTORS[1],), DESCRIPTORS[2:]):
                roots = set()
                for name in names:
                    for marker in group:
                        if name == marker or name.endswith('/' + marker):
                            roots.add(name[:-len(marker)])
                            break
                if roots:
                    break
            if len(roots) != 1:
                raise ValueError('select a package with one unambiguous descriptor')
            prefix = roots.pop()
            if prefix:
                relative(prefix)
            def read(name):
                info = archive.getinfo(prefix + relative(name))
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('ZIP material is a link: ' + name)
                return archive.read(info)
            def skills(folder):
                base = prefix + relative(folder) + '/'
                # ZIPs may omit directory entries; children also prove existence.
                # An explicit empty directory is valid and has no Skills yet.
                members = [n for n in names if n.startswith(base)]
                if not members:
                    raise ValueError('declared skills directory is missing from ZIP: ' + folder)
                return sorted(n[len(prefix):] for n in members
                              if n.endswith('/SKILL.md') and len(n[len(base):].split('/')) == 2)
            yield read, skills


def discover(source, base_materials=()):
    """Return public catalog and exact bytes read, not callable tool bindings."""
    captured = {}
    with source_files(source) as (reader, list_skills):
        def read(name):
            name = relative(name)
            raw = reader(name)
            captured[name] = raw
            return raw
        for descriptor in DESCRIPTORS:
            try:
                raw = read(descriptor)
                break
            except (FileNotFoundError, KeyError):
                continue
        else:
            raise ValueError('no supported capability or plugin descriptor')
        manifest = json.loads(raw)
        provider = identifier(manifest['name'])
        version = manifest['version']
        if not isinstance(version, str) or not version.strip():
            raise ValueError('package must declare a version')
        native = descriptor != 'capability.json'
        materials = list(base_materials) if native else [*manifest.get('materials', []), *base_materials]
        # Private checker inputs never become producer knowledge through this reader.
        private = {relative(v if isinstance(v, str) else v['path']) for v in manifest.get('verification_files', [])
                   if isinstance(v, str) or not v.get('shared')}
        materials = list(dict.fromkeys(relative(v) for v in materials))
        source_root = Path(source).resolve(strict=True)
        private_alias = source_root.is_dir() and any(
            (source_root / public).resolve() == (source_root / hidden).resolve()
            for public in materials for hidden in private)
        if private.intersection(materials) or private_alias:
            raise ValueError('private checker material cannot be a public base material')
        catalog_skills = []
        folders = manifest.get('skills', [])
        implicit_folder = descriptor in ('.claude-plugin/plugin.json', 'plugin.json') and 'skills' not in manifest
        if native and (folders or implicit_folder):
            folders = ['skills'] if implicit_folder else (folders if isinstance(folders, list) else [folders])
            paths = []
            for folder in folders:
                name = relative(folder)
                if name.endswith('/SKILL.md'):
                    paths.append(name)
                    continue
                try:
                    paths.extend(list_skills(name))
                except (FileNotFoundError, ValueError) as exc:
                    if not implicit_folder or not (isinstance(exc, FileNotFoundError) or 'missing from ZIP' in str(exc)):
                        raise
            for path in sorted(set(paths)):
                text = read(path).decode('utf-8')
                front = text.split('---', 2)[1] if text.startswith('---\n') and len(text.split('---', 2)) == 3 else ''
                fields = dict(re.findall(r'^(name|description):[ \t]*(.+)$', front, re.M))
                name = identifier(fields.get('name', PurePosixPath(path).parent.name).strip('"\''))
                if any(s['name'] == name for s in catalog_skills):
                    raise ValueError('duplicate Skill name: ' + name)
                catalog_skills.append({'name': name, 'description': fields.get('description', ''), 'path': path})
        for path in materials:
            if not read(path).decode('utf-8').strip():
                raise ValueError('empty base material: ' + path)
        catalog = {'provider': provider, 'version': version, 'format': FORMATS[DESCRIPTORS.index(descriptor)],
                   'descriptor': descriptor, 'description': manifest.get('description', ''),
                   'skills': catalog_skills, 'base_materials': materials,
                   'tool_bindings_prepared': False, 'native_lifecycle_executed': False}
        index_name = manifest.get('foundry_asset_index')
        if index_name:
            index = json.loads(read(relative(index_name)))
            if index.get('version') != 1 or not isinstance(index.get('entries'), list):
                raise ValueError('unsupported public asset index')
            entries, names = [], {row['name'] for row in catalog_skills}
            for item in index['entries']:
                name = identifier(item['name'])
                if name in names or item['kind'] not in ('skill', 'workflow', 'agent'):
                    raise ValueError('duplicate or invalid public entry: ' + name)
                names.add(name)
                path = relative(item['path'])
                deps = [relative(value) for value in item.get('requires', [])]
                for public in [path, *deps]:
                    if public in private or (source_root.is_dir() and any(
                            (source_root / public).resolve() == (source_root / hidden).resolve() for hidden in private)):
                        raise ValueError('private file in public asset index')
                    if public not in captured:
                        read(public)
                entries.append({'name': name, 'kind': item['kind'], 'description': item['description'],
                                'path': path, 'requires': deps})
            catalog['skills'].extend(entries)
    catalog['files'] = [{'path': path, 'sha256': digest(raw)} for path, raw in sorted(captured.items())]
    return catalog, captured


def read_registry(path):
    if not path.exists():
        return {'format': 1, 'records': []}
    data = json.loads(path.read_text())
    if data.get('format') != 1 or not isinstance(data.get('records'), list):
        raise ValueError('unsupported connection registry')
    return data


def registry_entries(root, scope, keys=None):
    registries = (REGISTRY,) if keys is None else (REGISTRY, ON_DEMAND_REGISTRY)
    found = {}
    for filename in registries:
        path = root / filename
        records = read_registry(path)['records']
        latest = {row['id']: row for row in records if row['scope'] == scope}
        for name, row in latest.items():
            key = scope + '.' + name
            if keys is not None and key not in keys:
                continue
            if key in found:
                raise ValueError('connection key occurs in both registries: ' + key)
            found[key] = (path, row)
    return found


def configure(root, scope, connection_id, source=None, base_materials=(), enabled=True, *, on_demand=False):
    """Append a local connection revision. Same binding is idempotent; history stays."""
    root = Path(root).resolve(strict=True)
    identifier(connection_id)
    if scope not in ('instance', 'project') or not root.is_dir():
        raise ValueError('connection requires an existing instance or project directory')
    path = root / (ON_DEMAND_REGISTRY if on_demand else REGISTRY)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix('.lock')
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        data = read_registry(path)
        previous = next((r for r in reversed(data['records']) if r['id'] == connection_id and r['scope'] == scope), None)
        if source is None:
            if previous is None:
                raise ValueError('cannot disconnect an unknown connection')
            row = deepcopy(previous)
        else:
            catalog, _ = discover(source, base_materials)
            row = {'id': connection_id, 'scope': scope, 'scope_root': str(root),
                   'source': str(Path(source).absolute()), 'resolved_source': str(Path(source).resolve(strict=True)), 'catalog': catalog,
                   'base_materials': list(base_materials)}
        row.update(scope=scope, scope_root=str(root), enabled=enabled)
        row.pop('revision', None)
        if previous and row == {k: v for k, v in previous.items() if k != 'revision'}:
            return previous
        row['revision'] = 1 + (previous['revision'] if previous else 0)
        data['records'].append(row)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(encoded(data))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
        return row
    finally:
        os.close(fd)
        lock.unlink()


def check_binding(binding):
    if 'selected_files' in binding:
        if str(Path(binding['source']).resolve(strict=True)) != binding['resolved_source']:
            return False
        with source_files(binding['source']) as (read, _):
            return all(digest(read(name)) == expected for name, expected in binding['selected_files'].items())
    catalog, _ = discover(binding['source'], binding.get('base_materials', []))
    return catalog == binding['catalog'] and str(Path(binding['source']).resolve(strict=True)) == binding['resolved_source']


def selection_files(binding, requested):
    catalog = binding['catalog']
    all_paths = {catalog['descriptor'], *catalog['base_materials']}
    material = dict.fromkeys(catalog['base_materials'], 'base')
    for item in catalog['skills']:
        if binding['key'] + ':' + item['name'] not in requested:
            continue
        all_paths.update([item['path'], *item.get('requires', [])])
        material[item['path']] = 'skill'
        for path in item.get('requires', []):
            if Path(path).suffix.lower() in ('.md', '.markdown', '.txt', '.json'):
                material.setdefault(path, 'reference')
    hashes = {r['path']: r['sha256'] for r in catalog['files'] if r['path'] in all_paths}
    if set(hashes) != all_paths:
        raise ValueError('selected file missing from registered catalog: ' + binding['key'])
    return hashes, material


def selected_capture(binding, hashes):
    """Check registered identity and materialize only the chosen public files."""
    if str(Path(binding['source']).resolve(strict=True)) != binding['resolved_source']:
        raise ValueError('selected connection moved: ' + binding['key'])
    with source_files(binding['source']) as (read, _):
        captured = {name: read(name) for name in sorted(hashes)}
    if any(digest(raw) != hashes[name] for name, raw in captured.items()):
        raise ValueError('connected materials changed; explicitly reconnect to bind the new version')
    return captured


def snapshot_context(instance, project, keys, skills):
    return {'selection_version': 1, 'stage': 'build', 'instance': str(Path(instance).resolve(strict=True)),
            'project': str(Path(project).resolve(strict=True)) if project else None,
            'connections': sorted(keys), 'skills': sorted(set(skills))}


def reuse_snapshot(snapshot, instance, project, records, skills):
    """Validate membership before any source access. Old or extra bytes are discarded."""
    if not isinstance(snapshot, dict) or snapshot.get('selection_context') != snapshot_context(instance, project, records, skills):
        return None
    if snapshot.get('status') != 'READY' or snapshot.get('diagnostics') != []:
        return None
    expected_bindings, expected_material = [], []
    for key, binding in records.items():
        hashes, kinds = selection_files(binding, set(skills))
        expected_bindings.append({**binding, 'selected_files': hashes})
        expected_material.extend((key, name, kind, hashes[name]) for name, kind in kinds.items())
    if snapshot.get('connections') != expected_bindings or not isinstance(snapshot.get('materials'), list):
        return None
    rows = snapshot['materials']
    if len(rows) != len(expected_material):
        return None
    for row, expected in zip(rows, expected_material):
        if (not isinstance(row, dict) or set(row) != {'connection', 'path', 'kind', 'sha256', 'text'} or
                tuple(row[k] for k in ('connection', 'path', 'kind', 'sha256')) != expected or
                not isinstance(row['text'], str) or digest(row['text'].encode()) != expected[3]):
            return None
    try:
        if not all(check_binding(binding) for binding in expected_bindings):
            return None
    except (ValueError, OSError, KeyError, zipfile.BadZipFile):
        return None
    return {'connections': expected_bindings, 'materials': rows, 'diagnostics': [], 'status': 'READY'}


def load_connections(instance_root, project_root=None, skills=(), *, keys=None):
    """Automatically load scoped catalogs/base materials; expand selected Skills only."""
    requested = set(skills)
    result = {'connections': [], 'materials': [], 'diagnostics': [], 'commands_executed': False,
              'model_load_verified': False, 'runtime_verified': False}
    providers, selected = {}, set()
    roots = [('instance', instance_root)] + ([('project', project_root)] if project_root else [])
    for scope, directory in roots:
        root = Path(directory).resolve(strict=True)
        try:
            for key, (path, row) in registry_entries(root, scope, keys).items():
                if row['scope'] != scope or row['scope_root'] != str(root):
                    raise ValueError('registry scope does not match its selected root')
                if not row['enabled']:
                    continue
                identifier(row['id'])
                conflict = False
                try:
                    binding = {**deepcopy(row), 'key': key, 'registry': str(path)}
                    if keys is None:
                        catalog, captured = discover(row['source'], row.get('base_materials', []))
                        if catalog != row['catalog'] or str(Path(row['source']).resolve(strict=True)) != row['resolved_source']:
                            raise ValueError('connected materials changed; explicitly reconnect to bind the new version')
                    else:
                        catalog = row['catalog']
                        hashes, kinds = selection_files(binding, requested)
                        captured = selected_capture(binding, hashes)
                        binding['selected_files'] = hashes
                    provider = catalog['provider']
                    if provider in providers:
                        conflict = True
                        raise ValueError('provider already connected by ' + providers[provider] + '; choose one binding')
                    providers[provider] = key
                    result['connections'].append(binding)
                    if keys is not None:
                        for name, kind in kinds.items():
                            result['materials'].append({'connection': key, 'path': name, 'kind': kind,
                                                        'sha256': hashes[name], 'text': captured[name].decode('utf-8')})
                        selected.update(key + ':' + item['name'] for item in catalog['skills']
                                        if key + ':' + item['name'] in requested)
                        continue
                    for name in catalog['base_materials']:
                        result['materials'].append({'connection': key, 'path': name, 'sha256': digest(captured[name]),
                                                    'text': captured[name].decode('utf-8'), 'kind': 'base'})
                    included = set(catalog['base_materials'])
                    for skill in catalog['skills']:
                        name = key + ':' + skill['name']
                        if name in requested:
                            selected.add(name)
                            raw = captured[skill['path']]
                            result['materials'].append({'connection': key, 'path': skill['path'], 'sha256': digest(raw),
                                                        'text': raw.decode('utf-8'), 'kind': 'skill'})
                            for path in skill.get('requires', []):
                                if path in included or Path(path).suffix.lower() not in ('.md', '.markdown', '.txt', '.json'):
                                    continue
                                included.add(path)
                                result['materials'].append({'connection': key, 'path': path, 'sha256': digest(captured[path]),
                                                            'text': captured[path].decode('utf-8'), 'kind': 'reference'})
                except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile) as exc:
                    required = keys is not None or conflict or bool(row['catalog']['base_materials']) or any(
                        name.startswith(key + ':') for name in requested)
                    result['diagnostics'].append({'id': key, 'severity': 'ERROR' if required else 'WARNING',
                                                  'code': 'CONNECTION_UNAVAILABLE', 'message': str(exc)})
        except (ValueError, OSError, KeyError, TypeError) as exc:
            result['diagnostics'].append({'id': scope, 'severity': 'ERROR', 'code': 'REGISTRY_UNAVAILABLE', 'message': str(exc)})
    if keys is not None:
        for key in sorted(set(keys) - {row['key'] for row in result['connections']}
                          - {row['id'] for row in result['diagnostics']}):
            result['diagnostics'].append({'id': key, 'severity': 'ERROR', 'code': 'CONNECTION_UNAVAILABLE',
                                          'message': 'selected connection missing or disabled'})
    for name in sorted(requested - selected):
        result['diagnostics'].append({'id': name, 'severity': 'ERROR', 'code': 'SKILL_UNAVAILABLE', 'message': 'requested Skill not loaded'})
    if keys is not None:
        result['selection_context'] = snapshot_context(instance_root, project_root, keys, requested)
    result['status'] = 'INCOMPLETE' if result['diagnostics'] else 'READY'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ('connect', 'disconnect'):
        command = sub.add_parser(action)
        command.add_argument('--root', required=True, type=Path)
        command.add_argument('--scope', required=True, choices=('instance', 'project'))
        command.add_argument('--id', required=True)
        command.add_argument('--on-demand', action='store_true', help='use the registry for explicit stage selections only')
        if action == 'connect':
            command.add_argument('--source', required=True, type=Path)
            command.add_argument('--base-material', action='append', default=[])
    command = sub.add_parser('load')
    command.add_argument('--instance-root', required=True, type=Path)
    command.add_argument('--project-root', type=Path)
    command.add_argument('--skill', action='append', default=[])
    args = parser.parse_args()
    try:
        if args.action == 'load':
            result = load_connections(args.instance_root, args.project_root, args.skill)
        else:
            result = configure(args.root, args.scope, args.id, getattr(args, 'source', None),
                               getattr(args, 'base_material', []), args.action == 'connect', on_demand=args.on_demand)
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result.get('status') == 'INCOMPLETE' else 0
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        print(json.dumps({'status': 'CONNECTION_ERROR', 'message': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
