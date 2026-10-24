"""External preparation contracts with temporary files, never Programs or models.

The real tool and checker below are tiny test-owned processes. They do not
qualify a business workflow, native receiver, or capability dispatch guard.
"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

from tests.python_fixture import python_fixture_header
from unittest.mock import patch

from harness_foundry_factory.acceptance_contract import validate_acceptance_contracts
from harness_foundry_factory.build_plan import compile_build_plan
from harness_foundry_factory.build_runtime import _local_argv, _validate_scope
from harness_foundry_factory.source_intake import load_local_sources, validate_requirement_source_bindings
from harness_foundry_factory.verification_snapshot import snapshot_verifier


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / 'examples/capability-adapters/prepare.py'
SPEC = importlib.util.spec_from_file_location('tested_capability_prepare', ENTRY)
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)


class CapabilityPrepareTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='capability-prepare-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        self.source = self.root / 'original-sources'
        self.source.mkdir()
        self.brief = b'# Test-owned contract\r\nPreserve all input text in a local report.\r\n'
        (self.source / 'brief.md').write_bytes(self.brief)
        self.verifier = self.root / 'verifier'
        self.verifier.mkdir()
        (self.verifier / 'check.py').write_text('print("TEST CHECKER ONLY")\n')
        self.output = self.root / 'new-materials'
        self.package = self.project / 'packages' / 'echo-v1'
        self.package.mkdir(parents=True)
        (self.package / 'guide.md').write_bytes(b'# Echo method\r\nUse the selected CLI.\r\n')
        (self.package / 'tool.py').write_text(
            'import json, sys\n'
            'print(json.dumps({"version":"1.0", "text":sys.argv[1]}))\n')
        (self.package / 'expected.json').write_text('{"marker":"INDEPENDENT-ONLY-812"}\n')
        self.descriptor = {
            'name': 'echo', 'version': '1.0', 'usage': 'both',
            'inputs': ['UTF-8 text'], 'outputs': ['JSON text'],
            'materials': ['guide.md'],
            'tools': [{'id': 'echo-tool', 'path': 'tool.py', 'interpreter': 'python'}],
            'environment': [{'id': 'python', 'kind': 'executable'}],
            'verification_files': ['expected.json'],
        }
        self.save_descriptor()
        source = {'source_id': 'PROJECT-BRIEF', 'path_or_uri': 'brief.md', 'loaded_completely': True}
        basis = {'source_id': 'PROJECT-BRIEF', 'source_locator': 'L1-L2'}
        request = {
            'requirement_ir': {
                'program_id': 'PREPARATION-TEST', 'revision': 1,
                'target': {'id': 'TEXT', 'mission': 'A test-owned local text tool',
                           'scope': ['Preserve the declared input'], 'non_goals': ['Real business acceptance']},
                'sources': [source],
                'atoms': [{'atom_id': 'PRESERVE', 'source_id': 'PROJECT-BRIEF',
                           'source_locator': 'L2', 'text_or_lossless_paraphrase': 'Preserve all input text.'}],
                'acceptance_cases': [{'case_id': 'TEXT-CHECK', 'atom_ids': ['PRESERVE'],
                                      'description': 'The output preserves input text.', 'acceptance_contract': basis}],
                'negative_cases': [],
            },
            'plan': {'schema_version': '1.2', 'plan_id': 'TEXT-PLAN', 'revision': 1,
                     'requirement_revision': 1, 'workpacks': [{
                         'workpack_id': 'MAKE-TEXT', 'job_id': 'TEXT', 'executor': 'LOCAL',
                         'goal': 'Use the declared temporary test tool', 'depends_on': [],
                         'atom_ids': ['PRESERVE'], 'inputs': [{'kind': 'SOURCE', 'id': 'PROJECT-BRIEF'}],
                         'local_argv': ['python', '-c', 'print("not executed by preparation")'],
                         'artifacts': [{'artifact_id': 'TEXT-RESULT', 'path': 'outputs/text.json'}],
                         'verification': [{'case_id': 'TEXT-CHECK',
                                           'argv': ['python', '-I', '-B', 'verifier://check.py'],
                                           'artifact_ids': ['TEXT-RESULT'], 'resource_profile_ref': 'local'}],
                     }]},
            'document_review': {'test-only': 'old context must not be inherited'},
            'expected_revision': 99,
        }
        scope = {
            'workspace_root': str(self.root / 'target'), 'verification_root': str(self.verifier),
            'source_read_roots': [], 'task_write_roots': {'MAKE-TEXT': ['outputs']},
            'executables': {'python': sys.executable}, 'codex_executable': sys.executable,
            'model': None, 'allow_model_service': False, 'max_attempts': 4, 'max_task_attempts': 3,
            'command_timeout_seconds': 30, 'expires_at': '2099-01-01T00:00:00Z',
            'verification_resources': {'schema_version': '1.0', 'root': str(self.root / 'resources'),
                'checker_files': [], 'profiles': {'local': {
                    'writable_areas': ['scratch', 'report-staging'], 'network': {'mode': 'NONE'},
                    'services': [], 'result_protocol': 'STRUCTURED_V1', 'required_checks': ['text'],
                    'report_files': ['summary.json'], 'retention': {'success': 'REPORTS_ONLY', 'failure_days': 7},
                }}},
        }
        self.config = {
            'project_root': str(self.project), 'source_root': str(self.source),
            'selections': [{'directory': 'packages/echo-v1', 'version': '1.0', 'workpack_ids': ['MAKE-TEXT']}],
            'environment_bindings': {'python': {'path': sys.executable}},
            'base_materials': {'request': request, 'scope': scope,
                'source_manifest': [{'source_id': 'PROJECT-BRIEF', 'path': 'brief.md'}],
                'preparation': {'advance_request': {'advance_mode': 'ONE_ATTEMPT'},
                                'next': 'Return to the original host after this attempt.', 'verifier_inputs': []}},
        }

    def save_descriptor(self, package=None, descriptor=None):
        (package or self.package).joinpath('capability.json').write_text(
            json.dumps(descriptor or self.descriptor, ensure_ascii=False), encoding='utf-8')

    def tree(self):
        return {str(path.relative_to(self.root)): ('link', str(path.readlink())) if path.is_symlink()
                else ('file', path.read_bytes()) if path.is_file() else ('directory',)
                for path in self.root.rglob('*')}

    def materialize(self):
        materials = PREPARE.write_materials(self.config, self.output)
        for row in materials['preparation']['verifier_inputs']:
            destination = self.verifier / row['path']
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(row['source'], destination)
        return materials

    def append_package_config(self, materials, *, tool_id='other-tool'):
        other = self.project / 'packages/other'
        shutil.copytree(self.package, other)
        descriptor = {**deepcopy(self.descriptor), 'name': 'other'}
        descriptor['tools'][0].update(id=tool_id, interpreter='other-python')
        descriptor['environment'] = [{'id': 'other-python', 'kind': 'executable'}]
        self.save_descriptor(other, descriptor)
        return {
            'project_root': str(self.project), 'base_materials': materials,
            'source_root': materials['preparation']['source_root'],
            'selections': [{'directory': str(other), 'version': '1.0', 'workpack_ids': ['MAKE-TEXT']}],
            'environment_bindings': {'other-python': {'path': sys.executable}},
        }

    def test_pure_api_preserves_originals_and_never_dispatches_or_creates_state(self):
        before, config = self.tree(), deepcopy(self.config)
        with patch('subprocess.Popen', side_effect=AssertionError('preparation must not dispatch')):
            materials, files = PREPARE.build_materials(self.config, self.output)
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.config, config)
        self.assertTrue(files)
        self.assertEqual(materials['preparation']['readiness'], 'READY')
        self.assertEqual(materials['preparation']['status'], 'MATERIALS_ONLY_NOT_APPROVED')
        for key in ('commands_executed', 'runtime_verified', 'protected_copy_created'):
            self.assertIs(materials['preparation'][key], False)
        self.assertNotIn('document_review', materials['request'])
        self.assertNotIn('expected_revision', materials['request'])
        self.assertEqual(materials['preparation']['advance_request'], {'advance_mode': 'ONE_ATTEMPT'})

    def test_materialized_sources_compile_and_scope_resolves_without_a_program(self):
        materials = self.materialize()
        request, scope = materials['request'], materials['scope']
        snapshot = load_local_sources(Path(materials['preparation']['source_root']), materials['source_manifest'])
        validate_requirement_source_bindings(request['requirement_ir'], snapshot)
        contracts = validate_acceptance_contracts(request['requirement_ir'], snapshot=snapshot, required=True)
        self.assertIn('Preserve all input text', contracts['TEXT-CHECK']['text'])
        self.assertEqual(compile_build_plan(request['requirement_ir'], request['plan'])['status'],
                         'PLAN_COMPILED_NOT_AUTHORIZED')
        _validate_scope(SimpleNamespace(database_path=self.root / 'control.sqlite3'), request['plan'], scope)
        inputs = request['plan']['workpacks'][0]['inputs']
        self.assertIn({'kind': 'SOURCE', 'id': 'CAP-echo-VERSION'}, inputs)
        self.assertIn({'kind': 'SOURCE', 'id': 'CAP-echo-M1'}, inputs)
        changes = materials['preparation']['changes']
        self.assertEqual(set(changes['sources_added']), {'CAP-echo-M1', 'CAP-echo-VERSION'})
        self.assertIn({'kind': 'SOURCE', 'id': 'CAP-echo-VERSION'}, changes['workpack_inputs_added']['MAKE-TEXT'])
        self.assertEqual(changes['executables_added'], {})
        self.assertIn(str(self.package / 'tool.py'), changes['read_roots_added'])
        self.assertEqual((self.output / 'sources/brief.md').read_bytes(), self.brief)
        version = json.loads((self.output / 'sources/capabilities/echo/selected-version.json').read_text())
        self.assertEqual(version['version'], '1.0')
        self.assertNotIn('expected.json', {row['path'] for row in version['files']})
        self.assertNotIn('INDEPENDENT-ONLY-812', json.dumps(snapshot))
        self.assertFalse(any((self.root / name).exists() for name in ('target', 'control.sqlite3', 'resources')))

    def test_temporary_tool_consumes_selected_binding_and_retains_interpreter_alias(self):
        alias = self.project / 'python-alias'
        alias.symlink_to(sys.executable)
        self.descriptor['tools'][0]['interpreter_args'] = ['-I', '-B']
        self.save_descriptor()
        self.config['base_materials']['scope']['executables']['python'] = str(alias)
        self.config['environment_bindings']['python']['path'] = str(alias)
        materials, _ = PREPARE.build_materials(self.config, self.output)
        self.assertEqual(PREPARE.check_selection(materials)['status'], 'MATCH')
        prefix = materials['tool_bindings']['echo-tool']['argv_prefix']
        argv = _local_argv([*prefix, 'new input: 中文'], materials['scope'])
        self.assertEqual(argv[0], str(alias))
        self.assertEqual(argv[1:3], ['-I', '-B'])
        self.assertIn(str(self.package / 'tool.py'), argv)
        completed = subprocess.run(argv, cwd=self.root, capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), {'version': '1.0', 'text': 'new input: 中文'})
        self.assertFalse(self.output.exists())

    def test_new_selected_version_changes_real_tool_without_replacing_old_package(self):
        old_materials, _ = PREPARE.build_materials(self.config, self.output)
        old_bytes = (self.package / 'tool.py').read_bytes()
        newer = self.project / 'packages/echo-v2'
        shutil.copytree(self.package, newer)
        descriptor = {**deepcopy(self.descriptor), 'version': '2.0'}
        self.save_descriptor(newer, descriptor)
        (newer / 'tool.py').write_bytes(old_bytes.replace(b'"1.0"', b'"2.0"'))
        config = deepcopy(self.config)
        config['selections'][0].update(directory='packages/echo-v2', version='2.0')
        materials, _ = PREPARE.build_materials(config, self.output)
        argv = _local_argv([*materials['tool_bindings']['echo-tool']['argv_prefix'], 'another input'], materials['scope'])
        result = subprocess.run(argv, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'version': '2.0', 'text': 'another input'})
        self.assertEqual((self.package / 'tool.py').read_bytes(), old_bytes)
        self.assertEqual(PREPARE.check_selection(old_materials)['status'], 'MATCH')
        self.assertEqual(PREPARE.check_selection(materials)['status'], 'MATCH')

    def test_append_to_prepared_materials_preserves_previous_consumers_and_identity(self):
        first = self.materialize()
        config = self.append_package_config(first)
        before, original = self.tree(), deepcopy(first)
        output = self.root / 'combined-materials'
        combined, files = PREPARE.build_materials(config, output)
        self.assertEqual(self.tree(), before)
        self.assertEqual(first, original)
        self.assertEqual(combined['preparation']['readiness'], 'READY')
        self.assertEqual({row['name'] for row in combined['preparation']['selections']}, {'echo', 'other'})
        self.assertIn(first['preparation']['selections'][0], combined['preparation']['selections'])
        self.assertEqual(set(combined['tool_bindings']), {'echo-tool', 'other-tool'})
        self.assertEqual(combined['tool_bindings']['echo-tool'], first['tool_bindings']['echo-tool'])
        environment = combined['preparation']['environment']
        self.assertEqual(set(environment['bindings']), {'python', 'other-python'})
        self.assertEqual(environment['bindings']['python'], first['preparation']['environment']['bindings']['python'])
        for diagnostic in first['preparation']['environment']['diagnostics']:
            self.assertIn(diagnostic, environment['diagnostics'])
        for diagnostic in first['preparation']['diagnostics']:
            self.assertIn(diagnostic, combined['preparation']['diagnostics'])
        self.assertEqual({row['id'] for row in environment['diagnostics']}, {'python', 'other-python'})
        for row in first['source_manifest']:
            self.assertIn(row, combined['source_manifest'])
            self.assertEqual(files['sources/' + row['path']],
                             (Path(first['preparation']['source_root']) / row['path']).read_bytes())
        self.assertEqual(PREPARE.check_selection(combined)['status'], 'MATCH')
        (self.package / 'tool.py').write_text('raise RuntimeError("identity check must not execute")\n')
        changed = PREPARE.check_selection(combined)
        self.assertEqual(changed['status'], 'CHANGED')
        self.assertEqual(changed['changes'], [{'name': 'echo', 'version': '1.0', 'path': 'tool.py'}])
        self.assertFalse(changed['commands_executed'])
        self.assertFalse(output.exists())

    def test_appended_materials_retain_native_tool_and_runtime_read_fragment(self):
        (self.package / 'helper.txt').write_text('OLD NATIVE DEPENDENCY')
        (self.package / 'tool.py').write_text(
            python_fixture_header() + 'from pathlib import Path\n'
            'print(Path(__file__).with_name("helper.txt").read_text())\n')
        (self.package / 'tool.py').chmod(0o700)
        self.descriptor['tools'][0].pop('interpreter')
        self.descriptor['environment'] = []
        self.descriptor['runtime_files'] = ['helper.txt']
        self.save_descriptor()
        first = self.materialize()
        config = self.append_package_config(first)
        combined, _ = PREPARE.build_materials(config, self.root / 'combined-materials')
        fragment = combined['scope_fragment']
        for path in first['scope_fragment']['source_read_roots']:
            self.assertIn(path, fragment['source_read_roots'])
            self.assertNotIn(path, combined['preparation']['changes']['read_roots_added'])
        self.assertEqual(fragment['executables']['echo-tool'], str(self.package / 'tool.py'))
        argv = _local_argv(combined['tool_bindings']['echo-tool']['argv_prefix'], fragment)
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), 'OLD NATIVE DEPENDENCY')

    def test_appending_ready_package_does_not_erase_previous_incomplete_diagnostics(self):
        self.config['environment_bindings'] = {}
        first = self.materialize()
        self.assertEqual(first['preparation']['readiness'], 'INCOMPLETE')
        config = self.append_package_config(first)
        combined, _ = PREPARE.build_materials(config, self.root / 'combined-materials')
        self.assertEqual(combined['preparation']['readiness'], 'INCOMPLETE')
        self.assertEqual(combined['preparation']['environment']['status'], 'INCOMPLETE')
        self.assertIn('other-tool', combined['tool_bindings'])
        for diagnostic in first['preparation']['diagnostics']:
            self.assertIn(diagnostic, combined['preparation']['diagnostics'])
        for diagnostic in first['preparation']['environment']['diagnostics']:
            self.assertIn(diagnostic, combined['preparation']['environment']['diagnostics'])
        self.assertEqual({row['name'] for row in combined['preparation']['selections']}, {'echo', 'other'})

    def test_appended_version_requirement_reuses_or_enriches_the_same_environment(self):
        first = self.materialize()
        unknown = next(row for row in first['preparation']['diagnostics'] if row['code'] == 'VERSION_UNKNOWN')
        self.assertEqual(unknown['severity'], 'INFO')
        config = self.append_package_config(first)
        other = Path(config['selections'][0]['directory'])
        descriptor = json.loads((other / 'capability.json').read_text())
        descriptor['tools'][0]['interpreter'] = 'python'
        descriptor['environment'] = [{'id': 'python', 'kind': 'executable',
                                      'version_min': '3.0', 'version_max_exclusive': '4.0'}]
        self.save_descriptor(other, descriptor)
        config['environment_bindings'] = {'python': {'path': sys.executable, 'observed_version': '3.14'}}
        enriched, _ = PREPARE.build_materials(config, self.root / 'enriched-materials')
        self.assertEqual(enriched['preparation']['readiness'], 'READY')
        self.assertEqual(enriched['preparation']['environment']['bindings']['python']['observed_version'], '3.14')
        self.assertIn(unknown, enriched['preparation']['diagnostics'])
        self.assertIn(unknown, enriched['preparation']['environment']['diagnostics'])
        self.assertIn(unknown, enriched['preparation']['retained_diagnostics'])
        self.assertIsNone(first['preparation']['environment']['bindings']['python']['observed_version'])

        known_config = deepcopy(self.config)
        known_config['environment_bindings']['python']['observed_version'] = '3.14'
        known = PREPARE.write_materials(known_config, self.root / 'known-materials')
        config.update(base_materials=known, source_root=known['preparation']['source_root'])
        for observation in (None, '3.14.0', '3.15'):
            with self.subTest(new_observation=observation):
                config['environment_bindings'] = {} if observation is None else {
                    'python': {'path': sys.executable, 'observed_version': observation}}
                before, original = self.tree(), deepcopy(known)
                if observation == '3.15':
                    with self.assertRaisesRegex(ValueError, 'conflict'):
                        PREPARE.build_materials(config, self.root / 'combined-materials')
                else:
                    combined, _ = PREPARE.build_materials(config, self.root / 'combined-materials')
                    self.assertEqual(combined['preparation']['readiness'], 'READY')
                    self.assertEqual(combined['scope']['executables']['python'], known['scope']['executables']['python'])
                    self.assertEqual(set(combined['tool_bindings']), {'echo-tool', 'other-tool'})
                self.assertEqual(self.tree(), before)
                self.assertEqual(known, original)

        other_python = self.project / 'different-venv/bin/python'
        other_python.parent.mkdir(parents=True)
        other_python.symlink_to(sys.executable)
        config['environment_bindings'] = {'python': {'path': str(other_python), 'observed_version': '3.14'}}
        with self.assertRaisesRegex(ValueError, 'conflict'):
            PREPARE.build_materials(config, self.root / 'different-venv-materials')

        self.descriptor['environment'][0]['version_min'] = '3.0'
        self.save_descriptor()
        incomplete = PREPARE.write_materials(self.config, self.root / 'incomplete-version-materials')
        old_error = next(row for row in incomplete['preparation']['diagnostics']
                         if row['code'] == 'VERSION_UNKNOWN' and row['severity'] == 'ERROR')
        config.update(base_materials=incomplete, source_root=incomplete['preparation']['source_root'])
        config['environment_bindings'] = {'python': {'path': sys.executable, 'observed_version': '3.14'}}
        combined, _ = PREPARE.build_materials(config, self.root / 'still-incomplete-materials')
        self.assertEqual(combined['preparation']['readiness'], 'INCOMPLETE')
        self.assertIn(old_error, combined['preparation']['diagnostics'])
        self.assertIn(old_error, combined['preparation']['retained_diagnostics'])

    def test_appended_package_cannot_replace_an_existing_tool_binding(self):
        first = self.materialize()
        config = self.append_package_config(first, tool_id='echo-tool')
        before, original = self.tree(), deepcopy(first)
        with self.assertRaisesRegex(ValueError, 'conflict'):
            PREPARE.write_materials(config, self.root / 'combined-materials')
        self.assertEqual(self.tree(), before)
        self.assertEqual(first, original)

    def test_path_only_append_preserves_known_version_for_the_same_call_entry(self):
        python = self.project / 'venv-a/bin/python'
        other_python = self.project / 'venv-b/bin/python'
        for call in (python, other_python):
            call.parent.mkdir(parents=True)
            call.symlink_to(sys.executable)
        alias = self.root / 'venv-a-alias'
        alias.symlink_to(python.parent.parent, target_is_directory=True)
        self.config['base_materials']['scope']['executables']['python'] = str(python)
        self.config['environment_bindings']['python'] = {'path': str(python), 'observed_version': '3.14'}
        first = self.materialize()
        config = self.append_package_config(first)
        other = Path(config['selections'][0]['directory'])
        descriptor = json.loads((other / 'capability.json').read_text())
        descriptor['tools'][0]['interpreter'] = 'python'
        descriptor['environment'] = [{'id': 'python', 'kind': 'executable',
                                      'version_min': '3.0', 'version_max_exclusive': '4.0'}]
        self.save_descriptor(other, descriptor)
        for supplied in (python, alias / 'bin/python'):
            with self.subTest(path=str(supplied)):
                config['environment_bindings'] = {'python': {'path': str(supplied)}}
                before, original = self.tree(), deepcopy(first)
                combined, _ = PREPARE.build_materials(config, self.root / 'combined-materials')
                self.assertEqual(combined['preparation']['readiness'], 'READY')
                environment = combined['preparation']['environment']
                self.assertEqual(environment['bindings']['python']['observed_version'], '3.14')
                self.assertFalse(any(row['code'] == 'VERSION_UNKNOWN' for row in environment['diagnostics']))
                self.assertEqual(combined['scope']['executables']['python'], str(python))
                self.assertEqual(set(combined['tool_bindings']), {'echo-tool', 'other-tool'})
                self.assertEqual(self.tree(), before)
                self.assertEqual(first, original)

        # An explicit unknown observation is not an omitted field.
        config['environment_bindings'] = {'python': {'path': str(python), 'observed_version': None}}
        before = self.tree()
        incomplete, _ = PREPARE.build_materials(config, self.root / 'unknown-version-materials')
        self.assertEqual(incomplete['preparation']['readiness'], 'INCOMPLETE')
        self.assertTrue(any(row['code'] == 'VERSION_UNKNOWN' and row['severity'] == 'ERROR'
                            for row in incomplete['preparation']['environment']['diagnostics']))
        self.assertEqual(self.tree(), before)

        # Equal final binaries do not make two venv call entries interchangeable.
        self.assertEqual(python.resolve(), other_python.resolve())
        config['environment_bindings'] = {'python': {'path': str(other_python)}}
        before, original = self.tree(), deepcopy(first)
        with self.assertRaisesRegex(ValueError, 'conflict'):
            PREPARE.write_materials(config, self.root / 'different-venv-materials')
        self.assertEqual(self.tree(), before)
        self.assertEqual(first, original)

    def test_parent_alias_equivalence_preserves_call_path_without_merging_distinct_venvs(self):
        first = self.project / 'venv-a'
        second = self.project / 'venv-b'
        for venv in (first, second):
            (venv / 'bin').mkdir(parents=True)
            (venv / 'bin/python').symlink_to(sys.executable)
        alias = self.project / 'venv-alias'
        alias.symlink_to(first, target_is_directory=True)
        original_call = str(alias / 'bin/python')
        self.config['base_materials']['scope']['executables']['python'] = original_call
        self.config['environment_bindings']['python']['path'] = str(first / 'bin/python')
        materials, _ = PREPARE.build_materials(self.config, self.output)
        self.assertEqual(materials['preparation']['readiness'], 'READY')
        self.assertEqual(materials['scope']['executables']['python'], original_call)
        argv = _local_argv(materials['tool_bindings']['echo-tool']['argv_prefix'], materials['scope'])
        self.assertEqual(argv[0], original_call)
        self.assertEqual((first / 'bin/python').resolve(), (second / 'bin/python').resolve())
        self.config['environment_bindings']['python']['path'] = str(second / 'bin/python')
        before = self.tree()
        with self.assertRaisesRegex(ValueError, 'conflict'):
            PREPARE.write_materials(self.config, self.output)
        self.assertEqual(self.tree(), before)

    def test_wrong_or_duplicate_version_does_not_write_materials(self):
        for selections in (
            [{**self.config['selections'][0], 'version': '2.0'}],
            [self.config['selections'][0], deepcopy(self.config['selections'][0])],
        ):
            with self.subTest(selections=selections):
                config = {**self.config, 'selections': selections}
                before = self.tree()
                with self.assertRaises(ValueError):
                    PREPARE.write_materials(config, self.output)
                self.assertEqual(self.tree(), before)

    def test_identity_rechecks_declared_files_without_claiming_a_lock_or_receiver(self):
        (self.package / 'helper.txt').write_text('declared helper')
        self.descriptor['runtime_files'] = ['helper.txt']
        self.save_descriptor()
        materials, _ = PREPARE.build_materials(self.config, self.output)
        for name in ('guide.md', 'tool.py', 'helper.txt', 'expected.json', 'capability.json'):
            with self.subTest(name=name):
                path = self.package / name
                original = path.read_bytes()
                path.write_bytes(original + b'\n')
                before = self.tree()
                result = PREPARE.check_selection(materials)
                self.assertEqual(result['status'], 'CHANGED')
                self.assertEqual([row['path'] for row in result['changes']], [name])
                self.assertFalse(result['commands_executed'])
                self.assertFalse(result['acceptance_granted'])
                self.assertEqual(self.tree(), before)
                path.write_bytes(original)
        (self.package / 'unselected.txt').write_text('not part of declared identity')
        self.assertEqual(PREPARE.check_selection(materials)['status'], 'MATCH')

    def test_empty_or_dependency_only_package_has_no_consumable_entry(self):
        for dependencies in ([], ['tool.py']):
            with self.subTest(runtime_files=dependencies):
                self.descriptor.update(materials=[], tools=[], runtime_files=dependencies)
                self.save_descriptor()
                with self.assertRaises(ValueError):
                    PREPARE.build_materials(self.config, self.output)
        self.assertFalse(self.output.exists())

    def test_interpreter_or_workpack_binding_gap_is_not_ready(self):
        for changed in ('interpreter', 'workpack'):
            with self.subTest(changed=changed):
                config = deepcopy(self.config)
                if changed == 'interpreter':
                    config['environment_bindings'] = {}
                else:
                    config['selections'][0]['workpack_ids'] = []
                materials, _ = PREPARE.build_materials(config, self.output)
                self.assertEqual(materials['preparation']['readiness'], 'INCOMPLETE')
        self.config['selections'][0]['workpack_ids'] = ['UNDECLARED-TASK']
        with self.assertRaises(ValueError):
            PREPARE.build_materials(self.config, self.output)

    def test_source_and_executable_conflicts_preserve_base_and_package(self):
        for conflict in ('source', 'executable'):
            with self.subTest(conflict=conflict):
                config = deepcopy(self.config)
                if conflict == 'source':
                    base = config['base_materials']
                    base['request']['requirement_ir']['sources'][0]['source_id'] = 'CAP-echo-M1'
                    base['source_manifest'][0]['source_id'] = 'CAP-echo-M1'
                else:
                    config['base_materials']['scope']['executables']['python'] = str(self.package / 'tool.py')
                before, original = self.tree(), deepcopy(config)
                with self.assertRaises(ValueError):
                    PREPARE.write_materials(config, self.output)
                self.assertEqual(config, original)
                self.assertEqual(self.tree(), before)

    def test_multiple_packages_reject_conflicting_tool_or_environment_ids(self):
        other = self.project / 'packages/other'
        shutil.copytree(self.package, other)
        for conflict in ('tool', 'environment'):
            with self.subTest(conflict=conflict):
                descriptor = {**deepcopy(self.descriptor), 'name': 'other'}
                if conflict == 'environment':
                    self.descriptor['environment'][0]['version_max_exclusive'] = '4.0'
                    self.save_descriptor()
                    descriptor['tools'][0]['id'] = 'other-tool'
                    descriptor['environment'][0]['version_min'] = '999.0'
                self.save_descriptor(other, descriptor)
                config = deepcopy(self.config)
                config['selections'].append({'directory': str(other), 'version': '1.0', 'workpack_ids': ['MAKE-TEXT']})
                before = self.tree()
                with self.assertRaises(ValueError):
                    PREPARE.write_materials(config, self.output)
                self.assertEqual(self.tree(), before)

    def test_compatible_environment_bounds_merge_without_false_conflict(self):
        self.descriptor['environment'][0].update(version_min='3.0', version_max_exclusive='4.0')
        self.save_descriptor()
        other = self.project / 'packages/compatible'
        shutil.copytree(self.package, other)
        descriptor = {**deepcopy(self.descriptor), 'name': 'compatible'}
        descriptor['tools'][0]['id'] = 'compatible-tool'
        descriptor['environment'][0].update(version_min='3.10', version_max_exclusive='3.99')
        self.save_descriptor(other, descriptor)
        self.config['selections'].append({'directory': str(other), 'version': '1.0', 'workpack_ids': ['MAKE-TEXT']})
        self.config['environment_bindings']['python']['observed_version'] = '3.11'
        materials, _ = PREPARE.build_materials(self.config, self.output)
        self.assertEqual(materials['preparation']['readiness'], 'READY')
        self.assertEqual(set(materials['tool_bindings']), {'echo-tool', 'compatible-tool'})
        self.assertFalse(materials['preparation']['environment']['receiver_verified'])
        self.assertFalse(materials['preparation']['environment']['probes_executed'])

    def test_source_destination_conflict_does_not_overwrite_project_rules(self):
        target = self.source / 'capabilities/echo/guide.md'
        target.parent.mkdir(parents=True)
        target.write_text('Original project-specific rules must win no silent overwrite.\n')
        self.config['base_materials']['source_manifest'][0]['path'] = 'capabilities/echo/guide.md'
        self.config['base_materials']['request']['requirement_ir']['sources'][0]['path_or_uri'] = 'capabilities/echo/guide.md'
        before = self.tree()
        with self.assertRaises(ValueError):
            PREPARE.write_materials(self.config, self.output)
        self.assertEqual(self.tree(), before)

    def test_manifest_paths_and_aliases_cannot_escape_declared_package(self):
        outside = self.root / 'outside.md'
        outside.write_text('Unselected outside material')
        (self.package / 'escaped.md').symlink_to(outside)
        for name in ('../outside.md', '/outside.md', 'guide.md/../guide.md', 'escaped.md'):
            with self.subTest(name=name):
                self.descriptor['materials'] = [name]
                self.save_descriptor()
                before = self.tree()
                with self.assertRaises((ValueError, OSError)):
                    PREPARE.write_materials(self.config, self.output)
                self.assertEqual(self.tree(), before)

    def test_production_reads_or_sources_cannot_expose_private_expectations(self):
        alias = self.project / 'oracle-alias'
        alias.symlink_to(self.package / 'expected.json')
        for mode in ('parent-read', 'alias-read', 'source'):
            with self.subTest(mode=mode):
                config = deepcopy(self.config)
                if mode == 'source':
                    self.descriptor['materials'] = ['guide.md', 'expected.json']
                    self.save_descriptor()
                else:
                    config['base_materials']['scope']['source_read_roots'] = [str(self.package if mode == 'parent-read' else alias)]
                before = self.tree()
                with self.assertRaisesRegex(ValueError, 'protected verification'):
                    PREPARE.write_materials(config, self.output)
                self.assertEqual(self.tree(), before)

    def test_explicit_shared_input_is_allowed_without_publishing_private_oracle(self):
        (self.package / 'input.json').write_text('{"rows":[1,2,3]}\n')
        self.descriptor['materials'].append('input.json')
        self.descriptor['verification_files'].append({'path': 'input.json', 'shared': True})
        self.save_descriptor()
        materials = self.materialize()
        snapshot = load_local_sources(Path(materials['preparation']['source_root']), materials['source_manifest'])
        self.assertTrue(any(row['path_or_uri'].endswith('/input.json') for row in snapshot['sources']))
        self.assertFalse(any(row['path_or_uri'].endswith('/expected.json') for row in snapshot['sources']))
        self.assertEqual({row['path'] for row in materials['preparation']['verifier_inputs']},
                         {'capabilities/echo/input.json', 'capabilities/echo/expected.json'})

    def test_existing_checker_materials_are_preserved_and_new_dependencies_are_snapshotted(self):
        original = self.root / 'old-oracle.json'
        original.write_text('{"old":true}\n')
        base = self.config['base_materials']
        base['preparation']['verifier_inputs'].append({'source': str(original), 'path': 'old-oracle.json'})
        base['scope']['verification_resources']['checker_files'] = ['old-oracle.json']
        materials = self.materialize()
        self.assertEqual(set(materials['scope']['verification_resources']['checker_files']),
                         {'old-oracle.json', 'capabilities/echo/expected.json'})
        self.assertEqual(materials['preparation']['next'], base['preparation']['next'])
        scope = materials['scope']
        _validate_scope(SimpleNamespace(database_path=self.root / 'control.sqlite3'), materials['request']['plan'], scope)
        protected = snapshot_verifier(SimpleNamespace(database_path=self.root / 'control.sqlite3'),
                                      materials['request']['plan'], scope)
        selected = Path(protected['runtime_root']) / 'capabilities/echo/expected.json'
        original.write_text('{"old":false}\n')
        (self.package / 'expected.json').write_text('{"marker":"MUTATED"}\n')
        self.assertEqual(json.loads(selected.read_text()), {'marker': 'INDEPENDENT-ONLY-812'})
        self.assertEqual(json.loads((Path(protected['runtime_root']) / 'old-oracle.json').read_text()), {'old': True})
        self.assertFalse((self.root / 'control.sqlite3').exists())

    def test_verifier_destination_conflict_is_not_silently_replaced(self):
        original = self.root / 'different-oracle.json'
        original.write_text('{"marker":"OLD"}')
        self.config['base_materials']['preparation']['verifier_inputs'].append(
            {'source': str(original), 'path': 'capabilities/echo/expected.json'})
        before = self.tree()
        with self.assertRaises(ValueError):
            PREPARE.write_materials(self.config, self.output)
        self.assertEqual(self.tree(), before)

    def test_shared_destination_does_not_remove_another_private_source_boundary(self):
        shared = self.root / 'shared-input.json'
        shared.write_bytes((self.package / 'expected.json').read_bytes())
        self.config['base_materials']['preparation']['verifier_inputs'].append({
            'source': str(shared), 'path': 'capabilities/echo/expected.json', 'shared': True})
        self.config['base_materials']['scope']['source_read_roots'] = [str(self.package / 'expected.json')]
        before = self.tree()
        with self.assertRaises(ValueError):
            PREPARE.write_materials(self.config, self.output)
        self.assertEqual(self.tree(), before)

    def test_shipped_material_and_tool_packages_feed_one_source_root_and_real_cli(self):
        # Install only test-owned copies in the isolated fixture. A staging
        # checkout in shared /tmp is not a receiver-approved dependency root.
        packages = self.project / 'selected-examples'
        for name in ('reference-notes', 'text-count'):
            shutil.copytree(ENTRY.parent / 'packages' / name / '1', packages / name / '1')
        self.config['selections'] = [
            {'directory': str(packages / name / '1'), 'version': '1', 'workpack_ids': ['MAKE-TEXT']}
            for name in ('reference-notes', 'text-count')]
        self.config['environment_bindings']['python']['observed_version'] = '.'.join(map(str, sys.version_info[:3]))
        original = deepcopy(self.config['base_materials'])
        materials = self.materialize()
        request = materials['request']
        snapshot = load_local_sources(Path(materials['preparation']['source_root']), materials['source_manifest'])
        validate_requirement_source_bindings(request['requirement_ir'], snapshot)
        validate_acceptance_contracts(request['requirement_ir'], snapshot=snapshot, required=True)
        self.assertEqual(compile_build_plan(request['requirement_ir'], request['plan'])['status'],
                         'PLAN_COMPILED_NOT_AUTHORIZED')
        _validate_scope(SimpleNamespace(database_path=self.root / 'control.sqlite3'),
                        request['plan'], materials['scope'])
        self.assertEqual(len(snapshot['sources']), 5)
        self.assertTrue(all(not Path(row['path']).is_absolute() for row in materials['source_manifest']))
        self.assertEqual(self.config['base_materials'], original)
        self.assertEqual(PREPARE.check_selection(materials)['status'], 'MATCH')
        sample = self.root / 'new-input.txt'
        sample.write_text('甲乙\n \nthird\n', encoding='utf-8')
        argv = _local_argv([*materials['tool_bindings']['count-text']['argv_prefix'], str(sample)], materials['scope'])
        completed = subprocess.run(argv, cwd=self.root, capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), {'characters': 11, 'nonempty_lines': 2})
        self.assertFalse(any((self.root / name).exists() for name in ('target', 'control.sqlite3', 'resources')))

    def test_each_selected_package_needs_its_source_task_binding(self):
        self.config['selections'].append({
            'directory': str(ENTRY.parent / 'packages/reference-notes/1'),
            'version': '1', 'workpack_ids': [],
        })
        materials, _ = PREPARE.build_materials(self.config, self.output)
        self.assertEqual(materials['preparation']['readiness'], 'INCOMPLETE')
        self.assertTrue(any(row['severity'] == 'ERROR' for row in materials['preparation']['diagnostics']))
        self.assertFalse(self.output.exists())

    def test_workspace_dependencies_outside_all_task_writes_are_usable(self):
        workspace = self.root / 'target'
        tools = workspace / 'tools'
        tools.mkdir(parents=True)
        (tools / 'helper.txt').write_text('Ordinary project-owned read dependency.\n')
        python = workspace / '.venv/bin/python'
        python.parent.mkdir(parents=True)
        python.symlink_to(sys.executable)
        self.descriptor['environment'].append({'id': 'project-tools', 'kind': 'directory'})
        self.save_descriptor()
        self.config['environment_bindings'].update({
            'python': {'path': str(python)}, 'project-tools': {'path': str(tools)},
        })
        self.config['base_materials']['scope']['executables']['python'] = str(python)
        materials = self.materialize()
        self.assertEqual(materials['preparation']['readiness'], 'READY')
        self.assertEqual(materials['scope']['executables']['python'], str(python))
        self.assertIn(str(tools), materials['scope']['source_read_roots'])
        _validate_scope(SimpleNamespace(database_path=self.root / 'control.sqlite3'),
                        materials['request']['plan'], materials['scope'])
        self.assertFalse((workspace / 'outputs').exists())
        for writable in ('tools', '.venv', 'tools/generated'):
            with self.subTest(other_task_writes=writable):
                config = deepcopy(self.config)
                task = deepcopy(config['base_materials']['request']['plan']['workpacks'][0])
                task.update(workpack_id='SECOND', job_id='SECOND', depends_on=['MAKE-TEXT'])
                task['artifacts'] = [{'artifact_id': 'SECOND-RESULT', 'path': writable + '/result.json'}]
                task['verification'][0]['artifact_ids'] = ['SECOND-RESULT']
                config['base_materials']['request']['plan']['workpacks'].append(task)
                config['base_materials']['scope']['task_write_roots']['SECOND'] = [writable]
                before = self.tree()
                with self.assertRaises(ValueError):
                    PREPARE.build_materials(config, self.root / 'rejected-materials')
                self.assertEqual(self.tree(), before)

    def test_output_materials_and_private_checker_stay_outside_workspace(self):
        # The project fixture includes the private expected.json. Its exclusion
        # does not imply that ordinary project tools or a venv are forbidden.
        for target in (self.project, self.output):
            with self.subTest(target=target):
                config = deepcopy(self.config)
                config['base_materials']['scope']['workspace_root'] = str(target)
                with self.assertRaises(ValueError):
                    PREPARE.build_materials(config, self.output)
        self.assertFalse(self.output.exists())

    def test_executable_parent_alias_in_write_domain_remains_rejected(self):
        output = self.root / 'target/outputs'
        output.mkdir(parents=True)
        alias = output / 'sdk'
        alias.symlink_to(Path(sys.executable).parent, target_is_directory=True)
        call = str(alias / Path(sys.executable).name)
        self.config['base_materials']['scope']['executables']['python'] = call
        self.config['environment_bindings']['python']['path'] = call
        with self.assertRaisesRegex(ValueError, 'write roots'):
            PREPARE.build_materials(self.config, self.output)

    def test_workspace_alias_cannot_hide_executable_link_in_a_write_domain(self):
        workspace = self.root / 'target'
        output = workspace / 'outputs'
        output.mkdir(parents=True)
        (output / 'sdk').symlink_to(Path(sys.executable).parent, target_is_directory=True)
        workspace_alias = self.root / 'workspace-alias'
        workspace_alias.symlink_to(workspace, target_is_directory=True)
        bridge = self.root / 'outside-bridge'
        bridge.symlink_to(output / 'sdk', target_is_directory=True)
        self.config['base_materials']['scope']['workspace_root'] = str(workspace_alias)
        for index, call in enumerate((workspace_alias / 'outputs/sdk' / Path(sys.executable).name,
                                      bridge / Path(sys.executable).name)):
            with self.subTest(call=str(call)):
                materials_output = self.root / ('rejected-materials-' + str(index))
                self.config['base_materials']['scope']['executables']['python'] = str(call)
                self.config['environment_bindings']['python']['path'] = str(call)
                before, original = self.tree(), deepcopy(self.config)
                with self.assertRaisesRegex(ValueError, 'write roots'):
                    PREPARE.write_materials(self.config, materials_output)
                self.assertEqual(self.tree(), before)
                self.assertEqual(self.config, original)
                self.assertFalse(materials_output.exists())

    def test_aliases_to_workspace_readonly_venv_preserve_the_call_entry(self):
        workspace = self.root / 'target'
        python = workspace / '.venv/bin/python'
        python.parent.mkdir(parents=True)
        python.symlink_to(sys.executable)
        workspace_alias = self.root / 'workspace-alias'
        workspace_alias.symlink_to(workspace, target_is_directory=True)
        # A common ancestor of the writes is not itself a read dependency.
        root_alias = self.root / 'external-root-alias'
        root_alias.symlink_to(self.root, target_is_directory=True)
        for call in (workspace_alias / '.venv/bin/python',
                     root_alias / 'workspace-alias/.venv/bin/python'):
            with self.subTest(call=str(call)):
                config = deepcopy(self.config)
                config['base_materials']['scope']['workspace_root'] = str(workspace_alias)
                config['base_materials']['scope']['executables']['python'] = str(call)
                config['environment_bindings']['python']['path'] = str(python)
                before = self.tree()
                materials, _ = PREPARE.build_materials(config, self.output)
                self.assertEqual(materials['preparation']['readiness'], 'READY')
                argv = _local_argv(materials['tool_bindings']['echo-tool']['argv_prefix'], materials['scope'])
                self.assertEqual(argv[0], str(call))
                self.assertEqual(materials['scope']['executables']['python'], str(call))
                self.assertEqual(self.tree(), before)

    def test_cli_creates_only_new_materials_and_checks_identity_without_dispatch(self):
        config = self.root / 'config.json'
        config.write_text(json.dumps(self.config))
        argv = [sys.executable, '-I', '-B', str(ENTRY), '--config', str(config), '--output', str(self.output)]
        result = subprocess.run(argv, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        before = self.tree()
        second = subprocess.run(argv, capture_output=True, text=True, timeout=15)
        self.assertEqual(second.returncode, 1)
        self.assertEqual(self.tree(), before)
        check = [sys.executable, '-I', '-B', str(ENTRY), '--check-selection', str(self.output / 'materials.json')]
        self.assertEqual(subprocess.run(check, capture_output=True, text=True, timeout=15).returncode, 0)
        (self.package / 'tool.py').write_text('raise RuntimeError("not executed by identity check")\n')
        before = self.tree()
        changed = subprocess.run(check, capture_output=True, text=True, timeout=15)
        self.assertEqual(changed.returncode, 1, changed.stdout + changed.stderr)
        self.assertEqual(json.loads(changed.stdout)['status'], 'CHANGED')
        self.assertEqual(self.tree(), before)


if __name__ == '__main__':
    unittest.main()
