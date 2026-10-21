"""WP04 DATA delivery fixtures, not real target or cross-device acceptance.

Version 2 is made only in each temporary fixture. The ordinary-file helpers
receive the actual emitted target baseline, never an inferred package baseline.
No Program, authorization, budget or existing acceptance record is created here.
"""

from contextlib import redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_capability_data as data_fixture


ROOT = Path(__file__).resolve().parents[1]


def load_helper(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONSUME = load_helper('wp04_delivery_consume', 'examples/capability-adapters/consume.py')
MERGE = load_helper('wp04_delivery_merge', 'examples/harness-composition-upgrade/helpers/merge.py')
APPLY = load_helper('wp04_delivery_apply', 'examples/harness-composition-upgrade/helpers/apply.py')


class CapabilityDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = data_fixture.CapabilityDataTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.v1 = self.fixture.package
        self.v2 = self.root / 'engineering-version-2'
        shutil.copytree(self.v1, self.v2)
        descriptor = json.loads((self.v2 / 'capability.json').read_text())
        descriptor['version'] = '2'
        (self.v2 / 'capability.json').write_text(json.dumps(descriptor))
        script = self.v2 / 'summarize_csv.py'
        script.write_bytes(script.read_bytes() + b'\n# Engineering-only version 2 revision.\n')
        self.old_package = self.tree(self.v1)
        self.materials = {version: CONSUME._prepare.build_materials({
            'project_root': str(self.root),
            'selections': [{'directory': str(package), 'version': version}],
            'environment_bindings': {'python': {
                'path': sys.executable, 'observed_version': '.'.join(map(str, sys.version_info[:3]))}},
        }, self.root / ('materials-' + version))[0]
            for version, package in (('1', self.v1), ('2', self.v2))}
        self.target = self.root / 'delivered-target'
        self.target.mkdir()
        self.tool = 'tools/summarize_csv.py'
        # This project-specific emitted wrapper comment makes actual G differ
        # from package bytes. It must survive in the historical baseline.
        prefix = b'# DATA tool emitted for this project.\n'
        self.write(self.target / self.tool, prefix + (self.v1 / 'summarize_csv.py').read_bytes())
        self.write(self.target / 'project.json', self.fixture.config_path.read_bytes())
        self.baseline = self.root / 'old-generated-baseline'
        shutil.copytree(self.target, self.baseline)
        self.old_g = self.tree(self.baseline)
        self.proposed = self.root / 'candidate-assembly'
        self.write(self.proposed / self.tool, prefix + (self.v2 / 'summarize_csv.py').read_bytes())
        self.write(self.proposed / 'project.json', self.fixture.config_path.read_bytes())
        self.counter = 0

    @staticmethod
    def write(path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    @staticmethod
    def tree(root):
        return {str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob('*') if path.is_file()}

    def merge(self, paths=None, unknown_g=(), owners=None):
        self.counter += 1
        work = self.root / ('merge-' + str(self.counter))
        work.mkdir()

        def state(path):
            if not path.exists():
                return {'missing': True}
            return {'file': os.path.relpath(path, work),
                    'executable': bool(path.stat().st_mode & 0o111)}

        rows = []
        for relative in paths or [self.tool, 'project.json']:
            current = self.target / relative
            saved = work / 'current' / relative
            if current.exists():
                self.write(saved, current.read_bytes())
                saved.chmod(current.stat().st_mode)
            rows.append({'path': relative,
                         'C': state(saved),
                         'G': None if relative in unknown_g else state(self.baseline / relative),
                         'N': state(self.proposed / relative),
                         'owners': (owners or {}).get(relative, ['data-summary'])})
        manifest = work / 'inputs.json'
        manifest.write_text(json.dumps({'format_version': 1, 'files': rows}))
        candidate = work / 'candidate'
        return MERGE.merge(manifest, candidate), candidate

    def apply_manifest(self, report, candidate, unmanaged=()):
        self.assertEqual(report['status'], 'READY')
        rows = []
        for row in report['files']:
            expected, desired = row['inputs']['C'], row['resolved']
            if row['path'] in unmanaged:
                action = 'leave-unmanaged'
            elif desired.get('missing'):
                action = 'remove'
            elif expected.get('missing'):
                action = 'create'
            else:
                action = 'update'
            rows.append({'path': row['path'], 'action': action,
                         'expected': expected, 'desired': desired})
        manifest = candidate / 'apply-intents.json'
        manifest.write_text(json.dumps({'format_version': 1, 'files': rows}))
        return manifest

    def apply(self, manifest):
        with redirect_stdout(io.StringIO()):
            return APPLY.apply(manifest, self.target, 'diagnostics/apply.json')

    def assert_history(self):
        self.assertEqual(self.tree(self.v1), self.old_package)
        self.assertEqual(self.tree(self.baseline), self.old_g)

    def test_selected_versions_match_executed_entries_and_delivered_upgrade_keeps_custom_config(self):
        before = deepcopy(self.materials)
        custom = deepcopy(self.fixture.config)
        custom['metrics'][0]['scale'] = 3
        self.write(self.target / 'project.json', json.dumps(custom).encode())
        current_config = (self.target / 'project.json').read_bytes()
        report, candidate = self.merge()
        self.assertEqual([row['selected'] for row in report['files']], ['N', 'C'])
        self.assertEqual(report['files'][0]['source_refs']['G'], str(self.baseline / self.tool))
        self.assertNotEqual((self.baseline / self.tool).read_bytes(), (self.v1 / 'summarize_csv.py').read_bytes())
        applied = self.apply(self.apply_manifest(report, candidate))
        self.assertEqual([row['status'] for row in applied['files']], ['APPLIED', 'ALREADY_DESIRED'])
        self.assertEqual((self.target / 'project.json').read_bytes(), current_config)
        self.assertEqual((self.target / self.tool).read_bytes(), (self.proposed / self.tool).read_bytes())

        # Independent new input and explicit oracle; neither comes from output.
        self.fixture.source.write_text('item,team,amount,unit,stage\na,north,0.25,yuan,yes\nb,north,25,fen,yes\nc,south,broken,bad,no\n')
        oracle = deepcopy(self.fixture.oracle)
        oracle['groups'][0]['metrics']['amount'] = data_fixture.value('0.500', 1, 2, 'yuan')
        oracle['groups'][0]['metrics']['average'] = data_fixture.value('0.25', 1, 4, 'yuan/item')
        oracle['rows'][0]['contributions']['amount'] = data_fixture.fraction(1, 4)
        self.fixture.expected.write_text(json.dumps(oracle))
        common_args = ['--input', str(self.fixture.source), '--config', str(self.target / 'project.json')]
        for version, package in (('1', self.v1), ('2', self.v2)):
            output = self.root / ('selected-' + version + '.json')
            call = CONSUME.prepare_call(self.materials[version], 'summarize-csv',
                                        [*common_args, '--output', str(output)])
            self.assertEqual(call['version'], version)
            self.assertEqual(call['argv'][3], str(package / 'summarize_csv.py'))
            completed = subprocess.run(call['argv'], cwd=self.root, capture_output=True, text=True, timeout=15)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            actual = json.loads(output.read_text())
            self.assertEqual({key: actual[key] for key in oracle}, oracle)
        completed = subprocess.run([sys.executable, '-I', '-B', str(self.target / self.tool),
                                    *common_args, '--output', str(self.fixture.output)],
                                   cwd=self.target, capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.fixture.config_path = self.target / 'project.json'
        checked = self.fixture.run_check(checker=self.v2 / 'check_summary.py')
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(json.loads(self.fixture.report.read_text())['status'], 'CHECKS_PASS')
        self.assertEqual(self.materials, before)
        self.assert_history()

    def test_local_tool_edit_conflicts_and_missing_actual_g_does_not_invent_a_baseline(self):
        current = self.target / self.tool
        current.write_bytes(current.read_bytes() + b'\n# Project customization.\n')
        before = self.tree(self.target)
        conflict, _ = self.merge(paths=[self.tool])
        self.assertEqual(conflict['status'], 'CONFLICT')
        self.assertIsNone(conflict['files'][0]['resolved'])
        unknown, _ = self.merge(paths=[self.tool], unknown_g=[self.tool])
        self.assertEqual(unknown['status'], 'PROJECT_INCREMENTAL_REQUIRED')
        self.assertIsNone(unknown['files'][0]['inputs']['G'])
        self.assertEqual(self.tree(self.target), before)
        self.assert_history()

    def test_explicit_removal_keeps_shared_runtime_custom_configuration_and_unmanaged_files(self):
        shared = 'shared/runtime-note.txt'
        self.write(self.target / shared, b'Used by DATA and another selected consumer.\n')
        self.write(self.baseline / shared, (self.target / shared).read_bytes())
        self.write(self.proposed / shared, (self.target / shared).read_bytes())
        self.old_g = self.tree(self.baseline)
        self.write(self.target / 'user-notes.txt', b'Project-owned notes.\n')
        self.write(self.target / 'sdk-installed-by-user/header.h', b'User-owned SDK.\n')
        custom = (self.target / 'project.json').read_bytes() + b'\n'
        self.write(self.target / 'project.json', custom)
        (self.proposed / self.tool).unlink()
        report, candidate = self.merge(paths=[self.tool, shared, 'project.json'],
                                       owners={self.tool: ['data-summary'], shared: ['data-summary', 'other-consumer'],
                                               'project.json': ['project']})
        result = self.apply(self.apply_manifest(report, candidate, unmanaged=['project.json']))
        self.assertEqual([row['status'] for row in result['files']], ['APPLIED', 'ALREADY_DESIRED', 'LEFT_UNMANAGED'])
        self.assertFalse((self.target / self.tool).exists())
        self.assertEqual((self.target / shared).read_bytes(), (self.baseline / shared).read_bytes())
        self.assertEqual((self.target / 'project.json').read_bytes(), custom)
        self.assertEqual((self.target / 'user-notes.txt').read_bytes(), b'Project-owned notes.\n')
        self.assertEqual((self.target / 'sdk-installed-by-user/header.h').read_bytes(), b'User-owned SDK.\n')
        self.assertTrue(Path(CONSUME.prepare_call(self.materials['1'], 'summarize-csv')['argv'][3]).exists())
        self.assert_history()

    def test_interrupted_apply_resumes_pending_file_without_rewriting_applied_tool(self):
        config = deepcopy(self.fixture.config)
        config['metrics'][0]['scale'] = 3
        self.write(self.proposed / 'project.json', json.dumps(config).encode())
        report, candidate = self.merge()
        manifest = self.apply_manifest(report, candidate)
        original = APPLY.fs.atomic_write
        calls = []

        def interrupt_second(path, *args, **kwargs):
            calls.append(Path(path))
            if Path(path) == self.target / 'project.json':
                raise OSError('fixture: interrupted second ordinary-file write')
            return original(path, *args, **kwargs)

        with patch.object(APPLY.fs, 'atomic_write', side_effect=interrupt_second):
            with self.assertRaisesRegex(OSError, 'interrupted second'):
                self.apply(manifest)
        incomplete = (self.target / 'diagnostics/apply.json').read_bytes()
        self.assertEqual(json.loads(incomplete)['status'], 'INCOMPLETE')
        self.assertEqual(json.loads(incomplete)['files'], [{'path': self.tool, 'action': 'update', 'status': 'APPLIED'}])
        self.write(candidate / 'first-apply-diagnostic.json', incomplete)
        tool_stat = (self.target / self.tool).stat()
        with patch.object(APPLY.fs, 'atomic_write', wraps=original) as writes:
            resumed = self.apply(manifest)
        self.assertEqual([row['status'] for row in resumed['files']], ['ALREADY_DESIRED', 'APPLIED'])
        self.assertNotIn(self.target / self.tool, [Path(call.args[0]) for call in writes.call_args_list])
        self.assertEqual((self.target / self.tool).stat().st_mtime_ns, tool_stat.st_mtime_ns)
        self.assertEqual((candidate / 'first-apply-diagnostic.json').read_bytes(), incomplete)
        self.assertEqual((self.target / 'project.json').read_bytes(), (self.proposed / 'project.json').read_bytes())
        self.assert_history()


if __name__ == '__main__':
    unittest.main()
