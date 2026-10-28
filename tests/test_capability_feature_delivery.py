"""Real isolated child calls for selected public delivery, never external services."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import zipfile
from tests import test_capability_feature_inventory as fi
module=fi.module
from tests import test_capability_external_delivery as ed
S=module('stack_handoff');I=module('inventory')

class BuiltinSubsetTests(unittest.TestCase):
    setUp=fi.FeatureInventoryTests.setUp
    write=fi.FeatureInventoryTests.write
    config=fi.FeatureInventoryTests.config
    def test_subset_relocation_and_no_original_install(self):
        m,_=module('prepare').build_materials(self.config(),self.root/'prep')
        output=self.root/'delivery';manifest=S.public_delivery(m,output)
        self.assertEqual(manifest['format_version'],2)
        self.assertEqual([t['id'] for t in manifest['selections'][0]['tools']],['offline'])
        self.assertFalse((output/'kit/2/guide.md').exists())
        self.assertTrue((output/'kit/2/shared.py').exists())
        shutil.rmtree(self.pkg)
        b=S.bind_delivery(output,{'python':{'path':sys.executable}},project_root=self.root)
        call=S.delivered_call(b,'offline',['新输入'])
        r=subprocess.run(call['argv'],capture_output=True,text=True,timeout=10)
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(json.loads(r.stdout),['新输入'])
        with self.assertRaises(ValueError):S.delivered_call(b,'remote')
        (output/'kit/2/shared.py').write_text('broken')
        with self.assertRaises(ValueError):S.delivered_call(b,'offline')

class ExternalSubsetTests(unittest.TestCase):
    setUp=ed.ExternalDeliveryTests.setUp
    bind=ed.ExternalDeliveryTests.bind
    def feature_setup(self):
        for name in ('sum','spare'):
            folder=self.source/'skills'/name;folder.mkdir()
            (folder/'SKILL.md').write_text('---\nname: '+name+'\n---\nUse '+name+'.\n')
        (self.source/'spare.py').write_text('raise RuntimeError("UNSELECTED")\n')
        (self.source/'guide.md').write_text('Read selected Skill.\n')
        self.definition['runtime_files']+=['spare.py','guide.md','skills/**/*']
        self.definition['operations']['spare']={'argv':['tool:missing','package:spare.py'],'tools':['missing']}
        self.adapter.write_text(json.dumps(self.definition))
        self.D=module('delivery')
        self.D.C.configure(self.instance,'instance','demo',self.source)
        mapping={'version':'1','provider':'demo','package_versions':['1'],
                 'adapter_sha256':self.D.N.sha(self.adapter.read_bytes()),'capability':{
                    'name':'demo','version':'1','usage':'both','descriptor_version':2,'inputs':['numbers'],'outputs':['sum'],
                    'materials':['guide.md','skills/sum/SKILL.md','skills/spare/SKILL.md'],
                    'tools':[],'runtime_files':['tool.py','spare.py'], 'environment':[],
                    'delivery':{'instruction_snippet':'guide.md'},'features':[
                        {'id':'sum','summary':'sum','kind':'tool','files':['tool.py','skills/sum/SKILL.md'],
                         'default_form':'AS_IS','skills':['sum'],'operations':['sum']},
                        {'id':'spare','summary':'spare','kind':'tool','files':['spare.py','skills/spare/SKILL.md'],
                         'default_form':'AS_IS','skills':['spare'],'operations':['spare']}]}}
        self.map_path=self.root/'features.json';self.map_path.write_text(json.dumps(mapping))
        self.config['connections']['feature_selections']=[{'key':'instance.demo','mapping_path':str(self.map_path)}]
        self.config['connections']['workpack_ids']=['BUILD']
        sources=self.root/'requirements';sources.mkdir();(sources/'brief.md').write_text('Only add the new input numbers.\n')
        self.config.update(source_root=str(sources),requirement_links=[{'capability':'instance.demo','feature':'sum','source_id':'R','source_locator':'L1'}],
          base_materials={'request':{'requirement_ir':{'sources':[{'source_id':'R','path_or_uri':'brief.md'}]},'plan':{'workpacks':[{'workpack_id':'BUILD','inputs':[]}]}},
                          'source_manifest':[{'source_id':'R','path':'brief.md'}]})
    def test_trimmed_skills_and_runtime_bind_without_source_and_reject_unselected(self):
        self.feature_setup();m,_=module('prepare').build_materials(self.config,self.root/'prepared')
        self.assertEqual(m['native_bindings']['instance.demo']['operations'],['sum'])
        d=self.D.prepare_delivery(m,self.output)
        protected=self.root/'protected-delivery';shutil.copytree(self.output,protected)
        check=module('check_capability_delivery')
        self.assertEqual(check.check(self.output,protected,[self.output/'AGENTS.md'])['status'],'CHECKS_PASS')
        row=d['external'][0];target=self.output/row['root']
        self.assertFalse((target/'spare.py').exists());self.assertFalse((target/'skills/spare').exists())
        self.assertEqual(len(row['catalog']['skills']),2);self.assertEqual(len(row['delivery_identity']['catalog']['skills']),1)
        self.assertEqual(d['instruction_snippets']['instance.demo'],row['root']+'/guide.md')
        shutil.rmtree(self.source);self.adapter.unlink();self.map_path.unlink()
        b=self.bind();call=self.D.prepare_call(b,'sum',['2.5','3.75'],cwd=self.project)
        r=subprocess.run(call['argv'],capture_output=True,text=True,timeout=10)
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(json.loads(r.stdout),{'total':'6.25'})
        with self.assertRaises(ValueError):self.D.prepare_call(b,'spare',cwd=self.project)
        (target/'tool.py').unlink()
        with self.assertRaises((ValueError,OSError)):self.D.prepare_call(b,'sum',cwd=self.project)
    def test_external_mapping_change_rejected_before_delivery(self):
        self.feature_setup();m,_=module('prepare').build_materials(self.config,self.root/'prepared');self.map_path.write_text('{}')
        with self.assertRaises(ValueError):self.D.prepare_delivery(m,self.output)

    def test_material_only_subset_has_no_operation_and_preserves_known_material(self):
        self.feature_setup();mapping=json.loads(self.map_path.read_text())
        f=mapping['capability']['features'][0];f['operations']=[];f['kind']='material';f['files']=['skills/sum/SKILL.md']
        # The original runtime file stays owned by an unselected feature.
        mapping['capability']['features'][1]['files'].append('tool.py')
        self.map_path.write_text(json.dumps(mapping))
        m,_=module('prepare').build_materials(self.config,self.root/'prepared')
        self.assertFalse(m['native_bindings'])
        result=self.D.prepare_delivery(m,self.output);row=result['external'][0];target=self.output/row['root']
        self.assertEqual(row['mode'],'CATALOG_ONLY');self.assertFalse(result['runtime_verified'])
        self.assertTrue((target/'skills/sum/SKILL.md').is_file())
        self.assertFalse((target/'spare.py').exists());self.assertFalse((target/'tool.py').exists())
        self.assertEqual(len(row['delivery_catalog']['skills']),1)
    def test_direct_native_binding_rejects_layout_change(self):
        self.feature_setup();m,_=module('prepare').build_materials(self.config,self.root/'prepared')
        row=self.D.prepare_delivery(m,self.output)['external'][0];b=self.bind()
        target=self.output/row['root']/'tool.py';target.chmod(target.stat().st_mode ^ 0o100)
        with self.assertRaisesRegex(ValueError,'layout'):self.D.N.check_native(b)

    def test_old_skill_list_does_not_expand_feature_scope_or_remove_other_connections(self):
        self.feature_setup()
        other=self.root/'other';(other/'.codex-plugin').mkdir(parents=True);(other/'skills/reference').mkdir(parents=True)
        (other/'.codex-plugin/plugin.json').write_text(json.dumps({'name':'other','version':'1','skills':'skills'}))
        (other/'skills/reference/SKILL.md').write_text('---\nname: reference\n---\nOther reference.\n')
        self.D.C.configure(self.instance,'instance','other',other)
        self.config['connections']['skills']=['instance.demo:spare','instance.other:reference']
        m,files=module('prepare').build_materials(self.config,self.root/'prepared')
        self.assertEqual(m['preparation']['readiness'],'READY',m['preparation']['diagnostics'])
        names=set(files)
        self.assertIn('sources/external/instance.demo/materials/skills/sum/SKILL.md',names)
        self.assertIn('sources/external/instance.other/materials/skills/reference/SKILL.md',names)
        self.assertNotIn('sources/external/instance.demo/materials/skills/spare/SKILL.md',names)
        self.assertEqual(m['native_bindings']['instance.demo']['operations'],['sum'])
        # No feature mapping means the old explicit Skill list still applies.
        old=deepcopy(self.config);old['connections'].pop('feature_selections')
        _,old_files=module('prepare').build_materials(old,self.root/'legacy')
        self.assertIn('sources/external/instance.demo/materials/skills/spare/SKILL.md',old_files)

    def test_selected_build_only_skill_loads_but_is_not_delivered(self):
        self.feature_setup();mapping=json.loads(self.map_path.read_text())
        mapping['capability']['features'][0]['usage']='build';self.map_path.write_text(json.dumps(mapping))
        self.config['connections']['skills']=['instance.demo:spare']
        m,files=module('prepare').build_materials(self.config,self.root/'prepared')
        self.assertIn('sources/external/instance.demo/materials/skills/sum/SKILL.md',files)
        self.assertNotIn('sources/external/instance.demo/materials/skills/spare/SKILL.md',files)
        d=self.D.prepare_delivery(m,self.output)
        self.assertEqual(d['external'],[])
        self.assertEqual(d['features'][0]['final_form'],'BUILD_ONLY')

    def decided_config(self):
        self.config['capability_conditions']=[{'capability':'instance.demo','feature':'sum','unresolved':True,
            'category':'PROJECT_CONFLICT','question':'Retain this implementation?',
            'evidence':['fixture source and requirements'],'options':[{'id':'AS_IS'}]}]
        m,_=module('prepare').build_materials(self.config,self.root/'first')
        req=m['preparation']['external_features']['instance.demo']['decision_requests'][0]
        self.config['decision_records']=[{'decision_id':'fixture','request_ids':[req['request_id']],
            'subject':req['subject'],'choice':'AS_IS','context_identity':req['context_identity'],
            'decided_by':{'role':'USER'},'message_ref':{'chat_thread_id':'fixture','turn_id':'fixture'}}]
        return req

    def feature_request(self, label):
        m,_=module('prepare').build_materials(self.config,self.root/label)
        return m,m['preparation']['external_features']['instance.demo']['decision_requests'][0]

    def test_changed_related_source_stales_decision_and_restored_bytes_reuse_it(self):
        self.feature_setup();req=self.decided_config();saved=deepcopy(self.config['decision_records'])
        for path in ('skills/sum/SKILL.md','tool.py','guide.md'):
            with self.subTest(path=path):
                p=self.source/path;before=p.read_bytes();p.write_bytes(before+b'\nchanged related source\n')
                self.D.C.configure(self.instance,'instance','demo',self.source)
                m,new=self.feature_request('changed-'+p.name)
                self.assertNotEqual(new['context_identity'],req['context_identity'])
                self.assertTrue(any(d['code']=='DECISION_STALE' for d in m['preparation']['diagnostics']))
                p.write_bytes(before);self.D.C.configure(self.instance,'instance','demo',self.source)
                m,new=self.feature_request('restored-'+p.name)
                self.assertEqual(new,req);self.assertEqual(m['preparation']['readiness'],'READY')
        self.assertEqual(saved,self.config['decision_records'])

    def test_unselected_changes_and_source_relocation_do_not_repeat_decision(self):
        self.feature_setup();req=self.decided_config()
        for path in ('skills/spare/SKILL.md','spare.py'):
            p=self.source/path;p.write_bytes(p.read_bytes()+b'\nUnrelated change\n')
        self.D.C.configure(self.instance,'instance','demo',self.source)
        m,new=self.feature_request('unrelated');self.assertEqual(new,req)
        self.assertEqual(m['preparation']['readiness'],'READY')
        relocated=self.root/'relocated original';self.source.rename(relocated);self.source=relocated
        archive=self.root/'same source.zip'
        with zipfile.ZipFile(archive,'w') as z:
            for p in sorted(self.source.rglob('*')):
                if p.is_file():z.write(p,p.relative_to(self.source).as_posix())
        self.D.C.configure(self.instance,'instance','demo',archive)
        self.config['connections']['native'][0]['root']=str(self.source)
        m,new=self.feature_request('zip');self.assertEqual(new,req)
        self.assertEqual(m['preparation']['readiness'],'READY')

    def test_related_dependency_source_participates_in_decision(self):
        self.feature_setup();mapping=json.loads(self.map_path.read_text())
        mapping['capability']['features'][0]['requires']=['spare'];self.map_path.write_text(json.dumps(mapping))
        self.config['connections']['native'][0]['environment_bindings']['missing']={'path':sys.executable}
        req=self.decided_config();p=self.source/'spare.py';p.write_bytes(p.read_bytes()+b'\nchanged dependency\n')
        self.D.C.configure(self.instance,'instance','demo',self.source)
        m,new=self.feature_request('dependency')
        self.assertNotEqual(new['context_identity'],req['context_identity'])
        self.assertTrue(any(d['code']=='DECISION_STALE' for d in m['preparation']['diagnostics']))

    def test_unbound_old_decision_does_not_pass_as_source_bound(self):
        self.feature_setup();self.decided_config()
        mapping=json.loads(self.map_path.read_bytes());package=mapping['capability'];package['name']='instance.demo'
        old=I.select(package,self.config['connections']['feature_selections'][0],self.config,
                     {'R':(self.root/'requirements/brief.md').read_bytes()},self.D.C.digest(self.map_path.read_bytes()))
        req=old['decision_requests'][0];record=self.config['decision_records'][0]
        record.update(request_ids=[req['request_id']],context_identity=req['context_identity'])
        m,_=self.feature_request('unbound')
        self.assertTrue(any(d['code']=='DECISION_STALE' for d in m['preparation']['diagnostics']))

    def test_decision_sources_rechecked_without_native_binding(self):
        self.feature_setup();mapping=json.loads(self.map_path.read_text())
        feature=mapping['capability']['features'][0];feature['operations']=[];feature['kind']='material'
        self.map_path.write_text(json.dumps(mapping));self.decided_config()
        m,_=self.feature_request('bound');self.assertFalse(m['native_bindings'])
        original=deepcopy(m);p=self.source/'tool.py';before=p.read_bytes()
        p.write_bytes(before+b'\nchanged public dependency\n')
        changed=module('prepare').check_selection(m)
        self.assertEqual(changed['status'],'CHANGED')
        self.assertIn('decision_sources',{r['path'] for r in changed['changes']})
        p.write_bytes(before)
        self.assertEqual(module('prepare').check_selection(m)['status'],'MATCH')
        self.assertEqual(m,original)

    def test_no_condition_adds_no_decision_or_source_gate(self):
        self.feature_setup()
        m,_=module('prepare').build_materials(self.config,self.root/'ordinary')
        self.assertEqual(m['preparation']['external_features']['instance.demo']['decision_requests'],[])

if __name__=='__main__':unittest.main()
