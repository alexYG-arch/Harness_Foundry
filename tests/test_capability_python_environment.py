"""Real isolated CPython/venv probes; not a real-model Harness acceptance."""

from copy import deepcopy
import hashlib
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
PACKAGE = ROOT / 'examples/capability-adapters/packages/python-environment/1'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TOOL = load('test_python_env_tool', PACKAGE / 'python_environment.py')
CHECK = load('test_python_env_check', PACKAGE / 'check_python.py')


class CapabilityPythonEnvironmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.TemporaryDirectory(prefix='capability-python-clean-')
        cls.venv = Path(cls.base.name).resolve() / '全新 venv'
        subprocess.run([sys.executable, '-I', '-B', '-m', 'venv', '--without-pip', str(cls.venv)],
                       check=True, capture_output=True, text=True, timeout=30)
        cls.python = cls.venv / 'bin/python'

    @classmethod
    def tearDownClass(cls):
        cls.base.cleanup()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='capability-python-project-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.package = self.root / 'delivered'
        shutil.copytree(PACKAGE, self.package)
        self.project = self.root / '项目 module'
        self.project.mkdir()
        (self.project / 'chosen_module.py').write_text('__version__ = "fixture-1"\n', encoding='utf-8')
        self.profile = TOOL.bind(str(self.python), [str(self.project)])
        self.profile_path = self.root / 'profile.json'
        self.profile_path.write_text(json.dumps(self.profile), encoding='utf-8')
        self.input = self.root / 'probe-input.json'
        self.input.write_text(json.dumps({'schema_version': '1', 'modules': ['json', 'chosen_module'],
                                          'decimal_values': ['0.10', '0.20'], 'sqlite_values': [2, 3]}))
        self.expected = self.root / 'expected.json'
        self.oracle = {'schema_version': '1', 'python': {'prefix': str(self.venv), 'require_venv': True, 'version_min': [3, 11]},
                       'modules': {'chosen_module': {'origin_root': str(self.project)}},
                       'calculation': {'decimal_sum': '0.30', 'sqlite_count': 2, 'sqlite_sum': 5}}
        self.expected.write_text(json.dumps(self.oracle))

    def command(self, *argv, environment=None):
        env = {key: value for key, value in os.environ.items() if not key.startswith('FOUNDRY_')}
        env.update(environment or {})
        return subprocess.run([str(self.python), '-I', '-B', *map(str, argv)], cwd=self.root,
                              env=env, capture_output=True, text=True, timeout=20)

    def probe(self, name='probe'):
        result = self.command(self.package / 'python_environment.py', 'probe', '--profile', self.profile_path,
                              '--input', self.input, '--cwd', self.root, '--report-dir', self.root / name)
        return result, self.root / name

    def check(self, name='check', package=None, profile=None, expected=None, *extra, environment=None):
        package = package or self.package
        return self.command(package / 'check_python.py', '--profile', profile or self.profile_path,
            '--input', self.input, '--expected', expected or self.expected, '--cwd', self.root,
            '--report-dir', self.root / name, *extra, environment=environment)

    def test_manifest_runtime_complete_and_private_checker_not_public(self):
        descriptor = json.loads((PACKAGE / 'capability.json').read_text())
        self.assertEqual(descriptor['tools'][0]['interpreter'], 'project-python')
        public = descriptor['materials'] + descriptor['runtime_files'] + [row['path'] for row in descriptor['tools']]
        self.assertNotIn('check_python.py', public)
        self.assertEqual((PACKAGE / 'stack_runtime.py').read_bytes(),
                         (ROOT / 'examples/capability-adapters/stack_runtime.py').read_bytes())
        self.assertTrue(all((PACKAGE / name).is_file() for name in public))
        self.assertIn({'path': 'python_probe.py', 'shared': True}, descriptor['verification_files'])

    def test_bind_is_pure_and_keeps_venv_and_parent_alias(self):
        alias = self.root / 'venv alias'
        alias.symlink_to(self.venv, target_is_directory=True)
        with patch.object(TOOL.runtime.subprocess, 'Popen') as launched:
            profile = TOOL.bind(str(alias / 'bin/python'), [str(self.project)])
        launched.assert_not_called()
        self.assertEqual(profile['tools']['project-python'], str(self.python))
        self.assertNotEqual(profile['tools']['project-python'], str(self.python.resolve()))
        self.assertIn(str(self.venv / 'pyvenv.cfg'), [row['path'] for row in profile['observations']])

    def test_real_clean_venv_import_native_calculation_and_independent_check(self):
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        verdict = json.loads(result.stdout)
        self.assertEqual(verdict['status'], 'PASS')
        observation = verdict['observation']
        self.assertEqual(Path(observation['python']['prefix']).resolve(), self.venv)
        self.assertNotEqual(observation['python']['prefix'], observation['python']['base_prefix'])
        self.assertTrue(observation['modules']['_sqlite3']['native_extension'])
        self.assertTrue(observation['modules']['_decimal']['native_extension'])
        self.assertEqual(observation['calculation'], self.oracle['calculation'])
        self.assertEqual(observation['modules']['chosen_module']['origin'], str(self.project / 'chosen_module.py'))

    def test_selected_venv_site_packages_remain_visible_under_isolated_mode(self):
        location = self.command('-c', 'import sysconfig; print(sysconfig.get_path("purelib"))')
        self.assertEqual(location.returncode, 0, location.stderr)
        module = Path(location.stdout.strip()) / 'declared_venv_fixture.py'
        module.write_text('__version__ = "local-fixture"\n')
        self.addCleanup(module.unlink)
        specification = json.loads(self.input.read_text())
        specification['modules'].append('declared_venv_fixture')
        self.input.write_text(json.dumps(specification))
        self.oracle['modules']['declared_venv_fixture'] = {'origin_root': str(self.venv)}
        self.expected.write_text(json.dumps(self.oracle))
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(json.loads(result.stdout)['observation']['python']['no_site'])

    def test_missing_module_is_environment_error_not_product_assertion(self):
        specification = json.loads(self.input.read_text())
        specification['modules'].append('definitely_missing_foundry_module_71240')
        self.input.write_text(json.dumps(specification))
        result = self.check()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        verdict = json.loads(result.stdout)
        self.assertEqual(verdict['status'], 'ERROR')
        self.assertEqual(verdict['observation']['errors'][0]['error_type'], 'ModuleNotFoundError')

    def test_wrong_expected_result_or_prefix_is_assertion(self):
        self.oracle['calculation']['sqlite_sum'] = 99
        self.oracle['python']['prefix'] = str(self.root)
        self.expected.write_text(json.dumps(self.oracle))
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'ASSERTION')

    def test_complete_capture_recovery_does_not_import_again_or_overwrite(self):
        counter = self.root / 'import-count.txt'
        (self.project / 'chosen_module.py').write_text(
            'from pathlib import Path\np=Path(' + repr(str(counter)) + ')\np.write_text(p.read_text()+"x" if p.exists() else "x")\n')
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        before = {p.name: p.read_bytes() for p in (self.root / 'check').iterdir()}
        second = self.check()
        self.assertEqual(second.returncode, 2)
        recovered = self.check('check', None, None, None, '--recover')
        self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
        self.assertEqual(counter.read_text(), 'x')
        self.assertEqual({p.name: p.read_bytes() for p in (self.root / 'check').iterdir()}, before)

    def test_producer_capture_cannot_be_used_as_protected_checker_recovery(self):
        result, directory = self.probe('producer')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        restored = self.check('producer', None, None, None, '--recover')
        self.assertEqual(restored.returncode, 2)
        self.assertIn('not producer', restored.stdout)

    def test_incomplete_capture_does_not_replay(self):
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        observation = self.root / 'check/observation.json'
        before = (self.root / 'check/invocation.json').read_bytes()
        observation.unlink()
        result = self.check('check', None, None, None, '--recover')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(observation.exists())
        self.assertEqual((self.root / 'check/invocation.json').read_bytes(), before)

    def test_same_checker_bytes_can_recover_after_legal_directory_move(self):
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        original = (self.root / 'check/invocation.json').read_bytes()
        moved = self.root / 'moved-protected-copy'
        shutil.copytree(self.package, moved)
        recovered = self.check('check', moved, None, None, '--recover')
        self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
        self.assertEqual((self.root / 'check/invocation.json').read_bytes(), original)

    def test_checker_rejects_undeclared_operation_without_dispatch(self):
        self.profile['operations'] = ['run']
        self.profile_path.write_text(json.dumps(self.profile))
        result = self.check()
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root / 'check').exists())

    def test_protected_checker_loads_protected_public_fixture(self):
        protected = self.root / 'protected'
        shutil.copytree(self.package, protected)
        shutil.copy2(self.profile_path, protected / 'profile.json')
        shutil.copy2(self.expected, protected / 'expected.json')
        (self.package / 'python_probe.py').write_text('raise RuntimeError("product side altered")\n')
        result = self.check('protected-check', protected, protected / 'profile.json', protected / 'expected.json',
                            environment={'FOUNDRY_VERIFIER_ROOT': str(protected)})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = json.loads((self.root / 'protected-check/invocation.json').read_text())
        self.assertEqual(record['argv'][3], str(protected / 'python_probe.py'))
        wrong = self.check('outside-profile', protected, self.profile_path, protected / 'expected.json',
                           environment={'FOUNDRY_VERIFIER_ROOT': str(protected)})
        self.assertEqual(wrong.returncode, 2)
        self.assertFalse((self.root / 'outside-profile').exists())

    def test_module_change_invalidates_reuse_while_new_business_input_does_not(self):
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        receiver = {'host': 'engineering-fixture', 'network': 'none', 'writes': [str(self.root)]}
        report['receiver'] = receiver
        # Import success alone does not observe all loaded-library identities.
        self.assertFalse(report['observations_complete'])
        self.assertEqual(TOOL.runtime.reuse_probe(self.profile, report, receiver)['decision'], 'UNKNOWN')
        # Isolate known-file comparison here. The native integration suite
        # supplies real complete selected native dependency observations.
        report['observations_complete'] = True
        self.assertEqual(TOOL.runtime.reuse_probe(self.profile, report, receiver)['decision'], 'REUSE')
        (self.root / 'new-business-input.json').write_text('{"new": true}')
        self.assertEqual(TOOL.runtime.reuse_probe(self.profile, report, receiver)['decision'], 'REUSE')
        (self.project / 'chosen_module.py').write_text('__version__ = "fixture-2"\n')
        self.assertEqual(TOOL.runtime.reuse_probe(self.profile, report, receiver)['decision'], 'REPROBE')
        recovered = self.check('check', None, None, None, '--recover')
        self.assertEqual(recovered.returncode, 2)
        self.assertIn('module source changed', recovered.stdout)

    def test_namespace_import_works_but_unobserved_directory_contents_are_not_reused(self):
        (self.project / 'declared_namespace').mkdir()
        specification = json.loads(self.input.read_text())
        specification['modules'].append('declared_namespace')
        self.input.write_text(json.dumps(specification))
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        receiver = {'host': 'engineering-fixture'}
        report['receiver'] = receiver
        self.assertIsNone(report['observation']['modules']['declared_namespace']['origin'])
        self.assertEqual(TOOL.runtime.reuse_probe(self.profile, report, receiver)['decision'], 'UNKNOWN')

    def test_actual_project_module_new_input_and_explicit_path(self):
        (self.project / 'chosen_module.py').write_text(
            'import json, sys\nfrom decimal import Decimal\nprint(json.dumps({"sum": str(sum((Decimal(x) for x in sys.argv[1:]), Decimal(0))), "prefix": sys.prefix}))\n')
        result = self.command(self.package / 'python_environment.py', 'run', '--profile', self.profile_path,
            '--cwd', self.root, '--report-dir', self.root / 'task', '--module-name', 'chosen_module', '--', '1.25', '2.75')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = json.loads((self.root / 'task/stdout.txt').read_text())
        self.assertEqual(output['sum'], '4.00')
        self.assertEqual(Path(output['prefix']).resolve(), self.venv)
        self.profile['extensions']['python']['project_paths'] = []
        self.profile_path.write_text(json.dumps(self.profile))
        missing = self.command(self.package / 'python_environment.py', 'run', '--profile', self.profile_path,
            '--cwd', self.project, '--report-dir', self.root / 'no-implicit-cwd', '--module-name', 'chosen_module')
        self.assertEqual(missing.returncode, 2)
        self.assertIn('No module named chosen_module', (self.root / 'no-implicit-cwd/stderr.txt').read_text())

    def test_declared_module_binding_changes_require_new_profile(self):
        self.profile = TOOL.bind(str(self.python), [str(self.project)], [str(self.project / 'chosen_module.py')])
        self.profile_path.write_text(json.dumps(self.profile))
        (self.project / 'chosen_module.py').write_text('__version__ = "changed"\n')
        result, directory = self.probe()
        self.assertEqual(result.returncode, 2)
        self.assertFalse(directory.exists())
        fresh = TOOL.bind(str(self.python), [str(self.project)], [str(self.project / 'chosen_module.py')])
        old_bytes = self.profile_path.read_bytes()
        repaired_path = self.root / 'profile-repaired.json'
        repaired_path.write_text(json.dumps(fresh))
        result = self.check('repaired', None, repaired_path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.profile_path.read_bytes(), old_bytes)

    @unittest.skipUnless(sys.platform == 'darwin' and Path('/usr/bin/otool').is_file(), 'selected macOS otool observation')
    def test_native_observation_uses_selected_module_dependencies_and_then_actual_probe(self):
        before = deepcopy(self.profile)
        report_dir = self.root / 'native-observation'
        observed = TOOL.observe_native(self.profile, self.input, report_dir, otool='/usr/bin/otool', adapt_loader_paths=True)
        self.assertEqual(observed['status'], 'OBSERVED', observed.get('issues'))
        self.assertFalse(observed['native_import_verified'])
        self.assertEqual(self.profile, before)
        self.assertTrue(observed['operations'])
        candidate = observed['profile']
        self.assertEqual(candidate['tools']['project-python'], str(self.python))
        self.assertEqual(candidate['tools']['python-otool'], '/usr/bin/otool')
        self.assertTrue(candidate['extensions']['python']['native_observation']['complete'])
        self.assertTrue(candidate['extensions']['python']['native_observation']['native_files'])
        self.assertEqual(candidate['extensions']['path_aliases'], observed['aliases'])
        self.assertTrue(all(path in candidate['read_paths'] for path in observed['read_path_proposals']))
        for alias in observed['aliases']:
            self.assertEqual(alias['status'], 'OBSERVED')
            self.assertEqual(TOOL.runtime.alias_observation(alias['path']), alias)
            self.assertIn(alias['read_parent'], candidate['read_paths'])
        profile_path = self.root / 'native-profile.json'
        profile_path.write_text(json.dumps(candidate))
        completed = self.check('native-check', None, profile_path)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        verdict = json.loads(completed.stdout)
        self.assertTrue(verdict['observations_complete'])
        receiver = {'host': 'local-engineering-venv', 'scope': str(self.root)}
        verdict['receiver'] = receiver
        self.assertEqual(TOOL.runtime.reuse_probe(candidate, verdict, receiver)['decision'], 'REUSE')
        retained = {str(p.relative_to(report_dir)): p.read_bytes() for p in report_dir.rglob('*') if p.is_file()}
        with self.assertRaises(FileExistsError):
            TOOL.observe_native(self.profile, self.input, report_dir, otool='/usr/bin/otool', adapt_loader_paths=True)
        self.assertEqual({str(p.relative_to(report_dir)): p.read_bytes() for p in report_dir.rglob('*') if p.is_file()}, retained)

    def test_native_observation_requires_explicit_available_tool_without_fallback(self):
        with patch.object(TOOL.runtime.subprocess, 'Popen') as launched:
            with self.assertRaisesRegex(ValueError, 'otool executable'):
                TOOL.observe_native(self.profile, self.input, self.root / 'missing-tool', otool=str(self.root / 'absent'))
        launched.assert_not_called()
        self.assertFalse((self.root / 'missing-tool').exists())

    def test_old_summary_does_not_trigger_probe_and_report_binding_is_checked(self):
        summary = self.root / 'existing-summary.json'
        summary.write_text('{"old":true}')
        result = self.check('should-not-start', None, None, None, '--report', str(summary))
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root / 'should-not-start').exists())
        self.assertEqual(summary.read_text(), '{"old":true}')
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        changed = json.loads(self.input.read_text())
        changed['sqlite_values'] = [100, 200]
        self.input.write_text(json.dumps(changed))
        result = self.check('check', None, None, None, '--recover')
        self.assertEqual(result.returncode, 2)
        self.assertIn('differs from', result.stdout)


if __name__ == '__main__':
    unittest.main()
