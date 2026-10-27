"""Optional report reconstruction over explicit immutable files, not control state.

Reported outcomes remain declarations. Bindings establish byte identity, never
semantic acceptance, authority, retry eligibility or budget consumption.
"""
from copy import deepcopy
import base64
import hashlib
from pathlib import Path
import re
from .build_types import canonical_json
from .rsi_cases import STATUSES, read_json, require
from .rsi_wiki import _local


def text(value):
    return isinstance(value, str) and bool(value.strip())


def strings(value):
    return isinstance(value, list) and all(text(x) for x in value)


def binding(value):
    require(isinstance(value, dict) and text(value.get('path')) and text(value.get('version')),
            'file path and declared version required')
    require(isinstance(value.get('sha256'), str)
            and re.fullmatch('[a-f0-9]{64}', value['sha256']), 'file digest required')
    return deepcopy(value)


def observe(root, reference, *, document=False):
    row = {'reference': binding(reference)}
    try:
        path = _local(root, reference['path'])
        with path.open('rb') as stream:
            if document:
                raw = stream.read()
                actual = hashlib.sha256(raw).hexdigest()
            else:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        row.update(observed_sha256=actual, binding='MATCH' if actual == reference['sha256'] else 'CHANGED')
        if document and row['binding'] == 'MATCH':
            doc = read_json(raw.decode('utf-8'))
            require(isinstance(doc, dict), 'report input must be an object')
            require(doc.get('version') == reference['version'], 'document version differs from binding')
            return row, doc
    except (OSError, ValueError, UnicodeError) as exc:
        row.update(binding='UNAVAILABLE', diagnostic=type(exc).__name__)
    return row, None


def validate_item(item):
    require(isinstance(item, dict) and text(item.get('id')) and text(item.get('condition')),
            'item id and complete condition required')
    require(item.get('reported_status') in STATUSES, 'explicit reported status required')
    for key in ('facts', 'interpretations', 'limits', 'pending_checks', 'depends_on', 'contradictions'):
        require(strings(item.get(key, [])), 'invalid item ' + key)
    require(isinstance(item.get('conditions', {}), dict), 'conditions must be an object')
    require(all(text(k) and text(v) for k, v in item.get('conditions', {}).items()), 'text conditions required')
    require(isinstance(item.get('source_refs', []), list), 'source_refs must be a list')
    for ref in item.get('source_refs', []):
        binding(ref)
    return deepcopy(item)


