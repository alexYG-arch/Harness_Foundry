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
    files, selections = {}, []
    for row in materials['preparation']['selections']:
        root = Path(row['directory'])
        descriptor = json.loads((root / 'capability.json').read_text())
        public = set(descriptor.get('materials', [])) | set(descriptor.get('runtime_files', [])) | {
            entry['path'] for entry in descriptor.get('tools', [])}
        version_dir = quote(row['version'], safe='')
        if version_dir in ('.', '..'):
            version_dir = version_dir.replace('.', '%2E')
        prefix = 'capabilities/' + _consume._prepare._id(row['name']) + '/' + version_dir + '/' 
        for relative in sorted(public):
            _consume._prepare._insert_file(files, prefix + relative, _consume._prepare._file(root, relative).read_bytes())
        selections.append({'name': row['name'], 'version': row['version'], 'root': prefix,
                           'tools': descriptor.get('tools', []), 'requirements': descriptor.get('environment', []),
                           'binding_required': True})
    manifest = {'format_version': 1, 'kind': 'stack-public-delivery', 'selections': selections,
                'files': [{'path': name, 'sha256': hashlib.sha256(raw).hexdigest()} for name, raw in sorted(files.items())],
                'private_checkers_included': False, 'local_bindings_included': False,
                'execution_authority_granted': False, 'runtime_verified': False}
    output.mkdir(parents=True, exist_ok=False)
    for relative, raw in files.items():
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
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
    args = parser.parse_args()
    materials = json.loads(args.materials.read_text())
    if args.command == 'call':
        values = args.args[1:] if args.args[:1] == ['--'] else args.args
        result = prepare_call(materials, args.tool, values)
    else:
        result = public_delivery(materials, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
