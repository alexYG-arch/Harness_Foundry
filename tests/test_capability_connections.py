"""E1 local connection/preparation tests, not plugin/service/model acceptance."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / 'examples/capability-adapters'


def load(name):
    spec = importlib.util.spec_from_file_location('connection_test_' + name, HELPERS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


C = load('connections')
P = load('prepare')


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='external connection 中文 ')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.instance = self.root / 'instance'; self.instance.mkdir()
        self.project = self.root / 'project'; self.project.mkdir()
        self.package = self.make_plugin('provider')

    def make_plugin(self, name):
        root = self.root / name
        (root / '.codex-plugin').mkdir(parents=True)
        (root / '.codex-plugin/plugin.json').write_text(json.dumps({'name': name, 'version': '1', 'skills': './skills/'}))
        for skill in ['review', 'init']:
            path = root / 'skills' / skill / 'SKILL.md'; path.parent.mkdir(parents=True)
            path.write_text('---\nname: ' + skill + '\ndescription: ' + skill + ' when needed\n---\n# Public ' + skill + '\n')
        (root / 'base.md').write_bytes(b'# Base\r\nKeep original rules.\r\n')
        (root / 'install.py').write_text('raise AssertionError("must not execute")')
        return root

    def connect(self, **kwargs):
        return C.configure(self.instance, 'instance', 'vendor', self.package, ['base.md'], **kwargs)

    def test_no_connection_reads_no_package_and_creates_nothing(self):
        with patch.object(C, 'discover', side_effect=AssertionError('no scan')):
            got = C.load_connections(self.instance, self.project)
        self.assertEqual(got['status'], 'READY')
        self.assertEqual(got['connections'], [])
        self.assertFalse((self.instance / '.foundry').exists())

    def test_native_catalog_and_base_auto_load_selected_skill_only(self):
        self.connect()
        got = C.load_connections(self.instance, self.project)
        self.assertEqual(len(got['connections'][0]['catalog']['skills']), 2)
        self.assertEqual([m['kind'] for m in got['materials']], ['base'])
        got = C.load_connections(self.instance, self.project, ['instance.vendor:review'])
        self.assertEqual([m['kind'] for m in got['materials']], ['base', 'skill'])
        self.assertIn('\r\n', got['materials'][0]['text'])
        self.assertFalse(got['commands_executed'])
        self.assertFalse(got['model_load_verified'])

    def test_project_scope_and_no_target(self):
        C.configure(self.project, 'project', 'local', self.package)
        self.assertFalse(C.load_connections(self.instance)['connections'])
        self.assertEqual(len(C.load_connections(self.instance, self.project)['connections']), 1)
        other = self.root / 'other'; other.mkdir()
        self.assertFalse(C.load_connections(self.instance, other)['connections'])

    def test_reconnect_idempotent_disconnect_history_and_native_config_unchanged(self):
        native = self.project / '.provider-config'; native.mkdir()
        config = native / 'config.json'; config.write_text('{"enabled":false,"workflows":{"check":false}}')
        before = config.read_bytes()
        self.assertEqual(self.connect()['revision'], 1)
        self.assertEqual(self.connect()['revision'], 1)
        self.assertEqual(C.configure(self.instance, 'instance', 'vendor', enabled=False)['revision'], 2)
        self.assertFalse(C.load_connections(self.instance, self.project)['connections'])
        self.assertEqual(self.connect()['revision'], 3)
        self.assertEqual(config.read_bytes(), before)
        self.assertEqual(len(C.read_registry(self.instance / C.REGISTRY)['records']), 3)

    def test_source_drift_does_not_silently_refresh_and_old_record_survives(self):
        old = self.connect()
        (self.package / 'base.md').write_text('# Changed')
        got = C.load_connections(self.instance, self.project)
        self.assertEqual(got['status'], 'INCOMPLETE')
        self.assertFalse(got['connections'])
        self.assertFalse(C.check_binding(old))
        self.assertEqual(self.connect()['revision'], 2)
        self.assertEqual(C.read_registry(self.instance / C.REGISTRY)['records'][0], old)

    def test_missing_provider_retains_other_and_qualified_skill_names(self):
        self.connect()
        second = self.make_plugin('second')
        C.configure(self.project, 'project', 'other', second)
        shutil.rmtree(self.package)
        got = C.load_connections(self.instance, self.project, ['project.other:review'])
        self.assertEqual(got['status'], 'INCOMPLETE')
        self.assertEqual([b['catalog']['provider'] for b in got['connections']], ['second'])
        self.assertEqual(got['materials'][0]['kind'], 'skill')

    def test_same_provider_conflict_is_not_a_silent_override(self):
        self.connect(); C.configure(self.project, 'project', 'local', self.package)
        got = C.load_connections(self.instance, self.project)
        self.assertEqual(got['status'], 'INCOMPLETE')
        self.assertIn('already connected', got['diagnostics'][0]['message'])

    def test_root_alias_works_without_leaking_to_other_project(self):
        alias = self.root / 'alias'; alias.symlink_to(self.project, target_is_directory=True)
        C.configure(alias, 'project', 'local', self.package)
        self.assertEqual(C.load_connections(self.instance, self.project)['status'], 'READY')

    def test_local_zip_native_catalog_no_extract_no_plugin_call(self):
        archive = self.root / 'plugin.zip'
        with zipfile.ZipFile(archive, 'w') as out:
            for path in self.package.rglob('*'):
                if path.is_file(): out.write(path, 'bundle/' + path.relative_to(self.package).as_posix())
        a, raw = C.discover(archive, ['base.md'])
        b, _ = C.discover(self.package, ['base.md'])
        self.assertEqual(a, b)
        self.assertNotIn('install.py', raw)
        self.assertFalse((self.root / 'bundle').exists())

    def test_zip_missing_declared_skill_directory_keeps_previous_registration(self):
        self.connect()
        registry = self.instance / C.REGISTRY
        before = registry.read_bytes()
        archive = self.root / 'missing-skills.zip'
        for prefix in ['', 'bundle/']:
            for unrelated in ['other/readme.md', 'skills-other/review/SKILL.md', 'skills']:
                with self.subTest(prefix=prefix, unrelated=unrelated):
                    with zipfile.ZipFile(archive, 'w') as bundle:
                        bundle.writestr(prefix + '.codex-plugin/plugin.json', json.dumps(
                            {'name': 'provider', 'version': '1', 'skills': './skills/'}))
                        bundle.writestr(prefix + unrelated, 'Not the declared directory')
                    with self.assertRaisesRegex(ValueError, 'declared skills directory.*missing'):
                        C.discover(archive)
                    with self.assertRaisesRegex(ValueError, 'declared skills directory.*missing'):
                        C.configure(self.instance, 'instance', 'vendor', archive)
                    self.assertEqual(registry.read_bytes(), before)
                    self.assertFalse(registry.with_suffix('.lock').exists())
        self.assertEqual(C.load_connections(self.instance)['status'], 'READY')

    def test_zip_empty_skill_directory_and_undeclared_skills_remain_valid(self):
        archive = self.root / 'empty-skills.zip'
        for prefix in ['', 'bundle/']:
            for entry in ['skills/', 'skills/readme.md', None]:
                with self.subTest(prefix=prefix, entry=entry):
                    descriptor = {'name': 'empty-provider', 'version': '1'}
                    if entry is not None:
                        descriptor['skills'] = './skills/'
                    with zipfile.ZipFile(archive, 'w') as bundle:
                        bundle.writestr(prefix + '.codex-plugin/plugin.json', json.dumps(descriptor))
                        if entry is not None:
                            bundle.writestr(prefix + entry, '' if entry.endswith('/') else 'No Skills yet')
                    catalog, _ = C.discover(archive)
                    self.assertEqual(catalog['skills'], [])
                    C.configure(self.instance, 'instance', 'empty', archive)
                    got = C.load_connections(self.instance)
                    self.assertEqual(got['status'], 'READY')
                    self.assertEqual(len(got['connections']), 1)
                    self.assertFalse(got['materials'])
                    requested = C.load_connections(self.instance, skills=['instance.empty:absent'])
                    self.assertEqual(requested['diagnostics'][0]['code'], 'SKILL_UNAVAILABLE')

    def test_zip_directory_loss_isolated_and_restored_without_reconnecting(self):
        self.connect()
        archive = self.root / 'empty-provider.zip'
        descriptor = json.dumps({'name': 'empty-provider', 'version': '1', 'skills': './skills/'})
        with zipfile.ZipFile(archive, 'w') as bundle:
            bundle.writestr('bundle/.codex-plugin/plugin.json', descriptor)
            bundle.writestr('bundle/skills/', '')
        C.configure(self.instance, 'instance', 'empty', archive)
        original_zip = archive.read_bytes()
        other = self.make_plugin('other-provider')
        C.configure(self.project, 'project', 'other', other)
        requested = ['instance.vendor:review', 'project.other:review']
        before = C.load_connections(self.instance, self.project, requested)
        materials, _ = P.build_materials({'project_root': str(self.project), 'connections': {
            'instance_root': str(self.instance), 'skills': requested}}, self.root / 'prepared')
        registry_bytes = {p: p.read_bytes() for p in [self.instance / C.REGISTRY, self.project / C.REGISTRY]}
        with zipfile.ZipFile(archive, 'w') as bundle:
            bundle.writestr('bundle/.codex-plugin/plugin.json', descriptor)
        for skills in [requested, [*requested, 'instance.empty:review']]:
            with self.subTest(required=len(skills) == 3):
                got = C.load_connections(self.instance, self.project, skills)
                self.assertEqual(got['status'], 'INCOMPLETE')
                self.assertEqual([b['key'] for b in got['connections']], ['instance.vendor', 'project.other'])
                self.assertEqual(got['materials'], before['materials'])
                gap = next(d for d in got['diagnostics'] if d['code'] == 'CONNECTION_UNAVAILABLE')
                self.assertEqual(gap['id'], 'instance.empty')
                self.assertIn('declared skills directory', gap['message'])
                self.assertEqual(gap['severity'], 'ERROR' if len(skills) == 3 else 'WARNING')
                self.assertFalse(got['commands_executed'])
        self.assertEqual(P.check_selection(materials)['status'], 'CHANGED')
        archive.write_bytes(original_zip)
        self.assertEqual(C.load_connections(self.instance, self.project, requested), before)
        self.assertEqual(P.check_selection(materials)['status'], 'MATCH')
        self.assertEqual({p: p.read_bytes() for p in registry_bytes}, registry_bytes)

    def test_escape_material_and_skill_symlink_rejected(self):
        outside = self.root / 'outside.md'; outside.write_text('secret')
        (self.package / 'link.md').symlink_to(outside)
        with self.assertRaises(ValueError): C.discover(self.package, ['link.md'])
        with self.assertRaises(ValueError): C.discover(self.package, ['../outside.md'])
        (self.package / 'skills/init/SKILL.md').unlink()
        (self.package / 'skills/init/SKILL.md').symlink_to(outside)
        with self.assertRaises(ValueError): C.discover(self.package)

    def test_missing_selected_skill_is_diagnostic(self):
        self.connect()
        got = C.load_connections(self.instance, skills=['instance.vendor:absent'])
        self.assertEqual(got['diagnostics'][0]['code'], 'SKILL_UNAVAILABLE')
        self.assertEqual(len(got['connections']), 1)

    def test_native_manifest_and_private_checker_stay_separate(self):
        directory = self.root / 'cap'; directory.mkdir()
        (directory / 'capability.json').write_text(json.dumps({'name': 'cap', 'version': '1', 'materials': ['guide.md'], 'verification_files': ['secret.json']}))
        (directory / 'guide.md').write_text('Public')
        (directory / 'secret.json').write_text('{"answer":"PRIVATE"}')
        catalog, raw = C.discover(directory)
        self.assertNotIn('secret.json', raw)
        with self.assertRaises(ValueError): C.discover(directory, ['secret.json'])

    def test_material_preparation_captures_external_and_checks_old_binding_without_registry(self):
        self.connect()
        materials, files = P.build_materials({'project_root': str(self.project), 'connections': {'instance_root': str(self.instance), 'skills': ['instance.vendor:review']}}, self.root / 'out')
        self.assertEqual(materials['preparation']['readiness'], 'READY')
        self.assertEqual(len(materials['source_manifest']), 3)
        self.assertEqual(P.check_selection(materials)['status'], 'MATCH')
        self.assertFalse(materials['tool_bindings'])
        C.configure(self.instance, 'instance', 'vendor', enabled=False)
        self.assertEqual(P.check_selection(materials)['status'], 'MATCH')
        (self.package / 'base.md').write_text('Changed')
        self.assertEqual(P.check_selection(materials)['status'], 'CHANGED')
        self.assertTrue(any(b'Keep original rules' in v for v in files.values()))

    def test_builtin_external_mix_keeps_private_checker_and_source_task_bindings(self):
        from tests.test_capability_prepare import CapabilityPrepareTests
        fixture = CapabilityPrepareTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.connect()
        config = fixture.config
        config['connections'] = {'instance_root': str(self.instance), 'workpack_ids': ['MAKE-TEXT']}
        materials, files = P.build_materials(config, fixture.output)
        self.assertEqual(materials['preparation']['readiness'], 'READY')
        self.assertEqual(materials['preparation']['selections'][0]['name'], 'echo')
        self.assertEqual(len(materials['preparation']['external_connections']), 1)
        self.assertNotIn('INDEPENDENT-ONLY-812', '\n'.join(v.decode() for v in files.values()))
        self.assertTrue(any(i['id'].startswith('EXT-') for i in materials['request']['plan']['workpacks'][0]['inputs']))
        self.assertNotIn('document_review', materials['request'])

    def test_same_root_scope_registry_is_not_misclassified(self):
        self.connect()
        self.assertEqual(C.load_connections(self.instance, self.instance)['status'], 'READY')
        other = self.make_plugin('another')
        C.configure(self.instance, 'project', 'vendor', other)
        got = C.load_connections(self.instance, self.instance)
        self.assertEqual(got['status'], 'READY')
        self.assertEqual(len(got['connections']), 2)

    def test_private_checker_alias_cannot_become_base_material(self):
        directory = self.root / 'cap'; directory.mkdir()
        (directory / 'capability.json').write_text(json.dumps({'name': 'cap', 'version': '1', 'materials': ['alias.json'], 'verification_files': ['secret.json']}))
        (directory / 'secret.json').write_text('{"private":1}')
        (directory / 'alias.json').symlink_to(directory / 'secret.json')
        with self.assertRaisesRegex(ValueError, 'private checker'): C.discover(directory)

    def test_connections_preserve_preexisting_rsi_handoff_and_budget_metadata(self):
        from tests.test_capability_prepare import CapabilityPrepareTests
        fixture = CapabilityPrepareTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.connect()
        config = fixture.config
        preserved = {'case_id': 'existing', 'consumed': 2, 'reviewed': 'pending'}
        config['base_materials']['preparation']['rsi_handoff'] = preserved.copy()
        config['connections'] = {'instance_root': str(self.instance), 'workpack_ids': ['MAKE-TEXT']}
        result, _ = P.build_materials(config, fixture.output)
        self.assertEqual(result['preparation']['rsi_handoff'], preserved)
        self.assertEqual(result['scope']['max_attempts'], config['base_materials']['scope']['max_attempts'])
        self.assertFalse(result['preparation']['commands_executed'])

    def test_second_preparation_reuses_binding_and_sources_then_adds_only_selected_skill(self):
        from tests.test_capability_prepare import CapabilityPrepareTests
        fixture = CapabilityPrepareTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.connect()
        config = fixture.config
        config['connections'] = {'instance_root': str(self.instance), 'workpack_ids': ['MAKE-TEXT']}
        first = P.write_materials(config, fixture.output)
        previous = json.dumps(first, sort_keys=True)
        second_config = {'project_root': str(fixture.project), 'source_root': str(fixture.output / 'sources'),
                         'base_materials': first, 'connections': config['connections']}
        second, _ = P.build_materials(second_config, fixture.root / 'second')
        self.assertEqual(second['preparation']['external_connections'], first['preparation']['external_connections'])
        self.assertEqual(second['source_manifest'], first['source_manifest'])
        self.assertEqual(second['request']['plan']['workpacks'][0]['inputs'], first['request']['plan']['workpacks'][0]['inputs'])
        second_config['connections'] = {**config['connections'], 'skills': ['instance.vendor:review']}
        extended, _ = P.build_materials(second_config, fixture.root / 'extended')
        self.assertEqual(len(extended['source_manifest']), len(first['source_manifest']) + 1)
        self.assertEqual(json.dumps(first, sort_keys=True), previous)
        self.assertEqual(extended['preparation']['selections'], first['preparation']['selections'])

    def test_unrequested_catalog_gap_does_not_block_builtin_but_required_skill_does(self):
        from tests.test_capability_prepare import CapabilityPrepareTests
        fixture = CapabilityPrepareTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        C.configure(self.instance, 'instance', 'optional', self.package)
        shutil.rmtree(self.package)
        config = fixture.config
        config['connections'] = {'instance_root': str(self.instance), 'workpack_ids': ['MAKE-TEXT']}
        materials, _ = P.build_materials(config, fixture.output)
        self.assertEqual(materials['preparation']['readiness'], 'READY')
        gap = next(d for d in materials['preparation']['diagnostics'] if d['code'] == 'CONNECTION_UNAVAILABLE')
        self.assertEqual(gap['severity'], 'WARNING')
        self.assertEqual(materials['preparation']['external_connections'], [])
        config['connections']['skills'] = ['instance.optional:review']
        required, _ = P.build_materials(config, fixture.output)
        self.assertEqual(required['preparation']['readiness'], 'INCOMPLETE')
        self.assertTrue(any(d['code'] == 'SKILL_UNAVAILABLE' for d in required['preparation']['diagnostics']))

    def test_actual_cli_restart_uses_persisted_catalog(self):
        args = [sys.executable, '-I', '-S', '-B', str(HELPERS / 'connections.py')]
        run = subprocess.run([*args, 'connect', '--root', str(self.instance), '--scope', 'instance', '--id', 'vendor', '--source', str(self.package)], capture_output=True, text=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
        run = subprocess.run([*args, 'load', '--instance-root', str(self.instance), '--skill', 'instance.vendor:review'], capture_output=True, text=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
        self.assertEqual(json.loads(run.stdout)['materials'][0]['kind'], 'skill')

    def test_generic_package_contains_and_runs_connection_entry_in_isolation(self):
        spec = importlib.util.spec_from_file_location('connection_packager', ROOT / 'devtools/package_generic_release.py')
        packager = importlib.util.module_from_spec(spec); spec.loader.exec_module(packager)
        archive = self.root / 'candidate.zip'; packager.package(archive)
        extracted = self.root / 'delivery'
        with zipfile.ZipFile(archive) as data: data.extractall(extracted)
        entry = extracted / 'examples/capability-adapters/connections.py'
        self.assertEqual(entry.read_bytes(), (HELPERS / 'connections.py').read_bytes())
        run = subprocess.run([sys.executable, '-I', '-S', '-B', str(entry), 'load', '--instance-root', str(extracted)], cwd=self.root, capture_output=True, text=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(json.loads(run.stdout)['connections'], [])
        self.assertIn('CONNECTIONS.md', (extracted / '.agents/skills/harness-foundry-build/SKILL.md').read_text())


if __name__ == '__main__': unittest.main()
