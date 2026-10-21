"""WP06 scoped read-only observation with real temporary native event stores.

Local fixture processes verify projection and recovery boundaries; they do not
claim a real model, native sandbox, browser, PiP or human-use acceptance.
"""
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_build_runtime as support
import test_build_resources as resource_support
import test_build_replan as replan_support
from harness_foundry_factory import build_observation as observation
from harness_foundry_factory.build_authoring import record_build_plan_proposal
from harness_foundry_factory.build_repair import request_build_repair
from harness_foundry_factory.build_runtime import prepare_build_authorization, approve_build_authorization
from harness_foundry_factory.build_types import RequestValidationError
from harness_foundry_factory.process_observation import CommandObservation
from harness_foundry_factory.revision_store import RevisionControlEventStore

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'examples/capability-adapters/packages/local-dashboard/1'
_spec = importlib.util.spec_from_file_location('wp06_dashboard_contract', PACKAGE / 'dashboard.py')
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)


class FoundryDashboardTests(unittest.TestCase):
    def setUp(self):
        self.f = support.BuildRuntimeTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.scope.update(expires_at='2099-01-01T00:00:00Z', max_attempts=24)

    def selection(self, prepared=None):
        return {'kind': 'foundry_build', 'project_id': self.f.ir['target']['id'],
                'project_version': 'fixture-v1', 'run_id': 'same-host-run',
                'program_id': self.f.program, 'prepared_event_id': prepared or self.f.prepared_id}

    def project(self, prepared=None):
        selected = self.selection(prepared)
        raw = observation.read_foundry_projection(self.f.store.database_path, selected)
        self.assertEqual(D.normalize_projection(raw, selected), raw, 'projection must fit the delivered WP05 interface')
        self.assertEqual({step['step_id']: step['state'] for step in raw['business']['steps']},
                         self.states(raw), 'steps must not create a second acceptance state')
        return raw

    def read_scope(self, prepared=None):
        return observation.read_build_scope(self.f.store.database_path, self.f.program, prepared or self.f.prepared_id)

    def rebind(self, *, scope=None, origin=None, key='rebind'):
        f = self.f
        prepared = prepare_build_authorization(f.store, f.program, f.proposal_id, f.source_id,
            scope or f.scope, rebind_from=origin or f.prepared_id, **f.kwargs(key))
        approve_build_authorization(f.store, f.program, prepared['event_id'],
            human_message_ref='TEST ONLY fixture approval', **f.kwargs(key + '-approve'))
        return prepared['event_id']

    def once(self, prepared=None):
        return self.f.controller().advance(prepared or self.f.prepared_id, advance_mode='ONE_ATTEMPT')

    @staticmethod
    def states(projection):
        return {item['item_id']: item['state'] for item in projection['business']['items']}

    def assert_completion(self, projection, completed, total=2):
        completion = projection['business']['completion']
        self.assertEqual((completion['completed'], completion['total']), (completed, total))
        self.assertIn('声明检查', completion['label'])
        self.assertIn('非完整 Harness 验收', completion['label'])

    def test_unapproved_scope_is_visible_without_claiming_started_or_complete(self):
        self.f.prepare(approve=False)
        raw = self.project()
        self.assertEqual(raw['selection'], self.selection())
        self.assertIn('APPROVAL_REQUIRED', raw['business']['current'])
        self.assertEqual(set(self.states(raw).values()), {'NOT_STARTED'})
        self.assert_completion(raw, 0)
        self.assertEqual(raw['business']['budget'], {'attempts_consumed': 0, 'attempts_remaining': 24})
        self.assertEqual(raw['business']['current_step_id'], 'IMPLEMENT-READER')
        self.assertEqual(raw['business']['steps'], [
            {'step_id': task['workpack_id'], 'label': task['workpack_id'], 'state': 'NOT_STARTED',
             'detail': '尚无本范围尝试或有效接受记录', 'depends_on': task['depends_on']}
            for task in self.f.plan['workpacks']])
        self.assertFalse(self.f.runner.invocations)
        self.assertFalse(self.read_scope()['writes_performed'])
        self.assertFalse(self.read_scope()['harness_e2e_verified'])

    def test_steps_follow_plan_and_attention_moves_without_adding_attempts_or_substeps(self):
        f = self.f; f.prepare()
        self.assertEqual(self.once()['attempt_status'], 'ACCEPTED')
        before = f.events(); calls = len(f.runner.invocations)
        for _ in range(2):
            displayed = self.project()
            self.assertEqual([step['step_id'] for step in displayed['business']['steps']],
                             ['IMPLEMENT-READER', 'MAKE-REPORT'])
            self.assertEqual(displayed['business']['steps'][1]['depends_on'], ['IMPLEMENT-READER'])
            self.assertEqual(displayed['business']['current_step_id'], 'MAKE-REPORT')
            self.assertEqual(displayed['business']['steps'][0]['detail'],
                             '最近记录阶段：独立检查；声明检查已接受')
            self.assert_completion(displayed, 1)
            self.assertEqual(displayed['business']['budget']['attempts_consumed'], 1)
        self.assertEqual(f.events(), before)
        self.assertEqual(len(f.runner.invocations), calls)
        self.assertEqual(self.once()['attempt_status'], 'ACCEPTED')
        completed = self.project()
        self.assertNotIn('current_step_id', completed['business'])
        self.assert_completion(completed, 2)
        self.assertEqual(completed['business']['budget']['attempts_consumed'], 2)

    def test_attention_uses_latest_unresolved_record_without_inventing_a_command_phase(self):
        self.f.prepare()
        scoped = self.read_scope()
        # Projection-only fixture: command absence is not evidence that a
        # previously started attempt is running, completed, or undispatched.
        scoped['attempts'] = [
            {'workpack_id': identity, 'attempt_id': 'TEST-' + identity,
             'prepared_event_id': self.f.prepared_id, 'proposal_event_id': self.f.proposal_id,
             'status': 'IN_FLIGHT', 'phase': 'NOT_DISPATCHED', 'last_record_revision': revision}
            for identity, revision in (('IMPLEMENT-READER', 10), ('MAKE-REPORT', 20))]
        scoped['authorization']['budget'].update(attempts_consumed=2, attempts_remaining=22)
        with patch.object(observation, 'read_build_scope', return_value=scoped):
            displayed = self.project()
        self.assertEqual(displayed['business']['current_step_id'], 'MAKE-REPORT')
        self.assertTrue(all(step['state'] == 'UNKNOWN' and step['detail'] == '尝试待结算'
                            for step in displayed['business']['steps']))
        self.assert_completion(displayed, 0)
        self.assertEqual(displayed['business']['budget']['attempts_consumed'], 2)

        scoped['invalidations'] = [{'event_id': 'TEST-INVALIDATION', 'stream_revision': 30,
                                   'workpack_ids': ['IMPLEMENT-READER']}]
        with patch.object(observation, 'read_build_scope', return_value=scoped):
            invalidated = self.project()
        self.assertEqual(invalidated['business']['current_step_id'], 'IMPLEMENT-READER')
        self.assertEqual(invalidated['business']['steps'][0]['state'], 'INVALIDATED')
        self.assertEqual(invalidated['business']['budget'], displayed['business']['budget'])

    def test_missing_scope_or_database_never_falls_back_or_creates_a_store(self):
        self.f.prepare()
        before = self.f.events()
        for value in (None, '', ' ', 'CEVT-DOES-NOT-EXIST'):
            with self.subTest(prepared=value), self.assertRaises(RequestValidationError):
                observation.read_build_scope(self.f.store.database_path, self.f.program, value)
        absent = self.f.root / 'absent' / 'control.sqlite3'
        with self.assertRaises(RequestValidationError):
            observation.read_build_scope(absent, self.f.program, self.f.prepared_id)
        self.assertFalse(absent.parent.exists())
        self.assertEqual(self.f.events(), before)

    def test_program_target_and_incomplete_selection_cannot_borrow_another_scope(self):
        self.f.prepare()
        selection = self.selection()
        variants = [{**selection, 'program_id': 'OTHER-PROGRAM'},
                    {**selection, 'project_id': 'OTHER-TARGET'}, {**selection, 'kind': 'harness_run'}]
        variants += [{k: v for k, v in selection.items() if k != missing}
                     for missing in ('program_id', 'prepared_event_id', 'project_version', 'run_id')]
        for value in variants:
            with self.subTest(selection=value), self.assertRaises(RequestValidationError):
                observation.read_foundry_projection(self.f.store.database_path, value)
        self.assertEqual(self.project()['selection'], selection)
        self.assertFalse(self.f.runner.invocations)

    def test_same_project_version_run_and_program_keep_independent_prepared_scopes(self):
        f = self.f; f.prepare()
        self.assertEqual(self.once()['attempt_status'], 'ACCEPTED')
        other = prepare_build_authorization(f.store, f.program, f.proposal_id, f.source_id,
            f.scope, **f.kwargs('independent-prepare'))['event_id']
        first, second = self.project(), self.project(other)
        self.assertEqual({k: v for k, v in first['selection'].items() if k != 'prepared_event_id'},
                         {k: v for k, v in second['selection'].items() if k != 'prepared_event_id'})
        self.assert_completion(first, 1)
        self.assert_completion(second, 0)
        self.assertTrue(first['business']['recent'][0].startswith('Attempt '))
        self.assertTrue(first['business']['recent'][-1].startswith('本范围展示计划 '))
        self.assertEqual(first['business']['scope_ref'], f.prepared_id)
        self.assertEqual(second['business']['scope_ref'], other)
        self.assertEqual(first['business']['budget']['attempts_consumed'], 1)
        self.assertEqual(second['business']['budget']['attempts_consumed'], 0)
        self.assertFalse(self.read_scope(other)['attempts'])

    def test_one_event_read_stays_bound_when_a_new_proposal_is_committed(self):
        f = self.f; f.prepare()
        before = f.events(); old_proposal = f.proposal_id
        next_plan = deepcopy(f.plan); next_plan['revision'] += 1
        next_plan['workpacks'][0]['goal'] = 'Next proposal, not the selected preparation.'
        original = RevisionControlEventStore.list_events
        reads = []
        def interleaved(store, program_id):
            rows = original(store, program_id)
            if store.read_only:
                reads.append((program_id, len(rows)))
                if len(reads) == 1:
                    record_build_plan_proposal(f.store, f.ir, next_plan, document_review=f.review,
                        expected_revision=len(before), idempotency_key='concurrent-proposal', created_at=support.NOW)
            return rows
        with patch.object(RevisionControlEventStore, 'list_events', interleaved):
            scoped = self.read_scope()
        self.assertEqual(reads, [(f.program, len(before))])
        self.assertEqual(scoped['stream_revision'], len(before))
        self.assertEqual(scoped['authorization']['proposal_event_id'], old_proposal)
        self.assertEqual(scoped['authorization']['plan'], f.plan)
        refreshed = self.read_scope()
        self.assertEqual(refreshed['stream_revision'], len(before) + 1)
        self.assertEqual(refreshed['authorization']['plan'], f.plan)
        self.assertEqual(self.project()['business']['proposal_ref'], old_proposal)

    def replan_fixture(self):
        helper = replan_support.BuildReplanTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        self.f = helper.f
        self.f.scope.update(expires_at='2099-01-01T00:00:00Z', max_attempts=24)
        return helper

    def test_same_prepared_uses_executed_merged_plan_without_adopting_unstarted_proposals(self):
        helper = self.replan_fixture()
        f = self.f; f.prepare()
        original_proposal = f.proposal_id
        original_plan = deepcopy(f.plan)
        merged = helper.merged()
        adopted_proposal = helper.record(merged)['event_id']
        pending = self.project()
        self.assertEqual(pending['business']['proposal_ref'], original_proposal)
        self.assertEqual(set(self.states(pending)), {'IMPLEMENT-READER', 'MAKE-REPORT'})
        self.assert_completion(pending, 0, 2)
        self.assertEqual(pending['business']['budget']['attempts_consumed'], 0)

        self.assertEqual(f.advance()['status'], 'PLAN_CHECKS_ACCEPTED')
        displayed = self.project()
        self.assertEqual(displayed['business']['proposal_ref'], adopted_proposal)
        self.assertEqual(self.states(displayed), {'COMBINED': 'ACCEPTED'})
        self.assertEqual([step['step_id'] for step in displayed['business']['steps']], ['COMBINED'])
        self.assertNotIn('current_step_id', displayed['business'])
        self.assert_completion(displayed, 1, 1)
        self.assertEqual(displayed['business']['budget']['attempts_consumed'], 1)
        scoped = self.read_scope()
        self.assertEqual(scoped['authorization']['proposal_event_id'], original_proposal)
        self.assertEqual(scoped['authorization']['plan'], original_plan)
        self.assertEqual(scoped['execution_proposal_event_id'], adopted_proposal)
        self.assertEqual(scoped['execution_plan'], merged)
        self.assertEqual(len(f.events('BUILD_AUTHORIZATION_APPROVED')), 1)
        self.assertEqual(len(f.runner.invocations), 4)

        later = deepcopy(merged); later['revision'] += 1
        later['workpacks'][0]['goal'] += ' TEST proposed future change, not executed.'
        helper.record(later)
        events = f.events()
        for _ in range(2):
            after = self.project()
            self.assertEqual(after['business']['proposal_ref'], adopted_proposal)
            self.assertEqual(self.states(after), {'COMBINED': 'ACCEPTED'})
            self.assert_completion(after, 1, 1)
            self.assertEqual(after['business']['budget'], displayed['business']['budget'])
            self.assertEqual(self.read_scope()['execution_plan'], merged)
        self.assertEqual(f.events(), events)
        self.assertEqual(len(f.runner.invocations), 4)

    def test_same_prepared_uses_executed_split_plan_and_keeps_original_budget_owners(self):
        helper = self.replan_fixture()
        split = helper.prepare_split()
        f = self.f
        original_proposal = f.proposal_id
        original_plan = deepcopy(f.plan)
        adopted_proposal = f.events('BUILD_PLAN_PROPOSED')[-1]['event_id']
        pending = self.project()
        self.assertEqual(pending['business']['proposal_ref'], original_proposal)
        self.assertEqual(self.states(pending), {'COMBINED': 'NOT_STARTED'})
        self.assert_completion(pending, 0, 1)

        self.assertEqual(self.once()['attempt_status'], 'ACCEPTED')
        partial = self.project()
        self.assertEqual(partial['business']['proposal_ref'], adopted_proposal)
        self.assertEqual(self.states(partial), {'IMPLEMENT-READER': 'ACCEPTED', 'MAKE-REPORT': 'NOT_STARTED'})
        self.assertEqual([step['step_id'] for step in partial['business']['steps']],
                         [task['workpack_id'] for task in split['workpacks']])
        self.assertEqual(partial['business']['current_step_id'], 'MAKE-REPORT')
        self.assert_completion(partial, 1, 2)
        self.assertEqual(partial['business']['budget']['attempts_consumed'], 1)
        self.assertEqual(f.advance()['status'], 'PLAN_CHECKS_ACCEPTED')
        displayed = self.project()
        self.assertEqual(displayed['business']['proposal_ref'], adopted_proposal)
        self.assertEqual(self.states(displayed), {'IMPLEMENT-READER': 'ACCEPTED', 'MAKE-REPORT': 'ACCEPTED'})
        self.assert_completion(displayed, 2, 2)
        self.assertEqual(displayed['business']['budget']['attempts_consumed'], 2)
        scoped = self.read_scope()
        self.assertEqual(scoped['authorization']['proposal_event_id'], original_proposal)
        self.assertEqual(scoped['authorization']['plan'], original_plan)
        self.assertEqual(scoped['authorization']['budget']['task_attempts_consumed'], {'COMBINED': 2})
        self.assertEqual(scoped['execution_plan'], split)
        self.assertEqual(scoped['execution_proposal_event_id'], adopted_proposal)
        self.assertEqual(len(f.events('BUILD_AUTHORIZATION_APPROVED')), 1)
        calls = len(f.runner.invocations)

        later = deepcopy(split); later['revision'] += 1
        later['workpacks'][1]['goal'] += ' TEST future proposal only.'
        helper.record(later)
        events = f.events()
        for _ in range(2):
            after = self.project()
            self.assertEqual(after['business']['proposal_ref'], adopted_proposal)
            self.assert_completion(after, 2, 2)
            self.assertEqual(after['business']['budget'], displayed['business']['budget'])
            self.assertEqual(self.read_scope()['execution_plan'], split)
        self.assertEqual(f.events(), events)
        self.assertEqual(len(f.runner.invocations), calls)

    def enable_fixture_codex_reader(self):
        # Existing test receiver writes only fixture bytes and never invokes a model.
        local_runner = self.f.runner
        captured = []
        self.f.runner = self.f._codex_fixture_runner(captured)
        return lambda: len(local_runner.invocations) + len(captured)

    def test_invalidated_acceptance_is_not_counted_from_old_accepted_history(self):
        calls = self.enable_fixture_codex_reader()
        f = self.f; f.prepare(); self.assertEqual(f.advance()['status'], 'PLAN_CHECKS_ACCEPTED')
        self.assert_completion(self.project(), 2)
        reader = self.read_scope()['accepted']['IMPLEMENT-READER']
        request_build_repair(f.controller(), {'program_id': f.program, 'prepared_event_id': f.prepared_id,
            'expected_revision': len(f.events()), 'idempotency_key': 'confirmed-fixture-finding',
            'targets': [{'artifact_id': 'READER-SOURCE', 'accepted_attempt_id': reader['attempt_id']}],
            'finding': {'requirement_refs': ['PROJECT-BRIEF:L1-L2'], 'reason': 'TEST confirmed additional case',
                        'evidence_refs': ['TEST fixture receipt'], 'repair_goal': 'repair and recheck'}})
        observed = self.project()
        self.assert_completion(observed, 0)
        self.assertEqual(set(self.states(observed).values()), {'INVALIDATED'})
        self.assertEqual(observed['business']['current_step_id'], 'IMPLEMENT-READER')
        self.assertTrue(all('原接受已失效' in step['detail'] for step in observed['business']['steps']))
        self.assertEqual(observed['business']['budget']['attempts_consumed'], 2)
        self.assertEqual(calls(), 5)
        self.assertEqual(len(f.events('BUILD_ATTEMPT_STARTED')), 2)

    def test_legal_rebind_reuses_acceptance_and_counts_lineage_only_once(self):
        f = self.f; f.prepare(); self.once()
        second = self.rebind()
        third = self.rebind(origin=second, key='third-preparation')
        before = f.events(); calls = len(f.runner.invocations)
        for _ in range(3):
            projection = self.project(third)
            self.assert_completion(projection, 1)
            self.assertEqual(projection['business']['budget']['attempts_consumed'], 1)
        accepted_item = next(i for i in projection['business']['items'] if i['state'] == 'ACCEPTED')
        self.assertIn('合法复用', accepted_item['label'])
        self.assertIn('Prepared ' + f.prepared_id, accepted_item['evidence_refs'])
        self.assertEqual(projection['business']['current_step_id'], 'MAKE-REPORT')
        self.assertEqual(projection['business']['steps'][0]['detail'], '合法复用的已接受成果')
        self.assertFalse(self.read_scope(third)['attempts'], 'lineage is not copied into this preparation history')
        self.assertIn('SUPERSEDED', self.project()['business']['current'])
        self.assertEqual(f.events(), before)
        self.assertEqual(len(f.runner.invocations), calls)

    def test_inherited_acceptance_invalidation_without_local_attempt_remains_visible(self):
        calls = self.enable_fixture_codex_reader()
        f = self.f; f.prepare(); f.advance()
        next_prepared = self.rebind()
        scoped = self.read_scope(next_prepared)
        self.assertFalse(scoped['attempts'])
        reader = scoped['accepted']['IMPLEMENT-READER']
        request_build_repair(f.controller(), {'program_id': f.program, 'prepared_event_id': next_prepared,
            'expected_revision': len(f.events()), 'idempotency_key': 'inherited-fixture-finding',
            'targets': [{'artifact_id': 'READER-SOURCE', 'accepted_attempt_id': reader['attempt_id']}],
            'finding': {'requirement_refs': ['PROJECT-BRIEF:L1-L2'], 'reason': 'TEST inherited extra case',
                        'evidence_refs': ['TEST inherited receipt'], 'repair_goal': 'repair and recheck'}})
        displayed = self.project(next_prepared)
        self.assert_completion(displayed, 0)
        self.assertEqual(set(self.states(displayed).values()), {'INVALIDATED'})
        self.assertFalse(self.read_scope(next_prepared)['attempts'])
        self.assertEqual(displayed['business']['budget']['attempts_consumed'], 2)
        self.assertEqual(calls(), 5)
        # A later valid repair is current acceptance, not a permanent old warning.
        self.assertEqual(f.controller().advance(next_prepared)['status'], 'PLAN_CHECKS_ACCEPTED')
        repaired = self.project(next_prepared)
        self.assert_completion(repaired, 2)
        self.assertEqual(set(self.states(repaired).values()), {'ACCEPTED'})
        self.assertFalse(repaired['business']['pending'])
        self.assertNotIn('current_step_id', repaired['business'])
        self.assertEqual(repaired['business']['budget']['attempts_consumed'], 4)

    def test_changed_checker_keeps_old_evidence_but_requires_reverification(self):
        f = self.f; f.prepare(); f.advance()
        old_events = f.events()
        new_root = f.root / 'updated-verifier'; new_root.mkdir()
        (new_root / 'check.py').write_text(support.VERIFIER + '\n# updated checker binding\n')
        new = self.rebind(scope={**f.scope, 'verification_root': str(new_root)})
        calls = len(f.runner.invocations)
        projected = self.project(new)
        self.assert_completion(projected, 0)
        self.assertEqual(set(self.states(projected).values()), {'PENDING'})
        self.assertEqual(projected['business']['current_step_id'], 'IMPLEMENT-READER')
        self.assertTrue(all(step['detail'] == '保留旧产物，待独立复验'
                            for step in projected['business']['steps']))
        self.assertEqual(self.read_scope(new)['reverification_pending'], ['IMPLEMENT-READER', 'MAKE-REPORT'])
        self.assertEqual(projected['business']['budget']['attempts_consumed'], 2)
        self.assertEqual(f.events()[:len(old_events)], old_events)
        self.assertEqual(len(f.runner.invocations), calls)
        self.assert_completion(self.project(), 2)

    def test_not_dispatched_preserves_spent_budget_without_repairing_or_recounting(self):
        f = self.f
        f.plan['schema_version'] = '1.1'
        f.plan['workpacks'][0]['effects'] = {'allowed': ['src/reader.py'], 'required': ['src/reader.py'], 'must_preserve': []}
        f.prepare()
        with patch('harness_foundry_factory.build_runtime.snapshot_effects', side_effect=OSError('TEST baseline unavailable')):
            self.assertEqual(self.once()['attempt_status'], 'NOT_DISPATCHED')
        before = f.events()
        for _ in range(3):
            projected = self.project()
            self.assert_completion(projected, 0)
            self.assertEqual(self.states(projected)['IMPLEMENT-READER'], 'NOT_RUN')
            self.assertEqual(projected['business']['current_step_id'], 'IMPLEMENT-READER')
            self.assertEqual(projected['business']['steps'][0]['detail'],
                             '未派发，已用预算保留')
            self.assertEqual(projected['business']['budget']['attempts_consumed'], 1)
            self.assertIn('ADVANCE_WITH_CURRENT_SCOPE_AND_BUDGET', ' '.join(projected['business']['pending']))
        self.assertEqual(f.events(), before)
        self.assertFalse(f.runner.invocations)

    def interrupted_durable_command(self):
        f = self.f
        f.runner = resource_support.DurableResourceFixtureRunner()
        f.prepare()
        def interrupt(*args):
            raise support.InjectedControllerCrash()
        f.runner.after_run = interrupt
        with self.assertRaises(support.InjectedControllerCrash):
            self.once()
        f.runner.after_run = None
        return Path(f.runner.invocations[0]['observation_root'])

    def test_durable_report_is_observed_without_recovery_replay_or_database_writes(self):
        root = self.interrupted_durable_command()
        f = self.f; before = f.events(); database = f.store.database_path.read_bytes()
        attachments = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
        with (patch.object(CommandObservation, 'recover', side_effect=AssertionError('observer cannot recover')),
              patch.object(support.BuildController, 'advance', side_effect=AssertionError('observer cannot dispatch')),
              patch.object(RevisionControlEventStore, 'append_batch', side_effect=AssertionError('observer cannot write'))):
            for _ in range(2):
                scoped = self.read_scope()
                self.assertEqual(scoped['attempts'][0]['recovery']['host_observation']['observation_state'], 'DURABLE_RESULT_AVAILABLE')
                displayed = self.project()
                self.assert_completion(displayed, 0)
                self.assertEqual(displayed['business']['current_step_id'], 'IMPLEMENT-READER')
                self.assertEqual(displayed['business']['steps'][0]['state'], 'UNKNOWN')
                self.assertEqual(displayed['business']['steps'][0]['detail'], '最近记录阶段：实施；尝试待结算')
                self.assertIn('已有持久观测', ' '.join(displayed['observation']['gaps']))
                self.assertIn('不重放', ' '.join(displayed['observation']['gaps']))
        self.assertEqual(f.events(), before)
        self.assertEqual(f.store.database_path.read_bytes(), database)
        self.assertEqual({p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}, attachments)
        self.assertEqual(len(f.runner.invocations), 1)
        self.assertFalse(f.events('BUILD_COMMAND_OBSERVED'))

    def test_output_activity_updates_without_event_revision_or_completion_change(self):
        root = self.interrupted_durable_command()
        for name in ('stdout.bin', 'stderr.bin'):
            os.utime(root / name, (1000, 1000))
        before = self.project()
        with (root / 'stdout.bin').open('ab') as stream:
            stream.write(b'ADDITIONAL-PRIVATE-OUTPUT')
        os.utime(root / 'stdout.bin', (2000, 2000))
        after = self.project()
        self.assertEqual(before['business']['source_revision'], after['business']['source_revision'])
        self.assertNotEqual(before['observation']['activity']['last_output_at'], after['observation']['activity']['last_output_at'])
        self.assertEqual(before['business']['completion'], after['business']['completion'])
        self.assertEqual(before['business']['budget'], after['business']['budget'])
        self.assertNotIn('ADDITIONAL-PRIVATE-OUTPUT', json.dumps(after))

    def test_activity_keeps_previous_command_until_latest_outputs_without_crossing_prepared(self):
        f = self.f
        f.plan['workpacks'][0]['local_argv'][-1] += '; print("FIRST-COMMAND-PRIVATE-OUTPUT")'
        durable = resource_support.DurableResourceFixtureRunner()
        def interrupt_before_check(invocation, before_dispatch):
            if invocation['phase'] == 'VERIFICATION':
                raise support.InjectedControllerCrash()
            return durable(invocation, before_dispatch)
        f.runner = interrupt_before_check
        f.prepare()
        with self.assertRaises(support.InjectedControllerCrash):
            self.once()
        first_root = Path(durable.invocations[0]['observation_root'])
        for name in ('stdout.bin', 'stderr.bin'):
            os.utime(first_root / name, (1000, 1000))
        latest_command = f.events('BUILD_COMMAND_PLANNED')[-1]['payload']
        latest_root = Path(latest_command['observation_root'])
        self.assertEqual(latest_command['phase'], 'VERIFICATION')
        self.assertNotEqual(first_root, latest_root)
        self.assertFalse((latest_root / 'stdout.bin').exists())
        self.assertEqual(len(f.events('BUILD_COMMAND_OBSERVED')), 1)
        first = self.project()
        self.assertEqual(first['business']['steps'][0]['detail'], '最近记录阶段：独立检查；尝试待结算')
        self.assertEqual(first['business']['steps'][0]['state'], 'UNKNOWN')
        expected_first = datetime.fromtimestamp(1000, timezone.utc).isoformat()
        self.assertEqual(first['observation']['activity']['last_output_at'], expected_first)

        # Append a separate preparation's fixture command facts; its later
        # activity must never be included in the selected preparation's view.
        other_prepared = prepare_build_authorization(f.store, f.program, f.proposal_id, f.source_id,
            f.scope, **f.kwargs('other-activity-prepare'))['event_id']
        other_root = f.root / 'other-command-observation'; other_root.mkdir()
        (other_root / 'stdout.bin').write_bytes(b'OTHER-PREPARED-PRIVATE-OUTPUT')
        os.utime(other_root / 'stdout.bin', (3000, 3000))
        other_start = {**f.events('BUILD_ATTEMPT_STARTED')[0]['payload'],
                       'prepared_event_id': other_prepared, 'attempt_id': 'TEST-OTHER-ACTIVITY'}
        other_command = {**latest_command, 'prepared_event_id': other_prepared,
                         'attempt_id': other_start['attempt_id'], 'command_id': 'TEST-OTHER-COMMAND',
                         'observation_root': str(other_root)}
        f.store.append_batch(f.program, [
            {'event_type': 'BUILD_ATTEMPT_STARTED', 'payload': other_start},
            {'event_type': 'BUILD_COMMAND_PLANNED', 'payload': other_command}],
            **f.kwargs('other-activity-fixture'))
        isolated = self.project()
        self.assertEqual(isolated['observation']['activity']['last_output_at'], expected_first)
        self.assertEqual(isolated['business']['completion'], first['business']['completion'])
        self.assertEqual(isolated['business']['budget'], first['business']['budget'])

        latest_root.mkdir(exist_ok=True)
        (latest_root / 'stdout.bin').write_bytes(b'LATEST-CHECK-PRIVATE-OUTPUT')
        os.utime(latest_root / 'stdout.bin', (2000, 2000))
        updated = self.project()
        self.assertEqual(updated['observation']['activity']['last_output_at'],
                         datetime.fromtimestamp(2000, timezone.utc).isoformat())
        self.assertEqual(updated['business']['source_revision'], isolated['business']['source_revision'])
        self.assertEqual(updated['business']['completion'], isolated['business']['completion'])
        self.assertEqual(updated['business']['budget'], isolated['business']['budget'])
        self.assert_completion(updated, 0)
        self.assertEqual(updated['business']['budget']['attempts_consumed'], 1)
        self.assertEqual(len(durable.invocations), 1)
        self.assertNotIn('PRIVATE-OUTPUT', json.dumps(updated))

    def test_expiry_updates_without_event_revision_or_budget_change(self):
        f = self.f; f.prepare()
        with patch('harness_foundry_factory.build_entrypoint.datetime') as clock:
            clock.now.return_value = datetime(2098, 12, 31, tzinfo=timezone.utc)
            before = self.project()
            clock.now.return_value = datetime(2099, 1, 2, tzinfo=timezone.utc)
            after = self.project()
        self.assertIn('APPROVED', before['business']['current'])
        self.assertIn('EXPIRED', after['business']['current'])
        self.assertEqual(before['business']['source_revision'], after['business']['source_revision'])
        self.assertEqual(before['business']['budget'], after['business']['budget'])
        self.assertFalse(f.runner.invocations)

    def test_display_does_not_export_product_paths_argv_source_or_raw_process_output(self):
        f = self.f
        secret = 'TEST-PRIVATE-RAW-OUTPUT-DO-NOT-EXPOSE'
        f.plan['workpacks'][0]['local_argv'][-1] += '; print(' + repr(secret) + ')'
        f.prepare(); f.advance()
        stored = json.dumps(f.events())
        self.assertIn(secret, stored, 'fixture must contain sensitive raw output in the original host record')
        projected = json.dumps(self.project(), ensure_ascii=False)
        for private in (str(f.root), 'src/reader.py', secret, 'local_argv', f.source_text.strip()):
            self.assertNotIn(private, projected)
        self.assertIn('Prepared ' + f.prepared_id, projected)
        self.assertIn('Proposal ' + f.proposal_id, projected)
        self.assert_completion(self.project(), 2)


if __name__ == '__main__':
    unittest.main()
