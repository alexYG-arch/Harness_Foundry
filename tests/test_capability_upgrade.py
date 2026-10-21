"""Thin next-selection handoff with test-owned tools, not business acceptance."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / 'examples/capability-adapters/upgrade.py'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


UPGRADE = load('tested_capability_upgrade', ENTRY)
PREPARE = UPGRADE._prepare
CONSUME = load('consume_for_upgrade_tests', ENTRY.with_name('consume.py'))


class CapabilityUpgradeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='capability-upgrade-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        self.marker = self.root / 'tool-calls.txt'
        self.package1 = self.package('echo', '1', 'v1')
        self.package2 = self.package('echo', '2', 'v2')
        self.sources = self.root / 'project-sources'
        self.sources.mkdir()
        (self.sources / 'brief.md').write_bytes(b'# Project owned\r\nPreserve the custom unit and title.\r\n')
        self.project_base = {
            'source_manifest': [{'source_id': 'BRIEF', 'path': 'brief.md'}],
            'request': {'requirement_ir': {
                'program_id': 'PROJECT-TEST', 'target': {'mission': 'Keep project rules'},
                'sources': [{'source_id': 'BRIEF', 'path_or_uri': 'brief.md', 'loaded_completely': True}],
                'atoms': [{'atom_id': 'UNITS', 'text_or_lossless_paraphrase': 'Use per-day units'}]},
                'plan': {'workpacks': [{'workpack_id': 'MAKE', 'inputs': [{'kind': 'SOURCE', 'id': 'BRIEF'}],
                                       'goal': 'Use project title and per-day units'}]},
                'document_review': {'old': 'not inherited'}, 'expected_revision': 88},
            'scope': {'workspace_root': str(self.project), 'task_write_roots': {'MAKE': ['outputs']},
                      'executables': {'python': sys.executable}, 'source_read_roots': [],
                      'max_attempts': 7, 'max_task_attempts': 4,
                      'verification_resources': {'checker_files': ['project-check.py']}},
            'preparation': {'next': 'Return to the original host', 'verifier_inputs': []},
        }
        self.config1 = self.config(self.package1, '1')
        self.config2 = self.config(self.package2, '2')
        self.old_output = self.root / 'materials-v1'
        self.old = PREPARE.write_materials(self.config1, self.old_output)

    def package(self, name, version, answer, *, directory=None):
        path = directory or self.root / 'packages' / name / version
        path.mkdir(parents=True)
        descriptor = {
            'name': name, 'version': version, 'usage': 'both', 'inputs': ['new text'], 'outputs': ['JSON'],
            'materials': ['guide.md'], 'verification_files': ['expected.json'],
            'tools': [{'id': name + '-tool', 'path': 'tool.py', 'interpreter': 'python',
                       'interpreter_args': ['-I', '-B']}],
            'environment': [{'id': 'python', 'kind': 'executable', 'version_min': '3.11'}],
        }
        (path / 'capability.json').write_text(json.dumps(descriptor))
        (path / 'guide.md').write_text('Use the actual ' + version + ' tool with project parameters.\n')
        (path / 'expected.json').write_text('{"private":"INDEPENDENT-ONLY-882"}\n')
        (path / 'tool.py').write_text(
            'import json, sys\nfrom pathlib import Path\n'
            'with Path(sys.argv[1]).open("a") as stream: stream.write(' + repr(answer + '\n') + ')\n'
            'print(json.dumps({"version":' + repr(version) + ',"value":' + repr(answer)
            + ',"input":sys.argv[2]}))\n')
        return path

    def config(self, package, version):
        return {'project_root': str(self.project), 'source_root': str(self.sources),
                'base_materials': deepcopy(self.project_base),
                'selections': [{'directory': str(package), 'version': version, 'workpack_ids': ['MAKE']}],
                'environment_bindings': {'python': {'path': sys.executable, 'observed_version': '3.14'}}}

    def tree(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob('*') if path.is_file()}

    def call(self, materials, value):
        prepared = CONSUME.prepare_call(materials, 'echo-tool', [str(self.marker), value])
        result = subprocess.run(prepared['argv'], cwd=self.root, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_new_and_old_versions_call_once_each_after_pure_preparation(self):
        before, old, config = self.tree(), deepcopy(self.old), deepcopy(self.config2)
        with patch('subprocess.Popen', side_effect=AssertionError('preparation does not execute')):
            materials, files, transition = UPGRADE.build_upgrade(self.old, self.config2, self.root / 'new')
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.old, old)
        self.assertEqual(self.config2, config)
        self.assertFalse(transition['commands_executed'])
        self.assertFalse(transition['budget_modified'])
        self.assertFalse(transition['acceptance_granted'])
        self.assertIn('VERSION_CHANGED', transition['packages'][0]['changes'])
        self.assertIn('CONTENT_CHANGED', transition['packages'][0]['changes'])
        self.assertEqual(transition['source_affected_workpacks'], ['MAKE'])
        self.assertEqual(self.call(self.old, 'first unseen input'), {'version': '1', 'value': 'v1', 'input': 'first unseen input'})
        self.assertEqual(self.call(materials, 'different new input'), {'version': '2', 'value': 'v2', 'input': 'different new input'})
        self.assertEqual(self.marker.read_text(), 'v1\nv2\n')
        self.assertNotIn(b'INDEPENDENT-ONLY', b''.join(files.values()))

    def test_project_customization_budget_and_private_handoff_survive(self):
        materials, files, transition = UPGRADE.build_upgrade(self.old, self.config2, self.root / 'new')
        request = materials['request']
        self.assertEqual(request['requirement_ir']['atoms'], self.project_base['request']['requirement_ir']['atoms'])
        self.assertEqual(request['plan']['workpacks'][0]['goal'], 'Use project title and per-day units')
        self.assertEqual(files['sources/brief.md'], (self.sources / 'brief.md').read_bytes())
        self.assertNotIn('document_review', request)
        self.assertNotIn('expected_revision', request)
        self.assertEqual(materials['scope']['max_attempts'], 7)
        self.assertEqual(materials['scope']['max_task_attempts'], 4)
        self.assertEqual(materials['preparation']['next'], 'Return to the original host')
        self.assertEqual(materials['scope']['verification_resources']['checker_files'],
                         ['project-check.py', 'capabilities/echo/expected.json'])
        self.assertEqual(materials['preparation']['verifier_inputs'][0]['source'], str(self.package2 / 'expected.json'))
        self.assertFalse(transition['authority_inherited'])

    def test_rollback_creates_new_materials_and_keeps_both_histories(self):
        second, _ = UPGRADE.write_upgrade(self.old, self.config2, self.root / 'materials-v2')
        before = self.tree()
        restored, report = UPGRADE.write_upgrade(second, self.config1, self.root / 'rollback-materials')
        self.assertTrue(all(self.tree()[key] == raw for key, raw in before.items()))
        self.assertEqual(restored['preparation']['selections'][0]['version'], '1')
        self.assertEqual(report['packages'][0]['before']['version'], '2')
        self.assertFalse(report['target_modified'])
        self.assertFalse(report['physical_files_removed'])
        self.assertEqual(self.call(restored, 'rollback input')['value'], 'v1')
        self.assertEqual(self.call(second, 'old v2 selection still valid')['value'], 'v2')
        with self.assertRaisesRegex(ValueError, 'new materials directory'):
            UPGRADE.write_upgrade(second, self.config1, self.old_output)

    def test_same_version_changed_content_is_reported_and_bound(self):
        revised = self.package('echo', '1', 'revised-v1', directory=self.root / 'revised-v1')
        materials, _, report = UPGRADE.build_upgrade(self.old, self.config(revised, '1'), self.root / 'new')
        changes = report['packages'][0]['changes']
        self.assertIn('CONTENT_CHANGED', changes)
        self.assertNotIn('VERSION_CHANGED', changes)
        self.assertEqual(self.call(materials, 'revision input')['value'], 'revised-v1')
        self.assertEqual(self.call(self.old, 'old immutable input')['value'], 'v1')

    def test_old_file_drift_is_retained_diagnostic_not_a_global_upgrade_block(self):
        (self.package1 / 'guide.md').write_text('Changed old source; no longer old identity\n')
        before = deepcopy(self.old['preparation']['selections'])
        materials, _, report = UPGRADE.build_upgrade(self.old, self.config2, self.root / 'new')
        self.assertEqual(report['previous_selection_check']['status'], 'CHANGED')
        self.assertEqual(report['packages'][0]['before'], before[0])
        with self.assertRaisesRegex(ValueError, 'files changed'):
            CONSUME.prepare_call(self.old, 'echo-tool')
        self.assertEqual(self.call(materials, 'fixed explicit selection')['value'], 'v2')

    def test_missing_old_dependency_can_be_corrected_without_inheriting_old_error(self):
        invalid = deepcopy(self.config1)
        invalid['environment_bindings']['python']['path'] = str(self.root / 'missing-python')
        incomplete = PREPARE.write_materials(invalid, self.root / 'incomplete')
        self.assertEqual(incomplete['preparation']['readiness'], 'INCOMPLETE')
        repaired, _, report = UPGRADE.build_upgrade(incomplete, self.config1, self.root / 'repaired')
        self.assertEqual(repaired['preparation']['readiness'], 'READY')
        self.assertTrue(any(row['severity'] == 'ERROR' for row in report['previous_diagnostics']))
        self.assertTrue(report['environment'])
        self.assertEqual(self.call(repaired, 'corrected host binding')['value'], 'v1')
        self.assertFalse(report['commands_executed'])

    def test_removal_keeps_shared_interpreter_and_does_not_delete_packages(self):
        other = self.package('other', '1', 'other-v1')
        config = deepcopy(self.config1)
        config['selections'].append({'directory': str(other), 'version': '1', 'workpack_ids': ['MAKE']})
        combined = PREPARE.write_materials(config, self.root / 'combined')
        before = self.tree()
        materials, _, report = UPGRADE.build_upgrade(combined, self.config(other, '1'), self.root / 'without-echo')
        self.assertEqual(set(materials['tool_bindings']), {'other-tool'})
        self.assertEqual(materials['scope']['executables']['python'], sys.executable)
        self.assertNotIn('echo-tool', materials['tool_bindings'])
        self.assertEqual(next(row['changes'] for row in report['packages'] if row['name'] == 'echo'), ['REMOVED'])
        self.assertEqual(report['environment'], [])
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.call(combined, 'retained old target')['value'], 'v1')

    def test_remove_last_capability_returns_explicit_project_base(self):
        config = deepcopy(self.config1)
        config['selections'] = []
        before = self.tree()
        materials, report = UPGRADE.write_upgrade(self.old, config, self.root / 'project-only')
        self.assertTrue(all(self.tree()[key] == raw for key, raw in before.items()))
        self.assertEqual(materials['scope'], self.project_base['scope'])
        self.assertEqual(materials['source_manifest'], self.project_base['source_manifest'])
        self.assertEqual(materials['preparation']['selections'], [])
        self.assertEqual(materials['preparation']['readiness'], 'READY')
        self.assertEqual(materials['tool_bindings'], {})
        self.assertEqual(materials['request']['plan'], self.project_base['request']['plan'])
        self.assertEqual(materials['request']['requirement_ir'], self.project_base['request']['requirement_ir'])
        self.assertNotIn('document_review', materials['request'])
        self.assertEqual((self.root / 'project-only/sources/brief.md').read_bytes(), (self.sources / 'brief.md').read_bytes())
        self.assertFalse(report['physical_files_removed'])
        self.assertTrue(self.package1.is_dir())
        with self.assertRaisesRegex(ValueError, 'absent'):
            CONSUME.prepare_call(materials, 'echo-tool')
        self.assertEqual(self.call(self.old, 'old target still selected')['value'], 'v1')

    def test_explicit_empty_fragment_has_no_phantom_dependency(self):
        config = {'project_root': str(self.project), 'selections': []}
        materials, files, report = UPGRADE.build_upgrade(self.old, config, self.root / 'empty')
        self.assertEqual(files, {})
        self.assertEqual(materials['scope_fragment'], {'executables': {}, 'source_read_roots': []})
        self.assertEqual(materials['preparation']['readiness'], 'READY')
        self.assertNotIn('request', materials)
        self.assertTrue(report['packages'])

    def test_complete_config_and_unmixed_project_base_are_required_before_output(self):
        for config in ({'project_root': str(self.project)}, {**self.config2, 'base_materials': self.old}):
            with self.subTest(config=list(config)):
                with self.assertRaises(ValueError):
                    UPGRADE.write_upgrade(self.old, config, self.root / 'must-not-exist')
                self.assertFalse((self.root / 'must-not-exist').exists())
        config = deepcopy(self.config2)
        config['selections'][0]['version'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'selected version differs'):
            UPGRADE.write_upgrade(self.old, config, self.root / 'must-not-exist')
        self.assertFalse((self.root / 'must-not-exist').exists())

    def test_project_sources_change_and_missing_history_are_explicit(self):
        (self.sources / 'brief.md').write_text('Changed project requirement\n')
        _, _, changed = UPGRADE.build_upgrade(self.old, self.config1, self.root / 'new')
        source = next(row for row in changed['source_files'] if row['id'] == 'BRIEF')
        self.assertNotEqual(source['before']['sha256'], source['after']['sha256'])
        self.assertEqual(changed['source_affected_workpacks'], ['MAKE'])
        (self.old_output / 'sources/brief.md').unlink()
        _, _, missing = UPGRADE.build_upgrade(self.old, self.config1, self.root / 'another-new')
        source = next(row for row in missing['source_files'] if row['id'] == 'BRIEF')
        self.assertFalse(source['before']['available'])
        self.assertTrue(source['after']['available'])

    def test_empty_selection_keeps_project_incomplete_and_rejects_target_output(self):
        config = deepcopy(self.config1)
        config['selections'] = []
        config['base_materials']['preparation'].update(readiness='INCOMPLETE', diagnostics=[
            {'code': 'PROJECT_INPUT_MISSING', 'severity': 'ERROR'}])
        materials, _, _ = UPGRADE.build_upgrade(self.old, config, self.root / 'new')
        self.assertEqual(materials['preparation']['readiness'], 'INCOMPLETE')
        with self.assertRaisesRegex(ValueError, 'separate from the workspace'):
            UPGRADE.write_upgrade(self.old, config, self.project / 'materials')
        self.assertFalse((self.project / 'materials').exists())

    def test_project_only_keeps_legal_residual_bindings_and_parent_aliases(self):
        alias = self.root / 'python-parent-alias'
        alias.symlink_to(Path(sys.executable).parent, target_is_directory=True)
        local_alias = self.project / 'local-bin'
        local_alias.symlink_to(Path(sys.executable).parent, target_is_directory=True)
        paths = [sys.executable, str(alias / Path(sys.executable).name), './local-bin/' + Path(sys.executable).name]
        for invocation in paths:
            with self.subTest(invocation=invocation):
                config = deepcopy(self.config1)
                config['selections'] = []
                config['environment_bindings']['python']['path'] = invocation
                config['environment_bindings']['qt-sdk'] = {'path': str(self.root / 'unused-old-sdk')}
                materials, _, _ = UPGRADE.build_upgrade(self.old, config, self.root / 'project-only')
                self.assertEqual(materials['preparation']['readiness'], 'READY')
                self.assertEqual(materials['scope'], self.project_base['scope'])
                self.assertFalse(any(row['severity'] == 'ERROR' for row in materials['preparation']['diagnostics']))
                unused = next(row for row in materials['preparation']['diagnostics'] if row['id'] == 'qt-sdk')
                self.assertEqual(unused['severity'], 'INFO')
                self.assertEqual(unused['code'], 'UNSELECTED_ENVIRONMENT_BINDING')
        self.assertFalse(self.marker.exists())

    def test_project_only_environment_changes_are_not_silently_ignored(self):
        changed_python = self.root / 'project-python'
        changed_python.symlink_to(sys.executable)
        config = deepcopy(self.config1)
        config['selections'] = []
        config['environment_bindings']['python']['path'] = str(changed_python)
        unchanged, report = UPGRADE.write_upgrade(self.old, config, self.root / 'unapplied-environment')
        self.assertEqual(unchanged['preparation']['readiness'], 'INCOMPLETE')
        self.assertEqual(unchanged['scope']['executables']['python'], sys.executable)
        self.assertTrue(any(row['code'] == 'ENVIRONMENT_BINDINGS_NOT_APPLIED'
                            for row in unchanged['preparation']['diagnostics']))
        self.assertFalse(report['commands_executed'])
        config['base_materials']['scope']['executables']['python'] = str(changed_python)
        config['environment_bindings'] = {}
        corrected, _, _ = UPGRADE.build_upgrade(self.old, config, self.root / 'corrected-environment')
        self.assertEqual(corrected['preparation']['readiness'], 'READY')
        self.assertEqual(corrected['scope']['executables']['python'], str(changed_python))
        self.assertEqual(config['base_materials']['scope'], corrected['scope'])
        self.assertFalse(self.marker.exists())

    def test_incompatible_shared_requirements_fail_without_output(self):
        other = self.package('other', '1', 'other-v1')
        manifest = json.loads((other / 'capability.json').read_text())
        manifest['environment'][0] = {'id': 'python', 'kind': 'executable', 'version_max_exclusive': '3.10'}
        (other / 'capability.json').write_text(json.dumps(manifest))
        config = deepcopy(self.config2)
        config['selections'].append({'directory': str(other), 'version': '1', 'workpack_ids': ['MAKE']})
        with self.assertRaisesRegex(ValueError, 'do not intersect'):
            UPGRADE.write_upgrade(self.old, config, self.root / 'must-not-exist')
        self.assertFalse((self.root / 'must-not-exist').exists())

    def test_cli_writes_materials_only_and_preserves_old_output(self):
        path = self.root / 'next-config.json'
        path.write_text(json.dumps(self.config2))
        original = (self.old_output / 'materials.json').read_bytes()
        result = subprocess.run([sys.executable, '-I', '-B', str(ENTRY), '--previous',
                                 str(self.old_output / 'materials.json'), '--config', str(path),
                                 '--output', str(self.root / 'cli-materials')],
                                cwd=self.root, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        response = json.loads(result.stdout)
        self.assertEqual(response['readiness'], 'READY')
        self.assertFalse(response['commands_executed'])
        self.assertFalse(self.marker.exists())
        self.assertEqual((self.old_output / 'materials.json').read_bytes(), original)
        self.assertTrue(Path(response['transition']).is_file())


if __name__ == '__main__':
    unittest.main()
