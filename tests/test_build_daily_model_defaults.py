"""Default model choice for new preparations; local fixtures, no real model calls."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import test_build_runtime as support
from harness_foundry_factory.build_entrypoint import apply_build_request, read_build
from harness_foundry_factory.build_runtime import (
    NativeBuildRunner, approve_build_authorization, prepare_build_authorization,
)
from harness_foundry_factory.build_types import IdempotencyConflictError, RequestValidationError
from harness_foundry_factory.coding_process import _dispatch_configuration
from harness_foundry_factory.process_observation import CommandObservation


RESOLVER = 'harness_foundry_factory.coding_defaults.resolve_codex_defaults'
SERVICE = {'provider': 'openai', 'config': {}}
SOURCE = {'method': 'CODEX_CONFIG_READ', 'config_scope': 'GLOBAL', 'model_turns': 0}


class BuildDefaultFollowTests(unittest.TestCase):
    def setUp(self):
        self.f = support.BuildRuntimeTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.calls = []
        self.f.runner = self.f._codex_fixture_runner(self.calls)
        self.f.prepare(approve=False)
        self.selected = {'model': 'fixture-default-model', 'model_reasoning_effort': 'high',
                         'model_service': deepcopy(SERVICE), 'model_defaults_source': deepcopy(SOURCE)}

    def scope(self, *, omit=False):
        result = deepcopy(self.f.scope)
        if omit:
            result.pop('model')
        else:
            result['model'] = None
        return result

    def prepare(self, scope, key='default-prepare', **kwargs):
        f = self.f
        return prepare_build_authorization(f.store, f.program, f.proposal_id, f.source_id,
                                           scope, **f.kwargs(key), **kwargs)

    def approve(self, identity, key='default-approve'):
        f = self.f
        return approve_build_authorization(f.store, f.program, identity,
            human_message_ref='TEST FIXTURE ONLY; not actual runtime authority', **f.kwargs(key))

    def read(self, identity):
        return next(row for row in read_build(self.f.store.database_path, self.f.program)['authorizations']
                    if row['prepared_event_id'] == identity)

    def invocation(self, identity):
        controller = self.f.controller()
        _, prepared, plan = controller._current(identity)
        return controller._invocation(prepared, plan['workpacks'][0], [])

    def command(self, identity):
        invocation = self.invocation(identity)
        with patch('harness_foundry_factory.coding_process.CodexCodingRunner.run',
                   return_value={'status': 'MODEL_PROCESS_FAILED'}) as run:
            NativeBuildRunner()(invocation, lambda: None)
        return run.call_args.args[0]

    def test_public_prepare_defaults_for_omitted_or_null_model_without_authorizing(self):
        f = self.f
        for omit in (False, True):
            with self.subTest(omit=omit):
                scope = self.scope(omit=omit)
                scope['expires_at'] = '2099-01-01T00:00:00Z'
                original = deepcopy(scope)
                request = {'program_id': f.program, 'proposal_event_id': f.proposal_id,
                    'source_event_id': f.source_id, 'scope': scope,
                    'expected_revision': len(f.events()), 'idempotency_key': 'public-default-' + str(omit)}
                with patch(RESOLVER, return_value=self.selected) as resolver:
                    result = apply_build_request('prepare-build-authorization', request, f.store.database_path)
                resolver.assert_called_once_with(f.scope['codex_executable'], require_explicit=False)
                self.assertEqual(result['status'], 'BUILD_SCOPE_APPROVAL_REQUIRED')
                self.assertFalse(result['execution_started'])
                saved = self.read(result['event_id'])['scope']
                self.assertEqual(saved['model_policy'], 'CODEX_GLOBAL_DEFAULTS')
                self.assertEqual(saved['model_service'], SERVICE)
                self.assertIsNone(saved['model'])
                self.assertNotIn('model_reasoning_effort', saved)
                self.assertEqual(scope, original, 'preparation must not mutate caller material')
        self.assertFalse(f.events('BUILD_AUTHORIZATION_APPROVED'))
        self.assertFalse(f.events('BUILD_ATTEMPT_STARTED'))

    def test_native_unspecified_defaults_remain_unspecified(self):
        selected = {**self.selected, 'model': None, 'model_reasoning_effort': None}
        with patch(RESOLVER, return_value=selected):
            event = self.prepare(self.scope(omit=True))
        saved = event['payload']['scope']
        self.assertIsNone(saved['model'])
        self.assertNotIn('model_reasoning_effort', saved)
        self.assertEqual(saved['model_service'], SERVICE)
        self.assertFalse(self.f.events('BUILD_ATTEMPT_STARTED'))

    def test_exact_request_replay_preserves_bound_service_without_refresh(self):
        f = self.f
        scope = self.scope(omit=True)
        args = f.kwargs('same-default-request')
        with patch(RESOLVER, return_value=self.selected):
            first = prepare_build_authorization(f.store, f.program, f.proposal_id, f.source_id, scope, **args)
        self.approve(first['event_id'])
        before = deepcopy(f.events())
        with patch(RESOLVER, side_effect=AssertionError('existing preparation must not refresh defaults')):
            again = prepare_build_authorization(f.store, f.program, f.proposal_id, f.source_id, scope, **args)
            with self.assertRaises(IdempotencyConflictError):
                prepare_build_authorization(f.store, f.program, f.proposal_id, f.source_id,
                    {**scope, 'model': 'changed-fixed-model'}, **args)
        self.assertEqual(first, again)
        self.assertEqual(f.events(), before)
        self.assertEqual(self.read(first['event_id'])['budget']['attempts_consumed'], 0)

    def test_explicit_model_stays_fixed_with_or_without_explicit_policy(self):
        for explicit_policy in (False, True):
            scope = {**self.f.scope, 'model_reasoning_effort': 'low'}
            if explicit_policy:
                scope['model_policy'] = 'FIXED'
            with self.subTest(explicit_policy=explicit_policy), patch(
                    RESOLVER, side_effect=AssertionError('manual selection cannot consult defaults')):
                event = self.prepare(scope, key='fixed-' + str(explicit_policy))
            saved = event['payload']['scope']
            self.assertEqual(saved.get('model_policy', 'FIXED'), 'FIXED')
            self.assertEqual(saved['model'], self.f.scope['model'])
            self.assertEqual(saved['model_reasoning_effort'], 'low')
            self.assertNotIn('model_defaults_source', event['payload'])

    def test_freeze_current_defaults_remains_an_explicit_option(self):
        with patch(RESOLVER, return_value=self.selected) as resolver:
            event = self.prepare(self.scope(omit=True), follow_codex_defaults=True)
        resolver.assert_called_once_with(self.f.scope['codex_executable'])
        saved = event['payload']['scope']
        self.assertEqual(saved.get('model_policy', 'FIXED'), 'FIXED')
        self.assertEqual((saved['model'], saved['model_reasoning_effort']), ('fixture-default-model', 'high'))
        self.approve(event['event_id'])
        with patch(RESOLVER, side_effect=AssertionError('frozen scope must not change at dispatch')):
            command = self.command(event['event_id'])
            selected, configuration, _, _ = _dispatch_configuration(command)
        self.assertEqual(selected.model, 'fixture-default-model')
        self.assertEqual(configuration['model_policy'], 'FIXED')

    def test_incomplete_explicit_choice_is_not_silently_replaced(self):
        invalid = ({**self.scope(), 'model_policy': 'FIXED'},
                   {**self.scope(), 'model_reasoning_effort': 'high'},
                   {**self.scope(), 'model': ''})
        before = deepcopy(self.f.events())
        for index, scope in enumerate(invalid):
            with self.subTest(index=index), patch(RESOLVER,
                    side_effect=AssertionError('do not reinterpret an incomplete explicit choice')):
                with self.assertRaises(RequestValidationError):
                    self.prepare(scope, key='incomplete-' + str(index))
        self.assertEqual(self.f.events(), before)

    def test_default_policy_does_not_grant_model_service_permission(self):
        before = deepcopy(self.f.events())
        with patch(RESOLVER, side_effect=AssertionError('permission absent; no configuration read')):
            with self.assertRaises(RequestValidationError):
                self.prepare({**self.scope(), 'allow_model_service': False})
        self.assertEqual(self.f.events(), before)

    def test_requested_service_is_not_replaced_by_global_service(self):
        before = deepcopy(self.f.events())
        service = {'provider': 'different', 'config': {'name': 'Different', 'wire_api': 'responses',
                   'base_url': 'https://different.example.invalid/v1'}}
        with patch(RESOLVER, return_value=self.selected):
            with self.assertRaisesRegex(RequestValidationError, 'service'):
                self.prepare({**self.scope(), 'model_service': service})
        self.assertEqual(self.f.events(), before)

    def test_local_legacy_replay_and_omitted_model_do_not_read_defaults(self):
        local = support.BuildRuntimeTests()
        local.setUp()
        self.addCleanup(local.doCleanups)
        with patch(RESOLVER, side_effect=AssertionError('LOCAL does not use a model')):
            local.prepare(approve=False)
            first = local.events('BUILD_AUTHORIZATION_PREPARED')[0]
            args = {'expected_revision': len(local.events()) - 1,
                    'idempotency_key': 'prepare', 'created_at': support.NOW}
            replay = prepare_build_authorization(local.store, local.program, local.proposal_id,
                local.source_id, local.scope, **args)
            self.assertEqual(replay, first)
            self.assertNotIn('resource_prepare_request', first['payload'])
            scope = deepcopy(local.scope)
            scope.pop('model')
            event = prepare_build_authorization(local.store, local.program, local.proposal_id,
                local.source_id, scope, **local.kwargs('local-omitted'))
        self.assertIsNone(event['payload']['scope']['model'])
        self.assertNotIn('model_policy', event['payload']['scope'])
        self.assertFalse(local.events('BUILD_ATTEMPT_STARTED'))

    def test_existing_approved_fixed_scope_is_never_reinterpreted(self):
        f = self.f
        self.approve(f.prepared_id)
        before = deepcopy(f.events())
        with patch(RESOLVER, side_effect=AssertionError('old fixed authority is unchanged')):
            command = self.command(f.prepared_id)
            selected, configuration, _, _ = _dispatch_configuration(command)
            self.read(f.prepared_id)
        self.assertEqual(selected.model, f.scope['model'])
        self.assertEqual(configuration['model_policy'], 'FIXED')
        self.assertEqual(f.events(), before)

    def test_new_commands_refresh_defaults_under_one_approval_and_same_service(self):
        f = self.f
        with patch(RESOLVER, return_value=self.selected):
            event = self.prepare(self.scope())
        self.approve(event['event_id'])
        command = self.command(event['event_id'])
        self.assertEqual(command.model_policy, 'CODEX_GLOBAL_DEFAULTS')
        before = deepcopy(f.events())
        later = {**self.selected, 'model': 'fixture-later-model', 'model_reasoning_effort': 'low'}
        with patch(RESOLVER, side_effect=[self.selected, later]) as resolver:
            first, first_record, _, _ = _dispatch_configuration(command)
            second, second_record, _, _ = _dispatch_configuration(command)
        self.assertEqual(resolver.call_count, 2)
        self.assertEqual((first.model, first.reasoning_effort), ('fixture-default-model', 'high'))
        self.assertEqual((second.model, second.reasoning_effort), ('fixture-later-model', 'low'))
        self.assertEqual(first_record['model_service'], second_record['model_service'])
        self.assertEqual(f.events(), before, 'configuration resolution does not approve or consume attempts')
        self.assertEqual(len(f.events('BUILD_AUTHORIZATION_APPROVED')), 1)

    def test_rebind_to_default_policy_preserves_consumption_and_accepted_producer(self):
        f = self.f
        self.approve(f.prepared_id, key='fixed-approve')
        first = f.controller().advance(f.prepared_id, advance_mode='ONE_ATTEMPT')
        self.assertEqual(first['attempt_status'], 'ACCEPTED')
        old = f.prepared_id
        before = deepcopy(f.events())
        with patch(RESOLVER, return_value=self.selected):
            event = self.prepare(self.scope(omit=True), rebind_from=old)
        self.approve(event['event_id'], key='rebind-approve')
        readback = self.read(event['event_id'])
        self.assertEqual(readback['budget']['attempts_consumed'], 1)
        self.assertEqual(readback['budget']['attempts_remaining'], f.scope['max_attempts'] - 1)
        self.assertEqual(readback['reused_acceptance']['IMPLEMENT-READER']['prepared_event_id'], old)
        with patch(RESOLVER, side_effect=AssertionError('accepted producer must not run again')):
            result = f.controller().advance(event['event_id'])
            repeated = f.controller().advance(event['event_id'])
        self.assertEqual(result['status'], 'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(repeated['status'], 'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(self.read(event['event_id'])['budget']['attempts_consumed'], 2)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(f.events()[:len(before)], before)

    def test_complete_report_recovery_never_refreshes_defaults_or_recounts(self):
        f = self.f
        with patch(RESOLVER, return_value=self.selected):
            event = self.prepare(self.scope())
        identity = event['event_id']
        self.approve(identity)

        def append(kind, payload):
            return f.store.append_batch(f.program, [{'event_type': kind, 'payload': payload}],
                                        **f.kwargs('observation-' + str(len(f.events()))))[0]

        binding = {'prepared_event_id': identity, 'proposal_event_id': f.proposal_id,
                   'attempt_id': 'FIXTURE-ATTEMPT', 'workpack_id': 'IMPLEMENT-READER', 'job_id': 'CSV-PIPELINE'}
        append('BUILD_ATTEMPT_STARTED', binding)
        command = {**binding, 'command_id': 'FIXTURE-COMMAND', 'executor': 'CODEX',
                   'phase': 'IMPLEMENTATION', 'case_id': None, 'observation_root': str(f.root / 'command')}
        append('BUILD_COMMAND_PLANNED', command)
        observation = CommandObservation(command['observation_root'], command['command_id'], 'CODEX')
        try:
            observation.finished({'status': 'MODEL_TURN_COMPLETED', 'exit_code': 0,
                                  'final_message': 'fixture completion, not independent acceptance'})
        finally:
            observation.close()
        request = {'program_id': f.program, 'prepared_event_id': identity,
                   'expected_revision': len(f.events()), 'idempotency_key': 'complete-reconcile'}
        budget = self.read(identity)['budget']
        with patch(RESOLVER, side_effect=AssertionError('recovery uses original configuration')), \
             patch('subprocess.Popen', side_effect=AssertionError('no replay during recovery')):
            result = apply_build_request('reconcile-build-observations', request, f.store.database_path)
            repeated = apply_build_request('reconcile-build-observations', request, f.store.database_path)
            self.assertEqual(result, repeated)
            self.assertEqual(self.read(identity)['budget'], budget)
        self.assertEqual(result['recovered_command_ids'], ['FIXTURE-COMMAND'])
        self.assertFalse(result['execution_started'])
        self.assertEqual(budget['attempts_consumed'], 1)
        self.assertEqual(len(f.events('BUILD_ATTEMPT_STARTED')), 1)
        self.assertFalse(self.calls)


if __name__ == '__main__':
    unittest.main()
