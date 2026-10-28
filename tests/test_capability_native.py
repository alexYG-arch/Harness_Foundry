"""Native handoff engineering checks; fixtures are not service acceptance."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'examples/capability-adapters'
def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value
N = module('native_tested', BASE / 'native.py')
P = module('native_prepare_tested', BASE / 'prepare.py')
C = module('native_consume_tested', BASE / 'consume.py')
from harness_foundry_factory.process_observation import CommandObservation


class NativeCapabilityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='native handoff-')
        self.addCleanup(temp.cleanup); self.root = Path(temp.name).resolve()
        self.project = self.root / '工程 project'; self.project.mkdir()
        self.instance = self.root / 'host'; self.instance.mkdir()
        self.package = self.root / 'provider'; (self.package / '.codex-plugin').mkdir(parents=True)
        (self.package / '.codex-plugin/plugin.json').write_text(json.dumps({'name':'demo','version':'1'}))
        (self.package / 'tool.py').write_text('import json,sys\nprint(json.dumps(sys.argv[1:]))\n')
        self.adapter = self.root / 'adapter.json'
        self.definition = {'provider':'demo','version':'1','package_versions':['1'],
            'runtime_files':['.codex-plugin/plugin.json','tool.py'],
            'operations':{'echo':{'argv':['tool:python','package:tool.py'], 'tools':['python'], 'effects':[]}}}
        self.adapter.write_text(json.dumps(self.definition))
        N.C.configure(self.instance, 'instance', 'demo', self.package)
        self.connection = N.C.load_connections(self.instance)['connections'][0]
        self.config = {'key':'instance.demo','adapter_path':str(self.adapter),'root':str(self.package),
                       'operations':['echo'],'environment_bindings':{'python':{'path':sys.executable}}}

    def binding(self):
        return N.bind_native(self.connection, self.config, project_root=self.project)

    def test_prepare_does_not_execute_and_original_argv_preserves_unicode(self):
        with patch('subprocess.Popen',side_effect=AssertionError('preparation must not execute')):
            b = self.binding(); c=N.prepare_call(b,'echo',['空 格','--x'],cwd=self.project)
        self.assertEqual(c['argv'],[sys.executable,str(self.package/'tool.py'),'空 格','--x'])
        r=subprocess.run(c['argv'],cwd=c['cwd'],capture_output=True,text=True,timeout=10)
        self.assertEqual(r.returncode,0);self.assertEqual(json.loads(r.stdout),['空 格','--x'])
        self.assertFalse(c['acceptance_granted'])

    def test_zip_origin_matches_installed_layout_without_rewriting(self):
        archive=self.root/'original.zip'
        with zipfile.ZipFile(archive,'w') as z:
            for p in self.package.rglob('*'):
                if p.is_file():z.write(p,'bundle/'+p.relative_to(self.package).as_posix())
        original=archive.read_bytes()
        N.C.configure(self.instance,'instance','demo',archive)
        self.connection=N.C.load_connections(self.instance)['connections'][0]
        b=self.binding(); self.assertTrue(N.check_native(b))
        self.assertEqual(archive.read_bytes(),original)
        (self.package/'tool.py').write_text('changed')
        with self.assertRaisesRegex(ValueError,'differs'):self.binding()

    def test_live_file_and_adapter_changes_rejected_then_restore(self):
        b=self.binding()
        for path in [self.package/'tool.py', self.adapter]:
            original=path.read_bytes();path.write_bytes(original+b'\n')
            with self.assertRaises(ValueError):N.prepare_call(b,'echo',cwd=self.project)
            path.write_bytes(original); self.assertTrue(N.check_native(b))

    def test_wrong_provider_version_entry_and_missing_dependency(self):
        for edit in [lambda d:d.update(provider='other'),lambda d:d.update(package_versions=['2']),
                     lambda d:d.update(runtime_files=['missing.py'])]:
            d=deepcopy(self.definition);edit(d);self.adapter.write_text(json.dumps(d))
            with self.assertRaises((ValueError,FileNotFoundError)):self.binding()
        self.adapter.write_text(json.dumps(self.definition))
        b=self.binding()
        with self.assertRaises(ValueError):N.prepare_call(b,'unknown',cwd=self.project)

    def test_missing_tool_is_diagnostic_without_install(self):
        self.config['environment_bindings']={}
        b=self.binding();self.assertEqual(b['environment']['status'],'INCOMPLETE')
        with self.assertRaisesRegex(ValueError,'environment'):N.prepare_call(b,'echo',cwd=self.project)

    def test_declared_file_symlink_alias_and_escape(self):
        saved=(self.package/'tool.py').read_bytes()
        (self.package/'impl.py').write_bytes(saved);(self.package/'tool.py').unlink()
        (self.package/'tool.py').symlink_to('impl.py')
        self.assertTrue(N.check_native(self.binding()))
        (self.package/'tool.py').unlink();outside=self.root/'outside.py';outside.write_bytes(saved)
        (self.package/'tool.py').symlink_to(outside)
        with self.assertRaises(ValueError):self.binding()

    def test_prepare_consume_integration_and_no_namespace_override(self):
        config={'project_root':str(self.project),'connections':{'instance_root':str(self.instance),'native':[self.config]}}
        m,_=P.build_materials(config,self.root/'prepared')
        self.assertEqual(m['preparation']['readiness'],'READY')
        self.assertEqual(P.check_selection(m)['status'],'MATCH')
        call=C.prepare_call(m,'instance.demo.echo',['abc'])
        self.assertEqual(call['argv'][-1],'abc');self.assertEqual(call['cwd'],str(self.project))
        self.assertIn('instance.demo.python',m['scope_fragment']['executables'])
        self.assertEqual(call['local_argv'],['instance.demo.python',str(self.package/'tool.py'),'abc'])
        self.assertNotIn('python',m['scope_fragment']['executables'])
        (self.package/'tool.py').write_text('changed')
        self.assertEqual(P.check_selection(m)['status'],'CHANGED')
        with self.assertRaises(ValueError):C.prepare_call(m,'instance.demo.echo')

    def test_second_merge_retains_bindings_and_no_duplicate_task_source(self):
        source=self.root/'sources';source.mkdir();(source/'brief.md').write_text('Build fixture')
        req={'requirement_ir':{'sources':[{'source_id':'BRIEF','path_or_uri':'brief.md','loaded_completely':True}]},
             'plan':{'workpacks':[{'workpack_id':'BUILD','inputs':[]}]}}
        config={'project_root':str(self.project),'source_root':str(source),
                'base_materials':{'request':req,'source_manifest':[{'source_id':'BRIEF','path':'brief.md'}]},
                'connections':{'instance_root':str(self.instance),'workpack_ids':['BUILD'],'native':[self.config]}}
        first=P.write_materials(config,self.root/'first')
        config.update(base_materials=first,source_root=str(self.root/'first/sources'))
        second,_=P.build_materials(config,self.root/'second')
        self.assertEqual(first['native_bindings'],second['native_bindings'])
        self.assertEqual(first['request'],second['request'])
        self.assertEqual(first['tool_bindings'],second['tool_bindings'])

    def test_native_reads_cannot_expose_private_checker_or_overlap_task_writes(self):
        for scope in [{'verification_root':str(self.package)},
                      {'workspace_root':str(self.root),'task_write_roots':{'BUILD':['provider']}}]:
            req={'requirement_ir':{'sources':[]},'plan':{'workpacks':[{'workpack_id':'BUILD','inputs':[]}]}}
            config={'project_root':str(self.project),'source_root':str(self.project),
                    'base_materials':{'request':req,'scope':scope,'source_manifest':[]},
                    'connections':{'instance_root':str(self.instance),'workpack_ids':['BUILD'],'native':[self.config]}}
            with self.assertRaises(ValueError):P.build_materials(config,self.root/'prepared')

    def test_recovery_keeps_original_identity_without_reprobe_or_reexecution(self):
        b=self.binding();call=N.prepare_call(b,'echo',['new input'],cwd=self.project)
        obs=CommandObservation(self.root/'obs','COMMAND-1','LOCAL');self.addCleanup(obs.close)
        N.attach_call(obs,call);N.attach_call(obs,call)
        result={'status':'COMPLETED','exit_code':0,'stdout':'original captured output','stderr':''}
        obs.finished(result)
        (self.package/'tool.py').unlink();self.adapter.unlink()
        with patch('subprocess.Popen',side_effect=AssertionError('recovery must not execute')):
            first=N.recover_call(obs.root,'COMMAND-1','LOCAL')
            second=N.recover_call(obs.root,'COMMAND-1','LOCAL')
        self.assertEqual(first,second);self.assertEqual(first['result'],result)
        self.assertFalse(first['replay_allowed'])
        with self.assertRaises(ValueError):N.recover_call(obs.root,'COMMAND-2','LOCAL')

    def test_partial_capture_never_requests_replay_or_completion(self):
        obs=CommandObservation(self.root/'obs','COMMAND-1','LOCAL');self.addCleanup(obs.close)
        N.attach_call(obs,N.prepare_call(self.binding(),'echo',cwd=self.project))
        obs.started(999999);obs.write('stdout',b'partial')
        got=N.recover_call(obs.root,'COMMAND-1','LOCAL')
        self.assertEqual(got['status'],'UNRESOLVED');self.assertIsNone(got['result'])
        self.assertFalse(got['replay_allowed'])
        with self.assertRaises(ValueError):N.attach_call(obs,{})

    def test_receipt_omits_argument_secrets_and_binding_is_immutable(self):
        obs=CommandObservation(self.root/'obs','COMMAND-1','LOCAL');self.addCleanup(obs.close)
        call=N.prepare_call(self.binding(),'echo',['--token','synthetic-secret'],cwd=self.project)
        N.attach_call(obs,call)
        self.assertNotIn('synthetic-secret',(obs.root/'native-call.json').read_text())
        with self.assertRaises(ValueError):N.attach_call(obs,{**call,'version':'other'})






    def test_native_only_version_upgrade_and_removal_keep_old_materials(self):
        U=module('native_upgrade_tested',BASE/'upgrade.py')
        config={'project_root':str(self.project),'selections':[],
                'connections':{'instance_root':str(self.instance),'native':[self.config]}}
        old=P.write_materials(config,self.root/'old');saved=deepcopy(old)
        newer=self.root/'provider-v2';shutil.copytree(self.package,newer)
        (newer/'.codex-plugin/plugin.json').write_text(json.dumps({'name':'demo','version':'2'}))
        adapter2=self.root/'adapter-v2.json';definition=deepcopy(self.definition)
        definition.update(version='2',package_versions=['2']);adapter2.write_text(json.dumps(definition))
        N.C.configure(self.instance,'instance','demo',newer)
        next_config=deepcopy(config);next_config['connections']['native'][0].update(root=str(newer),adapter_path=str(adapter2))
        new,files,transition=U.build_upgrade(old,next_config,self.root/'next')
        self.assertEqual(C.prepare_call(new,'instance.demo.echo')['version'],'2')
        self.assertEqual(transition['native_bindings'][0]['change'],'CHANGED')
        self.assertEqual(old,saved);self.assertTrue(P.check_selection(old)['status']=='MATCH')
        self.assertFalse(transition['budget_modified']);self.assertFalse(transition['commands_executed'])
        empty,_,removed=U.build_upgrade(new,{'project_root':str(self.project),'selections':[]},self.root/'removed')
        self.assertFalse(empty['tool_bindings']);self.assertEqual(removed['native_bindings'][0]['change'],'REMOVED')
        self.assertTrue(self.package.exists() and newer.exists())

    def test_native_same_version_change_is_an_explicit_new_source_binding(self):
        U=module('native_rebind_tested',BASE/'upgrade.py')
        config={'project_root':str(self.project),'selections':[],
                'connections':{'instance_root':str(self.instance),'native':[self.config]}}
        old=P.write_materials(config,self.root/'old')
        old_handoff=(self.root/'old/sources/external/instance.demo/native-handoff.json').read_bytes()
        (self.package/'tool.py').write_text('print("new content")')
        self.assertEqual(P.check_selection(old)['status'],'CHANGED')
        new,files,transition=U.build_upgrade(old,config,self.root/'next')
        self.assertEqual(P.check_selection(new)['status'],'MATCH')
        self.assertNotEqual(files['sources/external/instance.demo/native-handoff.json'],old_handoff)
        self.assertEqual(transition['previous_selection_check']['status'],'CHANGED')
        self.assertTrue(transition['source_files']);self.assertFalse(transition['authority_inherited'])
        self.assertEqual((self.root/'old/sources/external/instance.demo/native-handoff.json').read_bytes(),old_handoff)

    def wildcard_source(self, archive_prefix=None):
        for rel in ['runtime/main.py', 'runtime/lib/helper.py', 'runtime/lib/deep/nested.py']:
            path=self.package/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('# original '+rel)
        self.definition['runtime_files']=['.codex-plugin/plugin.json','tool.py','runtime/**/*.py']
        self.adapter.write_text(json.dumps(self.definition))
        original=self.root/'original';shutil.copytree(self.package,original)
        (original/'unselected.txt').write_text('not a runtime dependency')
        source=original
        if archive_prefix is not None:
            source=self.root/'original.zip'
            with zipfile.ZipFile(source,'w') as z:
                for path in original.rglob('*'):
                    if path.is_file():z.write(path,archive_prefix+path.relative_to(original).as_posix())
        N.C.configure(self.instance,'instance','demo',source)
        self.connection=N.C.load_connections(self.instance)['connections'][0]
        return source

    def test_directory_glob_missing_member_rejected_without_requiring_unselected_files(self):
        original=self.wildcard_source()
        self.assertTrue(N.check_native(self.binding()))
        missing=self.package/'runtime/lib/helper.py';raw=missing.read_bytes();missing.unlink()
        with self.assertRaisesRegex(ValueError,'missing.*runtime/lib/helper.py'):self.binding()
        missing.write_bytes(raw)
        self.assertTrue(N.check_native(self.binding()))
        self.assertEqual((original/'runtime/lib/helper.py').read_bytes(),raw)
        (self.package/'runtime/extra.py').write_text('# unexpected declared member')
        with self.assertRaises(ValueError):self.binding()

    def test_zip_glob_missing_member_rejected_and_recursive_zero_depth_kept(self):
        source=self.wildcard_source('bundle/')
        saved=source.read_bytes()
        self.assertTrue(N.check_native(self.binding()))
        for relative in ['runtime/main.py','runtime/lib/helper.py','runtime/lib/deep/nested.py']:
            with self.subTest(relative=relative):
                path=self.package/relative;raw=path.read_bytes();path.unlink()
                try:
                    with self.assertRaisesRegex(ValueError,'missing.*'+relative):self.binding()
                finally:
                    path.write_bytes(raw)
        self.assertEqual(source.read_bytes(),saved)
        self.assertTrue(N.check_native(self.binding()))

    def test_zip_glob_matches_declared_depth_only_without_wrapper_directory(self):
        self.wildcard_source('')
        self.definition['runtime_files']=['.codex-plugin/plugin.json','tool.py','runtime/*.py']
        self.adapter.write_text(json.dumps(self.definition))
        (self.package/'runtime/lib/helper.py').unlink()
        self.assertTrue(N.check_native(self.binding()))
        (self.package/'runtime/main.py').unlink()
        with self.assertRaises(ValueError):self.binding()

    def material_upgrade_fixture(self):
        U=module('native_material_upgrade_tested',BASE/'upgrade.py')
        skill=self.package/'skills/review/SKILL.md';skill.parent.mkdir(parents=True)
        skill.write_text('---\nname: review\ndescription: Review public inputs\n---\nOriginal review method.\n')
        (self.package/'.codex-plugin/plugin.json').write_text(json.dumps({'name':'demo','version':'1','skills':'./skills/'}))
        N.C.configure(self.instance,'instance','demo',self.package)
        req={'requirement_ir':{'sources':[]},'plan':{'workpacks':[{'workpack_id':'BUILD','inputs':[]}]}}
        config={'project_root':str(self.project),'source_root':str(self.project),'selections':[],
                'base_materials':{'request':req,'source_manifest':[], 'scope':{'max_attempts':3}},
                'connections':{'instance_root':str(self.instance),'workpack_ids':['BUILD'],
                               'skills':['instance.demo:review'],'native':[self.config]}}
        old=P.write_materials(config,self.root/'original-materials')
        return U,config,old,skill

    def test_upgrade_removes_native_tools_but_retains_selected_materials(self):
        U,config,old,skill=self.material_upgrade_fixture();saved=deepcopy(old)
        for explicit_empty in [False,True]:
            with self.subTest(explicit_empty=explicit_empty):
                next_config=deepcopy(config)
                if explicit_empty:next_config['connections']['native']=[]
                else:del next_config['connections']['native']
                with patch('subprocess.Popen',side_effect=AssertionError('upgrade never dispatches')):
                    new,files,transition=U.build_upgrade(old,next_config,self.root/'next')
                self.assertEqual(new['preparation']['readiness'],'READY')
                self.assertFalse(new.get('native_bindings'));self.assertFalse(new['tool_bindings'])
                self.assertEqual([r['key'] for r in new['preparation'].get('external_connections',[])],['instance.demo'])
                self.assertEqual(files['sources/external/instance.demo/materials/skills/review/SKILL.md'],skill.read_bytes())
                ids={r['source_id'] for r in new['source_manifest']}
                self.assertEqual(ids,{v['id'] for v in new['request']['plan']['workpacks'][0]['inputs']})
                self.assertFalse(any('native-handoff' in name for name in files))
                self.assertEqual(new['scope']['max_attempts'],3)
                self.assertEqual(transition['native_bindings'][0]['change'],'REMOVED')
                self.assertFalse(transition['budget_modified']);self.assertFalse(transition['authority_inherited'])
                self.assertEqual(old,saved)

    def test_material_only_upgrade_keeps_connection_diagnostics_and_known_results(self):
        U,config,old,skill=self.material_upgrade_fixture()
        config['connections'].pop('native')
        config['connections']['skills'].append('instance.missing:review')
        new,files,_=U.build_upgrade(old,config,self.root/'next')
        self.assertEqual(new['preparation']['readiness'],'INCOMPLETE')
        self.assertIn('SKILL_UNAVAILABLE',{r['code'] for r in new['preparation']['diagnostics']})
        self.assertEqual(files['sources/external/instance.demo/materials/skills/review/SKILL.md'],skill.read_bytes())

    def test_explicit_disconnect_can_return_to_project_only_with_empty_registry(self):
        U,config,old,_=self.material_upgrade_fixture()
        N.C.configure(self.instance,'instance','demo',enabled=False)
        config['connections'].update(native=[],skills=[])
        new,files,transition=U.build_upgrade(old,config,self.root/'next')
        self.assertEqual(new['preparation']['readiness'],'READY')
        self.assertFalse(new['source_manifest']);self.assertFalse(new['tool_bindings'])
        self.assertEqual(new['scope']['max_attempts'],3)
        self.assertFalse(transition['budget_modified']);self.assertFalse(transition['physical_files_removed'])
        self.assertTrue(self.package.exists())

    def test_unavailable_materials_keep_project_and_diagnostic_severity(self):
        U,config,old,_=self.material_upgrade_fixture()
        self.package.rename(self.root/'temporarily-unavailable')
        config['connections']['native']=[]
        for required in [False,True]:
            with self.subTest(required=required):
                config['connections']['skills']=['instance.demo:review'] if required else []
                new,files,transition=U.build_upgrade(old,config,self.root/'next')
                self.assertEqual(new['preparation']['readiness'],'INCOMPLETE' if required else 'READY')
                self.assertEqual(new['scope']['max_attempts'],3)
                self.assertFalse(new['tool_bindings']);self.assertFalse(transition['budget_modified'])
                self.assertIn('CONNECTION_UNAVAILABLE',{r['code'] for r in new['preparation']['diagnostics']})
                self.assertEqual(any(r['severity']=='ERROR' for r in new['preparation']['diagnostics']),required)



if __name__=='__main__':unittest.main()
