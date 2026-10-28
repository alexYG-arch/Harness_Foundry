"""Stable preparation decisions. No approval, dispatch, installation or accounting."""
from copy import deepcopy
import hashlib
import json

CATEGORIES = frozenset('MODE_SELECTION MAINTENANCE_MODEL VERSION_ADOPTION ON_DEMAND_AMBIGUITY DELIVERY_FORM FOUNDRY_GUARANTEE_CONFLICT CAPABILITY_CONFLICT PROJECT_CONFLICT ENVIRONMENT_CONFLICT DATA_AND_COMPLIANCE POST_DELIVERY_OWNERSHIP REMOVAL_IMPACT SCOPE_EXPANSION CONTRACT_CHANGE IRREVERSIBLE_RISK UNRESOLVED_EFFECT ACCEPTANCE_JUDGMENT'.split())
TAGS = frozenset('BYPASSES_FOUNDRY_CONTROL CALLS_MODEL_SERVICE PERSISTENT_PROCESS NETWORK_ACCESS TELEMETRY CREDENTIALS_REQUIRED SENSITIVE_DATA LICENSE_OBLIGATION IRREVERSIBLE_EFFECT WRITES_ENVIRONMENT_CONFIG WRITES_OUTSIDE_WORKSPACE WRITES_PROJECT_FILES GLOBAL_STATE AUTO_UPDATE EXTERNAL_BINARY PLATFORM_SPECIFIC INTERACTIVE_ONLY TRIGGER_OVERLAP REQUIRES_HOST_TOOL'.split())
FORMS = frozenset('AS_IS BRIDGED REPLACED_BY_FOUNDRY POST_DELIVERY EXCLUDED BUILD_ONLY'.split())


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def request(subject, *, descriptor_sha256, mode, requirements, dependencies, condition, source_identity=None):
    """The host supplies a concrete unresolved condition, not just a package tag."""
    if condition['category'] not in CATEGORIES:
        raise ValueError('unknown decision category')
    options = condition['options']
    ids = [o['id'] for o in options]
    if not ids or len(ids) != len(set(ids)) or not condition.get('question') or not condition.get('evidence'):
        raise ValueError('decision requires a question, evidence and unique options')
    context = {'subject': subject, 'descriptor_sha256': descriptor_sha256, 'mode': mode,
               'requirements': requirements, 'dependencies': dependencies,
               'condition': {k: deepcopy(condition[k]) for k in ('category', 'question', 'options', 'evidence')}}
    if source_identity is not None:
        context['source_identity'] = deepcopy(source_identity)
    identity = {'descriptor_sha256': descriptor_sha256, 'decision_context_sha256': digest(context)}
    result = {'request_id': 'DR-' + identity['decision_context_sha256'][:24], 'subject': deepcopy(subject),
            **{k: deepcopy(condition[k]) for k in ('category', 'question', 'options', 'evidence')},
            'blocking': True, 'context_identity': identity}
    if source_identity is not None:
        result['source_identity'] = deepcopy(source_identity)
    return result


def resolve(req, records):
    matches = [r for r in records if req['request_id'] in r.get('request_ids', [])]
    if not matches:
        # A record with the same explicit subject can explain a stale decision.
        stale = any(r.get('subject') == req['subject'] for r in records)
        return None, 'DECISION_STALE' if stale else 'DECISION_REQUIRED'
    if len(matches) != 1:
        raise ValueError('decision request has multiple records')
    row = matches[0]
    identity = row.get('context_identities', {}).get(req['request_id'], row.get('context_identity'))
    if identity != req['context_identity']:
        return None, 'DECISION_STALE'
    message = row.get('message_ref', {})
    if (not row.get('decision_id') or row.get('decided_by', {}).get('role') != 'USER'
            or not message.get('chat_thread_id') or not message.get('turn_id')
            or row.get('choice') not in {o['id'] for o in req['options']}):
        return None, 'DECISION_REQUIRED'
    return row, None
