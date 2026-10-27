#!/usr/bin/env python3
"""Prepare a verified offline conversion, never adopt or rewrite a live controller.

This developer tool is deliberately absent from the generic runtime ZIP. It
preserves event identities, literal requests, and ordered idempotent results.
External evidence stays at its original paths; no business command is replayed.
"""
import argparse
from contextlib import closing
import hashlib
from itertools import zip_longest
import json
import os
from pathlib import Path
import runpy
import shutil
import sqlite3
import stat
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'src/harness_foundry_factory/python_startup.py'))['require_supported_python'](launcher=__file__)
from harness_foundry_factory.revision_store import RevisionControlEventStore as Store
from harness_foundry_factory.revision_bodies import COMPACT, INLINE, encode_payload, hydrate_payload, store_bodies
from harness_foundry_factory.build_types import canonical_json, RequestValidationError


def require(condition, message):
    if not condition:
        raise RequestValidationError(message)


def readonly(path):
    c = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    return c


def check_tables(c, store):
    expected = {'control_events', 'control_idempotency', 'sqlite_sequence'}
    if store.physical_format == COMPACT:
        expected.add('control_source_bodies')
    names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    require(names == expected, 'conversion does not discard unknown tables; preserve this database for review')


def backup_database(source, destination, *, timeout=900):
    """SQLite backup includes committed WAL pages; no immutable=1 or file copy."""
    source, destination = Path(source).resolve(strict=True), Path(destination)
    require(not destination.exists(), 'snapshot destination already exists')
    Store(source, read_only=True)  # Reject legacy authoring state before any output.
    started = time.monotonic()
    def progress(status, remaining, total):
        if time.monotonic() - started > timeout:
            raise TimeoutError('snapshot time budget exhausted; partial output is not usable')
    with closing(readonly(source)) as src:
        page_bytes = src.execute('PRAGMA page_count').fetchone()[0] * src.execute('PRAGMA page_size').fetchone()[0]
        require(shutil.disk_usage(destination.parent).free >= page_bytes,
                'insufficient free space even for the consistent snapshot')
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst, pages=256, progress=progress, sleep=0.05)
    return destination


def request_value(store, c, raw):
    request = json.loads(raw)
    if store.physical_format == COMPACT:
        for entry in request['entries']:
            hydrate_payload(c, entry['payload'], canonical_json(entry.pop('source_refs')))
    return request


def converted_request(c, request, target_format):
    if target_format == COMPACT:
        for entry in request['entries']:
            payload, refs, bodies = encode_payload(entry['event_type'], entry['payload'])
            store_bodies(c, bodies)
            entry['payload'], entry['source_refs'] = payload, refs
    return canonical_json(request)


def event_rows(c):
    return c.execute('SELECT * FROM control_events ORDER BY sequence')


def request_rows(c):
    return c.execute('SELECT * FROM control_idempotency ORDER BY program_id, idempotency_key')


def compare_databases(left, right):
    """Bounded-memory comparison of full values, not only hashes or counts."""
    a, b = Store(left, read_only=True), Store(right, read_only=True)
    events = requests = 0
    programs = {}
    with closing(readonly(left)) as x, closing(readonly(right)) as y:
        x.execute('BEGIN'); y.execute('BEGIN')
        for old, new in zip_longest(event_rows(x), event_rows(y)):
            require(old is not None and new is not None, 'event count differs')
            av, bv = a._decode_event(old, connection=x), b._decode_event(new, connection=y)
            require(old['sequence'] == new['sequence'] and canonical_json(av) == canonical_json(bv),
                    'event identity or complete payload differs')
            program = av['program_id']
            require(av['stream_revision'] == programs.get(program, 0) + 1, 'source revision gap')
            programs[program] = av['stream_revision']; events += 1
        for old, new in zip_longest(request_rows(x), request_rows(y)):
            require(old is not None and new is not None, 'idempotency count differs')
            require(all(old[k] == new[k] for k in ('program_id', 'idempotency_key', 'created_at')),
                    'idempotency identity differs')
            require(canonical_json(request_value(a, x, old['request_json'])) ==
                    canonical_json(request_value(b, y, new['request_json'])), 'literal request differs')
            av = a._replay_events(x, old['program_id'], old['events_json'])
            bv = b._replay_events(y, new['program_id'], new['events_json'])
            require(canonical_json(av) == canonical_json(bv), 'ordered original result differs')
            requests += 1
    return {'events': events, 'idempotency_records': requests, 'revisions': programs,
            'comparison': 'FULL_VALUES_TYPES_ORDER_AND_IDENTITIES'}


