"""Prepare an explicit next capability selection; never apply or resume work.

The next config is complete and uses project-owned base materials, not a prior
capability-expanded result. Old packages, targets, reports and authority remain
untouched. This host-only handoff is neither an installer nor a continuation
state machine; ordinary target files still use the existing C/G/N helpers.
"""

import argparse
from copy import deepcopy
import importlib.util
import json
from pathlib import Path


_spec = importlib.util.spec_from_file_location('capability_prepare_for_upgrade', Path(__file__).with_name('prepare.py'))
_prepare = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_prepare)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _packages(materials):
    rows = materials.get('preparation', {}).get('selections', [])
    result = {row['name']: row for row in rows}
    _require(len(result) == len(rows), 'previous selections must have unique capability names')
    return result


def _differences(before, after):
    return [{'id': key, 'change': 'ADDED' if key not in before else 'REMOVED' if key not in after else 'CHANGED',
             'before': deepcopy(before.get(key)), 'after': deepcopy(after.get(key))}
            for key in sorted(before.keys() | after.keys())
            if key not in before or key not in after or before[key] != after[key]]


def _workpack_sources(materials):
    if 'request' in materials:
        return {row['workpack_id']: [value['id'] for value in row.get('inputs', []) if value['kind'] == 'SOURCE']
                for row in materials['request']['plan']['workpacks']}
    return {key: [row['id'] for row in values if row['kind'] == 'SOURCE']
            for key, values in materials.get('request_fragment', {}).get('workpack_inputs', {}).items()}


def _sources(materials, files=None):
    """Observe only explicit source files, without treating absent history as equal."""
    result = {}
    for row in materials.get('source_manifest', []):
        observed = {'path': row['path'], 'sha256': None, 'available': False}
        try:
            raw = files['sources/' + row['path']] if files is not None else _prepare._file(
                Path(materials['preparation']['source_root']).resolve(strict=True), row['path']).read_bytes()
            observed.update(sha256=_prepare._digest(raw), available=True)
        except (OSError, RuntimeError, KeyError, ValueError):
            pass
        result[row['source_id']] = observed
    return result


