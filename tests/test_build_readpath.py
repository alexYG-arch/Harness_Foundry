"""Read optimization in disposable stores; no models, migrations or real Programs."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from harness_foundry_factory.build_authoring import _proposal_event, record_build_plan_proposal
from harness_foundry_factory.build_correction import POLICY, validate_authority_chain
from harness_foundry_factory.build_entrypoint import _scope_readback
from harness_foundry_factory.build_observation import read_build_scope
from harness_foundry_factory.build_runtime import revoke_build_authorization
from harness_foundry_factory.build_types import BuildAuthorizationError, RequestValidationError, authorization_reason
from harness_foundry_factory.revision_store import RevisionControlEventStore
import test_build_runtime as support


class StoreReadPathTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'control.sqlite3'
        self.store = RevisionControlEventStore(self.path)

    def append(self, kind, payload, program='P'):
        revision = self.store.event_count(program)
        return self.store.append_batch(program, [{'event_type': kind, 'payload': payload}],
            expected_revision=revision, idempotency_key=f'{program}-{revision}', created_at=support.NOW)[0]

    def source(self, text='line one\r\n汉🙂\n', program='P'):
        return self.append('BUILD_SOURCES_CAPTURED', {'snapshot': {'complete': True, 'sources': [
            {'source_id': 'S1', 'text': text, 'loaded_completely': True, 'line_count': 2},
            {'source_id': 'S2', 'text': '', 'loaded_completely': True, 'line_count': 0}]},
            'manifest': [{'source_id': 'S1'}], 'source_root': '/declared'}, program)

    def test_exact_lookup_rejects_wrong_program_type_and_id(self):
        one = self.append('A', {'a': 1}); two = self.append('A', {'a': 2})
        self.append('A', {'a': 3}, 'Q')
        self.assertEqual(self.store.find_event('P', event_type='A'), two)
        self.assertEqual(self.store.find_event('P', event_type='A', event_id=one['event_id']), one)
        for program, kind, identity in [('Q', 'A', one['event_id']), ('P', 'B', one['event_id']), ('P', 'A', 'missing')]:
            self.assertIsNone(self.store.find_event(program, event_type=kind, event_id=identity))

    def test_count_and_control_view_never_decode_large_source(self):
        large = 'REPEATED-SOURCE-' * 100000
        source = self.source(large); other = self.append('BUILD_PLAN_PROPOSED', {'plan': 1})
        original = json.loads; sizes = []
        def decode(value, *args, **kwargs):
            sizes.append(len(value)); self.assertNotIn(large[:1000], value)
            return original(value, *args, **kwargs)
        with patch('harness_foundry_factory.revision_store.json.loads', decode):
            self.assertEqual(self.store.event_count('P'), 2)
            self.assertEqual(sizes, [])
            rows = self.store.list_control_events('P')
            self.assertEqual(_proposal_event(self.store, 'P', None), other)
        self.assertEqual(rows[0], {**source, 'payload': {}, 'payload_omitted': True})
        self.assertLess(sum(sizes), 1000)
        self.assertEqual(self.store.list_events('P'), [source, other])

    def test_metadata_then_full_hydration_preserves_exact_source_and_order(self):
        source = self.source(); view = self.store.list_control_events('P')
        expected = deepcopy(source)
        for item in expected['payload']['snapshot']['sources']: item.pop('text')
        expected['source_text_omitted'] = True
        self.assertEqual(self.store.hydrate_source_event('P', view, source['event_id'], include_text=False), expected)
        self.assertEqual(self.store.hydrate_source_event('P', view, source['event_id']), source)
        self.assertEqual(view, self.store.list_events('P'))

    def test_view_does_not_import_later_sources_or_another_program(self):
        source = self.source(); view = self.store.list_control_events('P')
        later = self.source('new body'); foreign = self.source(program='Q')
        self.assertEqual(self.store.hydrate_source_event('P', view, source['event_id']), source)
        for identity in (later['event_id'], foreign['event_id']):
            with self.assertRaises(RequestValidationError): self.store.hydrate_source_event('P', view, identity)
        self.assertEqual(len(view), 1)

    def test_hydration_checks_immutable_header_and_missing_record(self):
        source = self.source(); view = self.store.list_control_events('P')
        changed = {**source, 'stream_revision': 99}
        for loaded in (None, changed):
            with patch.object(self.store, 'find_event', return_value=loaded), self.assertRaises(RequestValidationError):
                self.store.hydrate_source_event('P', view, source['event_id'])
        self.assertTrue(view[0]['payload_omitted'])

    def test_metadata_fallback_without_sql_json_preserves_compatibility(self):
        source = self.source(); expected = self.store.find_event('P', event_type='BUILD_SOURCES_CAPTURED', source_metadata=True)
        original = self.store._connection
        @contextmanager
        def connection():
            with original() as real:
                class Proxy:
                    def execute(self, query, args):
                        if 'json_set' in query: raise sqlite3.OperationalError('no such function: json_set')
                        return real.execute(query, args)
                yield Proxy()
        with patch.object(self.store, '_connection', connection):
            self.assertEqual(self.store.find_event('P', event_type='BUILD_SOURCES_CAPTURED', source_metadata=True), expected)
        self.assertEqual(self.store.list_events('P'), [source])

    def test_metadata_does_not_swallow_unrelated_database_errors(self):
        self.source()
        with patch.object(self.store, '_connection') as connection:
            connection.return_value.__enter__.return_value.execute.side_effect = sqlite3.OperationalError('disk error')
            with self.assertRaisesRegex(sqlite3.OperationalError, 'disk error'):
                self.store.find_event('P', event_type='BUILD_SOURCES_CAPTURED', source_metadata=True)

    def test_readonly_queries_leave_database_bytes_and_old_api_unchanged(self):
        source = self.source(); before = self.path.read_bytes()
        readonly = RevisionControlEventStore(self.path, read_only=True)
        view = readonly.list_control_events('P')
        readonly.event_count('P'); readonly.hydrate_source_event('P', view, source['event_id'], include_text=False)
        self.assertEqual(readonly.list_events('P'), [source])
        self.assertEqual(self.path.read_bytes(), before)


class ControllerReadPathTests(unittest.TestCase):
    def setUp(self):
        self.f = support.BuildRuntimeTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)

    def test_dispatch_acceptance_and_reuse_do_not_require_full_history_read(self):
        f = self.f; f.prepare(); controller = f.controller()
        with patch.object(f.store, 'list_events', side_effect=AssertionError('full history read')):
            result = controller.advance(f.prepared_id)
            self.assertEqual(result['status'], 'PLAN_CHECKS_ACCEPTED', result)
            calls = len(f.runner.invocations)
            self.assertEqual(controller.advance(f.prepared_id)['status'], 'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(len(f.runner.invocations), calls)
        self.assertEqual(len(f.events('BUILD_ATTEMPT_STARTED')), 2)

    def test_current_uses_one_proposal_view_then_refreshes(self):
        f = self.f; f.prepare(); before = f.events(); original = f.store.list_control_events
        next_plan = deepcopy(f.plan); next_plan['revision'] += 1
        next_plan['workpacks'][0]['goal'] = 'Next ordinary plan revision'
        def interleaved(program):
            rows = original(program)
            record_build_plan_proposal(f.store, f.ir, next_plan, document_review=f.review,
                expected_revision=len(before), idempotency_key='later', created_at=support.NOW)
            return rows
        with patch.object(f.store, 'list_control_events', interleaved):
            rows, current, plan = f.controller()._current(f.prepared_id)
        self.assertEqual(len(rows), len(before)); self.assertEqual(plan, f.plan)
        self.assertEqual(current['proposal_event_id'], f.proposal_id)
        self.assertEqual(f.controller()._current(f.prepared_id)[2], next_plan)

    def test_scope_metadata_matches_full_projection_without_materializing_source_text(self):
        f = self.f; f.prepare(); full = f.events()
        expected = _scope_readback(next(e for e in full if e['event_id'] == f.prepared_id), full)
        original = RevisionControlEventStore.find_event; reads = []
        def find(store, program, **kwargs):
            reads.append(kwargs); self.assertTrue(kwargs['source_metadata'])
            return original(store, program, **kwargs)
        with patch.object(RevisionControlEventStore, 'find_event', find), \
                patch.object(RevisionControlEventStore, 'list_events', side_effect=AssertionError('full history')):
            actual = read_build_scope(f.store.database_path, f.program, f.prepared_id, include_workflow=True)
        self.assertEqual(actual['authorization'], expected); self.assertEqual(len(reads), 1)
        self.assertFalse(actual['writes_performed']); self.assertEqual(f.events(), full)

    def test_revocation_refresh_and_absent_authorization_do_not_charge_attempt(self):
        f = self.f; f.prepare(approve=False)
        self.assertEqual(f.advance()['reason_code'], 'BUILD_AUTHORIZATION_ABSENT')
        f.approve(); f.controller()._current(f.prepared_id)
        revoke_build_authorization(f.store, f.program, f.prepared_id, **f.kwargs('revoke'))
        self.assertEqual(f.advance()['reason_code'], 'BUILD_AUTHORIZATION_REVOKED')
        self.assertEqual(f.events('BUILD_ATTEMPT_STARTED'), []); self.assertEqual(f.runner.invocations, [])

    def test_expiry_and_unknown_prepared_have_distinct_reasons(self):
        f = self.f; f.prepare(); controller = f.controller()
        controller.clock = lambda: datetime.fromisoformat(support.NOW) + timedelta(days=1)
        self.assertEqual(controller.advance(f.prepared_id)['reason_code'], 'BUILD_AUTHORIZATION_EXPIRED')
        self.assertEqual(controller.advance('missing')['reason_code'], 'BUILD_AUTHORIZATION_BINDING_INVALID')
        self.assertEqual(f.events('BUILD_ATTEMPT_STARTED'), [])

    def test_polling_observes_new_revocation_without_source_decode_or_refund(self):
        f = self.f; f.prepare(); reasons = []
        def during_run(invocation):
            callback = invocation['cancellation_reason']
            with patch.object(f.store, 'find_event', side_effect=AssertionError('source decoded while polling')):
                reasons.append(callback())
                f.store.append_batch(f.program, [{'event_type': 'BUILD_AUTHORIZATION_REVOKED',
                    'payload': {'prepared_event_id': f.prepared_id}}], expected_revision=f.store.event_count(f.program),
                    idempotency_key='poll-revoke', created_at=support.NOW)
                reasons.extend([callback(), callback()])
        f.runner.before_run = during_run
        result = f.advance()
        self.assertEqual(result['status'], 'BUILD_STOPPED')
        self.assertEqual(reasons, [None, 'BUILD_AUTHORIZATION_REVOKED', 'BUILD_AUTHORIZATION_REVOKED'])
        self.assertEqual(len(f.events('BUILD_ATTEMPT_STARTED')), 1)
        self.assertEqual(len(f.events('BUILD_COMMAND_OBSERVED')), 1)
        self.assertEqual(len(f.runner.invocations), 1)

    def test_source_and_checker_drift_are_still_checked_before_dispatch(self):
        f = self.f; f.prepare()
        for path in (f.source / 'brief.md', f.verifier / 'check.py'):
            with self.subTest(path=path.name):
                original = path.read_bytes(); path.write_bytes(original + b'\nchanged\n')
                result = f.advance(); path.write_bytes(original)
                self.assertEqual(result['status'], 'BUILD_STOPPED')
                self.assertIn('changed', result['reason'])
        self.assertEqual(f.events('BUILD_ATTEMPT_STARTED'), [])
        self.assertEqual(f.runner.invocations, [])

    def test_derived_display_uses_reason_code_not_human_wording(self):
        f = self.f; f.prepare(); rows = f.events()
        prepared = next(row for row in rows if row['event_id'] == f.prepared_id)
        prepared['payload']['scope']['expires_at'] = '2999-01-01T00:00:00Z'
        approval = next(row for row in rows if row['event_type'] == 'BUILD_AUTHORIZATION_APPROVED')
        approval['payload']['derived_authority'] = {'test': 'projection only'}
        for error, state in ((RequestValidationError('expired revoked unrelated error'), 'APPROVAL_REQUIRED'),
                             (BuildAuthorizationError('non-English reason', reason_code='BUILD_AUTHORIZATION_REVOKED'), 'REVOKED'),
                             (BuildAuthorizationError('non-English reason', reason_code='BUILD_AUTHORIZATION_EXPIRED'), 'EXPIRED')):
            with self.subTest(state=state), patch('harness_foundry_factory.build_correction.validate_authority_chain', side_effect=error):
                self.assertEqual(_scope_readback(prepared, rows)['state'], state)


class AuthorizationReasonTests(unittest.TestCase):
    def test_unknown_error_text_cannot_classify_revocation_or_expiry(self):
        for message in ('revoked', 'expired', 'revoked expired', 'unknown'):
            self.assertEqual(authorization_reason(RequestValidationError(message)), 'BUILD_AUTHORIZATION_INVALID')
        error = BuildAuthorizationError('translated human message', reason_code='BUILD_AUTHORIZATION_REVOKED')
        self.assertEqual(authorization_reason(error), 'BUILD_AUTHORIZATION_REVOKED')
        self.assertEqual(error.as_response()['error']['code'], 'REQUEST_VALIDATION_ERROR')
        self.assertEqual(error.exit_code, 2)

    def test_derived_authority_still_inherits_source_revocation_and_expiry(self):
        now = datetime.fromisoformat(support.NOW)
        events = [
            {'event_id': 'P1', 'event_type': 'BUILD_AUTHORIZATION_PREPARED', 'stream_revision': 1,
             'payload': {'scope': {'expires_at': '2026-09-18T01:00:00Z'}}},
            {'event_id': 'A1', 'event_type': 'BUILD_AUTHORIZATION_APPROVED', 'stream_revision': 2,
             'payload': {'prepared_event_id': 'P1', 'human_message_ref': 'TEST ONLY'}},
            {'event_id': 'P2', 'event_type': 'BUILD_AUTHORIZATION_PREPARED', 'stream_revision': 3,
             'payload': {'scope': {'expires_at': '2026-09-20T01:00:00Z'}}},
            {'event_id': 'A2', 'event_type': 'BUILD_AUTHORIZATION_APPROVED', 'stream_revision': 4,
             'payload': {'prepared_event_id': 'P2', 'derived_authority': {'policy': POLICY,
                 'source_prepared_event_id': 'P1', 'source_approval_event_id': 'A1'}}}]
        self.assertEqual(validate_authority_chain(events, 'P2', now), ['A2', 'A1'])
        for variant, clock, expected in (
            (events, now + timedelta(days=1), 'BUILD_AUTHORIZATION_EXPIRED'),
            (events + [{'event_type': 'BUILD_AUTHORIZATION_REVOKED', 'payload': {'prepared_event_id': 'P1'}}], now, 'BUILD_AUTHORIZATION_REVOKED'),
            (events[:1] + events[2:], now, 'BUILD_AUTHORIZATION_BINDING_INVALID')):
            with self.assertRaises(BuildAuthorizationError) as caught: validate_authority_chain(variant, 'P2', clock)
            self.assertEqual(authorization_reason(caught.exception), expected)
