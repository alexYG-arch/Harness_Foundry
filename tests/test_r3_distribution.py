"""Actual relocated package checks; no real model, grant, native sandbox or release."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('r3_packager', ROOT/'devtools/package_generic_release.py')
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


class R3DistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='foundry-r3-distribution-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name).resolve()
        cls.bundle = cls.root/'relocated'
        supplied = os.environ.get('FOUNDRY_R3_TEST_ARCHIVE')
        candidate = Path(supplied).resolve(strict=True) if supplied else cls.root/'candidate.zip'
        if not supplied:
            packager.package(candidate)
        # The optional path tests the exact already-fixed engineering archive.
        # It is test input only, never a receiver or production bypass.
        with zipfile.ZipFile(candidate) as archive:
            for item in archive.infolist():
                path = Path(item.filename)
                if path.is_absolute() or '..' in path.parts:
                    raise ValueError('test archive must use contained paths')
            archive.extractall(cls.bundle)
        cls.example = cls.bundle/'examples/harness-composition-upgrade'
        cls.env = {k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME')}

    def python(self, *args, data=None, expected=0):
        result = subprocess.run([sys.executable, '-I', '-S', '-B', *map(str,args)],
            cwd=self.root, env=self.env, input=data, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, expected, result.stdout+'\n'+result.stderr)
        return result

    def test_static_description_has_separate_roles_without_loading_runtime(self):
        catalog = self.bundle/'src/harness_foundry_factory/build_capabilities.py'
        described = json.loads(self.python(catalog).stdout)
        self.assertEqual(described['target_protocol_version'], '2.9')
        self.assertTrue(described['descriptive_only'])
        self.assertFalse(described['execution_authority_granted'])
        self.assertFalse(described['acceptance_claimed'])
        ids = {item['capability_id'] for item in described['capabilities']}
        self.assertTrue({'sqlite','local-service','remote-http','test-credentials','product-copy','business-workflows'} <= ids)
        for item in described['capabilities']:
            for field in ('factory_knowledge','factory_execution','target_delivery','acceptance_boundary','input_shape'):
                self.assertTrue(item[field], (item['capability_id'],field))
            for module in item['implementation_modules']:
                self.assertTrue((self.bundle/'src/harness_foundry_factory'/f'{module}.py').is_file())
            for dependency in item['dependencies']:
                if dependency.startswith('examples/'):
                    self.assertTrue((self.bundle/dependency).is_file(), dependency)
        unknown = json.loads(self.python(catalog,'--id','project-specific-unlisted-need',expected=1).stdout)
        self.assertFalse(unknown['requirement_disallowed'])
        self.python('-c', f'import runpy, sys; runpy.run_path({str(catalog)!r}); '
                    'assert not any(x.startswith("harness_foundry_factory") for x in sys.modules)')
        generated = self.python(catalog,'--markdown').stdout
        self.assertIn(generated.strip(), (self.bundle/'docs/CAPABILITY_REFERENCE.md').read_text())

    def test_all_actual_packaged_modules_import_and_cli_runs_without_development_path(self):
        # Enumerate the extracted artifact, not the packager's MODULES tuple.
        code = '''import importlib, pathlib, sys
root = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(root/'src'))
for path in (root/'src/harness_foundry_factory').glob('*.py'):
    if path.stem != '__init__':
        module = importlib.import_module('harness_foundry_factory.'+path.stem)
        assert pathlib.Path(module.__file__).resolve().is_relative_to(root)
assert not any('site-packages' in str(getattr(v, '__file__', '')) for v in sys.modules.values())
'''
        self.python('-c',code,self.bundle)
        result=json.loads(self.python(self.bundle/'tools/hffactory.py','version','--json').stdout)
        self.assertEqual(result['product_route'],'GENERIC_REVIEWED_BUILD')
        self.assertFalse(result['legacy_specification_required'])
        for relative in ('helpers/merge.py','helpers/apply.py','integration/mechanism_requests.py',
                         'integration/business_requests.py','integration/prepare_host_evidence.py',
                         'verifier/check_business.py','verifier/check_mechanisms.py','verifier/check_mechanism_resource.py'):
            self.python(self.example/relative,'--help')

    def test_relocated_doc_merge_apply_and_actual_export_check(self):
        mechanism = self.example/'mechanisms/doc'
        merge_output=self.root/'merge-candidate'
        result=self.python(self.example/'helpers/merge.py','--inputs',mechanism/'scenarios/upgrade-1/inputs.json',
                           '--output',merge_output,expected=2)
        self.assertIn('CONFLICT',result.stdout)
        target=self.root/'doc-target'
        shutil.copytree(mechanism/'custom/current',target)
        self.python(self.example/'helpers/apply.py','--manifest',mechanism/'scenarios/upgrade-1/apply.json',
                    '--target',target,'--result','outputs/apply.json')
        check=json.loads(self.python(self.example/'verifier/check_mechanisms.py','--kind','doc','--target',target,
                         '--expected',self.example/'verifier/expectations/doc-v2.json').stdout)
        self.assertEqual(check['result'],'PASS')
        self.assertEqual(check['scope'],'offline-cli-exported-content')
        self.assertEqual((target/'USER_NOTES.md').read_bytes(),(mechanism/'custom/current/USER_NOTES.md').read_bytes())
        self.assertFalse((target/'report.md').exists())

    def test_relocated_api_all_versions_and_business_input_dependency_closure(self):
        for stage,relative in (('v1','custom/current'),('v2','expected/after-v2'),('v3','expected/after-v3')):
            result=json.loads(self.python(self.example/'verifier/check_mechanisms.py','--kind','api',
                '--target',self.example/'mechanisms/api'/relative,
                '--expected',self.example/f'verifier/expectations/api-{stage}.json').stdout)
            self.assertEqual(result['result'],'PASS')
            self.assertEqual(result['live_http'],'NOT_RUN')
        for group in ('prd-design','data-reasoning','market-research'):
            directory=self.example/'business'/group
            manifest=json.loads((directory/'manifest.json').read_text())
            refs=manifest['inputs']+[manifest[k] for k in ('task','expected','counterexamples','upgrade','tool_preparation')]
            refs += list(manifest['workflows'].values())
            if 'live_task' in manifest:
                refs.append(manifest['live_task'])
            for ref in refs:
                path=(directory/ref).resolve()
                self.assertTrue(path.is_relative_to(self.example) and path.is_file(),(group,ref))
            source_index=directory/'inputs/sources.json'
            if source_index.is_file():
                for source in json.loads(source_index.read_text())['sources']:
                    self.assertTrue((directory/'inputs'/source['filename']).is_file())
            self.assertEqual(manifest['status'],'EXECUTION_NOT_RUN')
            for name in manifest['outputs']:
                self.assertFalse((directory/name).exists())
        for path in self.bundle.rglob('*.md'):
            for link in re.findall(r'\]\(([^)]+)\)',path.read_text()):
                if '://' in link or link.startswith('#'):
                    continue
                destination=(path.parent/link.split('#',1)[0]).resolve()
                self.assertTrue(destination.is_relative_to(self.bundle) and destination.is_file(),(path,link))

    def test_relocated_business_generators_compile_using_packaged_workflows_and_expectations(self):
        requirement=self.root/'business-build.md'
        requirement.write_text('Package test only. Produce selected business outputs from declared fixed inputs.\n')
        for group in ('prd-design','data-reasoning','market-research'):
            bindings={'program_id':'PACKAGE-'+group.upper(), 'requirement_path':str(requirement),
                'workspace_root':str(self.root/group/'target'), 'verification_root':str(self.root/group/'verifier'),
                'resource_root':str(self.root/group/'resources'), 'group_root':str(self.example/'business'/group),
                'python_read_roots':[], 'python_executable':sys.executable, 'codex_executable':sys.executable,
                'model':'TEST-NOT-EXECUTED', 'max_attempts':3, 'max_task_attempts':3,
                'command_timeout_seconds':900, 'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}
            bindfile=self.root/(group+'-bindings.json'); bindfile.write_text(json.dumps(bindings))
            output=self.root/(group+'-materials.json')
            self.python(self.example/'integration/business_requests.py','--group',group,'--version','v1',
                        '--phase','automatic','--bindings',bindfile,'--output',output)
            materials=json.loads(output.read_text())
            self.assertEqual(materials['preparation']['status'],'MATERIALS_ONLY_NOT_APPROVED')
            self.assertTrue(Path(materials['preparation']['workflow_path']).is_relative_to(self.bundle))
            for row in materials['preparation']['verifier_inputs']:
                self.assertTrue(Path(row['source']).is_relative_to(self.bundle) and Path(row['source']).is_file())
            result=json.loads(self.python(self.bundle/'tools/hffactory.py','compile-build-plan','--request','-',
                              '--json',data=json.dumps(materials['request'])).stdout)
            self.assertEqual(result['status'],'PLAN_COMPILED_NOT_AUTHORIZED')
            self.assertFalse(Path(bindings['workspace_root']).exists())


if __name__ == '__main__':
    unittest.main()
