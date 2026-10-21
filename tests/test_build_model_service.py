"""Controller service bindings and legacy continuation; fixture models only.

Historical records below are disposable event fixtures. They do not authorize a
real model, mutate a user Program, or qualify a native service implementation.
"""
from copy import deepcopy
import json
import os
import unittest
from unittest.mock import patch

import test_build_runtime as support
from harness_foundry_factory.build_entrypoint import apply_build_request, read_build
from harness_foundry_factory.build_runtime import (
    NativeBuildRunner, approve_build_authorization, prepare_build_authorization,
)
from harness_foundry_factory.build_types import IdempotencyConflictError, RequestValidationError
from harness_foundry_factory.process_observation import CommandObservation


RESOLVER = 'harness_foundry_factory.coding_defaults.resolve_codex_defaults'
SERVICE = {
    'provider': 'fixture-provider',
    'config': {'name': 'Fixture service', 'base_url': 'https://models.example.invalid/v1',
               'wire_api': 'responses', 'requires_openai_auth': True},
}
SOURCE = {'method': 'CODEX_CONFIG_READ', 'codex_executable': '/usr/bin/true',
          'config_scope': 'GLOBAL', 'model_turns': 0}


class BuildModelServiceTests(unittest.TestCase):
    def setUp(self):
        self.f = support.BuildRuntimeTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.calls = []
        self.f.runner = self.f._codex_fixture_runner(self.calls)
        self.f.prepare(approve=False)
        self.selected = {'model': 'fixture-model', 'model_reasoning_effort': 'high',
                         'model_service': deepcopy(SERVICE), 'model_defaults_source': deepcopy(SOURCE)}

    def prepare(self, scope, key='service-prepare', **kwargs):
        f = self.f
        return prepare_build_authorization(f.store, f.program, f.proposal_id, f.source_id,
                                           scope, **f.kwargs(key), **kwargs)

    def approve(self, identity, key='service-approve'):
        f = self.f
        return approve_build_authorization(f.store, f.program, identity,
            human_message_ref='TEST FIXTURE approval, not an actual user grant', **f.kwargs(key))

    def read(self, identity):
        return next(row for row in read_build(self.f.store.database_path, self.f.program)['authorizations']
                    if row['prepared_event_id'] == identity)

    def invocation(self, identity):
        controller = self.f.controller()
        _, prepared, plan = controller._current(identity)
        return controller._invocation(prepared, plan['workpacks'][0], [])

    def append(self, kind, payload):
        f = self.f
        return f.store.append_batch(f.program, [{'event_type': kind, 'payload': payload}],
                                   **f.kwargs('legacy-fixture-' + str(len(f.events()))))[0]

    def legacy_preparation(self):
        """Create the old persisted shape without changing an existing event."""
        payload = deepcopy(self.f.events('BUILD_AUTHORIZATION_PREPARED')[0]['payload'])
        payload['scope'].update(model=None, model_policy='CODEX_GLOBAL_DEFAULTS')
        payload['scope'].pop('model_service', None)
        payload['scope'].pop('model_reasoning_effort', None)
        for name in ('model_defaults_source', 'prepare_request', 'resource_prepare_request'):
            payload.pop(name, None)
        return self.append('BUILD_AUTHORIZATION_PREPARED', payload)['event_id']

    def test_fixed_service_is_public_and_reaches_receiver_without_default_lookup(self):
        f = self.f
        with patch(RESOLVER, side_effect=AssertionError('fixed scope must not query defaults')):
            event = self.prepare({**f.scope, 'model_service': deepcopy(SERVICE)})
            self.approve(event['event_id'])
            self.assertEqual(self.read(event['event_id'])['scope']['model_service'], SERVICE)
            invocation = self.invocation(event['event_id'])
            authority = json.loads(invocation['prompt'].split('\n', 1)[1])['task']['runtime_authorization']
            self.assertEqual(authority['model_service'], SERVICE)
            with patch('harness_foundry_factory.coding_process.CodexCodingRunner.run',
                       return_value={'status': 'MODEL_PROCESS_FAILED'}) as run:
                NativeBuildRunner()(invocation, lambda: None)
        command = run.call_args.args[0]
        self.assertEqual(command.model, f.scope['model'])
        self.assertEqual(command.model_policy, 'FIXED')
        self.assertEqual(command.model_service, SERVICE)
        self.assertFalse(f.events('BUILD_ATTEMPT_STARTED'))

    def test_follow_defaults_freezes_pair_and_service_and_exact_replay_does_not_refresh(self):
        f = self.f
        scope = {**f.scope, 'model': None}
        arguments = f.kwargs('frozen-service')
        with patch(RESOLVER, return_value=self.selected) as resolver:
            event = prepare_build_authorization(f.store, f.program, f.proposal_id, f.source_id,
                scope, follow_codex_defaults=True, **arguments)
        self.assertEqual(resolver.call_count, 1)
        self.assertIsNone(scope['model'], 'the caller input remains unmodified')
        prepared = event['payload']['scope']
        self.assertEqual((prepared['model'], prepared['model_reasoning_effort']), ('fixture-model', 'high'))
        self.assertEqual(prepared['model_service'], SERVICE)
        self.approve(event['event_id'])
        with patch(RESOLVER, side_effect=AssertionError('do not refresh an existing preparation')):
            repeated = prepare_build_authorization(f.store, f.program, f.proposal_id, f.source_id,
                scope, follow_codex_defaults=True, **arguments)
            self.assertEqual(repeated, event)
            self.assertEqual(self.read(event['event_id'])['model_defaults_source'], SOURCE)
            invocation = self.invocation(event['event_id'])
        authority = json.loads(invocation['prompt'].split('\n', 1)[1])['task']['runtime_authorization']
        self.assertEqual(authority['model_service'], SERVICE)
        self.assertEqual(authority['model'], 'fixture-model')
        self.assertFalse(f.events('BUILD_ATTEMPT_STARTED'))

    def test_dynamic_prepare_freezes_service_but_not_the_model_or_effort(self):
        f = self.f
        scope = {**f.scope, 'model': None, 'model_policy': 'CODEX_GLOBAL_DEFAULTS'}
        args = f.kwargs('dynamic-service')
        with patch(RESOLVER, return_value=self.selected) as resolver:
            event = prepare_build_authorization(f.store, f.program, f.proposal_id, f.source_id, scope, **args)
        resolver.assert_called_once_with(f.scope['codex_executable'], require_explicit=False)
        self.assertIsNone(event['payload']['scope']['model'])
        self.assertNotIn('model_reasoning_effort', event['payload']['scope'])
        self.assertEqual(event['payload']['scope']['model_service'], SERVICE)
        self.approve(event['event_id'])
        with patch(RESOLVER, side_effect=AssertionError('readback does not refresh defaults')):
            self.assertEqual(self.read(event['event_id'])['scope']['model_service'], SERVICE)
            invocation = self.invocation(event['event_id'])
            repeated = prepare_build_authorization(f.store, f.program, f.proposal_id, f.source_id, scope, **args)
            self.assertEqual(repeated, event)
            with self.assertRaises(IdempotencyConflictError):
                prepare_build_authorization(f.store, f.program, f.proposal_id, f.source_id,
                    {**scope, 'model_policy': 'FIXED', 'model': 'fixture-model'}, **args)
            with patch('harness_foundry_factory.coding_process.CodexCodingRunner.run',
                       return_value={'status': 'MODEL_PROCESS_FAILED'}) as run:
                NativeBuildRunner()(invocation, lambda: None)
        authority = json.loads(invocation['prompt'].split('\n', 1)[1])['task']['runtime_authorization']
        self.assertEqual(authority['model_policy'], 'CODEX_GLOBAL_DEFAULTS')
        self.assertEqual(authority['model_service'], SERVICE)
        self.assertIsNone(authority['model'])
        command = run.call_args.args[0]
        self.assertEqual(command.model_policy, 'CODEX_GLOBAL_DEFAULTS')
        self.assertEqual(command.model_service, SERVICE)
        self.assertIsNone(command.model)
        self.assertIsNone(command.reasoning_effort)

    def test_dynamic_prepare_accepts_native_missing_model_without_inventing_one(self):
        selected = {**self.selected, 'model': None, 'model_reasoning_effort': None}
        with patch(RESOLVER, return_value=selected):
            event = self.prepare({**self.f.scope, 'model': None, 'model_policy': 'CODEX_GLOBAL_DEFAULTS'})
        self.assertIsNone(event['payload']['scope']['model'])
        self.assertNotIn('model_reasoning_effort', event['payload']['scope'])
        self.assertEqual(event['payload']['scope']['model_service'], SERVICE)
        self.assertFalse(self.f.events('BUILD_ATTEMPT_STARTED'))

    def test_service_environment_references_do_not_import_secret_values(self):
        service = deepcopy(SERVICE)
        service['config'].update(env_key='FOUNDRY_TEST_API_KEY',
                                 env_http_headers={'X-Test-Authorization': 'FOUNDRY_TEST_API_KEY'})
        secret = 'TEST-SECRET-MUST-NOT-ENTER-PREPARED-OR-PROMPT'
        with patch.dict(os.environ, {'FOUNDRY_TEST_API_KEY': secret}), \
             patch(RESOLVER, side_effect=AssertionError('explicit service must not read defaults')):
            event = self.prepare({**self.f.scope, 'model_service': service})
            self.approve(event['event_id'])
            invocation = self.invocation(event['event_id'])
            readback = self.read(event['event_id'])
        self.assertEqual(readback['scope']['model_service'], service)
        self.assertNotIn(secret, json.dumps(self.f.events()))
        self.assertNotIn(secret, json.dumps(readback))
        self.assertNotIn(secret, invocation['prompt'])

    def test_inline_secret_service_is_rejected_before_any_attempt(self):
        f = self.f
        before = len(f.events())
        for key, extra in (
                ('header', {'http_headers': {'Authorization': 'Bearer TEST-SECRET'}}),
                ('key', {'api_key': 'TEST-SECRET'}),
                ('url', {'base_url': 'https://user:TEST-SECRET@models.example.invalid/v1'})):
            service = deepcopy(SERVICE)
            service['config'].update(extra)
            with self.subTest(key=key), self.assertRaises(RequestValidationError):
                self.prepare({**f.scope, 'model_service': service}, key='unsafe-' + key)
        self.assertEqual(len(f.events()), before)
        self.assertFalse(f.events('BUILD_ATTEMPT_STARTED'))

    def test_legacy_dynamic_read_and_complete_reconciliation_do_not_refresh_or_recount(self):
        f = self.f
        old = self.legacy_preparation()
        binding = {'prepared_event_id': old, 'proposal_event_id': f.proposal_id,
                   'attempt_id': 'LEGACY-ATTEMPT', 'workpack_id': 'IMPLEMENT-READER', 'job_id': 'CSV-PIPELINE'}
        self.append('BUILD_ATTEMPT_STARTED', binding)
        command = {**binding, 'command_id': 'LEGACY-COMMAND', 'executor': 'CODEX',
                   'phase': 'IMPLEMENTATION', 'case_id': None, 'observation_root': str(f.root / 'old-command')}
        self.append('BUILD_COMMAND_PLANNED', command)
        observation = CommandObservation(command['observation_root'], command['command_id'], 'CODEX')
        try:
            observation.finished({'status': 'MODEL_TURN_COMPLETED', 'exit_code': 0,
                                  'final_message': 'TEST fixture completed; not independent acceptance'})
        finally:
            observation.close()
        request = {'program_id': f.program, 'prepared_event_id': old,
                   'expected_revision': len(f.events()), 'idempotency_key': 'legacy-reconcile'}
        with patch(RESOLVER, side_effect=AssertionError('historical reads cannot query global settings')), \
             patch('subprocess.Popen', side_effect=AssertionError('reconciliation cannot execute')):
            budget = self.read(old)['budget']
            result = apply_build_request('reconcile-build-observations', request, f.store.database_path)
            repeated = apply_build_request('reconcile-build-observations', request, f.store.database_path)
            self.assertEqual(result, repeated)
            self.assertEqual(self.read(old)['budget'], budget)
        self.assertEqual(result['recovered_command_ids'], ['LEGACY-COMMAND'])
        self.assertEqual(budget['attempts_consumed'], 1)
        self.assertFalse(result['execution_started'])
        attempts = read_build(f.store.database_path, f.program)['attempts']
        self.assertEqual(attempts[-1]['status'], 'IN_FLIGHT')
        self.assertEqual(len(f.events('BUILD_ATTEMPT_STARTED')), 1)
        self.assertFalse(self.calls)

    def test_legacy_dynamic_accepted_plan_reuses_without_service_lookup_or_attempt(self):
        f = self.f
        self.approve(f.prepared_id, key='initial-complete-approve')
        initial = f.controller().advance(f.prepared_id)
        self.assertEqual(initial['status'], 'PLAN_CHECKS_ACCEPTED')
        accepted_events = [deepcopy(event) for event in f.events()
                           if event['event_type'] in {'BUILD_ATTEMPT_STARTED', 'BUILD_ATTEMPT_FINISHED'}]
        old = self.legacy_preparation()
        self.approve(old, key='legacy-complete-approve')
        for event in accepted_events:
            payload = event['payload']
            payload.update(prepared_event_id=old, attempt_id='LEGACY-' + payload['attempt_id'])
            self.append(event['event_type'], payload)
        before_events = deepcopy(f.events())
        before_budget = self.read(old)['budget']
        before_calls = len(self.calls)
        with patch(RESOLVER, side_effect=AssertionError('accepted history must not query defaults')), \
             patch('subprocess.Popen', side_effect=AssertionError('accepted history must not execute')):
            first = f.controller().advance(old, advance_mode='ONE_ATTEMPT')
            second = f.controller().advance(old, advance_mode='ONE_ATTEMPT')
        self.assertEqual(first['status'], 'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(second, first)
        self.assertEqual(self.read(old)['budget'], before_budget)
        self.assertEqual(before_budget['attempts_consumed'], 2)
        self.assertEqual(f.events(), before_events)
        self.assertEqual(len(self.calls), before_calls)

    def test_legacy_binding_gap_stops_new_dispatch_without_new_attempt(self):
        f = self.f
        old = self.legacy_preparation()
        self.approve(old, key='legacy-approve')
        with patch(RESOLVER, side_effect=AssertionError('old authority cannot discover a new service')):
            result = f.controller().advance(old, advance_mode='ONE_ATTEMPT')
            self.assertEqual(self.read(old)['budget']['attempts_consumed'], 0)
        self.assertEqual(result['status'], 'BUILD_STOPPED')
        self.assertIn('service', result.get('reason', '').lower())
        self.assertFalse(f.events('BUILD_ATTEMPT_STARTED'))
        self.assertFalse(self.calls)

    def test_legacy_rebind_keeps_spent_attempt_and_qualified_acceptance(self):
        f = self.f
        # Derive a historical acceptance fixture from actual local fixture output;
        # this copies events into an independent old-shaped scope, never edits them.
        self.approve(f.prepared_id, key='initial-approve')
        accepted = f.controller().advance(f.prepared_id, advance_mode='ONE_ATTEMPT')
        self.assertEqual(accepted['attempt_status'], 'ACCEPTED')
        start = deepcopy(f.events('BUILD_ATTEMPT_STARTED')[0]['payload'])
        finish = deepcopy(f.events('BUILD_ATTEMPT_FINISHED')[0]['payload'])
        old = self.legacy_preparation()
        self.approve(old, key='legacy-approve')
        for payload in (start, finish):
            payload.update(prepared_event_id=old, attempt_id='LEGACY-ACCEPTED')
        self.append('BUILD_ATTEMPT_STARTED', start)
        self.append('BUILD_ATTEMPT_FINISHED', finish)
        original_events = deepcopy(f.events())
        scope = {**f.scope, 'model': None, 'model_policy': 'CODEX_GLOBAL_DEFAULTS'}
        with patch(RESOLVER, return_value=self.selected):
            new = self.prepare(scope, key='legacy-rebind', rebind_from=old)['event_id']
        self.approve(new, key='legacy-rebind-approve')
        readback = self.read(new)
        self.assertEqual(readback['budget']['attempts_consumed'], 1)
        self.assertEqual(readback['budget']['attempts_remaining'], f.scope['max_attempts'] - 1)
        self.assertEqual(readback['reused_acceptance']['IMPLEMENT-READER']['prepared_event_id'], old)
        with patch(RESOLVER, side_effect=AssertionError('accepted producer must not be rerun')):
            result = f.controller().advance(new, advance_mode='ONE_ATTEMPT')
        self.assertEqual(result['attempt_status'], 'ACCEPTED')
        self.assertEqual(self.read(new)['budget']['attempts_consumed'], 2)
        self.assertEqual(len(self.calls), 1, 'only the initial fixture producer ran')
        self.assertEqual(f.events()[:len(original_events)], original_events)


if __name__ == '__main__':
    unittest.main()
