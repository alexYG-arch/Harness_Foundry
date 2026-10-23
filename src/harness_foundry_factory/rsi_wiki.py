"""Declared local knowledge lookup; no execution, acceptance or control state.

Content, applicability and validation scope are declarations. Byte checks bind
sources; they do not establish that a method works or grant tool authority.
"""
from copy import deepcopy
import hashlib
from pathlib import Path
import re
from .rsi_cases import read_json, require, write_case
from .rsi_review import digest


STATES = {'CANDIDATE', 'VERIFIED_SCOPED', 'SUPERSEDED', 'WITHDRAWN'}
KINDS = {'FACT', 'METHOD', 'CAPABILITY_REFERENCE', 'COUNTEREXAMPLE'}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _strings(value):
    return isinstance(value, list) and all(_text(x) for x in value)


def _local(root, name):
    require(_text(name), 'relative file path required')
    p = Path(name)
    require(not p.is_absolute() and '..' not in p.parts, 'path must stay within declared collection')
    resolved = (root / p).resolve()
    require(resolved.is_relative_to(root), 'path resolves outside declared collection')
    return resolved


def validate_entry(entry):
    require(isinstance(entry, dict), 'entry must be an object')
    for key in ('id', 'version', 'title', 'summary'):
        require(_text(entry.get(key)), 'entry ' + key + ' required')
    require(entry.get('state') in STATES, 'invalid declared state')
    require(entry.get('kind') in KINDS, 'invalid knowledge kind')
    for key in ('keywords', 'limits', 'pending_checks', 'capability_refs'):
        require(_strings(entry.get(key, [])), 'invalid ' + key)
    for field in ('conditions', 'excludes'):
        require(isinstance(entry.get(field, {}), dict), 'invalid ' + field)
        for key, values in entry.get(field, {}).items():
            require(_text(key) and _strings(values) and values, 'invalid condition values')
    sources = entry.get('sources', [])
    require(isinstance(sources, list), 'sources must be a list')
    for source in sources:
        require(isinstance(source, dict) and _text(source.get('path')), 'source path required')
        require(all(_text(source.get(k)) for k in ('version', 'evidence_kind')), 'source version/kind required')
        require(re.fullmatch(r'[a-f0-9]{64}', source.get('sha256', '')) is not None, 'source digest required')
    if entry['state'] == 'VERIFIED_SCOPED':
        require(_text(entry.get('validation_scope')), 'verified declaration requires explicit scope')
    return deepcopy(entry)


def propose(entry, output):
    """Save a new candidate; never auto-promote or overwrite an old version."""
    candidate = deepcopy(entry)
    candidate['state'] = 'CANDIDATE'
    write_case(validate_entry(candidate), output)


def _sources(root, sources):
    rows = []
    for source in sources:
        row = deepcopy(source)
        try:
            actual = hashlib.sha256(_local(root, source['path']).read_bytes()).hexdigest()
            row['observed_sha256'] = actual
            row['binding'] = 'MATCH' if actual == source['sha256'] else 'CHANGED'
        except (OSError, ValueError):
            row['binding'] = 'UNAVAILABLE'
        rows.append(row)
    return rows


def _terms(text):
    # Modest deterministic keyword lookup; Chinese bigrams avoid requiring spaces.
    text = text.casefold()
    words = re.findall(r'[a-z0-9_]+', text)
    for phrase in re.findall(r'[\u3400-\u9fff]+', text):
        words.extend(phrase[i:i+2] for i in range(max(1, len(phrase)-1)))
    return set(words)


def _condition_priority(entry, conditions):
    # Rank declared compatibility, not proof of validity; retain every match.
    required = entry.get('conditions', {})
    if (any(key in conditions and conditions[key] not in values for key, values in required.items())
            or any(conditions.get(key) in values for key, values in entry.get('excludes', {}).items())):
        return 2
    if any(key not in conditions for key in required):
        return 1
    return 0


