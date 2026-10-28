#!/usr/bin/env python3
"""Prepare a selected external adapter; never build, install or dispatch it.

Original bytes and author declarations remain distinct. The output is an
independent candidate using the existing connections/native interfaces.
"""
from copy import deepcopy
from datetime import date, datetime, time
import argparse
import importlib.util
import json
import math
import os
import re
from pathlib import Path
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from harness_foundry_factory.python_startup import require_supported_python
require_supported_python(launcher=str(Path(__file__).absolute()))
import tomllib
from harness_foundry_factory.rsi_cases import read_json, require


def module(name):
    spec = importlib.util.spec_from_file_location('author_' + name, Path(__file__).with_name(name + '.py'))
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


N = module('native')
C = N.C


def pointer(document, location):
    require(isinstance(location, str) and (not location or location.startswith('/')), 'JSON pointer required')
    value = document
    for part in location.split('/')[1:] if location else []:
        part = part.replace('~1', '/').replace('~0', '~')
        if isinstance(value, list):
            require(re.fullmatch(r'0|[1-9][0-9]*', part) is not None, 'invalid JSON pointer array index')
            value = value[int(part)]
        else:
            value = value[part]
    return deepcopy(value)


def render(value, document, mapped):
    if isinstance(value, dict):
        if set(value) == {'$pointer'}:
            result = pointer(document, value['$pointer'])
            mapped.append(value['$pointer'])
            return result
        return {k: render(v, document, mapped) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, document, mapped) for v in value]
    return deepcopy(value)


def leaves(value, location=''):
    if isinstance(value, dict) and value:
        return [row for k, v in value.items() for row in leaves(v, location + '/' + k.replace('~', '~0').replace('/', '~1'))]
    if isinstance(value, list) and value:
        return [row for i, v in enumerate(value) for row in leaves(v, location + '/' + str(i))]
    return [{'pointer': location, 'value': value}]


def report_value(value, scalar_types, location=''):
    """Keep TOML-only scalar facts in JSON, with explicit types and raw source retained."""
    if isinstance(value, dict):
        return {k: report_value(v, scalar_types, location + '/' + k.replace('~', '~0').replace('/', '~1'))
                for k, v in value.items()}
    if isinstance(value, list):
        return [report_value(v, scalar_types, location + '/' + str(i)) for i, v in enumerate(value)]
    if isinstance(value, (datetime, date, time)):
        scalar_types.append({'pointer': location, 'type': type(value).__name__})
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        scalar_types.append({'pointer': location, 'type': 'float'})
        return str(value)
    return value


def link_directories(root, name, target):
    """Retain ordinary directories traversed before '..', without copying their contents."""
    cursor = root / Path(name).parent
    require(cursor.resolve(strict=True) == cursor, 'directory link needs an explicit derived layout')
    directories = set()
    for part in Path(target).parts[:-1]:
        cursor = cursor.parent if part == '..' else cursor / part
        require(cursor.is_relative_to(root), 'link traversal must remain inside its package')
        require(not cursor.is_symlink(), 'directory link needs an explicit derived layout')
        require(cursor.is_dir(), 'link traversal directory is missing')
        if cursor != root:
            directories.add('package/upstream/' + cursor.relative_to(root).as_posix())
    return directories


def links_match(output, links, inputs):
    """A matching link spelling alone does not establish a usable copied file."""
    if not links:
        return True
    expected = {row['path']: row['sha256'] for row in inputs}
    try:
        root = (output / 'package/upstream').resolve(strict=True)
        for name, target in links.items():
            relative = name.removeprefix('package/upstream/')
            path = N._file(root, relative)
            if not path.is_symlink() or os.readlink(path) != target or N.sha(path.read_bytes()) != expected[relative]:
                return False
    except (OSError, ValueError, RuntimeError):
        return False
    return True