def _without_capabilities(config, output_root):
    """Return the explicit project base; do not infer removal from old scope."""
    project = Path(config['project_root'])
    _require(project.is_absolute() and project.is_dir(), 'project_root must be an existing absolute directory')
    base = deepcopy(config.get('base_materials', {}))
    output = Path(output_root).absolute()
    scope = base.get('scope', {})
    files, manifest, origins, sources = {}, [], [], []
    production = []
    request = base.get('request')
    removed_context = []
    if base:
        _require(request is not None, 'project base_materials requires its existing request')
        source_root = Path(config['source_root'])
        _require(source_root.is_absolute(), 'source_root must be explicit and absolute')
        source_root = source_root.resolve(strict=True)
        originals = {row['source_id']: row for row in request['requirement_ir']['sources']}
        rows = base['source_manifest']
        _require(len(originals) == len(request['requirement_ir']['sources'])
                 and len(rows) == len(originals) and {row['source_id'] for row in rows} == set(originals),
                 'project source manifest and requirement sources differ')
        for row in rows:
            _require(originals[row['source_id']]['path_or_uri'] == row['path'],
                     'project source path disagrees with requirement: ' + row['source_id'])
            path = _prepare._file(source_root, row['path'])
            production.append(path)
            raw = _prepare._text(path.read_bytes(), row['path'])
            _prepare._insert_file(files, 'sources/' + row['path'], raw)
            manifest.append(deepcopy(row))
            sources.append(deepcopy(originals[row['source_id']]))
            origins.append({'source_id': row['source_id'], 'origin': str(path)})
        removed_context = [key for key in request if key not in ('requirement_ir', 'plan')]
        request = {key: request[key] for key in ('requirement_ir', 'plan')}
    environment = _prepare.resolve_environment([], {}, project_root=project)
    preparation = deepcopy(base.get('preparation', {}))
    diagnostics = deepcopy(preparation.get('diagnostics', []))
    bindings = config.get('environment_bindings', {})
    _require(isinstance(bindings, dict), 'environment_bindings must be an object')
    project_executables = scope.get('executables', {})
    for identity, binding in bindings.items():
        if identity not in project_executables:
            diagnostics.append({'id': identity, 'code': 'UNSELECTED_ENVIRONMENT_BINDING', 'severity': 'INFO',
                                'message': 'No selected capability consumes this binding; the explicit project '
                                'scope and physical dependencies are unchanged.'})
            continue
        # Reuse the existing path resolver, then compare invocation paths rather
        # than final binaries so a different virtual environment is not collapsed.
        observed = _prepare.resolve_environment([{'id': identity, 'kind': 'executable'}],
                                                {identity: binding}, project_root=project)
        path = observed['bindings'].get(identity, {}).get('absolute_path')
        if path and _prepare._call_path(path) == _prepare._call_path(project_executables[identity]):
            continue
        diagnostics.append({'id': identity, 'code': 'ENVIRONMENT_BINDINGS_NOT_APPLIED', 'severity': 'ERROR',
                            'message': 'This binding differs from the explicit project executable and was not applied. '
                            'Put the intended project environment change in base_materials.scope before preparing again.'})
    protected = _prepare._prepare_verifier_inputs(
        scope, preparation.get('verifier_inputs', []), production, output)
    preparation.update(status='MATERIALS_ONLY_NOT_APPROVED',
                       readiness='INCOMPLETE' if preparation.get('readiness') == 'INCOMPLETE'
                       or any(row.get('severity') == 'ERROR' for row in diagnostics) else 'READY',
                       source_root=str(output / 'sources'), source_origins=origins, selections=[],
                       environment=environment, diagnostics=diagnostics, verifier_inputs=protected,
                       checker_files_fragment=[row['path'] for row in protected],
                       removed_request_context=removed_context, commands_executed=False,
                       runtime_verified=False, protected_copy_created=False)
    result = {'source_manifest': manifest,
              'scope_fragment': deepcopy(base.get('scope_fragment', {'executables': {}, 'source_read_roots': []})),
              'request_fragment': {'sources': sources, 'workpack_inputs': {}},
              'tool_bindings': {}, 'preparation': preparation}
    if request is not None:
        result['request'], result['scope'] = request, deepcopy(scope)
    return result, files


