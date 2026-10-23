"""Evidence association tests, including real local RED/GREEN collection; no model."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from harness_foundry_factory.rsi_cases import import_case
from harness_foundry_factory.rsi_tdd import associate_tdd
from harness_foundry_factory.test_execution import run_tests

ROOT=Path(__file__).resolve().parents[1]
TEST='test_total.Total.test_total'

class RSITddTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.manifest={'case_id':'arithmetic','goal':'Exact integer total','requirements':['Sum all integers'],'sources':[]}
        for name,status in [('red','CHECKS_FAILED'),('green','CHECKS_PASS')]:
            result={'status':status,'tests_run':1,'failures':[{'test':TEST,'traceback':'AssertionError: wrong total'}] if name=='red' else [],
                'errors':[],'test_log':f'test_total ({TEST}) ... '+('FAIL' if name=='red' else 'ok')+'\n'}
            (self.root/(name+'.json')).write_text(json.dumps(result))
            self.manifest['sources'].append({'source_id':name,'kind':'FOUNDRY_REPORT','path':name+'.json','context':{
                'implementation_version':name,'test_version':'tests-v1','platform':'local','environment':'venv1','phase':'DEVELOPMENT'}})
        self.case=import_case(self.manifest,self.root)
        def run(name,start,end):
            return {'run_id':name,'command_id':'cmd-'+name,'ref':name+'#/','behavior_id':'sum', 'test_id':TEST,
                'assertion_id':'exact-total','input_id':'integers','platform':'local','environment':'venv1',
                'argv':['python','-m','unittest','test_total'],'implementation_version':name,'test_version':'tests-v1',
                'started_at':f'2026-10-23T00:00:{start:02d}+00:00','finished_at':f'2026-10-23T00:00:{end:02d}+00:00'}
        self.cycle={'id':'sum-cycle','behavior':'integer total','requirement':'Sum all integers','applicability':'APPLICABLE',
            'red':run('red',1,2),'green':run('green',4,5),'mode':'TEST_FIRST','test_defined_at':'2026-10-23T00:00:00Z',
            'red_assessment':{'relation':'TARGET_ASSERTION','reason':'Known total differs','evidence_refs':['red#/']},
            'change':{'before_version':'red','after_version':'green','summary':'Return sum rather than first item',
                      'started_at':'2026-10-23T00:00:03Z'},'final_version':'green'}
        self.association={'case_id':'arithmetic','cycles':[self.cycle]}

    def report(self):return associate_tdd(self.case,self.association)
    def row(self):return self.report()['cycles'][0]

    def test_comparable_pair_keeps_all_originals_and_no_acceptance_or_budget(self):
        old=deepcopy(self.case);result=self.report();row=result['cycles'][0]
        self.assertEqual(row['classification'],'TEST_FIRST')
        self.assertEqual(row['evidence_pair_status'],'COMPARABLE_REPORTED_RED_GREEN')
        self.assertEqual(row['red']['original_result'],self.case['sources'][0]['document'])
        self.assertFalse(result['full_tdd_verified']);self.assertFalse(result['acceptance_verified'])
        self.assertFalse(result['commands_executed']);self.assertFalse(result['budget_modified'])
        self.assertIsNone(result['independent_test_total']);self.assertEqual(self.case,old)
        self.assertEqual(row['independent_acceptance']['status'],'NOT_RUN')

    def test_unrelated_environment_is_not_red_but_target_environment_can_be(self):
        self.cycle['red_assessment']['relation']='UNRELATED_ENVIRONMENT'
        self.assertEqual(self.row()['classification'],'BLOCKED')
        for relation in ['TARGET_INTERFACE_MISSING','TARGET_ENVIRONMENT_BEHAVIOR']:
            self.cycle['red_assessment']['relation']=relation
            self.assertEqual(self.row()['classification'],'TEST_FIRST')

    def test_legal_green_only_and_not_applicable(self):
        self.cycle.pop('red');self.assertEqual(self.row()['classification'],'GREEN_ONLY')
        self.association['cycles']=[{'id':'docs','applicability':'NOT_APPLICABLE','reason':'Only prose changes'}]
        self.assertEqual(self.row()['classification'],'NOT_APPLICABLE')

    def test_no_selected_test_no_red_pair(self):
        self.case['sources'][0]['document']['failures'][0]['test']='unrelated.test'
        self.assertEqual(self.row()['classification'],'BLOCKED')
        self.case['sources'][0]['document']['failures'][0]['test']=TEST
        self.case['sources'][1]['document']['test_log']='another ... ok'
        self.assertEqual(self.row()['classification'],'BLOCKED')

    def test_skip_discovery_failure_or_model_claim_cannot_be_green(self):
        original=deepcopy(self.case)
        for key in ['skipped','expected_failures','unexpected_successes','discovery_errors']:
            self.case=deepcopy(original);self.case['sources'][1]['document'][key]=[{'test':TEST,'reason':'selected skip'}] if key=='skipped' else [TEST]
            self.assertEqual(self.row()['classification'],'BLOCKED')
        self.case=deepcopy(original);self.case['observations'][1]['evidence_kind']='MODEL_STATEMENT'
        self.assertEqual(self.row()['classification'],'INSUFFICIENT_EVIDENCE')

    def test_selected_red_green_survives_unrelated_suite_failures_and_skips(self):
        original=deepcopy(self.case)
        for outcome in ('failures','errors','skipped','expected_failures','unexpected_successes'):
            self.case=deepcopy(original)
            for source in self.case['sources']:
                result=source['document'];result['status']='CHECKS_FAILED'
                result.setdefault(outcome,[]).append({'test':'other.Test.test_other','reason':'other outcome'} if outcome in ('failures','errors','skipped') else 'other.Test.test_other')
            row=self.row()
            self.assertEqual(row['classification'],'TEST_FIRST',(outcome,row))
            self.assertEqual(row['green']['reported_status'],'CHECKS_FAILED')
            self.assertEqual(row['green']['original_result'],self.case['sources'][1]['document'])
            self.assertFalse(row['full_tdd_verified'])

    def test_selected_skip_expected_failure_and_conflicting_success_are_not_green(self):
        original=deepcopy(self.case)
        for outcome in ('skipped','expected_failures','unexpected_successes','errors','failures'):
            self.case=deepcopy(original);result=self.case['sources'][1]['document'];result['status']='CHECKS_FAILED'
            result.setdefault(outcome,[]).append({'test':TEST,'reason':'selected outcome'} if outcome in ('skipped','errors','failures') else TEST)
            self.assertNotEqual(self.row()['evidence_pair_status'],'COMPARABLE_REPORTED_RED_GREEN',outcome)
        self.case=deepcopy(original);self.case['sources'][1]['document']['test_log']='other (other.Test.test_other) ... ok\n'
        self.assertEqual(self.row()['classification'],'BLOCKED')

    def test_different_platform_or_environment_kept_separate(self):
        for key in ['platform','environment']:
            self.cycle['green'][key]='different';self.case['sources'][1]['context'][key]='different'
            self.assertEqual(self.row()['classification'],'CONDITIONS_CHANGED')
            self.cycle['green'][key]='local' if key=='platform' else 'venv1'
            self.case['sources'][1]['context'][key]=self.cycle['green'][key]

    def test_test_change_needs_equivalence_and_weakening_is_not_paired(self):
        self.cycle['green']['test_version']='tests-v2';self.case['sources'][1]['context']['test_version']='tests-v2'
        self.assertEqual(self.row()['classification'],'CONDITIONS_CHANGED')
        self.cycle['test_equivalence']={'relation':'WEAKENED','reason':'Drop assertion','evidence_refs':['green#/']}
        self.assertEqual(self.row()['classification'],'CONDITIONS_CHANGED')
        self.cycle['test_equivalence'].update(relation='EQUIVALENT',reason='Same exact assertion after rename')
        self.assertEqual(self.row()['classification'],'TEST_FIRST')
        self.assertFalse(self.row()['full_tdd_verified'])

    def test_restored_report_rechecks_binding_without_discarding_old_case(self):
        old=deepcopy(self.case);self.case['sources'][0]['parse_status']='UNAVAILABLE'
        self.assertEqual(self.row()['classification'],'INSUFFICIENT_EVIDENCE')
        self.case=old;self.assertEqual(self.row()['classification'],'TEST_FIRST')
        self.case['sources'][0]['context']['implementation_version']='other'
        self.assertEqual(self.row()['classification'],'INSUFFICIENT_EVIDENCE')

    def test_developer_and_independent_evidence_are_not_mixed(self):
        self.case['sources'][0]['context']['phase']='INDEPENDENT'
        self.assertEqual(self.row()['classification'],'INSUFFICIENT_EVIDENCE')

    def test_repeated_pair_and_repeated_read_do_not_count_twice(self):
        another=deepcopy(self.cycle);another['id']='duplicate';self.association['cycles'].append(another)
        result=self.report();self.assertEqual(result,self.report())
        self.assertEqual(result['cycles'][1]['classification'],'DUPLICATE_PAIR')
        self.assertEqual(result['cycles'][1]['duplicate_of'],'sum-cycle')

    def test_posthoc_reproduction_not_original_test_first(self):
        self.cycle.update(mode='POST_HOC_REPRODUCTION',test_defined_at='2027-01-01T00:00:00Z')
        self.assertEqual(self.row()['classification'],'POST_HOC_REPRODUCTION')
        self.cycle['mode']='TEST_FIRST';self.assertEqual(self.row()['classification'],'INSUFFICIENT_EVIDENCE')
        self.cycle['mode']='DEFECT_REPRODUCTION';self.assertEqual(self.row()['classification'],'DEFECT_REPRODUCTION')

    def test_final_refactor_requires_final_version_check(self):
        self.cycle['final_version']='refactored';self.assertEqual(self.row()['classification'],'INSUFFICIENT_EVIDENCE')
        src=deepcopy(self.case['sources'][1]);src['source_id']='final';src['context']['implementation_version']='refactored'
        self.case['sources'].append(src)
        obs=deepcopy(self.case['observations'][1]);obs.update(ref='final#/',source_id='final');self.case['observations'].append(obs)
        run=deepcopy(self.cycle['green']);run.update(ref='final#/',run_id='final',command_id='cmd-final',implementation_version='refactored',
            started_at='2026-10-23T00:00:06Z',finished_at='2026-10-23T00:00:07Z')
        self.cycle['final_check']=run
        self.assertEqual(self.row()['classification'],'TEST_FIRST')

    def test_missing_cause_or_public_requirement_not_invented(self):
        self.cycle['red_assessment']['evidence_refs']=['missing']
        self.assertEqual(self.row()['classification'],'INSUFFICIENT_EVIDENCE')
        self.cycle['requirement']='not in public case'
        self.assertEqual(self.row()['classification'],'INSUFFICIENT_EVIDENCE')

    def test_real_mixed_suite_preserves_failed_suite_and_selected_success(self):
        project=self.root/'mixed-project';project.mkdir();work=self.root/'mixed-scratch';work.mkdir()
        (project/'test_total.py').write_text('import unittest\nfrom total import total\nclass Total(unittest.TestCase):\n def test_total(self): self.assertEqual(total([2,3]),5)\n @unittest.skip("unrelated optional tool")\n def test_optional(self): pass\n')
        self.cycle['test_defined_at']=datetime.now(timezone.utc).isoformat()
        impl=project/'total.py';impl.write_text('def total(xs): return xs[0]\n')
        for name,code in [('red',None),('green','def total(xs): return sum(xs)\n')]:
            if code:
                self.cycle['change']['started_at']=datetime.now(timezone.utc).isoformat();impl.write_text(code)
            start=datetime.now(timezone.utc).isoformat();result=run_tests(project,work,sys.executable)
            end=datetime.now(timezone.utc).isoformat()
            self.assertEqual(result['status'],'CHECKS_FAILED');self.assertEqual(len(result['skipped']),1)
            (self.root/(name+'.json')).write_text(json.dumps(result))
            self.cycle[name].update(started_at=start,finished_at=end)
        self.case=import_case(self.manifest,self.root)
        row=self.row();self.assertEqual(row['classification'],'TEST_FIRST',row)
        self.assertEqual(row['green']['status'],'PASS')
        self.assertEqual(row['green']['reported_status'],'CHECKS_FAILED')
        self.assertEqual(len(row['green']['original_result']['skipped']),1)
        self.assertFalse(row['full_tdd_verified'])

    def test_docstring_success_keeps_selected_and_suite_verdict(self):
        original=deepcopy(self.case)
        for newline in ('\n','\r\n'):
            for unrelated in (None,'failures','errors','skipped','expected_failures','unexpected_successes'):
                self.case=deepcopy(original)
                for index,source in enumerate(self.case['sources']):
                    result=source['document']
                    result['test_log']=f'test_total ({TEST})'+newline+'Check exact integer total ... '+('FAIL' if index==0 else 'ok')+newline
                    if unrelated:
                        result['status']='CHECKS_FAILED'
                        result.setdefault(unrelated,[]).append({'test':'other.Test.test_other','reason':'other outcome'} if unrelated in ('failures','errors','skipped') else 'other.Test.test_other')
                with self.subTest(newline=repr(newline),unrelated=unrelated):
                    row=self.row();self.assertEqual(row['classification'],'TEST_FIRST',row)
                    self.assertEqual(row['green']['status'],'PASS')
                    self.assertEqual(row['green']['reported_status'],'CHECKS_FAILED' if unrelated else 'CHECKS_PASS')
                    self.assertEqual(row['green']['original_result'],self.case['sources'][1]['document'])
                    self.assertFalse(row['full_tdd_verified'])

    def test_docstring_does_not_borrow_success_from_another_test(self):
        original=deepcopy(self.case)
        for outcome in ('FAIL','ERROR',"skipped 'not available'",'expected failure','unexpected success',''):
            self.case=deepcopy(original);result=self.case['sources'][1]['document']
            result['status']='CHECKS_FAILED'
            result['test_log']=f'test_total ({TEST})\nCheck exact integer total ... {outcome}\ntest_other (other.Test.test_other)\nOther behavior ... ok\n'
            with self.subTest(outcome=outcome):
                self.assertNotEqual(self.row()['green']['status'],'PASS')
        self.case=deepcopy(original);result=self.case['sources'][1]['document']
        result['test_log']=f'test_total ({TEST})\nCheck exact integer total ... ok\n'
        for key in ('failures','errors','skipped','expected_failures','unexpected_successes'):
            with self.subTest(conflict=key):
                result[key]=[{'test':TEST,'reason':'selected outcome'}] if key in ('failures','errors','skipped') else [TEST]
                self.assertNotEqual(self.row()['green']['status'],'PASS')
                result[key]=[]

    def test_real_docstring_red_green_with_clean_and_failed_regression(self):
        for mixed in (False,True):
            project=self.root/('documented-project-'+str(mixed));project.mkdir()
            scratch=self.root/('documented-scratch-'+str(mixed));scratch.mkdir()
            content='import unittest\nfrom total import total\nclass Total(unittest.TestCase):\n def test_total(self):\n  """Check exact integer total.\n\n  Additional documentation must not affect test identity.\n  """\n  self.assertEqual(total([2,3]),5)\n'
            if mixed:
                content+=' def test_other(self): self.fail("unrelated regression")\n @unittest.skip("optional dependency")\n def test_optional(self): pass\n'
            (project/'test_total.py').write_text(content)
            self.cycle['test_defined_at']=datetime.now(timezone.utc).isoformat()
            implementation=project/'total.py';implementation.write_text('def total(xs): return xs[0]\n')
            for phase in ('red','green'):
                if phase=='green':
                    self.cycle['change']['started_at']=datetime.now(timezone.utc).isoformat()
                    implementation.write_text('def total(xs): return sum(xs)\n')
                start=datetime.now(timezone.utc).isoformat();result=run_tests(project,scratch,sys.executable)
                end=datetime.now(timezone.utc).isoformat()
                self.assertIn(f'({TEST})\nCheck exact integer total. ... ',result['test_log'])
                self.assertEqual(result['status'],'CHECKS_FAILED' if mixed or phase=='red' else 'CHECKS_PASS')
                (self.root/(phase+'.json')).write_text(json.dumps(result))
                self.cycle[phase].update(started_at=start,finished_at=end)
            self.case=import_case(self.manifest,self.root)
            row=self.row();self.assertEqual(row['classification'],'TEST_FIRST',row)
            self.assertEqual(row['green']['status'],'PASS')
            self.assertEqual(row['green']['reported_status'],'CHECKS_FAILED' if mixed else 'CHECKS_PASS')
            self.assertEqual(len(row['green']['original_result'].get('failures',[])),1 if mixed else 0)
            self.assertFalse(row['full_tdd_verified']);self.assertFalse(self.report()['budget_modified'])

    def test_explicit_success_ids_are_authoritative_and_keep_conflicts(self):
        original=deepcopy(self.case)
        for ids in ([],['other.Test.test_other']):
            self.case=deepcopy(original);self.case['sources'][1]['document']['successes']=ids
            self.assertEqual(self.row()['green']['status'],'BLOCKED')
        self.case=deepcopy(original);result=self.case['sources'][1]['document']
        result.update(successes=[TEST],test_log='',status='CHECKS_FAILED',skipped=[{'test':'other.Test.test_other','reason':'optional'}])
        row=self.row();self.assertEqual(row['classification'],'TEST_FIRST')
        self.assertEqual(row['green']['reported_status'],'CHECKS_FAILED')
        self.assertEqual(row['green']['original_result'],result)
        for key in ('failures','errors','skipped','expected_failures','unexpected_successes'):
            self.case=deepcopy(original);result=self.case['sources'][1]['document'];result['successes']=[TEST]
            result[key]=[{'test':TEST}] if key in ('failures','errors','skipped') else [TEST]
            self.assertNotEqual(self.row()['green']['status'],'PASS',key)
        for invalid in (None,TEST,[None],['']):
            self.case=deepcopy(original);self.case['sources'][1]['document']['successes']=invalid
            self.assertEqual(self.row()['classification'],'INSUFFICIENT_EVIDENCE')

    def test_legacy_description_reference_neither_borrows_green_nor_erases_red(self):
        original=deepcopy(self.case)
        for description in (f'Related ({TEST})',f'test_total ({TEST})'):
            for newline in ('\n','\r\n'):
                other=f'test_other (other.Test.test_other){newline}{description} ... ok{newline}'
                self.case=deepcopy(original);self.case['sources'][1]['document']['test_log']=other
                self.assertEqual(self.row()['green']['status'],'BLOCKED')
                self.case=deepcopy(original)
                self.case['sources'][0]['document']['test_log']+=other
                self.case['sources'][1]['document']['test_log']=other+self.case['sources'][1]['document']['test_log']
                row=self.row();self.assertEqual(row['red']['status'],'FAIL')
                self.assertEqual(row['classification'],'TEST_FIRST')

    def test_legacy_failure_details_cannot_supply_success(self):
        for separator in ('='*70,'-'*70):
            self.case['sources'][1]['document']['test_log']='test_other (other.Test.test_other) ... FAIL\n\n'+separator+f'\ntest_total ({TEST}) ... ok\n'
            self.assertEqual(self.row()['green']['status'],'BLOCKED')

    def test_real_success_identity_and_legacy_reports_agree(self):
        project=self.root/'identity-project';project.mkdir();scratch=self.root/'identity-scratch';scratch.mkdir()
        tests=project/'test_total.py';implementation=project/'total.py'
        other=f'import unittest\nfrom total import total\nclass Total(unittest.TestCase):\n def test_other(self):\n  """test_total ({TEST})"""\n  pass\n'
        implementation.write_text('def total(xs): return xs[0]\n');tests.write_text(other)
        absent=run_tests(project,scratch,sys.executable)
        self.assertEqual(absent['successes'],['test_total.Total.test_other'])
        for legacy in (False,True):
            record=deepcopy(absent)
            if legacy:record.pop('successes')
            self.case['sources'][1]['document']=record
            self.assertEqual(self.row()['green']['status'],'BLOCKED')
        tests.write_text(other+' def test_total(self):\n  """Exact integer total."""\n  self.assertEqual(total([2,3]),5)\n')
        self.cycle['test_defined_at']=datetime.now(timezone.utc).isoformat()
        for phase in ('red','green'):
            if phase=='green':
                self.cycle['change']['started_at']=datetime.now(timezone.utc).isoformat()
                implementation.write_text('def total(xs): return sum(xs)\n')
            start=datetime.now(timezone.utc).isoformat();result=run_tests(project,scratch,sys.executable)
            end=datetime.now(timezone.utc).isoformat()
            self.assertEqual(TEST in result['successes'],phase=='green')
            (self.root/(phase+'.json')).write_text(json.dumps(result));self.cycle[phase].update(started_at=start,finished_at=end)
        self.case=import_case(self.manifest,self.root)
        self.assertEqual(self.row()['classification'],'TEST_FIRST')
        for source in self.case['sources']:source['document'].pop('successes')
        self.assertEqual(self.row()['classification'],'TEST_FIRST')
        self.assertFalse(self.report()['budget_modified']);self.assertFalse(self.report()['acceptance_verified'])

    def test_cli_writes_new_result_and_refuses_overwrite(self):
        case=self.root/'case.json';case.write_text(json.dumps(self.case))
        association=self.root/'association.json';association.write_text(json.dumps(self.association))
        output=self.root/'report.json'
        cmd=[sys.executable,'-B',str(ROOT/'tools/report_rsi_tdd.py'),'--case',str(case),'--association',str(association),'--output',str(output)]
        first=subprocess.run(cmd,capture_output=True,text=True)
        self.assertEqual(first.returncode,0,first.stderr);old=output.read_bytes()
        self.assertNotEqual(subprocess.run(cmd,capture_output=True).returncode,0)
        self.assertEqual(output.read_bytes(),old)

    def test_real_local_red_green_via_existing_collector(self):
        project=self.root/'project';project.mkdir();work=self.root/'scratch';work.mkdir()
        tests=project/'test_total.py'
        tests.write_text('import unittest\nfrom total import total\nclass Total(unittest.TestCase):\n def test_total(self): self.assertEqual(total([2,3]),5)\n')
        defined=datetime.now(timezone.utc).isoformat();test_sha=hashlib.sha256(tests.read_bytes()).hexdigest()
        impl=project/'total.py';impl.write_text('def total(xs): return xs[0]\n')
        red_start=datetime.now(timezone.utc).isoformat();red=run_tests(project,work,sys.executable)
        red_end=datetime.now(timezone.utc).isoformat()
        change=datetime.now(timezone.utc).isoformat();impl.write_text('def total(xs): return sum(xs)\n')
        green_start=datetime.now(timezone.utc).isoformat();green=run_tests(project,work,sys.executable)
        green_end=datetime.now(timezone.utc).isoformat()
        self.assertEqual(red['status'],'CHECKS_FAILED',red);self.assertEqual(green['status'],'CHECKS_PASS',green)
        self.assertTrue(red['protected_source_unchanged']);self.assertTrue(green['protected_source_unchanged'])
        for name,result in [('red',red),('green',green)]:
            (self.root/(name+'.json')).write_text(json.dumps(result))
        self.case=import_case(self.manifest,self.root)
        self.cycle['test_defined_at']=defined;self.cycle['change']['started_at']=change
        self.cycle['red'].update(started_at=red_start,finished_at=red_end)
        self.cycle['green'].update(started_at=green_start,finished_at=green_end)
        self.assertEqual(hashlib.sha256(tests.read_bytes()).hexdigest(),test_sha)
        row=self.row();self.assertEqual(row['classification'],'TEST_FIRST',row)
        self.assertFalse(row['full_tdd_verified'])

if __name__=='__main__':unittest.main()