def query(config, config_root, question, conditions, limit=5):
    require(_text(question), 'question required')
    require(isinstance(conditions, dict) and all(_text(k) and _text(v) for k,v in conditions.items()), 'text conditions required')
    require(isinstance(limit, int) and not isinstance(limit, bool) and limit > 0, 'positive result limit required')
    require(isinstance(config, dict) and isinstance(config.get('collections'), list), 'declared collections required')
    base = Path(config_root).resolve(strict=True)
    matches, diagnostics, seen = [], [], set()
    for binding in config['collections']:
        require(isinstance(binding, dict) and all(_text(binding.get(k)) for k in ('id','path','version')), 'collection identity/path/version required')
        cid = binding['id']
        require(cid not in seen, 'duplicate collection id')
        seen.add(cid)
        require(binding.get('visibility') in {'PUBLIC','PROJECT'}, 'collection visibility required')
        # The configured collection itself may be elsewhere (project-private).
        root = (base / binding['path']).resolve()
        try:
            catalog = read_json((root / 'collection.json').read_text())
            require(isinstance(catalog, dict) and isinstance(catalog.get('entries'), list), 'invalid collection')
            require(catalog.get('version') == binding['version'], 'collection version mismatch')
            require(_strings(catalog['entries']) and len(set(catalog['entries'])) == len(catalog['entries']), 'invalid or duplicate entry paths')
            updates = catalog.get('updates', [])
            require(_strings(updates), 'invalid update paths')
        except (OSError, ValueError, TypeError) as error:
            diagnostics.append({'collection': cid, 'limitation': str(error)})
            continue
        lifecycle, update_errors = [], []
        for name in updates:
            try:
                item = read_json(_local(root, name).read_text())
                require(isinstance(item, dict) and item.get('state') in {'WITHDRAWN','SUPERSEDED'}, 'invalid lifecycle state')
                require(all(_text(item.get(k)) for k in ('entry_id','entry_version','entry_sha256','reason')), 'lifecycle target and reason required')
                validate_entry({'id':'update', 'version':'1', 'title':'update', 'summary':'update', 'state':'CANDIDATE', 'kind':'FACT', 'sources':item.get('sources',[])})
                require(item.get('sources'), 'counterevidence source required')
                lifecycle.append({**item, 'update_sha256': digest(item), 'source_bindings': _sources(root, item['sources'])})
            except (OSError, ValueError, TypeError) as error:
                update_errors.append(str(error))
        diagnostics.extend({"collection": cid, "limitation": "LIFECYCLE_UNRESOLVED: " + error}
                           for error in update_errors)
        identities = set()
        for name in catalog['entries']:
            try:
                raw = _local(root, name).read_bytes()
                entry = validate_entry(read_json(raw.decode('utf-8')))
                identity = (entry['id'], entry['version'])
                require(identity not in identities, 'duplicate entry identity')
                identities.add(identity)
                sha = hashlib.sha256(raw).hexdigest()
            except (OSError, ValueError, TypeError) as error:
                diagnostics.append({'collection': cid, 'entry': name, 'limitation': str(error)})
                continue
            score = len(_terms(question) & _terms(' '.join([entry['title'],entry['summary'],*entry.get('keywords',[])])))
            if not score:
                continue
            limits = list(entry.get('limits', []))
            sources = _sources(root, entry.get('sources', []))
            if not sources:
                limits.append('NO_SOURCES')
            limits.extend('SOURCE_' + s['binding'] + ': ' + s['path'] for s in sources if s['binding'] != 'MATCH')
            for key, values in entry.get('conditions', {}).items():
                if conditions.get(key) not in values:
                    limits.append(('CONDITION_UNKNOWN: ' if key not in conditions else 'CONDITION_MISMATCH: ') + key)
            for key, values in entry.get('excludes', {}).items():
                if conditions.get(key) in values:
                    limits.append('EXCLUDED: ' + key)
            limits.extend('PENDING_CHECK: ' + p for p in entry.get('pending_checks', []))
            limits.extend('LIFECYCLE_UNRESOLVED: ' + e for e in update_errors)
            related = [u for u in lifecycle if u['entry_id'] == entry['id'] and u['entry_version'] == entry['version']]
            valid = [u for u in related if u['entry_sha256'] == sha]
            if len(valid) != len(related):
                limits.append('LIFECYCLE_TARGET_CHANGED')
            states = {u['state'] for u in valid} | {entry['state']}
            state = 'WITHDRAWN' if 'WITHDRAWN' in states else 'SUPERSEDED' if 'SUPERSEDED' in states else entry['state']
            for u in valid:
                if any(s['binding'] != 'MATCH' for s in u['source_bindings']):
                    limits.append('COUNTEREVIDENCE_UNAVAILABLE_OR_CHANGED')
            if state != 'VERIFIED_SCOPED':
                limits.append('DECLARED_STATE: ' + state)
            if entry['kind'] == 'COUNTEREXAMPLE':
                limits.append('COUNTEREXAMPLE_NOT_SUCCESS_METHOD')
            matches.append({'collection': cid, 'collection_version': binding['version'], 'visibility': binding['visibility'],
                'entry_path': name, 'entry_sha256': sha, 'entry': entry, 'sources': sources,
                'current_declared_state': state, 'lifecycle': valid, 'limits': limits, 'score': score,
                'independently_verified': False})
    matches.sort(key=lambda row: (_condition_priority(row['entry'], conditions),
                                  -row['score'], row['collection'], row['entry']['id'],row['entry']['version']))
    return {'schema_version':'RSI_WIKI_QUERY_V1', 'question':question, 'conditions':deepcopy(conditions),
        'config_sha256':digest(config), 'matches':matches[:limit], 'matched_total':len(matches), 'diagnostics':diagnostics,
        'commands_executed':False, 'budget_modified':False, 'acceptance_verified':False,
        'no_match_blocks_task':False, 'limitations':['Declared sources and scope are not independent proof; references do not authorize tools.']}


def record_decision(result, decisions, output):
    """Freeze what was read and why; later queries never rebind this receipt."""
    require(isinstance(result, dict) and result.get('schema_version') == 'RSI_WIKI_QUERY_V1', 'query report required')
    require(isinstance(decisions, list), 'decisions must be a list')
    rows, seen = [], set()
    for decision in decisions:
        require(isinstance(decision, dict) and _text(decision.get('reason')), 'decision reason required')
        key = (decision.get('collection'),decision.get('id'),decision.get('version'),decision.get('sha256'))
        require(key not in seen, 'duplicate decision')
        seen.add(key)
        choices = [r for r in result['matches'] if (r['collection'],r['entry']['id'],r['entry']['version'],r['entry_sha256']) == key]
        require(len(choices) == 1, 'decision must bind one returned entry version')
        require(decision.get('action') in {'ADOPT','NOT_ADOPT'}, 'invalid decision action')
        rows.append({'decision':deepcopy(decision), 'read_snapshot':deepcopy(choices[0])})
    write_case({'schema_version':'RSI_WIKI_DECISION_V1','query_sha256':digest(result),
        'question':result['question'], 'conditions':result['conditions'], 'decisions':rows,
        'decision_verified':False, 'tool_authorization_granted':False, 'budget_modified':False}, output)
