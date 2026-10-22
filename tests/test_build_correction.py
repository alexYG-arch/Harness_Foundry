"""Same-scope host corrections in disposable Programs, never real grants/models."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import unittest

from harness_foundry_factory.build_correction import (
    POLICY, REVERIFY_KIND, TECHNICAL_POLICY, completed_implementation_candidates,
    derive_checker_authorization, resolve_technical_attempt, validate_authority_chain,
)
from harness_foundry_factory.build_runtime import (prepare_build_authorization,
    approve_build_authorization, revoke_build_authorization, classify_verification_result)
from harness_foundry_factory.build_state import project_execution_state, project_budget_attempts, attempt_budget
from harness_foundry_factory.build_types import RequestValidationError, IdempotencyConflictError, RevisionConflictError
import test_build_runtime as support
from test_build_resources import DurableResourceFixtureRunner


def host_review(policy=POLICY):
    return {"policy":policy,"actor":{"type":"TRUSTED_CODEX_HOST","chat_thread_id":"TEST-HOST","turn_id":"TEST-REVIEW"},
            "reason":"TEST: correct omitted checker adapter argument; unchanged public assertions reviewed",
            "evidence_refs":["TEST independent adapter diff and public expected cases"],
            "decision":"EQUIVALENT_CHECKER_CORRECTION" if policy == POLICY else "TECHNICAL_FALSE_BLOCK_CONFIRMED"}


class CheckerCorrectionTests(unittest.TestCase):
    def setUp(self):
        f = self.f = support.BuildRuntimeTests(); f.setUp(); self.addCleanup(f.doCleanups)
        self.runner = DurableResourceFixtureRunner()
        def run(invocation,before):
            result=self.runner(invocation,before)
            return classify_verification_result(result) if invocation['phase']=='VERIFICATION' else result
        f.runner=run

    def prepare_failure(self, *, whole_budget=False):
        f=self.f
        if whole_budget: f.scope['max_attempts']=1
        (f.verifier/'check.py').write_text("raise PermissionError('TEST checker adapter problem')\n")
        f.prepare()
        result=f.controller().advance(f.prepared_id,advance_mode='ONE_ATTEMPT')
        self.assertEqual(result['attempt_status'],'BLOCKED',result)
        self.attempt_id=result['attempt_id']
        return result

    def evidence(self, old, new, *, complete=None):
        f=self.f;events=f.events()
        before=next(e['payload'] for e in events if e['event_id']==old)
        after=next(e['payload'] for e in events if e['event_id']==new)
        return {'review':host_review(),'source_prepared_event_id':old,
            'old_verifier_files':before['verifier_files'],'new_verifier_files':after['verifier_files'],
            'preserved_case_ids':[c['case_id'] for t in f.plan['workpacks'] for c in t['verification']],
            'changed_files':{name:{'role':'CHECKER_ADAPTER','reason':'TEST adapter-only diff reviewed'}
                             for name in before['verifier_files'].keys() | after['verifier_files'].keys()
                             if before['verifier_files'].get(name)!=after['verifier_files'].get(name)},
            'completed_attempts':{} if complete is None else {complete:self.completed_receipt(complete)}}

    def completed_receipt(self, attempt_id):
        history=project_budget_attempts(self.f.events(),self.f.prepared_id)
        ids=[e['payload']['command_id'] for e in self.f.events('BUILD_COMMAND_OBSERVED')
             if e['payload']['attempt_id']==attempt_id]
        return {'artifacts':deepcopy(history[attempt_id]['artifacts']), 'effects':{
            'status':'EFFECTS_RECONCILED','command_ids':ids,'detail':'TEST original local writes and process exit independently inspected',
            'evidence_refs':['TEST real local capture and declared artifact inspection']}}

    def new_binding(self, *, origin=None, scope=None, key='correction', complete=None):
        f=self.f;old=origin or f.prepared_id
        root=f.root/key;root.mkdir();(root/'check.py').write_text(support.VERIFIER+'\n# '+key+'\n')
        prepared=prepare_build_authorization(f.store,f.program,f.proposal_id,f.source_id,
            scope or {**f.scope,'verification_root':str(root)},rebind_from=old,**f.kwargs(key+'-prepare'))
        new=prepared['event_id']; evidence=self.evidence(old,new,complete=complete)
        return new,evidence

    def derive(self, new, evidence, key='derive'):
        return derive_checker_authorization(self.f.store,self.f.program,new,evidence=evidence,**self.f.kwargs(key))

    def test_unaccepted_complete_implementation_is_pending_never_prefaked_accepted(self):
        self.prepare_failure();f=self.f
        new,evidence=self.new_binding(complete=self.attempt_id)
        approved=self.derive(new,evidence)
        pending=approved['payload']['rebind']['verification_pending']['IMPLEMENT-READER']
        self.assertEqual(pending['attempt_id'],self.attempt_id)
        self.assertEqual(pending['reverify_kind'],REVERIFY_KIND)
        self.assertEqual(pending['production_budget_charge'],0)
        self.assertEqual(project_execution_state(f.events(),new)[1],{})
        self.assertEqual(project_budget_attempts(f.events(),new)[self.attempt_id]['status'],'BLOCKED')
        self.assertNotIn('human_message_ref',approved['payload'])
        self.assertEqual(validate_authority_chain(f.events(),new,support.NOW)[-1],f.events('BUILD_AUTHORIZATION_APPROVED')[0]['event_id'])

    def test_production_budget_exhausted_can_finish_new_only_verification(self):
        self.prepare_failure(whole_budget=True);f=self.f
        new,evidence=self.new_binding(complete=self.attempt_id);self.derive(new,evidence)
        before=len(self.runner.invocations)
        result=f.controller().advance(new,advance_mode='ONE_ATTEMPT')
        self.assertEqual(result['attempt_status'],'ACCEPTED',result)
        self.assertEqual([c['phase'] for c in self.runner.invocations[before:]],['VERIFICATION','VERIFICATION'])
        budget=attempt_budget(f.scope,list(project_budget_attempts(f.events(),new).values()))
        self.assertEqual(budget['attempts_consumed'],1)
        self.assertEqual(budget['attempts_remaining'],0)
        self.assertEqual(f.controller().advance(new)['status'],'ATTEMPT_BUDGET_EXHAUSTED')
        self.assertEqual(project_budget_attempts(f.events(),new)[self.attempt_id]['status'],'BLOCKED')

    def test_complete_new_check_recovers_once_without_old_failure_or_recount(self):
        self.prepare_failure();f=self.f
        new,evidence=self.new_binding(complete=self.attempt_id);self.derive(new,evidence)
        before=len(self.runner.invocations)
        def crash(invocation,result):
            self.runner.after_run=None
            raise support.InjectedControllerCrash()
        self.runner.after_run=crash
        with self.assertRaises(support.InjectedControllerCrash):f.controller().advance(new,advance_mode='ONE_ATTEMPT')
        result=f.controller().advance(new,advance_mode='ONE_ATTEMPT')
        self.assertEqual(result['attempt_status'],'ACCEPTED',result)
        self.assertEqual([c['case_id'] for c in self.runner.invocations[before:]],['READ-ROWS','REJECT-MALFORMED'])
        attempts=project_budget_attempts(f.events(),new)
        self.assertEqual(attempt_budget(f.scope,list(attempts.values()))['attempts_consumed'],1)
        self.assertEqual(len(attempts),2)
        self.assertEqual(attempts[self.attempt_id]['status'],'BLOCKED')

    def test_source_revocation_blocks_actual_dispatch_but_old_readback_remains(self):
        from harness_foundry_factory.build_entrypoint import read_build
        self.prepare_failure();f=self.f
        new,evidence=self.new_binding(complete=self.attempt_id);self.derive(new,evidence)
        revoke_build_authorization(f.store,f.program,f.prepared_id,**f.kwargs('source-revoke'))
        before=len(self.runner.invocations)
        self.assertEqual(f.controller().advance(new)['status'],'BUILD_STOPPED')
        self.assertEqual(len(self.runner.invocations),before)
        readback=read_build(f.store.database_path,f.program)
        self.assertTrue(readback['attempts'])
        self.assertEqual(len(readback['attempts']),1)

    def test_failed_resource_retention_is_complete_evidence_for_correction(self):
        from test_build_resources import BuildResourceIntegrationTests, RESOURCE_CHECKER
        support_case=BuildResourceIntegrationTests();f=support_case.fixture(mode='pass')
        self.addCleanup(support_case.doCleanups);self.f=f
        (f.verifier/'check.py').write_text("raise PermissionError('TEST missing adapter setup')\n")
        f.prepare();result=f.controller().advance(f.prepared_id,advance_mode='ONE_ATTEMPT')
        self.assertEqual(result['attempt_status'],'BLOCKED',result);self.attempt_id=result['attempt_id']
        command=f.events('BUILD_COMMAND_OBSERVED')[-1]['payload']
        self.assertEqual(command['result']['resource_cleanup']['status'],'RETAINED')
        root=f.root/'fixed';root.mkdir();(root/'check.py').write_text(RESOURCE_CHECKER)
        new=prepare_build_authorization(f.store,f.program,f.proposal_id,f.source_id,
            {**f.scope,'verification_root':str(root)},rebind_from=f.prepared_id,**f.kwargs('p'))['event_id']
        self.derive(new,self.evidence(f.prepared_id,new,complete=self.attempt_id))
        count=len(f.runner.invocations)
        result=f.controller().advance(new,advance_mode='ONE_ATTEMPT')
        self.assertEqual(result['attempt_status'],'ACCEPTED',result)
        self.assertEqual([c['phase'] for c in f.runner.invocations[count:]],['VERIFICATION','VERIFICATION'])
        self.assertTrue(Path(command['resource_binding']['root']).is_dir(),'old failure materials retained')

    def test_ordinary_human_rebind_after_free_correction_keeps_original_charge_rule(self):
        f=self.f;f.prepare();self.assertEqual(f.advance()['status'],'PLAN_CHECKS_ACCEPTED')
        first,evidence=self.new_binding();self.derive(first,evidence)
        self.assertEqual(f.controller().advance(first)['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(attempt_budget(f.scope,list(project_budget_attempts(f.events(),first).values()))['attempts_consumed'],2)
        second,evidence=self.new_binding(origin=first,key='ordinary')
        approval=approve_build_authorization(f.store,f.program,second,human_message_ref='TEST actual independent approval',**f.kwargs('ordinary-approve'))
        self.assertTrue(approval['payload']['rebind']['verification_pending'])
        self.assertTrue(all('reverify_kind' not in row and 'production_budget_charge' not in row
                            for row in approval['payload']['rebind']['verification_pending'].values()))
        self.assertEqual(f.controller().advance(second)['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(attempt_budget(f.scope,list(project_budget_attempts(f.events(),second).values()))['attempts_consumed'],4)
        self.assertEqual(sum(a.get('production_budget_charge')==0 for a in project_execution_state(f.events(),second)[0].values()),0)

    def test_exact_replay_does_not_append_or_recount(self):
        self.prepare_failure();f=self.f;new,evidence=self.new_binding(complete=self.attempt_id)
        kwargs=f.kwargs('derive');one=derive_checker_authorization(f.store,f.program,new,evidence=evidence,**kwargs)
        count=len(f.events())
        self.assertEqual(derive_checker_authorization(f.store,f.program,new,evidence=evidence,**kwargs),one)
        self.assertEqual(len(f.events()),count)
        changed=deepcopy(evidence);changed['review']['reason']='different'
        with self.assertRaises(IdempotencyConflictError):derive_checker_authorization(f.store,f.program,new,evidence=changed,**kwargs)

    def test_human_approval_cannot_reuse_derived_approval_key(self):
        self.prepare_failure(); f=self.f
        new,evidence=self.new_binding(complete=self.attempt_id)
        kwargs=f.kwargs('shared-approval-key')
        approved=derive_checker_authorization(f.store,f.program,new,evidence=evidence,**kwargs)
        events=deepcopy(f.events())
        with self.assertRaises(IdempotencyConflictError):
            approve_build_authorization(f.store,f.program,new,
                human_message_ref='TEST separate human approval',**kwargs)
        self.assertEqual(f.events(),events)
        self.assertEqual(f.store.idempotent_events(f.program,kwargs['idempotency_key']),[approved])

    def test_revision_conflict_before_grant(self):
        self.f.prepare();new,evidence=self.new_binding();kwargs=self.f.kwargs('derive');kwargs['expected_revision']-=1
        with self.assertRaises(RevisionConflictError):derive_checker_authorization(self.f.store,self.f.program,new,evidence=evidence,**kwargs)
        self.assertEqual(len(self.f.events('BUILD_AUTHORIZATION_APPROVED')),1)

    def test_no_wholesale_blocked_import_without_specific_producer_review(self):
        self.prepare_failure();new,evidence=self.new_binding()
        approved=self.derive(new,evidence)
        self.assertEqual(approved['payload']['rebind']['verification_pending'],{})

    def test_missing_capture_is_not_qualified_by_file_bytes_or_process_absence(self):
        self.prepare_failure();new,evidence=self.new_binding(complete=self.attempt_id)
        command=self.f.events('BUILD_COMMAND_OBSERVED')[0]['payload']
        (Path(command['observation_root'])/'capture.json').unlink()
        with self.assertRaisesRegex(RequestValidationError,'complete durable'):self.derive(new,evidence)

    def test_truncated_raw_capture_is_not_eligible(self):
        self.prepare_failure();new,evidence=self.new_binding(complete=self.attempt_id)
        command=self.f.events('BUILD_COMMAND_OBSERVED')[-1]['payload']
        (Path(command['observation_root'])/'stderr.bin').write_bytes(b'')
        with self.assertRaisesRegex(RequestValidationError,'incomplete'):self.derive(new,evidence)

    def test_changed_product_is_not_reused(self):
        self.prepare_failure();new,evidence=self.new_binding(complete=self.attempt_id)
        (self.f.workspace/'src/reader.py').write_text(support.BAD_READER)
        with self.assertRaisesRegex(RequestValidationError,'product bytes changed'):self.derive(new,evidence)

    def test_missing_effects_review_is_not_replaced_by_unchanged_files(self):
        self.prepare_failure();new,evidence=self.new_binding(complete=self.attempt_id)
        evidence['completed_attempts'][self.attempt_id]['effects']['evidence_refs']=[]
        with self.assertRaisesRegex(RequestValidationError,'reconcile all command effects'):self.derive(new,evidence)

    def test_implementation_did_not_pass_is_not_eligible(self):
        self.prepare_failure();events=deepcopy(self.f.events())
        for row in events:
            if row['event_type']=='BUILD_COMMAND_OBSERVED' and row['payload']['phase']=='IMPLEMENTATION':
                row['payload']['result']['status']='MODEL_PROCESS_FAILED'
        with self.assertRaises(RequestValidationError):
            completed_implementation_candidates(events,self.f.prepared_id,{self.attempt_id:self.completed_receipt(self.attempt_id)})

    def test_no_permission_model_budget_or_expiry_expansion(self):
        for field,value in [('command_timeout_seconds',6),('max_attempts',6),('expires_at','2026-09-18T02:00:00Z')]:
            with self.subTest(field=field):
                f=support.BuildRuntimeTests();f.setUp()
                try:
                    f.prepare();root=f.root/'fixed';root.mkdir();(root/'check.py').write_text(support.VERIFIER)
                    scope={**f.scope,'verification_root':str(root),field:value}
                    if field=='max_attempts':
                        with self.assertRaises(RequestValidationError):prepare_build_authorization(f.store,f.program,f.proposal_id,f.source_id,scope,rebind_from=f.prepared_id,**f.kwargs('p'))
                        continue
                    prepared=prepare_build_authorization(f.store,f.program,f.proposal_id,f.source_id,scope,rebind_from=f.prepared_id,**f.kwargs('p'))
                    oldself=self.f;self.f=f
                    evidence=self.evidence(f.prepared_id,prepared['event_id']);self.f=oldself
                    with self.assertRaisesRegex(RequestValidationError,'same-scope correction'):
                        derive_checker_authorization(f.store,f.program,prepared['event_id'],evidence=evidence,**f.kwargs('derive'))
                finally:f.doCleanups()

    def test_changed_expected_answer_is_not_same_scope_adapter_fix(self):
        self.f.prepare();new,evidence=self.new_binding()
        evidence['changed_files']['check.py']['role']='EXPECTED_ANSWER'
        with self.assertRaisesRegex(RequestValidationError,'changed expectations'):
            self.derive(new,evidence)

    def test_declared_checker_code_dependency_can_be_fixed_with_explicit_review(self):
        from test_build_resources import BuildResourceIntegrationTests
        support_case=BuildResourceIntegrationTests()
        f=support_case.fixture(mode='pass');self.addCleanup(support_case.doCleanups)
        self.f=f
        f.scope['verification_resources']['checker_files']=['helper.py']
        (f.verifier/'helper.py').write_text('def argument(): return {}\n')
        f.prepare();old=f.prepared_id
        root=f.root/'corrected';root.mkdir()
        (root/'check.py').write_text((f.verifier/'check.py').read_text())
        (root/'helper.py').write_text('def argument(): return dict()\n')
        new=prepare_build_authorization(f.store,f.program,f.proposal_id,f.source_id,
            {**f.scope,'verification_root':str(root)},rebind_from=old,**f.kwargs('new'))['event_id']
        result=self.derive(new,self.evidence(old,new))
        self.assertEqual(result['payload']['derived_authority']['source_prepared_event_id'],old)

    def test_new_declared_adapter_helper_stays_inside_existing_protected_scope(self):
        from test_build_resources import BuildResourceIntegrationTests
        support_case=BuildResourceIntegrationTests();f=support_case.fixture(mode='pass')
        self.addCleanup(support_case.doCleanups);self.f=f;f.prepare()
        root=f.root/'helper-fix';root.mkdir()
        (root/'check.py').write_text((f.verifier/'check.py').read_text())
        (root/'helper.py').write_text('def arguments(): return {}\n')
        scope=deepcopy(f.scope);scope['verification_root']=str(root)
        scope['verification_resources']['checker_files']=['helper.py']
        new=prepare_build_authorization(f.store,f.program,f.proposal_id,f.source_id,scope,
            rebind_from=f.prepared_id,**f.kwargs('helper-new'))['event_id']
        evidence=self.evidence(f.prepared_id,new)
        result=self.derive(new,evidence)
        self.assertEqual(result['payload']['correction_request']['evidence']['changed_files']['helper.py']['role'],'CHECKER_ADAPTER')

    def test_forged_target_or_human_label_is_not_host_correction(self):
        self.f.prepare();new,evidence=self.new_binding()
        for label in ('HUMAN_VIA_CODEX_CHAT','IMPLEMENTATION_AGENT'):
            evidence['review']['actor']['type']=label
            with self.assertRaisesRegex(RequestValidationError,'trusted host'):self.derive(new,evidence)

    def test_all_assertions_must_remain_declared_and_reviewed(self):
        self.f.prepare();new,evidence=self.new_binding();evidence['preserved_case_ids'].pop()
        with self.assertRaisesRegex(RequestValidationError,'every original independent'):self.derive(new,evidence)

    def test_checker_mutation_after_prepare_cannot_inherit(self):
        self.f.prepare();new,evidence=self.new_binding()
        prepared=next(e['payload'] for e in self.f.events() if e['event_id']==new)
        (Path(prepared['scope']['verification_root'])/'check.py').write_text('print("PASS")')
        with self.assertRaisesRegex(RequestValidationError,'checker bytes changed'):self.derive(new,evidence)

    def test_revoked_source_blocks_derivation(self):
        f=self.f;f.prepare();new,evidence=self.new_binding()
        revoke_build_authorization(f.store,f.program,f.prepared_id,**f.kwargs('revoke'))
        with self.assertRaisesRegex(RequestValidationError,'revoked'):self.derive(new,evidence)

    def test_expired_source_blocks_derivation(self):
        self.f.prepare();new,evidence=self.new_binding();kwargs=self.f.kwargs('derive');kwargs['created_at']='2026-09-18T02:00:00Z'
        with self.assertRaisesRegex(RequestValidationError,'expired'):
            derive_checker_authorization(self.f.store,self.f.program,new,evidence=evidence,**kwargs)

    def test_superseded_source_remains_authority_until_revocation(self):
        f=self.f;f.prepare();old=f.prepared_id;new,evidence=self.new_binding();self.derive(new,evidence)
        self.assertTrue(validate_authority_chain(f.events(),new,support.NOW))
        revoke_build_authorization(f.store,f.program,old,**f.kwargs('revoke'))
        with self.assertRaisesRegex(RequestValidationError,'revoked'):validate_authority_chain(f.events(),new,support.NOW)

    def test_revoked_intermediate_cannot_be_skipped_using_root(self):
        f=self.f;f.prepare();new,evidence=self.new_binding();self.derive(new,evidence)
        newer,evidence2=self.new_binding(origin=new,key='second');self.derive(newer,evidence2,key='derive-second')
        revoke_build_authorization(f.store,f.program,new,**f.kwargs('revoke-middle'))
        with self.assertRaisesRegex(RequestValidationError,'revoked'):validate_authority_chain(f.events(),newer,support.NOW)

    def test_independent_human_rebind_does_not_inherit_old_revocation(self):
        f=self.f;f.prepare();new,evidence=self.new_binding()
        approve_build_authorization(f.store,f.program,new,human_message_ref='TEST NEW independent approval',**f.kwargs('human'))
        revoke_build_authorization(f.store,f.program,f.prepared_id,**f.kwargs('old-revoke'))
        self.assertEqual(len(validate_authority_chain(f.events(),new,support.NOW)),1)

    def test_completed_old_receipt_retrieval_survives_source_revocation(self):
        f=self.f;f.prepare();new,evidence=self.new_binding();kwargs=f.kwargs('derive')
        old=derive_checker_authorization(f.store,f.program,new,evidence=evidence,**kwargs)
        revoke_build_authorization(f.store,f.program,f.prepared_id,**f.kwargs('old-revoke'))
        self.assertEqual(derive_checker_authorization(f.store,f.program,new,evidence=evidence,**kwargs),old)

    def prepare_technical_block(self, *, completed=False):
        from harness_foundry_factory.process_observation import CommandObservation
        from harness_foundry_factory.coding_process import classify_coding_capture
        from harness_foundry_factory.coding_events import CodingEventObserver
        f=self.f
        f.plan['workpacks'][0]['executor']='CODEX';f.plan['workpacks'][0].pop('local_argv')
        f.scope.update(model='TEST-NOT-A-MODEL',allow_model_service=True)
        if completed:
            (f.verifier/'check.py').write_text("raise PermissionError('TEST checker adapter')\n")
        def run(invocation,before):
            if invocation['executor']=='LOCAL':
                result=self.runner(invocation,before)
                return classify_verification_result(result) if invocation['phase']=='VERIFICATION' else result
            before()
            if completed:(f.workspace/'src/reader.py').write_text(support.GOOD_READER)
            blocker={'foundry_blocker':{'failure_kind':'CONTRACT_GAP','reason':'TEST stale unauthorized context',
                'owner':'HOST','minimum_return_path':'CHECK_CONTEXT','evidence':['TEST received stale instruction']}}
            rows=[{'type':'thread.started','thread_id':'TEST-ONLY'}, {'type':'turn.started'},
                  {'type':'item.completed','item':{'type':'agent_message','text':'TEST product complete' if completed else json.dumps(blocker)}},
                  {'type':'turn.completed','usage':{'input_tokens':2,'output_tokens':3}}]
            data=b''.join((json.dumps(row)+'\n').encode() for row in rows)
            config={'model':'TEST-NOT-A-MODEL','model_policy':'FIXED','model_reasoning_effort':None,
                    'model_service':{'provider':'openai','config':{}},'model_defaults_source':None}
            capture={'exit_code':0,'timed_out':False,'stdout':'','stderr':'','stream_bytes':{'stdout':len(data),'stderr':0},
                     'model_configuration':config}
            observer=CodingEventObserver();observer.feed(data)
            result=classify_coding_capture(capture,observer)
            journal=CommandObservation(invocation['observation_root'],invocation['command_id'],'CODEX')
            journal.model_configuration(config);journal.write('stdout',data);journal.write('stderr',b'')
            journal.captured(capture);journal.finished(result);journal.close()
            return result
        f.runner=run;f.prepare()
        result=f.controller().advance(f.prepared_id,advance_mode='ONE_ATTEMPT')
        self.assertEqual(result['attempt_status'],'BLOCKED',result);self.attempt_id=result['attempt_id']

    def test_model_configuration_receipt_required_for_completed_producer(self):
        self.prepare_technical_block(completed=True);f=self.f
        new,evidence=self.new_binding(complete=self.attempt_id)
        command=next(e['payload'] for e in f.events('BUILD_COMMAND_OBSERVED') if e['payload']['executor']=='CODEX')
        (Path(command['observation_root'])/'model-configuration.json').unlink()
        with self.assertRaisesRegex(RequestValidationError,'original configuration receipt'):
            self.derive(new,evidence)

    def test_completed_model_producer_receipt_and_only_check_continuation(self):
        self.prepare_technical_block(completed=True);f=self.f
        new,evidence=self.new_binding(complete=self.attempt_id);self.derive(new,evidence)
        before=len(f.events('BUILD_COMMAND_PLANNED'))
        result=f.controller().advance(new,advance_mode='ONE_ATTEMPT')
        self.assertEqual(result['attempt_status'],'ACCEPTED',result)
        self.assertEqual([e['payload']['executor'] for e in f.events('BUILD_COMMAND_PLANNED')[before:]],['LOCAL','LOCAL'])
        self.assertEqual(attempt_budget(f.scope,list(project_budget_attempts(f.events(),new).values()))['attempts_consumed'],1)

    def test_real_product_failure_after_correction_spends_original_next_production(self):
        self.f.plan['workpacks'][0]['local_argv'][-1]=self.f.write_reader(support.BAD_READER)
        self.prepare_failure();f=self.f
        root=f.root/'assertion-checker';root.mkdir()
        checker="import json\ntry:\n    exec("+repr(support.VERIFIER)+")\nexcept AssertionError:\n    print(json.dumps({'status':'CHECKS_FAILED','failure_kind':'ASSERTION'}))\n    raise SystemExit(1)\n"
        (root/'check.py').write_text(checker)
        new=prepare_build_authorization(f.store,f.program,f.proposal_id,f.source_id,
            {**f.scope,'verification_root':str(root)},rebind_from=f.prepared_id,**f.kwargs('p'))['event_id']
        self.derive(new,self.evidence(f.prepared_id,new,complete=self.attempt_id))
        result=f.controller().advance(new,advance_mode='ONE_ATTEMPT')
        self.assertEqual(result['attempt_status'],'REJECTED',result)
        self.assertEqual(result['budget']['attempts_consumed'],1)
        next_result=f.controller().advance(new,advance_mode='ONE_ATTEMPT')
        self.assertEqual(next_result['attempt_status'],'REJECTED',next_result)
        self.assertEqual(next_result['budget']['attempts_consumed'],2)
        attempts=project_execution_state(f.events(),new)[0]
        self.assertEqual(sum(bool(a.get('reverify_kind')) for a in attempts.values()),1)

    def technical_evidence(self):
        receipt=self.completed_receipt(self.attempt_id)
        return {'review':host_review(TECHNICAL_POLICY),'effects':receipt['effects'],
                'command_ids':receipt['effects']['command_ids'],
                'classification':'TECHNICAL_FALSE_BLOCK_PUBLIC_SCOPE_COMPLETE',
                'public_basis':self.f.events('BUILD_AUTHORIZATION_PREPARED')[0]['payload']['acceptance_contracts']}

    def test_host_technical_disposition_is_not_new_approval_or_old_acceptance(self):
        self.prepare_technical_block();f=self.f;before=attempt_budget(f.scope,list(project_budget_attempts(f.events(),f.prepared_id).values()))
        result=resolve_technical_attempt(f.store,f.program,f.prepared_id,self.attempt_id,
            evidence=self.technical_evidence(),**f.kwargs('technical'))
        self.assertEqual(result['payload']['status'],'RETRY_ALLOWED')
        self.assertFalse(result['payload']['old_output_accepted'])
        self.assertNotIn('human_message_ref',result['payload'])
        self.assertEqual(len(f.events('BUILD_AUTHORIZATION_APPROVED')),1)
        self.assertEqual(before,attempt_budget(f.scope,list(project_budget_attempts(f.events(),f.prepared_id).values())))

    def test_technical_replay_is_read_only(self):
        self.prepare_technical_block();f=self.f;evidence=self.technical_evidence();kwargs=f.kwargs('technical')
        result=resolve_technical_attempt(f.store,f.program,f.prepared_id,self.attempt_id,evidence=evidence,**kwargs)
        count=len(f.events())
        self.assertEqual(resolve_technical_attempt(f.store,f.program,f.prepared_id,self.attempt_id,evidence=evidence,**kwargs),result)
        self.assertEqual(len(f.events()),count)

    def test_technical_disposition_rejects_missing_observation(self):
        self.prepare_technical_block();f=self.f;evidence=self.technical_evidence()
        (Path(f.events('BUILD_COMMAND_OBSERVED')[0]['payload']['observation_root'])/'result.json').unlink()
        with self.assertRaisesRegex(RequestValidationError,'complete durable'):
            resolve_technical_attempt(f.store,f.program,f.prepared_id,self.attempt_id,evidence=evidence,**f.kwargs('technical'))

    def test_technical_disposition_does_not_override_real_contract_gap(self):
        self.prepare_technical_block();f=self.f;evidence=self.technical_evidence()
        evidence['classification']='GENUINE_USER_DECISION_MISSING'
        with self.assertRaisesRegex(RequestValidationError,'genuine missing user decision'):
            resolve_technical_attempt(f.store,f.program,f.prepared_id,self.attempt_id,evidence=evidence,**f.kwargs('technical'))

    def test_verifier_block_requires_correction_not_producer_replay(self):
        self.prepare_failure();f=self.f;evidence=self.technical_evidence()
        with self.assertRaisesRegex(RequestValidationError,'explicit checker correction'):
            resolve_technical_attempt(f.store,f.program,f.prepared_id,self.attempt_id,evidence=evidence,**f.kwargs('technical'))


class TechnicalContinuationTests(unittest.TestCase):
    def test_host_disposition_continues_one_production_without_reapproval_or_refund(self):
        from harness_foundry_factory.coding_events import CodingEventObserver
        from harness_foundry_factory.coding_process import classify_coding_capture
        from harness_foundry_factory.process_observation import CommandObservation
        h = CheckerCorrectionTests()
        h.setUp()
        self.addCleanup(h.doCleanups)
        h.prepare_technical_block()
        f = h.f
        original_attempt = h.attempt_id
        original_approval = f.events('BUILD_AUTHORIZATION_APPROVED')
        original_commands = f.events('BUILD_COMMAND_OBSERVED')
        receipt = resolve_technical_attempt(f.store, f.program, f.prepared_id, original_attempt,
            evidence=h.technical_evidence(), **f.kwargs('host-technical-continuation'))
        self.assertEqual(receipt['payload']['status'], 'RETRY_ALLOWED')
        calls = []

        def runner(invocation, before):
            if invocation['executor'] == 'LOCAL':
                result = h.runner(invocation, before)
                return classify_verification_result(result) if invocation['phase'] == 'VERIFICATION' else result
            before()
            calls.append(invocation['command_id'])
            (f.workspace / 'src/reader.py').write_text(support.GOOD_READER)
            rows = [{'type': 'thread.started', 'thread_id': 'TEST-ONLY-CONTINUATION'},
                    {'type': 'turn.started'},
                    {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'TEST ONLY completed'}},
                    {'type': 'turn.completed', 'usage': {'input_tokens': 2, 'output_tokens': 3}}]
            data = b''.join((json.dumps(row) + '\n').encode() for row in rows)
            configuration = {'model': 'TEST-NOT-A-MODEL', 'model_policy': 'FIXED',
                'model_reasoning_effort': None, 'model_service': {'provider': 'openai', 'config': {}},
                'model_defaults_source': None}
            capture = {'exit_code': 0, 'timed_out': False, 'stdout': '', 'stderr': '',
                'stream_bytes': {'stdout': len(data), 'stderr': 0}, 'model_configuration': configuration}
            observer = CodingEventObserver()
            observer.feed(data)
            result = classify_coding_capture(capture, observer)
            journal = CommandObservation(invocation['observation_root'], invocation['command_id'], 'CODEX')
            try:
                journal.model_configuration(configuration)
                journal.write('stdout', data)
                journal.write('stderr', b'')
                journal.captured(capture)
                journal.finished(result)
            finally:
                journal.close()
            return result

        f.runner = runner
        result = f.controller().advance(f.prepared_id, advance_mode='ONE_ATTEMPT')
        self.assertEqual(result.get('attempt_status'), 'ACCEPTED', result)
        self.assertNotEqual(result['attempt_id'], original_attempt)
        self.assertEqual(len(calls), 1)
        self.assertEqual(f.events('BUILD_AUTHORIZATION_APPROVED'), original_approval)
        self.assertEqual(f.events('BUILD_COMMAND_OBSERVED')[:len(original_commands)], original_commands)
        history = project_budget_attempts(f.events(), f.prepared_id)
        budget = attempt_budget(f.scope, list(history.values()))
        self.assertEqual(budget['attempts_consumed'], 2)
        self.assertEqual(budget['attempts_remaining'], f.scope['max_attempts'] - 2)
        self.assertEqual(history[original_attempt]['status'], 'RETRY_ALLOWED')
        self.assertEqual(history[original_attempt]['original_status'], 'BLOCKED')
        accepted = project_execution_state(f.events(), f.prepared_id)[1]
        self.assertEqual(accepted['IMPLEMENT-READER']['attempt_id'], result['attempt_id'])
        self.assertEqual([row['phase'] for row in h.runner.invocations], ['VERIFICATION', 'VERIFICATION'])


class TechnicalStopTests(unittest.TestCase):
    def test_host_disposition_cannot_override_explicit_stop_or_required_decision(self):
        from unittest.mock import patch
        from harness_foundry_factory.coding_process import classify_coding_capture
        for marker in ('user_stop', 'human_decision_required', 'cancellation_reason'):
            with self.subTest(marker=marker):
                h = CheckerCorrectionTests()
                h.setUp()
                try:
                    # The test receiver supplies the marker before the helper
                    # writes its first durable result and controller observation.
                    def classified_with_marker(capture, observer):
                        return {**classify_coding_capture(capture, observer), marker: 'TEST explicit stop'}
                    with patch('harness_foundry_factory.coding_process.classify_coding_capture',
                               side_effect=classified_with_marker):
                        h.prepare_technical_block()
                    f = h.f
                    self.assertEqual(f.events('BUILD_COMMAND_OBSERVED')[0]['payload']['result'][marker],
                                     'TEST explicit stop')
                    evidence = h.technical_evidence()
                    events = deepcopy(f.events())
                    budget = attempt_budget(f.scope, list(project_budget_attempts(events, f.prepared_id).values()))
                    with self.assertRaisesRegex(RequestValidationError, 'user stop or real decision'):
                        resolve_technical_attempt(f.store, f.program, f.prepared_id, h.attempt_id,
                            evidence=evidence, **f.kwargs('must-not-resolve-stop'))
                    self.assertEqual(f.events(), events)
                    self.assertEqual(attempt_budget(f.scope,
                        list(project_budget_attempts(f.events(), f.prepared_id).values())), budget)
                    self.assertFalse(f.events('BUILD_ATTEMPT_RESOLVED'))
                finally:
                    h.doCleanups()



if __name__=='__main__':unittest.main()
