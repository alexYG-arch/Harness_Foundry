"""Optional, offline candidate/adoption handoff. Never apply, dispatch or accept."""
from copy import deepcopy
import hashlib
from pathlib import Path, PurePosixPath

from .build_types import canonical_json
from .rsi_cases import OWNERS, read_json, require


def digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def snapshot(root, files, version):
    """Bind only explicitly selected files, including executable and absent states."""
    require(isinstance(version, str) and bool(version.strip()), 'version required')
    require(isinstance(files, list) and bool(files), 'explicit nonempty files required')
    root = Path(root)
    rows = {}
    for name in files:
        require(isinstance(name, str), 'file path must be text')
        p = PurePosixPath(name)
        require(not p.is_absolute() and '..' not in p.parts and p.as_posix() == name
                and name != '.' and '\\' not in name and name not in rows, 'invalid or duplicate file path')
        path = root / name
        try:
            raw = path.read_bytes()
            rows[name] = {'sha256': hashlib.sha256(raw).hexdigest(),
                          'executable': bool(path.stat().st_mode & 0o111)}
        except FileNotFoundError:
            # A broken link is not the same as a deliberate absent file.
            require(not path.is_symlink(), 'unreadable declared link')
            rows[name] = {'missing': True}
    return {'schema_version': 'RSI_ARTIFACT_V1', 'version': version, 'files': rows,
            'content_sha256': digest(rows)}


def _read_binding(binding, root):
    require(isinstance(binding, dict), 'binding must be an object')
    require(isinstance(binding.get('path'), str) and binding['path'], 'binding path required')
    require(isinstance(binding.get('sha256'), str) and len(binding['sha256']) == 64, 'binding digest required')
    raw = (root / binding['path']).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == binding['sha256'], 'bound file changed')
    return read_json(raw.decode('utf-8'))


def report_adoption(manifest, material_root):
    """Associate original records without promoting host claims to verified results.

    Missing/changed evidence yields local gaps; other records and the requested
    decision survive. No workflow is gated and historical consumption is copied,
    never summed or interpreted as authority.
    """
    require(isinstance(manifest, dict), 'manifest must be an object')
    require(manifest.get('owner') in OWNERS, 'maintenance owner required')
    decision = manifest.get('decision', {})
    require(isinstance(decision, dict) and decision.get('action') in {'RETAIN', 'REJECT', 'ROLLBACK', 'DEFER'}
            and isinstance(decision.get('reason'), str) and bool(decision['reason'].strip()), 'declared decision and reason required')
    root = Path(material_root)
    result = {'schema_version': 'RSI_ADOPTION_REPORT_V1', 'manifest': deepcopy(manifest),
              'artifacts': {}, 'evidence': [], 'gaps': [], 'commands_executed': False,
              'budget_modified': False, 'acceptance_verified': False, 'decision_verified': False,
              'benefit_verified': False, 'deployment_modified': False}
    artifacts = manifest.get('artifacts', {})
    require(isinstance(artifacts, dict), 'artifacts must be an object')
    for name, binding in artifacts.items():
        row = {'binding': deepcopy(binding), 'state': 'UNAVAILABLE'}
        result['artifacts'][name] = row
        try:
            saved = _read_binding(binding, root)
            row['snapshot'] = saved
            require(saved.get('schema_version') == 'RSI_ARTIFACT_V1' and
                    saved.get('content_sha256') == digest(saved.get('files')), 'invalid artifact snapshot')
            actual = snapshot(root / binding['root'], list(saved['files']), saved['version'])
            row['current'] = actual
            row['state'] = 'MATCH' if saved == actual else 'CHANGED'
            if row['state'] != 'MATCH':
                result['gaps'].append(name + ': final files changed since snapshot')
        except (OSError, ValueError, KeyError, TypeError) as error:
            row['reason'] = str(error)
            result['gaps'].append(name + ': ' + str(error))
    evidence = manifest.get('evidence', [])
    require(isinstance(evidence, list), 'evidence must be a list')
    seen = set()
    for item in evidence:
        require(isinstance(item, dict) and isinstance(item.get('id'), str) and item['id']
                and item['id'] not in seen, 'unique evidence id required')
        seen.add(item['id'])
        row = {'binding': deepcopy(item), 'state': 'UNAVAILABLE'}
        result['evidence'].append(row)
        try:
            row['record'] = _read_binding(item, root)
            subject = item.get('subject')
            if subject is not None:
                artifact = result['artifacts'].get(subject, {})
                require(artifact.get('state') == 'MATCH', 'evidence subject unavailable or changed')
                require(item.get('subject_sha256') == artifact['snapshot']['content_sha256'],
                        'evidence refers to another artifact version')
            row['state'] = 'BOUND'
        except (OSError, ValueError, KeyError, TypeError) as error:
            row['reason'] = str(error)
            result['gaps'].append(item['id'] + ': ' + str(error))
    selected = decision.get('selected')
    if decision['action'] in {'RETAIN', 'ROLLBACK'}:
        if result['artifacts'].get(selected, {}).get('state') != 'MATCH':
            result['gaps'].append('selected artifact not bound to current files')
        checks = [r for r in result['evidence'] if r['state'] == 'BOUND'
                  and r['binding'].get('subject') == selected
                  and r['binding'].get('role') in {'REGRESSION', 'INDEPENDENT_CHECK'}]
        if not checks:
            result['gaps'].append('selected artifact has no bound behavior check; decision remains a declaration')
    result['association_status'] = 'EVIDENCE_GAPS' if result['gaps'] else 'RECORDED'
    result['limitations'] = [
        'Only declared files are bound; completeness and semantic relevance require host review.',
        'Bound reports may contain FAIL, SKIP or UNKNOWN; binding does not mean PASS.',
        'Development GREEN, regression, independent acceptance and measured benefits remain separate.',
        'Owner, scope, comparison, adoption stages and historical budgets are host declarations.',
        'No automatic merge, rollback, deployment, new budget or mandatory evidence gate.']
    return result
