"""Selected external runtime delivery; no installer, dispatch or authority.

New targets rebind local tools. Original packages and adapters remain separate;
private host materials, credentials, observations and virtualenvs are not copied.
"""
import argparse
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys


def module(name):
    spec = importlib.util.spec_from_file_location('delivery_' + name, Path(__file__).with_name(name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


N = module('native')
C = N.C
HELPERS = ('delivery.py', 'native.py', 'connections.py', 'environment.py', 'prepare.py',
           'consume.py', 'upgrade.py', 'stack_handoff.py', 'stack_runtime.py', 'native_dependencies.py', 'inventory.py', 'decisions.py', 'feature_connections.py')


def layout(root, names):
    """Capture selected files and only their required layout, including link targets.

    Relative in-package directory/file links and modes are preserved. Absolute
    links need an explicit derived layout, not silent rewriting on relocation.
    """
    root = Path(root).resolve(strict=True)
    rows, payloads, active = {}, {}, set()

    def visit(name):
        if not name or name == '.':
            return Path('.')
        path = Path(name)
        parent = visit(path.parent.as_posix())
        rel = (parent / path.name).as_posix()
        source = root / rel
        if rel in active:
            raise ValueError('cyclic runtime link: ' + rel)
        info = source.lstat()
        if stat.S_ISLNK(info.st_mode):
            target = os.readlink(source)
            if not source.resolve(strict=True).is_relative_to(root):
                raise ValueError('runtime link escapes package: ' + rel)
            if os.path.isabs(target):
                raise ValueError('absolute runtime link requires an explicit derived layout: ' + rel)
            active.add(rel)
            destination = parent
            for part in Path(target).parts:
                if part == '..':
                    if destination == Path('.'):
                        raise ValueError('runtime link escapes package: ' + rel)
                    destination = destination.parent
                elif part != '.':
                    destination = visit((destination / part).as_posix())
            active.remove(rel)
            rows[rel] = {'kind': 'link', 'target': target}
            return destination
        mode = stat.S_IMODE(info.st_mode) & 0o777
        if stat.S_ISDIR(info.st_mode):
            rows[rel] = {'kind': 'directory', 'mode': mode}
        elif stat.S_ISREG(info.st_mode):
            raw = source.read_bytes()
            rows[rel] = {'kind': 'file', 'sha256': N.sha(raw), 'mode': mode}
            payloads[rel] = raw
        else:
            raise ValueError('unsupported runtime node: ' + rel)
        return Path(rel)

    for name in sorted(set(names)):
        visit(C.relative(name))
    return dict(sorted(rows.items())), payloads


def write_layout(root, rows, payloads):
    root.mkdir(parents=True, exist_ok=False)
    # Parents first; directory modes last so read-only source layouts are legal.
    for name, row in sorted(rows.items(), key=lambda item: (item[0].count('/'), item[0])):
        path = root / name
        if row['kind'] == 'directory':
            path.mkdir()
        elif row['kind'] == 'file':
            path.write_bytes(payloads[name]); path.chmod(row['mode'])
        else:
            path.symlink_to(row['target'])
    for name, row in sorted(rows.items(), key=lambda item: item[0].count('/'), reverse=True):
        if row['kind'] == 'directory':
            (root / name).chmod(row['mode'])


def check_layout(root, expected):
    actual, _ = layout(root, expected)
    if actual != expected:
        raise ValueError('delivered runtime layout or content changed; bind an explicit new selection')


def write(root, name, raw):
    path = root / C.relative(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)


def prepare_delivery(materials, output, *, rsi_manifest=None, rsi_material_root=None):
    """Host-only selection to new public support. Retain partial output on I/O failure."""
    P = module('prepare')
    if P.check_selection(materials)['status'] != 'MATCH':
        raise ValueError('selected materials changed')
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    host = Path(__file__).resolve().parents[2]
    staged, entries = {}, []
    bindings = materials.get('native_bindings', {})
    for key, binding in sorted(bindings.items()):
        P._id(key)
        N.check_native(binding)
        root = Path(binding['root'])
        if output.resolve().is_relative_to(root) or root.is_relative_to(output.resolve()):
            raise ValueError('delivery must be separate from upstream runtime')
        feature_scope = materials['preparation'].get('external_features', {}).get(key)
        if feature_scope is not None and not any(f['final_form'] in ('AS_IS', 'BRIDGED') and f.get('operations') for f in feature_scope['features']):
            continue
        names = (set(feature_scope['delivery_files']) - {'capability.json'} if feature_scope else
                 {r['path'] for r in binding['files']} | {r['path'] for r in binding['connection']['catalog']['files']})
        names.add(binding['connection']['catalog']['descriptor'])
        names.update(n for n in ('LICENSE', 'LICENSE.md', 'COPYING') if (root / n).is_file())
        if feature_scope is None:
            names.update(p.relative_to(root).as_posix() for pattern in binding['adapter']['runtime_files']
                         for p in root.glob(pattern) if p.is_dir())
        descriptor = json.loads((root / binding['connection']['catalog']['descriptor']).read_text())
        if binding['connection']['catalog']['format'] == 'codex-plugin' and descriptor.get('skills'):
            names.add(C.relative(descriptor['skills']))
        private = [r if isinstance(r, str) else r['path'] for r in descriptor.get('verification_files', [])
                   if isinstance(r, str) or not r.get('shared')]
        private_real = {(root / n).resolve() for n in private}
        if any((root / n).resolve() in private_real for n in names):
            raise ValueError('private checker dependency cannot be delivered as public runtime')
        rows, payloads = layout(root, names)
        prefix = 'external/' + key
        staged[key] = (rows, payloads)
        adapter_raw = Path(binding['adapter_path']).read_bytes()
        entries.append({'key': key, 'mode': 'NATIVE', 'provider': binding['adapter']['provider'],
                        'version': binding['connection']['catalog']['version'],
                        'adapter_version': binding['adapter']['version'],
                        'root': prefix + '/upstream', 'adapter': prefix + '/adapter.json',
                        'adapter_sha256': N.sha(adapter_raw), 'catalog': binding['connection']['catalog'],
                        'base_materials': binding['connection'].get('base_materials', []),
                        'operations': binding['operations'], 'layout': rows,
                        'origin': {'kind': 'zip' if Path(binding['connection']['source']).is_file() else 'directory',
                                   'catalog_sha256': N.sha(C.encoded(binding['connection']['catalog']))},
                        'tools': sorted({r for op in binding['operations'] for r in binding['adapter']['operations'][op].get('tools', [])})})
        if feature_scope is not None:
            origin = binding['connection']['catalog']
            selected_skills = {skill for feature in feature_scope['features'] if feature['final_form'] in ('AS_IS', 'BRIDGED') for skill in feature.get('skills', [])}
            delivered_catalog = {**deepcopy(origin), 'skills': [r for r in origin['skills'] if r['name'] in selected_skills],
                                 'files': [{'path': n, 'sha256': N.sha(raw)} for n, raw in sorted(payloads.items())]}
            selected_ops = sorted({op for f in feature_scope['features'] if f['final_form'] in ('AS_IS', 'BRIDGED') for op in f.get('operations', [])})
            entries[-1]['operations'] = selected_ops
            entries[-1]['feature_scope'] = deepcopy(feature_scope)
            entries[-1]['delivery_identity'] = {'format_version': 2, 'origin_catalog': deepcopy(origin),
                'catalog': delivered_catalog, 'files': delivered_catalog['files'], 'operations': selected_ops,
                'layout': deepcopy(rows), 'mapping_sha256': feature_scope['mapping_sha256'], 'adapter_sha256': N.sha(adapter_raw)}
    public_only = []
    for connection in materials['preparation'].get('external_connections', []):
        if connection['key'] in staged:
            continue
        # Skill/reference-only connections are useful without a runnable binding.
        # Publish their captured public material, not guessed runtime dependencies.
        catalog, captured = C.discover(connection['source'], connection.get('base_materials', []))
        if catalog != connection['catalog']:
            raise ValueError('connected public materials changed')
        key = P._id(connection['key'])
        descriptor = json.loads(captured[catalog['descriptor']])
        directories = ([C.relative(descriptor['skills'])]
                       if catalog['format'] == 'codex-plugin' and descriptor.get('skills') else [])
        # Keep public redistribution notices without importing other host files.
        with C.source_files(connection['source']) as (read, _):
            for name in ('LICENSE', 'LICENSE.md', 'COPYING'):
                try:
                    captured.setdefault(name, read(name))
                except (FileNotFoundError, KeyError):
                    pass
        feature_scope = materials['preparation'].get('external_features', {}).get(key)
        if feature_scope is not None:
            names = set(feature_scope['delivery_files']) - {'capability.json'}
            if not names: continue
            names.add(catalog['descriptor'])
            with C.source_files(connection['source']) as (read, _):
                captured = {n: read(n) for n in sorted(names)}
                for name in ('LICENSE', 'LICENSE.md', 'COPYING'):
                    try: captured.setdefault(name, read(name))
                    except (FileNotFoundError, KeyError): pass
        public_only.append(({'key': key, 'mode': 'CATALOG_ONLY', 'provider': catalog['provider'],
                            'version': catalog['version'], 'catalog': catalog,
                            'root': 'external/' + key + '/upstream',
                            'operations': [], 'runtime_binding_required': True, 'material_directories': directories,
                            'material_files': {n: N.sha(raw) for n, raw in sorted(captured.items())}}, captured))
        if feature_scope is not None:
            selected_skills = {skill for f in feature_scope['features'] if f['final_form'] in ('AS_IS', 'BRIDGED') for skill in f.get('skills', [])}
            public_only[-1][0].update(feature_scope=deepcopy(feature_scope),
                delivery_catalog={**deepcopy(catalog), 'skills': [r for r in catalog['skills'] if r['name'] in selected_skills],
                                  'files': [{'path': n, 'sha256': N.sha(raw)} for n, raw in sorted(captured.items())]})
    output.mkdir(parents=True, exist_ok=False)
    for entry, captured in public_only:
        for name in entry['material_directories']:
            (output / entry['root'] / name).mkdir(parents=True, exist_ok=True)
        for name, raw in captured.items():
            write(output, entry['root'] + '/' + name, raw)
        entries.append(entry)
    for entry in entries:
        if entry['mode'] == 'CATALOG_ONLY':
            continue
        binding = bindings[entry['key']]
        rows, payloads = staged[entry['key']]
        write_layout(output / entry['root'], rows, payloads)
        write(output, entry['adapter'], Path(binding['adapter_path']).read_bytes())
        # Provider-owned lifecycle glue stays with that provider, not the core.
        lifecycle = Path(__file__).with_name('providers') / entry['provider'] / 'lifecycle.py'
        if lifecycle.is_file():
            name = 'external/' + entry['key'] + '/lifecycle.py'
            write(output, name, lifecycle.read_bytes())
            entry['lifecycle'] = name
            entry['lifecycle_sha256'] = N.sha(lifecycle.read_bytes())
        check_layout(output / entry['root'], rows)
        N.check_native(binding)
        if layout(Path(binding['root']), rows)[0] != rows:
            raise ValueError('runtime layout changed during delivery')
    for name in HELPERS:
        write(output, 'examples/capability-adapters/' + name, Path(__file__).with_name(name).read_bytes())
    for name in ('EXTERNAL_DELIVERY.md', 'NATIVE.md', 'STACK_ENVIRONMENT.md', 'FEATURES.md'):
        write(output, 'examples/capability-adapters/' + name, Path(__file__).with_name(name).read_bytes())
    for name in ('merge.py', 'apply.py', 'file_states.py'):
        rel = 'examples/harness-composition-upgrade/helpers/' + name
        write(output, rel, (host / rel).read_bytes())
    write(output, 'src/harness_foundry_factory/__init__.py', b'')
    for name in ('process_observation', 'local_process', 'resource_network', 'coding_process', 'coding_events'):
        rel = 'src/harness_foundry_factory/' + name + '.py'
        write(output, rel, (host / rel).read_bytes())
    write(output, 'LICENSE', (host / 'LICENSE').read_bytes())
    builtin = module('stack_handoff').public_delivery(materials, output / 'builtin')
    if rsi_manifest is not None:
        sys.path.insert(0, str(host / 'src'))
        from harness_foundry_factory.rsi_delivery import prepare_delivery as deliver_rsi
        deliver_rsi(host, rsi_manifest, rsi_material_root, output / 'rsi')
        for name in ('rsi_handoff.py', 'RSI_HANDOFF.md'):
            write(output, 'rsi/examples/capability-adapters/' + name, Path(__file__).with_name(name).read_bytes())
    instruction = ('# Selected external support\n\nRead examples/capability-adapters/EXTERNAL_DELIVERY.md. '
                   'Load the selected provider Skills from the upstream paths in delivery.json. '
                   'Bind this task\'s local tools before preparing calls; the host owns authorization and execution. '
                   'Preserve provider-managed configuration and disabled selections; delivery does not initialize projects.\n')
    if rsi_manifest is not None:
        instruction += ('\nRead rsi/examples/capability-adapters/RSI_HANDOFF.md and rsi/docs/RSI_DELIVERY.md. '
                        'At existing repair return points use the selected handoff without a new RSI reminder. '
                        'Keep original failures, verification and budget references; knowledge is advice, not acceptance.\n')
    inventories = [r['feature_scope'] for r in materials['preparation']['selections'] if 'feature_scope' in r]
    inventories += list(materials['preparation'].get('external_features', {}).values())
    snippets = {name: 'builtin/' + path for name, path in builtin.get('instruction_snippets', {}).items()}
    for row in entries:
        scope = row.get('feature_scope')
        if scope and scope.get('instruction_snippet'):
            snippets[row['key']] = row['root'] + '/' + scope['instruction_snippet']
    if inventories:
        instruction += '\nPaths below are relative to this capabilities directory. Use only entries selected in delivery.json.\n'
        for inv in inventories:
            if inv['capability'] in snippets:
                instruction += '\nRead ' + snippets[inv['capability']] + '.\n'
            for feature in inv['features']:
                if feature['final_form'] in ('AS_IS', 'BRIDGED'):
                    tools = feature.get('tool_refs', []) + ([feature['entry']['tool']] if feature.get('entry') else [])
                    instruction += '- ' + inv['capability'] + ':' + feature['feature'] + ': ' + ', '.join(tools + feature.get('operations', [])) + '\n'
    write(output, 'AGENTS.md', instruction.encode())
    # Only generated support hashes; upstream layout is separately described.
    support = {p.relative_to(output).as_posix(): N.sha(p.read_bytes()) for p in output.rglob('*')
               if p.is_file() and not p.relative_to(output).as_posix().startswith('external/')}
    result = {'format_version': 1, 'kind': 'external-public-delivery', 'external': entries,
              'builtin': builtin['selections'], 'rsi_selected': rsi_manifest is not None, 'support_files': support,
              'private_checkers_included': False, 'local_bindings_included': False,
              'commands_executed': False, 'runtime_verified': False, 'budget_modified': False}
    if inventories:
        inv = module('inventory')
        selections = [{**row, 'root': 'builtin/' + row['root']} for row in builtin['selections']]
        for row in entries:
            if row['mode'] == 'NATIVE':
                selections.append({'name': row['key'], 'version': row['version'], 'root': row['root'], 'layout': row['layout'], 'tools': []})
            else:
                rows, _ = layout(output / row['root'], row['material_files'])
                selections.append({'name': row['key'], 'version': row['version'], 'root': row['root'], 'layout': rows, 'tools': []})
            for name in ('adapter', 'lifecycle'):
                if name in row: support[row[name]] = N.sha((output / row[name]).read_bytes())
        result.update(format_version=2, selections=selections, features=[f for i in inventories for f in i['features']],
                      instruction_snippets=snippets, retained_unmanaged=[])
        write(output, 'capability-inventory.json', C.encoded(inventories))
        write(output, 'capability-inventory.md', inv.markdown(inventories).encode())
        records = []
        for i in inventories:
            for d in i['decision_records']:
                if d not in records: records.append(d)
        write(output, 'decision-records.json', C.encoded(records))
    if P.check_selection(materials)['status'] != 'MATCH':
        raise ValueError('selected materials changed during delivery')
    write(output, 'delivery.json', C.encoded(result))
    return result


def bind_delivery(delivery, key, environment, *, project_root):
    """Resolve local tools explicitly in the receiving directory, without installing."""
    delivery = Path(delivery).resolve(strict=True)
    manifest = json.loads((delivery / 'delivery.json').read_text())
    selected = [r for r in manifest['external'] if r['key'] == key]
    if len(selected) != 1:
        raise ValueError('select one delivered external connection')
    row = selected[0]
    if row['mode'] != 'NATIVE':
        raise ValueError('catalog-only delivery; prepare explicit native dependencies before calling')
    root = (delivery / C.relative(row['root'])).resolve(strict=True)
    adapter = delivery / C.relative(row['adapter'])
    if not root.is_relative_to(delivery) or not adapter.resolve(strict=True).is_relative_to(delivery):
        raise ValueError('delivery path escapes support directory')
    check_layout(root, row['layout'])
    if 'lifecycle' in row:
        file = delivery / C.relative(row['lifecycle'])
        if not file.resolve(strict=True).is_relative_to(delivery) or N.sha(file.read_bytes()) != row['lifecycle_sha256']:
            raise ValueError('delivered lifecycle changed')
    if N.sha(adapter.read_bytes()) != row['adapter_sha256']:
        raise ValueError('delivered adapter changed')
    connection = {'key': key, 'source': str(root), 'resolved_source': str(root),
                  'catalog': row['catalog'], 'base_materials': row['base_materials']}
    binding = N.bind_native(connection, {'root': str(root), 'adapter_path': str(adapter),
                            'operations': row['operations'], 'environment_bindings': environment}, project_root=project_root,
                            delivery_identity=row.get('delivery_identity'))
    binding['delivery'] = {'root': str(delivery), 'key': key, 'manifest_sha256': N.sha((delivery / 'delivery.json').read_bytes())}
    return binding


def prepare_call(binding, operation, args=(), *, cwd):
    reference = binding['delivery']
    directory = Path(reference['root'])
    raw = (directory / 'delivery.json').read_bytes()
    if N.sha(raw) != reference['manifest_sha256']:
        raise ValueError('delivery manifest changed; select the new version explicitly')
    row = next(r for r in json.loads(raw)['external'] if r['key'] == reference['key'])
    if Path(binding['root']) != (directory / row['root']).resolve(strict=True):
        raise ValueError('binding is not for the selected delivered runtime')
    check_layout(Path(binding['root']), row['layout'])
    return N.prepare_call(binding, operation, args, cwd=cwd)


def compare_deliveries(previous, current):
    """Dependency selection facts only; original manager and C/G/N still own writes."""
    U = module('upgrade')
    def rows(path):
        return {r['key']: r for r in json.loads((Path(path) / 'delivery.json').read_text())['external']}
    return {'external': U._differences(rows(previous), rows(current)), 'commands_executed': False,
            'target_modified': False, 'budget_modified': False, 'authority_inherited': False,
            'next': 'Rebind selected dependencies; merge only declared Foundry-owned files using actual C/G/N.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    d = sub.add_parser('deliver'); d.add_argument('--materials', type=Path, required=True)
    d.add_argument('--output', type=Path, required=True); d.add_argument('--rsi-manifest', type=Path)
    b = sub.add_parser('bind'); b.add_argument('--delivery', type=Path, required=True)
    b.add_argument('--key', required=True); b.add_argument('--environment', type=Path, required=True)
    b.add_argument('--project-root', type=Path, required=True); b.add_argument('--output', type=Path, required=True)
    c = sub.add_parser('call'); c.add_argument('--binding', type=Path, required=True)
    c.add_argument('--operation', required=True); c.add_argument('--cwd', type=Path, required=True)
    c.add_argument('args', nargs=argparse.REMAINDER)
    u = sub.add_parser('compare'); u.add_argument('--previous', type=Path, required=True); u.add_argument('--current', type=Path, required=True)
    a = p.parse_args()
    try:
        if a.command == 'deliver':
            result = prepare_delivery(json.loads(a.materials.read_text()), a.output,
                                      rsi_manifest=json.loads(a.rsi_manifest.read_text()) if a.rsi_manifest else None,
                                      rsi_material_root=a.rsi_manifest.parent if a.rsi_manifest else None)
        elif a.command == 'bind':
            result = bind_delivery(a.delivery, a.key, json.loads(a.environment.read_text()), project_root=a.project_root)
            with a.output.open('x') as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
        elif a.command == 'call':
            result = prepare_call(json.loads(a.binding.read_text()), a.operation,
                                  a.args[1:] if a.args[:1] == ['--'] else a.args, cwd=a.cwd)
        else:
            result = compare_deliveries(a.previous, a.current)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'NOT_PREPARED', 'message': str(exc), 'commands_executed': False}))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
