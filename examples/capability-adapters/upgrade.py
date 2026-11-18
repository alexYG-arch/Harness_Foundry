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


def _sources(materials, files=None, *, skipped=()):
    """Observe only explicit source files, without treating absent history as equal."""
    result = {}
    for row in materials.get('source_manifest', []):
        observed = {'path': row['path'], 'sha256': None, 'available': False}
        parts = row['path'].split('/', 2)
        if len(parts) == 3 and parts[0] == 'external' and parts[1] in skipped:
            observed.update(sha256=materials['preparation'].get('source_digests', {}).get(row['source_id']),
                            available=None)
            result[row['source_id']] = observed
            continue
        try:
            raw = files['sources/' + row['path']] if files is not None else _prepare._file(
                Path(materials['preparation']['source_root']).resolve(strict=True), row['path']).read_bytes()
            observed.update(sha256=_prepare._digest(raw), available=True)
        except (OSError, RuntimeError, KeyError, ValueError):
            pass
        result[row['source_id']] = observed
    return result


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
    selection = _prepare._scope.contract(config.get('connections'))
    if selection is None and 'connection_selection' in base.get('preparation', {}):
        raise ValueError('scoped materials cannot be reused as a legacy project base')
    skipped = set()
    if selection is not None:
        _prepare._scope.project_base(base)
        materials, files = _prepare.build_materials(config, output_root)
        current = {r['key']: r for r in materials['preparation'].get('external_connections', [])}
        history = previous_materials['preparation'].get('external_connections', [])
        same_source = {r['key'] for r in history if r['key'] in current and
                       r['resolved_source'] == current[r['key']]['resolved_source']}
        historical_keys = {r['key'] for r in history}
        for row in previous_materials.get('source_manifest', []):
            parts = row['path'].split('/', 2)
            if len(parts) == 3 and parts[0] == 'external':
                historical_keys.add(parts[1])
        skipped = historical_keys - same_source
        # Historical external authority never triggers live native, mapping or
        # package reads. The new preparation independently checks selected inputs.
        previous_check = _prepare.check_selection(_prepare._scope.limited(previous_materials, set()))
        if history:
            previous_check['external_not_rechecked'] = [
                {k: r[k] for k in ('key', 'revision', 'source', 'resolved_source')} for r in history]
            if previous_check['status'] == 'MATCH':
                previous_check['status'] = 'PARTIALLY_CHECKED'
    else:
        previous_check = _prepare.check_selection(previous_materials)
        connections = config.get('connections')
        loaded = _prepare._connections.load_connections(
            connections['instance_root'], config['project_root'], connections.get('skills', [])) if connections is not None else None
        # Removing native execution need not remove the connected public materials.
        # A genuinely empty/disconnected registry still returns the project base.
        if (config['selections'] or (connections or {}).get('native')
                or loaded and loaded['connections']):
            materials, files = _prepare.build_materials(config, output_root, connection_snapshot=loaded)
        else:
            materials, files = _prepare.project_only_materials(config, output_root)
            if loaded:
                # No available external materials: retain project facts and the
                # loader's existing optional/required diagnostic distinction.
                preparation = materials['preparation']
                preparation['diagnostics'].extend(loaded['diagnostics'])
                if any(row.get('severity') == 'ERROR' for row in loaded['diagnostics']):
                    preparation['readiness'] = 'INCOMPLETE'
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
    source_files = _differences(_sources(previous_materials, skipped=skipped), _sources(materials, files))
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
        'native_bindings': _differences(previous_materials.get('native_bindings', {}), materials.get('native_bindings', {})),
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
    def features(value):
        return {r['capability']+':'+r['feature']: r
                for package in value['preparation'].get('selections', [])
                for r in package.get('feature_scope', {}).get('features', [])} | {
                r['capability']+':'+r['feature']: r
                for projection in value['preparation'].get('external_features', {}).values()
                for r in projection['features']}
    old_features, new_features = features(previous_materials), features(materials)
    if old_features or new_features:
        transition['feature_changes'] = _differences(old_features, new_features)
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
