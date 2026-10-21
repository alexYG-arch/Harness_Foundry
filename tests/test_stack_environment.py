"""Shared environment handoff contracts, real finite child calls, no models."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = ROOT / 'examples/capability-adapters'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ADAPTERS / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


RUNTIME = load('stack_runtime_tests', 'stack_runtime.py')
PREPARE = load('stack_prepare_tests', 'prepare.py')
HANDOFF = load('stack_handoff_tests', 'stack_handoff.py')
UPGRADE = load('stack_upgrade_tests', 'upgrade.py')


class StackEnvironmentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='stack environment 中文 ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        self.package = self.root / 'package'
        self.package.mkdir()
        (self.package / 'guide.md').write_text('Public environment usage')
        (self.package / 'tool.py').write_text('print("public")\n')
        (self.package / 'private.py').write_text('SECRET_EXPECTATION_47 = True\n')
        (self.package / 'stack_runtime.py').write_bytes((ADAPTERS / 'stack_runtime.py').read_bytes())
        self.descriptor = {'name': 'stack-example', 'version': '1', 'usage': 'both',
            'inputs': ['public profile'], 'outputs': ['command report'], 'materials': ['guide.md'],
            'tools': [{'id': 'stack-example', 'path': 'tool.py', 'interpreter': 'aux-python'}],
            'runtime_files': ['stack_runtime.py'], 'verification_files': ['private.py', {'path': 'stack_runtime.py', 'shared': True}],
            'environment': [{'id': 'aux-python', 'kind': 'executable'}]}
        self.save_descriptor()
        self.profile = RUNTIME.make_profile({'name': 'stack-example', 'version': '1'},
            {'aux-python': sys.executable}, operations=['probe'])
        self.profile_path = self.root / 'profile.json'
        RUNTIME.write_new_json(self.profile_path, self.profile)
        self.config = {'project_root': str(self.project), 'selections': [{
            'directory': str(self.package), 'version': '1', 'environment_profile': str(self.profile_path)}]}

    def save_descriptor(self):
        (self.package / 'capability.json').write_text(json.dumps(self.descriptor))

    def test_profile_no_process_and_invocation_aliases_remain(self):
        alias = self.root / 'parent alias'
        alias.symlink_to(self.root, target_is_directory=True)
        with patch('subprocess.Popen', side_effect=AssertionError('pure only')):
            value = RUNTIME.make_profile({'name': 'example', 'version': '1'}, {'helper': sys.executable}, operations=['probe'])
            self.assertEqual(value['format_version'], 1)
            materials, _ = PREPARE.build_materials(self.config, self.root / 'prepared')
        self.assertEqual(materials['preparation']['readiness'], 'READY')
        self.assertFalse(materials['preparation']['commands_executed'])

    def test_environment_conflicts_and_no_global_mutation(self):
        profile = deepcopy(self.profile)
        profile['environment'] = {'set': {'CHOICE': 'project'}, 'prepend': {'PATH': ['/one', '/two', '/one']}}
        before = dict(os.environ)
        env = RUNTIME.child_environment(profile, {'PATH': '/two:/three', 'KEEP': 'yes'})
        self.assertEqual(env, {'PATH': '/one:/two:/three', 'KEEP': 'yes', 'CHOICE': 'project'})
        self.assertEqual(dict(os.environ), before)
        profile['environment']['set']['PATH'] = '/conflict'
        with self.assertRaises(ValueError):
            RUNTIME.child_environment(profile)

    def successful_probe(self, profile=None):
        p = profile or self.profile
        return {'status': 'PASS', 'complete': True, 'operation': 'probe',
                'profile_sha256': RUNTIME.profile_digest(p), 'receiver': {'network': 'NONE', 'operation': 'local'}}

    def test_reuse_same_conditions_and_business_input_not_in_key(self):
        report = self.successful_probe()
        report['business_input'] = 'old'
        self.assertEqual(RUNTIME.reuse_probe(self.profile, report, report['receiver'])['decision'], 'REUSE')
        report['business_input'] = 'new'
        self.assertEqual(RUNTIME.reuse_probe(self.profile, report, report['receiver'])['decision'], 'REUSE')

    def test_inplace_dependency_change_reprobes_without_version_change(self):
        dependency = self.root / 'module.py'
        dependency.write_text('VALUE = 1\n')
        report = self.successful_probe()
        report['observations'] = [RUNTIME.file_observation(dependency)]
        self.assertEqual(RUNTIME.reuse_probe(self.profile, report, report['receiver'])['decision'], 'REUSE')
        dependency.write_text('VALUE = 2\n')
        self.assertEqual(RUNTIME.reuse_probe(self.profile, report, report['receiver'])['decision'], 'REPROBE')
        dependency.unlink()
        self.assertEqual(RUNTIME.reuse_probe(self.profile, report, report['receiver'])['decision'], 'UNKNOWN')

    def test_alias_target_change_reprobes_even_when_old_library_is_unchanged(self):
        old = self.root / 'old-library'
        new = self.root / 'new-library'
        old.write_text('same bytes')
        new.write_text('same bytes')
        alias = self.root / 'selected-link'
        alias.symlink_to(old)
        profile = deepcopy(self.profile)
        profile['observations'].append(RUNTIME.file_observation(old))
        profile['extensions']['path_aliases'] = [RUNTIME.alias_observation(alias)]
        report = self.successful_probe(profile)
        self.assertEqual(RUNTIME.reuse_probe(profile, report, report['receiver'])['decision'], 'REUSE')
        old_bytes = old.read_bytes()
        alias.unlink()
        alias.symlink_to(new)
        self.assertEqual(RUNTIME.reuse_probe(profile, report, report['receiver'])['decision'], 'REPROBE')
        self.assertEqual(old.read_bytes(), old_bytes)

    def test_unreadable_alias_is_unknown_but_known_changed_dangling_target_reprobes(self):
        target = self.root / 'target'
        target.write_text('bound')
        alias = self.root / 'link'
        alias.symlink_to(target)
        profile = deepcopy(self.profile)
        profile['extensions']['path_aliases'] = [RUNTIME.alias_observation(alias)]
        report = self.successful_probe(profile)
        with patch.object(RUNTIME.os, 'readlink', side_effect=PermissionError('fixture permission denial')):
            self.assertEqual(RUNTIME.reuse_probe(profile, report, report['receiver'])['decision'], 'UNKNOWN')
        alias.unlink()
        alias.symlink_to(self.root / 'missing-new-target')
        self.assertEqual(RUNTIME.reuse_probe(profile, report, report['receiver'])['decision'], 'REPROBE')
        alias.unlink()
        self.assertEqual(RUNTIME.reuse_probe(profile, report, report['receiver'])['decision'], 'UNKNOWN')

    def test_alias_parent_proposal_is_explicit_profile_input_not_an_authorization(self):
        lookup = self.root / 'lookup'
        lookup.mkdir()
        target = self.root / 'chosen-library'
        target.write_text('chosen')
        link = lookup / 'chosen'
        link.symlink_to(target)
        self.profile['read_paths'].append(str(lookup))
        self.profile['extensions']['path_aliases'] = [RUNTIME.alias_observation(link)]
        self.profile_path.write_text(json.dumps(self.profile))
        with patch.object(RUNTIME.subprocess, 'Popen', side_effect=AssertionError('no process')):
            materials, files = PREPARE.build_materials(self.config, self.root / 'prepared')
        self.assertIn(str(lookup), materials['scope_fragment']['source_read_roots'])
        self.assertFalse(materials['preparation']['commands_executed'])
        captured = json.loads(files['sources/capabilities/stack-example/environment.json'])
        self.assertEqual(captured['extensions']['path_aliases'], self.profile['extensions']['path_aliases'])

    def test_incomplete_or_other_receiver_never_reuses(self):
        report = self.successful_probe()
        self.assertEqual(RUNTIME.reuse_probe(self.profile, report, {'network': 'OTHER'})['decision'], 'REPROBE')
        report['complete'] = False
        self.assertEqual(RUNTIME.reuse_probe(self.profile, report, report['receiver'])['decision'], 'UNKNOWN')

    def test_capture_real_process_once_and_retrieval_never_replays(self):
        directory = self.root / 'capture'
        marker = self.root / 'marker'
        command = [sys.executable, '-I', '-B', '-c', 'from pathlib import Path; p=Path(' + repr(str(marker)) + '); p.write_text(p.read_text()+"x" if p.exists() else "x"); print("done")']
        result = RUNTIME.run_capture(command, self.root, directory, timeout=20)
        self.assertEqual((result['status'], result['returncode']), ('FINISHED', 0))
        with patch.object(RUNTIME.subprocess, 'Popen', side_effect=AssertionError('no replay')):
            for _ in range(2):
                self.assertTrue(RUNTIME.read_capture(directory)['complete'])
        self.assertEqual(marker.read_text(), 'x')
        with self.assertRaises(FileExistsError):
            RUNTIME.run_capture(command, self.root, directory)
        self.assertEqual(marker.read_text(), 'x')
        (directory / 'stdout.txt').unlink()
        with self.assertRaises(ValueError):
            RUNTIME.read_capture(directory)

    def test_timeout_and_spawn_failure_are_captured_not_retried(self):
        result = RUNTIME.run_capture([sys.executable, '-I', '-c', 'import time; time.sleep(5)'],
                                     self.root, self.root / 'timeout', timeout=.05)
        self.assertEqual(result['status'], 'TIMEOUT')
        self.assertTrue(result['complete'])
        result = RUNTIME.run_capture([str(self.root / 'absent-tool')], self.root, self.root / 'spawn')
        self.assertEqual(result['status'], 'ERROR')
        self.assertFalse(result['commands_executed'])

    def test_failed_cleanup_is_bounded_unknown_and_not_replayed(self):
        child = Mock(pid=12345)
        child.wait.side_effect = RUNTIME.subprocess.TimeoutExpired('child', 1)
        with patch.object(RUNTIME.subprocess, 'Popen', return_value=child), patch.object(RUNTIME.os, 'killpg', side_effect=PermissionError):
            result = RUNTIME.run_capture([sys.executable, '-c', 'pass'], self.root, self.root / 'cleanup', timeout=.1)
        self.assertFalse(result['complete'])
        self.assertTrue(result['cleanup_unresolved'])
        self.assertEqual(child.wait.call_count, 2)
        self.assertTrue(all(call.kwargs.get('timeout') is not None for call in child.wait.call_args_list))
        with patch.object(RUNTIME.subprocess, 'Popen', side_effect=AssertionError('no replay')):
            with self.assertRaises(ValueError):
                RUNTIME.read_capture(self.root / 'cleanup')

    def test_incomplete_dependency_observation_is_unknown_not_failed_operation(self):
        report = self.successful_probe()
        report['observations_complete'] = False
        self.assertEqual(RUNTIME.reuse_probe(self.profile, report, report['receiver'])['decision'], 'UNKNOWN')
        self.assertEqual(report['status'], 'PASS')

    def test_handoff_keeps_business_separator_and_profile_argument(self):
        materials, _ = PREPARE.build_materials(self.config, self.root / 'prepared')
        args = ['run', '--module-name', 'project_module', '--', '--profile', 'business.json']
        call = HANDOFF.prepare_call(materials, 'stack-example', args)
        tail = call['argv'][call['argv'].index('run'):]
        self.assertEqual(tail, ['run', '--profile', str(self.profile_path), *args[1:]])

    def test_public_delivery_version_is_a_single_directory(self):
        self.descriptor['version'] = '../../outside'
        self.save_descriptor()
        self.config['selections'][0]['version'] = '../../outside'
        self.profile['package']['version'] = '../../outside'
        self.profile_path.write_text(json.dumps(self.profile))
        materials, _ = PREPARE.build_materials(self.config, self.root / 'prepared')
        delivery = self.root / 'delivery'
        result = HANDOFF.public_delivery(materials, delivery)
        self.assertEqual(result['selections'][0]['version'], '../../outside')
        self.assertFalse((self.root / 'outside').exists())
        self.assertTrue(all((delivery / row['path']).resolve().is_relative_to(delivery) for row in result['files']))

    def test_profile_is_public_source_and_protected_shared_input(self):
        materials, files = PREPARE.build_materials(self.config, self.root / 'prepared')
        rows = materials['preparation']['verifier_inputs']
        profile = next(r for r in rows if r['path'].endswith('/environment.json'))
        self.assertTrue(profile['shared'])
        self.assertIn('sources/capabilities/stack-example/environment.json', files)
        self.assertNotIn(b'SECRET_EXPECTATION_47', b''.join(files.values()))
        call = HANDOFF.prepare_call(materials, 'stack-example', ['probe'])
        self.assertEqual(call['argv'][-2:], ['--profile', str(self.profile_path)])
        self.assertFalse(call['commands_executed'])
        with self.assertRaises(ValueError):
            HANDOFF.prepare_call(materials, 'stack-example', ['probe', '--profile=/other'])

    def test_profile_drift_invalidates_consumption_without_execution(self):
        materials, _ = PREPARE.build_materials(self.config, self.root / 'prepared')
        self.profile_path.write_text('{}')
        self.assertEqual(PREPARE.check_selection(materials)['status'], 'CHANGED')
        with self.assertRaises(ValueError):
            HANDOFF.prepare_call(materials, 'stack-example', ['probe'])

    def test_distinct_role_bindings_and_conflict(self):
        self.config['environment_bindings'] = {'aux-python': {'path': str(self.root / 'other-python')}}
        with self.assertRaisesRegex(ValueError, 'differs'):
            PREPARE.build_materials(self.config, self.root / 'prepared')

    def test_public_delivery_contains_no_private_checker_or_local_profile(self):
        materials, _ = PREPARE.build_materials(self.config, self.root / 'prepared')
        delivery = self.root / 'delivery'
        result = HANDOFF.public_delivery(materials, delivery)
        self.assertFalse(result['private_checkers_included'])
        self.assertFalse(result['local_bindings_included'])
        content = b'\n'.join(p.read_bytes() for p in delivery.rglob('*') if p.is_file())
        self.assertNotIn(b'SECRET_EXPECTATION_47', content)
        self.assertFalse(any(p.name in ('private.py', 'environment.json') for p in delivery.rglob('*')))
        self.assertTrue((delivery / 'capabilities/stack-example/1/stack_runtime.py').is_file())
        with self.assertRaises(FileExistsError):
            HANDOFF.public_delivery(materials, delivery)

    def test_reprepare_from_project_base_preserves_failure_and_budget(self):
        self.descriptor['environment'][0]['version_min'] = '3.11'
        self.save_descriptor()
        old, _ = PREPARE.build_materials(self.config, self.root / 'old')
        self.assertEqual(old['preparation']['readiness'], 'INCOMPLETE')
        before = deepcopy(old)
        config = deepcopy(self.config)
        config['environment_bindings'] = {'aux-python': {'path': sys.executable, 'observed_version': '3.14.5'}}
        new, _, transition = UPGRADE.build_upgrade(old, config, self.root / 'new')
        self.assertEqual(new['preparation']['readiness'], 'READY')
        self.assertEqual(old, before)
        self.assertTrue(transition['previous_diagnostics'])
        self.assertFalse(transition['authority_inherited'])
        self.assertFalse(transition['budget_modified'])
        self.assertEqual(transition['packages'][0]['changes'], ['UNCHANGED'])
        config['base_materials'] = old
        with self.assertRaisesRegex(ValueError, 'not capability-expanded'):
            UPGRADE.build_upgrade(old, config, self.root / 'bad')

    def test_profile_alias_inside_write_domain_is_rejected(self):
        writable = self.project / 'writable'
        writable.mkdir()
        link = writable / 'profile.json'
        link.symlink_to(self.profile_path)
        alias = self.root / 'project alias'
        alias.symlink_to(self.project, target_is_directory=True)
        self.config['selections'][0]['environment_profile'] = str(alias / 'writable/profile.json')
        self.config['source_root'] = str(self.root)
        self.config['base_materials'] = {'request': {'requirement_ir': {'sources': []}, 'plan': {'workpacks': []}},
            'source_manifest': [], 'scope': {'workspace_root': str(self.project),
            'task_write_roots': {'BUILD': ['writable']}}}
        with self.assertRaisesRegex(ValueError, 'write roots'):
            PREPARE.build_materials(self.config, self.root / 'prepared')

    def test_profile_snapshot_parse_and_source_use_the_same_read(self):
        # An editor can replace a file between reads. Parse the captured bytes,
        # never an earlier independent read with a newer source snapshot.
        original = Path.read_text
        newer = deepcopy(self.profile)
        newer['environment']['set'] = {'CHOICE': 'new'}
        reads = []
        def changing_read(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            if path == self.profile_path:
                reads.append('independent parse')
                path.write_text(json.dumps(newer))
            return value
        with patch.object(Path, 'read_text', changing_read):
            materials, files = PREPARE.build_materials(self.config, self.root / 'prepared')
        self.assertEqual(reads, [])
        saved = json.loads(files['sources/capabilities/stack-example/environment.json'])
        self.assertEqual(saved, self.profile)
        self.assertEqual(materials['preparation']['stack_profiles'][0]['sha256'], RUNTIME.file_observation(self.profile_path)['sha256'])

    def test_missing_declared_profile_fields_fail_as_format_errors(self):
        for key in ('platform', 'environment'):
            value = deepcopy(self.profile)
            del value[key]
            with self.assertRaises(ValueError):
                RUNTIME.validate_profile(value)

    def test_wrong_package_profile_fails_before_writing(self):
        self.profile['package']['version'] = '2'
        self.profile_path.write_text(json.dumps(self.profile))
        with self.assertRaises(ValueError):
            PREPARE.build_materials(self.config, self.root / 'prepared')
        self.assertFalse((self.root / 'prepared').exists())


if __name__ == '__main__':
    unittest.main()
