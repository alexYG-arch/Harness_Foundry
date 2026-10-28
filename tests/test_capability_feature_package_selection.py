"""Feature-level delivery and real local entry checks, not model acceptance."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from tests import test_capability_feature_inventory as fi
from tests import test_target_dashboard as td

S=fi.module('stack_handoff');CHECK=fi.module('check_capability_delivery')
VERSIONS={'qt-cmake':'3','python-environment':'2','data-summary':'2','doc-export':'2',
          'host-review':'2','local-dashboard':'5','text-count':'2','reference-notes':'2'}


class PackageSelectionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve()

    def config(self,name,version):
        return {'project_root':str(self.root),'integration_mode':'ALL',
                'selections':[{'directory':str(fi.BASE/'packages'/name/version),'version':version}],
                'environment_bindings':{k:{'path':sys.executable,'observed_version':'3.14.5'} for k in ('python','project-python','qt-python')}}

    def test_eight_new_versions_prepare_deliver_and_check_with_declared_environment_fixtures(self):
        # Qt dependency observations here are test fixtures, not real SDK proof.
        fake=self.root/'declared-sdk';fake.mkdir()
        for name,version in VERSIONS.items():
            with self.subTest(package=name):
                config=self.config(name,version)
                if name=='qt-cmake':
                    config['environment_bindings'].update({k:{'path':sys.executable,'observed_version':'3.31.12'} for k in ('cmake','ctest')})
                    config['environment_bindings']['qt-sdk']={'path':str(fake)}
                materials,_=fi.P.build_materials(config,self.root/(name+'-prep'))
                self.assertEqual(materials['preparation']['readiness'],'READY',materials['preparation']['diagnostics'])
                target=self.root/(name+'-target');manifest=S.public_delivery(materials,target)
                expected=self.root/(name+'-protected');shutil.copytree(target,expected)
                instructions=self.root/(name+'-AGENTS.md')
                instructions.write_text('\n'.join([*manifest['instruction_snippets'].values(),
                    *(f['entry']['tool'] for f in manifest['features'] if f.get('entry'))]) if name!='reference-notes' else 'Build-only reference.')
                self.assertEqual(CHECK.check(target,expected,[instructions])['status'],'CHECKS_PASS')
                self.assertFalse(any(p.name.startswith('check_') for p in target.rglob('*.py')))
                if name=='reference-notes':self.assertEqual(manifest['selections'],[])

    def test_text_entry_runs_from_public_copy_and_old_explicit_all_remains_valid(self):
        for version in ('1','2'):
            with self.subTest(version=version):
                m,_=fi.P.build_materials(self.config('text-count',version),self.root/('p'+version))
                target=self.root/('t'+version);S.public_delivery(m,target)
                binding=S.bind_delivery(target,{'python':{'path':sys.executable,'observed_version':'3.14.5'}},project_root=self.root)
                source=self.root/('input'+version);source.write_text('汉A🙂\n\nB\n')
                call=S.delivered_call(binding,'count-text',[str(source)])
                result=subprocess.run(call['argv'],capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(json.loads(result.stdout),{'characters':7,'nonempty_lines':2})


class TargetSubsetTests(unittest.TestCase):
    setUp=td.TargetDashboardTests.setUp
    save=td.TargetDashboardTests.save
    request=td.TargetDashboardTests.request
    def test_subset_runs_http_and_preserves_records_without_foundry_tool(self):
        package=fi.BASE/'packages/local-dashboard/5';sources=self.root/'sources';sources.mkdir()
        (sources/'brief.md').write_text('Observe only the target run.\n')
        config={'project_root':str(self.root),'source_root':str(sources),
                'selections':[{'directory':str(package),'version':'5','workpack_ids':['BUILD']}],
                'requirement_links':[{'capability':'local-dashboard','feature':'target-observer','source_id':'R','source_locator':'L1'}],
                'base_materials':{'request':{'requirement_ir':{'sources':[{'source_id':'R','path_or_uri':'brief.md'}]},'plan':{'workpacks':[{'workpack_id':'BUILD','inputs':[]}]}},
                'source_manifest':[{'source_id':'R','path':'brief.md'}]},
                'environment_bindings':{'python':{'path':sys.executable,'observed_version':'3.14.5'}}}
        m,_=fi.P.build_materials(config,self.root/'prep');target=self.root/'delivered';manifest=S.public_delivery(m,target)
        row=manifest['selections'][0];self.assertEqual([t['id'] for t in row['tools']],['target-dashboard'])
        root=target/row['root'];self.assertTrue((root/'dashboard.py').exists());self.assertFalse((root/'guide.md').exists())
        component={'name':row['name'],'version':row['version'],'features':row['features'],
                   'files':[{'path':p,'sha256':v['sha256']} for p,v in row['layout'].items() if v['kind']=='file']}
        cfg=self.root/'observer.json';cfg.write_text(json.dumps({'component':component,'runs':[{'id':'data','selection':self.selection,'record':str(self.record)}]}))
        spec=importlib.util.spec_from_file_location('real_subset_target',root/'target.py');host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)
        before={p:p.read_bytes() for p in (self.record,self.report,*self.paths.values())}
        with host.observer_from_config(cfg,poll_seconds=60,idle_seconds=0) as service:
            result=self.request(service)
            self.assertIn('business',json.dumps(result))
        self.assertEqual(before,{p:p.read_bytes() for p in before})
        (root/'dashboard.py').unlink()
        with self.assertRaises((OSError,ValueError)):host.observer_from_config(cfg)
