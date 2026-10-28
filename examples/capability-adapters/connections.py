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
            descriptors = [n for n in names if n == '.codex-plugin/plugin.json' or n.endswith('/.codex-plugin/plugin.json')]
            if not descriptors:
                descriptors = [n for n in names if n == 'capability.json' or n.endswith('/capability.json')]
            if len(descriptors) != 1:
                raise ValueError('select a package with one unambiguous descriptor')
            marker = '.codex-plugin/plugin.json' if descriptors[0].endswith('.codex-plugin/plugin.json') else 'capability.json'
            prefix = descriptors[0][:-len(marker)]
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
        try:
            descriptor = '.codex-plugin/plugin.json'
            raw = read(descriptor)
        except (FileNotFoundError, KeyError):
            descriptor = 'capability.json'
            raw = read(descriptor)
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
        if native and manifest.get('skills'):
            for path in list_skills(relative(manifest['skills'])):
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
        catalog = {'provider': provider, 'version': version, 'format': 'codex-plugin' if native else 'capability',
                   'descriptor': descriptor, 'description': manifest.get('description', ''),
                   'skills': catalog_skills, 'base_materials': materials,
                   'tool_bindings_prepared': False, 'native_lifecycle_executed': False}
    catalog['files'] = [{'path': path, 'sha256': digest(raw)} for path, raw in sorted(captured.items())]
    return catalog, captured


def read_registry(path):
    if not path.exists():
        return {'format': 1, 'records': []}
    data = json.loads(path.read_text())
    if data.get('format') != 1 or not isinstance(data.get('records'), list):
        raise ValueError('unsupported connection registry')
    return data


def configure(root, scope, connection_id, source=None, base_materials=(), enabled=True):
    """Append a local connection revision. Same binding is idempotent; history stays."""
    root = Path(root).resolve(strict=True)
    identifier(connection_id)
    if scope not in ('instance', 'project') or not root.is_dir():
        raise ValueError('connection requires an existing instance or project directory')
    path = root / REGISTRY
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
    catalog, _ = discover(binding['source'], binding.get('base_materials', []))
    return catalog == binding['catalog'] and str(Path(binding['source']).resolve(strict=True)) == binding['resolved_source']


def load_connections(instance_root, project_root=None, skills=()):
    """Automatically load scoped catalogs/base materials; expand selected Skills only."""
    requested = set(skills)
    result = {'connections': [], 'materials': [], 'diagnostics': [], 'commands_executed': False,
              'model_load_verified': False, 'runtime_verified': False}
    providers, selected = {}, set()
    roots = [('instance', instance_root)] + ([('project', project_root)] if project_root else [])
    for scope, directory in roots:
        root = Path(directory).resolve(strict=True)
        path = root / REGISTRY
        try:
            records = read_registry(path)['records']
            latest = {row['id']: row for row in records if row['scope'] == scope}
            for row in latest.values():
                if row['scope'] != scope or row['scope_root'] != str(root):
                    raise ValueError('registry scope does not match its selected root')
                if not row['enabled']:
                    continue
                key = scope + '.' + identifier(row['id'])
                conflict = False
                try:
                    catalog, captured = discover(row['source'], row.get('base_materials', []))
                    if catalog != row['catalog'] or str(Path(row['source']).resolve(strict=True)) != row['resolved_source']:
                        raise ValueError('connected materials changed; explicitly reconnect to bind the new version')
                    provider = catalog['provider']
                    if provider in providers:
                        conflict = True
                        raise ValueError('provider already connected by ' + providers[provider] + '; choose one binding')
                    providers[provider] = key
                    binding = {**deepcopy(row), 'key': key, 'registry': str(path)}
                    result['connections'].append(binding)
                    for name in catalog['base_materials']:
                        result['materials'].append({'connection': key, 'path': name, 'sha256': digest(captured[name]),
                                                    'text': captured[name].decode('utf-8'), 'kind': 'base'})
                    for skill in catalog['skills']:
                        name = key + ':' + skill['name']
                        if name in requested:
                            selected.add(name)
                            raw = captured[skill['path']]
                            result['materials'].append({'connection': key, 'path': skill['path'], 'sha256': digest(raw),
                                                        'text': raw.decode('utf-8'), 'kind': 'skill'})
                except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile) as exc:
                    required = conflict or bool(row['catalog']['base_materials']) or any(
                        name.startswith(key + ':') for name in requested)
                    result['diagnostics'].append({'id': key, 'severity': 'ERROR' if required else 'WARNING',
                                                  'code': 'CONNECTION_UNAVAILABLE', 'message': str(exc)})
        except (ValueError, OSError, KeyError, TypeError) as exc:
            result['diagnostics'].append({'id': scope, 'severity': 'ERROR', 'code': 'REGISTRY_UNAVAILABLE', 'message': str(exc)})
    for name in sorted(requested - selected):
        result['diagnostics'].append({'id': name, 'severity': 'ERROR', 'code': 'SKILL_UNAVAILABLE', 'message': 'requested Skill not loaded'})
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
                               getattr(args, 'base_material', []), args.action == 'connect')
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result.get('status') == 'INCOMPLETE' else 0
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        print(json.dumps({'status': 'CONNECTION_ERROR', 'message': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
