"""Synthetic Reviewer calibration and real local controller checks; no model."""
from copy import deepcopy
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from harness_foundry_factory.rsi_review import (prepare_review,validate_report,digest,handoff_review,
    review_build_request,retrieve_review,REVIEWER_GUIDANCE)
from harness_foundry_factory.build_runtime import BuildController,revoke_build_authorization
from tests import test_build_runtime as runtime
from tests.build_review_fixture import reviewed_document

ROOT=Path(__file__).resolve().parents[1]


def report_fixture(request,status='SATISFIED',kind=None):
    refs=[{'file_id':'candidate','location':'L1'}]
    return {'schema_version':'RSI_REVIEW_REPORT_V1','request_sha256':digest(request),
        'review_id':request['review_id'],'candidate_version':request['candidate_version'],
        'conclusion':'CHANGES_REQUESTED' if status=='GAP' or kind=='DEFECT' else 'UNKNOWN' if status=='UNKNOWN' else 'ACCEPT',
        'coverage':[{'requirement_id':'R1','status':status,'reason':'Synthetic supplied semantic judgement',
                     'evidence_refs':refs if status!='UNKNOWN' else []}],
        'findings':[] if kind is None else [{'issue_key':'R1-result','requirement_id':'R1','kind':kind,
            'location':'candidate:L1','reason':'Synthetic supplied finding','evidence_refs':refs,
            'repair_request':'Repair only the stated missing behavior' if kind=='DEFECT' else ''}],
        'unresolved':[]}


class RSIReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'candidate.py').write_text('def total(xs): return sum(xs)\n')
        (self.root/'brief.md').write_text('Sum integers.\n')
        self.manifest={'review_id':'review-1','goal':'Check the public integer total behavior',
            'candidate_version':'v1','producer':{'program_id':'old-program','prepared_event_id':'old-prepared',
            'attempt_id':'old-attempt','workpack_id':'old-producer'},'requirements':[{'id':'R1','text':'Return exact total'}],
            'files':[{'id':'candidate','path':'candidate.py','role':'CANDIDATE'},
                     {'id':'brief','path':'brief.md','role':'PUBLIC_REQUIREMENT'}]}
        self.request=prepare_review(self.manifest,self.root)

    def test_public_packet_and_plan_are_preparation_not_approval(self):
        proposal=review_build_request(self.request,program_id='TEST-REVIEW')
        task=proposal['plan']['workpacks'][0]
        self.assertFalse(proposal['runtime_authorized'])
        self.assertEqual(task['executor'],'CODEX')
        self.assertEqual(task['artifacts'],[{'artifact_id':'REVIEW-REPORT','path':'outputs/review.json'}])
        self.assertEqual(proposal['scope_notes']['write_roots'],['outputs'])
        self.assertIn('Equivalent valid behavior',task['goal'])
        self.assertIn('requirements',self.request)
        self.assertIn('request_sha256',task['goal'])
        self.assertIn(digest(self.request),task['goal'])
        self.assertIn('repair_request',task['goal'])

    def test_explicit_public_inputs_do_not_copy_private_or_worker_defense(self):
        (self.root/'private.json').write_text('PRIVATE ORACLE')
        self.assertNotIn('PRIVATE ORACLE',json.dumps(self.request))
        self.manifest['files'].append({'id':'private','path':'private.json','role':'PRIVATE_EXPECTATION'})
        with self.assertRaisesRegex(ValueError,'private'):prepare_review(self.manifest,self.root)

    def test_material_change_and_path_escape_do_not_reuse_binding(self):
        self.manifest['files'][0]['sha256']=self.request['files'][0]['sha256']
        (self.root/'candidate.py').write_text('different')
        with self.assertRaisesRegex(ValueError,'changed'):prepare_review(self.manifest,self.root)
        self.manifest['files'][0]['path']='../elsewhere'
        with self.assertRaises(ValueError):prepare_review(self.manifest,self.root)

    def test_known_gap_stays_finding_and_report_contract_can_pass(self):
        report=report_fixture(self.request,'GAP','DEFECT')
        result=validate_report(self.request,report)
        self.assertEqual(result['reported_conclusion'],'CHANGES_REQUESTED')
        self.assertFalse(result['product_accepted'])
        self.assertFalse(result['automatic_repair_allowed'])
        self.assertFalse(result['semantic_truth_verified'])

    def test_legal_equivalent_and_wording_suggestion_not_rejected(self):
        report=report_fixture(self.request,kind='SUGGESTION')
        self.assertEqual(validate_report(self.request,report)['reported_conclusion'],'ACCEPT')

    def test_unknown_and_known_failure_are_both_preserved(self):
        report=report_fixture(self.request,'UNKNOWN','DEFECT')
        result=validate_report(self.request,report)
        self.assertTrue(result['unknowns_retained']);self.assertEqual(len(result['findings']),1)
        self.assertEqual(result['reported_conclusion'],'CHANGES_REQUESTED')

    def test_missing_requirement_bad_evidence_and_false_accept_are_rejected(self):
        valid=report_fixture(self.request,'GAP','DEFECT')
        variants=[]
        r=deepcopy(valid);r['coverage']=[];variants.append(r)
        r=deepcopy(valid);r['conclusion']='ACCEPT';variants.append(r)
        r=deepcopy(valid);r['coverage'][0]['evidence_refs'][0]['file_id']='private';variants.append(r)
        r=deepcopy(valid);r['request_sha256']='0'*64;variants.append(r)
        for report in variants:
            with self.subTest(report=report),self.assertRaises(ValueError):validate_report(self.request,report)

    def test_positive_opinion_cannot_override_objective_fail_or_error(self):
        report=report_fixture(self.request)
        self.assertEqual(handoff_review(self.request,report,objective_status='FAIL')['next_action'],'RETURN_OBJECTIVE_FAILURE')
        self.assertEqual(handoff_review(self.request,report,objective_status='ERROR')['next_action'],'RESOLVE_OBJECTIVE_GAP')

    def test_repeated_issue_key_does_not_become_new_issue_or_budget(self):
        report=report_fixture(self.request,'GAP','DEFECT')
        result=handoff_review(self.request,report,objective_status='PASS',previous_issue_keys=['R1-result'])
        self.assertEqual(result['new_issue_keys'],[])
        self.assertEqual(result['repeated_issue_keys'],['R1-result'])
        self.assertNotIn('attempts_consumed',result)

    def test_protected_checker_is_standalone_and_missing_inputs_are_not_business_failure(self):
        protected=self.root/'protected';protected.mkdir()
        checker=protected/'rsi_review.py'
        shutil.copyfile(ROOT/'src/harness_foundry_factory/rsi_review.py',checker)
        request=protected/'request.json';request.write_text(json.dumps(self.request))
        report=self.root/'report.json';report.write_text(json.dumps(report_fixture(self.request,'GAP','DEFECT')))
        env={**os.environ,'FOUNDRY_VERIFIER_ROOT':str(protected),'FOUNDRY_CASE_ID':'case','FOUNDRY_COMMAND_ID':'command'}
        cmd=[sys.executable,'-I','-B',str(checker),'--request',str(request),'--report',str(report)]
        good=subprocess.run(cmd,capture_output=True,text=True,env=env)
        self.assertEqual(good.returncode,0,good.stdout+good.stderr)
        self.assertEqual(json.loads(good.stdout)['case_id'],'case')
        bad=report_fixture(self.request);bad['coverage']=[];report.write_text(json.dumps(bad))
        invalid=subprocess.run(cmd,capture_output=True,text=True,env=env)
        self.assertEqual(json.loads(invalid.stdout)['failure_kind'],'ASSERTION')
        request.unlink()
        missing=subprocess.run(cmd,capture_output=True,text=True,env=env)
        self.assertNotIn('failure_kind',json.loads(missing.stdout))

    def test_review_report_handoff_uses_existing_host_snapshot_and_checker(self):
        from tests.test_capability_host_review import CapabilityHostReviewTests
        f=CapabilityHostReviewTests();f.setUp();self.addCleanup(f.doCleanups)
        report=report_fixture(self.request,'GAP','DEFECT')
        (f.evidence/'review.json').write_text(json.dumps(report))
        # The host supplies its own checked observation; the model's opinion is
        # evidence only, never silently promoted to a human or objective PASS.
        f.review['observations']=[{'id':'input-retention','result':'FAIL',
            'reason':'Synthetic independent host confirmation of the missing requirement',
            'evidence_refs':['observation.txt','review.json']}]
        f.write_json(f.review_path,f.review);f.capture()
        result,checked=f.run_check()
        self.assertEqual(result.returncode,1)
        self.assertEqual(checked['failure_kind'],'ASSERTION')
        self.assertEqual((f.snapshot/'evidence/review.json').read_bytes(),(f.evidence/'review.json').read_bytes())
        (f.outputs/'prototype/index.html').write_text('changed candidate')
        f.assert_error()


