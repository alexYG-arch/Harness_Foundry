"""Optional host handoff and public delivery for selected stack packages.

Never pass complete host materials to a producer. This module performs no
business execution, approval, budget mutation or SDK/venv installation.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.parse import quote


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_consume = _load('stack_handoff_consume', 'consume.py')
_runtime = _load('stack_handoff_runtime', 'stack_runtime.py')


def prepare_call(materials, tool_id, args=()):
    binding = materials['tool_bindings'][tool_id]
    profiles = [p for p in materials['preparation'].get('stack_profiles', [])
                if p['package'] == binding['package'] and p['version'] == binding['version']]
    if len(profiles) != 1:
        raise ValueError('select exactly one environment_profile for this tool')
    row = profiles[0]
    args = list(args)
    if not args or args[0].startswith('-'):
        raise ValueError('a stack operation is required before its arguments')
    wrapper_args = args[:args.index('--')] if '--' in args else args
    if any(v == '--profile' or v.startswith('--profile=') for v in wrapper_args):
        raise ValueError('profile comes from the selected binding, not an argument override')
    result = _consume.prepare_call(materials, tool_id, [args[0], '--profile', row['source'], *args[1:]])
    profile = _runtime.load_profile(row['source'], (binding['package'], binding['version']))
    return {**result, 'profile_sha256': _runtime.profile_digest(profile),
            'profile_source_id': row['source_id'], 'profile_verifier_path': row['target_path']}


def public_delivery(materials, output_root):
    """Write new public files only. Local bindings must be recreated explicitly."""
    if _consume._prepare.check_selection(materials)['status'] != 'MATCH':
        raise ValueError('selected capability or environment files changed')
    output = Path(output_root)
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    # Share the existing E6 layout copier; do not flatten public tool links.
    delivery = _load('stack_handoff_layout', 'delivery.py')
    files, selections, staged = {}, [], []
    inventories = [r['feature_scope'] for r in materials['preparation']['selections'] if 'feature_scope' in r]
    is_v2 = bool(inventories)
    for row in materials['preparation']['selections']:
        root = Path(row['directory'])
        descriptor = json.loads((root / 'capability.json').read_text())
        public = set(descriptor.get('materials', [])) | set(descriptor.get('runtime_files', [])) | {
            entry['path'] for entry in descriptor.get('tools', [])}
        feature_scope = row.get('feature_scope')
        tools = descriptor.get('tools', [])
        requirements = descriptor.get('environment', [])
        if feature_scope is not None:
            public = set(feature_scope['delivery_files'])
            delivered_features = [f for f in feature_scope['features'] if f['final_form'] in ('AS_IS', 'BRIDGED')]
            names = {tool for f in delivered_features for tool in [*f.get('tool_refs', []), *([f['entry']['tool']] if f.get('entry') else [])]}
            tools = [t for t in tools if t['id'] in names]
            declared_features = _load('stack_delivery_features', 'inventory.py').validate(descriptor)
            env_ids = {r for f in declared_features if f['id'] in {r['feature'] for r in delivered_features}
                       for r in f.get('environment_refs', [e['id'] for e in descriptor.get('environment', [])])}
            env_ids.update(t['interpreter'] for t in tools if t.get('interpreter'))
            envs = {e['id']: e for e in descriptor.get('environment', [])}
            requirements = [envs.get(k, {'id': k, 'kind': 'executable'}) for k in sorted(env_ids)]
            if not public: continue
        version_dir = quote(row['version'], safe='')
        if version_dir in ('.', '..'):
            version_dir = version_dir.replace('.', '%2E')
        prefix = ('' if is_v2 else 'capabilities/') + _consume._prepare._id(row['name']) + '/' + version_dir + '/'
        for relative in sorted(public):
            _consume._prepare._insert_file(files, prefix + relative, _consume._prepare._file(root, relative).read_bytes())
        rows, payloads = delivery.layout(root, public)
        for relative, raw in payloads.items():
            _consume._prepare._insert_file(files, prefix + relative, raw)
        staged.append((root, prefix, rows, payloads))
        selections.append({'name': row['name'], 'version': row['version'], 'root': prefix,
                           'tools': tools, 'requirements': requirements,
                           'layout': rows, 'binding_required': True})
        if feature_scope is not None:
            selections[-1]['features'] = [f['feature'] for f in delivered_features]
    manifest = {'format_version': 2 if is_v2 else 1, 'kind': 'stack-public-delivery', 'selections': selections,
                'files': [{'path': name, 'sha256': hashlib.sha256(raw).hexdigest()} for name, raw in sorted(files.items())],
                'private_checkers_included': False, 'local_bindings_included': False,
                'execution_authority_granted': False, 'runtime_verified': False}
    output.mkdir(parents=True, exist_ok=False)
    for root, prefix, rows, payloads in staged:
        delivery.write_layout(output / prefix, rows, payloads)
        delivery.check_layout(output / prefix, rows)
        delivery.check_layout(root, rows)
    if _consume._prepare.check_selection(materials)['status'] != 'MATCH':
        raise ValueError('selected capability or environment files changed during delivery')
    if is_v2:
        inventory = _load('stack_handoff_inventory', 'inventory.py')
        manifest.update(features=[f for inv in inventories for f in inv['features']],
                        instruction_snippets={inv['capability']: row['root'] + inv['instruction_snippet']
                                              for inv in inventories for row in selections
                                              if row['name'] == inv['capability'] and inv['instruction_snippet']},
                        retained_unmanaged=[])
        decision_records = []
        for inv in inventories:
            for record in inv['decision_records']:
                if record not in decision_records: decision_records.append(record)
        _runtime.write_new_json(output / 'capability-inventory.json', inventories)
        (output / 'capability-inventory.md').write_text(inventory.markdown(inventories))
        _runtime.write_new_json(output / 'decision-records.json', decision_records)
    _runtime.write_new_json(output / 'delivery.json', manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    call = sub.add_parser('call')
    call.add_argument('--materials', type=Path, required=True)
    call.add_argument('--tool', required=True)
    call.add_argument('args', nargs=argparse.REMAINDER)
    deliver = sub.add_parser('deliver')
    deliver.add_argument('--materials', type=Path, required=True)
    deliver.add_argument('--output', type=Path, required=True)
    bind = sub.add_parser('bind')
    bind.add_argument('--delivery', type=Path, required=True)
    bind.add_argument('--environment', type=Path, required=True)
    bind.add_argument('--project-root', type=Path, required=True)
    bound = sub.add_parser('call-delivered')
    bound.add_argument('--binding', type=Path, required=True); bound.add_argument('--tool', required=True)
    bound.add_argument('args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command == 'bind':
        print(json.dumps(bind_delivery(args.delivery, json.loads(args.environment.read_text()), project_root=args.project_root), ensure_ascii=False, indent=2))
        return
    if args.command == 'call-delivered':
        values = args.args[1:] if args.args[:1] == ['--'] else args.args
        print(json.dumps(delivered_call(json.loads(args.binding.read_text()), args.tool, values), ensure_ascii=False, indent=2))
        return
    materials = json.loads(args.materials.read_text())
    if args.command == 'call':
        values = args.args[1:] if args.args[:1] == ['--'] else args.args
        result = prepare_call(materials, args.tool, values)
    else:
        result = public_delivery(materials, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))



def bind_delivery(output_root, environment, *, project_root):
    """Bind the delivered public subset, never reopen host source or private checks."""
    output = Path(output_root).resolve(strict=True)
    raw = (output/'delivery.json').read_bytes(); manifest=json.loads(raw)
    if manifest['format_version'] != 2: raise ValueError('feature binding requires delivery v2')
    layout = _load('stack_feature_layout', 'delivery.py')
    requirements={}; tools={}
    for selected in manifest['selections']:
        root=output/selected['root'];layout.check_layout(root,selected['layout'])
        for req in selected['requirements']:_consume._prepare._merge_requirement(requirements,req)
        for tool in selected['tools']:
            _consume._prepare._merge(tools,tool['id'],{**tool,'root':selected['root']},'delivered tool')
    env=_consume._prepare.resolve_environment(list(requirements.values()),environment,project_root=project_root)
    return {'delivery_root':str(output),'manifest_sha256':hashlib.sha256(raw).hexdigest(),
            'tools':tools,'environment':env,'commands_executed':False,'acceptance_granted':False}


def delivered_call(binding, tool_id, args=()):
    root=Path(binding['delivery_root']);raw=(root/'delivery.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=binding['manifest_sha256']:raise ValueError('delivery identity changed')
    manifest=json.loads(raw);layout=_load('stack_feature_layout_call','delivery.py')
    expected={}
    for selected in manifest['selections']:
        layout.check_layout(root/selected['root'],selected['layout'])
        for tool in selected['tools']:expected[tool['id']]={**tool,'root':selected['root']}
    if expected!=binding['tools']:raise ValueError('delivered invocation table changed')
    if binding['environment']['status']!='READY':raise ValueError('delivered environment incomplete')
    if tool_id not in expected:raise ValueError('tool not selected for delivery')
    tool=expected[tool_id];file=root/tool['root']/tool['path']
    interpreter=tool.get('interpreter')
    if interpreter:
        fact=binding['environment']['bindings'][interpreter]
        invocation=Path(fact['absolute_path'])
        if str(invocation.resolve(strict=True))!=fact['resolved_path']:raise ValueError('bound interpreter changed')
        argv=[str(invocation),*tool.get('interpreter_args',[]),str(file),*args]
    else: argv=[str(file),*args]
    return {'tool_id':tool_id,'argv':argv,'commands_executed':False,'acceptance_granted':False}


if __name__ == '__main__':
    main()