def convert_snapshot(snapshot, destination, target_format):
    require(target_format in (INLINE, COMPACT), 'unsupported target format')
    require(not Path(destination).exists(), 'candidate destination already exists')
    source = Store(snapshot, read_only=True)
    with closing(readonly(snapshot)) as src:
        src.execute('BEGIN')
        check_tables(src, source)
        target = Store(destination, physical_format=target_format)
        with target._connection() as dst:
            dst.execute('BEGIN IMMEDIATE')
            for row in event_rows(src):
                event = source._decode_event(row, connection=src)
                payload, refs = event['payload'], []
                if target_format == COMPACT:
                    payload, refs, bodies = encode_payload(event['event_type'], payload)
                    store_bodies(dst, bodies)
                columns = 'sequence,event_id,program_id,stream_revision,event_type,payload_json,created_at'
                values = [row['sequence'], event['event_id'], event['program_id'], event['stream_revision'],
                          event['event_type'], canonical_json(payload), event['created_at']]
                if target_format == COMPACT:
                    columns += ',source_refs_json'; values.append(canonical_json(refs))
                dst.execute('INSERT INTO control_events (' + columns + ') VALUES (' + ','.join('?' for _ in values) + ')', values)
            for row in request_rows(src):
                request = request_value(source, src, row['request_json'])
                original = source._replay_events(src, row['program_id'], row['events_json'])
                # Check the old stored result against the actual original events.
                for event in original:
                    actual = src.execute('SELECT * FROM control_events WHERE program_id=? AND event_id=?',
                                         (row['program_id'], event['event_id'])).fetchone()
                    require(actual is not None and canonical_json(source._decode_event(actual, connection=src)) == canonical_json(event),
                            'original idempotent result is not bound to its event')
                result = [e['event_id'] for e in original] if target_format == COMPACT else original
                dst.execute('INSERT INTO control_idempotency VALUES (?,?,?,?,?)',
                            (row['program_id'], row['idempotency_key'], converted_request(dst, request, target_format),
                             canonical_json(result), row['created_at']))
            sequence = src.execute("SELECT seq FROM sqlite_sequence WHERE name='control_events'").fetchone()
            if sequence:
                dst.execute("UPDATE sqlite_sequence SET seq=? WHERE name='control_events'", (sequence[0],))
            for name in ('user_version', 'application_id'):
                dst.execute('PRAGMA ' + name + '=' + str(src.execute('PRAGMA ' + name).fetchone()[0]))
            dst.commit()
    return compare_databases(snapshot, destination)


def file_fact(path):
    with path.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    return {'size': path.stat().st_size, 'sha256': digest}


def revisions(path):
    with closing(readonly(path)) as c:
        return {r[0]: {'count': r[1], 'revision': r[2]} for r in c.execute(
            'SELECT program_id,COUNT(*),MAX(stream_revision) FROM control_events GROUP BY program_id')}


def _evidence_tree_paths(root, on_error):
    """Keep observed entries even if a directory scan stops partway through."""
    pending = [root]
    while pending:
        directory = pending.pop()
        entries = []
        try:
            with os.scandir(directory) as scan:
                for entry in scan:
                    entries.append(Path(entry.path))
        except OSError as exc:
            on_error(directory, exc, 'SCAN_DIRECTORY')
        for item in sorted(entries):
            try:
                mode = item.lstat().st_mode
            except OSError as exc:
                on_error(item, exc, 'READ_METADATA')
                continue
            # A directory link is evidence itself, not permission to walk its target.
            if stat.S_ISDIR(mode):
                pending.append(item)
            yield item, mode


def evidence_inventory(manifest):
    """Only explicit files/trees, never a recursive search of the product workspace."""
    require(isinstance(manifest, list), 'external evidence must be an explicit list')
    rows = []
    for declaration in manifest:
        require(isinstance(declaration, dict) and declaration.get('kind') in ('file', 'tree')
                and isinstance(declaration.get('role'), str) and declaration['role']
                and isinstance(declaration.get('path'), str) and Path(declaration['path']).is_absolute(),
                'external evidence requires absolute path, file/tree kind and role')
        path = Path(declaration['path'])
        row = {'declaration': declaration, 'status': 'AVAILABLE', 'files': {}}
        def unavailable(item, exc, operation):
            row.update(status='UNAVAILABLE', reason=type(exc).__name__)
            row.setdefault('errors', []).append({
                'path': '.' if item == path else item.relative_to(path).as_posix(),
                'operation': operation, 'reason': type(exc).__name__, 'errno': exc.errno})
        try:
            root_mode = path.stat().st_mode
            require(stat.S_ISREG(root_mode) if declaration['kind'] == 'file' else stat.S_ISDIR(root_mode),
                    'declared evidence is unavailable')
            paths = [(path, None)] if declaration['kind'] == 'file' else _evidence_tree_paths(path, unavailable)
            for item, mode in paths:
                name = '.' if item == path else item.relative_to(path).as_posix()
                try:
                    mode = item.lstat().st_mode if mode is None else mode
                    if stat.S_ISLNK(mode):
                        # Preserve link facts even when its target cannot be read.
                        facts = {'link': str(item.readlink()), 'resolved': str(item.resolve()),
                                 'target_is_file': False}
                        row['files'][name] = facts
                        target_mode = item.stat().st_mode
                        facts['target_is_file'] = stat.S_ISREG(target_mode)
                        if facts['target_is_file']:
                            facts.update(file_fact(item))
                        elif stat.S_ISDIR(target_mode):
                            facts['target_contents_checked'] = False
                    elif stat.S_ISREG(mode):
                        row['files'][name] = file_fact(item)
                except OSError as exc:
                    unavailable(item, exc, 'READ_ENTRY')
            expected = declaration.get('expected')
            if expected is not None and row['status'] == 'AVAILABLE':
                require(declaration['kind'] == 'file', 'expected binding is supported on declared files')
                # Artifact identity binds content, not whether its allowed path
                # is spelled through a symlink. Retain link metadata separately.
                actual = {k: row['files']['.'].get(k) for k in ('size', 'sha256')}
                if actual != expected:
                    row['status'] = 'BOUND_VERSION_CHANGED'
        except OSError as exc:
            unavailable(path, exc, 'READ_ROOT')
        except RequestValidationError as exc:
            row.update(status='UNAVAILABLE', reason=type(exc).__name__)
        rows.append(row)
    return rows


