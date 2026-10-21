"""Runtime authority in model prompts; synthetic grants/runners, no model calls.

Disposable test Programs only. Static review/inspection remains non-executing;
local fixture checks do not qualify a native receiver or a target Harness.
"""
from copy import deepcopy
from datetime import datetime
import json
import unittest
from unittest.mock import patch

from harness_foundry_factory.build_authoring import (
    read_build_plan_proposal, read_build_task_context, record_build_plan_proposal)
from harness_foundry_factory.build_runtime import (
    BuildController, approve_build_authorization, prepare_build_authorization,
    revoke_build_authorization)
from harness_foundry_factory.build_types import RequestValidationError
import test_build_runtime as support


class RuntimeTaskContextTests(unittest.TestCase):
    def setUp(self):
        self.f = support.BuildRuntimeTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.calls = []
        self.f.runner = self.f._codex_fixture_runner(self.calls)

    def prepare(self):
        self.f.prepare()
        controller = self.f.controller()
        _, prepared, plan = controller._current(self.f.prepared_id)
        return controller, prepared, plan['workpacks'][0]

    @staticmethod
    def context(invocation):
        return json.loads(invocation['prompt'].split('\n', 1)[1])['task']

    def revoke(self):
        f = self.f
        revoke_build_authorization(f.store, f.program, f.prepared_id,
                                   **f.kwargs('fixture-revoke'))

    def rebind(self, *, approve=True):
        f = self.f
        prepared = prepare_build_authorization(f.store, f.program, f.proposal_id,
            f.source_id, f.scope, rebind_from=f.prepared_id, **f.kwargs('fixture-rebind'))
        if approve:
            approve_build_authorization(f.store, f.program, prepared['event_id'],
                human_message_ref='TEST ONLY not a real approval', **f.kwargs('fixture-rebind-approve'))
        return prepared['event_id']

    def test_authorized_prompt_is_bound_without_claiming_start_or_acceptance(self):
        f = self.f
        controller, prepared, task = self.prepare()
        before = f.events()
        invocation = controller._invocation(prepared, task, [])
        context = self.context(invocation)
        self.assertEqual(context['status'], 'TASK_CONTEXT_RUNTIME_AUTHORIZED')
        self.assertTrue(context['authority_validated'])
        self.assertFalse(context['execution_started'])
        self.assertFalse(context['behavior_verified'])
        authority = context['runtime_authorization']
        self.assertEqual(authority['prepared_event_id'], f.prepared_id)
        self.assertEqual(authority['approval_event_id'], f.events('BUILD_AUTHORIZATION_APPROVED')[0]['event_id'])
        self.assertEqual(authority['approved_proposal_event_id'], f.proposal_id)
        self.assertEqual(authority['proposal_event_id'], context['proposal_binding']['proposal_event_id'])
        self.assertEqual(authority['source_event_id'], f.source_id)
        self.assertEqual(authority['workpack_id'], task['workpack_id'])
        for key in ('model', 'allow_model_service', 'command_timeout_seconds',
                    'max_attempts', 'max_task_attempts', 'expires_at'):
            self.assertEqual(authority[key], prepared['scope'][key])
        self.assertEqual(invocation['scope'], prepared['scope'])
        self.assertEqual(invocation['write_roots'], [str(f.workspace / 'src')])
        self.assertEqual(f.events(), before)
        self.assertFalse(self.calls)
        self.assertIn('historical preparation-only or document-review notes', invocation['prompt'])

    def test_static_inspection_and_review_still_do_not_grant_runtime_authority(self):
        f = self.f
        controller, prepared, task = self.prepare()
        controller._invocation(prepared, task, [])
        context = read_build_task_context(f.store, f.program, task['workpack_id'], event_id=f.proposal_id)
        self.assertEqual(context['status'], 'TASK_CONTEXT_NOT_AUTHORIZED')
        self.assertFalse(context['authority_validated'])
        self.assertNotIn('runtime_authorization', context)
        review = read_build_plan_proposal(f.store, f.program)['document_review']
        self.assertFalse(review['runtime_authorized'])
        self.assertFalse(f.events('BUILD_ATTEMPT_STARTED'))

    def test_revocation_after_upstream_check_prevents_prompt_authorization(self):
        controller, prepared, task = self.prepare()
        self.revoke()
        with self.assertRaisesRegex(RequestValidationError, 'absent or revoked'):
            controller._invocation(prepared, task, [])
        self.assertEqual(controller.advance(self.f.prepared_id)['status'], 'BUILD_STOPPED')
        self.assertFalse(self.calls)
        self.assertFalse(self.f.events('BUILD_ATTEMPT_STARTED'))

    def test_expiration_after_upstream_check_prevents_prompt_authorization(self):
        controller, prepared, task = self.prepare()
        controller.clock = lambda: datetime.fromisoformat(prepared['scope']['expires_at'].replace('Z', '+00:00'))
        with self.assertRaisesRegex(RequestValidationError, 'expired'):
            controller._invocation(prepared, task, [])
        self.assertEqual(controller.advance(self.f.prepared_id)['status'], 'BUILD_STOPPED')
        self.assertFalse(self.calls)
        self.assertFalse(self.f.events('BUILD_ATTEMPT_STARTED'))

    def test_new_unapproved_prepared_cannot_inherit_old_approval(self):
        controller, prepared, task = self.prepare()
        other_id = self.rebind(approve=False)
        changed = {**prepared, 'prepared_event_id': other_id}
        with self.assertRaisesRegex(RequestValidationError, 'absent or revoked'):
            controller._invocation(changed, task, [])
        self.assertEqual(controller.advance(other_id)['status'], 'BUILD_STOPPED')
        self.assertFalse(self.calls)
        self.assertFalse(self.f.events('BUILD_ATTEMPT_STARTED'))

    def test_forged_scope_or_task_cannot_be_marked_authorized(self):
        controller, prepared, task = self.prepare()
        bad_prepared = deepcopy(prepared)
        bad_prepared['scope']['max_attempts'] += 1
        with self.assertRaisesRegex(RequestValidationError, 'current prepared scope and Plan'):
            controller._invocation(bad_prepared, task, [])
        bad_task = {**task, 'goal': 'outside current task'}
        with self.assertRaisesRegex(RequestValidationError, 'current approved Plan'):
            controller._invocation(prepared, bad_task, [])
        self.assertFalse(self.calls)
        self.assertFalse(self.f.events('BUILD_ATTEMPT_STARTED'))

    def test_legal_replan_binds_current_plan_and_original_grant_without_new_gate(self):
        f = self.f
        controller, prepared, task = self.prepare()
        plan = deepcopy(f.plan)
        plan['revision'] += 1
        plan['workpacks'][0]['goal'] = 'Use a clearer implementation of the same row contract'
        revised = record_build_plan_proposal(f.store, f.ir, plan, document_review=f.review,
                                            **f.kwargs('fixture-legal-replan'))
        with self.assertRaisesRegex(RequestValidationError, 'current prepared scope and Plan'):
            controller._invocation(prepared, task, [])
        _, current, current_plan = controller._current(f.prepared_id)
        context = self.context(controller._invocation(current, current_plan['workpacks'][0], []))
        self.assertEqual(context['runtime_authorization']['approved_proposal_event_id'], f.proposal_id)
        self.assertEqual(context['runtime_authorization']['proposal_event_id'], revised['event_id'])
        self.assertEqual(context['proposal_binding']['plan_revision'], plan['revision'])
        result = controller.advance(f.prepared_id, advance_mode='ONE_ATTEMPT')
        self.assertEqual(result['attempt_status'], 'ACCEPTED', result)
        self.assertEqual(len(f.events('BUILD_AUTHORIZATION_APPROVED')), 1)
        self.assertEqual(result['budget']['attempts_consumed'], 1)

    def test_incompatible_plan_is_rejected_before_model_dispatch(self):
        f = self.f
        controller, prepared, task = self.prepare()
        plan = deepcopy(f.plan)
        plan['revision'] += 1
        plan['workpacks'][0]['artifacts'][0]['path'] = 'src/elsewhere.py'
        record_build_plan_proposal(f.store, f.ir, plan, document_review=f.review,
                                  **f.kwargs('fixture-incompatible-replan'))
        with self.assertRaises(RequestValidationError):
            controller._invocation(prepared, task, [])
        self.assertEqual(controller.advance(f.prepared_id)['status'], 'BUILD_STOPPED')
        self.assertFalse(self.calls)
        self.assertFalse(f.events('BUILD_ATTEMPT_STARTED'))

    def test_revoke_after_prompt_construction_still_prevents_real_dispatch(self):
        controller, _, _ = self.prepare()
        original = controller._invocation
        def revoke_after(*args, **kwargs):
            invocation = original(*args, **kwargs)
            self.revoke()
            return invocation
        with patch.object(controller, '_invocation', side_effect=revoke_after):
            result = controller.advance(self.f.prepared_id, advance_mode='ONE_ATTEMPT')
        self.assertEqual(result['status'], 'BUILD_STOPPED', result)
        self.assertFalse(self.calls)
        self.assertFalse(self.f.events('BUILD_COMMAND_PLANNED'))
        self.assertEqual(len(self.f.events('BUILD_ATTEMPT_STARTED')), 1,
                         'a reserved attempt is retained, not refunded by prompt failure')

    def test_rebind_repair_context_keeps_prior_attempt_and_cumulative_budget(self):
        f = self.f
        # Install the same synthetic model boundary, producing one failed then corrected output.
        local_runner = support.FixtureProcessRunner()
        def synthetic_repair(invocation, before_dispatch):
            if invocation['executor'] != 'CODEX':
                return local_runner(invocation, before_dispatch)
            before_dispatch()
            self.calls.append(deepcopy(invocation))
            (f.workspace / 'src/reader.py').write_text(
                support.BAD_READER if len(self.calls) == 1 else support.GOOD_READER)
            return {'status': 'MODEL_TURN_COMPLETED', 'final_message': 'TEST ONLY', 'exit_code': 0}
        f.runner = synthetic_repair
        controller, prepared, task = self.prepare()
        failed = controller.advance(f.prepared_id, advance_mode='ONE_ATTEMPT')
        self.assertEqual(failed['attempt_status'], 'REJECTED', failed)
        new_id = self.rebind()
        with self.assertRaisesRegex(RequestValidationError, 'superseded'):
            controller._invocation(prepared, task, [])
        result = controller.advance(new_id, advance_mode='ONE_ATTEMPT')
        self.assertEqual(result['attempt_status'], 'ACCEPTED', result)
        context = self.context(self.calls[-1])
        self.assertEqual(context['runtime_authorization']['prepared_event_id'], new_id)
        self.assertEqual(context['budget_consumed']['attempts'], 2)
        self.assertEqual(context['budget_consumed']['task_attempts'], 2)
        self.assertFalse(context['budget_consumed']['reset'])
        self.assertEqual(context['repair_history'][0]['attempt_id'], failed['attempt_id'])
        self.assertEqual(result['budget']['attempts_consumed'], 2)
        self.assertEqual(len(self.calls), 2)

    def test_complete_capture_recovery_does_not_rebuild_prompt_or_repeat_checks(self):
        f = self.f
        controller, _, _ = self.prepare()
        append = controller._append
        def crash_before_settlement(kind, *args, **kwargs):
            if kind == 'BUILD_ATTEMPT_FINISHED':
                raise support.InjectedControllerCrash()
            return append(kind, *args, **kwargs)
        with patch.object(controller, '_append', side_effect=crash_before_settlement), \
                self.assertRaises(support.InjectedControllerCrash):
            controller.advance(f.prepared_id, advance_mode='ONE_ATTEMPT')
        before = deepcopy(f.events('BUILD_COMMAND_OBSERVED'))
        self.assertEqual(len(before), 3)
        self.assertEqual(len(self.calls), 1)
        with patch.object(controller, '_invocation', side_effect=AssertionError('completed capture must not dispatch')):
            result = controller.advance(f.prepared_id, advance_mode='ONE_ATTEMPT')
        self.assertEqual(result['attempt_status'], 'ACCEPTED', result)
        self.assertEqual(f.events('BUILD_COMMAND_OBSERVED'), before)
        self.assertEqual(len(f.events('BUILD_COMMAND_PLANNED')), 3)
        self.assertEqual(result['budget']['attempts_consumed'], 1)
        self.assertEqual(len(self.calls), 1)


if __name__ == '__main__':
    unittest.main()
