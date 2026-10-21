"""Build reviewable Generic materials without creating a Program or target.

CLI: mechanism_requests.py --kind doc --stage v2 --phase candidate
                          --bindings bindings.json --output materials.json
The output is authoring data. Real document review and returned event/revision
identities must be supplied later through the existing Generic entrypoints.
"""

import argparse
import json
from pathlib import Path


PRODUCT_FILES = {
    'doc': ['config.json', 'tools/render.py', 'data/notes.json', 'data/sources.json', 'USER_NOTES.md'],
    'api': ['config.json', 'tools/service.py', 'tools/client.py', 'data/items.json'],
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
    return str(path)  # Preserve the declared venv/receiver alias.


def build_materials(kind, stage, phase, bindings):
    if kind not in PRODUCT_FILES or stage not in ('v1', 'v2', 'v3', 'incremental'):
        raise ValueError('unsupported mechanism or stage')
    if phase not in ('candidate', 'apply') or kind == 'api' and stage == 'incremental':
        raise ValueError('unsupported mechanism phase')
    if stage == 'v1' and phase == 'apply':
        raise ValueError('v1 is a new assembly delivered in its candidate workspace; no empty apply is needed')
    source = absolute(bindings['requirement_path'])
    text = source.read_text(encoding='utf-8')
    if not text.strip():
        raise ValueError('build document must have content')
    locator = 'L1-L' + str(len(text.splitlines()))
    workspace = absolute(bindings['workspace_root'])
    current = absolute(bindings['current_root'])
    verifier = absolute(bindings['verification_root'])
    resources = absolute(bindings['resource_root'])
    read_roots = [current, *[absolute(value) for value in bindings['python_read_roots']]]
    product_files = PRODUCT_FILES[kind]
    for name in product_files:
        if not (current/name).is_file():
            raise ValueError('current input is missing: ' + name)
    mode = 'new-assembly' if stage == 'v1' else 'project-incremental' if stage == 'incremental' else 'component-upgrade'
    workpack = 'ASSEMBLE' if phase == 'candidate' else 'APPLY'
    case = kind.upper() + '-CONTRACT'
    source_id = 'BUILD-DOCUMENT'
    target = 'product' if phase == 'candidate' else '.'
    goal = (f'Read the complete reviewed build document. Deliver the {kind} {stage} {mode} '
            f'from current input {current}. Preserve unrelated user content and settings; '
            'reference fixtures are not accepted A and helper diagnostics are not acceptance. ')
    if phase == 'candidate':
        if stage in ('v1', 'incremental') and bindings.get('component_old_root') is not None:
            raise ValueError('new assembly and project-only incremental must not invent an old component G')
        if stage != 'incremental':
            new = absolute(bindings['component_new_root'])
            read_roots.append(new)
            goal += f'Use new component bytes N at {new}. '
        if mode == 'component-upgrade':
            old = absolute(bindings['component_old_root'])
            read_roots.append(old)
            goal += f'Compare actual old component bytes G at {old} with C and N; resolve semantic conflicts. '
        if not bindings.get('model'):
            raise ValueError('candidate construction requires an explicit model binding')
        goal += ('Write the complete runnable product under product/. Do not read reference candidates or '
                 'independent expectations. New assembly has no historical A; later actual acceptance is recorded externally.')
        paths = ['product/' + name for name in product_files]
        effects = {'allowed': paths, 'required': paths, 'must_preserve': []}
        local = {}
        write_roots = ['product']
    else:
        candidate = absolute(bindings['candidate_root'])
        manifest = absolute(bindings['apply_manifest'])
        helpers = absolute(bindings['helpers_root'])
        data = json.loads(manifest.read_text(encoding='utf-8'))
        if data.get('format_version') != 1 or not data.get('files'):
            raise ValueError('apply needs a fixed nonempty ordinary-file manifest')
        changed, required = [], []
        for row in data['files']:
            path = row['path']
            if path not in product_files:
                raise ValueError('apply path is outside this mechanism contract: ' + path)
            if row['action'] not in ('create', 'update', 'remove', 'leave-unmanaged'):
                raise ValueError('unsupported ordinary-file action')
            for side, root in (('expected', current), ('desired', candidate)):
                state = row[side]
                if state.get('missing') is True:
                    continue
                reference = Path(state['file'])
                payload = (manifest.parent/reference).resolve()
                if reference.is_absolute() or not payload.is_file() or not payload.is_relative_to(root):
                    raise ValueError(side + ' must read the explicitly fixed input root')
            if row['action'] != 'leave-unmanaged':
                changed.append(path)
                if row['desired'].get('missing') is not True:
                    required.append(path)
        result = 'outputs/apply-result.json'
        paths = required + [result]
        effects = {'allowed': changed + [result], 'required': paths,
                   'must_preserve': [name for name in product_files if name not in changed]}
        local = {'local_argv': ['python', '-I', '-B', str(helpers/'apply.py'), '--manifest', str(manifest),
                                '--target', '.', '--result', result]}
        read_roots.extend([candidate, manifest, helpers])
        write_roots = ['.']
        goal += f'Apply only the fixed manifest {manifest}; use desired bytes from {candidate}. '
        goal += 'Verify the actual target after application. The result JSON is diagnostic only.'
    read_roots = list(dict.fromkeys(read_roots))
    for path in [source, verifier, resources, *read_roots]:
        if path.is_relative_to(workspace) or workspace.is_relative_to(path):
            raise ValueError('fixed inputs, verifier and resources must be separate from the writable target')
    for path in read_roots:
        if verifier.is_relative_to(path) or path.is_relative_to(verifier):
            raise ValueError('implementation reads must not expose independent verifier inputs')
    artifact_rows = [{'artifact_id': 'FILE-' + str(index + 1), 'path': path} for index, path in enumerate(paths)]
    artifact_ids = [row['artifact_id'] for row in artifact_rows]
    checks = ['document-content'] if kind == 'doc' else ['api-contract', 'owned-service-cleanup']
    requirement = {'program_id': bindings['program_id'], 'revision': 1,
        'target': {'id': kind.upper() + '-HARNESS', 'mission': f'{kind} {stage}: {mode} and preserved user customizations',
                   'scope': [goal], 'non_goals': ['Real user project mutation, external services, publication, and claims of prior acceptance']},
        'sources': [{'source_id': source_id, 'path_or_uri': source.name, 'loaded_completely': True}],
        'atoms': [{'atom_id': 'MECHANISM', 'text_or_lossless_paraphrase': text,
                   'source_id': source_id, 'source_locator': locator}],
        'acceptance_cases': [{'case_id': case, 'atom_ids': ['MECHANISM'],
            'description': 'Check actual document/API behavior and preserved customizations against protected independent expectations.',
            'acceptance_contract': {'source_id': source_id, 'source_locator': locator}}], 'negative_cases': []}
    plan = {'schema_version': '1.2', 'plan_id': bindings['program_id'] + '-PLAN', 'revision': 1, 'requirement_revision': 1,
        'workpacks': [{'workpack_id': workpack, 'job_id': 'MECHANISM', 'executor': 'CODEX' if phase == 'candidate' else 'LOCAL',
            'goal': goal, 'depends_on': [], 'atom_ids': ['MECHANISM'], 'inputs': [{'kind': 'SOURCE', 'id': source_id}],
            'artifacts': artifact_rows, 'effects': effects, **local,
            'verification': [{'case_id': case, 'argv': ['python', '-I', '-B', 'verifier://check_mechanism_resource.py',
                '--kind', kind, '--stage', stage, '--target', target], 'artifact_ids': artifact_ids, 'resource_profile_ref': 'mechanism'}]}]}
    scope = {'workspace_root': str(workspace), 'verification_root': str(verifier),
        'source_read_roots': [str(path) for path in read_roots], 'task_write_roots': {workpack: write_roots},
        'executables': {'python': executable(bindings['python_executable'])},
        'codex_executable': executable(bindings['codex_executable']),
        'model': bindings['model'] if phase == 'candidate' else None, 'allow_model_service': phase == 'candidate',
        **{key: bindings[key] for key in ('max_attempts', 'max_task_attempts', 'command_timeout_seconds', 'expires_at')},
        'verification_resources': {'schema_version': '1.0', 'root': str(resources),
            'checker_files': ['check_mechanisms.py', f'expectations/{kind}-{stage}.json'],
            'profiles': {'mechanism': {'writable_areas': ['scratch', 'report-staging'],
                'network': {'mode': 'NONE'} if kind == 'doc' else {'mode': 'LOCAL_SERVICE', 'tcp': 'LOOPBACK'},
                'services': [], 'result_protocol': 'STRUCTURED_V1', 'required_checks': checks,
                'report_files': ['summary.json'], 'retention': {'success': 'REPORTS_ONLY', 'failure_days': 7}}}}}
    return {'request': {'requirement_ir': requirement, 'plan': plan}, 'scope': scope,
        'source_manifest': [{'source_id': source_id, 'path': source.name}],
        'preparation': {'status': 'MATERIALS_ONLY_NOT_APPROVED', 'source_root': str(source.parent),
            'kind': kind, 'stage': stage, 'phase': phase, 'route': mode,
            'runtime_identity': None, 'accepted_A': None,
            'next': 'Display the versioned build document; obtain real review, then use actual Generic returned IDs and scope readback.'}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=['doc', 'api'], required=True)
    parser.add_argument('--stage', choices=['v1', 'v2', 'v3', 'incremental'], required=True)
    parser.add_argument('--phase', choices=['candidate', 'apply'], required=True)
    parser.add_argument('--bindings', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build_materials(args.kind, args.stage, args.phase, json.loads(args.bindings.read_text(encoding='utf-8')))
    with args.output.open('x', encoding='utf-8') as output:
        output.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