def reconstruct(request, root):
    """Rebuild all known conditions, keeping gaps and original outcome values."""
    require(isinstance(request, dict) and request.get('schema_version') == 'REPORT_HANDOFF_V1',
            'REPORT_HANDOFF_V1 required')
    require(text(request.get('report_id')), 'report_id required')
    require(isinstance(request.get('deltas', []), list), 'ordered deltas required')
    root = Path(root).resolve(strict=True)
    refs = [request['baseline'], *request.get('deltas', [])]
    require(len({(r['path'], r['sha256']) for r in refs}) == len(refs), 'duplicate baseline/delta reference')
    items, original, provenance, pending = {}, {}, {}, {}
    inputs, gaps = [], []
    original_total = None
    for index, ref in enumerate(refs):
        observed, doc = observe(root, ref, document=True)
        inputs.append(observed)
        if doc is None:
            gaps.append({'index': index, **observed})
            continue
        if index == 0:
            require(doc.get('schema_version') == 'REPORT_BASELINE_V1', 'baseline format required')
            rows = doc.get('items')
        else:
            require(doc.get('schema_version') == 'REPORT_DELTA_V1', 'delta format required')
            require(text(doc.get('reason')), 'delta change/impact explanation required')
            affected = doc.get('affected_ids', [])
            require(strings(affected) and len(affected) == len(set(affected)), 'unique affected ids required')
            for ident in affected:
                require(ident in items or gaps, 'unknown affected item')
                pending[ident] = {'reason': doc['reason'], 'reference': deepcopy(ref)}
            rows = doc.get('updates')
        require(isinstance(rows, list), 'baseline items or delta updates required')
        seen = set()
        for pos, supplied in enumerate(rows):
            item = validate_item(supplied)
            ident = item['id']
            require(ident not in seen, 'duplicate item in one input')
            seen.add(ident)
            items[ident] = item
            provenance[ident] = {'reference': deepcopy(ref),
                                'pointer': '/' + ('items' if index == 0 else 'updates') + '/' + str(pos)}
            # An explicit replacement supplies the new observation, not proof of
            # its truth. Old affected items with no replacement stay pending.
            pending.pop(ident, None)
            if index == 0:
                original[ident] = {key: deepcopy(item.get(key, {} if key == 'conditions' else []))
                                   for key in ('condition', 'conditions', 'limits')}
        if index == 0:
            original_total = len(rows)

    acceptance = request.get('baseline_acceptance_ref')
    acceptance_check = observe(root, acceptance)[0] if acceptance else None
    evidence_cache, result = {}, {}
    for ident, item in items.items():
        checks, reasons = [], []
        for ref in item.get('source_refs', []):
            key = canonical_json(ref)
            if key not in evidence_cache:
                evidence_cache[key] = observe(root, ref)[0]
            checks.append(evidence_cache[key])
        if gaps:
            reasons.append('INCOMPLETE_HISTORY')
        if acceptance_check and acceptance_check['binding'] != 'MATCH':
            reasons.append('BASELINE_ACCEPTANCE_UNRESOLVED')
        if ident in pending:
            reasons.append('AFFECTED_WITHOUT_NEW_OBSERVATION')
        if ident in original and any(item.get(key, {} if key == 'conditions' else []) != value
                                     for key, value in original[ident].items()):
            reasons.append('BASELINE_CONDITIONS_CHANGED')
        if not checks:
            reasons.append('NO_BOUND_EVIDENCE')
        if any(row['binding'] != 'MATCH' for row in checks):
            reasons.append('SOURCE_BINDING_UNRESOLVED')
        if item.get('pending_checks'):
            reasons.append('PENDING_CHECKS')
        if item.get('contradictions'):
            reasons.append('DECLARED_CONTRADICTION')
        if item['reported_status'] not in {'PASS', 'ACCEPTED'}:
            reasons.append('REPORTED_RESULT_NOT_PASS')
        result[ident] = {'item': item, 'original_condition': original.get(ident, {}).get('condition'),
                         'original_context': deepcopy(original.get(ident)),
                         'provenance': provenance[ident], 'source_checks': deepcopy(checks),
                         'review_reasons': reasons, 'pending_impact': deepcopy(pending.get(ident)),
                         'independently_verified': False}

    # Dependencies retain incomplete old work even when no current file changed.
    # A cycle is an unresolved dependency, not authority to schedule anything.
    def dependency_issues(ident, trail):
        problems = set()
        for dep in items[ident].get('depends_on', []):
            if dep not in result:
                problems.add('MISSING_DEPENDENCY:' + dep)
            elif dep in trail:
                problems.add('CYCLIC_DEPENDENCY:' + dep)
            else:
                if result[dep]['review_reasons']:
                    problems.add('UNRESOLVED_DEPENDENCY:' + dep)
                problems.update(dependency_issues(dep, trail | {dep}))
        return problems
    extra = {ident: sorted(dependency_issues(ident, {ident})) for ident in items}
    for ident, row in result.items():
        row['review_reasons'].extend(extra[ident])
        row['reuse_assessment'] = 'REVIEW_REQUIRED' if row['review_reasons'] else 'SCOPED_REUSE_CANDIDATE'
    view = {'schema_version': 'REPORT_VIEW_V1', 'report_id': request['report_id'],
            'original_total': original_total, 'total': len(items), 'items': list(result.values()),
            'inputs': inputs, 'history_gaps': gaps, 'baseline_acceptance': acceptance_check,
            'unresolved_impacts': {k: v for k, v in pending.items() if k not in items},
            'reconstruction': 'PARTIAL' if gaps else 'COMPLETE',
            'acceptance_verified': False, 'budget_modified': False, 'commands_executed': False}
    # Bind continuations to the actual view, including newly unavailable evidence.
    view['view_id'] = hashlib.sha256(canonical_json(view).encode()).hexdigest()
    return view


