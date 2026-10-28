"""Explicit cumulative additions in isolated fixture Programs, never real grants."""
from copy import deepcopy
import unittest

from harness_foundry_factory.build_entrypoint import apply_build_request, read_build
from harness_foundry_factory.build_display import render_build_readback
from harness_foundry_factory.build_runtime import (
    prepare_build_authorization, approve_build_authorization, revoke_build_authorization)
from harness_foundry_factory.build_state import project_budget_attempts
from harness_foundry_factory.build_types import RequestValidationError, IdempotencyConflictError
import test_build_runtime as support
from test_build_resources import DurableResourceFixtureRunner


class BudgetExtensionTests(unittest.TestCase):
    def setUp(self):
        f = self.f = support.BuildRuntimeTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.scope.update(max_attempts=6, max_task_attempts=6, expires_at='2099-01-01T00:00:00Z')

    def extension(self, total=1, task=1):
        return {'additional_attempts': total, 'additional_task_attempts': task,
                'reason': 'TEST ONLY explicitly requested cumulative additional allowance'}

    def prepare_extension(self, *, old=None, total=1, task=1, key='extend', scope=None):
        f = self.f
        old = old or f.prepared_id
        previous = next(e['payload']['scope'] for e in f.events() if e['event_id'] == old)
        new = scope or {**previous, 'max_attempts': previous['max_attempts'] + total,
                       'max_task_attempts': previous['max_task_attempts'] + task}
        return prepare_build_authorization(f.store, f.program, f.proposal_id, f.source_id, new,
            rebind_from=old, budget_extension=self.extension(total, task), **f.kwargs(key))

    def approve(self, event, key='extend-approval'):
        return approve_build_authorization(self.f.store, self.f.program, event['event_id'],
            human_message_ref='TEST ONLY later human decision for displayed addition', **self.f.kwargs(key))

    def grant(self, identity):
        return next(g for g in read_build(self.f.store.database_path, self.f.program)['authorizations']
                    if g['prepared_event_id'] == identity)

    def test_spent_six_add_one_keeps_six_then_stops_at_seven(self):
        f = self.f
        f.plan['workpacks'][0]['local_argv'][-1] = f.write_reader(support.BAD_READER)
        f.prepare()
        self.assertEqual(f.advance()['status'], 'ATTEMPT_BUDGET_EXHAUSTED')
        self.assertEqual(self.grant(f.prepared_id)['budget']['attempts_consumed'], 6)
        before = deepcopy(f.events())
        new = self.prepare_extension()
        scope = self.grant(new['event_id'])
        self.assertEqual(scope['state'], 'APPROVAL_REQUIRED')
        self.assertEqual(scope['budget']['attempts_consumed'], 6)
        self.assertEqual(scope['budget']['attempts_remaining'], 1)
        calls = len(f.runner.invocations)
        self.assertEqual(f.controller().advance(new['event_id'])['status'], 'BUILD_STOPPED')
        self.assertEqual(len(f.runner.invocations), calls)
        approval = self.approve(new)
        self.assertFalse(approval['payload']['rebind']['budget_reset'])
        self.assertFalse(approval['payload']['rebind']['old_authority_inherited'])
        self.assertEqual(f.controller().advance(f.prepared_id)['status'], 'BUILD_STOPPED')
        self.assertEqual(f.controller().advance(new['event_id'])['status'], 'ATTEMPT_BUDGET_EXHAUSTED')
        self.assertEqual(self.grant(new['event_id'])['budget']['attempts_consumed'], 7)
        self.assertEqual(self.grant(new['event_id'])['budget']['attempts_remaining'], 0)
        self.assertEqual(f.events()[:len(before)], before)
        calls = len(f.runner.invocations)
        for _ in range(2):
            self.assertEqual(f.controller().advance(new['event_id'])['status'], 'ATTEMPT_BUDGET_EXHAUSTED')
        self.assertEqual(len(f.runner.invocations), calls)

    def test_public_prepare_and_human_summary_expose_absolute_and_additional_limits(self):
        f = self.f; f.prepare()
        request = dict(program_id=f.program, proposal_event_id=f.proposal_id, source_event_id=f.source_id,
                       scope={**f.scope,'max_attempts':7,'max_task_attempts':7},
                       rebind_from=f.prepared_id,budget_extension=self.extension(),
                       expected_revision=len(f.events()),idempotency_key='public-extension')
        result = apply_build_request('prepare-build-authorization', request, f.store.database_path)
        self.assertEqual(result['status'], 'BUILD_SCOPE_APPROVAL_REQUIRED')
        change = result['readback']['budget_extension']
        self.assertEqual(change['previous_limits'], {'max_attempts':6,'max_task_attempts':6})
        self.assertEqual(change['new_limits'], {'max_attempts':7,'max_task_attempts':7})
        self.assertEqual(change['task_cap_applies_to'], ['IMPLEMENT-READER','MAKE-REPORT'])
        self.assertFalse(result['execution_started'])
        human = render_build_readback(read_build(f.store.database_path,f.program))
        self.assertIn('6 → 7',human)
        self.assertIn('各任务统一',human)

    def test_approved_addition_can_finish_real_local_repair_without_eighth_attempt(self):
        from harness_foundry_factory.build_authoring import record_build_plan_proposal
        from harness_foundry_factory.build_runtime import record_source_snapshot
        f=self.f
        f.plan['workpacks'][0]['local_argv'][-1]=f.write_reader(support.BAD_READER)
        f.prepare();self.assertEqual(f.advance()['status'],'ATTEMPT_BUDGET_EXHAUSTED')
        f.ir['revision']+=1;f.plan['revision']+=1;f.plan['requirement_revision']=f.ir['revision']
        f.plan['workpacks'][0]['local_argv'][-1]=f.write_reader(support.GOOD_READER)
        proposal=record_build_plan_proposal(f.store,f.ir,f.plan,document_review=f.review,**f.kwargs('repair-plan'))
        f.proposal_id=proposal['event_id']
        source=record_source_snapshot(f.store,f.program,f.proposal_id,f.source,
            [{'source_id':'PROJECT-BRIEF','path':'brief.md'}],**f.kwargs('repair-source'))
        f.source_id=source['event_id']
        new=self.prepare_extension();self.approve(new)
        result=f.controller().advance(new['event_id'],advance_mode='ONE_ATTEMPT')
        self.assertEqual(result['attempt_status'],'ACCEPTED',result)
        self.assertEqual(result['budget']['attempts_consumed'],7)
        calls=len(f.runner.invocations)
        self.assertEqual(f.controller().advance(new['event_id'])['status'],'ATTEMPT_BUDGET_EXHAUSTED')
        self.assertEqual(len(f.runner.invocations),calls)

    def test_new_real_approval_can_use_revoked_history_without_reviving_old_grant(self):
        f=self.f;f.prepare()
        f.controller().advance(f.prepared_id,advance_mode='ONE_ATTEMPT')
        revoke_build_authorization(f.store,f.program,f.prepared_id,**f.kwargs('revoke-old'))
        new=self.prepare_extension();self.approve(new)
        self.assertEqual(f.controller().advance(f.prepared_id)['status'],'BUILD_STOPPED')
        self.assertEqual(f.controller().advance(new['event_id'])['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(self.grant(new['event_id'])['budget']['attempts_consumed'],2)

    def test_current_plan_change_rejects_pending_extension(self):
        from harness_foundry_factory.build_authoring import record_build_plan_proposal
        f=self.f;f.prepare();new=self.prepare_extension()
        f.ir['revision']+=1;f.plan['revision']+=1;f.plan['requirement_revision']=f.ir['revision']
        record_build_plan_proposal(f.store,f.ir,f.plan,document_review=f.review,**f.kwargs('changed-plan'))
        with self.assertRaisesRegex(RequestValidationError,'proposal changed'):
            self.approve(new)
        self.assertEqual(len(f.runner.invocations),0)

    def test_bad_extension_or_unmarked_change_rejected(self):
        f = self.f; f.prepare()
        for extension in [None,{},self.extension(-1,1),self.extension(True,1),
                          self.extension(0,0),self.extension(2,1),
                          {**self.extension(),'unexpected':1},
                          {**self.extension(),'reason':''}]:
            with self.subTest(extension=extension), self.assertRaises(RequestValidationError):
                prepare_build_authorization(f.store,f.program,f.proposal_id,f.source_id,
                    {**f.scope,'max_attempts':7,'max_task_attempts':7},rebind_from=f.prepared_id,
                    budget_extension=extension,**f.kwargs('invalid'))
        with self.assertRaises(RequestValidationError):
            prepare_build_authorization(f.store,f.program,f.proposal_id,f.source_id,
                {**f.scope,'max_attempts':7,'max_task_attempts':7},
                budget_extension=self.extension(),**f.kwargs('unlinked'))
        self.assertEqual(len(f.events('BUILD_AUTHORIZATION_PREPARED')),1)

    def test_total_and_task_limits_remain_independent(self):
        f = self.f; f.scope['max_attempts']=10;f.scope['max_task_attempts']=1
        f.plan['workpacks'][0]['local_argv'][-1]=f.write_reader(support.BAD_READER)
        f.prepare();self.assertEqual(f.advance()['status'],'TASK_REPAIR_BUDGET_EXHAUSTED')
        total_only=self.prepare_extension(total=1,task=0);self.approve(total_only)
        calls=len(f.runner.invocations)
        self.assertEqual(f.controller().advance(total_only['event_id'])['status'],'TASK_REPAIR_BUDGET_EXHAUSTED')
        self.assertEqual(len(f.runner.invocations),calls)
        task_only=self.prepare_extension(old=total_only['event_id'],total=0,task=1,key='task-only')
        self.approve(task_only,'task-only-approve')
        self.assertEqual(f.controller().advance(task_only['event_id'])['status'],'TASK_REPAIR_BUDGET_EXHAUSTED')
        grant=self.grant(task_only['event_id'])
        self.assertEqual(grant['budget']['attempts_consumed'],2)
        self.assertEqual(grant['budget']['attempts_remaining'],9)
        self.assertEqual(grant['budget']['task_attempts_remaining']['MAKE-REPORT'],2)

    def test_exact_prepare_and_approval_replays_and_multihop_do_not_add_twice(self):
        f=self.f;f.prepare();f.controller().advance(f.prepared_id,advance_mode='ONE_ATTEMPT')
        args=(f.store,f.program,f.proposal_id,f.source_id,{**f.scope,'max_attempts':7,'max_task_attempts':7})
        kw=dict(rebind_from=f.prepared_id,budget_extension=self.extension(),**f.kwargs('retry-prepare'))
        new=prepare_build_authorization(*args,**kw)
        self.assertEqual(prepare_build_authorization(*args,**kw),new)
        with self.assertRaises(IdempotencyConflictError):
            prepare_build_authorization(*args,**{**kw,'budget_extension':{**self.extension(),'reason':'changed'}})
        ak=dict(human_message_ref='TEST only actual decision',**f.kwargs('retry-approve'))
        granted=approve_build_authorization(f.store,f.program,new['event_id'],**ak)
        count=len(f.events())
        self.assertEqual(approve_build_authorization(f.store,f.program,new['event_id'],**ak),granted)
        self.assertEqual(len(f.events()),count)
        follow=self.prepare_extension(old=new['event_id'],key='follow')
        self.approve(follow,'follow-approve')
        self.assertEqual(self.grant(follow['event_id'])['budget']['attempts_consumed'],1)
        self.assertEqual(self.grant(follow['event_id'])['budget']['attempts_remaining'],7)

    def test_only_latest_parallel_successor_can_commit(self):
        f=self.f;f.prepare()
        a=self.prepare_extension(key='a');b=self.prepare_extension(key='b')
        self.approve(a)
        with self.assertRaisesRegex(RequestValidationError,'latest linked'):
            self.approve(b,'b-approve')
        self.assertEqual(len(f.events('BUILD_AUTHORIZATION_APPROVED')),2)

    def test_revoked_expired_and_wrong_program_extensions_do_not_dispatch(self):
        f=self.f;f.prepare()
        revoked=self.prepare_extension(key='revoked')
        revoke_build_authorization(f.store,f.program,revoked['event_id'],**f.kwargs('revoke'))
        with self.assertRaisesRegex(RequestValidationError,'revoked'):
            self.approve(revoked)
        expired=self.prepare_extension(key='expires')
        with self.assertRaisesRegex(RequestValidationError,'expiration'):
            approve_build_authorization(f.store,f.program,expired['event_id'],human_message_ref='TEST',
                **{**f.kwargs('late'),'created_at':'2100-01-01T00:00:00Z'})
        with self.assertRaisesRegex(RequestValidationError,'this Program'):
            prepare_build_authorization(f.store,f.program,f.proposal_id,f.source_id,
                {**f.scope,'max_attempts':7,'max_task_attempts':7},rebind_from='CEVT-FOREIGN',
                budget_extension=self.extension(),**f.kwargs('foreign'))
        self.assertEqual(len(f.runner.invocations),0)

    def test_expiry_or_revocation_after_approval_blocks_but_readback_survives(self):
        from datetime import datetime
        f=self.f;f.prepare();new=self.prepare_extension();self.approve(new)
        future=support.BuildController(f.store,f.program,runner=f.runner,
                                       clock=lambda:datetime.fromisoformat('2100-01-01T00:00:00+00:00'))
        self.assertEqual(future.advance(new['event_id'])['status'],'BUILD_STOPPED')
        revoke_build_authorization(f.store,f.program,new['event_id'],**f.kwargs('revoke-after'))
        self.assertEqual(f.controller().advance(new['event_id'])['status'],'BUILD_STOPPED')
        self.assertEqual(self.grant(new['event_id'])['state'],'REVOKED')
        self.assertEqual(len(f.runner.invocations),0)

    def test_unresolved_effects_cannot_be_bypassed_by_addition(self):
        f=self.f;f.prepare()
        def crash(invocation,before): raise support.InjectedControllerCrash()
        f.runner=crash
        with self.assertRaises(support.InjectedControllerCrash):f.advance()
        new=self.prepare_extension()
        with self.assertRaisesRegex(RequestValidationError,'unresolved'):self.approve(new)
        self.assertEqual(self.grant(new['event_id'])['budget']['attempts_consumed'],1)

    def test_accepted_reuse_and_complete_readback_do_not_replay(self):
        f=self.f;f.prepare();self.assertEqual(f.advance()['status'],'PLAN_CHECKS_ACCEPTED')
        new=self.prepare_extension();self.approve(new)
        calls=len(f.runner.invocations)
        for _ in range(2):
            self.assertEqual(f.controller().advance(new['event_id'])['status'],'PLAN_CHECKS_ACCEPTED')
            self.assertEqual(self.grant(new['event_id'])['budget']['attempts_consumed'],2)
        self.assertEqual(len(f.runner.invocations),calls)
        self.assertEqual(len(self.grant(new['event_id'])['reused_acceptance']),2)

    def test_exhausted_accepted_delivery_can_use_added_budget_for_existing_repair_entry(self):
        # Synthetic model output, real control events and local independent checks.
        # This checks integration with the unchanged extra-defect repair entry.
        h=support.BuildRepairTests();h.setUp();self.addCleanup(h.doCleanups)
        self.f=f=h.f
        report=f.plan['workpacks'][1];report['executor']='CODEX';report.pop('local_argv')
        h.prepare(total=2,per_task=1)
        with self.assertRaisesRegex(RequestValidationError,'BUDGET_EXHAUSTED'):
            h.repair(h.request(artifacts=('SUMMARY',)))
        old=deepcopy(f.events());reader_bytes=(f.workspace/'src/reader.py').read_bytes()
        new=self.prepare_extension();self.approve(new);f.prepared_id=new['event_id']
        request=h.request(artifacts=('SUMMARY',));h.repair(request)
        self.assertEqual(h.controller.advance(f.prepared_id)['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(self.grant(f.prepared_id)['budget']['attempts_consumed'],3)
        self.assertEqual(self.grant(f.prepared_id)['budget']['attempts_remaining'],0)
        self.assertEqual(len(h.captured),3)
        self.assertEqual((f.workspace/'src/reader.py').read_bytes(),reader_bytes)
        self.assertEqual(f.events()[:len(old)],old)
        h.repair(request)  # Same repair request returns its old event; no re-invalidation.
        self.assertEqual(h.controller.advance(f.prepared_id)['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(len(h.captured),3)

    def test_full_capture_recovers_same_attempt_after_extension(self):
        f=self.f;f.prepare();new=self.prepare_extension();self.approve(new)
        runner=DurableResourceFixtureRunner();f.runner=runner
        def crash(invocation,result):
            runner.after_run=None
            raise support.InjectedControllerCrash()
        runner.after_run=crash
        with self.assertRaises(support.InjectedControllerCrash):
            f.controller().advance(new['event_id'],advance_mode='ONE_ATTEMPT')
        result=f.controller().advance(new['event_id'],advance_mode='ONE_ATTEMPT')
        self.assertEqual(result['attempt_status'],'ACCEPTED',result)
        self.assertEqual(sum(i['phase']=='IMPLEMENTATION' for i in runner.invocations),1)
        self.assertEqual(self.grant(new['event_id'])['budget']['attempts_consumed'],1)

    def test_automatic_correction_cannot_approve_extension(self):
        from harness_foundry_factory.build_correction import derive_checker_authorization
        f=self.f;f.prepare();new=self.prepare_extension()
        with self.assertRaisesRegex(RequestValidationError,'budget|human'):
            derive_checker_authorization(f.store,f.program,new['event_id'],evidence={},**f.kwargs('derive'))
        self.assertEqual(self.grant(new['event_id'])['state'],'APPROVAL_REQUIRED')

    def test_extension_after_checker_reverification_keeps_free_round_separate(self):
        import test_build_correction as corrections
        c=corrections.CheckerCorrectionTests();c.setUp();self.addCleanup(c.doCleanups)
        c.prepare_failure(whole_budget=True)
        old,evidence=c.new_binding(complete=c.attempt_id);c.derive(old,evidence)
        self.assertEqual(c.f.controller().advance(old,advance_mode='ONE_ATTEMPT')['attempt_status'],'ACCEPTED')
        self.f=c.f
        new=self.prepare_extension(old=old);self.approve(new)
        grant=self.grant(new['event_id'])
        self.assertEqual(grant['budget']['attempts_consumed'],1)
        self.assertEqual(grant['budget']['checker_reverification_rounds'],1)
        self.assertEqual(grant['budget']['attempts_remaining'],1)
        self.assertEqual(len(project_budget_attempts(c.f.events(),new['event_id'])),2)


if __name__=='__main__': unittest.main()
