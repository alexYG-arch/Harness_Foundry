"""Native provider handoffs. Preparation never executes, authorizes or retries.

The existing host owns dispatch, credentials, sandbox, budget and observation.
Only the selected provider is inspected; upstream files are never rewritten.
"""

import argparse
from copy import deepcopy
from fnmatch import fnmatchcase
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import stat


def _module(name):
    spec = importlib.util.spec_from_file_location('native_' + name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


C = _module('connections')
E = _module('environment')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _file(root, relative):
    path = root / C.relative(relative)
    real = path.resolve(strict=True)
    if not real.is_relative_to(root) or not real.is_file():
        raise ValueError('native dependency must remain inside its package: ' + relative)
    return path


def adapter_for(provider):
    path = Path(__file__).with_name('providers') / C.identifier(provider) / 'adapter.json'
    return path if path.is_file() else None


def _inventory(root, patterns):
    files = {}
    for pattern in patterns:
        C.relative(pattern)
        matches = [p for p in root.glob(pattern) if p.is_file()]
        if not matches:
            raise ValueError('native dependency pattern has no files: ' + pattern)
        for p in matches:
            rel = p.relative_to(root).as_posix()
            p = _file(root, rel)
            files[rel] = {'path': rel, 'resolved_path': str(p.resolve()), 'sha256': sha(p.read_bytes())}
    return [files[n] for n in sorted(files)]


def _matches_parts(parts, pattern):
    """Match archive paths with directory glob depth, including zero-depth **."""
    if not pattern:
        return not parts
    if pattern[0] == '**':
        return _matches_parts(parts, pattern[1:]) or bool(parts) and _matches_parts(parts[1:], pattern)
    return bool(parts) and fnmatchcase(parts[0], pattern[0]) and _matches_parts(parts[1:], pattern[1:])


def _source_paths(connection, patterns):
    """Inventory only declared runtime inputs in the original directory or ZIP."""
    source = Path(connection['source']).resolve(strict=True)
    if source.is_dir():
        return {p.relative_to(source).as_posix() for pattern in patterns
                for p in source.glob(C.relative(pattern)) if p.is_file()}
    with C.zipfile.ZipFile(source) as archive:
        marker = connection['catalog']['descriptor']
        roots = [n[:-len(marker)] for n in archive.namelist() if n == marker or n.endswith('/' + marker)]
        if len(roots) != 1:
            raise ValueError('native source must have one package root')
        prefix = roots[0]
        patterns = [C.relative(p).split('/') for p in patterns]
        return {C.relative(info.filename[len(prefix):]) for info in archive.infolist()
                if not info.is_dir() and info.filename.startswith(prefix)
                and any(_matches_parts(info.filename[len(prefix):].split('/'), pattern) for pattern in patterns)}


def bind_native(connection, config, *, project_root, delivery_identity=None):
    """Bind an installed layout against the connected source, without installing.

    Explicit adapter_path supports other providers; it is not a core registry.
    Original package files and adapter files have separate version identities.
    """
    if delivery_identity is None and not C.check_binding(connection):
        raise ValueError('connected source changed; select the new version explicitly')
    adapter_path = Path(config.get('adapter_path') or adapter_for(connection['catalog']['provider']) or '')
    adapter_path = adapter_path.resolve(strict=True)
    raw = adapter_path.read_bytes()
    adapter = json.loads(raw)
    if adapter['provider'] != connection['catalog']['provider']:
        raise ValueError('adapter provider differs from connection')
    if connection['catalog']['version'] not in adapter['package_versions']:
        raise ValueError('adapter does not declare this package version')
    root = Path(config['root']).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('native execution requires an installed directory, not a ZIP')
    if delivery_identity is None:
        catalog, _ = C.discover(root, connection.get('base_materials', []))
        if catalog != connection['catalog']:
            raise ValueError('native layout differs from connected materials')
        patterns = adapter['runtime_files']
        files = _inventory(root, patterns)
        expected = _source_paths(connection, patterns)
        actual = {row['path'] for row in files}
        if expected != actual:
            raise ValueError('native layout differs from connected source: missing='
                             + repr(sorted(expected - actual)) + ', extra=' + repr(sorted(actual - expected)))
        # The installation may have a different location, but not different inputs.
        with C.source_files(connection['source']) as (read, _):
            for row in files:
                if sha(read(row['path'])) != row['sha256']:
                    raise ValueError('native layout differs from connected source: ' + row['path'])
    else:
        if delivery_identity['adapter_sha256'] != sha(raw):
            raise ValueError('delivered adapter identity mismatch')
        if delivery_identity['origin_catalog'] != connection['catalog']:
            raise ValueError('delivered source identity mismatch')
        files = deepcopy(delivery_identity['files'])
        _check_delivered_files(root, delivery_identity)
    selected = config.get('operations', list(adapter['operations']))
    if not selected or len(selected) != len(set(selected)) or any(n not in adapter['operations'] for n in selected):
        raise ValueError('select unique declared native operations')
    roles = sorted({role for op in selected for role in adapter['operations'][op].get('tools', [])})
    environment = E.resolve_environment([{'id': r, 'kind': 'executable'} for r in roles],
                                        config.get('environment_bindings', {}), project_root=project_root)
    invocation_files = {}
    for role, path in environment['scope_fragment']['executables'].items():
        invocation_files[role] = {'path': path, 'resolved_path': str(Path(path).resolve()),
                                  'sha256': sha(Path(path).read_bytes())}
    result = {'connection': deepcopy(connection), 'root': str(root), 'files': files,
            'adapter_path': str(adapter_path), 'adapter_sha256': sha(raw), 'adapter': adapter,
            'operations': selected, 'environment': environment, 'invocation_files': invocation_files,
            'commands_executed': False, 'acceptance_granted': False}
    if delivery_identity is not None:
        if not set(selected) <= set(delivery_identity['operations']):
            raise ValueError('operation was not selected for delivery')
        result['delivery_identity'] = deepcopy(delivery_identity)
    return result


def _check_delivered_files(root, identity):
    # The host fixed these expectations from the source before delivery.
    # Do not discover expected files from the receiving directory.
    for row in identity['files']:
        path = root / C.relative(row['path'])
        if not path.resolve(strict=True).is_relative_to(root) or sha(path.read_bytes()) != row['sha256']:
            raise ValueError('selected delivered dependency changed: ' + row['path'])
    for name, expected in identity.get('layout', {}).items():
        path = root / C.relative(name)
        metadata = path.lstat()
        if expected['kind'] == 'link':
            valid = stat.S_ISLNK(metadata.st_mode) and os.readlink(path) == expected['target']
        else:
            valid = ((stat.S_ISREG(metadata.st_mode) if expected['kind'] == 'file' else stat.S_ISDIR(metadata.st_mode))
                     and stat.S_IMODE(metadata.st_mode) & 0o777 == expected['mode'])
        if not valid:
            raise ValueError('selected delivered layout changed: ' + name)
    descriptor = identity['origin_catalog']['descriptor']
    manifest = json.loads((root / descriptor).read_bytes())
    if (manifest['name'], manifest['version']) != (identity['origin_catalog']['provider'], identity['origin_catalog']['version']):
        raise ValueError('delivered provider/version mismatch')


def check_native(binding):
    """New calls check live inputs; historical report retrieval does not."""
    if 'delivery_identity' not in binding and not C.check_binding(binding['connection']):
        raise ValueError('native connection changed')
    path = Path(binding['adapter_path'])
    if sha(path.read_bytes()) != binding['adapter_sha256'] or json.loads(path.read_bytes()) != binding['adapter']:
        raise ValueError('native adapter changed')
    if 'delivery_identity' in binding:
        _check_delivered_files(Path(binding['root']), binding['delivery_identity'])
        if binding['files'] != binding['delivery_identity']['files'] or not set(binding['operations']) <= set(binding['delivery_identity']['operations']):
            raise ValueError('delivered invocation scope changed')
    else:
        files = _inventory(Path(binding['root']), binding['adapter']['runtime_files'])
        if files != binding['files']:
            raise ValueError('native package changed; prepare new materials after updating')
    for role, item in binding['invocation_files'].items():
        path = Path(item['path'])
        if (str(path.resolve(strict=True)) != item['resolved_path'] or sha(path.read_bytes()) != item['sha256']
                or not os.access(path, os.X_OK)):
            raise ValueError('native executable changed: ' + role)
    return True


def prepare_call(binding, operation, args=(), *, cwd):
    check_native(binding)
    if binding['environment']['status'] != 'READY':
        raise ValueError('native environment is incomplete')
    if operation not in binding['operations']:
        raise ValueError('native operation is not selected: ' + operation)
    if not isinstance(args, (list, tuple)) or any(not isinstance(x, str) or '\x00' in x for x in args):
        raise ValueError('native arguments must be strings')
    cwd = Path(cwd).resolve(strict=True)
    if not cwd.is_dir():
        raise ValueError('native cwd must exist')
    entry = binding['adapter']['operations'][operation]
    tools = binding['environment']['scope_fragment']['executables']
    argv = []
    for value in entry['argv']:
        if value.startswith('tool:'):
            argv.append(tools[value[5:]])
        elif value.startswith('package:'):
            rel = C.relative(value[8:])
            if rel not in {r['path'] for r in binding['files']}:
                raise ValueError('native entry is not in bound dependencies')
            argv.append(str(_file(Path(binding['root']), rel)))
        else:
            argv.append(value)
    return {'tool_id': binding['connection']['key'] + '.' + operation,
            'provider': binding['adapter']['provider'], 'version': binding['connection']['catalog']['version'],
            'adapter_version': binding['adapter']['version'],
            'local_argv': [binding['connection']['key'] + '.' + entry['argv'][0][5:], *argv[1:], *args]
                          if entry['argv'][0].startswith('tool:') else None,
            'native_identity': {'adapter_sha256': binding['adapter_sha256'],
                                'files_sha256': sha(C.encoded(binding['files']))}, 'argv': [*argv, *args], 'cwd': str(cwd),
            'effects': deepcopy(entry['effects']), 'requirements': deepcopy(entry.get('requirements', [])),
            'scope_fragment': {'source_read_roots': [binding['root'], *tools.values()],
                               'executables': {binding['connection']['key'] + '.' + r: p for r, p in tools.items()}},
            'commands_executed': False, 'acceptance_granted': False}


def attach_call(observation, call):
    """Trusted host hook before its existing command dispatch, never authority.

    Keep secrets in the host's existing stdin/credential channels, not args.
    Persist only call identity; original outputs stay in CommandObservation.
    """
    if (observation.root / 'started.json').exists():
        raise ValueError('attach native call before dispatch')
    public = {k: deepcopy(v) for k, v in call.items() if k not in ('argv', 'local_argv', 'scope_fragment')}
    public['argv_sha256'] = sha(C.encoded(call['argv']))
    public['argument_count'] = len(call['argv'])
    receipt = {'binding': observation.binding, 'call': public}
    path = observation.root / 'native-call.json'
    if path.exists():
        if json.loads(path.read_text()) != receipt:
            raise ValueError('native call is already bound')
    else:
        observation._save('native-call.json', receipt)
    return receipt


def recover_call(root, command_id, executor):
    """Reuse the controller's complete capture; never probe/update/replay a tool."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
    from harness_foundry_factory.process_observation import CommandObservation
    root = Path(root)
    receipt = json.loads((root / 'native-call.json').read_text())
    if receipt['binding'] != {'command_id': command_id, 'executor': executor}:
        raise ValueError('native call belongs to another command')
    result = CommandObservation.recover(root, command_id, executor)
    return {'call': receipt['call'], 'result': result,
            'status': 'CAPTURED' if result is not None else 'UNRESOLVED',
            'replay_allowed': False, 'commands_executed': False, 'acceptance_granted': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binding', type=Path)
    p.add_argument('--operation')
    p.add_argument('--cwd', type=Path)
    p.add_argument('--recover', type=Path)
    p.add_argument('--command-id')
    p.add_argument('--executor', choices=['LOCAL', 'CODEX'])
    p.add_argument('args', nargs=argparse.REMAINDER)
    a = p.parse_args()
    try:
        if a.recover:
            result = recover_call(a.recover, a.command_id, a.executor)
        else:
            result = prepare_call(json.loads(a.binding.read_text()), a.operation,
                                  a.args[1:] if a.args[:1] == ['--'] else a.args, cwd=a.cwd)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(json.dumps({'status': 'NOT_PREPARED', 'message': str(e), 'commands_executed': False}))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
