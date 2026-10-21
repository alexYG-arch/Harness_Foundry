"""Project verifier handoff after removing the final capability.

Temporary project fixtures exercise the existing checker snapshot and a tiny
checker process. They are not target Harness, native receiver or model evidence.
"""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from harness_foundry_factory.verification_snapshot import snapshot_verifier

import test_capability_upgrade as upgrade_fixture


UPGRADE = upgrade_fixture.UPGRADE


class CapabilityUpgradeVerifierTests(unittest.TestCase):
    def setUp(self):
        # Reuse the existing project and old accepted-material fixture without
        # inheriting its test methods or causing discovery to run them twice.
        self.fixture = upgrade_fixture.CapabilityUpgradeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.project = self.fixture.project
        self.sources = self.fixture.sources
        self.old = self.fixture.old
        self.config = deepcopy(self.fixture.config1)
        self.config['selections'] = []
        self.base = self.config['base_materials']
        self.private = self.root / 'project-private'
        self.private.mkdir()
        self.verifier = self.root / 'project-verifier'
        self.verifier.mkdir()
        self.base['scope']['verification_root'] = str(self.verifier)
        self.base['scope']['verification_resources']['root'] = str(self.root / 'resources')
        self.output = self.root / 'project-only'
        self.rejection_index = 0

    def add_input(self, source, destination='expected.json', raw=b'{"value":7}\n', shared=None):
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(raw)
        row = {'source': str(source), 'path': destination}
        if shared is not None:
            row['shared'] = shared
        self.base['preparation']['verifier_inputs'].append(row)
        return row

    def assert_rejected_without_changes(self, config=None, message='protected verification'):
        self.rejection_index += 1
        output = self.root / ('rejected-' + str(self.rejection_index))
        before, original, old = self.fixture.tree(), deepcopy(config or self.config), deepcopy(self.old)
        with self.assertRaisesRegex(ValueError, message):
            UPGRADE.write_upgrade(self.old, config or self.config, output)
        self.assertEqual(self.fixture.tree(), before)
        self.assertEqual(config or self.config, original)
        self.assertEqual(self.old, old)
        self.assertFalse(output.exists())

    def test_private_inputs_are_not_exposed_by_read_roots_or_aliases(self):
        secret = self.private / 'expected.json'
        self.add_input(secret)
        alias = self.root / 'public-alias.json'
        alias.symlink_to(secret)
        for read_root in (self.private, secret, alias):
            with self.subTest(read_root=str(read_root)):
                config = deepcopy(self.config)
                config['base_materials']['scope']['source_read_roots'] = [str(read_root)]
                self.assert_rejected_without_changes(config)

    def test_project_source_cannot_also_be_a_private_expected_input(self):
        brief = self.sources / 'brief.md'
        self.base['preparation']['verifier_inputs'] = [{'source': str(brief), 'path': 'expected-brief.md'}]
        self.assert_rejected_without_changes()

    def test_private_inputs_stay_outside_workspace_even_outside_task_write_roots(self):
        self.add_input(self.project / 'private-reference/expected.json')
        self.assert_rejected_without_changes(message='separate from the workspace')

    def test_same_destination_and_bytes_are_deduplicated_without_mutating_base(self):
        first = self.add_input(self.private / 'first.json', 'references/expected.json')
        self.add_input(self.private / 'equivalent.json', 'references/expected.json', shared=False)
        self.base['scope']['verification_resources']['checker_files'] += ['references/expected.json']
        before, original = self.fixture.tree(), deepcopy(self.config)
        with patch('subprocess.Popen', side_effect=AssertionError('preparation must not execute')):
            materials, files, report = UPGRADE.build_upgrade(self.old, self.config, self.output)
        self.assertEqual(materials['preparation']['verifier_inputs'], [first])
        self.assertEqual(materials['preparation']['checker_files_fragment'], ['references/expected.json'])
        self.assertEqual(materials['scope']['verification_resources']['checker_files'],
                         ['project-check.py', 'references/expected.json'])
        self.assertEqual(materials['scope']['max_attempts'], 7)
        self.assertEqual(materials['scope']['max_task_attempts'], 4)
        self.assertEqual(materials['preparation']['readiness'], 'READY')
        self.assertFalse(report['budget_modified'])
        self.assertFalse(report['commands_executed'])
        self.assertEqual(files, {'sources/brief.md': (self.sources / 'brief.md').read_bytes()})
        self.assertEqual(self.fixture.tree(), before)
        self.assertEqual(self.config, original)

    def test_duplicate_destination_keeps_every_private_origin_isolated(self):
        self.add_input(self.private / 'first.json', 'expected.json')
        exposed = self.root / 'exposed-identical.json'
        self.add_input(exposed, 'expected.json')
        self.base['scope']['source_read_roots'] = [str(exposed)]
        self.assert_rejected_without_changes()

    def test_destination_content_conflict_is_rejected_before_writing(self):
        self.add_input(self.private / 'first.json', 'expected.json')
        self.add_input(self.private / 'different.json', 'expected.json', raw=b'{"value":8}\n')
        self.assert_rejected_without_changes(message='conflict')

    def test_shared_and_private_destination_conflict_is_rejected_in_either_order(self):
        self.add_input(self.private / 'first.json', 'expected.json', shared=False)
        self.add_input(self.private / 'same.json', 'expected.json', shared=True)
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                config = deepcopy(self.config)
                if reverse:
                    config['base_materials']['preparation']['verifier_inputs'].reverse()
                self.assert_rejected_without_changes(config, message='sharing conflict')

    def test_merged_checker_files_feed_indirect_dependency_to_actual_snapshot(self):
        dependency = self.private / 'oracle.json'
        original = b'{"value":731}\n'
        self.add_input(dependency, 'references/oracle.json', original)
        (self.verifier / 'project-check.py').write_text(
            'import json\nfrom pathlib import Path\n'
            'value = json.loads((Path(__file__).parent / "references/oracle.json").read_text())\n'
            'print(json.dumps(value))\n')
        (self.verifier / 'retained-note.txt').write_text('Existing explicitly declared checker dependency.\n')
        self.base['scope']['verification_resources']['checker_files'] += ['retained-note.txt']
        self.base['request']['plan']['workpacks'][0]['verification'] = [{
            'argv': ['python', '-I', '-B', 'verifier://project-check.py']}]
        original_base = deepcopy(self.base)
        old_files = self.fixture.tree()
        materials, report = UPGRADE.write_upgrade(self.old, self.config, self.output)
        self.assertEqual(materials['scope']['verification_resources']['checker_files'],
                         ['project-check.py', 'retained-note.txt', 'references/oracle.json'])
        self.assertFalse(materials['preparation']['protected_copy_created'])
        self.assertFalse((self.verifier / 'references/oracle.json').exists())
        self.assertTrue(all(self.fixture.tree()[name] == raw for name, raw in old_files.items()))
        self.assertEqual(self.base, original_base)
        self.assertFalse(report['commands_executed'])
        for row in materials['preparation']['verifier_inputs']:
            destination = self.verifier / row['path']
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(row['source'], destination)
        snapshot = snapshot_verifier(SimpleNamespace(database_path=self.root / 'control.sqlite3'),
                                     materials['request']['plan'], materials['scope'])
        runtime = Path(snapshot['runtime_root'])
        self.assertEqual(snapshot['files'],
                         ['project-check.py', 'references/oracle.json', 'retained-note.txt'])
        self.assertEqual((runtime / 'references/oracle.json').read_bytes(), original)
        self.assertEqual((runtime / 'retained-note.txt').read_bytes(),
                         (self.verifier / 'retained-note.txt').read_bytes())
        # Changes after snapshot must not redirect the checker to original inputs.
        dependency.write_text('{"value":999}\n')
        (self.verifier / 'references/oracle.json').write_text('{"value":888}\n')
        completed = subprocess.run([sys.executable, '-I', '-B', str(runtime / 'project-check.py')],
                                   cwd=self.project, capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), {'value': 731})
        self.assertFalse((self.root / 'control.sqlite3').exists())
        self.assertFalse((self.root / 'resources').exists())
        self.assertFalse(self.fixture.marker.exists())

    def test_explicit_shared_inputs_remain_usable_as_public_project_material(self):
        brief = self.sources / 'brief.md'
        self.base['preparation']['verifier_inputs'] = [
            {'source': str(brief), 'path': 'inputs/brief.md', 'shared': True}]
        workspace_input = self.project / 'inputs/data.json'
        self.add_input(workspace_input, 'inputs/data.json', b'{"rows":[1,2,3]}\n', shared=True)
        self.base['scope']['source_read_roots'] = [str(self.sources), str(workspace_input)]
        before = self.fixture.tree()
        materials, files, _ = UPGRADE.build_upgrade(self.old, self.config, self.output)
        self.assertEqual(materials['preparation']['readiness'], 'READY')
        self.assertEqual(materials['preparation']['verifier_inputs'], self.base['preparation']['verifier_inputs'])
        self.assertEqual(materials['scope']['source_read_roots'], self.base['scope']['source_read_roots'])
        self.assertEqual(materials['scope']['verification_resources']['checker_files'],
                         ['project-check.py', 'inputs/brief.md', 'inputs/data.json'])
        self.assertEqual(files['sources/brief.md'], brief.read_bytes())
        self.assertEqual(self.fixture.tree(), before)

    def test_empty_fragment_and_empty_project_inputs_still_need_no_capability(self):
        for config in ({'project_root': str(self.project), 'selections': []}, self.config):
            with self.subTest(project_base='base_materials' in config):
                before = self.fixture.tree()
                materials, _, report = UPGRADE.build_upgrade(self.old, config, self.output)
                self.assertEqual(materials['preparation']['readiness'], 'READY')
                self.assertEqual(materials['preparation']['selections'], [])
                self.assertEqual(materials['preparation']['verifier_inputs'], [])
                self.assertEqual(materials['preparation']['checker_files_fragment'], [])
                self.assertEqual(materials['tool_bindings'], {})
                self.assertFalse(report['commands_executed'])
                self.assertFalse(report['budget_modified'])
                self.assertEqual(self.fixture.tree(), before)
                if 'base_materials' in config:
                    self.assertEqual(materials['scope'], self.base['scope'])
                else:
                    self.assertNotIn('request', materials)
                    self.assertNotIn('scope', materials)

    def test_project_inputs_without_resource_mode_keep_fragment_without_enabling_resources(self):
        self.add_input(self.private / 'expected.json', 'references/expected.json')
        del self.base['scope']['verification_resources']
        original = deepcopy(self.config)
        materials, _, _ = UPGRADE.build_upgrade(self.old, self.config, self.output)
        self.assertEqual(materials['preparation']['readiness'], 'READY')
        self.assertEqual(materials['preparation']['checker_files_fragment'], ['references/expected.json'])
        self.assertEqual(materials['preparation']['verifier_inputs'], self.base['preparation']['verifier_inputs'])
        self.assertNotIn('verification_resources', materials['scope'])
        self.assertFalse(materials['preparation']['protected_copy_created'])
        self.assertEqual(self.config, original)


if __name__ == '__main__':
    unittest.main()