_UNSET = object()


def query(view, *, offset=0, limit=20, item_id=None, conditions=None, field=None,
          value=_UNSET, source=None, details=False, view_id=None):
    require(type(offset) is int and offset >= 0 and type(limit) is int and limit > 0,
            'nonnegative offset and positive caller-selected limit required')
    conditions = conditions or {}
    require(isinstance(conditions, dict), 'query conditions must be an object')
    require(field is None or text(field), 'field name required')
    rows = []
    for row in view['items']:
        item = row['item']
        if item_id is not None and item['id'] != item_id:
            continue
        if any(item.get('conditions', {}).get(k) != v for k, v in conditions.items()):
            continue
        if field is not None and (field not in item or (value is not _UNSET and canonical_json(item[field]) != canonical_json(value))):
            continue
        if source is not None and not any(r['path'] == source for r in item.get('source_refs', [])):
            continue
        rows.append(row)
    valid = view_id is None or view_id == view['view_id']
    page = rows[offset:offset + limit] if valid else []
    more = offset + len(page) < len(rows)
    if not details:
        page = [{**{k: deepcopy(v) for k, v in row.items() if k != 'item'},
                 'item': {k: deepcopy(row['item'][k]) for k in
                          ('id', 'condition', 'reported_status', 'conditions', 'limits', 'pending_checks',
                           'contradictions', 'depends_on') if k in row['item']},
                 'omitted_fields': sorted(set(row['item']) - {'id', 'condition', 'reported_status',
                    'conditions', 'limits', 'pending_checks', 'contradictions', 'depends_on'})} for row in page]
    return {**{k: deepcopy(v) for k, v in view.items() if k != 'items'}, 'items': page,
            'matches': len(rows), 'offset': offset, 'limit': limit, 'details': details,
            'continuation_valid': valid, 'next_offset': offset + len(page) if valid and more else None,
            'selection_complete': valid and not more,
            'all_items_returned': valid and offset == 0 and len(page) == view['total'],
            'diagnostic': None if valid else 'VIEW_CHANGED_RESTART_QUERY'}


def read_source(root, reference, *, offset=0, length=65536):
    """Return an explicitly selected byte range, preserving UTF-8/binary bytes."""
    require(type(offset) is int and offset >= 0 and type(length) is int and length > 0,
            'nonnegative byte offset and positive length required')
    root = Path(root).resolve(strict=True)
    row = {'reference': binding(reference), 'offset': offset, 'length': length,
           'acceptance_verified': False, 'commands_executed': False}
    try:
        path = _local(root, reference['path'])
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            size = stream.tell()
            if actual != reference['sha256']:
                return {**row, 'binding': 'CHANGED', 'observed_sha256': actual}
            stream.seek(min(offset, size)); raw = stream.read(length)
            # Verify the same opened source stayed bound during the ranged read.
            stream.seek(0)
            require(hashlib.file_digest(stream, 'sha256').hexdigest() == actual, 'source changed during read')
        try:
            content = raw.decode('utf-8')
        except UnicodeDecodeError:
            content = None
        end = min(offset, size) + len(raw)
        return {**row, 'binding': 'MATCH', 'size': size, 'text': content,
                'bytes_base64': base64.b64encode(raw).decode('ascii'),
                'next_offset': end if end < size else None, 'eof': end == size,
                'complete_read': offset == 0 and end == size}
    except (OSError, ValueError) as exc:
        return {**row, 'binding': 'UNAVAILABLE', 'diagnostic': type(exc).__name__}
