"""Fresh/fixed stack ZIP evidence, relocated helpers and a real clean Python.

This is package/native engineering validation, not a model-built Harness or
WP10 acceptance. Optional fixed archive inputs are never repackaged in place.
"""

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
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SELECTED = {'qt-cmake': '2', 'python-environment': '1'}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GENERIC = load('stack_distribution_generic', ROOT / 'devtools/package_generic_release.py')
CAPABILITY = load('stack_distribution_capability', ROOT / 'devtools/package_capability_candidate.py')


def tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}


def extract(archive_path, destination):
    with zipfile.ZipFile(archive_path) as archive:
        paths = archive.namelist()
        if len(paths) != len(set(paths)) or any(Path(p).is_absolute() or '..' in Path(p).parts for p in paths):
            raise ValueError('candidate ZIP requires unique contained paths')
        archive.extractall(destination)


class StackEnvironmentDistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        evidence = os.environ.get('FOUNDRY_STACK_DISTRIBUTION_EVIDENCE_ROOT')
        if evidence:
            cls.root = Path(evidence).resolve()
            cls.root.mkdir(parents=True, exist_ok=False)
        else:
            temporary = tempfile.TemporaryDirectory(prefix='stack packaged 中文 ')
            cls.addClassCleanup(temporary.cleanup)
            cls.root = Path(temporary.name).resolve()
        cls.bundle = cls.root / 'unpacked generic'
        cls.capabilities = cls.root / 'unpacked capabilities'
        cls.archives = {}
        cls.package_records = []
        supplied = os.environ.get('FOUNDRY_STACK_TEST_ARCHIVES')
        archive_root = Path(supplied).resolve(strict=True) if supplied else cls.root
        for name, version in SELECTED.items():
            path = archive_root / (name + '-' + version + '.zip')
            if not supplied:
                cls.package_records.append(CAPABILITY.package_capability(
                    ROOT / 'examples/capability-adapters/packages' / name / version, version, path))
            cls.archives[name] = path
            extract(path, cls.capabilities / name)
        cls.generic_archive = archive_root / ('runtime.zip' if supplied and (archive_root / 'runtime.zip').is_file() else 'generic.zip')
        if not supplied:
            cls.package_records.append(GENERIC.package(cls.generic_archive))
        extract(cls.generic_archive, cls.bundle)
        cls.helpers = cls.bundle / 'examples/capability-adapters'
        cls.home, cls.tmp = cls.root / 'clean-home', cls.root / 'tmp'
        cls.home.mkdir()
        cls.tmp.mkdir()
        cls.env = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': str(cls.home), 'TMPDIR': str(cls.tmp),
                   'LANG': 'en_US.UTF-8', 'LC_ALL': 'en_US.UTF-8'}
        cls.venv = cls.root / 'clean venv'
        # The project .venv runs this test. A newly created isolated environment
        # supplies the receiver; no copying .venv, pip install or user site.
        result = subprocess.run([sys.executable, '-I', '-B', '-m', 'venv', '--without-pip', str(cls.venv)],
                                cwd=cls.root, env=cls.env, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        cls.python = cls.venv / 'bin/python'
        cls.identities = {'generic': hashlib.sha256(cls.generic_archive.read_bytes()).hexdigest(),
                          **{name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in cls.archives.items()}}
        (cls.root / 'archive-identities.json').write_text(json.dumps(cls.identities, indent=2) + '\n')

    def setUp(self):
        self.case = self.root / self._testMethodName
        self.case.mkdir()

    def invoke(self, *arguments, isolated_helpers=True, expected=0, environment=None):
        flags = ['-I', '-S', '-B'] if isolated_helpers else ['-I', '-B']
        result = subprocess.run([str(self.python), *flags, *map(str, arguments)], cwd=self.case,
                                env={**self.env, **(environment or {})}, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, expected, result.stdout + '\n' + result.stderr)
        return result

    def prepare_python(self, package=None):
        package = package or self.capabilities / 'python-environment'
        project = self.case / 'new project'
        project.mkdir()
        (project / 'selected_project.py').write_text('VALUE = "fresh input"\n')
        profile = self.case / 'profile.json'
        result = self.invoke(package / 'python_environment.py', 'bind', '--python', self.python,
            '--project-path', project, '--output', profile)
        self.assertFalse(json.loads(result.stdout)['executed'])
        config = self.case / 'prepare.json'
        version = self.invoke('-c', 'import platform; print(platform.python_version())').stdout.strip()
        config.write_text(json.dumps({'project_root': str(project), 'selections': [
            {'directory': str(package), 'version': '1', 'environment_profile': str(profile)}],
            'environment_bindings': {'project-python': {'path': str(self.python), 'observed_version': version}}}))
        materials = self.case / 'materials'
        prepared = self.invoke(self.helpers / 'prepare.py', '--config', config, '--output', materials)
        self.assertEqual(json.loads(prepared.stdout)['readiness'], 'READY')
        return package, project, profile, config, materials

    def test_fixed_zip_bytes_and_manifests_match_current_selected_source(self):
        with zipfile.ZipFile(self.generic_archive) as archive:
            expected = GENERIC.collect_files(ROOT)
            self.assertEqual({name: archive.read(name) for name in archive.namelist()}, expected)
            manifest = json.loads(archive.read('PACKAGE_MANIFEST.json'))
            self.assertEqual(set(manifest['files']), set(archive.namelist()))
            self.assertEqual(manifest['target_protocol_version'], '2.9')
            self.assertFalse(manifest['acceptance_claimed'])
            self.assertFalse(manifest['execution_authority_granted'])
        for name, version in SELECTED.items():
            with self.subTest(name=name), zipfile.ZipFile(self.archives[name]) as archive:
                expected = CAPABILITY.collect_capability(ROOT / 'examples/capability-adapters/packages' / name / version, version)
                self.assertEqual({p: archive.read(p) for p in archive.namelist()}, expected)
                manifest = json.loads(archive.read(CAPABILITY.MANIFEST))
                self.assertEqual(set(manifest['files']), set(archive.namelist()))
                self.assertEqual((manifest['name'], manifest['version']), (name, version))
                self.assertEqual(manifest['target_protocol_version'], '2.9')
                for field in ('runtime_verified', 'acceptance_claimed', 'execution_authority_granted'):
                    self.assertFalse(manifest[field])
        current = {'generic': hashlib.sha256(self.generic_archive.read_bytes()).hexdigest(),
                   **{name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in self.archives.items()}}
        self.assertEqual(current, self.identities)

    def test_packaged_helpers_help_and_shared_sources_load_without_development_modules(self):
        for name in ('prepare.py', 'consume.py', 'upgrade.py', 'stack_handoff.py'):
            self.assertIn('usage:', self.invoke(self.helpers / name, '--help').stdout)
        for name, entries in {'qt-cmake': ('qt_environment.py', 'qt_cmake.py', 'check_ctest.py'),
                              'python-environment': ('python_environment.py', 'check_python.py', 'python_probe.py', 'python_inspect.py', 'python_run.py')}.items():
            for entry in entries:
                with self.subTest(package=name, entry=entry):
                    self.assertIn('usage:', self.invoke(self.capabilities / name / entry, '--help').stdout)
        for common in ('stack_runtime.py', 'native_dependencies.py'):
            expected = (self.helpers / common).read_bytes()
            self.assertEqual(expected, (self.capabilities / 'qt-cmake' / common).read_bytes())
            self.assertEqual(expected, (self.capabilities / 'python-environment' / common).read_bytes())
        code = '''import importlib.util, pathlib, sys
root = pathlib.Path(sys.argv[1])
for name in ('prepare', 'consume', 'upgrade', 'stack_runtime', 'native_dependencies', 'stack_handoff'):
    spec = importlib.util.spec_from_file_location('packaged_'+name, root/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert pathlib.Path(module.__file__).resolve().is_relative_to(root)
assert not any('site-packages' in value for value in sys.path)
print('PACKAGED_HELPERS_ONLY')
'''
        self.assertIn('PACKAGED_HELPERS_ONLY', self.invoke('-c', code, self.helpers).stdout)

    def test_packaged_prepare_consume_upgrade_and_public_delivery_are_nonexecuting(self):
        package, project, profile, config, materials = self.prepare_python()
        before = tree(materials)
        captured = self.case / 'not-started'
        call = self.invoke(self.helpers / 'stack_handoff.py', 'call', '--materials', materials / 'materials.json',
            '--tool', 'python-environment', '--', 'run', '--cwd', project, '--report-dir', captured,
            '--module-name', 'selected_project', '--', '--profile', 'business-profile.json')
        proposed = json.loads(call.stdout)
        self.assertFalse(proposed['commands_executed'])
        self.assertFalse(proposed['acceptance_granted'])
        self.assertFalse(captured.exists())
        self.assertIn(str(package / 'python_environment.py'), proposed['argv'])
        self.assertIn(str(profile), proposed['argv'])
        self.assertEqual(proposed['argv'][-3:], ['--', '--profile', 'business-profile.json'])
        raw = self.invoke(self.helpers / 'consume.py', '--materials', materials / 'materials.json',
                          '--tool', 'python-environment', '--', '--help')
        self.assertFalse(json.loads(raw.stdout)['commands_executed'])
        upgraded = self.case / 'upgraded-materials'
        result = self.invoke(self.helpers / 'upgrade.py', '--previous', materials / 'materials.json',
                             '--config', config, '--output', upgraded)
        self.assertEqual(json.loads(result.stdout)['readiness'], 'READY')
        transition = json.loads((upgraded / 'transition.json').read_text())
        self.assertEqual(transition['packages'][0]['changes'], ['UNCHANGED'])
        for field in ('commands_executed', 'target_modified', 'acceptance_granted', 'authority_inherited', 'budget_modified'):
            self.assertFalse(transition[field])
        delivery = self.case / 'public delivery'
        result = self.invoke(self.helpers / 'stack_handoff.py', 'deliver', '--materials', materials / 'materials.json', '--output', delivery)
        manifest = json.loads(result.stdout)
        self.assertFalse(manifest['private_checkers_included'])
        self.assertFalse(manifest['local_bindings_included'])
        names = set(tree(delivery))
        self.assertFalse(any(name.endswith(('check_python.py', 'environment.json', 'expected.json')) for name in names))
        self.assertNotIn(str(profile).encode(), b''.join(tree(delivery).values()))
        self.assertEqual(tree(materials), before)
        self.assertTrue((delivery / 'capabilities/python-environment/1/python_environment.py').is_file())

    @unittest.skipUnless(sys.platform == 'darwin' and Path('/usr/bin/otool').is_file(), 'selected macOS native dependency observer')
    def test_public_delivery_rebinds_clean_venv_and_checks_new_input_with_packaged_native_helpers(self):
        _, project, _, _, materials = self.prepare_python()
        delivery = self.case / 'public target'
        self.invoke(self.helpers / 'stack_handoff.py', 'deliver', '--materials', materials / 'materials.json', '--output', delivery)
        package = delivery / 'capabilities/python-environment/1'
        before = tree(package)
        profile = self.case / 'target-profile.json'
        self.invoke(package / 'python_environment.py', 'bind', '--python', self.python, '--project-path', project, '--output', profile)
        source = self.case / 'new-probe-input.json'
        source.write_text(json.dumps({'schema_version': '1', 'modules': ['selected_project'],
            'decimal_values': ['1.25', '2.75', '-0.50'], 'sqlite_values': [11, 7, -3]}))
        actual_profile = self.case / 'target-native-profile.json'
        observation = self.invoke(package / 'python_environment.py', 'observe-native', '--profile', profile, '--input', source,
            '--otool', '/usr/bin/otool', '--report-dir', self.case / 'native-observation', '--adapt-loader-paths', '--output', actual_profile,
            isolated_helpers=False)
        observed = json.loads(observation.stdout)
        self.assertEqual(observed['status'], 'OBSERVED')
        self.assertFalse(observed['native_import_verified'])
        protected = self.case / 'protected'
        protected.mkdir()
        for name in ('check_python.py', 'python_probe.py', 'stack_runtime.py'):
            shutil.copy2(self.capabilities / 'python-environment' / name, protected / name)
        shutil.copy2(actual_profile, protected / 'profile.json')
        expected = protected / 'expected.json'
        expected.write_text(json.dumps({'schema_version': '1',
            'python': {'prefix': str(self.venv), 'require_venv': True, 'version_min': [3, 11]},
            'modules': {'selected_project': {'origin_root': str(project)}},
            'calculation': {'decimal_sum': '3.50', 'sqlite_count': 3, 'sqlite_sum': 15}}))
        report = self.case / 'check-capture'
        summary = self.case / 'summary.json'
        arguments = [protected / 'check_python.py', '--profile', protected / 'profile.json', '--input', source,
            '--expected', expected, '--cwd', self.case, '--report-dir', report]
        completed = self.invoke(*arguments, '--report', summary, isolated_helpers=False,
                                environment={'FOUNDRY_VERIFIER_ROOT': str(protected)})
        result = json.loads(completed.stdout)
        self.assertEqual(result['status'], 'PASS')
        self.assertTrue(result['observations_complete'])
        self.assertEqual(json.loads(summary.read_text())['status'], 'CHECKS_PASS')
        self.assertEqual(result['observation']['calculation'], {'decimal_sum': '3.50', 'sqlite_count': 3, 'sqlite_sum': 15})
        self.assertEqual(Path(result['observation']['python']['prefix']).resolve(), self.venv)
        records = tree(report)
        restored = self.invoke(*arguments, '--recover', '--report', self.case / 'recovered-summary.json', isolated_helpers=False,
                               environment={'FOUNDRY_VERIFIER_ROOT': str(protected)})
        self.assertEqual(json.loads(restored.stdout)['status'], 'PASS')
        self.assertEqual(tree(report), records)
        self.assertEqual(tree(package), before)
        # Captured argv uses extracted/delivered helpers and declared tools,
        # never a developer helper or earlier runs directory.
        command = json.loads((report / 'invocation.json').read_text())
        self.assertEqual(command['argv'][3], str(protected / 'python_probe.py'))
        self.assertNotIn(str(ROOT / 'examples'), json.dumps(command))
        self.assertNotIn(str(ROOT / 'src'), json.dumps(command))


if __name__ == '__main__':
    unittest.main()
