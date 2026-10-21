"""Read-only host handoff for a selected capability tool.

The host may read private checker dependencies while checking the selection.
Do not run this helper inside a producer or give that producer materials.json.
The returned command uses only its public tool and declared executable bindings;
the existing caller still owns permission, execution, budget and recovery.
This is neither a file lock nor a receiver/SDK version probe.
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path


_spec = importlib.util.spec_from_file_location('capability_prepare_for_call', Path(__file__).with_name('prepare.py'))
_prepare = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_prepare)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _selected_tool(materials, tool_id):
    binding = materials['tool_bindings'].get(tool_id)
    _require(isinstance(binding, dict), 'selected tool is absent: ' + tool_id)
    packages = [row for row in materials['preparation']['selections']
                if row['name'] == binding['package'] and row['version'] == binding['version']]
    _require(len(packages) == 1, 'tool package/version is not selected: ' + tool_id)
    selected = packages[0]
    root = Path(selected['directory'])
    listed = {row['path'] for row in selected['files']}
    _require('capability.json' in listed, 'selection lacks its descriptor: ' + tool_id)
    descriptor = json.loads(_prepare._file(root, 'capability.json').read_text(encoding='utf-8'))
    _require((descriptor['name'], descriptor['version']) == (binding['package'], binding['version']),
             'descriptor identity differs from selected tool: ' + tool_id)
    declared = {'capability.json', *descriptor.get('materials', []), *descriptor.get('runtime_files', []),
                *(row['path'] for row in descriptor.get('tools', [])),
                *(row if isinstance(row, str) else row['path'] for row in descriptor.get('verification_files', []))}
    _require(listed == declared, 'selection does not cover declared files: ' + tool_id)
    entries = [row for row in descriptor.get('tools', []) if row['id'] == tool_id]
    _require(len(entries) == 1, 'tool is not unique in selected descriptor: ' + tool_id)
    entry = entries[0]
    path = str(_prepare._file(root, entry['path']))
    interpreter = entry.get('interpreter')
    prefix = [interpreter, *entry.get('interpreter_args', []), path] if interpreter else [tool_id]
    _require(binding['argv_prefix'] == prefix, 'tool prefix differs from selected descriptor: ' + tool_id)
    return binding, entry, path, prefix


def prepare_call(materials, tool_id, args=()):
    """Validate a host-owned selection and return a command without starting it.

    local_argv retains the existing logical executable syntax. argv is its
    concrete host equivalent. Private verification files are checked by this
    host, never added to the command or copied into the producer's sources.
    """
    _require(isinstance(tool_id, str), 'tool_id must be a string')
    _require(isinstance(args, (list, tuple)) and all(isinstance(value, str) for value in args),
             'args must be a list or tuple of strings')
    _require(materials['preparation']['readiness'] == 'READY', 'capability materials are not READY')
    _require(_prepare.check_selection(materials)['status'] == 'MATCH', 'selected capability files changed')
    binding, _, _, prefix = _selected_tool(materials, tool_id)
    fragment = materials['scope_fragment']['executables']
    executables = materials.get('scope', materials['scope_fragment'])['executables']
    observations = materials['preparation']['environment']['bindings']

    def executable(identity):
        value = executables.get(identity)
        _require(isinstance(value, str) and Path(value).is_absolute(), 'executable is not bound: ' + identity)
        _require(identity in fragment and _prepare._call_path(value) == _prepare._call_path(fragment[identity]),
                 'executable differs from prepared binding: ' + identity)
        facts = observations.get(identity)
        if facts is not None:
            _require(facts['kind'] == 'executable'
                     and _prepare._call_path(value) == _prepare._call_path(facts['absolute_path'])
                     and str(Path(value).resolve(strict=True)) == facts['resolved_path'],
                     'executable observation changed: ' + identity)
        else:
            _, native, native_path, _ = _selected_tool(materials, identity)
            _require(not native.get('interpreter') and _prepare._call_path(value) == _prepare._call_path(native_path),
                     'native executable differs from selected tool: ' + identity)
        _require(Path(value).is_file() and os.access(value, os.X_OK), 'executable is unavailable: ' + identity)
        return value

    local_argv = [*prefix, *args]
    argv = [executable(prefix[0])]
    for value in local_argv[1:]:
        argv.append(executable(value.removeprefix('executable://')) if value.startswith('executable://') else value)
    return {'tool_id': tool_id, 'package': binding['package'], 'version': binding['version'],
            'local_argv': local_argv, 'argv': argv, 'commands_executed': False,
            'acceptance_granted': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--materials', required=True, type=Path)
    parser.add_argument('--tool', required=True)
    parser.add_argument('args', nargs=argparse.REMAINDER)
    options = parser.parse_args()
    try:
        args = options.args[1:] if options.args[:1] == ['--'] else options.args
        result = prepare_call(json.loads(options.materials.read_text(encoding='utf-8')), options.tool, args)
    except (OSError, RuntimeError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({'status': 'NOT_PREPARED', 'error': str(exc), 'commands_executed': False}))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
