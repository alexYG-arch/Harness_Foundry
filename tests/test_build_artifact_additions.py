"""Append declarations using disposable Programs and real LOCAL fixture processes.

Approvals are test data, not business authority or real-model validation.
"""
from copy import deepcopy
from datetime import datetime
import json
import unittest

from harness_foundry_factory.build_authoring import record_build_plan_proposal
from harness_foundry_factory.build_correction import derive_checker_authorization
from harness_foundry_factory.build_display import render_build_readback
from harness_foundry_factory.build_entrypoint import apply_build_request, read_build
from harness_foundry_factory.build_rebind import approval_rebind, validate_rebind
from harness_foundry_factory.build_runtime import (
    approve_build_authorization, prepare_build_authorization, record_source_snapshot,
    revoke_build_authorization,
)
from harness_foundry_factory.build_state import project_execution_state
from harness_foundry_factory.build_types import RequestValidationError
import test_build_runtime as support
from test_build_resources import DurableResourceFixtureRunner


class ArtifactAdditionTests(unittest.TestCase):
    def setUp(self):
        f = self.f = support.BuildRuntimeTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.scope.update(max_attempts=6, max_task_attempts=3, expires_at='2099-01-01T00:00:00Z')
        # The independent check knows the public format before the missing
        # output is added to a Plan. It actually reads the newly declared file.
        (f.verifier/'check.py').write_text(support.VERIFIER + '''
if len(sys.argv) > 2:
    assert Path(sys.argv[2]).read_text() == "declared supplement\\n"
''')

    def add(self, index=1, identity='SUPPLEMENT', path='outputs/extra.txt'):
        task = self.f.plan['workpacks'][index]
        task['artifacts'].append({'artifact_id':identity,'path':path})
        task['verification'][0]['artifact_ids'].append(identity)
        task['verification'][0]['argv'].append(path)
        task['local_argv'][-1] += '; from pathlib import Path; Path(' + repr(path) + ').write_text("declared supplement\\n")'

    def proposal(self, key='added'):
        f = self.f
        f.plan['revision'] += 1
        result = record_build_plan_proposal(f.store,f.ir,f.plan,document_review=f.review,**f.kwargs(key+'-plan'))
        f.proposal_id = result['event_id']
        source = record_source_snapshot(f.store,f.program,f.proposal_id,f.source,
            [{'source_id':'PROJECT-BRIEF','path':'brief.md'}],**f.kwargs(key+'-source'))
        f.source_id = source['event_id']
        return result['payload']

    def prepare(self, origin=None, key='added', scope=None, extension=None):
        f = self.f
        return prepare_build_authorization(f.store,f.program,f.proposal_id,f.source_id,
            scope or f.scope,rebind_from=origin or f.prepared_id,
            budget_extension=extension,**f.kwargs(key+'-prepare'))

    def approve(self, prepared, key='added'):
        f = self.f
        kwargs={**f.kwargs(key+'-approve'),'created_at':prepared['created_at']}
        return approve_build_authorization(f.store,f.program,prepared['event_id'],
            human_message_ref='TEST ONLY actual decision for the displayed amended Plan',**kwargs)

    def grant(self, prepared):
        return next(row for row in read_build(self.f.store.database_path,self.f.program)['authorizations']
                    if row['prepared_event_id'] == prepared['event_id'])

    def test_public_readback_pending_then_reuses_accepted_producer_without_recount(self):
        f=self.f; f.prepare()
        f.controller().advance(f.prepared_id,advance_mode='ONE_ATTEMPT')
        old_events=deepcopy(f.events()); old_accepted=project_execution_state(old_events,f.prepared_id)[1]
        self.add(); self.proposal()
        result=apply_build_request('prepare-build-authorization',dict(program_id=f.program,
            proposal_event_id=f.proposal_id,source_event_id=f.source_id,scope=f.scope,
            rebind_from=f.prepared_id,expected_revision=len(f.events()),idempotency_key='public-add'),f.store.database_path)
        new=next(e for e in f.events() if e['event_id']==result['readback']['prepared_event_id'])
        delta=[{'workpack_id':'MAKE-REPORT','artifact_id':'SUPPLEMENT','path':'outputs/extra.txt'}]
        self.assertEqual(result['readback']['artifact_additions'],delta)
        self.assertEqual(result['readback']['state'],'APPROVAL_REQUIRED')
        self.assertFalse(result['execution_started'])
        self.assertIn('追加产物',render_build_readback(read_build(f.store.database_path,f.program)))
        count=len(f.runner.invocations)
        self.assertEqual(f.controller().advance(new['event_id'])['status'],'BUILD_STOPPED')
        self.assertEqual(len(f.runner.invocations),count)
        approved=self.approve(new)['payload']['rebind']
        self.assertEqual(approved['artifact_additions'],delta)
        self.assertEqual(approved['accepted'],old_accepted)
        self.assertFalse(approved['budget_reset']); self.assertFalse(approved['old_authority_inherited'])
        self.assertEqual(f.controller().advance(f.prepared_id)['status'],'BUILD_STOPPED')
        self.assertEqual(f.controller().advance(new['event_id'])['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual([i['workpack_id'] for i in f.runner.invocations[count:]],['MAKE-REPORT']*2)
        self.assertEqual(self.grant(new)['budget']['attempts_consumed'],2)
        self.assertEqual(f.events()[:len(old_events)],old_events)
        self.assertEqual((f.workspace/'outputs/extra.txt').read_text(),'declared supplement\n')

    def test_accepted_owner_addition_rebuilds_it_and_consumers_never_imports_old_pass(self):
        f=self.f; f.prepare(); f.advance(); old=deepcopy(f.events())
        self.add(index=0,path='src/extra.txt'); self.proposal(); new=self.prepare()
        relation=self.approve(new)['payload']['rebind']
        self.assertEqual(relation['rebuild_workpack_ids'],['IMPLEMENT-READER'])
        self.assertFalse(relation['accepted']); self.assertFalse(relation['verification_pending'])
        count=len(f.runner.invocations)
        self.assertEqual(f.controller().advance(new['event_id'])['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual([i['workpack_id'] for i in f.runner.invocations[count:] if i['phase']=='IMPLEMENTATION'],
                         ['IMPLEMENT-READER','MAKE-REPORT'])
        self.assertEqual(self.grant(new)['budget']['attempts_consumed'],4)
        self.assertEqual(f.events()[:len(old)],old)

    def test_addition_does_not_turn_pending_reverification_into_acceptance(self):
        f=self.f; f.prepare(); f.advance()
        root=f.root/'corrected'; root.mkdir(); (root/'check.py').write_bytes((f.verifier/'check.py').read_bytes()+b'\n# adapter\n')
        scope={**f.scope,'verification_root':str(root)}
        pending=self.prepare(key='checker',scope=scope); self.approve(pending,key='checker')
        self.add(); self.proposal(); new=self.prepare(origin=pending['event_id'],scope=scope)
        relation=self.approve(new)['payload']['rebind']
        self.assertEqual(relation['rebuild_workpack_ids'],['MAKE-REPORT'])
        self.assertEqual(list(relation['verification_pending']),['IMPLEMENT-READER'])
        self.assertFalse(relation['accepted'])
        count=len(f.runner.invocations)
        self.assertEqual(f.controller().advance(new['event_id'])['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual([i['phase'] for i in f.runner.invocations[count:]],
                         ['VERIFICATION','VERIFICATION','IMPLEMENTATION','VERIFICATION'])
        self.assertEqual(self.grant(new)['budget']['attempts_consumed'],4)

    def test_automatic_checker_correction_cannot_authorize_extra_output(self):
        f=self.f; f.prepare(); self.add(); self.proposal(); new=self.prepare()
        with self.assertRaisesRegex(RequestValidationError,'production'):
            derive_checker_authorization(f.store,f.program,new['event_id'],evidence={},**f.kwargs('not-equivalent'))
        with self.assertRaisesRegex(RequestValidationError,'human approval'):
            approval_rebind(f.events(),f.prepared_id,new['payload'],f.events('BUILD_PLAN_PROPOSED')[-1]['payload'])
        self.assertEqual(len(f.events('BUILD_AUTHORIZATION_APPROVED')),1)

    def test_old_declarations_cannot_be_deleted_moved_renamed_or_reassigned(self):
        f=self.f; f.prepare(); old=deepcopy(f.events('BUILD_PLAN_PROPOSED')[-1]['payload'])
        variants=[]
        for field,value in [('artifact_id','RENAMED'),('path','src/moved.py'),('replaces_artifact_id','OTHER')]:
            candidate=deepcopy(old); candidate['plan']['workpacks'][0]['artifacts'][0][field]=value; variants.append(candidate)
        candidate=deepcopy(old); candidate['plan']['workpacks'][0]['artifacts']=[]; variants.append(candidate)
        candidate=deepcopy(old)
        candidate['plan']['workpacks'][1]['artifacts'].append(candidate['plan']['workpacks'][0]['artifacts'].pop()); variants.append(candidate)
        for candidate in variants:
            with self.subTest(candidate=candidate),self.assertRaises(RequestValidationError):
                validate_rebind(f.events(),f.prepared_id,candidate,f.scope)
        self.assertEqual(len(f.runner.invocations),0)

    def test_added_paths_cannot_expand_original_owner_write_roots_or_follow_escape(self):
        f=self.f; f.prepare(); self.add(path='src/extra.txt'); self.proposal()
        scope=deepcopy(f.scope); scope['task_write_roots']['MAKE-REPORT']=['outputs','src']
        with self.assertRaisesRegex(RequestValidationError,'original.*write roots'):
            self.prepare(scope=scope)
        candidate=deepcopy(f.events('BUILD_PLAN_PROPOSED')[-1]['payload'])
        outside=f.root/'outside'; outside.mkdir(); (f.workspace/'outputs/link').symlink_to(outside,target_is_directory=True)
        candidate['plan']['workpacks'][1]['artifacts'][-1]['path']='outputs/link/extra.txt'
        with self.assertRaisesRegex(RequestValidationError,'outside'):
            validate_rebind(f.events(),f.prepared_id,candidate,f.scope)

    def test_unknown_effects_block_addition_before_prepare(self):
        f=self.f; f.prepare()
        def crash(invocation,result): raise support.InjectedControllerCrash()
        f.runner.after_run=crash
        with self.assertRaises(support.InjectedControllerCrash): f.advance()
        self.add(); self.proposal()
        with self.assertRaisesRegex(RequestValidationError,'unresolved'):
            self.prepare()
        self.assertEqual(len(f.events('BUILD_AUTHORIZATION_PREPARED')),1)

    def test_current_plan_and_revoked_or_expired_grant_cannot_dispatch_additions(self):
        f=self.f; f.prepare(); self.add(); self.proposal(); new=self.prepare()
        self.proposal(key='newer')
        with self.assertRaisesRegex(RequestValidationError,'proposal changed'): self.approve(new)
        new=self.prepare(key='current'); self.approve(new,key='current')
        controller=f.controller(); controller.clock=lambda:datetime.fromisoformat('2100-01-01T00:00:00+00:00')
        result=controller.advance(new['event_id'])
        self.assertEqual(result['status'],'BUILD_STOPPED')
        revoke_build_authorization(f.store,f.program,new['event_id'],**f.kwargs('revoke'))
        self.assertEqual(f.controller().advance(new['event_id'])['status'],'BUILD_STOPPED')
        with self.assertRaisesRegex(RequestValidationError,'revoked'): self.approve(new,key='again')
        self.assertEqual(len(f.runner.invocations),0)

    def test_real_new_decision_may_continue_revoked_history_not_revive_old_grant(self):
        f=self.f; f.prepare(); f.controller().advance(f.prepared_id,advance_mode='ONE_ATTEMPT')
        revoke_build_authorization(f.store,f.program,f.prepared_id,**f.kwargs('revoke-old'))
        self.add(); self.proposal(); new=self.prepare(); self.approve(new)
        self.assertEqual(f.controller().advance(f.prepared_id)['status'],'BUILD_STOPPED')
        self.assertEqual(f.controller().advance(new['event_id'])['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(self.grant(new)['budget']['attempts_consumed'],2)

    def test_idempotent_prepare_approve_multihop_and_complete_report_recovery(self):
        f=self.f; f.prepare(); f.controller().advance(f.prepared_id,advance_mode='ONE_ATTEMPT')
        self.add(); self.proposal()
        kw=f.kwargs('same-prepare')
        args=(f.store,f.program,f.proposal_id,f.source_id,f.scope)
        new=prepare_build_authorization(*args,rebind_from=f.prepared_id,**kw)
        self.assertEqual(prepare_build_authorization(*args,rebind_from=f.prepared_id,**kw),new)
        ak=f.kwargs('same-approve'); args2=(f.store,f.program,new['event_id'])
        approved=approve_build_authorization(*args2,human_message_ref='TEST later decision',**ak)
        self.assertEqual(approve_build_authorization(*args2,human_message_ref='TEST later decision',**ak),approved)
        newer=self.prepare(origin=new['event_id'],key='next'); self.approve(newer,key='next')
        self.assertNotIn('artifact_additions',self.grant(newer))
        runner=DurableResourceFixtureRunner(); f.runner=runner
        def crash(invocation,result):
            runner.after_run=None
            raise support.InjectedControllerCrash()
        runner.after_run=crash
        with self.assertRaises(support.InjectedControllerCrash):f.controller().advance(newer['event_id'])
        self.assertEqual(f.controller().advance(newer['event_id'])['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual([i['phase'] for i in runner.invocations],['IMPLEMENTATION','VERIFICATION'])
        events=deepcopy(f.events())
        for _ in range(2):
            self.assertEqual(f.controller().advance(newer['event_id'])['status'],'PLAN_CHECKS_ACCEPTED')
            self.assertEqual(self.grant(newer)['budget']['attempts_consumed'],2)
        self.assertEqual(f.events(),events)
        self.assertEqual(len(runner.invocations),2)

    def test_addition_and_exact_budget_extension_share_old_consumption(self):
        f=self.f; f.scope.update(max_attempts=1,max_task_attempts=1); f.prepare()
        self.assertEqual(f.advance()['status'],'ATTEMPT_BUDGET_EXHAUSTED')
        self.add(); self.proposal()
        no_increase=self.prepare(); self.approve(no_increase)
        self.assertEqual(f.controller().advance(no_increase['event_id'])['status'],'ATTEMPT_BUDGET_EXHAUSTED')
        new=self.prepare(origin=no_increase['event_id'],key='increase',scope={**f.scope,'max_attempts':2},
            extension={'additional_attempts':1,'additional_task_attempts':0,'reason':'TEST new total allowance'})
        self.approve(new,key='increase')
        self.assertEqual(f.controller().advance(new['event_id'])['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(self.grant(new)['budget']['attempts_consumed'],2)
        self.assertEqual(self.grant(new)['budget']['attempts_remaining'],0)

    def test_missing_new_output_is_not_covered_by_an_old_pass(self):
        f=self.f; f.prepare(); f.controller().advance(f.prepared_id,advance_mode='ONE_ATTEMPT')
        command=f.plan['workpacks'][1]['local_argv'][-1]
        self.add(); f.plan['workpacks'][1]['local_argv'][-1]=command
        self.proposal(); new=self.prepare(); self.approve(new)
        result=f.controller().advance(new['event_id'],advance_mode='ONE_ATTEMPT')
        self.assertNotEqual(result['attempt_status'],'ACCEPTED')
        self.assertNotIn('MAKE-REPORT',project_execution_state(f.events(),new['event_id'])[1])
        self.assertEqual(self.grant(new)['budget']['attempts_consumed'],2)

    def test_compiler_still_requires_new_output_checks_and_effects(self):
        f=self.f; f.prepare(); self.add()
        f.plan['workpacks'][1]['verification'][0]['artifact_ids'].remove('SUPPLEMENT')
        with self.assertRaisesRegex(RequestValidationError,'every output'):self.proposal(key='unchecked')
        f.plan['workpacks'][1]['verification'][0]['artifact_ids'].append('SUPPLEMENT')
        f.plan['schema_version']='1.1'
        f.plan['workpacks'][1]['effects']={'required':['outputs/summary.json'],
            'allowed':['outputs/summary.json'],'must_preserve':[]}
        with self.assertRaisesRegex(RequestValidationError,'all declared output'):self.proposal(key='effects')

    def test_added_successor_version_uses_existing_replacement_checks(self):
        f=self.f
        f.scope['task_write_roots']['MAKE-REPORT'].append('src')
        f.prepare(); f.controller().advance(f.prepared_id,advance_mode='ONE_ATTEMPT')
        self.add(path='src/reader.py')
        task=f.plan['workpacks'][1]
        task['artifacts'][-1]['replaces_artifact_id']='READER-SOURCE'
        self.proposal(); new=self.prepare(); self.approve(new)
        self.assertEqual(f.controller().advance(new['event_id'])['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(self.grant(new)['budget']['attempts_consumed'],2)
        newer=self.prepare(origin=new['event_id'],key='reuse'); relation=self.approve(newer,key='reuse')['payload']['rebind']
        self.assertEqual(set(relation['accepted']),{'IMPLEMENT-READER','MAKE-REPORT'})
        count=len(f.runner.invocations)
        self.assertEqual(f.controller().advance(newer['event_id'])['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(len(f.runner.invocations),count)

    def test_new_source_evidence_does_not_reuse_accepted_result(self):
        f=self.f; f.prepare(); f.controller().advance(f.prepared_id,advance_mode='ONE_ATTEMPT')
        original=f.source/'brief.md'
        original.write_text(f.source_text+'Additional source fact.\n')
        from tests.build_review_fixture import reviewed_document
        f.review=reviewed_document(f.source,path=original)
        f.review['version']='test-v2'
        f.review['decision']['actor']['turn_id']='TEST-NEW-DOCUMENT-CONFIRMATION'
        self.add(); self.proposal(); new=self.prepare(); relation=self.approve(new)['payload']['rebind']
        self.assertIn('IMPLEMENT-READER',relation['rebuild_workpack_ids'])
        self.assertFalse(relation['accepted'])

    def test_no_new_checks_can_be_authorized_when_preparation_is_revoked(self):
        f=self.f; f.prepare(); self.add(); self.proposal(); new=self.prepare()
        revoke_build_authorization(f.store,f.program,new['event_id'],**f.kwargs('revoke-pending'))
        with self.assertRaisesRegex(RequestValidationError,'revoked'): self.approve(new)
        self.assertEqual(f.controller().advance(new['event_id'])['status'],'BUILD_STOPPED')
        self.assertEqual(self.grant(new)['budget']['attempts_consumed'],0)
        self.assertEqual(len(f.runner.invocations),0)

    def test_relative_paths_with_spaces_and_unchanged_semantic_write_root_are_legal(self):
        f=self.f; f.prepare()
        (f.workspace/'outputs'/'notes here').mkdir()
        self.add(path='outputs/notes here/补充.txt'); self.proposal()
        scope=deepcopy(f.scope); scope['task_write_roots']['MAKE-REPORT']=['outputs/notes here','outputs']
        new=self.prepare(scope=scope); self.approve(new)
        self.assertEqual(f.controller().advance(new['event_id'])['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual((f.workspace/'outputs/notes here/补充.txt').read_text(),'declared supplement\n')

    def test_task_identity_job_and_dependency_reassignment_remain_rejected(self):
        f=self.f; f.prepare(); self.add()
        proposal=self.proposal()
        for field,value in [('workpack_id','NEW-TASK'),('job_id','NEW-JOB'),('depends_on',[])]:
            candidate=deepcopy(proposal); candidate['plan']['workpacks'][1][field]=value
            with self.subTest(field=field),self.assertRaises(RequestValidationError):
                validate_rebind(f.events(),f.prepared_id,candidate,f.scope)

    def test_new_unresolved_attempt_after_prepare_is_rechecked_at_approval(self):
        f=self.f; f.prepare(); self.add(); self.proposal(); new=self.prepare()
        # Simulate a durable late reservation from the old worker; approval must
        # inspect it again, not trust the earlier clean preparation snapshot.
        old=next(e['payload'] for e in f.events() if e['event_id']==f.prepared_id)
        f.store.append_batch(f.program,[{'event_type':'BUILD_ATTEMPT_STARTED','payload':{
            'prepared_event_id':f.prepared_id,'attempt_id':'TEST-LATE-ATTEMPT',
            'proposal_event_id':old['proposal_event_id'],'workpack_id':'MAKE-REPORT',
            'job_id':'REPORT','budget_workpack_ids':['MAKE-REPORT']}}],**f.kwargs('late-start'))
        with self.assertRaisesRegex(RequestValidationError,'unresolved'): self.approve(new)
        self.assertEqual(self.grant(new)['budget']['attempts_consumed'],1)

    def test_duplicate_id_and_undeclared_same_path_replacement_remain_rejected(self):
        f=self.f; f.prepare(); self.add()
        task=f.plan['workpacks'][1]
        for field,value in [('artifact_id','READER-SOURCE'),('path','src/reader.py')]:
            original=deepcopy(task['artifacts'][-1]); task['artifacts'][-1][field]=value
            with self.subTest(field=field),self.assertRaises(RequestValidationError): self.proposal(key=field)
            task['artifacts'][-1]=original

    def replacement_pending(self):
        f=self.f
        f.scope['task_write_roots']['MAKE-REPORT'].append('src')
        f.prepare(); f.advance()
        self.add(path='src/reader.py')
        f.plan['workpacks'][1]['artifacts'][-1]['replaces_artifact_id']='READER-SOURCE'
        self.proposal(); new=self.prepare(); self.approve(new)
        return new

    def test_old_task_start_does_not_consume_later_added_replacement(self):
        new=self.replacement_pending(); f=self.f
        root=f.root/'checker-r2'; root.mkdir()
        (root/'check.py').write_bytes((f.verifier/'check.py').read_bytes()+b'\n# checker binding change\n')
        pending=self.prepare(origin=new['event_id'],key='checker',scope={**f.scope,'verification_root':str(root)})
        relation=self.approve(pending,key='checker')['payload']['rebind']
        self.assertEqual(list(relation['verification_pending']),['IMPLEMENT-READER'])
        self.assertEqual(f.controller().advance(pending['event_id'])['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(self.grant(pending)['budget']['attempts_consumed'],4)

    def test_old_task_start_cannot_hide_drift_before_new_replacement_dispatch(self):
        new=self.replacement_pending(); f=self.f
        (f.workspace/'src/reader.py').write_text('wrong old input\n')
        count=len(f.runner.invocations)
        self.assertEqual(f.controller().advance(new['event_id'])['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual([i['workpack_id'] for i in f.runner.invocations[count:] if i['phase']=='IMPLEMENTATION'],
                         ['IMPLEMENT-READER','MAKE-REPORT'])
        self.assertEqual(self.grant(new)['budget']['attempts_consumed'],4)

    def test_model_prompt_binds_added_declarations_to_actual_new_approval(self):
        from harness_foundry_factory.build_authoring import read_build_task_context
        f=self.f; captured=[]; f.runner=f._codex_fixture_runner(captured); f.prepare()
        task=f.plan['workpacks'][0]
        addition={'artifact_id':'EXTRA','path':'src/extra.txt'}
        task['artifacts'].append(addition)
        task['verification'][0]['artifact_ids'].append('EXTRA')
        self.proposal(); new=self.prepare()
        static=read_build_task_context(f.store,f.program,'IMPLEMENT-READER',event_id=f.proposal_id)
        self.assertFalse(static['authority_validated'])
        self.assertEqual(f.controller().advance(new['event_id'])['status'],'BUILD_STOPPED')
        approved=self.approve(new)
        controller=f.controller(); _,prepared,plan=controller._current(new['event_id'])
        invocation=controller._invocation(prepared,plan['workpacks'][0],[])
        context=json.loads(invocation['prompt'].split('\n',1)[1])['task']
        self.assertEqual(context['workpack']['artifacts'][-1],addition)
        auth=context['runtime_authorization']
        self.assertEqual(auth['prepared_event_id'],new['event_id'])
        self.assertEqual(auth['approval_event_id'],approved['event_id'])
        self.assertEqual(auth['proposal_event_id'],f.proposal_id)
        self.assertEqual(invocation['write_roots'],[str(f.workspace/'src')])
        self.assertEqual(captured,[], 'prompt binding is not a real model call')


if __name__ == '__main__':
    unittest.main()