def build_upgrade(previous_materials, config, output_root):
    """Return (new materials, file bytes, transition) without writing/executing.

    Config.selections is the complete next set, including an explicit [] when
    returning to project-only materials. That path returns the explicit project
    base scope; differing project executable bindings are reported unapplied,
    while equivalent restatements and unused removed-capability bindings do not
    block preparation.
    Historical drift is diagnostic: fresh
    explicit bindings can repair it without rewriting the old evidence.
    """
    _require(isinstance(previous_materials, dict) and isinstance(config, dict), 'materials and config must be objects')
    _require('selections' in config and isinstance(config['selections'], list), 'provide the complete next selections list')
    base = config.get('base_materials', {})
    _require(isinstance(base, dict), 'base_materials must be project materials')
    _require(not base.get('preparation', {}).get('selections') and not base.get('tool_bindings'),
             'base_materials must be project materials, not capability-expanded materials')
    before = _packages(previous_materials)
    previous_check = _prepare.check_selection(previous_materials)
    if config['selections']:
        materials, files = _prepare.build_materials(config, output_root)
    else:
        materials, files = _without_capabilities(config, output_root)
    after = _packages(materials)
    package_changes = []
    for name in sorted(before.keys() | after.keys()):
        old, new = before.get(name), after.get(name)
        changes = []
        if old is None:
            changes.append('ADDED')
        elif new is None:
            changes.append('REMOVED')
        else:
            if old['version'] != new['version']:
                changes.append('VERSION_CHANGED')
            if {row['path']: row['sha256'] for row in old['files']} != {row['path']: row['sha256'] for row in new['files']}:
                changes.append('CONTENT_CHANGED')
            if old['directory'] != new['directory'] or {row['path']: row['resolved_path'] for row in old['files']} != {
                    row['path']: row['resolved_path'] for row in new['files']}:
                changes.append('LOCATION_CHANGED')
        package_changes.append({'name': name, 'changes': changes or ['UNCHANGED'],
                                'before': deepcopy(old), 'after': deepcopy(new)})
    old_sources, new_sources = _workpack_sources(previous_materials), _workpack_sources(materials)
    changed_names = {row['name'] for row in package_changes if row['changes'] != ['UNCHANGED']}
    source_files = _differences(_sources(previous_materials), _sources(materials, files))
    affected_source_ids = {row['source_id'] for data in (previous_materials, materials)
                           for row in data.get('source_manifest', [])
                           if any(row['path'].startswith('capabilities/' + name + '/') for name in changed_names)}
    affected_source_ids.update(row['id'] for row in source_files)
    source_changes = _differences(old_sources, new_sources)
    transition = {
        'format_version': 1, 'kind': 'capability-upgrade-handoff', 'status': 'MATERIALS_ONLY_NOT_APPROVED',
        'previous_selection_check': previous_check,
        'previous_diagnostics': deepcopy(previous_materials.get('preparation', {}).get('diagnostics', [])),
        'packages': package_changes,
        'tools': _differences(previous_materials.get('tool_bindings', {}), materials.get('tool_bindings', {})),
        'environment': _differences(previous_materials.get('preparation', {}).get('environment', {}).get('bindings', {}),
                                    materials['preparation']['environment']['bindings']),
        'scope_executables': _differences(previous_materials.get('scope', previous_materials.get('scope_fragment', {})).get('executables', {}),
                                          materials.get('scope', materials['scope_fragment']).get('executables', {})),
        'source_files': source_files,
        'workpack_sources': source_changes,
        'source_affected_workpacks': sorted({row['id'] for row in source_changes} | {
            task for mapping in (old_sources, new_sources) for task, values in mapping.items()
            if affected_source_ids.intersection(values)}),
        'next_readiness': materials['preparation']['readiness'],
        'commands_executed': False, 'target_modified': False, 'physical_files_removed': False,
        'acceptance_granted': False, 'authority_inherited': False, 'budget_modified': False,
    }
    return materials, files, transition


def write_upgrade(previous_materials, config, output_root):
    """Write only a new host materials directory, retaining partial I/O output."""
    output = Path(output_root).absolute()
    _require(not output.exists() and not output.is_symlink(), 'output must be a new materials directory')
    materials, files, transition = build_upgrade(previous_materials, config, output)
    output.mkdir(parents=True, exist_ok=False)
    for relative, raw in files.items():
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as stream:
            stream.write(raw)
    for name, data in (('materials.json', materials), ('transition.json', transition)):
        with (output / name).open('xb') as stream:
            stream.write(_prepare._json(data))
    return materials, transition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous', required=True, type=Path)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        materials, _ = write_upgrade(json.loads(args.previous.read_text(encoding='utf-8')),
                                     json.loads(args.config.read_text(encoding='utf-8')), args.output)
    except (OSError, RuntimeError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({'status': 'PREPARATION_ERROR', 'message': str(exc), 'commands_executed': False}, ensure_ascii=False))
        return 1
    print(json.dumps({'status': 'MATERIALS_ONLY_NOT_APPROVED', 'readiness': materials['preparation']['readiness'],
                      'materials': str(args.output.absolute() / 'materials.json'),
                      'transition': str(args.output.absolute() / 'transition.json'),
                      'commands_executed': False}, ensure_ascii=False))
    return 0 if materials['preparation']['readiness'] == 'READY' else 1


if __name__ == '__main__':
    raise SystemExit(main())
