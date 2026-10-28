"""Feature planning and invocation contracts, without models or external services."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'examples/capability-adapters'
def module(name):
    spec=importlib.util.spec_from_file_location('feature_test_'+name, BASE/(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
I=module('inventory');P=module('prepare');C=module('consume')

class FeatureInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.pkg=self.root/'kit';self.pkg.mkdir()
        self.desc={'name':'kit','version':'2','descriptor_version':2,'usage':'both',
            'inputs':['text'],'outputs':['JSON'],'materials':['guide.md','target.md'],
            'runtime_files':['shared.py'], 'tools':[
                {'id':'offline','path':'shared.py','interpreter':'python'},
                {'id':'remote','path':'shared.py','interpreter':'unavailable-sdk'}],
            'environment':[{'id':'python','kind':'executable'},{'id':'unavailable-sdk','kind':'executable'}],
            'delivery':{'instruction_snippet':'target.md'},'features':[
                {'id':'local','summary':'Offline processing','kind':'tool','files':['shared.py'],
                 'entry':{'tool':'offline'},'environment_refs':[], 'default_form':'AS_IS'},
                {'id':'online','summary':'Remote processing','kind':'tool','files':['shared.py'],
                 'entry':{'tool':'remote'},'environment_refs':['unavailable-sdk'],'default_form':'BRIDGED'}]}
        (self.pkg/'shared.py').write_text('import json,sys\nprint(json.dumps(sys.argv[1:]))\n')
        for n in ['guide.md','target.md']:(self.pkg/n).write_text('# Public instructions\n')
        self.write()
    def write(self):
        (self.pkg/'capability.json').write_text(json.dumps(self.desc))
    def inventory(self, config=None, selection=None):
        return I.select(self.desc, selection or {}, ({'integration_mode':'ALL'} if config is None else config), {}, 'd'*64)
    def config(self):
        source=self.root/'sources';source.mkdir(exist_ok=True);(source/'brief.md').write_text('Use offline computation.\n')
        return {'project_root':str(self.root),'selections':[{'directory':str(self.pkg),'version':'2','workpack_ids':['BUILD']}],
                'source_root':str(source),'environment_bindings':{'python':{'path':sys.executable}},
                'requirement_links':[{'capability':'kit','feature':'local','source_id':'BRIEF','source_locator':'L1'}],
                'base_materials':{'request':{'requirement_ir':{'sources':[{'source_id':'BRIEF','path_or_uri':'brief.md'}]},
                                'plan':{'workpacks':[{'workpack_id':'BUILD','inputs':[]}]}},
                'source_manifest':[{'source_id':'BRIEF','path':'brief.md'}]}}
    def test_all_deduplicates_shared_files_but_requires_both_tools(self):
        r=self.inventory();self.assertEqual(r['active_tools'],['offline','remote']);self.assertEqual(r['delivery_files'].count('shared.py'),1)
    def test_default_on_demand_with_no_evidence_selects_nothing(self):
        r=self.inventory(config={});self.assertEqual(r['active_tools'],[])
        self.assertTrue(all(f['status']=='NOT_SELECTED_ON_DEMAND' for f in r['features']))
    def test_shared_file_does_not_select_other_tool_or_missing_sdk(self):
        m,_=P.build_materials(self.config(),self.root/'prepared')
        self.assertEqual(m['preparation']['readiness'],'READY')
        self.assertEqual(set(m['tool_bindings']),{'offline'})
        self.assertEqual(set(m['preparation']['environment']['bindings']),{'python'})
        self.assertIn('shared.py',{r['path'] for r in m['preparation']['selections'][0]['files']})
        self.assertEqual(C.prepare_call(m,'offline',['hello'])['argv'][0],sys.executable)
        with self.assertRaises(ValueError):C.prepare_call(m,'remote')
    def test_selected_missing_interpreter_stays_incomplete(self):
        c=self.config();c['environment_bindings']={};m,_=P.build_materials(c,self.root/'prepared')
        self.assertEqual(m['preparation']['readiness'],'INCOMPLETE')
    def test_full_source_identity_survives_subset(self):
        m,_=P.build_materials(self.config(),self.root/'prepared')
        self.desc['features'][1]['summary']='Changed unselected source';self.write()
        self.assertEqual(P.check_selection(m)['status'],'CHANGED')
    def test_scope_mutation_rejected(self):
        m,_=P.build_materials(self.config(),self.root/'prepared')
        m['preparation']['selections'][0]['feature_scope']['active_tools'].append('remote')
        with self.assertRaises(ValueError):C.prepare_call(m,'offline')
    def test_source_locator_must_resolve(self):
        c=self.config();c['requirement_links'][0]['source_locator']='L2'
        with self.assertRaisesRegex(ValueError,'locator'):P.build_materials(c,self.root/'prepared')
    def test_dependency_closure(self):
        self.desc['features'][0]['requires']=['online'];self.write()
        c=self.config();m,_=P.build_materials(c,self.root/'prepared')
        self.assertEqual(m['preparation']['readiness'],'INCOMPLETE')
        self.assertIn('remote',m['preparation']['selections'][0]['feature_scope']['active_tools'])
    def test_environment_fallback_is_legacy_compatible(self):
        del self.desc['features'][0]['environment_refs'];self.write()
        m,_=P.build_materials(self.config(),self.root/'prepared')
        self.assertEqual(m['preparation']['readiness'],'INCOMPLETE')
    def test_unowned_runtime_rejected(self):
        self.desc['runtime_files'].append('orphan.py')
        with self.assertRaisesRegex(ValueError,'FEATURE_FILE_UNOWNED'):self.inventory()
    def test_private_file_cannot_be_feature(self):
        self.desc['verification_files']=['secret.json'];self.desc['features'][0]['files'].append('secret.json')
        with self.assertRaisesRegex(ValueError,'private'):self.inventory()
    def test_tags_do_not_create_approval(self):
        self.desc['features'][1]['conflict_tags']=['NETWORK_ACCESS','TELEMETRY','AUTO_UPDATE']
        self.assertEqual(self.inventory()['decision_requests'],[])
    def test_legacy_without_new_fields_has_no_projection(self):
        del self.desc['descriptor_version'];del self.desc['features'];self.desc['tools']=self.desc['tools'][:1];self.desc['environment']=self.desc['environment'][:1];self.write()
        c=self.config();c.pop('requirement_links');m,_=P.build_materials(c,self.root/'prepared')
        self.assertNotIn('feature_scope',m['preparation']['selections'][0])

    def test_decided_exclusion_does_not_pull_unused_dependency(self):
        self.desc['features'][0]['requires']=['online']
        condition={'capability':'kit','feature':'local','unresolved':True,'category':'DELIVERY_FORM',
                   'question':'Use a host alternative?', 'evidence':['fixture requirement'], 'options':[{'id':'POST_DELIVERY'}]}
        config={'capability_conditions':[condition], 'requirement_links':[{'capability':'kit','feature':'local','source_id':'R','source_locator':'L1'}]}
        first=I.select(self.desc,{},config,{'R':b'Need local result'},'source')
        request=first['decision_requests'][0]
        config['decision_records']=[{'decision_id':'fixture-only','request_ids':[request['request_id']],
          'choice':'POST_DELIVERY','context_identity':request['context_identity'],'decided_by':{'role':'USER'},
          'message_ref':{'chat_thread_id':'test-fixture','turn_id':'test-fixture'}}]
        second=I.select(self.desc,{},config,{'R':b'Need local result'},'source')
        self.assertEqual(second['active_tools'],[])
        self.assertEqual(second['features'][1]['status'],'NOT_SELECTED_ON_DEMAND')
        self.assertEqual(second['decision_requests'][0],request)
        self.assertEqual(second['features'][0]['final_form'],'POST_DELIVERY')
    def test_build_usage_cannot_be_promoted_by_pin(self):
        self.desc['features'][0]['usage']='build'
        with self.assertRaisesRegex(ValueError,'build-only'):
            self.inventory(selection={'feature_pins':[{'feature':'local','form':'AS_IS','decision_id':'x'}]})
    def test_runtime_cannot_hide_required_dependency_as_build_only(self):
        self.desc['features'][0]['requires']=['online'];self.desc['features'][1]['usage']='build'
        r=self.inventory();self.assertTrue(any(d['code']=='DEPENDENCY_DELIVERY_CONFLICT' for d in r['diagnostics']))

    def test_dependency_checks_final_form_and_keeps_legal_build_use(self):
        self.desc['features'][0]['requires']=['online']
        self.desc['features'][1]['files'].append('dependency.json')
        self.desc['materials'].append('dependency.json')
        for parent_form in ('AS_IS', 'BRIDGED', 'BUILD_ONLY'):
            for dependency_form in ('AS_IS', 'BRIDGED', 'BUILD_ONLY'):
                with self.subTest(parent=parent_form, dependency=dependency_form):
                    self.desc['features'][0]['default_form']=parent_form
                    selection={'feature_pins':[{'feature':'online','form':dependency_form,'decision_id':'fixture'}]}
                    config={'integration_mode':'ALL'}
                    request=self.inventory(config,selection)['decision_requests'][0]
                    config['decision_records']=[{'decision_id':'fixture','request_ids':[request['request_id']],
                        'choice':dependency_form,'context_identity':request['context_identity'],
                        'decided_by':{'role':'USER'},'message_ref':{'chat_thread_id':'fixture','turn_id':'fixture'}}]
                    r=self.inventory(config,selection)
                    conflicts=[d for d in r['diagnostics'] if d['code']=='DEPENDENCY_DELIVERY_CONFLICT']
                    self.assertEqual(bool(conflicts),parent_form!='BUILD_ONLY' and dependency_form=='BUILD_ONLY')
                    self.assertEqual('dependency.json' in r['delivery_files'],dependency_form!='BUILD_ONLY')
                    self.assertIn('remote',r['active_tools'])

    def test_circular_dependencies_finish_with_one_entry_each(self):
        self.desc['features'][0]['requires']=['online'];self.desc['features'][1]['requires']=['local']
        r=self.inventory();self.assertEqual(len(r['features']),2);self.assertEqual(len(r['active_tools']),2)
    def test_invalid_relative_values_are_diagnostic(self):
        for value in (None,42,'../secret','/tmp/file'):
            with self.subTest(value=value), self.assertRaises(ValueError):I.relative(value)

    def test_selected_external_binary_carries_doctor_without_other_owner_operations(self):
        self.desc['tools'].append({'id':'doctor','path':'doctor.py','interpreter':'python'})
        (self.pkg/'doctor.py').write_text('print("diagnostic")\n')
        self.desc['features'][1]['files'].append('doctor.py')
        self.desc['features'][1]['tool_refs']=['doctor']
        self.desc['features'][0]['conflict_tags']=['EXTERNAL_BINARY']
        self.desc['delivery']['doctor']={'tool':'doctor','args':['--check']}
        self.write();m,_=P.build_materials(self.config(),self.root/'prep')
        scope=m['preparation']['selections'][0]['feature_scope']
        self.assertEqual(m['preparation']['readiness'],'READY')
        self.assertEqual(scope['active_tools'],['doctor','offline'])
        self.assertIn('doctor.py',scope['delivery_files'])
        self.assertEqual(scope['features'][1]['status'],'NOT_SELECTED_ON_DEMAND')
        d=module('stack_handoff').public_delivery(m,self.root/'target')
        self.assertEqual({t['id'] for t in d['selections'][0]['tools']},{'doctor','offline'})

    def test_build_only_pin_never_offers_runtime_forms(self):
        self.desc['features'][0]['usage']='build'
        r=self.inventory(selection={'feature_pins':[{'feature':'local','form':'BUILD_ONLY','decision_id':'pending'}]})
        self.assertEqual(r['decision_requests'][0]['options'],[{'id':'BUILD_ONLY'}])

    def test_feature_upgrade_names_only_changed_selection_and_keeps_old_materials(self):
        c=self.config();old=P.write_materials(c,self.root/'old');original=deepcopy(old)
        c['requirement_links']=[]
        new,_,transition=module('upgrade').build_upgrade(old,c,self.root/'new')
        self.assertEqual(old,original)
        self.assertEqual([row['id'] for row in transition['feature_changes']],['kit:local'])
        self.assertEqual(new['tool_bindings'],{})
        self.assertFalse(transition['budget_modified'])

class DecisionsTests(unittest.TestCase):
    def req(self, **change):
        return I.D.request({'capability':'kit','version':'2','feature':'a'},descriptor_sha256='original',mode='ALL',requirements=change.get('requirements',[]),dependencies=[],condition={'category':'DELIVERY_FORM','question':'Choose representation','evidence':['actual conflict'],'options':[{'id':'BRIDGED'}]})
    def record(self, req):
        return {'decision_id':'D1','request_ids':[req['request_id']],'choice':'BRIDGED',
                'decided_by':{'role':'USER'},'message_ref':{'chat_thread_id':'fixture','turn_id':'fixture'},
                'context_identity':req['context_identity'],'subject':req['subject']}
    def test_recording_does_not_change_request_identity(self):
        req=self.req();record=self.record(req);self.assertEqual(I.D.resolve(self.req(),[record]),(record,None))
        record['recorded_at']='later';self.assertEqual(I.D.resolve(self.req(),[record])[1],None)
    def test_unrelated_record_does_not_invalidate(self):
        req=self.req();r=self.record(req);self.assertEqual(I.D.resolve(req,[{'decision_id':'other'},r])[1],None)
    def test_changed_requirement_stales_old_decision(self):
        self.assertEqual(I.D.resolve(self.req(requirements=['new']),[self.record(self.req())])[1],'DECISION_STALE')
    def test_missing_human_message_never_resolves(self):
        req=self.req();r=self.record(req);r.pop('message_ref');self.assertEqual(I.D.resolve(req,[r])[1],'DECISION_REQUIRED')
    def test_multiple_requests_bind_each_context(self):
        a=self.req();b=self.req(requirements=['second']);r=self.record(a);r['request_ids'].append(b['request_id'])
        r['context_identities']={a['request_id']:a['context_identity'],b['request_id']:b['context_identity']}
        self.assertIsNone(I.D.resolve(a,[r])[1]);self.assertIsNone(I.D.resolve(b,[r])[1])

if __name__=='__main__':unittest.main()