def recorded_paths(snapshot):
    """Index known recovery roots; index presence is not proof of complete evidence."""
    store = Store(snapshot, read_only=True)
    found = []
    def visit(value, locator, event):
        if isinstance(value, dict):
            for k, v in value.items():
                if k in ('observation_root', 'runtime_root') and isinstance(v, str):
                    found.append({'event_id': event['event_id'], 'program_id': event['program_id'],
                                  'locator': locator + [k], 'path': v, 'available': Path(v).exists()})
                elif k != 'text':
                    visit(v, locator + [k], event)
        elif isinstance(value, list):
            for i, v in enumerate(value): visit(v, locator + [i], event)
    with closing(readonly(snapshot)) as c:
        for row in event_rows(c):
            event = store._decode_event(row, connection=c)
            visit(event['payload'], [], event)
    return found


def prepare_migration(source, output, *, target_format=COMPACT, evidence=(), timeout=900):
    """Produce a separate candidate and report. This is not a deployment switch."""
    source = Path(source).resolve(strict=True)
    output = Path(output).absolute()
    require(not output.exists() and output.parent.is_dir(), 'use a new output directory with an existing parent')
    output.mkdir()
    report = {'schema_version': 'REVISION_MIGRATION_V1', 'source': str(source), 'target_format': target_format,
              'status': 'INCOMPLETE', 'adoption_authorized': False, 'business_commands': 0, 'budget_modified': False,
              'path_policy': 'PRESERVE_ORIGINAL_BINDINGS_NO_RELOCATION'}
    try:
        before = evidence_inventory(list(evidence))
        snapshot = backup_database(source, output / 'snapshot.sqlite3', timeout=timeout)
        report['snapshot'] = {'path': str(snapshot), **file_fact(snapshot)}
        report['logical_comparison'] = convert_snapshot(snapshot, output / 'candidate.sqlite3', target_format)
        report['candidate'] = {'path': str(output / 'candidate.sqlite3'), **file_fact(output / 'candidate.sqlite3')}
        report['external_evidence'] = evidence_inventory(list(evidence))
        report['external_evidence_stable'] = before == report['external_evidence']
        report['recorded_recovery_paths'] = recorded_paths(snapshot)
        report['undeclared_recovery_roots'] = sorted({r['path'] for r in report['recorded_recovery_paths']
            if not any(d.get('kind') == 'tree' and Path(r['path']).is_relative_to(Path(d['path'])) for d in evidence)})
        report['source_revisions_after_conversion'] = revisions(source)
        report['source_advanced_since_snapshot'] = revisions(snapshot) != report['source_revisions_after_conversion']
        report['writer_state'] = 'NOT_QUIESCED_NO_SWITCH_PERFORMED'
        # This does not approve unknown/missing attachments or authorize adoption.
        report['status'] = 'DATABASE_CONVERSION_VERIFIED'
        report['external_evidence_status'] = ('DECLARED_FILES_VERIFIED' if evidence and before == report['external_evidence']
            and all(r['status'] == 'AVAILABLE' for r in before) else 'REVIEW_REQUIRED')
    except BaseException as exc:
        report['error_type'] = type(exc).__name__
        raise
    finally:
        (output / 'migration-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--to', choices=(INLINE, COMPACT), default=COMPACT)
    parser.add_argument('--evidence', type=Path, help='JSON list of declared external evidence files/trees')
    args = parser.parse_args()
    try:
        result = prepare_migration(args.source, args.output, target_format=args.to,
                                   evidence=json.loads(args.evidence.read_text()) if args.evidence else [])
    except (OSError, ValueError, sqlite3.Error, RequestValidationError) as exc:
        print(json.dumps({'status': 'INCOMPLETE', 'error': type(exc).__name__, 'detail': str(exc), 'adoption_authorized': False}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