class RSIReviewControllerTests(unittest.TestCase):
    def setUp(self):
        helper=RSIReviewTests();helper.setUp();self.addCleanup(helper.doCleanups)
        self.request=helper.request
        self.f=runtime.BuildRuntimeTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        proposed=review_build_request(self.request,program_id=self.f.program)
        self.f.ir,self.f.plan=proposed['requirement_ir'],proposed['plan']
        (self.f.source/'brief.md').write_text(json.dumps(self.request))
        self.f.review=reviewed_document(self.f.source,path=self.f.source/'brief.md')
        shutil.copyfile(ROOT/'src/harness_foundry_factory/rsi_review.py',self.f.verifier/'rsi_review.py')
        (self.f.verifier/'request.json').write_text(json.dumps(self.request))
        self.f.scope.update(task_write_roots={'INDEPENDENT-REVIEW':['outputs']},model='TEST-NOT-A-MODEL',allow_model_service=True)
        self.calls=[];self.local=runtime.FixtureProcessRunner()
        def runner(invocation,before_dispatch):
            if invocation['executor']!='CODEX':return self.local(invocation,before_dispatch)
            before_dispatch();self.calls.append(deepcopy(invocation))
            self.assertEqual(invocation['write_roots'],[str(self.f.workspace/'outputs')])
            context=json.loads(invocation['prompt'].split('\n',1)[1])['task']
            self.assertTrue(context['authority_validated'])
            (self.f.workspace/'outputs/review.json').write_text(json.dumps(report_fixture(self.request,'GAP','DEFECT')))
            return {'status':'MODEL_TURN_COMPLETED','exit_code':0,'final_message':'Only summary, use report artifact',
                    'model_configuration':{'model':'TEST-NOT-A-MODEL'}}
        self.f.runner=runner

    def test_existing_controller_counts_review_and_reads_twice_without_replay(self):
        self.f.prepare();controller=self.f.controller()
        result=controller.advance(self.f.prepared_id,advance_mode='ONE_ATTEMPT')
        self.assertEqual(result['attempt_status'],'ACCEPTED',result)
        self.assertEqual(len(self.calls),1)
        attempt=self.f.events('BUILD_ATTEMPT_STARTED')[0]['payload']['attempt_id']
        before=deepcopy(self.f.events())
        receipts=[retrieve_review(self.f.store,self.f.program,self.f.prepared_id,attempt,self.request,
                    self.f.workspace/'outputs/review.json',objective_status='PASS') for _ in range(2)]
        self.assertEqual(receipts[0],receipts[1]);self.assertEqual(self.f.events(),before)
        request_file=self.f.root/'review-request.json';request_file.write_text(json.dumps(self.request))
        cmd=[sys.executable,'-B',str(ROOT/'tools/rsi_review.py'),'--output',str(self.f.root/'receipt.json'),
             'retrieve','--request',str(request_file),'--report',str(self.f.workspace/'outputs/review.json'),
             '--database',str(self.f.store.database_path),'--program-id',self.f.program,
             '--prepared-id',self.f.prepared_id,'--attempt-id',attempt,'--objective-status','PASS']
        cli=subprocess.run(cmd,capture_output=True,text=True)
        self.assertEqual(cli.returncode,0,cli.stderr);self.assertEqual(self.f.events(),before)
        self.assertEqual(receipts[0]['budget']['attempts_consumed'],1)
        self.assertEqual(receipts[0]['next_action'],'VERIFY_FINDINGS_WITH_ORIGINAL_PRODUCER')
        self.assertFalse(receipts[0]['product_accepted'])
        controller.advance(self.f.prepared_id,advance_mode='ONE_ATTEMPT')
        self.assertEqual(len(self.calls),1)
        revoke_build_authorization(self.f.store,self.f.program,self.f.prepared_id,**self.f.kwargs('revoke'))
        self.assertEqual(retrieve_review(self.f.store,self.f.program,self.f.prepared_id,attempt,self.request,
            self.f.workspace/'outputs/review.json',objective_status='FAIL')['new_model_calls'],0)
        historical=deepcopy(self.f.events())
        historical.append({'event_id':'synthetic-invalidation','event_type':'BUILD_ACCEPTANCE_INVALIDATED',
            'payload':{'prepared_event_id':self.f.prepared_id,'workpack_ids':['INDEPENDENT-REVIEW']}})
        class HistoricalStore:
            def list_events(_,program_id):return historical
        historical_result=retrieve_review(HistoricalStore(),self.f.program,self.f.prepared_id,attempt,self.request,
            self.f.workspace/'outputs/review.json',objective_status='PASS')
        self.assertEqual(historical_result['review_attempt_status'],'INVALIDATED')
        self.assertEqual(historical_result['next_action'],'INSPECT_INVALIDATED_REVIEW_HISTORY')
        self.assertEqual(historical_result['budget']['attempts_consumed'],1)
        (self.f.workspace/'outputs/review.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'differs'):retrieve_review(self.f.store,self.f.program,self.f.prepared_id,
            attempt,self.request,self.f.workspace/'outputs/review.json',objective_status='PASS')

    def test_accepted_recorded_reassessment_can_be_read_without_stream_replay(self):
        self.f.prepare();self.f.controller().advance(self.f.prepared_id,advance_mode='ONE_ATTEMPT')
        events=deepcopy(self.f.events())
        command=next(e['payload'] for e in events if e['event_type']=='BUILD_COMMAND_OBSERVED' and e['payload']['executor']=='CODEX')
        completed=deepcopy(command['result']);command['result']={'status':'MODEL_PROCESS_FAILED','reason':'synthetic old receiver'}
        correction={'event_id':'synthetic-recorded-reassessment','event_type':'BUILD_COMMAND_REASSESSED',
            'payload':{'policy':'SYNTHETIC_RECORDED_REASSESSMENT','attempt_id':command['attempt_id'],'prepared_event_id':self.f.prepared_id,
                       'command_id':command['command_id'],'original_result':deepcopy(command['result']),'result':completed}}
        # Simulated historical event sequence, never appended to production state.
        events.insert(-1,correction)
        class HistoricalStore:
            def list_events(_,program_id):return events
        def retrieve():return retrieve_review(HistoricalStore(),self.f.program,self.f.prepared_id,command['attempt_id'],self.request,
            self.f.workspace/'outputs/review.json',objective_status='PASS')
        result=retrieve();self.assertEqual(result['review_receipt']['original_observation_status'],'MODEL_PROCESS_FAILED')
        self.assertEqual(result['review_receipt']['effective_observation_status'],'MODEL_TURN_COMPLETED')
        self.assertEqual(result['budget']['attempts_consumed'],1);self.assertEqual(len(self.calls),1)
        self.assertEqual(retrieve(),result)
        correction['payload']['command_id']='different'
        with self.assertRaisesRegex(ValueError,'binding differs'):retrieve()

    def corrected_review(self):
        from harness_foundry_factory.build_runtime import prepare_build_authorization
        from harness_foundry_factory.build_correction import derive_checker_authorization
        from tests.test_build_resources import DurableResourceFixtureRunner
        from harness_foundry_factory.process_observation import CommandObservation
        from harness_foundry_factory.build_runtime import classify_verification_result
        f=self.f;model_fixture=f.runner;local=DurableResourceFixtureRunner()
        def durable(invocation,before):
            if invocation['executor']=='LOCAL':return classify_verification_result(local(invocation,before))
            result=model_fixture(invocation,before)
            configuration={'model':'TEST-NOT-A-MODEL','model_policy':'FIXED',
                           'model_reasoning_effort':f.scope.get('model_reasoning_effort'),
                           'model_service':{'provider':'openai','config':{}}}
            journal=CommandObservation(invocation['observation_root'],invocation['command_id'],'CODEX')
            try:
                journal.model_configuration(configuration)
                capture={'exit_code':0,'timed_out':False,'stdout':'','stderr':'',
                         'stream_bytes':{'stdout':0,'stderr':0},'model_configuration':configuration}
                journal.captured(capture)
                result.update(capture=capture,model_configuration=configuration)
                journal.finished(result)
            finally:journal.close()
            return result
        f.runner=durable
        (f.verifier/'rsi_review.py').write_text("raise RuntimeError('TEST checker adapter failure')\n")
        f.prepare();original=f.prepared_id
        failed=f.controller().advance(original,advance_mode='ONE_ATTEMPT')
        self.assertNotEqual(failed['attempt_status'],'ACCEPTED')
        production=failed['attempt_id'];previous=original
        rounds=[]
        for n in (1,2):
            root=f.root/('corrected-review-'+str(n));root.mkdir()
            (root/'rsi_review.py').write_text((ROOT/'src/harness_foundry_factory/rsi_review.py').read_text()+'\n# adapter revision '+str(n)+'\n')
            (root/'request.json').write_text(json.dumps(self.request))
            prepared=prepare_build_authorization(f.store,f.program,f.proposal_id,f.source_id,
                {**f.scope,'verification_root':str(root)},rebind_from=previous,**f.kwargs('review-prepare-'+str(n)))
            new=prepared['event_id'];events=f.events()
            old=next(e['payload'] for e in events if e['event_id']==previous)
            current=prepared['payload']
            complete={}
            if n==1:
                finished=next(e['payload'] for e in events if e['event_type']=='BUILD_ATTEMPT_FINISHED')
                complete[production]={'artifacts':finished['artifacts'],'effects':{
                    'status':'EFFECTS_RECONCILED','command_ids':[e['payload']['command_id'] for e in events if e['event_type']=='BUILD_COMMAND_OBSERVED'],
                    'detail':'TEST fixture report and command completion inspected','evidence_refs':['TEST report and command observation']}}
            evidence={'review':{'policy':'SAME_SCOPE_CHECKER_CORRECTION_V1','actor':{'type':'TRUSTED_CODEX_HOST','chat_thread_id':'TEST','turn_id':'TEST-CORRECTION'},
                        'reason':'TEST adapter-only correction, same report assertion','evidence_refs':['TEST checker diff'],'decision':'EQUIVALENT_CHECKER_CORRECTION'},
                'source_prepared_event_id':previous,'old_verifier_files':old['verifier_files'],'new_verifier_files':current['verifier_files'],
                'preserved_case_ids':['REVIEW-REPORT-CONTRACT'],'changed_files':{
                    name:{'role':'CHECKER_ADAPTER','reason':'TEST corrected adapter'} for name in old['verifier_files'].keys()|current['verifier_files'].keys()
                    if old['verifier_files'].get(name)!=current['verifier_files'].get(name)},'completed_attempts':complete}
            derive_checker_authorization(f.store,f.program,new,evidence=evidence,**f.kwargs('review-derive-'+str(n)))
            result=f.controller().advance(new,advance_mode='ONE_ATTEMPT')
            self.assertEqual(result['attempt_status'],'ACCEPTED',result)
            rounds.append((new,result['attempt_id']));previous=new
        return production,rounds

    def test_corrected_checker_report_reads_original_model_and_current_acceptance(self):
        production,rounds=self.corrected_review();f=self.f
        prepared,attempt=rounds[-1];before=deepcopy(f.events())
        receipts=[retrieve_review(f.store,f.program,prepared,attempt,self.request,f.workspace/'outputs/review.json',objective_status='FAIL') for _ in range(2)]
        self.assertEqual(receipts[0],receipts[1]);self.assertEqual(f.events(),before);self.assertEqual(len(self.calls),1)
        r=receipts[0];self.assertEqual(r['review_receipt']['attempt_id'],attempt)
        self.assertEqual(r['review_receipt']['production_attempt_id'],production)
        self.assertEqual(r['review_receipt']['production_prepared_event_id'],f.prepared_id)
        self.assertEqual(len(r['review_receipt']['reverification_chain']),2)
        self.assertEqual(r['budget']['attempts_consumed'],1);self.assertEqual(r['budget']['checker_reverification_rounds'],2)
        self.assertEqual(r['next_action'],'RETURN_OBJECTIVE_FAILURE')
        self.assertFalse(r['product_accepted']);self.assertEqual(r['new_model_calls'],0)
        revoke_build_authorization(f.store,f.program,prepared,**f.kwargs('revoke-corrected'))
        self.assertEqual(retrieve_review(f.store,f.program,prepared,attempt,self.request,f.workspace/'outputs/review.json',objective_status='FAIL')['new_model_calls'],0)

    def test_corrected_checker_retrieval_rejects_broken_production_links(self):
        production,rounds=self.corrected_review();f=self.f;prepared,attempt=rounds[-1]
        original=deepcopy(f.events())
        variants=[('production_attempt_id','unrelated'),('reverification_of_attempt_id',attempt),('reverification_of_attempt_id','missing'),('workpack_id','other')]
        for key,value in variants:
            history=deepcopy(original)
            for event in history:
                if event['payload'].get('attempt_id')==attempt and event['event_type'] in {'BUILD_ATTEMPT_STARTED','BUILD_ATTEMPT_FINISHED'}:
                    event['payload'][key]=value
            class HistoricalStore:
                def list_events(_,program):return history
            with self.subTest(key=key),self.assertRaises(ValueError):
                retrieve_review(HistoricalStore(),f.program,prepared,attempt,self.request,f.workspace/'outputs/review.json',objective_status='FAIL')
        self.assertEqual(f.events(),original);self.assertEqual(len(self.calls),1)

    def test_unapproved_scope_does_not_dispatch_or_invent_receipt(self):
        self.f.prepare(approve=False)
        self.assertEqual(self.f.controller().advance(self.f.prepared_id)['status'],'BUILD_STOPPED')
        self.assertEqual(self.calls,[])
        with self.assertRaises(ValueError):retrieve_review(self.f.store,self.f.program,self.f.prepared_id,
            'missing',self.request,self.f.workspace/'outputs/review.json',objective_status='PASS')


if __name__=='__main__':unittest.main()
