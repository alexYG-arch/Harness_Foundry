"""External target delivery engineering checks, not remote/model acceptance."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'examples/capability-adapters'
def load(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
D=load('external_delivery_tests',BASE/'delivery.py')
P=D.module('prepare')
MERGE=load('external_delivery_merge',ROOT/'examples/harness-composition-upgrade/helpers/merge.py')
from harness_foundry_factory.process_observation import CommandObservation

class ExternalDeliveryTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(prefix='external delivery-');self.addCleanup(t.cleanup)
        self.root=Path(t.name).resolve();self.project=self.root/'接收 project';self.project.mkdir()
        self.instance=self.root/'host';self.instance.mkdir();self.source=self.root/'original'
        (self.source/'.codex-plugin').mkdir(parents=True);(self.source/'skills').mkdir()
        (self.source/'.codex-plugin/plugin.json').write_text(json.dumps({'name':'demo','version':'1','skills':'skills'}))
        (self.source/'tool.py').write_text('import json,sys\nfrom decimal import Decimal\nprint(json.dumps({"total":str(sum(map(Decimal,sys.argv[1:]),Decimal(0)))}))\n')
        (self.source/'tool.py').chmod(0o751);(self.source/'LICENSE').write_text('fixture license')
        (self.source/'private.json').write_text('PRIVATE EXPECTATION SENTINEL')
        self.adapter=self.root/'adapter.json'
        self.definition={'provider':'demo','version':'1','package_versions':['1'],
            'runtime_files':['.codex-plugin/plugin.json','tool.py'],
            'operations':{'sum':{'argv':['tool:python','package:tool.py'],'tools':['python'],'effects':[]}}}
        self.adapter.write_text(json.dumps(self.definition));self.output=self.root/'support'
        self.environment={'python':{'path':sys.executable}}
        D.C.configure(self.instance,'instance','demo',self.source)
        self.config={'project_root':str(self.project),'connections':{'instance_root':str(self.instance),
            'native':[{'key':'instance.demo','adapter_path':str(self.adapter),'root':str(self.source),
                       'environment_bindings':self.environment}]}}

    def materials(self):
        return P.build_materials(self.config,self.root/'host-materials')[0]

    def deliver(self, **kw):
        return D.prepare_delivery(self.materials(),self.output,**kw)

    def bind(self):
        return D.bind_delivery(self.output,'instance.demo',self.environment,project_root=self.project)

    def cli(self, *args):
        result=subprocess.run([sys.executable,'-I','-S','-B',str(self.output/'examples/capability-adapters/delivery.py'),*map(str,args)],
            cwd=self.project,env={**os.environ,'PYTHONPATH':'/absent-developer-source'},capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return json.loads(result.stdout)

    def test_relocated_new_process_two_inputs_only_delivery_and_declared_interpreter(self):
        receipt=self.deliver();old=self.root/'relocated 交付';self.output.rename(old);self.output=old
        shutil.rmtree(self.source);shutil.rmtree(self.instance);self.adapter.unlink()
        env=self.root/'environment.json';env.write_text(json.dumps(self.environment));binding=self.root/'binding.json'
        result=self.cli('bind','--delivery',self.output,'--key','instance.demo','--environment',env,'--project-root',self.project,'--output',binding)
        self.assertEqual(result['environment']['scope_fragment']['executables']['python'],sys.executable)
        for values,expected in [(['1.25','2.75'],'4.00'),(['-0.10','0.30'],'0.20')]:
            call=self.cli('call','--binding',binding,'--operation','sum','--cwd',self.project,'--',*values)
            run=subprocess.run(call['argv'],cwd=call['cwd'],capture_output=True,text=True,timeout=20)
            self.assertEqual(run.returncode,0,run.stderr);self.assertEqual(json.loads(run.stdout),{'total':expected})
        self.assertFalse(receipt['runtime_verified']);self.assertFalse(receipt['budget_modified'])
        self.assertNotIn(str(self.source),(self.output/'delivery.json').read_text())
        self.assertFalse(any(b'PRIVATE EXPECTATION SENTINEL' in p.read_bytes() for p in self.output.rglob('*') if p.is_file()))
        self.assertEqual((self.output/'external/instance.demo/upstream/tool.py').stat().st_mode&0o777,0o751)
        self.assertTrue((self.output/'external/instance.demo/upstream/skills').is_dir())

    def test_relative_directory_and_multihop_links_keep_modes_and_only_needed_files(self):
        (self.source/'actual').mkdir();(self.source/'actual').chmod(0o750)
        (self.source/'spare').mkdir();(self.source/'spare/secret.txt').write_text('NOT SELECTED')
        (self.source/'tool.py').rename(self.source/'actual/tool.py')
        (self.source/'middle.py').symlink_to('actual/tool.py')
        (self.source/'tool.py').symlink_to('spare/../middle.py')
        (self.source/'alias').symlink_to('actual',target_is_directory=True)
        self.definition['runtime_files'].append('alias/tool.py');self.adapter.write_text(json.dumps(self.definition))
        self.deliver();b=self.bind();call=D.prepare_call(b,'sum',['2','3'],cwd=self.project)
        result=subprocess.run(call['argv'],capture_output=True,text=True,timeout=10)
        self.assertEqual(json.loads(result.stdout)['total'],'5')
        root=Path(b['root']);self.assertEqual(os.readlink(root/'tool.py'),'spare/../middle.py')
        self.assertEqual(os.readlink(root/'alias'),'actual');self.assertTrue((root/'spare').is_dir())
        self.assertEqual((root/'actual').stat().st_mode&0o777,0o750)
        self.assertFalse((root/'spare/secret.txt').exists())

    def test_absolute_or_escaping_or_cyclic_layout_rejected_without_execution(self):
        for target in (str(self.source/'tool.py'),'../outside','loop'):
            p=self.source/'loop';p.symlink_to(target)
            with self.assertRaises((ValueError,OSError,RuntimeError)):
                D.layout(self.source,['loop'])
            p.unlink()
        self.assertFalse(self.output.exists())

    def test_missing_tool_is_diagnostic_and_original_not_installed(self):
        self.deliver()
        b=D.bind_delivery(self.output,'instance.demo',{},project_root=self.project)
        self.assertEqual(b['environment']['status'],'INCOMPLETE')
        with self.assertRaisesRegex(ValueError,'environment'):
            D.prepare_call(b,'sum',cwd=self.project)

    def test_new_calls_check_layout_and_restore_does_not_change_identity(self):
        self.deliver();b=self.bind();p=Path(b['root'])/'tool.py';old=p.read_bytes()
        for change in ('bytes','mode','adapter'):
            if change=='bytes':p.write_bytes(old+b'# changed\n')
            elif change=='mode':p.chmod(0o600)
            else:Path(b['adapter_path']).write_text('{}')
            with self.assertRaises(ValueError):D.prepare_call(b,'sum',cwd=self.project)
            p.write_bytes(old);p.chmod(0o751);Path(b['adapter_path']).write_text(json.dumps(self.definition))
        self.assertEqual(D.prepare_call(b,'sum',cwd=self.project)['native_identity'],D.prepare_call(self.bind(),'sum',cwd=self.project)['native_identity'])

    def test_complete_report_retrieval_survives_package_removal_without_replay(self):
        self.deliver();b=self.bind();call=D.prepare_call(b,'sum',['4','5'],cwd=self.project)
        obs=CommandObservation(self.root/'capture','CMD','LOCAL');D.N.attach_call(obs,call)
        obs.started(123)
        result=subprocess.run(call['argv'],capture_output=True,timeout=10)
        obs.write('stdout',result.stdout);obs.captured({'exit_code':result.returncode,'stdout':result.stdout.decode(),'timed_out':False});obs.close()
        shutil.rmtree(Path(b['root']))
        with patch('subprocess.Popen',side_effect=AssertionError('no replay')):
            first=D.N.recover_call(obs.root,'CMD','LOCAL');second=D.N.recover_call(obs.root,'CMD','LOCAL')
        self.assertEqual(first,second);self.assertEqual(first['status'],'CAPTURED');self.assertFalse(first['replay_allowed'])
        # A fresh isolated interpreter must classify capture.json without host imports.
        for _ in range(2):
            r=subprocess.run([sys.executable,'-I','-S','-B',str(self.output/'examples/capability-adapters/native.py'),
                '--recover',str(obs.root),'--command-id','CMD','--executor','LOCAL'],capture_output=True,text=True,timeout=15)
            self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(json.loads(r.stdout),first)
        with self.assertRaises(ValueError):D.N.recover_call(obs.root,'OTHER','LOCAL')

    def test_partial_capture_remains_unknown(self):
        self.deliver();b=self.bind();call=D.prepare_call(b,'sum',cwd=self.project)
        obs=CommandObservation(self.root/'partial','CMD','LOCAL');D.N.attach_call(obs,call);obs.started(123)
        result=D.N.recover_call(obs.root,'CMD','LOCAL')
        self.assertEqual(result['status'],'UNRESOLVED');self.assertFalse(result['replay_allowed'])

    def test_partial_delivery_is_preserved_not_overwritten(self):
        with patch.object(D,'write',side_effect=OSError('storage fault')):
            with self.assertRaises(OSError):self.deliver()
        before={str(p):p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        self.assertFalse((self.output/'delivery.json').exists())
        with self.assertRaises(FileExistsError):self.deliver()
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.output.rglob('*') if p.is_file()})

    def test_stale_host_selection_rejected_before_delivery(self):
        materials=self.materials();(self.source/'tool.py').write_text('changed')
        with self.assertRaisesRegex(ValueError,'changed'):D.prepare_delivery(materials,self.output)
        self.assertFalse(self.output.exists())

    def test_selected_private_verifier_is_not_delivered(self):
        shutil.rmtree(self.source/'.codex-plugin');descriptor={'name':'demo','version':'1','verification_files':['private.json']}
        (self.source/'capability.json').write_text(json.dumps(descriptor))
        self.definition['runtime_files']=['capability.json','tool.py','private.json'];self.adapter.write_text(json.dumps(self.definition))
        D.C.configure(self.instance,'instance','demo',self.source)
        with self.assertRaisesRegex(ValueError,'private checker'):self.deliver()
        self.assertFalse(self.output.exists())

    def test_optional_rsi_uses_existing_delivery_and_tools_after_original_removed(self):
        materials=self.root/'rsi-materials';materials.mkdir();(materials/'private.json').write_text('RSI PRIVATE SENTINEL')
        manifest={'version':'E6','wiki':{'collections':[]},'knowledge_files':[]}
        r=self.deliver(rsi_manifest=manifest,rsi_material_root=materials);shutil.rmtree(materials)
        self.assertTrue(r['rsi_selected']);self.assertIn('existing repair return points',(self.output/'AGENTS.md').read_text())
        for script in ('tools/rsi_wiki.py','tools/rsi_review.py','tools/report_rsi_tdd.py','examples/capability-adapters/rsi_handoff.py'):
            run=subprocess.run([sys.executable,'-I','-S','-B',str(self.output/'rsi'/script),'--help'],capture_output=True,text=True,timeout=15)
            self.assertEqual(run.returncode,0,run.stderr)
        report=self.root/'query.json'
        run=subprocess.run([sys.executable,'-I','-S','-B',str(self.output/'rsi/tools/rsi_wiki.py'),'query','--config',str(self.output/'rsi/wiki.json'),'--question','new task','--output',str(report)],capture_output=True,text=True,timeout=15)
        self.assertEqual(run.returncode,0,run.stderr);self.assertEqual(json.loads(report.read_text())['matches'],[])
        self.assertFalse(any(b'RSI PRIVATE SENTINEL' in p.read_bytes() for p in self.output.rglob('*') if p.is_file()))

    def test_builtin_and_external_keep_separate_runtime_names(self):
        cap=self.root/'builtin';cap.mkdir();(cap/'tool.py').write_text('print("builtin")\n')
        (cap/'capability.json').write_text(json.dumps({'name':'demo','version':'1','usage':'both','inputs':['numbers'],'outputs':['sum'],'materials':[],
            'tools':[{'id':'sum','path':'tool.py','interpreter':'python'}], 'environment':[{'id':'python','kind':'executable'}]}))
        self.config['selections']=[{'directory':str(cap),'version':'1'}];self.config['environment_bindings']=self.environment
        r=self.deliver();self.assertEqual(r['builtin'][0]['name'],'demo')
        self.assertTrue((self.output/'builtin/capabilities/demo/1/tool.py').is_file())
        self.assertTrue((self.output/'external/instance.demo/upstream/tool.py').is_file())
        self.assertEqual(D.prepare_call(self.bind(),'sum',cwd=self.project)['tool_id'],'instance.demo.sum')

    def builtin_fixture(self, tools, runtime=(), verification=()):
        cap=self.root/'builtin';cap.mkdir()
        (cap/'capability.json').write_text(json.dumps({'name':'builtin','version':'1','usage':'both',
            'inputs':['fixture'],'outputs':['result'],'materials':[], 'tools':tools,
            'runtime_files':list(runtime), 'verification_files':list(verification),
            'environment':[{'id':'python','kind':'executable'}]}))
        self.config['selections']=[{'directory':str(cap),'version':'1'}]
        self.config['environment_bindings']=self.environment
        return cap

    def test_delivered_builtin_executable_runs_after_relocation_without_source(self):
        cap=self.builtin_fixture([{'id':'native-marker','path':'run.sh'}], verification=['private.json'])
        (cap/'run.sh').write_text('#!/bin/sh\nprintf "BUILTIN_OK\\n"\n')
        (cap/'run.sh').chmod(0o751);(cap/'private.json').write_text('BUILTIN PRIVATE EXPECTATION')
        before=subprocess.run([str(cap/'run.sh')],capture_output=True,text=True,timeout=15)
        self.assertEqual((before.returncode,before.stdout),(0,'BUILTIN_OK\n'))
        self.deliver();self.output.rename(self.root/'搬迁 support');self.output=self.root/'搬迁 support'
        shutil.rmtree(cap)
        tool=self.output/'builtin/capabilities/builtin/1/run.sh'
        self.assertEqual(tool.stat().st_mode&0o777,0o751)
        run=subprocess.run([str(tool)],cwd=self.project,capture_output=True,text=True,timeout=15)
        self.assertEqual((run.returncode,run.stdout),(0,'BUILTIN_OK\n'),run.stderr)
        self.assertFalse((tool.parent/'private.json').exists())
        self.assertEqual(D.prepare_call(self.bind(),'sum',cwd=self.project)['tool_id'],'instance.demo.sum')

    def test_delivered_builtin_links_read_declared_resources_without_private_siblings(self):
        cap=self.builtin_fixture([{'id':'linked-marker','path':'launch.py','interpreter':'python'}],
            runtime=['alias/data.txt','shared.txt'],
            verification=['bin/private.json',{'path':'shared.txt','shared':True}])
        (cap/'bin').mkdir();(cap/'spare').mkdir()
        (cap/'bin/main.py').write_text('from pathlib import Path\nprint(Path(__file__).resolve().with_name("data.txt").read_text())\n')
        (cap/'bin/main.py').chmod(0o751);(cap/'bin/data.txt').write_text('LINKED_OK')
        (cap/'bin/private.json').write_text('BUILTIN PRIVATE EXPECTATION');(cap/'spare/unused.txt').write_text('UNSELECTED')
        (cap/'shared.txt').write_text('shared public input')
        (cap/'alias').symlink_to('bin',target_is_directory=True)
        (cap/'middle.py').symlink_to('alias/main.py')
        (cap/'launch.py').symlink_to('spare/../middle.py')
        before=subprocess.run([sys.executable,'-I','-S','-B',str(cap/'launch.py')],capture_output=True,text=True,timeout=15)
        self.assertEqual((before.returncode,before.stdout),(0,'LINKED_OK\n'))
        self.deliver();self.output.rename(self.root/'搬迁 support');self.output=self.root/'搬迁 support'
        shutil.rmtree(cap)
        root=self.output/'builtin/capabilities/builtin/1'
        for name,target in [('launch.py','spare/../middle.py'),('middle.py','alias/main.py'),('alias','bin')]:
            with self.subTest(link=name):
                self.assertTrue((root/name).is_symlink())
                self.assertEqual(os.readlink(root/name),target)
        self.assertTrue((root/'spare').is_dir());self.assertEqual(list((root/'spare').iterdir()),[])
        self.assertEqual((root/'bin/main.py').stat().st_mode&0o777,0o751)
        self.assertEqual((root/'shared.txt').read_text(),'shared public input')
        run=subprocess.run([sys.executable,'-I','-S','-B',str(root/'launch.py')],cwd=self.project,capture_output=True,text=True,timeout=15)
        self.assertEqual((run.returncode,run.stdout),(0,'LINKED_OK\n'),run.stderr)
        content=b'\n'.join(p.read_bytes() for p in root.rglob('*') if p.is_file())
        self.assertNotIn(b'BUILTIN PRIVATE EXPECTATION',content);self.assertNotIn(b'UNSELECTED',content)

    def test_version_upgrade_is_new_selection_and_old_receipt_unchanged(self):
        first=self.deliver();oldbytes=(self.output/'delivery.json').read_bytes();old=self.output
        plugin=self.source/'.codex-plugin/plugin.json';data=json.loads(plugin.read_text());data['version']='2';plugin.write_text(json.dumps(data))
        self.definition['package_versions']=['2'];self.definition['version']='2';self.adapter.write_text(json.dumps(self.definition))
        D.C.configure(self.instance,'instance','demo',self.source)
        self.output=self.root/'support-v2';self.deliver()
        result=D.compare_deliveries(old,self.output)
        self.assertEqual(result['external'][0]['change'],'CHANGED');self.assertFalse(result['budget_modified'])
        self.assertEqual((old/'delivery.json').read_bytes(),oldbytes)
        # Choosing old delivery works without reconnecting or mutating old observations.
        self.assertTrue(D.bind_delivery(old,'instance.demo',self.environment,project_root=self.project))

    def test_existing_cgn_preserves_customization_and_missing_baseline_conflicts(self):
        states=self.root/'states';states.mkdir()
        for name,raw in [('current','custom'),('generated','default'),('next','default')]: (states/name).write_text(raw)
        item={'path':'connection.json','owners':['foundry-connection'],'C':{'file':'current','executable':False},'G':{'file':'generated','executable':False},'N':{'file':'next','executable':False}}
        manifest=states/'inputs.json';manifest.write_text(json.dumps({'format_version':1,'files':[item]}))
        result=MERGE.merge(manifest,self.root/'candidate1');self.assertEqual(result['files'][0]['selected'],'C')
        (states/'next').write_text('new-default');manifest.write_text(json.dumps({'format_version':1,'files':[item]}))
        self.assertEqual(MERGE.merge(manifest,self.root/'candidate2')['status'],'CONFLICT')
        item['G']=None;manifest.write_text(json.dumps({'format_version':1,'files':[item]}))
        self.assertEqual(MERGE.merge(manifest,self.root/'candidate3')['status'],'PROJECT_INCREMENTAL_REQUIRED')
        self.assertEqual((states/'current').read_text(),'custom')

    def test_public_only_connection_delivers_materials_without_guessing_commands(self):
        self.config['connections']['native']=[]
        r=self.deliver();self.assertEqual(r['external'][0]['mode'],'CATALOG_ONLY')
        self.assertTrue((self.output/'external/instance.demo/upstream/.codex-plugin/plugin.json').is_file())
        self.assertFalse((self.output/'external/instance.demo/upstream/tool.py').exists())
        public=self.output/'external/instance.demo/upstream'
        catalog,_=D.C.discover(public)
        self.assertEqual(catalog,r['external'][0]['catalog'])
        self.assertEqual((public/'LICENSE').read_text(),'fixture license')
        with self.assertRaisesRegex(ValueError,'catalog-only'):self.bind()

    def test_long_legal_connection_identifier_and_same_version_content_change(self):
        key='d'*64
        D.C.configure(self.instance,'instance',key,self.source)
        D.C.configure(self.instance,'instance','demo',enabled=False)
        self.config['connections']['native'][0]['key']='instance.'+key
        self.deliver()
        b=D.bind_delivery(self.output,'instance.'+key,self.environment,project_root=self.project)
        self.assertEqual(b['connection']['key'],'instance.'+key)

    def test_no_rsi_selection_no_new_gate_and_no_effects(self):
        with patch('subprocess.Popen',side_effect=AssertionError('preparation does not execute')):
            r=self.deliver();self.bind()
        self.assertFalse(r['rsi_selected']);self.assertFalse((self.output/'rsi').exists())
        self.assertFalse(r['commands_executed']);self.assertFalse(r['local_bindings_included'])

if __name__=='__main__':unittest.main()
