"""Budget preparation hints and early layout checks; no real model calls."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
import unittest

from harness_foundry_factory.build_display import render_build_readback
from harness_foundry_factory.build_entrypoint import read_build
from harness_foundry_factory.build_preview import preview_build
from harness_foundry_factory.build_runtime import prepare_build_authorization, approve_build_authorization
from harness_foundry_factory.build_state import budget_planning_readback
from harness_foundry_factory.coding_process import instruction_read_preflight
from harness_foundry_factory.build_types import RequestValidationError
import test_build_runtime as support


class BudgetPlanningTests(unittest.TestCase):
    def setUp(self):
        self.f = support.BuildRuntimeTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def grant(self, identity=None):
        return next(g for g in read_build(self.f.store.database_path, self.f.program)['authorizations']
                    if g['prepared_event_id'] == (identity or self.f.prepared_id))

    def test_initial_reference_distinguishes_attempts_model_and_checks_without_mutation(self):
        f = self.f
        f._codex_fixture_runner([])
        original = deepcopy((f.plan, f.scope))
        result = budget_planning_readback(f.plan, f.scope)
        self.assertEqual(result['first_pass_reference'], {'production_attempts': 2, 'model_invocations': 1,
            'independent_check_commands': 3, 'declared_environment_preflights': 0})
        self.assertEqual(result['warnings'], [])
        self.assertFalse(result['duration_and_monetary_cost_estimated'])
        self.assertEqual((f.plan, f.scope), original)

    def test_low_budget_is_advisory_not_new_gate_or_automatic_increase(self):
        f = self.f
        f.scope.update(max_attempts=1, max_task_attempts=1)
        f.prepare()
        before = deepcopy(f.events())
        result = self.grant()
        self.assertIn('TOTAL_BELOW_INITIAL_PASS', result['budget_planning']['warnings'])
        self.assertIn('NO_TASK_REPAIR_RESERVE', result['budget_planning']['warnings'])
        self.assertEqual(result['scope']['max_attempts'], 1)
        self.assertEqual(result['budget']['attempts_consumed'], 0)
        self.assertIn('不阻断', render_build_readback(read_build(f.store.database_path, f.program)))
        self.assertEqual(f.events(), before)
        self.assertEqual(f.controller().advance(f.prepared_id, advance_mode='ONE_ATTEMPT')['attempt_status'], 'ACCEPTED')
        self.assertEqual(self.grant()['budget']['attempts_consumed'], 1)

    def test_exact_first_pass_budget_has_no_claim_of_repair_reserve(self):
        self.f.scope.update(max_attempts=2)
        result = budget_planning_readback(self.f.plan, self.f.scope)
        self.assertEqual(result['warnings'], ['NO_TOTAL_REPAIR_RESERVE'])

    def test_preview_shows_same_reference_without_target_or_program_creation(self):
        f = self.f
        for p in (f.workspace / 'src', f.workspace / 'outputs', f.workspace):
            p.rmdir()
        request = {'preview_path': str(f.root / 'preview.json'),
            'document': {k: v for k, v in f.review.items() if k not in {'presentation', 'decision'}},
            'requirement_ir': f.ir, 'plan': f.plan, 'source_root': str(f.source),
            'manifest': [{'source_id': 'PROJECT-BRIEF', 'path': 'brief.md'}], 'scope': f.scope}
        db = f.root / 'new.sqlite3'
        result = preview_build(request, db, clock=lambda: support.NOW)
        self.assertEqual(result['budget_planning'], budget_planning_readback(f.plan, f.scope))
        self.assertFalse(db.exists())
        self.assertFalse(f.workspace.exists())
        self.assertEqual(preview_build(request, db, clock=lambda: support.NOW), result)

    def test_accepted_retrieval_and_rebind_do_not_predict_repeat_work_or_reset_usage(self):
        f = self.f
        f.scope.update(max_attempts=2, max_task_attempts=1)
        f.prepare()
        self.assertEqual(f.advance()['status'], 'PLAN_CHECKS_ACCEPTED')
        before = deepcopy(f.events())
        count = len(f.runner.invocations)
        for _ in range(2):
            self.assertEqual(self.grant()['budget_planning']['warnings'], [])
            self.assertEqual(self.grant()['budget']['attempts_consumed'], 2)
        self.assertEqual(f.events(), before)
        new = prepare_build_authorization(f.store, f.program, f.proposal_id, f.source_id, f.scope,
            rebind_from=f.prepared_id, **f.kwargs('planning-rebind'))
        self.assertEqual(self.grant(new['event_id'])['budget_planning']['warnings'], [])
        approve_build_authorization(f.store, f.program, new['event_id'],
            human_message_ref='TEST ONLY rebind decision', **f.kwargs('planning-approve'))
        self.assertEqual(f.controller().advance(new['event_id'])['status'], 'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(self.grant(new['event_id'])['budget']['attempts_consumed'], 2)
        self.assertEqual(len(f.runner.invocations), count)

    def test_continuation_reference_never_recounts_unresolved_or_checker_rounds(self):
        f = self.f
        f.scope.update(max_attempts=1, max_task_attempts=1)
        result = budget_planning_readback(f.plan, f.scope, initial_execution=False)
        self.assertEqual(result['basis'], 'PLAN_REFERENCE_NOT_REMAINING_WORK')
        self.assertEqual(result['warnings'], [])

    def test_missing_artifact_file_cannot_be_created_as_write_directory(self):
        f = self.f
        f.scope['task_write_roots']['IMPLEMENT-READER'] = ['src/reader.py']
        with self.assertRaisesRegex(RequestValidationError, 'parent directory'):
            f.prepare()
        self.assertFalse((f.workspace / 'src/reader.py').exists())
        self.assertFalse(f.events('BUILD_ATTEMPT_STARTED'))

    def test_root_below_declared_file_is_also_rejected(self):
        f = self.f
        f.scope['task_write_roots']['IMPLEMENT-READER'] += ['outputs/summary.json/cache']
        with self.assertRaisesRegex(RequestValidationError, 'parent directory'):
            f.prepare()
        self.assertFalse(f.events('BUILD_ATTEMPT_STARTED'))

    def test_missing_codex_instruction_directory_mistake_is_caught_before_dispatch(self):
        self._assert_instruction_root_rejected('AGENTS.md')

    def test_missing_override_instruction_directory_is_caught_before_dispatch(self):
        self._assert_instruction_root_rejected('AGENTS.override.md')

    def _assert_instruction_root_rejected(self, name):
        f = self.f
        f._codex_fixture_runner([])
        f.scope['task_write_roots']['IMPLEMENT-READER'] = ['src', name]
        with self.assertRaisesRegex(RequestValidationError, 'instruction files'):
            f.prepare()
        self.assertFalse((f.workspace / name).exists())
        self.assertFalse(f.events('BUILD_ATTEMPT_STARTED'))

    def test_parent_alias_and_dotted_directory_are_legal(self):
        f = self.f
        (f.workspace / 'source-alias').symlink_to(f.workspace / 'src', target_is_directory=True)
        f.scope['task_write_roots']['IMPLEMENT-READER'] = ['source-alias', 'cache.json']
        f.prepare()
        self.assertEqual(f.advance()['status'], 'PLAN_CHECKS_ACCEPTED')
        self.assertTrue((f.workspace / 'cache.json').is_dir())

    def test_real_instruction_file_under_directory_root_is_legal(self):
        f = self.f
        f._codex_fixture_runner([])
        (f.workspace / 'AGENTS.md').write_text('TEST ONLY project guidance\n')
        f.scope['task_write_roots']['IMPLEMENT-READER'] = ['.']
        f.prepare(approve=False)
        self.assertTrue((f.workspace / 'AGENTS.md').is_file())
        self.assertFalse(f.events('BUILD_ATTEMPT_STARTED'))

    def test_nonempty_override_allows_shadowed_instruction_directory(self):
        f = self.f
        f._codex_fixture_runner([])
        override = f.workspace / 'AGENTS.override.md'
        override.write_text('TEST ONLY selected guidance\n')
        (f.workspace / 'AGENTS.md').mkdir()
        f.scope['task_write_roots']['IMPLEMENT-READER'] += ['AGENTS.md']
        f.prepare(approve=False)
        check = instruction_read_preflight(f.workspace, [f.workspace])
        self.assertIn(str(override), check['instruction_files'])
        self.assertNotIn(str(f.workspace / 'AGENTS.md'), check['instruction_files'])
        self.assertFalse(f.events('BUILD_ATTEMPT_STARTED'))

    def test_linked_override_preserves_priority_and_legal_parent_alias(self):
        f = self.f
        f._codex_fixture_runner([])
        target = f.workspace / 'src/guidance.txt'
        target.write_text('TEST ONLY linked guidance\n')
        (f.workspace / 'AGENTS.override.md').symlink_to('src/guidance.txt')
        (f.workspace / 'AGENTS.md').mkdir()
        (f.workspace / 'source-alias').symlink_to('src', target_is_directory=True)
        f.scope['task_write_roots']['IMPLEMENT-READER'] = ['source-alias', 'AGENTS.md']
        f.prepare(approve=False)
        check = instruction_read_preflight(f.workspace, [f.workspace])
        self.assertIn(str(target), check['instruction_files'])
        self.assertNotIn(str(f.workspace / 'AGENTS.md'), check['instruction_files'])
        self.assertFalse(f.events('BUILD_ATTEMPT_STARTED'))

    def test_empty_override_still_checks_missing_fallback_directory(self):
        f = self.f
        f._codex_fixture_runner([])
        (f.workspace / 'AGENTS.override.md').write_text('')
        f.scope['task_write_roots']['IMPLEMENT-READER'] += ['AGENTS.md']
        with self.assertRaisesRegex(RequestValidationError, 'instruction files'):
            f.prepare()
        self.assertFalse((f.workspace / 'AGENTS.md').exists())
        self.assertFalse(f.events('BUILD_ATTEMPT_STARTED'))

    def test_missing_linked_instruction_target_cannot_be_write_directory(self):
        f = self.f
        f._codex_fixture_runner([])
        (f.workspace / 'AGENTS.md').symlink_to('src/missing-guidance')
        f.scope['task_write_roots']['IMPLEMENT-READER'] += ['src/missing-guidance']
        with self.assertRaisesRegex(RequestValidationError, 'instruction files'):
            f.prepare()
        self.assertFalse((f.workspace / 'src/missing-guidance').exists())
        self.assertFalse(f.events('BUILD_ATTEMPT_STARTED'))

    def test_missing_override_link_target_also_rejects_nested_write_root(self):
        f = self.f
        f._codex_fixture_runner([])
        (f.workspace / 'AGENTS.override.md').symlink_to('guidance-link')
        (f.workspace / 'guidance-link').symlink_to('src/missing-override')
        (f.workspace / 'AGENTS.md').write_text('TEST ONLY fallback\n')
        f.scope['task_write_roots']['IMPLEMENT-READER'] += ['src/missing-override/cache']
        with self.assertRaisesRegex(RequestValidationError, 'instruction files'):
            f.prepare()
        self.assertFalse((f.workspace / 'src/missing-override').exists())
        self.assertFalse(f.events('BUILD_ATTEMPT_STARTED'))

    def test_missing_linked_instruction_can_be_created_under_legal_parent(self):
        f = self.f
        f._codex_fixture_runner([])
        (f.workspace / 'AGENTS.md').symlink_to('src/guidance.txt')
        f.prepare(approve=False)
        self.assertFalse((f.workspace / 'src/guidance.txt').exists())
        before = deepcopy(f.events())
        for _ in range(2):
            self.assertEqual(self.grant()['budget']['attempts_consumed'], 0)
        self.assertEqual(f.events(), before)

    def test_model_receives_whole_turn_limit_and_expiry_reduction(self):
        f = self.f
        f._codex_fixture_runner([])
        f.scope['command_timeout_seconds'] = 1800
        f.prepare()
        controller = f.controller()
        expiry = datetime.fromisoformat(f.scope['expires_at'].replace('Z', '+00:00'))
        controller.clock = lambda: expiry - timedelta(seconds=40)
        _, prepared, plan = controller._current(f.prepared_id)
        before = deepcopy(f.events())
        invocation = controller._invocation(prepared, plan['workpacks'][0], [])
        context = json.loads(invocation['prompt'].split('\n', 1)[1])['task']
        self.assertEqual(context['command_time_budget'], {'configured_seconds': 1800,
            'effective_seconds_at_invocation': 40, 'expires_at': f.scope['expires_at'],
            'applies_to': 'WHOLE_MODEL_INVOCATION'})
        self.assertEqual(invocation['timeout_seconds'], 40)
        self.assertEqual(context['runtime_authorization']['command_timeout_seconds'], 1800)
        self.assertEqual(f.events(), before)

    def test_local_check_has_own_command_limit(self):
        f = self.f
        f.prepare()
        controller = f.controller()
        _, prepared, plan = controller._current(f.prepared_id)
        task = plan['workpacks'][0]
        check = task['verification'][0]
        call = controller._invocation(prepared, task, check['argv'], case_id=check['case_id'])
        context = json.loads(call['prompt'].split('\n', 1)[1])['task']
        self.assertEqual(context['command_time_budget']['applies_to'], 'LOCAL_COMMAND')
        self.assertEqual(call['timeout_seconds'], f.scope['command_timeout_seconds'])

    def test_time_only_rebind_keeps_old_spend_and_waits_for_approval(self):
        f = self.f
        f.prepare()
        f.controller().advance(f.prepared_id, advance_mode='ONE_ATTEMPT')
        scope = {**f.scope, 'command_timeout_seconds': 1200, 'expires_at': '2099-01-01T00:00:00Z'}
        new = prepare_build_authorization(f.store, f.program, f.proposal_id, f.source_id, scope,
            rebind_from=f.prepared_id, **f.kwargs('time-only-rebind'))
        grant = self.grant(new['event_id'])
        self.assertEqual(grant['state'], 'APPROVAL_REQUIRED')
        self.assertEqual(grant['budget']['attempts_consumed'], 1)
        self.assertEqual(grant['scope']['max_attempts'], f.scope['max_attempts'])
        count = len(f.runner.invocations)
        self.assertEqual(f.controller().advance(new['event_id'])['status'], 'BUILD_STOPPED')
        self.assertEqual(len(f.runner.invocations), count)
        approve_build_authorization(f.store, f.program, new['event_id'],
            human_message_ref='TEST ONLY approved time extension', **f.kwargs('time-approve'))
        self.assertEqual(f.controller().advance(new['event_id'])['status'], 'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(self.grant(new['event_id'])['budget']['attempts_consumed'], 2)


if __name__ == '__main__':
    unittest.main()