def prepare(request, source_root):
    """Return candidate files/modes/links and a private mapping report, read-only."""
    root = Path(source_root).resolve(strict=True)
    require(root.is_dir(), 'explicit source directory required')
    descriptor = C.relative(request['descriptor'])
    raw = N._file(root, descriptor).read_bytes()
    kind = request['format']
    if kind == 'json':
        document = read_json(raw.decode('utf-8'))
    elif kind == 'toml':
        document = tomllib.loads(raw.decode('utf-8'))
    elif kind == 'text':
        document = {'text': raw.decode('utf-8')}
    else:
        raise ValueError('select json, toml, or text with explicit author mapping')
    mapped = []
    declared = render(request['mapping'], document, mapped)
    provider = C.identifier(declared['provider'])
    version = declared['version']
    require(isinstance(version, str) and version.strip(), 'explicit package version required')
    adapter_version = request['adapter_version']
    require(isinstance(adapter_version, str) and adapter_version.strip(), 'adapter version required')
    inventory = N._inventory(root, request['runtime_files'])
    names = {r['path'] for r in inventory}
    files, modes, links = {}, {}, {}
    directories = set()
    for row in inventory:
        name = row['path']; path = N._file(root, name); destination = 'package/upstream/' + name
        if path.is_symlink():
            target = os.readlink(path)
            require(not Path(target).is_absolute(), 'absolute link needs an explicit derived layout')
            directories.update(link_directories(root, name, target))
            # Check the copied link's immediate spelling, not only its final referent.
            target_name = Path(os.path.normpath(str(Path(name).parent / target))).as_posix()
            require(target_name in names, 'select the link target as a runtime input')
            links[destination] = target
        else:
            files[destination] = path.read_bytes()
            modes[destination] = stat.S_IMODE(path.stat().st_mode) & 0o777
    public = [C.relative(n) for n in request.get('materials', [])]
    require(set(public) <= names, 'public material must be a selected input')
    for name in public:
        require(N._file(root, name).read_text().strip(), 'public material must contain text')
    operations, unresolved = {}, []
    for name, entry in declared.get('operations', {}).items():
        C.identifier(name)
        try:
            require(isinstance(entry, dict), 'operation must be an object')
            for key in ('argv', 'tools', 'effects', 'requirements'):
                require(isinstance(entry.get(key), list) and all(isinstance(v, str) for v in entry[key]), 'declare argv/tools/effects/requirements')
            argv = entry['argv']; tools = entry['tools']
            require(argv and argv[0].startswith('tool:') and argv[0][5:] in tools, 'first argv must name a declared tool')
            require(len(tools) == len(set(tools)), 'duplicate tool role')
            for role in tools: C.identifier(role)
            converted = []
            for arg in argv:
                require('\x00' not in arg, 'invalid argument')
                if arg.startswith('tool:'):
                    require(arg[5:] in tools, 'undeclared tool role'); converted.append(arg)
                elif arg.startswith('package:'):
                    source = C.relative(arg[8:]); require(source in names, 'entry not in selected runtime files')
                    converted.append('package:upstream/' + source)
                else:
                    converted.append(arg)
            operations[name] = {**deepcopy(entry), 'argv': converted}
        except (ValueError, KeyError, TypeError) as error:
            unresolved.append({'operation': name, 'reason': str(error), 'declared': deepcopy(entry)})
    catalog = {'name': provider, 'version': version, 'description': declared.get('description', ''),
               'materials': ['upstream/' + n for n in public], 'verification_files': []}
    adapter = {'format': 1, 'provider': provider, 'version': adapter_version, 'package_versions': [version],
               'runtime_files': ['capability.json', *['upstream/' + r['path'] for r in inventory]], 'operations': operations}
    files['package/capability.json'] = C.encoded(catalog)
    files['adapter.json'] = C.encoded(adapter)
    bindings = {'descriptor': {'path': descriptor, 'sha256': N.sha(raw)}, 'inputs': inventory,
                'source_root': str(root), 'request': deepcopy(request),
                'generator': {n: N.sha(Path(p).read_bytes()) for n, p in
                              [('author', __file__), ('native', N.__file__), ('connections', C.__file__)]}}
    report = {'status': 'CANDIDATE', 'format': kind, 'original_document': document,
              'mapped_pointers': sorted(set(mapped)),
              'unmapped': [r for r in leaves(document) if not any(r['pointer'] == p or r['pointer'].startswith(p + '/') or p == '' for p in mapped)],
              'author_mapping': deepcopy(request['mapping']), 'declared_license': declared.get('license', 'UNKNOWN'),
              'unresolved_operations': unresolved, 'available_operations': list(operations),
              'build': deepcopy(request.get('build', {})), 'changes': deepcopy(request.get('changes', [])),
              'binding': bindings, 'runtime_modes': modes, 'runtime_links': links,
              'runtime_directories': sorted(directories),
              'commands_executed': False, 'acceptance_granted': False, 'budget_modified': False,
              'limitations': ['Mapping declarations are not semantic verification or execution authority.',
                             'Text mode preserves YAML/README; it does not parse their semantics.',
                             'Report and original descriptor may be private; deliver only reviewed runtime inputs.',
                             'Build/rewrite behavior, host dependencies and target delivery need independent verification.']}
    files['source-descriptor.bin'] = raw
    if kind == 'toml':
        scalar_types = []
        report = report_value(report, scalar_types)
        if scalar_types: report['report_scalar_types'] = scalar_types
    files['mapping-report.json'] = C.encoded(report)
    # Freeze the selected source facts; do not silently combine different reads.
    require(N._file(root, descriptor).read_bytes() == raw and N._inventory(root, request['runtime_files']) == inventory,
            'selected source changed during conversion')
    return files, modes, links, report


