"""Prepare ordinary-file delivery intents for the existing apply helper.

Host preparation only. Links retain their layout and are handed back to the
existing layout writer; they are never represented as required ordinary files.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path


def prepare(payload, output, *, result, workpack_id='CAPABILITY-DELIVERY'):
    payload = Path(payload).resolve(strict=True)
    output = Path(output).absolute()
    base = Path(__file__).resolve().parents[1] / 'harness-composition-upgrade/helpers'
    spec = importlib.util.spec_from_file_location('delivery_intent_files', base / 'file_states.py')
    fs = importlib.util.module_from_spec(spec); spec.loader.exec_module(fs)
    result = str(fs.relative_path(result))
    prefix = 'harness/capabilities'
    if result == prefix or result.startswith(prefix + '/'):
        raise ValueError('result must not overlap capability payload')
    if output.resolve().is_relative_to(payload) or payload.is_relative_to(output.resolve()):
        raise ValueError('intent materials must remain separate from public payload')
    files, layouts = [], []
    for path in sorted(payload.rglob('*')):
        relative = path.relative_to(payload).as_posix()
        name = prefix + '/' + relative
        if path.is_symlink():
            layouts.append({'path': name, 'kind': 'link', 'target': os.readlink(path)})
        elif path.is_file():
            files.append({'path': name, 'action': 'create', 'expected': {'missing': True},
                          'desired': {'file': os.path.relpath(path, output), 'executable': bool(path.stat().st_mode & 0o111)}})
        elif path.is_dir():
            layouts.append({'path': name, 'kind': 'directory'})
    intents = {'format_version': 1, 'files': files}
    fragment = {'workpack_id': workpack_id, 'status': 'MATERIALS_ONLY_NOT_APPROVED',
                'effects': {'required': [r['path'] for r in files] + [result],
                            'allowed': [r['path'] for r in files] + [r['path'] for r in layouts] + [result],
                            'must_preserve': []},
                'result': result, 'layout_steps': layouts,
                'links_require_layout_writer': any(r['kind'] == 'link' for r in layouts),
                'next': 'Merge into the existing Plan and use its authorized LOCAL execution. Payload and intents stay outside the target.',
                'commands_executed': False, 'budget_modified': False}
    output.mkdir(parents=True, exist_ok=False)
    for name, value in (('apply-intents.json', intents), ('plan-fragment.json', fragment)):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    return fragment


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--payload', required=True); p.add_argument('--output', required=True)
    p.add_argument('--result', required=True); p.add_argument('--workpack-id', default='CAPABILITY-DELIVERY')
    a = p.parse_args()
    print(json.dumps(prepare(a.payload, a.output, result=a.result, workpack_id=a.workpack_id), ensure_ascii=False))


if __name__ == '__main__': main()
