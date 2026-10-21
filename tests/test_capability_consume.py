"""Host handoff and test-owned tools, not a real target Harness acceptance."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import venv


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / 'examples/capability-adapters/consume.py'
SPEC = importlib.util.spec_from_file_location('tested_capability_consume', ENTRY)
CONSUME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONSUME)
PREPARE = CONSUME._prepare


class CapabilityConsumeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='capability-consume-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / 'project with spaces'
        self.project.mkdir()
        self.package = self.project / 'packages' / 'echo-v1'
        self.package.mkdir(parents=True)
        self.output = self.root / 'materials'
        self.marker = self.root / 'calls.txt'
        (self.package / 'guide.md').write_text('Use the declared text tool.\n')
        (self.package / 'helper.txt').write_text('PUBLIC HELPER')
        (self.package / 'expected.json').write_text('{"private":"ORACLE-ONLY-4321"}\n')
        (self.package / 'tool.py').write_text(
            'import json, sys\nfrom pathlib import Path\n'
            'with Path(sys.argv[1]).open("a") as stream: stream.write("called\\n")\n'
            'print(json.dumps({"text": sys.argv[2], "helper": '
            'Path(__file__).with_name("helper.txt").read_text()}))\n')
        self.descriptor = {
            'name': 'echo', 'version': '1.0', 'usage': 'both',
            'inputs': ['text'], 'outputs': ['JSON'], 'materials': ['guide.md'],
            'tools': [{'id': 'echo-tool', 'path': 'tool.py', 'interpreter': 'python',
                       'interpreter_args': ['-I', '-B']}],
            'runtime_files': ['helper.txt'], 'verification_files': ['expected.json'],
            'environment': [{'id': 'python', 'kind': 'executable'}],
        }
        self.save_descriptor()
        self.config = {'project_root': str(self.project),
                       'selections': [{'directory': str(self.package), 'version': '1.0'}],
                       'environment_bindings': {'python': {'path': sys.executable}}}

    def save_descriptor(self):
        (self.package / 'capability.json').write_text(json.dumps(self.descriptor))

    def materials(self):
        return PREPARE.build_materials(self.config, self.output)[0]

    def execute(self, call):
        return subprocess.run(call['argv'], cwd=self.root, capture_output=True, text=True, timeout=15)

    def test_pure_handoff_then_actual_calls_preserve_new_inputs_once_each(self):
        materials = self.materials()
        original = deepcopy(materials)
        for value in ('first input', '第二份新输入'):
            with patch('subprocess.Popen', side_effect=AssertionError('handoff does not execute')):
                call = CONSUME.prepare_call(materials, 'echo-tool', [str(self.marker), value])
            self.assertFalse(call['commands_executed'])
            self.assertFalse(call['acceptance_granted'])
            self.assertEqual(call['version'], '1.0')
            result = self.execute(call)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {'text': value, 'helper': 'PUBLIC HELPER'})
        self.assertEqual(self.marker.read_text().splitlines(), ['called', 'called'])
        self.assertEqual(materials, original)
        self.assertFalse(self.output.exists())

    def test_changed_declared_files_stop_before_any_call(self):
        for relative in ('tool.py', 'helper.txt', 'expected.json', 'capability.json'):
            with self.subTest(relative=relative):
                materials = self.materials()
                path = self.package / relative
                original = path.read_bytes()
                path.write_bytes(original + b'\nchanged')
                try:
                    with self.assertRaisesRegex(ValueError, 'files changed'):
                        CONSUME.prepare_call(materials, 'echo-tool', [str(self.marker), 'must not run'])
                    self.assertFalse(self.marker.exists())
                finally:
                    path.write_bytes(original)

    def test_material_metadata_must_match_selected_descriptor_and_coverage(self):
        original = self.materials()
        changes = [
            lambda row: row['tool_bindings']['echo-tool'].update(version='2.0'),
            lambda row: row['tool_bindings']['echo-tool'].update(package='other'),
            lambda row: row['tool_bindings']['echo-tool']['argv_prefix'].__setitem__(-1, str(self.root / 'other.py')),
            lambda row: row['tool_bindings']['echo-tool']['argv_prefix'].__setitem__(1, '-E'),
            lambda row: row['preparation']['selections'][0].update(name='other'),
            lambda row: row['preparation']['selections'][0]['files'].pop(),
        ]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                materials = deepcopy(original)
                change(materials)
                with self.assertRaises(ValueError):
                    CONSUME.prepare_call(materials, 'echo-tool', [str(self.marker), 'bad metadata'])
        self.assertFalse(self.marker.exists())

    def test_unknown_tool_incomplete_and_non_string_args_do_not_start(self):
        materials = self.materials()
        with self.assertRaisesRegex(ValueError, 'absent'):
            CONSUME.prepare_call(materials, 'not-selected')
        with self.assertRaisesRegex(ValueError, 'strings'):
            CONSUME.prepare_call(materials, 'echo-tool', [123])
        materials['preparation']['readiness'] = 'INCOMPLETE'
        with self.assertRaisesRegex(ValueError, 'not READY'):
            CONSUME.prepare_call(materials, 'echo-tool')
        self.assertFalse(self.marker.exists())

    def test_append_preserves_actual_old_tool_handoff(self):
        sources = self.root / 'sources'
        sources.mkdir()
        (sources / 'brief.md').write_text('Test-owned handoff fixture.\n')
        self.config.update(source_root=str(sources), base_materials={
            'request': {'requirement_ir': {'sources': [
                {'source_id': 'BRIEF', 'path_or_uri': 'brief.md', 'loaded_completely': True}]},
                'plan': {'workpacks': [{'workpack_id': 'BUILD', 'inputs': []}]}},
            'source_manifest': [{'source_id': 'BRIEF', 'path': 'brief.md'}],
            'scope': {'workspace_root': str(self.root / 'target'), 'task_write_roots': {'BUILD': ['out']},
                      'executables': {}, 'source_read_roots': []}})
        self.config['selections'][0]['workpack_ids'] = ['BUILD']
        old = PREPARE.write_materials(self.config, self.output)
        other = self.project / 'packages/other'
        shutil.copytree(self.package, other)
        descriptor = deepcopy(self.descriptor)
        descriptor.update(name='other')
        descriptor['tools'][0]['id'] = 'other-tool'
        (other / 'capability.json').write_text(json.dumps(descriptor))
        combined = PREPARE.build_materials({
            'project_root': str(self.project), 'base_materials': old,
            'source_root': old['preparation']['source_root'],
            'selections': [{'directory': str(other), 'version': '1.0', 'workpack_ids': ['BUILD']}]},
            self.root / 'combined')[0]
        call = CONSUME.prepare_call(combined, 'echo-tool', [str(self.marker), 'old selection, new input'])
        result = self.execute(call)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['text'], 'old selection, new input')
        self.assertEqual(self.marker.read_text(), 'called\n')

    def test_parent_alias_preserves_final_venv_invocation(self):
        virtual = self.project / '.venv'
        venv.EnvBuilder(with_pip=False, symlinks=True).create(virtual)
        executable = virtual / 'bin/python'
        (self.package / 'tool.py').write_text('import sys\nprint(sys.prefix)\n')
        alias = self.root / 'project-alias'
        alias.symlink_to(self.project, target_is_directory=True)
        invocation = str(alias / '.venv/bin/python')
        self.config['environment_bindings']['python']['path'] = invocation
        materials = self.materials()
        call = CONSUME.prepare_call(materials, 'echo-tool', [str(self.marker), 'alias input'])
        self.assertEqual(call['argv'][0], invocation)
        self.assertNotEqual(call['argv'][0], str(Path(sys.executable).resolve()))
        result = self.execute(call)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(result.stdout.strip()).resolve(), virtual)
        materials['scope_fragment']['executables']['python'] = str(executable)
        self.assertEqual(CONSUME.prepare_call(materials, 'echo-tool')['argv'][0], str(executable))

    def test_different_venv_and_changed_interpreter_object_are_not_silently_rebound(self):
        for name in ('venv-one', 'venv-two'):
            directory = self.project / name / 'bin'
            directory.mkdir(parents=True)
            (directory / 'python').symlink_to(sys.executable)
        first = self.project / 'venv-one/bin/python'
        self.config['environment_bindings']['python']['path'] = str(first)
        materials = self.materials()
        materials['scope_fragment']['executables']['python'] = str(self.project / 'venv-two/bin/python')
        with self.assertRaisesRegex(ValueError, 'observation changed'):
            CONSUME.prepare_call(materials, 'echo-tool')
        materials = self.materials()
        replacement = self.project / 'replacement-interpreter'
        replacement.write_text('#!/bin/sh\nexit 0\n')
        replacement.chmod(0o755)
        first.unlink()
        first.symlink_to(replacement)
        with self.assertRaisesRegex(ValueError, 'observation changed'):
            CONSUME.prepare_call(materials, 'echo-tool')
        self.assertFalse(self.marker.exists())

    def test_nested_executable_uses_prepared_observation(self):
        materials = self.materials()
        call = CONSUME.prepare_call(materials, 'echo-tool', ['executable://python'])
        self.assertEqual(call['local_argv'][-1], 'executable://python')
        self.assertEqual(call['argv'][-1], sys.executable)
        with self.assertRaisesRegex(ValueError, 'not bound'):
            CONSUME.prepare_call(materials, 'echo-tool', ['executable://unselected'])

    def test_native_tool_is_bound_to_selected_file(self):
        native = self.package / 'native-tool'
        native.write_text('#!/bin/sh\nprintf "native:%s\\n" "$1"\n')
        native.chmod(0o755)
        self.descriptor['tools'] = [{'id': 'native-tool', 'path': 'native-tool'}]
        self.descriptor['environment'] = []
        self.save_descriptor()
        materials = self.materials()
        call = CONSUME.prepare_call(materials, 'native-tool', ['new input'])
        result = self.execute(call)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'native:new input\n')
        materials['scope_fragment']['executables']['native-tool'] = sys.executable
        with self.assertRaisesRegex(ValueError, 'native executable differs'):
            CONSUME.prepare_call(materials, 'native-tool')

    def test_host_checks_private_file_but_handoff_has_no_private_dependency(self):
        materials = self.materials()
        private = self.package / 'expected.json'
        reads = []
        original = Path.read_bytes

        def observed(path):
            reads.append(path)
            return original(path)

        with patch.object(Path, 'read_bytes', observed):
            call = CONSUME.prepare_call(materials, 'echo-tool', [str(self.marker), 'public input'])
        self.assertIn(private, reads)
        for root in materials['scope_fragment']['source_read_roots']:
            self.assertFalse(private.is_relative_to(Path(root)))
        self.assertNotIn(str(private), json.dumps(call))
        self.assertNotIn('ORACLE-ONLY-4321', json.dumps(call))
        result = self.execute(call)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('ORACLE-ONLY-4321', result.stdout)

    def test_cli_only_reports_handoff_and_failure_does_not_execute(self):
        PREPARE.write_materials(self.config, self.output)
        command = [sys.executable, '-B', str(ENTRY), '--materials', str(self.output / 'materials.json'),
                   '--tool', 'echo-tool', '--', str(self.marker), 'CLI new input']
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['argv'][-1], 'CLI new input')
        self.assertFalse(self.marker.exists())
        (self.package / 'helper.txt').write_text('changed helper')
        failed = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(failed.returncode, 1)
        self.assertFalse(json.loads(failed.stdout)['commands_executed'])
        self.assertFalse(self.marker.exists())


if __name__ == '__main__':
    unittest.main()