def write_candidate(request, source_root, output):
    output = Path(output).absolute()
    root = Path(source_root).resolve(strict=True)
    require(not output.resolve().is_relative_to(root) and not root.is_relative_to(output.resolve()), 'candidate must be separate from original input')
    files, modes, links, report = prepare(request, root)
    expected = set(files) | set(links)
    directories = report['runtime_directories']
    if output.exists():
        actual = {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file() or p.is_symlink()}
        same = actual == expected
        for n, raw in files.items():
            p = output / n
            same = same and p.is_file() and not p.is_symlink() and p.read_bytes() == raw
            if n in modes: same = same and stat.S_IMODE(p.stat().st_mode) == modes[n]
        same = same and all((output / n).is_dir() and not (output / n).is_symlink() for n in directories)
        same = same and links_match(output, links, report['binding']['inputs'])
        require(same, 'existing candidate differs or is incomplete; preserve it and choose a new output')
        return {'status': 'CANDIDATE', 'reused': True, 'output': str(output),
                'unresolved_operations': report['unresolved_operations'], 'commands_executed': False}
    output.mkdir(parents=False)
    for name in directories:
        (output / name).mkdir(parents=True, exist_ok=True)
    for name, raw in files.items():
        path = output / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        if name in modes: path.chmod(modes[name])
    for name, target in links.items():
        path = output / name; path.parent.mkdir(parents=True, exist_ok=True); path.symlink_to(target)
    require(links_match(output, links, report['binding']['inputs']),
            'candidate links differ or are incomplete; preserve it and choose a new output')
    return {'status': 'CANDIDATE', 'reused': False, 'output': str(output),
            'unresolved_operations': report['unresolved_operations'], 'commands_executed': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--request', required=True, type=Path)
    p.add_argument('--source-root', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    try:
        result = write_candidate(read_json(a.request.read_text()), a.source_root, a.output)
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        print(json.dumps({'status': 'NOT_PREPARED', 'message': 'Check declared mapping, inputs and a separate output.', 'commands_executed': False}))
        return 1
    print(json.dumps(result, ensure_ascii=False)); return 0


if __name__ == '__main__': raise SystemExit(main())
