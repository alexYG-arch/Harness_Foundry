"""Relocated WP09 candidate checks, not release or second-device acceptance.

Only new engineering inputs are executed. Qt checks exercise help/import paths,
not an SDK build; DATA expected values are authored independently of its output.
The optional archive inputs recheck the exact already-fixed candidates.
"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / 'examples/capability-adapters/packages'
NAMES = ('data-summary', 'qt-cmake', 'doc-export', 'host-review', 'local-dashboard')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PACKAGER = load('wp09_capability_packager', ROOT / 'devtools/package_capability_candidate.py')
GENERIC = load('wp09_generic_packager', ROOT / 'devtools/package_generic_release.py')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob('*') if path.is_file() and '__pycache__' not in path.parts}


def declared(descriptor):
    return {'capability.json', *descriptor.get('materials', []),
            *descriptor.get('runtime_files', []),
            *(row['path'] for row in descriptor.get('tools', [])),
            *(row if isinstance(row, str) else row['path']
              for row in descriptor.get('verification_files', []))}


def extract(candidate, destination):
    with zipfile.ZipFile(candidate) as archive:
        for item in archive.infolist():
            path = Path(item.filename)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('test candidate must use contained paths')
        archive.extractall(destination)


class CapabilityDistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix='foundry-capability-distribution-')
        cls.addClassCleanup(temporary.cleanup)
        cls.root = Path(temporary.name).resolve()
        cls.bundle = cls.root / 'relocated generic'
        cls.capabilities = cls.root / 'relocated capabilities'
        cls.archives = {}
        supplied = os.environ.get('FOUNDRY_CAPABILITY_TEST_ARCHIVES')
        for name in NAMES:
            archive = (Path(supplied).resolve(strict=True) / (name + '-1.zip')
                       if supplied else cls.root / (name + '-1.zip'))
            if not supplied:
                PACKAGER.package_capability(PACKAGES / name / '1', '1', archive)
            cls.archives[name] = archive
            extract(archive, cls.capabilities / name)
        supplied_generic = os.environ.get('FOUNDRY_R3_TEST_ARCHIVE')
        cls.generic_archive = (Path(supplied_generic).resolve(strict=True)
                               if supplied_generic else cls.root / 'generic.zip')
        if not supplied_generic:
            GENERIC.package(cls.generic_archive)
        extract(cls.generic_archive, cls.bundle)
        cls.helpers = cls.bundle / 'examples/capability-adapters'
        cls.env = {key: value for key, value in os.environ.items()
                   if key not in ('PYTHONPATH', 'PYTHONHOME') and not key.startswith('FOUNDRY_')}

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='case-', dir=self.root)
        self.addCleanup(temporary.cleanup)
        self.case = Path(temporary.name)

    def python(self, *args, expected=0):
        result = subprocess.run([sys.executable, '-I', '-S', '-B', *map(str, args)],
                                cwd=self.case, env=self.env, capture_output=True,
                                text=True, timeout=45)
        self.assertEqual(result.returncode, expected, result.stdout + '\n' + result.stderr)
        return result

    def test_five_exact_candidate_archives_cover_declared_files_and_claim_no_acceptance(self):
        for name in NAMES:
            with self.subTest(capability=name):
                package = self.capabilities / name
                descriptor = json.loads((package / 'capability.json').read_text())
                manifest = json.loads((package / PACKAGER.MANIFEST).read_text())
                expected = declared(descriptor) | {'LICENSE', PACKAGER.MANIFEST}
                with zipfile.ZipFile(self.archives[name]) as archive:
                    self.assertEqual(set(archive.namelist()), expected)
                    self.assertEqual(len(archive.namelist()), len(expected))
                    # Fixed input ZIPs must match the final selected source,
                    # rather than proving only that some prior ZIP can run.
                    self.assertEqual({path: archive.read(path) for path in archive.namelist()},
                                     PACKAGER.collect_capability(PACKAGES / name / '1', '1'))
                self.assertEqual(set(manifest['files']), expected)
                self.assertEqual((manifest['name'], manifest['version']), (name, '1'))
                self.assertEqual(manifest['target_protocol_version'], '2.9')
                for key in ('acceptance_claimed', 'execution_authority_granted', 'runtime_verified'):
                    self.assertIs(manifest[key], False)
                self.assertEqual(manifest['verification_files'], descriptor.get('verification_files', []))
                self.assertEqual(manifest['environment'], descriptor.get('environment', []))

    def test_unlisted_private_files_are_not_collected_and_preflight_has_no_side_effects(self):
        source = self.case / 'source'
        shutil.copytree(PACKAGES / 'data-summary/1', source)
        (source / 'project-secret.txt').write_text('PRIVATE-PROJECT-EXPECTATION')
        (source / 'private').mkdir()
        (source / 'private/expected.json').write_text('{"unlisted":"business answer"}')
        before = tree(self.case)
        with patch('subprocess.Popen', side_effect=AssertionError('packaging must not dispatch')):
            files = PACKAGER.collect_capability(source, '1')
            result = PACKAGER.package_capability(source, '1')
        self.assertNotIn('project-secret.txt', files)
        self.assertNotIn('private/expected.json', files)
        self.assertNotIn(b'PRIVATE-PROJECT-EXPECTATION', b'\n'.join(files.values()))
        self.assertFalse(result['writes_performed'])
        self.assertFalse(result['release_accepted'])
        self.assertEqual(tree(self.case), before)

    def test_wrong_version_and_existing_destination_preserve_old_bytes(self):
        package = PACKAGES / 'data-summary/1'
        absent = self.case / 'not-created.zip'
        with self.assertRaises(ValueError):
            PACKAGER.package_capability(package, 'wrong-version', absent)
        self.assertFalse(absent.exists())
        destination = self.case / 'old.zip'
        destination.write_bytes(b'old accepted bytes are not a new candidate')
        before = tree(self.case)
        with self.assertRaises(ValueError):
            PACKAGER.package_capability(package, '1', destination)
        self.assertEqual(tree(self.case), before)

    def test_same_selected_bytes_produce_identical_archives(self):
        for name in NAMES:
            with self.subTest(capability=name):
                first, second = self.case / (name + '-a.zip'), self.case / (name + '-b.zip')
                left = PACKAGER.package_capability(PACKAGES / name / '1', '1', first)
                right = PACKAGER.package_capability(PACKAGES / name / '1', '1', second)
                self.assertEqual(first.read_bytes(), second.read_bytes())
                self.assertEqual(left['archive_sha256'], digest(first))
                self.assertEqual(left['archive_sha256'], right['archive_sha256'])
                self.assertFalse(left['release_accepted'])
                self.assertFalse(right['runtime_verified'])

    def test_relocated_generic_helpers_import_and_help_without_checkout_modules(self):
        expected = ('prepare.py', 'environment.py', 'consume.py', 'upgrade.py', 'foundry_dashboard.py')
        for filename in expected:
            self.assertTrue((self.helpers / filename).is_file(), filename)
        for filename in ('prepare.py', 'consume.py', 'upgrade.py', 'foundry_dashboard.py'):
            with self.subTest(entry=filename):
                self.assertIn('usage:', self.python(self.helpers / filename, '--help').stdout)
        # Import the actual relocated reader and its dependencies, allowing only
        # the extracted src directory and the interpreter standard library.
        code = '''import importlib, pathlib, sys
root = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(root/'src'))
module = importlib.import_module('harness_foundry_factory.build_observation')
assert pathlib.Path(module.__file__).resolve().is_relative_to(root)
for name, value in list(sys.modules.items()):
    if name.startswith('harness_foundry_factory'):
        assert pathlib.Path(value.__file__).resolve().is_relative_to(root)
'''
        self.python('-c', code, self.bundle)
        readme = (self.helpers / 'README.md').read_text()
        self.assertIn('consume.py', readme)
        self.assertIn('does **not** execute', readme)

    def test_relocated_declared_doc_host_and_dashboard_entrypoints_have_complete_dependencies(self):
        before = tree(self.capabilities)
        for name in ('doc-export', 'host-review', 'local-dashboard'):
            package = self.capabilities / name
            descriptor = json.loads((package / 'capability.json').read_text())
            for relative in declared(descriptor):
                self.assertTrue((package / relative).is_file(), (name, relative))
            entries = [row['path'] for row in descriptor['tools']]
            entries += [row if isinstance(row, str) else row['path']
                        for row in descriptor.get('verification_files', [])]
            for entry in entries:
                with self.subTest(capability=name, entry=entry):
                    self.assertIn('usage:', self.python(package / entry, '--help').stdout)
        dashboard = self.capabilities / 'local-dashboard'
        for relative in ('target.py', 'dashboard.py', 'target-guide.md',
                         'web/index.html', 'web/app.js', 'web/style.css'):
            self.assertTrue((dashboard / relative).is_file())
        self.assertEqual(tree(self.capabilities), before)

    def test_relocated_qt_help_requires_no_sdk_and_does_not_claim_native_build(self):
        package = self.capabilities / 'qt-cmake'
        before = tree(self.case)
        for entry in ('qt_cmake.py', 'check_ctest.py'):
            self.assertIn('usage:', self.python(package / entry, '--help').stdout)
        self.assertEqual(tree(self.case), before)
        manifest = json.loads((package / PACKAGER.MANIFEST).read_text())
        self.assertFalse(manifest['runtime_verified'])
        self.assertIn('qt-sdk', {item['id'] for item in manifest['environment']})

    def test_relocated_prepare_consume_data_cli_and_independent_checker(self):
        package = self.capabilities / 'data-summary'
        before_package = tree(package)
        input_path = self.case / 'new-input.csv'
        config = self.case / 'aggregation.json'
        output = self.case / 'actual.json'
        expected = self.case / 'independent-expected.json'
        input_path.write_text('item,team,amount\na,north,1.25\nb,north,1.75\n')
        config.write_text(json.dumps({'schema_version': '1.0', 'group_by': ['team'], 'filters': [],
            'rows': {'key': ['item'], 'duplicates': 'error', 'missing': 'error'},
            'metrics': [{'id': 'total', 'op': 'sum', 'column': 'amount', 'unit': 'count',
                         'scale': 2, 'rounding': 'HALF_EVEN'}]}))
        # Independent full oracle: 5/4 + 7/4 = 3, with both row contributions.
        oracle = {'schema_version': '1.0',
            'summary': {'input_rows': 2, 'included_rows': 2, 'excluded_rows': 0},
            'groups': [{'key': {'team': 'north'}, 'metrics': {'total': {
                'value': '3.00', 'exact': {'numerator': '3', 'denominator': '1'}, 'unit': 'count'}}}],
            'rows': [
                {'record': 1, 'group': {'team': 'north'}, 'key': {'item': 'a'},
                 'contributions': {'total': {'numerator': '5', 'denominator': '4'}}},
                {'record': 2, 'group': {'team': 'north'}, 'key': {'item': 'b'},
                 'contributions': {'total': {'numerator': '7', 'denominator': '4'}}}],
            'excluded': []}
        expected.write_text(json.dumps(oracle))
        preparation = self.case / 'prepare.json'
        preparation.write_text(json.dumps({'project_root': str(self.case),
            'selections': [{'directory': str(package), 'version': '1'}],
            'environment_bindings': {'python': {'path': sys.executable,
                'observed_version': platform.python_version()}}}))
        materials_dir = self.case / 'materials'
        prepared = json.loads(self.python(self.helpers / 'prepare.py', '--config', preparation,
                                          '--output', materials_dir).stdout)
        self.assertEqual(prepared['readiness'], 'READY')
        materials = json.loads((materials_dir / 'materials.json').read_text())
        self.assertFalse(materials['preparation']['commands_executed'])
        self.assertFalse(materials['preparation']['runtime_verified'])
        self.assertTrue(any(row['source'] == str(package / 'check_summary.py')
                            for row in materials['preparation']['verifier_inputs']))
        self.assertFalse(any(path.name == 'check_summary.py' for path in (materials_dir / 'sources').rglob('*')))
        handoff = json.loads(self.python(self.helpers / 'consume.py', '--materials',
            materials_dir / 'materials.json', '--tool', 'summarize-csv', '--',
            '--input', input_path, '--config', config, '--output', output).stdout)
        self.assertFalse(handoff['commands_executed'])
        self.assertFalse(handoff['acceptance_granted'])
        self.assertFalse(output.exists())
        self.assertEqual(handoff['argv'][0], sys.executable)
        self.assertIn(str(package / 'summarize_csv.py'), handoff['argv'])
        self.assertNotIn(str(package / 'check_summary.py'), handoff['argv'])
        executed = subprocess.run(handoff['argv'], cwd=self.case, env=self.env,
                                  capture_output=True, text=True, timeout=30)
        self.assertEqual(executed.returncode, 0, executed.stderr)
        report = self.case / 'report.json'
        self.python(package / 'check_summary.py', '--input', input_path, '--config', config,
                    '--actual', output, '--expected', expected, '--report', report)
        checked = json.loads(report.read_text())
        self.assertEqual(checked['status'], 'CHECKS_PASS')
        self.assertEqual(checked['checks'], [{'id': 'data-summary', 'status': 'PASS'}])
        self.assertEqual(checked['observation_binding']['files'], {
            'input': digest(input_path), 'config': digest(config),
            'actual': digest(output), 'expected': digest(expected)})
        # Keep the accepted engineering report and output; a separate wrong
        # result must fail the same independent checker, without producer replay.
        old_report, old_output = report.read_bytes(), output.read_bytes()
        bad = json.loads(old_output)
        bad['groups'][0]['metrics']['total']['value'] = '4.00'
        incorrect = self.case / 'incorrect.json'
        incorrect.write_text(json.dumps(bad))
        failed_report = self.case / 'failed-report.json'
        self.python(package / 'check_summary.py', '--input', input_path, '--config', config,
                    '--actual', incorrect, '--expected', expected, '--report', failed_report, expected=1)
        failed = json.loads(failed_report.read_text())
        self.assertEqual(failed['failure_kind'], 'ASSERTION')
        self.assertEqual(failed['checks'], [{'id': 'data-summary', 'status': 'FAIL'}])
        self.assertEqual(report.read_bytes(), old_report)
        self.assertEqual(output.read_bytes(), old_output)
        self.assertEqual(tree(package), before_package)
        # Exercise the actual relocated upgrade writer, not only --help. A
        # complete same-version selection produces new materials and an honest
        # UNCHANGED diff without applying anything or replaying DATA commands.
        old_materials = tree(materials_dir)
        upgraded_dir = self.case / 'next-materials'
        upgrade = json.loads(self.python(self.helpers / 'upgrade.py', '--previous',
            materials_dir / 'materials.json', '--config', preparation,
            '--output', upgraded_dir).stdout)
        self.assertEqual(upgrade['readiness'], 'READY')
        self.assertFalse(upgrade['commands_executed'])
        transition = json.loads((upgraded_dir / 'transition.json').read_text())
        self.assertEqual(transition['previous_selection_check']['status'], 'MATCH')
        self.assertEqual([(row['name'], row['changes']) for row in transition['packages']],
                         [('data-summary', ['UNCHANGED'])])
        for key in ('commands_executed', 'target_modified', 'physical_files_removed',
                    'acceptance_granted', 'authority_inherited', 'budget_modified'):
            self.assertIs(transition[key], False)
        next_call = json.loads(self.python(self.helpers / 'consume.py', '--materials',
            upgraded_dir / 'materials.json', '--tool', 'summarize-csv', '--', '--help').stdout)
        self.assertFalse(next_call['commands_executed'])
        self.assertIn(str(package / 'summarize_csv.py'), next_call['argv'])
        self.assertEqual(tree(materials_dir), old_materials)
        self.assertEqual(report.read_bytes(), old_report)
        self.assertEqual(output.read_bytes(), old_output)
        self.assertEqual(tree(package), before_package)


if __name__ == '__main__':
    unittest.main()
