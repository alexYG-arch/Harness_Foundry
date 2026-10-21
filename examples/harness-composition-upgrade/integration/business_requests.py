"""Prepare R3 business Generic materials without creating a Program or target.

Automatic plans run a fixed-input business workflow. Reviewed plans only copy
existing declared outputs and check them against protected host observations.
The outer host supplies actual document/runtime decisions and returned IDs later.
"""

import argparse
import json
import os
from pathlib import Path, PurePosixPath


GROUPS = {
    'prd-design': 'prd-design',
    'data-reasoning': 'data-reasoning',
    'market-research': 'market-research',
    'market-live': 'market-research',
}


def absolute(value):
    path = Path(value)
    if not path.is_absolute():
        raise ValueError('bindings must use absolute paths: ' + str(value))
    return path.resolve()


def executable(value):
    path = Path(value)
    if not path.is_absolute() or not path.is_file():
        raise ValueError('executable binding must name an existing absolute file')
    return str(path)  # Keep an explicitly selected venv/receiver alias.


def relative_file(root, name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or '\\' in name or any(x in ('', '.', '..') for x in name.split('/')):
        raise ValueError('expected a named relative input file: ' + str(name))
    source = root / path
    if not source.is_file():
        raise ValueError('missing declared input: ' + str(source))
    return source


def build_materials(group, version, phase, bindings):
    group = group.replace('_', '-')
    if group not in GROUPS or version not in ('v1', 'v2') or phase not in ('automatic', 'reviewed'):
        raise ValueError('unsupported business group, workflow version or phase')
    if group == 'market-live' and phase != 'reviewed':
        raise ValueError('market-live uses actual outer-host search/open results followed by reviewed LOCAL reuse')
    source = absolute(bindings['requirement_path'])
    document = source.read_bytes().decode('utf-8')
    if not document.strip():
        raise ValueError('build document must have content')
    locator = 'L1-L' + str(len(document.splitlines()))
    workspace = absolute(bindings['workspace_root'])
    verifier = absolute(bindings['verification_root'])
    resources = absolute(bindings['resource_root'])
    fixture = absolute(bindings['group_root'])
    manifest = json.loads((fixture / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['id'] != GROUPS[group].replace('-', '_'):
        raise ValueError('fixture does not match selected business group')
    workflow_name = manifest['workflows'][version]
    workflow = relative_file(fixture, workflow_name)
    workflow_text = workflow.read_bytes().decode('utf-8')
    if not workflow_text.strip():
        raise ValueError('selected workflow must have content')
    names = (manifest['live_outputs'] if group == 'market-live' else
             manifest['outputs'] + (manifest['v2_additional_outputs'] if version == 'v2' else []))
    # These are fixed example contracts, not a general user-supplied task schema.
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or len(path.parts) != 1 or name in ('', '.', '..') or '\\' in name:
            raise ValueError('business output must be a named ordinary file')
    fixture_names = ['manifest.json', 'expected.json', workflow_name, *manifest['inputs']]
    verifier_inputs = [{'source': str(relative_file(fixture, name)), 'path': 'business/' + GROUPS[group] + '/' + name}
                       for name in fixture_names]
    read_roots = [absolute(value) for value in bindings['python_read_roots']]
    preparation = {'status': 'MATERIALS_ONLY_NOT_APPROVED', 'source_root': str(source.parent),
                   'group': group, 'version': version, 'phase': phase,
                   'workflow_path': str(workflow), 'workflow_text': workflow_text,
                   'runtime_identity': None, 'accepted_A': None,
                   'next': 'Display the versioned build document, obtain actual review, prepare named verifier inputs, then use real Generic IDs and scope readback.'}
    paths = ['outputs/' + name for name in names]
    case = 'BUSINESS-' + phase.upper()
    workpack = 'PRODUCE' if phase == 'automatic' else 'REUSE'
    check_argv = ['python', '-I', '-B', 'verifier://check_business.py', '--group', group,
                  '--version', version, '--phase', phase, '--target', 'outputs',
                  '--fixture', 'verifier://business/' + GROUPS[group] + '/manifest.json']
    effects = {'allowed': paths.copy(), 'required': paths.copy(), 'must_preserve': []}
    local = {}
    if phase == 'automatic':
        if not bindings.get('model'):
            raise ValueError('automatic production requires an explicit model binding')
        task = relative_file(fixture, manifest['task'])
        contract = relative_file(fixture.parent, 'OUTPUT_CONTRACTS.md')
        input_paths = [relative_file(fixture, name) for name in manifest['inputs']]
        read_roots.extend([task, workflow, contract, *input_paths])
        if version == 'v2':
            read_roots.append(relative_file(fixture, manifest['upgrade']))
            prior = absolute(bindings['prior_outputs_root'])
            previous = [relative_file(prior, name) for name in manifest['outputs']]
            read_roots.extend(previous)
            preparation['prior_outputs'] = [str(path) for path in previous]
        elif bindings.get('prior_outputs_root') is not None:
            raise ValueError('v1 starts from original inputs; do not invent prior business outputs or accepted A')
        goal = (f'Read the complete reviewed build document, task at {task}, output contract at {contract}, '
                f'and every declared original input: {json.dumps([str(path) for path in input_paths])}. '
                f'Load and follow the actual {version} workflow at {workflow}; its complete current text is:\n'
                + workflow_text + '\n'
                'Write only the declared business outputs under outputs/: ' + ', '.join(names) + '. '
                'Preserve original input identities and user customization. Use the declared Python for actual computation '
                'when the workflow requires it. Keep independent expectations and host review outside production. '
                'This phase accepts only automatic file/structured/numerical obligations; actual browser, semantic, '
                'and search observations are performed and fixed separately by the outer host. '
                'Do not invent search results, review records, runtime IDs, or acceptance.')
        if version == 'v2':
            goal += (' Read the actual prior v1 business outputs before upgrading: '
                     + json.dumps([str(path) for path in previous]) + '. '
                     'Apply the selected workflow upgrade to those actual prior decisions and content, '
                     'preserving original requirements and user customization. Expected fixtures are not prior outputs '
                     'and these input files do not themselves prove earlier acceptance.')
    else:
        prior = absolute(bindings['prior_outputs_root'])
        helpers = absolute(bindings['helpers_root'])
        apply_path = absolute(bindings['apply_manifest'])
        host = absolute(bindings['host_evidence_root'])
        review = json.loads(relative_file(host, 'review.json').read_text(encoding='utf-8'))
        if review['group'] != group or review['version'] != version:
            raise ValueError('host evidence does not match selected group and workflow')
        host_names = ['review.json', review['workflow_file'],
                      *[review['reviewed_outputs'] + '/' + name for name in names]]
        host_names.extend(ref for row in review['observations'] for ref in row.get('evidence_refs', []))
        verifier_inputs.extend({'source': str(relative_file(host, name)), 'path': 'host-evidence/' + name}
                               for name in dict.fromkeys(host_names))
        copied = [relative_file(prior, name) for name in names]
        apply_manifest = {'format_version': 1, 'files': [
            {'path': 'outputs/' + name, 'action': 'create', 'expected': {'missing': True},
             'desired': {'file': os.path.relpath(path, apply_path.parent),
                         'executable': bool(path.stat().st_mode & 0o111)}}
            for name, path in zip(names, copied)]}
        result = 'outputs/reuse-result.json'
        effects['allowed'].append(result)
        effects['required'].append(result)
        local = {'local_argv': ['python', '-I', '-B', str(relative_file(helpers, 'apply.py')),
                                '--manifest', str(apply_path), '--target', '.', '--result', result]}
        relative_file(helpers, 'file_states.py')
        read_roots.extend([*copied, helpers, apply_path])
        check_argv.extend(['--host-evidence', 'verifier://host-evidence/review.json'])
        preparation.update(apply_manifest_path=str(apply_path), apply_manifest=apply_manifest,
                           reuse_result=result,
                           advance_request={'advance_mode': 'ONE_ATTEMPT'})
        preparation['next'] = (
            'Prepare and review the actual scope, then complete advance_request with the current '
            'program_id, prepared_event_id and expected_revision. After the single attempt, read-build; '
            'do not advance fixed REUSE again to repair a host FAIL. Return the actual finding to the '
            'original producer through its existing repair entry, or to the original host for market-live. '
            'After repair, review the affected outputs and prepare fresh evidence and reviewed materials; '
            'retain the old records and actual consumption. Missing/stale evidence needs evidence repair, '
            'not product changes or producer replay.')
        goal = (f'Copy only the declared existing outputs from {prior} using the fixed ordinary-file apply manifest '
                f'{apply_path}. Do not rerun any model, computation, retrieval, browser, or other business producer. '
                'Independently compare the copied bytes with the protected host review and check this review contract. '
                'The reuse result is diagnostic. Earlier Program identity remains ordinary handoff context; '
                'this Program cannot recreate or inherit its approval, source capture, or acceptance identities.')
    if bindings.get('handoff_path') is not None:
        handoff = absolute(bindings['handoff_path'])
        if not handoff.is_file():
            raise ValueError('handoff_path must name an existing ordinary document')
        read_roots.append(handoff)
        preparation['handoff_path'] = str(handoff)
        goal += (f' Read ordinary handoff context at {handoff}. Its old Program references are context only; '
                 'use actual Generic returned identities for this Program, with no inherited approval or acceptance.')
    # Caller-provided runtime dependencies must not accidentally expose the
    # independent fixture/host inputs or overlap the new writable workspace.
    read_roots = list(dict.fromkeys(read_roots))
    hidden_inputs = [fixture / 'expected.json', fixture / 'counterexamples.json']
    if phase == 'reviewed':
        hidden_inputs.append(host)
    for path in [source, verifier, resources, *read_roots]:
        if path.is_relative_to(workspace) or workspace.is_relative_to(path):
            raise ValueError('fixed inputs, verifier and resources must be separate from the writable target')
    for path in read_roots:
        if verifier.is_relative_to(path) or path.is_relative_to(verifier):
            raise ValueError('implementation reads must not expose independent verifier inputs')
        if any(hidden.is_relative_to(path) or path.is_relative_to(hidden) for hidden in hidden_inputs):
            raise ValueError('implementation reads must not expose independent business expectations or host review')
    artifacts = [{'artifact_id': 'OUTPUT-' + str(index + 1), 'path': path} for index, path in enumerate(paths)]
    requirement = {'program_id': bindings['program_id'], 'revision': 1,
        'target': {'id': 'BUSINESS', 'mission': group + ' ' + version + ' ' + phase,
                   'scope': [goal], 'non_goals': ['Publication, inherited acceptance, or unperformed host observations']},
        'sources': [{'source_id': 'BUILD-DOCUMENT', 'path_or_uri': source.name, 'loaded_completely': True}],
        'atoms': [{'atom_id': 'BUSINESS', 'text_or_lossless_paraphrase': document,
                   'source_id': 'BUILD-DOCUMENT', 'source_locator': locator}],
        'acceptance_cases': [{'case_id': case, 'atom_ids': ['BUSINESS'],
            'description': ('Automatic file, structured and numerical obligations only.' if phase == 'automatic' else
                            'Declared reused output bytes and independently prepared host review obligations only.'),
            'acceptance_contract': {'source_id': 'BUILD-DOCUMENT', 'source_locator': locator}}], 'negative_cases': []}
    plan = {'schema_version': '1.2', 'plan_id': bindings['program_id'] + '-PLAN', 'revision': 1, 'requirement_revision': 1,
        'workpacks': [{'workpack_id': workpack, 'job_id': 'BUSINESS', 'executor': 'CODEX' if phase == 'automatic' else 'LOCAL',
            'goal': goal, 'depends_on': [], 'atom_ids': ['BUSINESS'], 'inputs': [{'kind': 'SOURCE', 'id': 'BUILD-DOCUMENT'}],
            'artifacts': artifacts, 'effects': effects, **local,
            'verification': [{'case_id': case, 'argv': check_argv,
                'artifact_ids': [row['artifact_id'] for row in artifacts], 'resource_profile_ref': 'business'}]}]}
    scope = {'workspace_root': str(workspace), 'verification_root': str(verifier),
        'source_read_roots': [str(path) for path in read_roots], 'task_write_roots': {workpack: ['outputs']},
        'executables': {'python': executable(bindings['python_executable'])},
        'codex_executable': executable(bindings['codex_executable']),
        'model': bindings['model'] if phase == 'automatic' else None, 'allow_model_service': phase == 'automatic',
        **{key: bindings[key] for key in ('max_attempts', 'max_task_attempts', 'command_timeout_seconds', 'expires_at')},
        'verification_resources': {'schema_version': '1.0', 'root': str(resources),
            'checker_files': [row['path'] for row in verifier_inputs],
            'profiles': {'business': {'writable_areas': ['scratch', 'report-staging'],
                'network': {'mode': 'NONE'}, 'services': [], 'result_protocol': 'STRUCTURED_V1',
                'required_checks': ['business-' + phase], 'report_files': ['summary.json'],
                'retention': {'success': 'REPORTS_ONLY', 'failure_days': 7}}}}}
    preparation['verifier_inputs'] = verifier_inputs
    return {'request': {'requirement_ir': requirement, 'plan': plan}, 'scope': scope,
            'source_manifest': [{'source_id': 'BUILD-DOCUMENT', 'path': source.name}], 'preparation': preparation}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group', choices=list(GROUPS), required=True)
    parser.add_argument('--version', choices=['v1', 'v2'], required=True)
    parser.add_argument('--phase', choices=['automatic', 'reviewed'], required=True)
    parser.add_argument('--bindings', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    materials = build_materials(args.group, args.version, args.phase, json.loads(args.bindings.read_text(encoding='utf-8')))
    with args.output.open('x', encoding='utf-8') as output:
        output.write(json.dumps(materials, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
