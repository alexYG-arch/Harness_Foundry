"""Explicit rebinding with disposable Programs; no actual human/runtime grant."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from harness_foundry_factory.build_runtime import (
    prepare_build_authorization, approve_build_authorization, classify_verification_result)
from harness_foundry_factory.build_entrypoint import apply_build_request, read_build
from harness_foundry_factory.build_state import project_budget_attempts, project_execution_state, attempt_budget
from harness_foundry_factory.build_types import RequestValidationError
import test_build_runtime as support
import test_build_resources as resources


class RebindTests(unittest.TestCase):
    def setUp(self):
        self.f = support.BuildRuntimeTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.scope['max_attempts'] = 24

    def rebind(self, *, approve=True, scope=None, origin=None, key='rebind'):
        f = self.f
        old = origin or f.prepared_id
        candidate = prepare_build_authorization(f.store, f.program, f.proposal_id, f.source_id,
            scope or f.scope, rebind_from=old, **f.kwargs(key))
        if approve:
            approve_build_authorization(f.store, f.program, candidate['event_id'],
                human_message_ref='TEST ONLY rebind approval', **f.kwargs(key+'-approve'))
        return candidate['event_id']

    def budget(self, prepared_id):
        return attempt_budget(self.f.scope, list(project_budget_attempts(self.f.events(), prepared_id).values()))

    def test_exact_usage_keeps_other_task_allowance_and_old_dispatch_stops(self):
        f = self.f;f.prepare()
        f.controller().advance(f.prepared_id, advance_mode='ONE_ATTEMPT')
        old = f.prepared_id
        new = self.rebind()
        self.assertEqual(self.budget(new)['attempts_remaining'], 23)
        before_dispatch=read_build(f.store.database_path,f.program)['authorizations'][-1]
        self.assertEqual(before_dispatch['budget']['task_attempts_remaining']['MAKE-REPORT'],3)
        self.assertEqual(before_dispatch['reused_acceptance']['IMPLEMENT-READER']['prepared_event_id'],old)
        self.assertEqual(self.budget(new)['task_attempts_remaining'], {'IMPLEMENT-READER': 2})
        self.assertEqual(f.controller().advance(old)['status'], 'BUILD_STOPPED')
        self.assertEqual(f.controller().advance(new)['status'], 'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(self.budget(new)['attempts_consumed'], 2)
        self.assertEqual(len(f.runner.invocations), 5, 'accepted producer must not run twice')
        result = read_build(f.store.database_path, f.program)
        scopes = {g['prepared_event_id']: g for g in result['authorizations']}
        self.assertEqual(scopes[old]['state'], 'SUPERSEDED')
        self.assertEqual(scopes[new]['budget']['this_preparation_attempts'], 1)
        self.assertEqual(scopes[new]['budget']['attempts_consumed'], 2)
        self.assertEqual(project_execution_state(f.events(), new)[1]['IMPLEMENT-READER']['prepared_event_id'], old)

    def test_task_cap_is_cumulative_not_new_scope_three_more(self):
        f=self.f
        f.plan['workpacks'][0]['local_argv'][-1] = f.write_reader(support.BAD_READER)
        f.prepare()
        f.controller().advance(f.prepared_id, advance_mode='ONE_ATTEMPT')
        new=self.rebind()
        self.assertEqual(f.controller().advance(new)['status'], 'TASK_REPAIR_BUDGET_EXHAUSTED')
        self.assertEqual(self.budget(new)['attempts_consumed'], 3)
        self.assertEqual(self.budget(new)['task_attempts_remaining']['IMPLEMENT-READER'], 0)
        self.assertEqual(self.budget(new)['attempts_remaining'], 21)

    def test_changed_checker_reverifies_without_replaying_either_implementation(self):
        f=self.f;f.prepare();self.assertEqual(f.advance()['status'], 'PLAN_CHECKS_ACCEPTED')
        newroot=f.root/'new-verifier';newroot.mkdir()
        (newroot/'check.py').write_text(support.VERIFIER+'\n# corrected independent checker\n')
        scope={**f.scope,'verification_root':str(newroot)}
        new=self.rebind(scope=scope)
        before=len(f.runner.invocations)
        self.assertEqual(f.controller().advance(new)['status'], 'PLAN_CHECKS_ACCEPTED')
        calls=f.runner.invocations[before:]
        self.assertEqual([c['phase'] for c in calls], ['VERIFICATION']*3)
        rows=project_execution_state(f.events(),new)[0]
        self.assertEqual(len(rows),2)
        self.assertTrue(all(a.get('reverification_of_attempt_id') for a in rows.values()))
        self.assertEqual(self.budget(new)['attempts_consumed'],4)
        self.assertEqual(self.budget(new)['task_attempts_consumed'],{'IMPLEMENT-READER':2,'MAKE-REPORT':2})

    def test_only_changed_case_file_requires_reverification(self):
        f=self.f
        (f.verifier/'report.py').write_text(support.VERIFIER)
        f.plan['workpacks'][1]['verification'][0]['argv'][3]='verifier://report.py'
        f.prepare();f.advance()
        newroot=f.root/'new-verifier';newroot.mkdir()
        (newroot/'check.py').write_text(support.VERIFIER)
        (newroot/'report.py').write_text(support.VERIFIER+'\n# changed report checker\n')
        new=self.rebind(scope={**f.scope,'verification_root':str(newroot)})
        before=len(f.runner.invocations)
        self.assertEqual(f.controller().advance(new)['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual([(c['phase'],c['case_id']) for c in f.runner.invocations[before:]], [('VERIFICATION','REPORT-COUNT')])

    def test_old_blocked_is_history_after_real_checker_fix(self):
        f=self.f
        (f.verifier/'check.py').write_text("raise PermissionError('TEST unavailable old scratch')\n")
        runner=f.runner
        def classified(invocation,before):
            result=runner(invocation,before)
            return classify_verification_result(result) if invocation['phase']=='VERIFICATION' else result
        f.runner=classified
        f.prepare()
        self.assertEqual(f.controller().advance(f.prepared_id,advance_mode='ONE_ATTEMPT')['status'],'HELD_COMMAND_FAILURE')
        newroot=f.root/'fixed-verifier';newroot.mkdir();(newroot/'check.py').write_text(support.VERIFIER)
        new=self.rebind(scope={**f.scope,'verification_root':str(newroot)})
        self.assertEqual(f.controller().advance(new)['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(self.budget(new)['attempts_consumed'],3)
        self.assertEqual(project_budget_attempts(f.events(),new)[next(iter(project_execution_state(f.events(),f.prepared_id)[0]))]['status'],'BLOCKED')
        self.assertIn('PermissionError',json.dumps(project_budget_attempts(f.events(),new)))

    def test_unresolved_attempt_cannot_be_rebound_into_fresh_authority(self):
        f=self.f;f.prepare()
        def crash(invocation,before):
            raise support.InjectedControllerCrash()
        f.runner=crash
        with self.assertRaises(support.InjectedControllerCrash):f.advance()
        pending=self.rebind(approve=False)
        with self.assertRaisesRegex(RequestValidationError,'unresolved'):
            approve_build_authorization(f.store,f.program,pending,human_message_ref='TEST ONLY',**f.kwargs('new-approval'))
        self.assertEqual(self.budget(pending)['attempts_consumed'],1)

    def test_repeated_reads_and_multi_hop_do_not_recount(self):
        f=self.f;f.prepare();f.controller().advance(f.prepared_id,advance_mode='ONE_ATTEMPT')
        new=self.rebind()
        for _ in range(3):read_build(f.store.database_path,f.program)
        newer=self.rebind(origin=new,key='rebind-again')
        self.assertEqual(self.budget(newer)['attempts_consumed'],1)
        self.assertEqual(f.controller().advance(newer)['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(self.budget(newer)['attempts_consumed'],2)

    def test_parallel_successors_cannot_both_take_old_balance(self):
        f=self.f;f.prepare()
        first=self.rebind(approve=False,key='first')
        second=self.rebind(approve=False,key='second')
        approve_build_authorization(f.store,f.program,first,human_message_ref='TEST ONLY',**f.kwargs('first-approve'))
        with self.assertRaisesRegex(RequestValidationError,'latest linked'):
            approve_build_authorization(f.store,f.program,second,human_message_ref='TEST ONLY',**f.kwargs('second-approve'))

    def test_rebind_rejects_double_subtracted_budget_and_foreign_reference(self):
        f=self.f;f.prepare()
        with self.assertRaisesRegex(RequestValidationError,'ceilings'):
            self.rebind(scope={**f.scope,'max_attempts':23})
        with self.assertRaisesRegex(RequestValidationError,'this Program'):
            self.rebind(origin='CEVT-NOT-IN-THIS-STREAM')

    def test_public_request_accepts_optional_relation_without_new_command(self):
        f=self.f;f.scope['expires_at']='2099-01-01T00:00:00Z';f.prepare();old=f.prepared_id
        result=apply_build_request('prepare-build-authorization',{
            'program_id':f.program,'proposal_event_id':f.proposal_id,'source_event_id':f.source_id,
            'scope':f.scope,'rebind_from':old,'expected_revision':len(f.events()),'idempotency_key':'public-rebind'},f.store.database_path)
        self.assertEqual(result['status'],'BUILD_SCOPE_APPROVAL_REQUIRED')
        self.assertEqual(result['readback']['rebind_from'],old)
        self.assertFalse(result['execution_started'])

    def test_reverification_recovery_reuses_observed_checks(self):
        f=self.f;f.prepare();f.advance()
        newroot=f.root/'v2';newroot.mkdir();(newroot/'check.py').write_text(support.VERIFIER+'\n# v2\n')
        new=self.rebind(scope={**f.scope,'verification_root':str(newroot)})
        runner=resources.DurableResourceFixtureRunner();f.runner=runner
        def crash(invocation,result):
            runner.after_run=None
            raise support.InjectedControllerCrash()
        runner.after_run=crash
        with self.assertRaises(support.InjectedControllerCrash):f.controller().advance(new,advance_mode='ONE_ATTEMPT')
        result=f.controller().advance(new,advance_mode='ONE_ATTEMPT')
        self.assertEqual(result['attempt_status'],'ACCEPTED',result)
        self.assertEqual([c['case_id'] for c in runner.invocations],['READ-ROWS','REJECT-MALFORMED'])
        self.assertEqual(self.budget(new)['attempts_consumed'],3)

    def test_not_dispatched_is_spent_and_can_continue_in_new_binding(self):
        from unittest.mock import patch
        f=self.f;f.prepare();controller=f.controller()
        execute=controller._execute_command
        def interrupted(*args):
            raise support.InjectedControllerCrash()
        with patch.object(controller,'_execute_command',side_effect=interrupted), self.assertRaises(support.InjectedControllerCrash):
            controller.advance(f.prepared_id,advance_mode='ONE_ATTEMPT')
        settled=controller.advance(f.prepared_id,advance_mode='ONE_ATTEMPT')
        self.assertEqual(settled['attempt_status'],'NOT_DISPATCHED')
        new=self.rebind()
        result=f.controller().advance(new,advance_mode='ONE_ATTEMPT')
        self.assertEqual(result['attempt_status'],'ACCEPTED')
        self.assertEqual(result['budget']['attempts_consumed'],2)

    def test_handoff_and_repair_context_follow_only_explicit_ancestry(self):
        captured=[];f=self.f
        f.runner=f._codex_fixture_runner(captured,first_bad=True)
        f.prepare()
        first=f.controller().advance(f.prepared_id,advance_mode='ONE_ATTEMPT')
        self.assertEqual(first['attempt_status'],'REJECTED')
        new=self.rebind()
        invalid=f.controller().advance(new,advance_mode='ONE_ATTEMPT',codex_handoff={
            'workpack_id':'IMPLEMENT-READER','basis_attempt_ids':['ATTEMPT-UNRELATED'],'summary':'TEST'})
        self.assertEqual(invalid['status'],'HELD_CODEX_HANDOFF')
        result=f.controller().advance(new,advance_mode='ONE_ATTEMPT',codex_handoff={
            'workpack_id':'IMPLEMENT-READER','basis_attempt_ids':[first['attempt_id']],'summary':'TEST prior failure evidence'})
        self.assertEqual(result['attempt_status'],'ACCEPTED',result)
        context=json.loads(captured[-1]['prompt'].split('\n',1)[1])['task']
        self.assertEqual(context['repair_history'][0]['attempt_id'],first['attempt_id'])
        self.assertEqual(context['budget_consumed']['attempts'],2)
        self.assertEqual(context['codex_handoff']['basis_attempt_ids'],[first['attempt_id']])

    def test_prepare_and_approval_exact_replay_do_not_add_usage_or_events(self):
        f=self.f;f.prepare()
        kwargs=f.kwargs('retryable-prepare')
        prepared=prepare_build_authorization(f.store,f.program,f.proposal_id,f.source_id,
            f.scope,rebind_from=f.prepared_id,**kwargs)
        approval_kwargs=f.kwargs('retryable-approve')
        approved=approve_build_authorization(f.store,f.program,prepared['event_id'],human_message_ref='TEST ONLY',**approval_kwargs)
        count=len(f.events())
        replay=prepare_build_authorization(f.store,f.program,f.proposal_id,f.source_id,
            f.scope,rebind_from=f.prepared_id,**kwargs)
        self.assertEqual(prepared,replay)
        self.assertEqual(approved,approve_build_authorization(f.store,f.program,prepared['event_id'],
            human_message_ref='TEST ONLY',**approval_kwargs))
        self.assertEqual(len(f.events()),count)
        self.assertEqual(self.budget(prepared['event_id'])['attempts_consumed'],0)

    def test_unchanged_binding_keeps_accepted_replacement_without_resurrecting_old_bytes(self):
        f=self.f
        task=deepcopy(f.plan['workpacks'][0])
        task.update(workpack_id='READER-V2',job_id='MAINTENANCE',depends_on=['MAKE-REPORT'],
                    inputs=[{'kind':'ARTIFACT','id':'READER-SOURCE'}],
                    artifacts=[{'artifact_id':'READER-V2','path':'src/reader.py','replaces_artifact_id':'READER-SOURCE'}])
        task['local_argv'][-1]=f.write_reader(support.GOOD_READER+'\n# new physical version\n')
        for check in task['verification']:check['artifact_ids']=['READER-V2']
        f.plan['workpacks'].append(task);f.scope['task_write_roots']['READER-V2']=['src']
        f.prepare();self.assertEqual(f.advance()['status'],'PLAN_CHECKS_ACCEPTED')
        physical=(f.workspace/'src/reader.py').read_bytes()
        new=self.rebind();count=len(f.runner.invocations)
        self.assertEqual(f.controller().advance(new)['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(len(f.runner.invocations),count)
        self.assertEqual((f.workspace/'src/reader.py').read_bytes(),physical)
        self.assertEqual(self.budget(new)['attempts_consumed'],3)

    def test_new_case_with_same_public_contract_rechecks_without_reimplementation(self):
        from harness_foundry_factory.build_authoring import record_build_plan_proposal
        from harness_foundry_factory.build_runtime import record_source_snapshot
        f=self.f;f.prepare();f.advance()
        original=deepcopy(f.ir['negative_cases'][0]);original['case_id']='EXTRA-ROWS'
        f.ir['negative_cases'].append(original);f.ir['revision']+=1
        f.plan['revision']+=1;f.plan['requirement_revision']=f.ir['revision']
        check=deepcopy(f.plan['workpacks'][0]['verification'][0]);check['case_id']='EXTRA-ROWS'
        f.plan['workpacks'][0]['verification'].append(check)
        proposal=record_build_plan_proposal(f.store,f.ir,f.plan,document_review=f.review,**f.kwargs('extra-case-plan'))
        f.proposal_id=proposal['event_id']
        source=record_source_snapshot(f.store,f.program,f.proposal_id,f.source,
            [{'source_id':'PROJECT-BRIEF','path':'brief.md'}],**f.kwargs('extra-case-source'))
        f.source_id=source['event_id']
        new=self.rebind();count=len(f.runner.invocations)
        self.assertEqual(f.controller().advance(new)['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual([i['phase'] for i in f.runner.invocations[count:]],['VERIFICATION']*4)

    def test_reverified_business_failure_runs_native_product_repair(self):
        from harness_foundry_factory.build_authoring import record_build_plan_proposal
        f=self.f
        (f.verifier/'check.py').write_text('print("TEST old incomplete checker")\n')
        f.plan['workpacks'][0]['local_argv'][-1]=f.write_reader(support.BAD_READER)
        runner=f.runner
        def classified(invocation,before):
            result=runner(invocation,before)
            return classify_verification_result(result) if invocation['phase']=='VERIFICATION' else result
        f.runner=classified;f.prepare();self.assertEqual(f.advance()['status'],'PLAN_CHECKS_ACCEPTED')
        checker='''import json,runpy,sys
if sys.argv[1]=="report":
    from pathlib import Path
    okay=json.loads(Path("outputs/summary.json").read_text())=={"rows":3,"invalid":2}
else:
    reader=runpy.run_path("src/reader.py")
    okay=reader["inspect_rows"](["1","bad",""])["rows"]==3
if not okay:
    print(json.dumps({"status":"CHECKS_FAILED","failure_kind":"ASSERTION"}))
    raise SystemExit(1)
'''
        newroot=f.root/'corrected';newroot.mkdir();(newroot/'check.py').write_text(checker)
        new=self.rebind(scope={**f.scope,'verification_root':str(newroot)})
        count=len(runner.invocations)
        failed=f.controller().advance(new,advance_mode='ONE_ATTEMPT')
        self.assertEqual(failed['attempt_status'],'REJECTED')
        self.assertTrue(all(i['phase']=='VERIFICATION' for i in runner.invocations[count:]))
        f.plan['revision']+=1
        f.plan['workpacks'][0]['local_argv'][-1]=f.write_reader(support.GOOD_READER)
        record_build_plan_proposal(f.store,f.ir,f.plan,document_review=f.review,**f.kwargs('repair-plan'))
        repaired=f.controller().advance(new)
        self.assertEqual(repaired['status'],'PLAN_CHECKS_ACCEPTED',repaired)
        self.assertEqual(self.budget(new)['task_attempts_consumed'],{'IMPLEMENT-READER':3,'MAKE-REPORT':3})


    def test_second_rebind_keeps_unexecuted_verification_pending_without_replaying_production(self):
        f=self.f;f.prepare();f.advance()
        root=f.root/'new-checker';root.mkdir();(root/'check.py').write_text(support.VERIFIER+'\n# new checker\n')
        scope={**f.scope,'verification_root':str(root)}
        first=self.rebind(scope=scope)
        second=self.rebind(scope=scope,origin=first,key='pending-again')
        count=len(f.runner.invocations)
        self.assertEqual(f.controller().advance(second)['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual([i['phase'] for i in f.runner.invocations[count:]],['VERIFICATION']*3)
        self.assertEqual(self.budget(second)['attempts_consumed'],4)


if __name__=='__main__':unittest.main()
