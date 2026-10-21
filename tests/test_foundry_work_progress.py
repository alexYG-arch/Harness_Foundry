"""Opt-in dashboard work history using isolated native fixture event stores.

Fixture commands and synthetic model outcomes establish display semantics only;
these tests do not call a real model or inspect another project's database.
"""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import test_build_runtime as support
import test_build_replan as replan_support
from test_build_resources import DurableResourceFixtureRunner
from harness_foundry_factory import build_observation as observation
from harness_foundry_factory.build_runtime import approve_build_authorization, prepare_build_authorization
from harness_foundry_factory.process_observation import CommandObservation
from harness_foundry_factory.revision_store import RevisionControlEventStore


class FoundryWorkProgressTests(unittest.TestCase):
    def setUp(self):
        self.f = support.BuildRuntimeTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.scope.update(expires_at='2099-01-01T00:00:00Z', max_attempts=24, max_task_attempts=8)

    def selection(self, prepared=None):
        return {'kind': 'foundry_build', 'project_id': self.f.ir['target']['id'],
                'project_version': 'same-version', 'run_id': 'same-run',
                'program_id': self.f.program, 'prepared_event_id': prepared or self.f.prepared_id}

    def project(self, prepared=None):
        return observation.read_foundry_projection(self.f.store.database_path,
                                                  self.selection(prepared), include_workflow=True)

    def assert_progress(self, projection, completed, total, *, current):
        progress = projection['business']['work_progress']
        self.assertEqual((progress['completed'], progress['total']), (completed, total))
        self.assertTrue(progress['label'])
        self.assertEqual(projection['business']['completion']['completed'], current,
                         'cumulative work must not replace current valid acceptance')

    def repair_fixture(self, *, independent=False):
        helper = support.BuildRepairTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        self.f = helper.f
        self.f.scope['expires_at'] = '2099-01-01T00:00:00Z'
        if independent:
            helper._independent_producers()
        helper.prepare(total=24, per_task=8)
        return helper

    def case_steps(self, projection, case_id):
        return [step for step in projection['business']['workflow']['steps']
                if case_id in step['label'] or any(case_id in ref for ref in step['evidence_refs'])]

    def assert_read_only(self, *, prepared=None, expected):
        f = self.f
        before = f.events()
        database = f.store.database_path.read_bytes()
        files = {str(p.relative_to(f.root)): p.read_bytes() for p in f.root.rglob('*') if p.is_file()}
        with (patch.object(CommandObservation, 'recover', side_effect=AssertionError('read cannot recover')),
              patch.object(support.BuildController, 'advance', side_effect=AssertionError('read cannot dispatch')),
              patch.object(RevisionControlEventStore, 'append_batch', side_effect=AssertionError('read cannot write'))):
            for _ in range(3):
                self.assertEqual(self.project(prepared), expected)
        self.assertEqual(f.events(), before)
        self.assertEqual(f.store.database_path.read_bytes(), database)
        self.assertEqual({str(p.relative_to(f.root)): p.read_bytes()
                          for p in f.root.rglob('*') if p.is_file()}, files)

    def test_default_projection_remains_compatible_and_opt_in_is_read_only(self):
        self.f.prepare()
        legacy = observation.read_foundry_projection(self.f.store.database_path, self.selection())
        explicit_false = observation.read_foundry_projection(self.f.store.database_path, self.selection(),
                                                            include_workflow=False)
        self.assertEqual(explicit_false, legacy)
        self.assertNotIn('work_progress', legacy['business'])
        self.assertNotIn('workflow', legacy['business'])
        extended = self.project()
        original_fields = deepcopy(extended)
        original_fields['business'].pop('work_progress')
        original_fields['business'].pop('workflow')
        self.assertEqual(original_fields, legacy)
        self.assert_progress(extended, 0, 2, current=0)
        self.assert_read_only(expected=extended)
        self.assertFalse(self.f.runner.invocations)

    def test_workflow_lists_future_implementation_each_case_and_acceptance(self):
        f = self.f
        f.prepare()
        pending = self.project()
        steps = pending['business']['workflow']['steps']
        expected = sum(2 + len(task['verification']) for task in f.plan['workpacks'])
        self.assertEqual(len(steps), expected)
        self.assertEqual(len({step['step_id'] for step in steps}), expected)
        for step in steps:
            self.assertEqual(step['state'], 'NOT_STARTED')
            self.assertIsInstance(step['detail'], str)
            self.assertIsInstance(step['history'], list)
            self.assertIsInstance(step['evidence_refs'], list)
        for case_id in ('READ-ROWS', 'REJECT-MALFORMED', 'REPORT-COUNT'):
            self.assertEqual(len(self.case_steps(pending, case_id)), 1, case_id)
        self.assertEqual(f.controller().advance(f.prepared_id, advance_mode='ONE_ATTEMPT')['attempt_status'],
                         'ACCEPTED')
        partial = self.project()
        self.assert_progress(partial, 1, 2, current=1)
        for case_id in ('READ-ROWS', 'REJECT-MALFORMED'):
            self.assertEqual(self.case_steps(partial, case_id)[0]['state'], 'PASS')
        self.assertEqual(self.case_steps(partial, 'REPORT-COUNT')[0]['state'], 'NOT_STARTED')
        self.assertEqual(len(partial['business']['workflow']['steps']), expected)
        self.assertEqual(f.advance()['status'], 'PLAN_CHECKS_ACCEPTED')
        complete = self.project()
        self.assert_progress(complete, 2, 2, current=2)
        states = [step['state'] for step in complete['business']['workflow']['steps']]
        self.assertEqual(states.count('COMPLETED'), 2, 'implementation completion is not a check PASS')
        self.assertEqual(states.count('PASS'), 3)
        self.assertEqual(states.count('ACCEPTED'), 2)
        self.assertNotIn('current_step_id', complete['business']['workflow'])
        self.assert_read_only(expected=complete)

    def test_single_affected_workpack_adds_one_unit_for_each_distinct_confirmed_request(self):
        helper = self.repair_fixture(independent=True)
        initial = self.project()
        self.assert_progress(initial, 2, 2, current=2)
        origin = helper.repair(helper.request(artifacts=('SUMMARY',)))
        self.assertEqual(origin['payload']['workpack_ids'], ['MAKE-REPORT'])
        self.assert_progress(self.project(), 2, 3, current=1)
        self.assertEqual(helper.step()['attempt_status'], 'ACCEPTED')
        self.assert_progress(self.project(), 3, 3, current=2)
        second = helper.repair(helper.request(artifacts=('SUMMARY',)))
        self.assertNotEqual(second['event_id'], origin['event_id'])
        self.assert_progress(self.project(), 3, 4, current=1)
        self.assertEqual(helper.step()['attempt_status'], 'ACCEPTED')
        completed = self.project()
        self.assert_progress(completed, 4, 4, current=2)
        calls = len(helper.captured) + len(self.f.runner.invocations)
        self.assert_read_only(expected=completed)
        self.assertEqual(len(helper.captured) + len(self.f.runner.invocations), calls)

    def test_retries_and_continuation_share_repair_units_and_keep_acceptance_history(self):
        helper = self.repair_fixture()
        self.assert_progress(self.project(), 2, 2, current=2)
        request = helper.request()
        origin = helper.repair(request)
        invalidated = self.project()
        self.assert_progress(invalidated, 2, 4, current=0)
        history = [row for step in invalidated['business']['workflow']['steps'] for row in step['history']]
        self.assertTrue(any(row['state'] == 'ACCEPTED' for row in history),
                        'invalidating current acceptance must retain prior accepted work in history')
        for row in history:
            self.assertTrue({'label', 'state', 'detail', 'evidence_refs'} <= row.keys())
        self.assertEqual(helper.repair(request), origin, 'idempotent request replay is not a new work item')
        helper.reader_text = support.BAD_READER
        self.assertEqual(helper.step()['attempt_status'], 'REJECTED')
        failed = self.project()
        self.assert_progress(failed, 2, 4, current=0)
        self.assertEqual(failed['business']['budget']['attempts_consumed'], 3)
        helper.reader_text = support.GOOD_READER
        self.assertEqual(helper.step()['attempt_status'], 'ACCEPTED')
        self.assert_progress(self.project(), 3, 4, current=1)
        continuation = helper.repair(helper.request(origin=origin))
        self.assertEqual(continuation['payload']['continuation_of'], origin['event_id'])
        reopened = self.project()
        self.assert_progress(reopened, 2, 4, current=0)
        workflow = reopened['business']['workflow']
        focused = next(step for step in workflow['steps'] if step['step_id'] == workflow['current_step_id'])
        self.assertNotIn(focused['state'], {'ACCEPTED', 'PASS', 'COMPLETED'},
                         'a reopened repair cannot focus a stage still displayed as completed')
        self.assert_read_only(expected=reopened)
        self.assertEqual(helper.step()['attempt_status'], 'ACCEPTED')
        self.assert_progress(self.project(), 3, 4, current=1)
        self.assertEqual(helper.step()['attempt_status'], 'ACCEPTED')
        repaired = self.project()
        self.assert_progress(repaired, 4, 4, current=2)
        self.assertEqual(repaired['business']['budget']['attempts_consumed'], 6)
        self.assertEqual(repaired['business']['budget']['attempts_remaining'], 18)
        self.assertEqual(len(self.f.events('BUILD_ATTEMPT_STARTED')), 6)

    def test_native_artifact_invalidation_does_not_invent_a_confirmed_repair_unit(self):
        f = self.f
        f.scope['max_attempts'] = 2
        f.prepare()
        self.assertEqual(f.advance()['status'], 'PLAN_CHECKS_ACCEPTED')
        self.assert_progress(self.project(), 2, 2, current=2)
        (f.workspace / 'src/reader.py').unlink()
        self.assertEqual(f.advance()['status'], 'ATTEMPT_BUDGET_EXHAUSTED')
        invalidations = f.events('BUILD_ACCEPTANCE_INVALIDATED')
        self.assertEqual(len(invalidations), 1)
        self.assertNotEqual(invalidations[0]['payload']['reason'], 'CODEX_CONFIRMED_REPAIR_REQUEST')
        invalidated = self.project()
        self.assert_progress(invalidated, 2, 2, current=0)
        self.assertEqual(invalidated['business']['budget']['attempts_consumed'], 2)
        self.assert_read_only(expected=invalidated)
        self.assertEqual(len(f.runner.invocations), 5)

    def test_same_labels_do_not_import_an_independent_preparation_history_or_budget(self):
        helper = self.repair_fixture()
        helper.repair()
        selected = self.project()
        self.assert_progress(selected, 2, 4, current=0)
        other = prepare_build_authorization(self.f.store, self.f.program, self.f.proposal_id,
            self.f.source_id, self.f.scope, **self.f.kwargs('separate-prepared'))['event_id']
        independent = self.project(other)
        self.assertEqual({k: v for k, v in selected['selection'].items() if k != 'prepared_event_id'},
                         {k: v for k, v in independent['selection'].items() if k != 'prepared_event_id'})
        self.assert_progress(independent, 0, 2, current=0)
        self.assertEqual(independent['business']['budget']['attempts_consumed'], 0)
        self.assertTrue(all(step['state'] == 'NOT_STARTED'
                            for step in independent['business']['workflow']['steps']))
        rendered = json.dumps(independent['business']['workflow'])
        for row in self.f.events('BUILD_ATTEMPT_STARTED'):
            self.assertNotIn(row['payload']['attempt_id'], rendered)
        self.assert_read_only(prepared=other, expected=independent)
        self.assert_progress(self.project(), 2, 4, current=0)

    def test_durable_but_unsettled_command_does_not_claim_a_completed_stage(self):
        f = self.f
        f.runner = DurableResourceFixtureRunner()
        f.prepare()
        def interrupt(*args):
            raise support.InjectedControllerCrash()
        f.runner.after_run = interrupt
        with self.assertRaises(support.InjectedControllerCrash):
            f.controller().advance(f.prepared_id, advance_mode='ONE_ATTEMPT')
        f.runner.after_run = None
        self.assertFalse(f.events('BUILD_COMMAND_OBSERVED'))
        self.assertEqual(len(f.runner.invocations), 1)
        uncertain = self.project()
        self.assert_progress(uncertain, 0, 2, current=0)
        states = {step['state'] for step in uncertain['business']['workflow']['steps']}
        self.assertFalse(states.intersection({'ACCEPTED', 'PASS', 'COMPLETED'}))
        self.assertIn('UNKNOWN', states)
        for case_id in ('READ-ROWS', 'REJECT-MALFORMED', 'REPORT-COUNT'):
            self.assertEqual(self.case_steps(uncertain, case_id)[0]['state'], 'NOT_STARTED')
        self.assert_read_only(expected=uncertain)
        self.assertEqual(len(f.runner.invocations), 1)

    def test_missing_command_observation_does_not_complete_planned_verification(self):
        f = self.f
        f.prepare()
        controller = f.controller()
        execute = controller._execute_command
        def interrupt_check(binding, prepared, invocation, revision):
            if invocation['phase'] == 'VERIFICATION':
                raise support.InjectedControllerCrash()
            return execute(binding, prepared, invocation, revision)
        with patch.object(controller, '_execute_command', side_effect=interrupt_check):
            with self.assertRaises(support.InjectedControllerCrash):
                controller.advance(f.prepared_id, advance_mode='ONE_ATTEMPT')
        displayed = self.project()
        self.assert_progress(displayed, 0, 2, current=0)
        for case_id in ('READ-ROWS', 'REJECT-MALFORMED', 'REPORT-COUNT'):
            self.assertNotIn(self.case_steps(displayed, case_id)[0]['state'], {'ACCEPTED', 'PASS', 'COMPLETED'})
        self.assert_read_only(expected=displayed)
        self.assertEqual(len(f.runner.invocations), 1)

    def test_legal_reuse_and_reverification_keep_selected_scope_work_and_stage_meaning(self):
        f = self.f
        f.prepare()
        self.assertEqual(f.advance()['status'], 'PLAN_CHECKS_ACCEPTED')
        original_attempts = [row['payload']['attempt_id'] for row in f.events('BUILD_ATTEMPT_STARTED')]
        reused = prepare_build_authorization(f.store, f.program, f.proposal_id, f.source_id,
            f.scope, rebind_from=f.prepared_id, **f.kwargs('work-reuse'))['event_id']
        approve_build_authorization(f.store, f.program, reused,
            human_message_ref='TEST ONLY fixture approval', **f.kwargs('work-reuse-approve'))
        projection = self.project(reused)
        self.assert_progress(projection, 2, 2, current=2)
        for step in projection['business']['workflow']['steps']:
            self.assertEqual(len(step['history']), 1)
            self.assertEqual(step['history'][0]['label'], '合法复用记录')
            self.assertIn(step['history'][0]['state'], {'NOT_RUN', 'ACCEPTED'})
        self.assertFalse(observation.read_build_scope(f.store.database_path, f.program, reused)['attempts'],
                         'legal reuse must not import predecessor attempts as local history')
        self.assertEqual(len(f.runner.invocations), 5)
        self.assert_read_only(prepared=reused, expected=projection)

        verifier = f.root / 'updated-verifier'
        verifier.mkdir()
        (verifier / 'check.py').write_text(support.VERIFIER + '\n# updated independent checker binding\n')
        next_scope = {**f.scope, 'verification_root': str(verifier)}
        reverify = prepare_build_authorization(f.store, f.program, f.proposal_id, f.source_id,
            next_scope, rebind_from=reused, **f.kwargs('work-reverify'))['event_id']
        approve_build_authorization(f.store, f.program, reverify,
            human_message_ref='TEST ONLY fixture approval', **f.kwargs('work-reverify-approve'))
        self.assert_progress(self.project(reverify), 0, 2, current=0)
        self.assertEqual(f.controller().advance(reverify)['status'], 'PLAN_CHECKS_ACCEPTED')
        checked = self.project(reverify)
        self.assert_progress(checked, 2, 2, current=2)
        states = [step['state'] for step in checked['business']['workflow']['steps']]
        self.assertEqual(states.count('NOT_RUN'), 2, 'reverification must not claim implementation reran')
        self.assertEqual(states.count('PASS'), 3)
        self.assertEqual(states.count('ACCEPTED'), 2)
        self.assertTrue(all(call['phase'] == 'VERIFICATION' for call in f.runner.invocations[5:]))
        self.assertEqual(len(f.runner.invocations), 8)
        local_history = json.dumps([row for step in checked['business']['workflow']['steps']
                                   for row in step['history']])
        for attempt_id in original_attempts:
            self.assertNotIn('Attempt ' + attempt_id, local_history)
        self.assert_read_only(prepared=reverify, expected=checked)

    def test_inherited_acceptance_invalidated_without_local_attempt_keeps_reuse_history(self):
        f = self.f
        f.scope['max_attempts'] = 2
        f.prepare()
        self.assertEqual(f.advance()['status'], 'PLAN_CHECKS_ACCEPTED')
        reused = prepare_build_authorization(f.store, f.program, f.proposal_id, f.source_id,
            f.scope, rebind_from=f.prepared_id, **f.kwargs('invalidated-reuse'))['event_id']
        approve_build_authorization(f.store, f.program, reused,
            human_message_ref='TEST ONLY fixture approval', **f.kwargs('invalidated-reuse-approve'))
        self.assert_progress(self.project(reused), 2, 2, current=2)
        (f.workspace / 'src/reader.py').unlink()
        self.assertEqual(f.controller().advance(reused)['status'], 'ATTEMPT_BUDGET_EXHAUSTED')
        scoped = observation.read_build_scope(f.store.database_path, f.program, reused)
        self.assertFalse(scoped['attempts'])
        self.assertEqual(len(scoped['invalidations']), 1)
        displayed = self.project(reused)
        self.assert_progress(displayed, 2, 2, current=0)
        self.assertEqual(displayed['business']['budget'], {'attempts_consumed': 2, 'attempts_remaining': 0})
        workflow = displayed['business']['workflow']
        focused = next(step for step in workflow['steps'] if step['step_id'] == workflow['current_step_id'])
        self.assertNotIn(focused['state'], {'PASS', 'COMPLETED', 'ACCEPTED'})
        self.assertEqual(sum(step['state'] == 'INVALIDATED' for step in workflow['steps']), 2)
        history = [row for step in workflow['steps'] for row in step['history']]
        self.assertTrue(all(row['label'] == '合法复用记录' for row in history))
        self.assertEqual(sum(row['state'] == 'ACCEPTED' for row in history), 2)
        self.assert_read_only(prepared=reused, expected=displayed)
        self.assertEqual(len(f.runner.invocations), 5)
        self.assertEqual(len(f.events('BUILD_ATTEMPT_STARTED')), 2)

    def test_preflight_exists_only_for_declared_environment_and_focus_skips_completed_implementation(self):
        # Pure event projection: no environment commands, controller writes or model calls.
        f = self.f
        plain_progress, plain = observation._work_history([], 'TEST-PREPARED', f.plan, {})
        self.assertEqual((plain_progress['completed'], plain_progress['total']), (0, 2))
        self.assertEqual(len(plain['steps']), 7)
        self.assertFalse(any('环境检查' in step['label'] for step in plain['steps']))
        plan = deepcopy(f.plan)
        plan['workpacks'][0]['environment'] = {'python': 'python', 'modules': ['json'], 'paths': []}
        progress, future = observation._work_history([], 'TEST-PREPARED', plan, {})
        self.assertEqual(progress, plain_progress)
        self.assertEqual(len(future['steps']), 8)
        environment = [step for step in future['steps'] if '环境检查' in step['label']]
        self.assertEqual(len(environment), 1)
        self.assertEqual(environment[0]['state'], 'NOT_STARTED')
        bound = {'prepared_event_id': 'TEST-PREPARED', 'attempt_id': 'TEST-ATTEMPT',
                 'workpack_id': 'IMPLEMENT-READER'}
        events = [{'event_id': 'TEST-START', 'stream_revision': 1,
                   'event_type': 'BUILD_ATTEMPT_STARTED', 'payload': bound}]
        for revision, phase, case_id in ((2, 'PREFLIGHT', None), (3, 'IMPLEMENTATION', None),
                                        (4, 'VERIFICATION', 'READ-ROWS')):
            events.append({'event_id': 'TEST-OBSERVED-' + str(revision), 'stream_revision': revision,
                'event_type': 'BUILD_COMMAND_OBSERVED', 'payload': {**bound, 'phase': phase, 'case_id': case_id,
                'command_id': 'TEST-COMMAND-' + str(revision), 'result': {'status': 'PASS', 'exit_code': 0}}})
        progress, observed = observation._work_history(events, 'TEST-PREPARED', plan, {})
        self.assertEqual(progress, plain_progress, 'command observations do not constitute final acceptance')
        self.assertEqual(next(step for step in observed['steps'] if '环境检查' in step['label'])['state'], 'PASS')
        self.assertEqual(next(step for step in observed['steps'] if step['label'].endswith('/ 实施'))['state'],
                         'COMPLETED')
        self.assertEqual(next(step for step in observed['steps'] if 'READ-ROWS' in step['label'])['state'], 'PASS')
        focused = next(step for step in observed['steps'] if step['step_id'] == observed['current_step_id'])
        self.assertIn('REJECT-MALFORMED', focused['label'])
        self.assertEqual(focused['state'], 'NOT_STARTED')
        self.assertFalse(f.runner.invocations)
        self.assertFalse(f.events())

    def test_work_units_follow_adopted_plan_without_adopting_a_future_proposal(self):
        helper = replan_support.BuildReplanTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        self.f = helper.f
        self.f.scope.update(expires_at='2099-01-01T00:00:00Z', max_attempts=24)
        self.f.prepare()
        merged = helper.merged()
        helper.record(merged)
        self.assert_progress(self.project(), 0, 2, current=0)
        self.assertEqual(self.f.advance()['status'], 'PLAN_CHECKS_ACCEPTED')
        adopted = self.project()
        self.assert_progress(adopted, 1, 1, current=1)
        self.assertEqual(len(adopted['business']['workflow']['steps']), 5)
        future = deepcopy(merged)
        future['revision'] += 1
        future['workpacks'][0]['goal'] += ' Future proposal only.'
        helper.record(future)
        self.assertEqual(self.project()['business']['work_progress'], adopted['business']['work_progress'])
        self.assertEqual(self.project()['business']['workflow'], adopted['business']['workflow'])


if __name__ == '__main__':
    unittest.main()
