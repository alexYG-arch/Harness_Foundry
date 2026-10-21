"""WP07 package/receiver integration; synthetic review facts are not live-tool evidence."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import unittest
from types import SimpleNamespace

from harness_foundry_factory.verification_snapshot import snapshot_verifier
import test_capability_prepare as fixture

ROOT=Path(__file__).resolve().parents[1]

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

CONSUME=load('wp07_consume',ROOT/'examples/capability-adapters/consume.py')


class NoncodingIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.CapabilityPrepareTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root
        self.config=deepcopy(self.fixture.config)
        self.packages={}
        for name in ('doc-export','host-review'):
            directory=self.root/'external-packages'/name/'1'
            shutil.copytree(ROOT/'examples/capability-adapters/packages'/name/'1',directory)
            self.packages[name]=directory
        self.config['selections']=[{'directory':str(path),'version':'1','workpack_ids':['MAKE-TEXT']}
                                   for path in self.packages.values()]
        self.config['environment_bindings']['python']['observed_version']='.'.join(map(str,sys.version_info[:3]))

    def test_private_checkers_reach_protected_snapshot_not_production_and_keep_project_context(self):
        expected=self.root/'private-expectation.json'
        expected.write_text('{"private-marker":"WP07-INDEPENDENT-EXPECTED"}')
        self.config['base_materials']['preparation']['verifier_inputs']=[
            {'source':str(expected),'path':'project/expected.json'}]
        before=deepcopy(self.config)
        materials,files=CONSUME._prepare.build_materials(self.config,self.root/'new-materials')
        self.assertEqual(materials['preparation']['readiness'],'READY')
        self.assertEqual(materials['preparation']['advance_request'],{'advance_mode':'ONE_ATTEMPT'})
        self.assertNotIn('document_review',materials['request'])
        self.assertEqual(materials['scope']['max_attempts'],4)
        self.assertEqual(self.config,before)
        public=b'\n'.join(files.values())
        self.assertNotIn(b'WP07-INDEPENDENT-EXPECTED',public)
        private=[]
        for name,path in self.packages.items():
            descriptor=json.loads((path/'capability.json').read_text())
            for rel in descriptor.get('verification_files',[]):
                rel=rel if isinstance(rel,str) else rel['path']
                private.append(path/rel)
        reads=[Path(path).resolve() for path in materials['scope']['source_read_roots']]
        for item in private+[expected]:
            self.assertFalse(any(item.resolve()==root or item.resolve().is_relative_to(root) for root in reads))
        for row in materials['preparation']['verifier_inputs']:
            destination=self.fixture.verifier/row['path']
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(row['source'],destination)
        snap=snapshot_verifier(SimpleNamespace(database_path=self.root/'test-control.sqlite3'),
                               materials['request']['plan'],materials['scope'])
        runtime=Path(snap['runtime_root'])
        self.assertEqual((runtime/'project/expected.json').read_bytes(),expected.read_bytes())
        for row in materials['preparation']['verifier_inputs']:
            self.assertIn(row['path'],snap['files'])
            self.assertEqual((runtime/row['path']).read_bytes(),Path(row['source']).read_bytes())
        expected.write_text('Changed original expectation, not the protected copy.')
        self.assertIn('WP07-INDEPENDENT-EXPECTED',(runtime/'project/expected.json').read_text())
        self.assertFalse((self.root/'test-control.sqlite3').exists())

    def test_selected_public_entry_and_version_drift_are_checked_before_host_handoff(self):
        materials,_=CONSUME._prepare.build_materials(self.config,self.root/'new-materials')
        for name,path in self.packages.items():
            descriptor=json.loads((path/'capability.json').read_text())
            for tool in descriptor['tools']:
                call=CONSUME.prepare_call(materials,tool['id'],['--help'])
                self.assertEqual(call['argv'][0],sys.executable)
                self.assertIn(str(path/tool['path']),call['argv'])
                self.assertEqual(call['version'],'1')
                self.assertFalse(call['commands_executed'])
        descriptor=json.loads((self.packages['host-review']/'capability.json').read_text())
        guide=self.packages['host-review']/descriptor['materials'][0]
        guide.write_bytes(guide.read_bytes()+b'\nChanged selected workflow.\n')
        with self.assertRaisesRegex(ValueError,'selected capability files changed'):
            CONSUME.prepare_call(materials,descriptor['tools'][0]['id'],['--help'])

    def test_host_review_runs_with_generic_file_uris_and_all_indirect_snapshot_dependencies(self):
        import os
        import subprocess
        import test_capability_host_review as host_fixture
        from harness_foundry_factory.build_runtime import _local_argv
        host=host_fixture.CapabilityHostReviewTests()
        host.setUp()
        self.addCleanup(host.doCleanups)
        host.capture()
        base=self.config['base_materials']
        declared=[(host.expected_path,'project/expected.json',False)]
        declared += [(p,'project/'+str(p.relative_to(host.project)),True)
                     for p in host.project.rglob('*') if p.is_file()]
        declared += [(p,'snapshot/'+str(p.relative_to(host.snapshot)),False)
                     for p in host.snapshot.rglob('*') if p.is_file()]
        base['preparation']['verifier_inputs']=[{'source':str(p),'path':name,'shared':shared}
                                              for p,name,shared in declared]
        materials,_=CONSUME._prepare.build_materials(self.config,self.root/'new-materials')
        checker=next(row['path'] for row in materials['preparation']['verifier_inputs']
                     if row['path'].endswith('/check_review.py'))
        argv=['python','-I','-B','verifier://'+checker,
              '--task','verifier://project/task.json','--expectation','verifier://project/expected.json',
              '--snapshot','verifier://snapshot/snapshot.json','--outputs',str(host.outputs)]
        plan=deepcopy(materials['request']['plan'])
        plan['workpacks'][0]['verification'][0]['argv']=argv
        for row in materials['preparation']['verifier_inputs']:
            destination=self.fixture.verifier/row['path']
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(row['source'],destination)
        snapshot=snapshot_verifier(SimpleNamespace(database_path=self.root/'runtime.sqlite3'),plan,materials['scope'])
        runtime=Path(snapshot['runtime_root'])
        runtime_scope={**materials['scope'],'verification_root':str(runtime)}
        actual=_local_argv(argv,runtime_scope)
        # Original private files can change after preparation: actual runtime
        # must continue reading only the separately declared captured version.
        host.expected_path.write_text('{}')
        (host.snapshot/'snapshot.json').write_text('{}')
        before={p:p.read_bytes() for p in host.outputs.rglob('*') if p.is_file()}
        for index in range(2):
            reports=self.root/('reports-'+str(index));reports.mkdir()
            result=subprocess.run(actual,cwd=host.outputs,env={**host.env,
                'FOUNDRY_VERIFIER_ROOT':str(runtime),'FOUNDRY_REPORT_DIR':str(reports),
                'FOUNDRY_CASE_ID':'WP07-HOST','FOUNDRY_COMMAND_ID':'ENGINEERING-'+str(index)},
                capture_output=True,text=True,timeout=15)
            report=json.loads((reports/'summary.json').read_text())
            self.assertEqual(result.returncode,0,(result.stderr,report))
            self.assertEqual(report['status'],'CHECKS_PASS')
            self.assertEqual(report['command_id'],'ENGINEERING-'+str(index))
        self.assertEqual(before,{p:p.read_bytes() for p in before})
        self.assertFalse((self.root/'runtime.sqlite3').exists())
