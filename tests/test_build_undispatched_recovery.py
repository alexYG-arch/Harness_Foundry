"""Effects preparation and no-command recovery using isolated native event stores.

Fixture processes exercise control semantics; these tests do not qualify an OS
sandbox, a real model, an external project or a Qt SDK.
"""
from copy import deepcopy
import threading
import unittest
from unittest.mock import patch

import test_build_runtime as support
from harness_foundry_factory.build_authoring import record_build_plan_proposal
from harness_foundry_factory.build_entrypoint import read_build
from harness_foundry_factory.build_runtime import (
    prepare_build_authorization, approve_build_authorization, record_source_snapshot)
from harness_foundry_factory.build_state import project_budget_attempts, project_execution_state, attempt_budget
from harness_foundry_factory.models import RequestValidationError, RevisionConflictError


class UndispatchedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f = support.BuildRuntimeTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.scope.update(max_attempts=24, max_task_attempts=24)
        self.f.plan['schema_version'] = '1.1'

    def effects(self, index=0, preflight=False):
        path = 'src/reader.py' if index == 0 else 'outputs/summary.json'
        self.f.plan['workpacks'][index]['effects'] = {
            'allowed': [path], 'required': [path], 'must_preserve': []}
        if preflight:
            self.f.plan['workpacks'][index]['environment'] = {
                'python': 'python', 'modules': ['json'], 'paths': []}

    def once(self, prepared=None, mode='ONE_ATTEMPT'):
        return self.f.controller().advance(prepared or self.f.prepared_id, advance_mode=mode)

    def legacy_unknown(self, index=0):
        """Append old-format host events; never rewrite a persisted history."""
        f = self.f
        controller = f.controller()
        with patch.object(controller, '_execute_command', side_effect=support.InjectedControllerCrash()), \
                self.assertRaises(support.InjectedControllerCrash):
            controller.advance(f.prepared_id, advance_mode='ONE_ATTEMPT')
        binding = f.events('BUILD_ATTEMPT_STARTED')[-1]['payload']
        controller._append('BUILD_ATTEMPT_FINISHED', {
            **binding, 'status': 'UNKNOWN_SIDE_EFFECT', 'artifacts': {},
            'verification': [{'diagnostic': 'TEST old effects baseline preparation failure'}],
            'effects': {'status': 'NOT_OBSERVED', 'external_effects_verified': False}},
            len(f.events()), binding['attempt_id'] + ':old-unknown')
        return binding

    def test_new_effects_failure_returns_once_preserving_diagnostic_and_budget(self):
        self.effects(); f = self.f; f.prepare()
        with patch('harness_foundry_factory.build_runtime.snapshot_effects',
                   side_effect=OSError('TEST effects preparation inaccessible')):
            result = self.once(mode='CONTINUOUS')
        self.assertEqual(result['attempt_status'], 'NOT_DISPATCHED')
        self.assertEqual(result['budget']['attempts_consumed'], 1)
        self.assertEqual(result['budget']['attempts_remaining'], 23)
        self.assertEqual(len(f.events('BUILD_ATTEMPT_STARTED')), 1)
        self.assertFalse(f.events('BUILD_COMMAND_PLANNED'))
        self.assertFalse(f.runner.invocations)
        finish = f.events('BUILD_ATTEMPT_FINISHED')[0]['payload']
        self.assertEqual(finish['failure_domain'], 'EFFECTS_PREPARATION')
        self.assertIn('inaccessible', finish['verification'][0]['diagnostic'])
        self.assertEqual(result['diagnostics'], finish['verification'])
        self.assertFalse(finish['old_output_accepted'])
        self.assertEqual(self.once()['attempt_status'], 'ACCEPTED')
        self.assertEqual(len(f.events('BUILD_ATTEMPT_STARTED')), 2)

    def test_legacy_unknown_recovers_once_and_reads_do_not_spend(self):
        self.effects(); f = self.f; f.prepare(); binding = self.legacy_unknown()
        old = deepcopy(f.events())
        result = self.once(mode='CONTINUOUS')
        self.assertEqual(result['attempt_id'], binding['attempt_id'])
        self.assertEqual(result['attempt_status'], 'NOT_DISPATCHED')
        self.assertEqual(result['budget']['attempts_consumed'], 1)
        self.assertFalse(f.events('BUILD_COMMAND_PLANNED'))
        self.assertEqual(f.events()[:len(old)], old)
        self.assertEqual(len(f.events('BUILD_ATTEMPT_RECOVERED')), 1)
        self.assertIn('old effects baseline preparation failure', result['diagnostics'][0]['diagnostic'])
        count = len(f.events())
        for _ in range(3): read_build(f.store.database_path, f.program)
        self.assertEqual(len(f.events()), count)
        self.assertEqual(len(f.events('BUILD_ATTEMPT_STARTED')), 1)
        later = self.once()
        self.assertEqual(later['attempt_status'], 'ACCEPTED')
        self.assertEqual(later['budget']['attempts_consumed'], 2)
        self.assertNotEqual(later['attempt_id'], binding['attempt_id'])

    def test_pass_preflight_remains_observed_and_is_not_replayed_during_recovery(self):
        self.effects(preflight=True); f = self.f; f.prepare()
        with patch('harness_foundry_factory.build_runtime.snapshot_effects',
                   side_effect=RequestValidationError('TEST baseline failed after preflight')):
            failed = self.once()
        self.assertEqual(failed['attempt_status'], 'UNKNOWN_SIDE_EFFECT')
        result = self.once(mode='CONTINUOUS')
        self.assertEqual(result['attempt_status'], 'NOT_DISPATCHED')
        self.assertEqual(result['attempt_id'], failed['attempt_id'])
        self.assertEqual([call['phase'] for call in f.runner.invocations], ['PREFLIGHT'])
        self.assertEqual(result['budget']['attempts_consumed'], 1)
        self.assertEqual(self.once()['budget']['attempts_consumed'], 2)

    def test_preflight_alone_cannot_explain_orphan_start_or_verification_inputs(self):
        for contradiction in ('orphan start', 'conflicting phase', 'verification inputs'):
            with self.subTest(contradiction=contradiction):
                self.setUp()
                self.effects(preflight=True); f = self.f; f.prepare()
                with patch('harness_foundry_factory.build_runtime.snapshot_effects',
                           side_effect=RequestValidationError('TEST preflight-only baseline failure')):
                    failed = self.once()
                binding = f.events('BUILD_ATTEMPT_STARTED')[-1]['payload']
                if contradiction == 'verification inputs':
                    kind = 'BUILD_VERIFICATION_INPUTS'
                    payload = {**binding, 'artifacts': {}}
                else:
                    kind = 'BUILD_COMMAND_STARTED'
                    payload = {**f.events('BUILD_COMMAND_PLANNED')[0]['payload'], 'pid': 12345,
                               'phase': 'IMPLEMENTATION'}
                    if contradiction == 'orphan start': payload['command_id'] = 'TEST-ORPHAN'
                f.controller()._append(kind, payload, len(f.events()), 'test-contradictory-facts')
                result = self.once()
                self.assertEqual(result['status'], 'HELD_UNRESOLVED_ATTEMPT')
                self.assertEqual(result['attempt_id'], failed['attempt_id'])
                self.assertEqual([row['phase'] for row in f.runner.invocations], ['PREFLIGHT'])
                self.assertFalse(f.events('BUILD_ATTEMPT_RECOVERED'))
                self.assertEqual(len(f.events('BUILD_ATTEMPT_STARTED')), 1)

    def test_intent_without_observation_stays_unresolved_without_replay(self):
        self.effects(); f = self.f; f.prepare()
        f.runner.before_run = lambda *args: (_ for _ in ()).throw(support.InjectedControllerCrash())
        with self.assertRaises(support.InjectedControllerCrash): self.once()
        f.runner.before_run = None
        for _ in range(2):
            self.assertEqual(self.once()['status'], 'HELD_UNRESOLVED_ATTEMPT')
        self.assertEqual(len(f.events('BUILD_COMMAND_PLANNED')), 1)
        self.assertFalse(f.runner.invocations)
        self.assertEqual(len(f.events('BUILD_ATTEMPT_STARTED')), 1)

    def test_dispatched_without_observation_is_never_classified_as_undispatched(self):
        self.effects(); f = self.f; f.prepare()
        f.runner.after_run = lambda *args: (_ for _ in ()).throw(support.InjectedControllerCrash())
        with self.assertRaises(support.InjectedControllerCrash): self.once()
        f.runner.after_run = None
        result = self.once()
        self.assertEqual(result['status'], 'HELD_UNRESOLVED_ATTEMPT')
        self.assertEqual(len(f.runner.invocations), 1)
        self.assertTrue((f.workspace / 'src/reader.py').is_file())
        self.assertFalse(f.events('BUILD_ATTEMPT_RECOVERED'))

    def test_incomplete_or_contradictory_records_do_not_prove_absence(self):
        self.effects(); f = self.f; f.prepare(); binding = self.legacy_unknown()
        rows = f.events(); attempt = project_execution_state(rows, f.prepared_id)[0][binding['attempt_id']]
        controller = f.controller()
        self.assertTrue(controller._no_command_intent(rows, f.prepared_id, attempt))
        variants = {}
        variants['missing event'] = rows[1:]
        variants['duplicate event'] = rows + [rows[-1]]
        for field, value in [('prepared_event_id', 'foreign'), ('proposal_event_id', 'foreign'),
                             ('workpack_id', 'foreign'), ('job_id', 'foreign')]:
            altered = deepcopy(rows); altered[-1]['payload'][field] = value
            variants[field] = altered
        for field, value in [('artifacts', {'A': {'path': 'src/reader.py'}}),
                             ('effects', {'status': 'VIOLATION'}), ('effects', None),
                             ('verification', None), ('verification', ['invalid']),
                             ('budget_workpack_ids', ['foreign']),
                             ('verification', [{'case_id': 'CASE', 'result': {'status': 'PASS'}}])]:
            altered = deepcopy(rows); altered[-1]['payload'][field] = value
            variants[field + repr(value)] = altered
        for kind in ('BUILD_COMMAND_PLANNED', 'BUILD_COMMAND_STARTED', 'BUILD_COMMAND_OBSERVED',
                     'BUILD_VERIFICATION_INPUTS', 'BUILD_ATTEMPT_RECOVERED'):
            altered = deepcopy(rows); altered[-1]['event_type'] = kind
            variants[kind] = altered
        for label, changed in variants.items():
            with self.subTest(label=label):
                self.assertFalse(controller._no_command_intent(changed, f.prepared_id, attempt))

    def test_recovery_cas_loses_to_committed_intent_without_settling(self):
        self.effects(); f = self.f; f.prepare(); self.legacy_unknown()
        controller = f.controller(); append = controller._append
        def race(kind, payload, revision, key):
            if kind == 'BUILD_ATTEMPT_RECOVERED':
                command = {**f.events('BUILD_ATTEMPT_STARTED')[-1]['payload'],
                    'command_id': 'TEST-LATE-INTENT', 'phase': 'IMPLEMENTATION', 'case_id': None,
                    'executor': 'LOCAL', 'observation_root': str(f.root / 'late-observation')}
                append('BUILD_COMMAND_PLANNED', command, revision, 'test-late-intent')
            return append(kind, payload, revision, key)
        with patch.object(controller, '_append', side_effect=race):
            result = controller.advance(f.prepared_id, advance_mode='ONE_ATTEMPT')
        self.assertEqual(result['status'], 'BUILD_STOPPED')
        self.assertFalse(f.events('BUILD_ATTEMPT_RECOVERED'))
        self.assertEqual(self.once()['status'], 'HELD_UNRESOLVED_ATTEMPT')
        self.assertFalse(f.runner.invocations)
        self.assertEqual(len(f.events('BUILD_ATTEMPT_STARTED')), 1)

    def test_delayed_dispatcher_cannot_start_or_overwrite_settled_attempt(self):
        self.effects(); f = self.f; f.prepare()
        controller = f.controller(); execute = controller._execute_command
        entered, resume = threading.Event(), threading.Event(); outcome = []
        def delayed(*args):
            entered.set()
            if not resume.wait(5): raise RuntimeError('test barrier timed out')
            return execute(*args)
        def old_dispatcher():
            try: outcome.append(controller.advance(f.prepared_id, advance_mode='ONE_ATTEMPT'))
            except BaseException as exc: outcome.append(exc)
        with patch.object(controller, '_execute_command', side_effect=delayed):
            thread = threading.Thread(target=old_dispatcher)
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                settled = self.once()
                self.assertEqual(settled['attempt_status'], 'NOT_DISPATCHED')
            finally:
                resume.set(); thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome[0]['attempt_status'], 'NOT_DISPATCHED')
        self.assertFalse(f.events('BUILD_COMMAND_PLANNED'))
        self.assertFalse(f.runner.invocations)
        self.assertEqual(len(f.events('BUILD_ATTEMPT_STARTED')), 1)
        self.assertEqual(len(f.events('BUILD_ATTEMPT_FINISHED')), 1)

    def test_recovered_consumer_rebind_keeps_accepted_harness_and_total_budget(self):
        self.effects(index=1); f = self.f; f.prepare(); accepted = self.once()
        with patch('harness_foundry_factory.build_runtime.snapshot_effects',
                   side_effect=OSError('TEST unchanged preparation failure; explicit later requests')):
            for _ in range(8):
                self.assertEqual(self.once()['attempt_status'], 'NOT_DISPATCHED')
        self.legacy_unknown(index=1)
        settled = self.once()
        self.assertEqual(settled['attempt_status'], 'NOT_DISPATCHED')
        self.assertEqual(settled['budget']['attempts_consumed'], 10)
        self.assertEqual(settled['budget']['attempts_remaining'], 14)
        f.plan['revision'] += 1
        f.plan['workpacks'][1]['effects']['allowed'].append('outputs/cache.txt')
        proposal = record_build_plan_proposal(f.store, f.ir, f.plan,
            document_review=f.review, **f.kwargs('corrected-plan'))
        source = record_source_snapshot(f.store, f.program, proposal['event_id'], f.source,
            [{'source_id':'PROJECT-BRIEF','path':'brief.md'}], **f.kwargs('corrected-sources'))
        prepared = prepare_build_authorization(f.store, f.program, proposal['event_id'], source['event_id'],
            f.scope, rebind_from=f.prepared_id, **f.kwargs('corrected-prepared'))['event_id']
        approve_build_authorization(f.store, f.program, prepared,
            human_message_ref='TEST-FIXTURE-ONLY', **f.kwargs('corrected-approved'))
        self.assertEqual(project_execution_state(f.events(), prepared)[1]['IMPLEMENT-READER']['attempt_id'],
                         accepted['attempt_id'])
        before = len(f.runner.invocations)
        result = self.once(prepared)
        self.assertEqual(result['attempt_status'], 'ACCEPTED')
        self.assertEqual(result['budget']['attempts_consumed'], 11)
        self.assertEqual(result['budget']['task_attempts_consumed'], {'IMPLEMENT-READER':1, 'MAKE-REPORT':10})
        self.assertEqual(result['budget']['attempts_remaining'], 13)
        self.assertEqual([row['job_id'] for row in f.runner.invocations[before:]], ['REPORT', 'REPORT'])
        self.assertEqual(read_build(f.store.database_path, f.program)['authorizations'][-1]['budget']['this_preparation_attempts'], 1)


if __name__ == '__main__':
    unittest.main()
