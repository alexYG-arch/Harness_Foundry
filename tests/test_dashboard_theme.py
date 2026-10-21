"""H05 engineering verification; no native PiP appearance or human verdict."""
from copy import deepcopy
import http.client
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
import test_capability_dashboard as dashboard_fixture
import test_target_dashboard as target_fixture
import test_target_dashboard_integration as upgrade_fixture
import test_foundry_dashboard_host as foundry_fixture

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'examples/capability-adapters/packages/local-dashboard/2'

def load(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

D=load('theme_dashboard',PACKAGE/'dashboard.py')
T=load('theme_target',PACKAGE/'target.py')

class DashboardThemeTests(unittest.TestCase):
    def fixture(self, cls):
        value=cls(); value.setUp(); self.addCleanup(value.doCleanups); return value

    def get(self, service, route):
        url=urlsplit(service.url)
        connection=http.client.HTTPConnection(url.hostname,url.port,timeout=3)
        try:
            connection.request('GET',url.path+route)
            response=connection.getresponse()
            self.assertEqual(response.status,200)
            return json.loads(response.read())
        finally:
            connection.close()

    def test_default_and_three_preferences_share_cache_and_do_not_dispatch(self):
        for theme in (None,'system','light','dark'):
            with self.subTest(theme=theme):
                source=dashboard_fixture.Source()
                kwargs={} if theme is None else {'theme':theme}
                observer=D.Observer({'one':{'selection':dashboard_fixture.identity(),'reader':source.read}},poll_seconds=60,idle_seconds=0,**kwargs)
                self.addCleanup(observer.stop)
                with patch('subprocess.run',side_effect=AssertionError('no business')), patch('subprocess.Popen',side_effect=AssertionError('no dispatch')):
                    observer.start()
                    url=urlsplit(observer.url)
                    for _ in range(2):
                        self.assertEqual(self.get(observer,'api/runs')['presentation'],{'theme':theme or 'system'})
                        snap=self.get(observer,'api/snapshot?run=one')
                        self.assertEqual(snap['presentation'],{'theme':theme or 'system'})
                        self.assertEqual(snap['business']['budget'],{'attempts_consumed':2,'attempts_remaining':3})
                    self.assertEqual(source.calls,1)
                    source.error=ValueError('source unavailable')
                    observer._collect('one')
                    self.assertEqual(observer.snapshot('one')['presentation'],{'theme':theme or 'system'})
                    observer.stop()
                    self.assertTrue(observer.wait(1))
                    with self.assertRaises(OSError): socket.create_connection((url.hostname,url.port),timeout=.2)

    def test_invalid_preference_is_local_config_diagnostic_before_reader_runs(self):
        for value in ('',None,{},True,'auto','LIGHT'):
            with self.subTest(value=value):
                source=dashboard_fixture.Source()
                with self.assertRaisesRegex(ValueError,'INVALID_OBSERVER_THEME'):
                    D.Observer({'one':{'selection':dashboard_fixture.identity(),'reader':source.read}},theme=value)
                self.assertEqual(source.calls,0)

    def test_non_object_config_keeps_existing_diagnostic(self):
        fixture=self.fixture(target_fixture.TargetDashboardTests)
        path=fixture.root/'invalid-observer.json'
        path.write_text('[]')
        with self.assertRaisesRegex(ValueError,'INVALID_OBSERVER_CONFIG'):
            D.observer_from_config(path)

    def test_standalone_and_target_config_use_external_theme_without_writes(self):
        fixture=self.fixture(target_fixture.TargetDashboardTests)
        config=fixture.root/'simple.json'
        display=fixture.root/'projection.json'
        display.write_text(json.dumps(dashboard_fixture.projection()))
        config.write_text(json.dumps({'theme':'light','runs':[{'id':'one','selection':dashboard_fixture.identity(),'source':display.name}]}))
        before=config.read_bytes()
        with D.observer_from_config(config,poll_seconds=60) as observer:
            self.assertEqual(observer.snapshot('one')['presentation'],{'theme':'light'})
        self.assertEqual(config.read_bytes(),before)
        binding=upgrade_fixture.component_binding(PACKAGE)
        config.write_text(json.dumps({'theme':'dark','component':binding,'runs':[{'id':'one','selection':fixture.selection,'record':str(fixture.record)}]}))
        before=fixture.all_bytes()
        with T.observer_from_config(config,poll_seconds=60) as observer:
            snap=observer.snapshot('one')
            self.assertEqual(snap['presentation'],{'theme':'dark'})
            self.assertEqual(snap['business']['items'][0]['state'],'PASS')
        self.assertEqual(fixture.all_bytes(),before)

    def test_foundry_adapter_preserves_legacy_and_selects_new_theme_interface(self):
        fixture=self.fixture(foundry_fixture.FoundryDashboardHostTests)
        with foundry_fixture.HOST.observer_from_config(fixture.config,poll_seconds=60) as old:
            self.assertNotIn('presentation',old.snapshot('one'))
        fixture.config_data['theme']='dark'; fixture.save()
        with self.assertRaisesRegex(ValueError,'SELECTED_DASHBOARD_THEME_UNSUPPORTED'):
            foundry_fixture.HOST.observer_from_config(fixture.config)
        selected=fixture.f.root/'dashboard-2'
        shutil.copytree(PACKAGE,selected)
        consume=foundry_fixture.HOST._load(ROOT/'examples/capability-adapters/consume.py','theme_consume')
        materials,_=consume._prepare.build_materials({'project_root':str(fixture.f.workspace),'selections':[{'directory':str(selected),'version':'2'}],
            'environment_bindings':{'python':{'path':sys.executable,'observed_version':'.'.join(map(str,sys.version_info[:3]))}}},fixture.f.root/'materials-new')
        (fixture.f.root/'materials.json').write_text(json.dumps(materials))
        db_before=fixture.f.store.database_path.read_bytes()
        with foundry_fixture.HOST.observer_from_config(fixture.config,poll_seconds=60) as observer:
            self.assertEqual(observer.snapshot('one')['presentation'],{'theme':'dark'})
        self.assertEqual(fixture.f.store.database_path.read_bytes(),db_before)
        self.assertFalse(fixture.f.runner.invocations)

    def test_real_package_upgrade_preserves_external_preference_mapping_and_evidence(self):
        fixture=self.fixture(upgrade_fixture.TargetDashboardIntegrationTests)
        fixture.delivery()
        for path in (fixture.config,fixture.baseline/'dashboard.json'):
            data=json.loads(path.read_text()); data['theme']='dark'; upgrade_fixture.save(path,data)
        # Use actual new package bytes, not the pre-existing synthetic version fixture.
        destination=fixture.proposed/'components/local-dashboard'
        shutil.rmtree(destination); shutil.copytree(PACKAGE,destination)
        proposed=json.loads(fixture.config.read_text()); proposed['component']=upgrade_fixture.component_binding(destination)
        upgrade_fixture.save(fixture.proposed/'dashboard.json',proposed)
        before=json.loads(fixture.config.read_text()); before.pop('component')
        baseline_bytes=upgrade_fixture.tree(fixture.baseline)
        paths=['components/local-dashboard/'+name for name in upgrade_fixture.tree(fixture.component)]
        report,candidate=fixture.merge(paths+['dashboard.json','records/display.json'])
        fixture.apply(report,candidate)
        current=json.loads(fixture.config.read_text()); current.pop('component')
        self.assertEqual(current,before)
        self.assertEqual(fixture.record_path.read_bytes(),fixture.custom_record)
        self.assertEqual({path:path.read_bytes() for path in fixture.bound_evidence},fixture.bound_evidence)
        self.assertEqual(upgrade_fixture.tree(fixture.baseline),baseline_bytes)
        selected=load('theme_upgraded_target',fixture.component/'target.py')
        with selected.observer_from_config(fixture.config,poll_seconds=60) as observer:
            snap=observer.snapshot('original-task')
            self.assertEqual(snap['component']['version'],'2')
            self.assertEqual(snap['presentation'],{'theme':'dark'})
            self.assertEqual(snap['business']['title'],'项目自定义状态标题')
            self.assertEqual(snap['business']['items'][0]['state'],'PASS')

    def test_actual_frontend_shared_theme_with_dom_fixture(self):
        node=shutil.which('node')
        if node is None: self.skipTest('Node unavailable: DOM fixture not run; browser proof remains separate')
        run=subprocess.run([node,str(ROOT/'tests/fixtures/dashboard_theme_dom.js'),str(PACKAGE/'web/app.js')],capture_output=True,text=True,timeout=10)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.assertIn('4 configurations',run.stdout)

if __name__=='__main__': unittest.main()
